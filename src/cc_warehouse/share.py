"""ccw share: sanitized static-site export (slice 11). DESIGN section 9.

Sanitization runs on COPIES at share time. Redaction operates on the PARSED content of
each JSONL line (json-decoded, so a `\\uXXXX`-escaped or non-ASCII secret cannot slip
past), then the SAME renderer that produces personal projections renders the sanitized
copy (R9), so nothing sensitive survives in the HTML copy-as-markdown payloads. The raw
store objects and the personal projections stay full fidelity (R4).

This slice writes the sanitized site into an explicit --out directory and deletes
nothing (write_projection overwrites only its own five files; it never prunes). The R4
shares-rebuild deletion authority activates when the warehouse shares/ space and
`ccw build --rebuild` regeneration land in a later slice.
"""

import html
import json
import os
import re
import shutil
import socket
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from cc_warehouse import build, catalog, render, store
from cc_warehouse.config import Config

_TOKEN = "[REDACTED]"
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Secret-shaped strings are DETECTED, never auto-redacted: a share containing one aborts
# unless --allow-findings (auto-mangling a token in a conversation ABOUT tokens would
# corrupt legitimate content, DESIGN section 9). The set is broad (operator decision):
# known key families plus a generic high-entropy token heuristic.
_SECRET_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("pem-private-key", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
)
# Generic high-entropy token: base64 / base64url alphabets (incl. -_ per URL-safe
# tokens), length >= 40. Slash is deliberately excluded so long filesystem paths do not
# mass-trigger. A pure-hex digest at a git/sha length is not a secret (see below).
_GENERIC_TOKEN_RE = re.compile(r"[A-Za-z0-9+_=-]{40,}")
_HEX_RE = re.compile(r"[0-9a-fA-F]+")


@dataclass(frozen=True)
class RedactionHit:
    pattern: str
    file: str
    line: int
    replacement: str


@dataclass(frozen=True)
class ShareReport:
    out_dir: Path
    hits: tuple[RedactionHit, ...]
    findings: tuple[RedactionHit, ...]  # secret-shaped detections; abort unless allowed
    skipped: tuple[str, ...] = ()  # session keys with no current/visible head (R10)
    errored: tuple[str, ...] = ()  # sessions whose object could not be read/written


@dataclass(frozen=True)
class _Resolved:
    """A session to share, reduced to catalog fields (no cross-module private type)."""

    short: str
    hash: str
    label: str
    slug: str | None
    first_ts: str | None


def _custom_patterns(config: Config) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Compile [share].redact_patterns as regexes (R5/F7).

    Values come from load_config, so DESIGN 8's layering applies (XDG file, then data-root
    file, then per-project). This module used to parse `<root>/config.toml` itself, which
    was a second implementation of one behaviour (R9/F8) and meant a pattern declared in
    the XDG tier was INVISIBLE here. That is the worst shape this defect can take: share
    is the one outward-facing command, so a redaction rule the operator had set was
    silently ignored and the content it named was published.

    A pattern that fails to compile, or a degenerate one that matches the empty string
    (which would insert a token between every character and corrupt the payload),
    contributes nothing rather than crashing, so one bad entry never breaks a whole share.
    Proven by tests/test_share_regressions.py::
    test_redact_patterns_from_the_xdg_config_are_applied and
    ::test_degenerate_custom_regex_does_not_corrupt.
    """
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for entry in config.redact_patterns:
        if not entry:
            continue
        try:
            pat = re.compile(entry)
        except re.error:
            continue
        compiled.append((entry, pat))
    return tuple(compiled)


def _builtin_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Home dir, username, hostname (from the environment), and email.

    The home dir is matched as a literal path. Username and hostname are matched at word
    boundaries so a short login ("bob") is still redacted where it stands alone without
    shredding it out of unrelated words (F9 vs over-redaction). An empty value yields no
    pattern. The current-process environment is the identity source this slice redacts
    (the frozen decision); per-session origin identity is a later enhancement.
    """
    patterns: list[tuple[str, re.Pattern[str]]] = [("email", _EMAIL_RE)]
    home = os.environ.get("HOME")
    if home:
        patterns.append(("home-dir", re.compile(re.escape(home))))
    for label, value in (("username", os.environ.get("USER")), ("hostname", socket.gethostname())):
        if value:
            patterns.append((label, re.compile(r"\b" + re.escape(value) + r"\b")))
    return tuple(patterns)


def _redaction_patterns(config: Config) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """All patterns most-specific-first: custom, then email, home, username, hostname.

    Ordering matters where patterns overlap (a username is a substring of an email); the
    more specific match is applied and attributed first.
    """
    return _custom_patterns(config) + _builtin_patterns()


def _redact_value(
    value: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    source: str,
    lineno: int,
    hits: list[RedactionHit],
) -> str:
    """Redact every non-empty pattern match in one string, recording a hit per match.

    A zero-width match (a degenerate pattern like `x*` or `\\b`) is skipped so it can
    never insert a token between characters and corrupt content. The token contains no
    character any pattern here matches, so redaction is idempotent.
    """
    for label, pat in patterns:
        out: list[str] = []
        last = 0
        count = 0
        for match in pat.finditer(value):
            if match.start() == match.end():
                continue
            out.append(value[last : match.start()])
            out.append(_TOKEN)
            last = match.end()
            count += 1
        if count:
            out.append(value[last:])
            value = "".join(out)
            hits.extend(
                RedactionHit(pattern=label, file=source, line=lineno, replacement=_TOKEN)
                for _ in range(count)
            )
    return value


def _redact_tree(
    node: object,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    source: str,
    lineno: int,
    hits: list[RedactionHit],
) -> object:
    """Redact every string VALUE in a decoded JSON structure (keys are structural)."""
    if isinstance(node, str):
        return _redact_value(node, patterns, source, lineno, hits)
    if isinstance(node, list):
        items = cast(list[object], node)
        return [_redact_tree(item, patterns, source, lineno, hits) for item in items]
    if isinstance(node, dict):
        return {
            key: _redact_tree(val, patterns, source, lineno, hits)
            for key, val in cast(dict[str, object], node).items()
        }
    return node


def _redact(
    text: str, source: str, patterns: tuple[tuple[str, re.Pattern[str]], ...]
) -> tuple[str, list[RedactionHit]]:
    """Redact the JSONL payload on its PARSED content, preserving one line per entry.

    Each line is json-decoded and its string values redacted, so a `\\uXXXX`-escaped or
    non-ASCII secret is caught (it is a literal string once decoded) and the re-serialized
    line, read back by the renderer, carries only redacted content. A line that is not
    valid JSON (a malformed line the parser would count as loss) is redacted as raw text
    rather than dropped. Line numbers match the parser's utf-8-sig line split.
    """
    out_lines: list[str] = []
    hits: list[RedactionHit] = []
    for lineno, line in enumerate(text.splitlines(keepends=True), start=1):
        body = line.rstrip("\n")
        newline = line[len(body) :]
        if not body.strip():
            out_lines.append(line)
            continue
        try:
            decoded = cast(object, json.loads(body))
        except json.JSONDecodeError:
            out_lines.append(_redact_value(body, patterns, source, lineno, hits) + newline)
            continue
        redacted = _redact_tree(decoded, patterns, source, lineno, hits)
        out_lines.append(json.dumps(redacted, ensure_ascii=False) + newline)
    return "".join(out_lines), hits


def _redact_display(value: str, patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> str:
    """Redact a catalog-derived display string (slug/label); no hit recording.

    The catalog is a second source separate from the payload, so a slug or label shown in
    the index or used as a path segment is sanitized with the same patterns (F9).
    """
    return _redact_value(value, patterns, "", 0, [])


def _is_generic_secret(candidate: str) -> bool:
    """A long token counts as secret-shaped unless it is a plain hex digest.

    git object ids (7-40 hex) and sha256 digests (64 hex) are pervasive in these
    transcripts and are not secrets; a hex string of any other length (e.g. a 128-hex
    secret_key_base) is not excluded. A real base64 token mixes letters and digits.
    """
    if _HEX_RE.fullmatch(candidate) and (7 <= len(candidate) <= 40 or len(candidate) == 64):
        return False
    has_alpha = any(c.isalpha() for c in candidate)
    has_digit = any(c.isdigit() for c in candidate)
    return has_alpha and has_digit


def _mask(value: str) -> str:
    return value[:6] + "..." if len(value) > 8 else "..."


def _scan_secrets(text: str, source: str) -> list[RedactionHit]:
    """Detect secret-shaped strings in the (already-redacted) text. Never mutates."""
    findings: list[RedactionHit] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for label, pat in _SECRET_RES:
            findings.extend(
                RedactionHit(pattern=label, file=source, line=lineno, replacement=_mask(m))
                for m in pat.findall(line)
            )
        for token in _GENERIC_TOKEN_RE.findall(line):
            if _is_generic_secret(token):
                findings.append(
                    RedactionHit(
                        pattern="high-entropy-token",
                        file=source,
                        line=lineno,
                        replacement=_mask(token),
                    )
                )
    return findings


def _index_html(entries: list[tuple[str, str]]) -> str:
    """A minimal self-contained index listing each shared session (multi-session gets
    one index, DESIGN section 9). Navigation only, not a second conversation renderer
    (R9); display strings are already redacted and are escaped via stdlib html.escape."""
    items = "\n".join(
        f'  <li><a href="{html.escape(href, quote=True)}">{html.escape(title)}</a></li>'
        for href, title in entries
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Shared sessions</title>\n"
        "</head>\n"
        "<body>\n"
        "<h1>Shared sessions</h1>\n"
        "<ul>\n"
        f"{items}\n"
        "</ul>\n"
        "</body>\n"
        "</html>\n"
    )


def _resolve(root: Path, sessions: tuple[str, ...]) -> tuple[list[_Resolved], list[str]]:
    """Map each s:<short> key to a current, visible head; the rest are skipped (R10).

    A missing, superseded, or hidden short all resolve to no head and are named as
    skipped rather than aborting the batch (operator decision, skip-and-continue).
    """
    resolved: list[_Resolved] = []
    skipped: list[str] = []
    conn = catalog.open_catalog(root)
    try:
        for key in sessions:
            short = key[2:] if key.startswith("s:") else key
            head = build.head_for_short(conn, short)
            if head is None:
                skipped.append(key)
                continue
            resolved.append(
                _Resolved(
                    short=head.short,
                    hash=head.hash,
                    label=head.label,
                    slug=head.slug,
                    first_ts=head.first_ts,
                )
            )
    finally:
        conn.close()
    return resolved, skipped


def share(
    config: Config,
    sessions: tuple[str, ...],
    out_dir: Path,
    *,
    allow_findings: bool = False,
) -> ShareReport:
    """Build the sanitized share site for the given s:<short> keys; multi-session gets
    one index. Secret-shaped strings abort the whole share (no pages written) unless
    allow_findings ships them verbatim. Redaction runs on the parsed payload before the
    shared renderer, so nothing sensitive survives in the copy-as-markdown payloads.
    """
    root = config.root
    patterns = _redaction_patterns(config)
    resolved, skipped = _resolve(root, sessions)

    # Phase 1: redact + scan every session in memory, writing nothing yet.
    prepared: list[tuple[_Resolved, bytes]] = []
    all_hits: list[RedactionHit] = []
    all_findings: list[RedactionHit] = []
    errored: list[str] = []
    for item in resolved:
        try:
            data = store.get(root, item.hash)
        except OSError:
            errored.append(f"s:{item.short}")  # store read failure is not a not-found
            continue
        text = data.decode("utf-8-sig", errors="replace")
        redacted_text, hits = _redact(text, item.short, patterns)
        all_hits.extend(hits)
        all_findings.extend(_scan_secrets(redacted_text, item.short))
        prepared.append((item, redacted_text.encode("utf-8")))

    # A secret finding is a safety gate, not an item failure: abort the whole share and
    # write nothing (index.html is a page too, so it stays off disk).
    if all_findings and not allow_findings:
        return ShareReport(
            out_dir=out_dir,
            hits=tuple(all_hits),
            findings=tuple(all_findings),
            skipped=tuple(skipped),
            errored=tuple(errored),
        )

    # Phase 2: write the sanitized copies, the index, and the report (all atomic, R2).
    out_dir.mkdir(parents=True, exist_ok=True)
    # Fixed policy: shares ignore personal render overrides, and hljs is INLINED so a
    # published page makes no third-party request (DESIGN 15 item 8, principal
    # 2026-07-24). Redaction protects the content; this protects the reader.
    options = render.RenderOptions(hljs="inline")
    index_entries: list[tuple[str, str]] = []
    for item, redacted_bytes in prepared:
        label = _redact_display(item.label, patterns)
        slug = _redact_display(item.slug or "session", patterns)
        first_ts = item.first_ts if item.first_ts and _DATE_RE.match(item.first_ts) else None
        # Reuse build's projection naming (R9); build sanitizes each path segment.
        subdir = build.projection_dir(out_dir, label, first_ts, slug, item.short)
        try:
            build.write_projection(subdir, redacted_bytes, options, force=True)
        except OSError:
            errored.append(f"s:{item.short}")  # a write failure, not a not-found
            continue
        href = f"{subdir.relative_to(out_dir).as_posix()}/conversation.html"
        index_entries.append((href, slug or item.short))

    store.atomic_write(out_dir / "index.html", _index_html(index_entries).encode("utf-8"))
    report_bytes = (json.dumps([asdict(h) for h in all_hits], indent=2) + "\n").encode("utf-8")
    store.atomic_write(out_dir / "redaction-report.json", report_bytes)

    return ShareReport(
        out_dir=out_dir,
        hits=tuple(all_hits),
        findings=tuple(all_findings),
        skipped=tuple(skipped),
        errored=tuple(errored),
    )


# ---------------------------------------------------------------------------
# --EXPOSED: publish UNSCRUBBED content, gated by a scrubbed-vs-exposed
# comparison (DESIGN section 9 amendment, principal-approved 2026-07-23). The
# whole flow lives here (a delete-sanctioned module) so the staging->final move
# stays out of cli.py. The CLI orchestrates the consent gate; this module never
# writes to the caller's real --out until commit_comparison is called.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SiteComparison:
    """The two staged sites plus the byte-size / redaction data the --EXPOSED
    gate shows the operator before they decide."""

    staging_root: Path  # the temp parent; removed by commit/discard
    scrubbed_dir: Path
    exposed_dir: Path
    per_session: tuple[tuple[str, int, int], ...]  # (label, scrubbed_bytes, exposed_bytes)
    hits: tuple[RedactionHit, ...]
    findings: tuple[RedactionHit, ...]
    skipped: tuple[str, ...]
    errored: tuple[str, ...]


def _write_site_entry(
    out_root: Path,
    item: _Resolved,
    payload: bytes,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    index: list[tuple[str, str]],
    *,
    redact_names: bool,
) -> int:
    """Render one session's projection into `out_root`; return the total bytes of
    its files. `redact_names` sanitizes the label/slug path segments (scrubbed
    site) or leaves them raw (exposed site)."""
    if redact_names:
        label = _redact_display(item.label, patterns)
        slug = _redact_display(item.slug or "session", patterns)
    else:
        label = item.label
        slug = item.slug or "session"
    first_ts = item.first_ts if item.first_ts and _DATE_RE.match(item.first_ts) else None
    subdir = build.projection_dir(out_root, label, first_ts, slug, item.short)
    build.write_projection(subdir, payload, render.RenderOptions(hljs="inline"), force=True)
    href = f"{subdir.relative_to(out_root).as_posix()}/conversation.html"
    index.append((href, slug or item.short))
    return sum(f.stat().st_size for f in subdir.iterdir() if f.is_file())


def _write_site_index(
    out_dir: Path, entries: list[tuple[str, str]], hits: tuple[RedactionHit, ...]
) -> None:
    store.atomic_write(out_dir / "index.html", _index_html(entries).encode("utf-8"))
    report = (json.dumps([asdict(h) for h in hits], indent=2) + "\n").encode("utf-8")
    store.atomic_write(out_dir / "redaction-report.json", report)


def prepare_comparison(config: Config, sessions: tuple[str, ...]) -> SiteComparison:
    """Render BOTH a scrubbed and an exposed (UN-redacted) site into a private
    temp staging area so the --EXPOSED gate can compare them. The caller's real
    --out is untouched until commit_comparison; discard_comparison removes the
    staging area if the operator aborts."""
    root = config.root
    patterns = _redaction_patterns(config)
    resolved, skipped = _resolve(root, sessions)
    staging_root = Path(tempfile.mkdtemp(prefix="ccw-exposed-"))
    scrubbed_dir = staging_root / "SCRUBBED"
    exposed_dir = staging_root / "EXPOSED"
    scrubbed_dir.mkdir(parents=True, exist_ok=True)
    exposed_dir.mkdir(parents=True, exist_ok=True)
    per_session: list[tuple[str, int, int]] = []
    all_hits: list[RedactionHit] = []
    all_findings: list[RedactionHit] = []
    errored: list[str] = []
    scrub_index: list[tuple[str, str]] = []
    exposed_index: list[tuple[str, str]] = []
    for item in resolved:
        try:
            data = store.get(root, item.hash)
        except OSError:
            errored.append(f"s:{item.short}")
            continue
        text = data.decode("utf-8-sig", errors="replace")
        redacted_text, hits = _redact(text, item.short, patterns)
        all_hits.extend(hits)
        all_findings.extend(_scan_secrets(redacted_text, item.short))
        s_bytes = _write_site_entry(
            scrubbed_dir, item, redacted_text.encode("utf-8"), patterns, scrub_index,
            redact_names=True,
        )
        e_bytes = _write_site_entry(
            exposed_dir, item, data, patterns, exposed_index, redact_names=False,
        )
        per_session.append((item.slug or item.short, s_bytes, e_bytes))
    _write_site_index(scrubbed_dir, scrub_index, tuple(all_hits))
    _write_site_index(exposed_dir, exposed_index, ())  # exposed = nothing redacted
    return SiteComparison(
        staging_root=staging_root,
        scrubbed_dir=scrubbed_dir,
        exposed_dir=exposed_dir,
        per_session=tuple(per_session),
        hits=tuple(all_hits),
        findings=tuple(all_findings),
        skipped=tuple(skipped),
        errored=tuple(errored),
    )


def commit_comparison(comparison: SiteComparison, out_dir: Path, *, keep_exposed: bool) -> None:
    """Move the chosen staged site(s) into the final `out_dir` under labelled
    subdirs after the operator consents, then remove the staging area. `SCRUBBED/`
    always lands; `EXPOSED/` only when keep_exposed (the operator typed EXPOSED).
    A pre-existing SCRUBBED/ or EXPOSED/ from a prior share is replaced (R4:
    shares-rebuild deletion authority)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    _replace_dir(comparison.scrubbed_dir, out_dir / "SCRUBBED")
    if keep_exposed:
        _replace_dir(comparison.exposed_dir, out_dir / "EXPOSED")
    report = (json.dumps([asdict(h) for h in comparison.hits], indent=2) + "\n").encode("utf-8")
    store.atomic_write(out_dir / "redaction-report.json", report)
    shutil.rmtree(comparison.staging_root, ignore_errors=True)


def discard_comparison(comparison: SiteComparison) -> None:
    """Remove the staging area without publishing anything (the operator aborted)."""
    shutil.rmtree(comparison.staging_root, ignore_errors=True)


def _replace_dir(src: Path, dest: Path) -> None:
    """Move `src` onto `dest`, replacing any prior directory there. Both are share
    output dirs (R4 shares-rebuild), never the store or a source."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(src), str(dest))
