"""Contract-derived regression tests for ccw share (slice 11).

Written from DESIGN section 9 + FINDINGS F6/F7/F9 (not ported from the implementation)
to pin the confirmed reviewer findings of the slice-11 loop so they cannot regress:

- B1 (F6): redaction/detection must see the DECODED content, so a `\\uXXXX`-escaped or
  non-ASCII secret/PII cannot slip past raw-text matching and reappear in the share.
- B5 (F9): a hostile payload timestamp must not let a shared directory escape --out.
- B2/B4 (F6): a long non-git hex secret and a base64url token are secret-shaped.
- B7 (F7): a degenerate custom regex must not corrupt content.
- B9 (F9): a short username is still redacted, at a word boundary, not shredded.
- A1 (F9): share refuses a populated, unrecognized --out rather than overwrite it.
- A3 (F7): an unreadable stored object is reported as an error, not a benign not-found.
"""

import hashlib
from pathlib import Path
from typing import cast

from conftest import (
    basic_session,
    catalog_rows,
    entry,
    hook_payload,
    jsonl,
    run_ccw,
    warehouse_root,
    write_transcript,
)


def capture_and_short(env: dict[str, str], data: bytes, **kwargs: str) -> str:
    transcript = write_transcript(env, data, **kwargs)  # type: ignore[arg-type]
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, cwd=None))
    assert result.code == 0, result.err
    digest = hashlib.sha256(data).hexdigest()
    rows = cast(
        list[tuple[object, ...]],
        catalog_rows(env, "SELECT short FROM session WHERE hash = ?", [digest]),
    )
    return f"s:{cast(str, rows[0][0])}"


def out_texts(out: Path) -> dict[Path, str]:
    return {
        p: p.read_text(errors="replace")
        for p in out.rglob("*")
        if p.is_file() and p.suffix in {".html", ".md"}
    }


def test_redact_patterns_from_the_xdg_config_are_applied(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """DESIGN 8 layering reaches share's redaction rules (found closing ticket 12b).

    `share.py` parsed `<root>/config.toml` itself instead of taking values from
    load_config, so a `[share] redact_patterns` entry declared in the XDG tier was
    invisible to it. The consequence is the worst shape this defect can take: share is
    the one outward-facing command, so a redaction rule the operator set was silently
    ignored and the content it named was PUBLISHED.
    """
    marker = "ACME-INTERNAL-4242"
    data = basic_session(prompt=f"the code is {marker} do not share")
    short = capture_and_short(ccw_env, data)

    # Declared ONLY in the XDG tier; the data-root file names no [share] section.
    warehouse_root(ccw_env).mkdir(parents=True, exist_ok=True)
    (warehouse_root(ccw_env) / "config.toml").write_text("[notify]\nopen_folder = false\n")
    xdg = Path(ccw_env["HOME"]) / ".config" / "cc-warehouse"
    xdg.mkdir(parents=True, exist_ok=True)
    (xdg / "config.toml").write_text('[share]\nredact_patterns = ["ACME-INTERNAL-[0-9]+"]\n')

    out = tmp_path / "site"
    result = run_ccw(["share", short, "--out", str(out)], ccw_env)
    assert result.code == 0, result.err
    for path, text in out_texts(out).items():
        assert marker not in text, f"an XDG-declared redaction pattern was ignored: {path}"


def test_share_does_not_parse_config_files_itself(ccw_env: dict[str, str]) -> None:
    """R9/F8 fence: config.py owns config parsing. A second reader is exactly how the
    layering silently diverged here and in relocate, so pin the absence of one."""
    from cc_warehouse import share as share_mod

    source = Path(share_mod.__file__).read_text()
    assert "tomllib" not in source, "share.py parses config.toml itself again"


def test_unicode_escaped_secret_is_detected_and_aborts(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A secret written as JSON \\uXXXX escapes decodes to sk-ant-... in the render, so
    it must be detected on the decoded content and abort the share (F6)."""
    token_plain = "sk-ant-api03-" + "a1" * 20
    escaped = "\\u0073k-ant-api03-" + "a1" * 20  # s == 's'
    sid = "aaaaaaaa-1111-2222-3333-444444444444"
    raw_user = (
        '{"type":"user","timestamp":"2026-01-05T10:00:00.000Z","sessionId":"'
        + sid
        + '","cwd":"/home/alice/projects/widget","message":{"role":"user",'
        + '"content":"my key is '
        + escaped
        + '"}}'
    )
    data = jsonl(
        raw_user,
        entry("assistant", "Noted.", "2026-01-05T10:00:05.000Z", session_id=sid),
    )
    short = capture_and_short(ccw_env, data, session_id=sid)
    out = tmp_path / "site"
    result = run_ccw(["share", short, "--out", str(out)], ccw_env)
    assert result.code != 0, "escaped secret slipped past detection"
    assert not out_texts(out), "wrote pages despite an escaped secret"

    result = run_ccw(["share", short, "--out", str(out), "--allow-findings"], ccw_env)
    assert result.code == 0, result.err
    assert token_plain in "".join(out_texts(out).values())


def test_non_ascii_custom_pattern_redacted_on_decoded_content(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A non-ASCII custom pattern is stored as \\uXXXX in the payload; redaction must
    still catch it because it runs on the decoded string (F6/F9)."""
    root = warehouse_root(ccw_env)
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_text('[share]\nredact_patterns = ["café-token-XYZ"]\n')
    data = jsonl(
        entry("user", "the value is café-token-XYZ here", "2026-01-05T10:00:00.000Z"),
        entry("assistant", "ok", "2026-01-05T10:00:05.000Z"),
    )
    short = capture_and_short(ccw_env, data)
    out = tmp_path / "site"
    result = run_ccw(["share", short, "--out", str(out)], ccw_env)
    assert result.code == 0, result.err
    shared = out_texts(out)
    assert shared, "no pages produced"
    for path, text in shared.items():
        assert "café-token-XYZ" not in text, f"non-ASCII custom value leaked into {path}"


def test_hostile_timestamp_cannot_escape_out(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """A payload timestamp containing path separators must not place a shared directory
    outside --out (F9 path traversal)."""
    sid = "bbbbbbbb-1111-2222-3333-444444444444"
    data = jsonl(
        entry("user", "hello", "../../../pwned-2026", session_id=sid),
        entry("assistant", "hi", "../../../pwned-2027", session_id=sid),
    )
    short = capture_and_short(ccw_env, data, session_id=sid)
    out = tmp_path / "guarded" / "site"
    result = run_ccw(["share", short, "--out", str(out)], ccw_env)
    assert result.code == 0, result.err
    assert (out / "index.html").exists()
    # Nothing may be written above --out.
    assert not (tmp_path / "pwned-2026").exists()
    assert not (out.parent / "pwned-2026").exists()
    for p in out.rglob("*"):
        assert out in p.parents or p == out, f"{p} escaped {out}"


def test_long_hex_secret_detected_but_git_sha_is_not(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A 128-hex secret_key_base is secret-shaped; a 40-hex git sha is not, so it must
    not falsely abort an otherwise clean share (F6, broad detector with hex carve-out)."""
    secret_key_base = "a3f5" * 32  # 128 hex chars
    data = jsonl(
        entry("user", f"secret_key_base = {secret_key_base}", "2026-01-05T10:00:00.000Z"),
        entry("assistant", "ok", "2026-01-05T10:00:05.000Z"),
    )
    short = capture_and_short(ccw_env, data)
    out = tmp_path / "site"
    assert run_ccw(["share", short, "--out", str(out)], ccw_env).code != 0

    git_sha = "deadbeef" * 5  # 40 hex chars, a plausible git object id
    sid = "cccccccc-1111-2222-3333-444444444444"
    data2 = jsonl(
        entry("user", f"see commit {git_sha}", "2026-01-05T10:00:00.000Z", session_id=sid),
        entry("assistant", "ok", "2026-01-05T10:00:05.000Z", session_id=sid),
    )
    short2 = capture_and_short(
        ccw_env, data2, session_id=sid, encoded_dir="-home-alice-projects-two"
    )
    out2 = tmp_path / "site2"
    assert run_ccw(["share", short2, "--out", str(out2)], ccw_env).code == 0


def test_base64url_token_is_secret_shaped(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """A high-entropy base64url token (with - and _) is secret-shaped (F6)."""
    token = "Ab3-cD_ef9Gh1jK2lM3nO4pQ5rS6tU7vW8xY9zAb0cD"  # 43 chars, base64url
    data = jsonl(
        entry("user", f"refresh token: {token}", "2026-01-05T10:00:00.000Z"),
        entry("assistant", "ok", "2026-01-05T10:00:05.000Z"),
    )
    short = capture_and_short(ccw_env, data)
    out = tmp_path / "site"
    assert run_ccw(["share", short, "--out", str(out)], ccw_env).code != 0


def test_degenerate_custom_regex_does_not_corrupt(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A zero-width custom pattern must be inert, not insert a token between every
    character and shred the payload (F7 conservative)."""
    root = warehouse_root(ccw_env)
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_text('[share]\nredact_patterns = ["x*"]\n')
    data = jsonl(
        entry("user", "the quick brown widget hops", "2026-01-05T10:00:00.000Z"),
        entry("assistant", "acknowledged", "2026-01-05T10:00:05.000Z"),
    )
    short = capture_and_short(ccw_env, data)
    out = tmp_path / "site"
    result = run_ccw(["share", short, "--out", str(out)], ccw_env)
    assert result.code == 0, result.err
    joined = "".join(out_texts(out).values())
    assert "quick brown widget" in joined, "content was corrupted by a zero-width pattern"
    assert "[REDACTED]" not in joined or joined.count("[REDACTED]") < 5


def test_short_username_redacted_at_word_boundary(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The username (USER=alice) is redacted where it stands alone but is not shredded
    out of an unrelated word like 'malice' (F9 vs over-redaction, word boundary)."""
    data = jsonl(
        entry("user", "authored by alice and the malice module", "2026-01-05T10:00:00.000Z"),
        entry("assistant", "ok", "2026-01-05T10:00:05.000Z"),
    )
    short = capture_and_short(ccw_env, data)
    out = tmp_path / "site"
    result = run_ccw(["share", short, "--out", str(out)], ccw_env)
    assert result.code == 0, result.err
    convo = "".join(t for p, t in out_texts(out).items() if p.name != "index.html")
    assert "by alice and" not in convo, "standalone username leaked into a page"
    assert "malice" in convo, "'malice' was over-redacted"


def test_share_refuses_populated_unrecognized_out(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """--out that is populated and not a prior share is refused, so a stray path never
    overwrites unrelated files (F9)."""
    out = tmp_path / "not-a-share"
    out.mkdir()
    (out / "important.txt").write_text("keep me")
    short = capture_and_short(ccw_env, basic_session())
    result = run_ccw(["share", short, "--out", str(out)], ccw_env)
    assert result.code != 0
    assert (out / "important.txt").read_text() == "keep me"
    assert not out_texts(out), "wrote into an unrecognized populated dir"


def test_share_out_cannot_be_pointed_inside_the_warehouse_store(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F9: `ccw render <path> --out` already refuses a target inside the warehouse's
    own objects/ or projections/ (`cli._out_under_warehouse`, used by `_render_adhoc`) -
    `ccw share --out` never got the same guard, so it could write straight into the
    store it is supposed to never touch (found by the 2026-08-23 architecture
    re-review). `force=True` at both of share.py's `write_projection` call sites makes
    this a real overwrite risk, not just an unwanted extra file."""
    short = capture_and_short(ccw_env, basic_session())
    target = warehouse_root(ccw_env) / "objects" / "shouldnt-write-here"
    result = run_ccw(["share", short, "--out", str(target)], ccw_env)
    assert result.code != 0, result.out + result.err
    assert not target.exists(), "share wrote inside the warehouse store"


def test_unreadable_object_reported_as_error_not_not_found(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A stored object that cannot be read is an error, never relabeled as a benign
    'no current session' (F7 conservative branch)."""
    data = basic_session()
    short = capture_and_short(ccw_env, data)
    root = warehouse_root(ccw_env)
    digest = hashlib.sha256(data).hexdigest()
    (root / "objects" / digest[:2] / f"{digest}.jsonl").unlink()  # simulate a corrupt store
    out = tmp_path / "site"
    result = run_ccw(["share", short, "--out", str(out)], ccw_env)
    assert result.code != 0
    assert "no current session" not in result.err, "I/O error mislabeled as not-found"
    assert "error" in result.err.lower()
    projection_names = {
        "conversation.html",
        "conversation.compact.html",
        "transcript.md",
        "transcript.compact.md",
    }
    session_pages = [p for p in out.rglob("*") if p.name in projection_names]
    assert not session_pages, "rendered a projection for an unreadable object"


def test_a_shared_page_makes_no_third_party_request(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """DESIGN 15 item 8 (principal, 2026-07-24): a share must not expose its READER.

    Redaction scrubs the content, but a CDN <script> makes every reader's browser
    announce its IP and the page URL to a third party. `share` exists so that publishing
    does not leak, so a shared page carries highlight.js inline and calls out to nothing.
    """
    short = capture_and_short(ccw_env, basic_session(prompt="check the shared page"))
    out = tmp_path / "site"
    result = run_ccw(["share", short, "--out", str(out)], ccw_env)
    assert result.code == 0, result.err

    pages = [p for p in out.rglob("*.html")]
    assert pages, "no pages were written"
    for page in pages:
        text = page.read_text(errors="replace")
        assert "cdnjs" not in text, f"{page.name} calls out to a CDN"
        assert "http://" not in text.replace("http://www.w3.org", ""), f"{page.name} has http refs"
