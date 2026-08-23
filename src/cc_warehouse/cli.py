"""Command-line entry point for ccw / cc-warehouse (DESIGN section 7).

Slice 8 wires the `build`, `render`, and `project rename` verbs onto the shared
build orchestration (build.write_projection / build.projection_dir are the single
projection implementation, R9). Every not-yet-landed verb keeps its Phase-2 stub
behavior (Error on stderr, exit 1) until its slice lands. This module holds no write
handle and removes nothing itself: build.py owns projection removal and the store
owns the one write primitive (R2/R4 fences).
"""

import functools
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cc_warehouse import (
    archive,
    build,
    capture,
    catalog,
    doctor,
    import_tree,
    migrate,
    notify,
    registry,
    reindex,
    relocate,
    share,
    status,
    sweep,
)
from cc_warehouse.config import (
    CAP_KEY,
    CHROME_KEYS,
    CONTENT_WORD_KEYS,
    WORD_KEYS,
    Config,
    cap_problem,
    load_config,
    word_problem,
)
from cc_warehouse.render import RenderOptions

# The v1 verb table (DESIGN section 7). The order is the help listing order;
# every name here must appear in `ccw -h` (test_help_lists_every_v1_verb).
_VERBS: tuple[tuple[str, str], ...] = (
    ("hook", "capture a session from a SessionEnd payload on stdin"),
    ("sweep", "import transcripts the hook missed (--source DIR)"),
    ("render", "(re)build the 4 files for --session s:<key>, or an ad-hoc <path>"),
    ("build", "rebuild projections from the catalog (--rebuild, content flags)"),
    ("migrate", "one-shot import of a legacy archive"),
    ("import", "adopt a foreign transcript tree (--from DIR)"),
    ("relocate", "move / rename a project across the external world"),
    ("project", "list / show / rename / move / merge projects"),
    ("share", "build a sanitized static site for chosen sessions"),
    ("status", "recent captures, counts, store size, last errors"),
    ("doctor", "is capture working, and if not since when"),
    ("repair", "re-render recent archive folders doctor's desync check flags"),
    ("verify", "re-hash objects and cross-check the catalog"),
    ("archive", "build (or --verify) the archive-first tree at --to DIR"),
    ("reindex", "rebuild catalog.sqlite from the archive tree alone"),
    ("version", "print the ccw version"),
)

# Flags a verb RECOGNISES in order to REFUSE them with its own reasoning. They
# are absent from the help (they do not work) but must not be swallowed by the
# generic unknown-flag check, because the handler's message is the useful one:
# `ccw build --since` explains that a windowed build would either delete
# out-of-window projections (R4) or emit an index that silently omits sessions,
# citing DESIGN 15 block 5. A generic "unrecognised option" would bury a
# deliberate design decision behind a typo message.
_REFUSED_FLAGS: dict[str, frozenset[str]] = {
    "build": frozenset({"--since", "--until"}),
}

_HELP_FLAGS = frozenset({"-h", "--help"})
_VERSION_FLAGS = frozenset({"-v", "--version"})


def _usage() -> str:
    """The `ccw` help text: a usage line plus every v1 verb. Printed on `-h`, on
    bare `ccw`, and (to stderr) on an unknown verb."""
    lines = ["usage: ccw <verb> [options]", "", "verbs:"]
    lines.extend(f"  {name:<9} {blurb}" for name, blurb in _VERBS)
    lines.append("")
    lines.append("run 'ccw <verb> -h' for a verb's options")
    return "\n".join(lines)


def _print_version() -> int:
    import cc_warehouse

    print(cc_warehouse.__version__)
    return 0


def _bare() -> int:
    """Bare `ccw`: a short status line (best-effort, only if a warehouse already
    exists so bare never creates one) plus the usage help. Exit 0 (DESIGN 7)."""
    try:
        config = load_config()
        if (config.root / "catalog.sqlite").exists():
            print(status.status_text(config))
            print()
    except Exception:  # a status readout must never make bare ccw fail
        pass
    print(_usage())
    return 0


# Content toggles: (flag stem, load_config key, VARIANT, help blurb). `--stem`
# forces on, `--no-stem` forces off (DESIGN section 8 flag tier).
#
# The variant a row reaches is a FIELD, not something recovered from the stem's
# spelling. Deriving it from a `-compact` suffix looked equivalent and was not:
# `--breadcrumbs` is compact-only without carrying the suffix, so a suffix test
# files it under the full-variant heading and tells the reader the opposite of
# the truth. It would also have no way to express "neither", which the next
# slice needs -- DESIGN 15 shared rule (d) makes chrome keys variant-agnostic,
# and block 3's truncation cap is explicitly "one cap, variant-agnostic".
#
# One table and one parser for both variants: the blocks differ only in which
# variant they reach and what they default to, and a second parser would be a
# second place for the bijection to drift. The stems ARE the bijection: flag =
# key with dashes, zero exceptions (shared rule c), so `--compact-subagents` is
# not a spelling of anything.
# The GROUP a flag is listed under. Not a variant: `_FULL` and `_COMPACT` happen
# to name variants, but `_CHROME` and `_LIMITS` name kinds of setting, and both
# are variant-agnostic without being the same thing. Slice 16 proved the
# distinction the hard way - filed under a single "not a variant" bucket, the
# truncation cap printed beneath a heading that called it an initial state the
# reader could click away, which it is not.
_FULL = "full"
_COMPACT = "compact"
_CHROME = "chrome"
_LIMITS = "limits"

_CONTENT_BOOL_FLAGS: tuple[tuple[str, str, str, str], ...] = (
    ("subagents", "subagents", _FULL, "sub-agent (sidechain) exchanges"),
    ("attachments", "attachments", _FULL, "file / plan attachments"),
    ("commands", "commands", _FULL, "slash commands the user ran"),
    ("extras", "extras", _FULL, "bridge / queue / last-prompt / agent-name events"),
    ("tool-output", "tool_output", _FULL, "structured stdout / stderr on tool results"),
    ("subagents-compact", "subagents_compact", _COMPACT, "sub-agent (sidechain) exchanges"),
    ("attachments-compact", "attachments_compact", _COMPACT, "file / plan attachments"),
    ("commands-compact", "commands_compact", _COMPACT, "slash commands the user ran"),
    ("extras-compact", "extras_compact", _COMPACT,
     "bridge / queue / last-prompt / agent-name events"),
    ("tool-output-compact", "tool_output_compact", _COMPACT, "tool calls and their results"),
    ("breadcrumbs", "breadcrumbs", _COMPACT, "per-phase caption strips"),
)

# Value-taking content toggles: (flag stem, load_config key, variant, value list,
# help blurb). The value list belongs to the ROW: these two happen to share one
# today, but slice 15's chrome flags each take their own (small|medium|large,
# expanded|collapsed, closed|open, local|iso), and a shared constant would print
# the wrong values beside them.
#
# `--reminders` is the one pre-v1.1 flag whose stem is not its config key
# (`reminders_full`): DESIGN section 7 names that spelling explicitly, so it is a
# documented exception the 2026-08-01 bijection inherited rather than created.
_CONTENT_VALUE_FLAGS: tuple[tuple[str, str, str, str, str], ...] = (
    ("reminders", "reminders", _FULL, "{collapse|strip|show}", "system-reminder handling"),
    ("reminders-compact", "reminders_compact", _COMPACT, "{collapse|strip|show}",
     "system-reminder handling"),
    # Chrome initial states (DESIGN 15 block 2). Variant-agnostic per shared rule
    # (d), so they group under `any` rather than under either variant. The legal
    # words come from config.CHROME_KEYS, which owns the frozen key map: a second
    # list of legal values here would eventually disagree with the loader's.
    *(
        (
            key.replace("_", "-"),
            key,
            _CHROME,
            "{" + "|".join(allowed) + "}",
            f"{blurb} ({default})",
        )
        for key, (allowed, default, blurb) in CHROME_KEYS.items()
    ),
    # The truncation cap (block 3). Variant-agnostic like the chrome keys, but
    # its value is a NUMBER rather than one of a word list, which is why the
    # value column belongs to the row rather than to a shared constant.
    (CAP_KEY.replace("_", "-"), CAP_KEY, _LIMITS, "N",
     "cap each rendered tool result at N characters (0 = off)"),
    # Ticket 20. Filed under _FULL rather than _CHROME: the chrome keys are
    # initial states a reader can click away, this decides what is on the page
    # at all, and slice 16 recorded what filing a setting under the wrong
    # heading does to the reader. Compact welds it off, so it is full-only.
    *(
        (
            key.replace("_", "-"),
            key,
            _FULL,
            "{" + "|".join(allowed) + "}",
            f"{blurb} ({default})",
        )
        for key, (allowed, default, blurb) in CONTENT_WORD_KEYS.items()
    ),
)


def _value_flag_problem(args: Sequence[str]) -> str | None:
    """An illegal VALUE among these args, as an error message.

    Reported in table order rather than in the order the operator typed, so with
    two bad flags this names whichever key comes first here. Saying "the first"
    would be an overclaim of exactly the kind R8 exists to stop.

    Flags are validated UP FRONT and refused as a usage error, unlike a config
    file whose problems are recorded so a capture can still run (R5). The
    asymmetry is deliberate: a flag is a thing the operator just typed, so
    failing loudly costs them one retry, while a bad config file must never be
    able to stop a session being stored.
    """
    flags = _content_flags(args)
    for key in WORD_KEYS:
        value = flags.get(key)
        if value is not None:
            problem = word_problem(key, value)
            if problem is not None:
                return problem
    cap = flags.get(CAP_KEY)
    if cap is not None:
        return cap_problem(cap)
    return None


def _content_flags(args: Sequence[str]) -> dict[str, str]:
    """Content toggles parsed into a load_config flags mapping. `--x` -> on,
    `--no-x` -> off; `--reminders VALUE` and `--reminders-compact VALUE` set the
    full and compact reminder modes.

    Every comparison is exact equality, which is what keeps `--subagents` and
    `--subagents-compact` (and `--reminders` and `--reminders-compact`) from
    shadowing each other now that both spellings exist."""
    flags: dict[str, str] = {}
    for arg in args:
        for stem, key, _variant, _blurb in _CONTENT_BOOL_FLAGS:
            if arg == f"--{stem}":
                flags[key] = "1"
            elif arg == f"--no-{stem}":
                flags[key] = "0"
    for i, arg in enumerate(args):
        for stem, key, _variant, _values, _blurb in _CONTENT_VALUE_FLAGS:
            if arg == f"--{stem}" and i + 1 < len(args):
                flags[key] = args[i + 1]
            elif arg.startswith(f"--{stem}="):
                flags[key] = arg.split("=", 1)[1]
    return flags


# --- the --since / --until window (DESIGN 15 entry 2026-08-01, block 5) -----
#
# Parsing lives here because it is CLI work; share.py and sweep.py receive an
# already-resolved pair of instants and only APPLY it. That keeps one parser
# (the tracer bullet's "one shared window parser/validator") without either
# module importing the other.
#
# This is the ONE place local time is contract-correct. Rendering must never
# learn the machine's zone - slice 15 has a fence asserting that - but a date
# the operator TYPED means their calendar day, so selection reads their clock.
# The principal chose wall-clock intent over agreement with the projection
# folder names, which slice UTC days; the consequence is stated in block 5 and
# tested rather than hidden.
Window = tuple[datetime | None, datetime | None]

_BARE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_boundary(text: str, *, end_of_day: bool) -> datetime:
    """One --since / --until value as an absolute instant.

    A bare YYYY-MM-DD is the operator's LOCAL calendar day: --since takes its
    00:00:00 and --until the last instant of it, so a one-day window is
    inclusive at both ends. A naive datetime reads as local for the same reason.
    A datetime carrying an offset is taken literally, because the operator
    already said exactly which instant they meant.

    Raises ValueError on anything else. No relative forms in v1.1: "7d" and
    "yesterday" are refused rather than guessed at, since a guessed window
    silently selects the wrong sessions.
    """
    if _BARE_DATE_RE.match(text):
        day = datetime.fromisoformat(text)
        moment = day + timedelta(days=1, microseconds=-1) if end_of_day else day
        return moment.astimezone()
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


def _window_flags(args: Sequence[str]) -> tuple[Window, str | None]:
    """(since, until) parsed from these args, plus an error message or None.

    One-sided windows are valid; since after until is a usage error, because it
    selects nothing and is far more likely to be a typo than an intent.
    """
    values: dict[str, str] = {}
    for i, arg in enumerate(args):
        for stem in ("since", "until"):
            if arg == f"--{stem}" and i + 1 < len(args):
                values[stem] = args[i + 1]
            elif arg.startswith(f"--{stem}="):
                values[stem] = arg.split("=", 1)[1]
    bounds: dict[str, datetime | None] = {"since": None, "until": None}
    for stem, raw in values.items():
        try:
            bounds[stem] = _parse_boundary(raw, end_of_day=stem == "until")
        except ValueError:
            return (None, None), (
                f"--{stem} {raw!r} is not a date or datetime; use YYYY-MM-DD or an "
                "ISO datetime (no relative forms in v1.1)"
            )
    since, until = bounds["since"], bounds["until"]
    if since is not None and until is not None and since > until:
        return (None, None), "--since is after --until, which selects nothing"
    return (since, until), None


def in_window(first_ts: str | None, window: Window) -> bool:
    """Whether a session's R12 FIRST timestamp falls inside the window.

    The first timestamp is what every listing already presents, so selection
    counts time the way the operator already reads it. A session with no
    timestamp cannot be placed and is excluded from any bounded window.
    """
    since, until = window
    if since is None and until is None:
        return True
    if not first_ts:
        return False
    try:
        stamp = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.astimezone()
    if since is not None and stamp < since:
        return False
    return not (until is not None and stamp > until)


def _config_source(args: Sequence[str]) -> tuple[bool, Path | None]:
    """The `--no-config` / `--config PATH` global switches (Group H)."""
    no_config = "--no-config" in args
    config_path: Path | None = None
    for i, arg in enumerate(args):
        if arg == "--config" and i + 1 < len(args):
            config_path = Path(args[i + 1])
        elif arg.startswith("--config="):
            config_path = Path(arg.split("=", 1)[1])
    return no_config, config_path


def _load(args: Sequence[str], *, project_id: int | None = None) -> Config:
    """load_config honoring the content toggles and `--no-config`/`--config`
    parsed from a verb's args."""
    no_config, config_path = _config_source(args)
    return load_config(
        flags=_content_flags(args),
        no_config=no_config,
        config_path=config_path,
        project_id=project_id,
    )


def _wants_help(args: Sequence[str]) -> bool:
    return any(a in _HELP_FLAGS for a in args)


def _verb_help(verb: str, specific: tuple[tuple[str, str], ...], *, content: bool) -> str:
    """Per-verb help: verb-specific options, then (for build/render) the shared
    content toggles and the config-source switches.

    The toggles are GROUPED by the variant they reach, which shared rule (c)
    explicitly allows ("help text may group flags for readability") as long as no
    flag is respelled. Every stem below is printed exactly as the parser accepts
    it, straight out of the same tables.
    """
    lines = [f"usage: ccw {verb} [options]", ""]
    for name, blurb in specific:
        lines.append(f"  {name:<28} {blurb}")
    if content:
        groups = (
            (_FULL, "content, full variants (default on; --no-X drops it):"),
            (_COMPACT, "content, compact variant (default off; --X adds it):"),
            (_CHROME, "page chrome (initial state only; the reader's own clicks win after that):"),
            (_LIMITS, "limits (opt-in; off unless set):"),
        )
        for variant, heading in groups:
            lines.append("")
            lines.append(heading)
            for stem, _key, row_variant, blurb in _CONTENT_BOOL_FLAGS:
                if row_variant == variant:
                    lines.append(f"  --[no-]{stem:<21} {blurb}")
            for stem, _key, row_variant, values, blurb in _CONTENT_VALUE_FLAGS:
                if row_variant == variant:
                    lines.append(f"  {f'--{stem} {values}':<28} {blurb}")
    lines.append("")
    lines.append("config:")
    lines.append(f"  {'--config PATH':<28} read one config file instead of the usual two")
    lines.append(f"  {'--no-config':<28} ignore config files (defaults + env + flags only)")
    return "\n".join(lines)


def _read_payload() -> dict[str, object]:
    """Parse and validate the SessionEnd JSON payload from stdin (SPEC section 2.6).

    Raises on an empty, non-JSON, non-object, or transcript_path-less payload; the hook
    turns any raise into an error notification and a clean exit (never-raise, F7)."""
    decoded = json.loads(sys.stdin.read())
    if not isinstance(decoded, dict):
        raise ValueError("SessionEnd payload is not a JSON object")
    payload = cast(dict[str, object], decoded)
    transcript = payload.get("transcript_path")
    if not isinstance(transcript, str) or not transcript:
        raise ValueError("SessionEnd payload has no transcript_path")
    return payload


def _str_field(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _spawn_render(short: str) -> None:
    """Spawn the detached render child (SPEC section 2.5): start_new_session, all stdio to
    DEVNULL, `ccw render --session s:<key>`. Capture never waits on the child; the child
    stays a stub until slice 8. Best-effort: an OS spawn failure (EAGAIN/ENOMEM/missing
    executable) is swallowed so a spawn failure never turns a stored capture into a
    reported error (DESIGN section 12)."""
    try:
        subprocess.Popen(
            [sys.executable, "-m", "cc_warehouse", "render", "--session", f"s:{short}"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return


def _reveal_target(config: Config, short: str | None) -> str:
    """The folder the open-folder opt-in should show for this capture.

    THE DEFECT THIS CLOSES, measured on the real warehouse 2026-08-04. This
    branch revealed `<root>/projections` unconditionally. That directory stopped
    existing the day `keep_projections = false` was set, and `notify.open_folder`
    is a fire-and-forget Popen whose failures are swallowed by design, so the
    reveal silently did nothing. Silence is exactly what the feature being OFF
    looks like, so there was no way to tell the two apart (F6).

    It also made the two branches disagree: a fresh capture reveals the session's
    own archive folder, via the render child, while an unchanged re-fire revealed
    a top-level directory. Same opt-in, two answers, one of them pointing at
    nothing. R9 says they should give one answer, and the session folder is the
    right one because the archive folder IS the deliverable.

    The no-archive case is deliberately UNCHANGED: without `archive_root` the
    vault-era layout is still in use and `projections/` is still the right place.
    This narrows the behaviour rather than replacing it.

    Never raises: it runs on the hook path, and DESIGN 12 makes every sink
    best-effort. A lookup that fails degrades to the old answer rather than
    costing a capture.
    """
    if config.archive_root is not None and short:
        try:
            conn = catalog.open_catalog(config.root)
            try:
                head = build.head_for_short(conn, short)
            finally:
                conn.close()
            if head is not None:
                return str(
                    build.archive_dir(
                        config.archive_root,
                        head.label,
                        head.first_ts,
                        head.session_uuid,
                        config.archive_timezone,
                        fallback_stem=f"session-{head.short}",
                    )
                )
        except Exception:  # noqa: BLE001 - a reveal may never fail a capture
            pass
    return str(config.root / "projections")


def _report_capture(config: Config, result: capture.CaptureResult) -> None:
    """Emit notifications for a completed capture per its action (DESIGN sections 4, 12).

    A duplicate SessionEnd invocation is silent (no sink fires). A fresh `stored` capture
    spawns the render child and reports ok; the network POSTs leave via the detached
    notify-only helper (notify.report), never inline on the hook. An unchanged re-fire
    reports skipped_unchanged (silent by default) and honors the open-folder opt-in. An
    error reports error. Every sink is best-effort and cannot fail capture."""
    if result.action == "duplicate-invocation":
        return
    short = result.short or None
    if result.action == "error":
        notify.report(
            config,
            notify.NotifyEvent("error", short, None, result.detail, result.elapsed_ms),
        )
        return
    if result.action == "skipped_unchanged":
        notify.report(
            config,
            notify.NotifyEvent(
                "skipped_unchanged", short, result.detail or None, "unchanged", result.elapsed_ms
            ),
        )
        if config.open_folder:
            notify.open_folder(config, _reveal_target(config, short))
        return
    # stored: a successful new capture. The render child is spawned INDEPENDENTLY of any
    # sink (a log or webhook failure must never suppress rendering); both the spawn and
    # notify.report are best-effort and neither can fail the capture (DESIGN section 12).
    _spawn_render(result.short)
    notify.report(
        config,
        notify.NotifyEvent("ok", short, result.detail or None, "captured", result.elapsed_ms),
    )


def _run_hook() -> int:
    """`ccw hook`: run the SessionEnd capture pipeline; always exit 0 (never-raise, F7).

    A kill switch (CCW_SKIP_HOOK) no-ops. An invalid payload, a missing transcript, or any
    unexpected failure becomes an error notification and a clean exit with nothing stored
    and no traceback on stderr (SPEC section 2.6)."""
    config: Config | None = None
    try:
        config = load_config()
        if config.skip_hook:
            # Ticket 24.7: a silent no-op here is indistinguishable from a healthy
            # capture with nothing to do. Report it (log-only, like
            # skipped_unchanged) so an operator who left CCW_SKIP_HOOK=1 set can
            # tell the difference from the audit trail.
            notify.report(
                config,
                notify.NotifyEvent("skipped_disabled", None, None, "CCW_SKIP_HOOK=1", None),
            )
            return 0
        payload = _read_payload()
        result = capture.capture_transcript(
            config,
            Path(str(payload["transcript_path"])),
            session_id=_str_field(payload, "session_id"),
            cwd=_str_field(payload, "cwd"),
        )
        _report_capture(config, result)
    except Exception as exc:  # never-raise into the harness (SPEC 2.6 / F7)
        if config is not None:
            try:
                notify.report(config, notify.NotifyEvent("error", None, None, repr(exc), None))
            except Exception:
                pass
    return 0


def _sweep_source(args: Sequence[str]) -> tuple[Path | None, str | None]:
    """Resolve the optional `--source DIR` / `--source=DIR` override for `ccw sweep`.

    Returns (source, error). No `--source` at all yields (None, None): the sweep uses the
    default ~/.claude/projects. A `--source` present but with a MISSING, EMPTY, or flag-like
    (starts with "-") value yields (None, message): the caller reports the usage error and
    refuses to sweep rather than silently targeting a tree the operator did not name (R5).
    Deliberately a hand-rolled parser rather than argparse: `sweep` takes exactly this one
    option, and the Group-A content flags slice 13 added apply to `build` and `render`, not
    here (DESIGN section 7)."""
    raw: str | None = None
    seen = False
    for i, arg in enumerate(args):
        if arg == "--source":
            raw = args[i + 1] if i + 1 < len(args) else None
            seen = True
            break
        if arg.startswith("--source="):
            raw = arg[len("--source=") :]
            seen = True
            break
    if not seen:
        return None, None
    if raw is None:
        return None, "sweep: --source requires a directory (no value given)"
    if not raw or raw.startswith("-"):
        return None, f"sweep: --source requires a directory, got {raw!r}"
    return Path(raw), None


def _run_sweep(args: Sequence[str]) -> int:
    """`ccw sweep`: capture transcripts the hook missed under a locks/sweep lock.

    A malformed `--source` is a usage error that refuses to sweep (R5). A live lock holder
    is a distinct refusal that is NOT counted as a batch item. Otherwise prints an end
    report naming every failed item (R10) and returns non-zero when any item failed, 0
    otherwise (R5/R10)."""
    source, source_error = _sweep_source(args)
    if source_error is not None:
        print(source_error, file=sys.stderr)
        return 2
    window, problem = _window_flags(args)
    if problem is not None:
        print(f"Error: {problem}", file=sys.stderr)
        return 1
    keep = functools.partial(in_window, window=window) if window != (None, None) else None
    quiet = "--quiet" in args
    config = load_config()
    if "--dry-run" in args:
        # A rehearsal, not a run. sweep.plan takes no lock and opens the catalog
        # read-only, so a dry-run on a warehouse that does not exist yet leaves
        # it that way (ticket 23; test_dry_run_on_a_fresh_root_creates_no_warehouse).
        planned = sweep.plan(config, source, keep)
        failures = planned.failures
        for outcome in failures:
            detail = outcome.detail or outcome.action
            print(f"sweep failed: {outcome.item}: {detail}", file=sys.stderr)
        if not quiet:
            for outcome in planned.outcomes:
                if outcome.action.startswith("would-"):
                    print(f"  {outcome.action}: {outcome.item}")
            would_store = sum(1 for o in planned.outcomes if o.action == "would-store")
            print(
                f"sweep --dry-run: {len(planned.outcomes)} items, "
                f"{would_store} would be stored, 0 written"
            )
        return 1 if failures else 0
    report = sweep.sweep(config, source, keep)
    if any(outcome.action == sweep.LOCK_HELD_ACTION for outcome in report.outcomes):
        print("sweep refused: lock held by a live holder", file=sys.stderr)
        return 2
    failures = report.failures
    for outcome in failures:
        print(f"sweep failed: {outcome.item}: {outcome.detail or outcome.action}", file=sys.stderr)
    stored = sum(1 for outcome in report.outcomes if outcome.action == "stored")
    # PROJECT WHAT WE JUST STORED. Found on real data 2026-08-04: the scheduled
    # sweep rescued 642 sessions with zero failures, and `ccw archive --verify`
    # then reported 3,194 problems because 721 folders held a conversation and
    # none of the five generated files. The hook renders by spawning a detached
    # child and only `_run_hook` ever calls it, so a swept session was stored and
    # unreadable, which inverts the archive-first premise.
    #
    # `build.build` rather than a second renderer here (R9): it is incremental,
    # it already mirrors into the archive, and it prunes nothing outside
    # projections/. One detached child per item is not an option at this scale;
    # this sweep would have spawned 2,064 processes.
    if stored:
        build_report = build.build(config)
        build_failures = build_report.failures
        for outcome in build_failures:
            print(f"sweep: projection failed: {outcome.item}: {outcome.detail}", file=sys.stderr)
        failures = failures + build_failures
    if not quiet:
        # --quiet drops STDOUT only. Failures are already on stderr above, and the
        # exit code is untouched, so a scheduled sweep stays silent when it works
        # and still speaks when it does not (ticket 23, 24.5).
        print(f"sweep: {len(report.outcomes)} items, {stored} stored, {len(failures)} failed")
    return 1 if failures else 0


def _parse_notify_record(args: Sequence[str]) -> dict[str, object] | None:
    """Extract the `--record <json>` event handed to the detached notify helper."""
    try:
        raw = args[args.index("--record") + 1]
    except (ValueError, IndexError):
        return None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    return cast(dict[str, object], decoded)


def _spoken_label(config: Config, short: object) -> str:
    """The project label to SAY for a capture, looked up from the catalog.

    The record's own `project` field carries the RESOLUTION SOURCE
    (`payload_cwd` / `jsonl_cwd` / `transcript_dir`), not a label, so it cannot
    be spoken. It is looked up here rather than corrected at the source on
    purpose: that field is on the durable audit line AND on every webhook
    payload, so changing what it means is its own decision with its own blast
    radius, not something to smuggle in alongside a voice sink.

    Runs in the DETACHED helper, never on the hook's critical path, so one extra
    read-only catalog open costs the operator nothing. Degrades to a neutral
    phrase rather than raising: a sink may not fail (DESIGN 12).
    """
    if not short:
        return "an unnamed project"
    try:
        conn = catalog.open_catalog(config.root)
        try:
            row = conn.execute(
                "SELECT p.label FROM session s JOIN project p ON p.id = s.project_id"
                " WHERE s.short = ? LIMIT 1",
                (str(short),),
            ).fetchone()
        finally:
            conn.close()
        if row and row[0]:
            return str(row[0])
    except Exception:  # noqa: BLE001 - a sink may never fail a capture
        pass
    return "an unnamed project"


def _voice_line(config: Config, record: Mapping[str, object]) -> str | None:
    """The sentence to speak for one capture record, or None to stay silent.

    Ported from the frozen specimen's `report()`: stored and failed speak, an
    unchanged re-fire does not. Keeping the decision in ONE function, driven by
    `notify.SPEAKING_STATUSES`, is what makes "what should speak, and when" a
    thing that can be changed by editing a set rather than by hunting call sites.
    """
    status = str(record.get("status") or "")
    if status not in notify.SPEAKING_STATUSES:
        return None
    if status == "error":
        reason = str(record.get("message") or "").strip() or "unknown error"
        return f"Transcript capture failed. {reason}"
    return f"Transcript captured to {_spoken_label(config, record.get('session'))}"


def _run_notify(args: Sequence[str]) -> int:
    """Hidden `ccw notify` verb: the detached notify-only helper (DESIGN section 12).

    Spawned fire-and-forget by the hook so the webhook POSTs stay off the capture
    critical path. Re-loads config from the inherited CCW_ROOT, then POSTs each opted-in
    sink best-effort. Never raises into anything (it is detached); always exits 0."""
    record = _parse_notify_record(args)
    if record is None:
        return 0
    try:
        config = load_config()
    except Exception:
        return 0
    notify.post_webhooks(config, record)
    line = _voice_line(config, record)
    if line is not None:
        notify.speak(config, line)
    return 0


def _run_build(args: Sequence[str]) -> int:
    """`ccw build`: project the catalog into projections/ (DESIGN sections 1, 6).

    Incremental by default; --rebuild regenerates every file, --include-hidden also
    projects warmup/no-summary sessions. A live locks/build holder makes build refuse
    without projecting anything (R14). Otherwise prints a one-line report and names any
    failed item (R10); exits non-zero when the build was refused or an item failed."""
    rest = args[1:]
    if any(
        a in ("--since", "--until") or a.startswith(("--since=", "--until="))
        for a in rest
    ):
        # REFUSED in DESIGN 15 block 5, recorded rather than deferred: a windowed
        # build either deletes out-of-window projections (R4) or emits an index
        # that silently omits sessions. Refusing loudly is the whole point.
        print(
            "Error: ccw build does not take --since/--until; a windowed build would "
            "either delete out-of-window projections or hide sessions. Use ccw share "
            "or ccw sweep",
            file=sys.stderr,
        )
        return 1
    problem = _value_flag_problem(rest)
    if problem is not None:
        print(f"Error: {problem}", file=sys.stderr)
        return 1
    rebuild = "--rebuild" in rest
    include_hidden = "--include-hidden" in rest
    config = _load(rest)
    report = build.build(config, rebuild=rebuild, include_hidden=include_hidden)
    if any(outcome.action == build.BUILD_LOCK_HELD for outcome in report.outcomes):
        print("build refused: lock held by a live holder", file=sys.stderr)
        return 2
    built = sum(1 for outcome in report.outcomes if outcome.action == "built")
    unchanged = sum(1 for outcome in report.outcomes if outcome.action == build.UNCHANGED)
    failures = report.failures
    for outcome in failures:
        print(f"build failed: {outcome.item}: {outcome.detail or outcome.action}", file=sys.stderr)
    # "unchanged" is its own segment, never folded into "built" (R10/F6):
    # an all-skipped run must not read as "0 built" with no explanation,
    # mirroring archive.MigrationReport.summary()'s "N unchanged" line.
    print(
        f"build: {len(report.outcomes)} sessions, {built} built, "
        f"{unchanged} unchanged, {len(failures)} failed"
    )
    return 1 if failures else 0


def _render_flags(rest: Sequence[str]) -> tuple[str | None, str | None, str | None]:
    """Split `ccw render` args into (session_key, out_dir, source_path).

    `--session s:<key>` selects the catalog form; a bare positional selects the ad-hoc
    form; `--out DIR` names the ad-hoc destination. This splits only the SELECTION
    arguments; the Group-A content flags slice 13 added are layered separately through
    load_config(flags=...) (DESIGN section 8), which is why this stayed hand-rolled."""
    session: str | None = None
    out: str | None = None
    source: str | None = None
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg == "--session":
            session = rest[i + 1] if i + 1 < len(rest) else None
            i += 2
        elif arg.startswith("--session="):
            session = arg[len("--session=") :]
            i += 1
        elif arg == "--out":
            out = rest[i + 1] if i + 1 < len(rest) else None
            i += 2
        elif arg.startswith("--out="):
            out = arg[len("--out=") :]
            i += 1
        else:
            if source is None and not arg.startswith("-"):
                source = arg
            i += 1
    return session, out, source
def _mirror_to_archive(config: Config, label: str, short: str, data: bytes) -> None:
    """Keep the archive-first tree CURRENT from the capture path (slice 19i).

    Before this, `ccw archive` filled a tree once and nothing kept it there, so
    every new session landed in the old store and the tree drifted from the
    moment the command finished. It was an export, not an archive.

    OPT-IN and NEVER FATAL. No `archive_root` means this is a no-op and the
    capture path behaves exactly as it did before, which is what lets the slice
    ship against a live warehouse. When it is set, a failure here is swallowed:
    the session is already in the store by the time this runs, the projections
    are already written, and DESIGN 12's rule is that the detached child must
    never turn a STORED capture into a lost one. The archive is the new tree and
    the old one is still the live one; an archive problem must not cost the
    operator the tree they actually use today.

    Takes the two fields it needs rather than the catalog head object: the
    head type is private to build.py, and reaching across a module boundary
    for a private name is coupling this function does not need.

    It calls the same folder writer `ccw archive` calls (R9), so a session
    captured live and the same session migrated land in the same folder. A
    second implementation here would silently double the tree.
    """
    if config.archive_root is None:
        return
    try:
        archive.write_session_folder(
            config.archive_root,
            label,
            data,
            build.render_options(config),
            config.archive_timezone,
            fallback_stem=f"session-{short}",
        )
    except Exception:
        return


def _open_rendered_page(config: Config, directory: Path, short: str) -> None:
    """Best-effort `--open`: hand this session's rendered HTML page to the
    platform opener (ticket 28.1). Checks the archive folder first when one is
    configured, mirroring `_reveal_target`'s "the archive is the deliverable"
    precedent, then falls back to the personal projections copy. Needs the
    literal FILE rather than `_reveal_target`'s own answer (a bare directory in
    the no-archive case), so it checks existence itself rather than trusting a
    folder computed for a different call site. With both retired there is
    nothing to open, and this is silently a no-op like every other
    fire-and-forget sink here (DESIGN section 12)."""
    candidates: list[Path] = []
    if config.archive_root is not None:
        candidates.append(Path(_reveal_target(config, short)) / "conversation.html")
    if config.keep_projections:
        candidates.append(directory / "conversation.html")
    for candidate in candidates:
        if candidate.exists():
            try:
                notify.open_page(str(candidate))
            except Exception:
                pass
            return


def _render_session(session_key: str, rest: Sequence[str], *, open_flag: bool = False) -> int:
    """`ccw render --session s:<key>`: (re)project one stored session, the hook's
    detached child (DESIGN section 4). Projects only a CURRENT head through the shared
    build helper (build.head_for_short, R9/F8): a short with no catalog row is the
    error contract (exit 1), but a short that exists yet is superseded or hidden is a
    clean no-op (return 0) that lays down no orphan dir the next build would prune.

    As the hook's detached child this is the last surviving signal on failure (DESIGN
    section 4): a render error emits a best-effort error notification (never raising)
    and exits non-zero, and a successful render honors the open-folder opt-in. A
    superseded/hidden no-op is not a failure, so it stays silent."""
    short = session_key[2:] if session_key.startswith("s:") else session_key
    config = _load(rest)
    conn = catalog.open_catalog(config.root)
    try:
        exists = (
            conn.execute("SELECT 1 FROM session WHERE short = ?", (short,)).fetchone()
            is not None
        )
        head = build.head_for_short(conn, short) if exists else None
    finally:
        conn.close()
    if not exists:
        print(f"Error: no stored session for s:{short}", file=sys.stderr)
        return 1
    if head is None:  # exists but superseded or hidden: clean no-op, no dir laid down
        return 0
    directory = build.projection_dir(
        config.root / "projections", head.label, head.first_ts, head.slug, head.short
    )
    try:
        data = archive.read_payload(
            config,
            label=head.label,
            first_ts=head.first_ts,
            session_uuid=head.session_uuid,
            short=head.short,
            sha256=head.hash,
        )
        if config.keep_projections:
            build.write_projection(directory, data, build.render_options(config), force=False)
        _mirror_to_archive(config, head.label, head.short, data)
    except Exception as exc:  # the detached child's only surviving signal (DESIGN 4)
        try:
            notify.report(config, notify.NotifyEvent("error", short, None, repr(exc), None))
        except Exception:
            pass
        return 1
    if config.open_folder:
        try:
            # NOT `directory`, which is the PROJECTIONS dir: with
            # keep_projections = false it is never written, so the reveal opened
            # nothing. Same defect as the skip branch and found the same day -
            # there are exactly two open_folder call sites and both had it.
            notify.open_folder(config, _reveal_target(config, head.short))
        except Exception:
            pass
    if open_flag:
        _open_rendered_page(config, directory, head.short)
    return 0


def _render_options(rest: Sequence[str]) -> RenderOptions:
    """Ad-hoc render honors the personal render config + content flags when a
    warehouse is configured, and falls back to defaults otherwise; it never opens
    the catalog or the store."""
    try:
        return build.render_options(_load(rest))
    except Exception:
        return RenderOptions()


def _out_under_warehouse(out: str) -> bool:
    """True when an ad-hoc --out resolves inside the warehouse store or projections.

    Guarded only when a warehouse root is configured; with none configured there is
    nothing to protect and the caller renders freely. The target and each guarded root
    are resolved before the ancestor check, so a symlinked or relative --out cannot slip
    an ad-hoc render's write into objects/ or projections/ and clobber the store (F9)."""
    try:
        config = load_config()
    except Exception:
        return False
    target = Path(out).resolve()
    for guarded in (config.root / "objects", config.root / "projections"):
        anchor = guarded.resolve()
        if target == anchor or anchor in target.parents:
            return True
    return False


def _render_adhoc(
    source: str, out: str | None, rest: Sequence[str], *, open_flag: bool = False
) -> int:
    """`ccw render <path> [--out DIR]`: render a transcript outside the store to a
    directory, without touching the catalog (DESIGN section 7). With no --out the target
    is a fresh temp dir (outside projections) whose path is printed. A user --out is
    rejected when it resolves inside the warehouse store or projections, so an ad-hoc
    render cannot clobber them (F9). A missing or unreadable source is the CLI error
    contract: `Error: <msg>` on stderr, exit 1."""
    try:
        data = Path(source).read_bytes()
    except OSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if out is not None and _out_under_warehouse(out):
        print(
            "Error: --out must not be inside the warehouse store or projections",
            file=sys.stderr,
        )
        return 1
    directory = Path(out) if out is not None else Path(tempfile.mkdtemp(prefix="ccw-render-"))
    build.write_projection(directory, data, _render_options(rest), force=False)
    if out is None:
        print(str(directory))
    if open_flag:
        try:
            notify.open_page(str(directory / "conversation.html"))
        except Exception:
            pass
    return 0


def _run_render(args: Sequence[str]) -> int:
    """`ccw render`: dispatch the --session (catalog) and ad-hoc (path) forms."""
    rest = args[1:]
    problem = _value_flag_problem(rest)
    if problem is not None:
        print(f"Error: {problem}", file=sys.stderr)
        return 1
    session, out, source = _render_flags(rest)
    open_flag = "--open" in rest
    if session is not None:
        return _render_session(session, rest, open_flag=open_flag)
    if source is not None:
        return _render_adhoc(source, out, rest, open_flag=open_flag)
    print("Error: render requires --session s:<key> or a transcript path", file=sys.stderr)
    return 1


_PROJECT_SUBCOMMANDS = "list | show <id> | rename <id> <label> | move OLD NEW | merge A B"


def _project_id_arg(raw: str) -> int | None:
    try:
        return int(raw)
    except ValueError:
        print(f"Error: project id must be an integer, got {raw!r}", file=sys.stderr)
        return None


def _run_project(args: Sequence[str]) -> int:
    """`ccw project` (DESIGN section 7): list / show / rename / move / merge.

    Completed at the v1 exit review 2026-07-24, which found DESIGN section 7 specifying
    all five while only `rename` existed. `show` is the load-bearing one: DESIGN section 8
    keys per-project config on `[project.<registry-id>]` and names this command as the way
    to obtain that id, so the per-project override feature had no documented way to be
    used. `list` and `show` read the catalog ONLY and open no stored payload (R6/F5).

    Every registry edit goes through the registry module rather than SQL written here (R9),
    so `move` and `merge` inherit its validation: a move whose old path is unclaimed or
    whose new path belongs to another project RAISES rather than silently recording
    nothing, and a merge validates both ids and soft-retires (R4: rows are never removed).
    Paths are time-stamped alias CLAIMS and claims are append-only, so a move ADDS the new
    path and keeps the old one (DESIGN section 2).
    """
    rest = args[1:]
    if not rest:
        print(f"Error: project requires a subcommand ({_PROJECT_SUBCOMMANDS})", file=sys.stderr)
        return 1
    sub, operands = rest[0], rest[1:]
    if sub not in ("list", "show", "rename", "move", "merge"):
        print(
            f"Error: unknown project subcommand {sub!r} ({_PROJECT_SUBCOMMANDS})",
            file=sys.stderr,
        )
        return 1

    config = load_config()
    conn = catalog.open_catalog(config.root)
    try:
        if sub == "list":
            rows = conn.execute(
                "SELECT id, label, retired FROM project ORDER BY id"
            ).fetchall()
            if not rows:
                print("no projects yet")
                return 0
            for project_id, label, retired in rows:
                # A retired project is SHOWN and marked, never hidden: rows are
                # soft-flagged (R4), so the command that enumerates projects must not
                # make a merged one appear to have been deleted.
                mark = "  (retired)" if retired else ""
                print(f"{project_id}\t{label}{mark}")
            return 0

        if sub == "show":
            if not operands:
                print("Error: project show requires <id>", file=sys.stderr)
                return 1
            project_id = _project_id_arg(operands[0])
            if project_id is None:
                return 1
            row = conn.execute(
                "SELECT label, created_at, retired FROM project WHERE id = ?", (project_id,)
            ).fetchone()
            if row is None:
                print(f"Error: no project with id {project_id}", file=sys.stderr)
                return 1
            label, created_at, retired = row
            sessions = conn.execute(
                "SELECT COUNT(*) FROM session WHERE project_id = ?", (project_id,)
            ).fetchone()[0]
            print(f"id: {project_id}")  # DESIGN 8: the id per-project config is keyed by
            print(f"label: {label}")
            print(f"created: {created_at}")
            print(f"retired: {'yes' if retired else 'no'}")
            print(f"sessions: {sessions}")
            print(f"config section: [project.{project_id}]")
            claims = conn.execute(
                "SELECT kind, path, first_seen, last_seen FROM project_alias"
                " WHERE project_id = ? ORDER BY kind, path",
                (project_id,),
            ).fetchall()
            print("claims:" if claims else "claims: (none)")
            for kind, path, first_seen, last_seen in claims:
                print(f"  {kind}\t{path}\t{first_seen} .. {last_seen}")
            return 0

        if sub == "rename":
            if len(operands) < 2:
                print("Error: project rename requires <id> <label>", file=sys.stderr)
                return 1
            project_id = _project_id_arg(operands[0])
            if project_id is None:
                return 1
            label = operands[1]
            if not label.strip():
                print("Error: project rename requires a non-empty label", file=sys.stderr)
                return 1
            exists = (
                conn.execute("SELECT 1 FROM project WHERE id = ?", (project_id,)).fetchone()
                is not None
            )
            if not exists:  # renaming a project that does not exist is an error, not a no-op
                print(f"Error: no project with id {project_id}", file=sys.stderr)
                return 1
            registry.rename_project(conn, project_id, label)
            return 0

        if sub == "move":
            if len(operands) < 2:
                print("Error: project move requires OLD NEW", file=sys.stderr)
                return 1
            old_path, new_path = operands[0], operands[1]
            owner = registry.project_for_path(conn, old_path, "cwd")
            if owner is None:
                print(f"Error: no project claims {old_path}", file=sys.stderr)
                return 1
            try:
                registry.move_project(
                    conn, owner, old_path, new_path, datetime.now(UTC).isoformat()
                )
            except ValueError as exc:  # another project's claim, or a stale old path (R5)
                print(f"Error: {exc}", file=sys.stderr)
                return 1
            print(f"project {owner}: claimed {new_path} (previous claims kept)")
            return 0

        # merge A B: A is KEPT, B is merged into it and soft-retired.
        if len(operands) < 2:
            print("Error: project merge requires A B (A is kept)", file=sys.stderr)
            return 1
        keep_id, merge_id = _project_id_arg(operands[0]), _project_id_arg(operands[1])
        if keep_id is None or merge_id is None:
            return 1
        labels = {
            cast(int, r[0]): cast(str, r[1])
            for r in conn.execute("SELECT id, label FROM project").fetchall()
        }
        try:
            registry.merge_projects(conn, keep_id, merge_id)
        except ValueError as exc:  # same id, unknown id, or a retired keep (R5)
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        keep_label = labels.get(keep_id, str(keep_id))
        merge_label = labels.get(merge_id, str(merge_id))
        # Say which way it went: `merge A B` read cold does not tell you which survives.
        print(
            f"merged {merge_label} ({merge_id}) into {keep_label} ({keep_id});"
            f" {merge_label} is retired, not deleted"
        )
        return 0
    finally:
        conn.close()


def _consented(assume_yes: bool, prompt: str) -> bool:
    """Gate an apply-class external-world write behind an explicit yes (R13/F10).

    --yes is consent. Otherwise a real interactive terminal is prompted once for [y/N].
    A non-TTY stdin (a pipe, a here-string, a cron job) is NOT consent: it returns False
    so the caller aborts having changed nothing (F10). An unreadable stdin also refuses.
    One implementation shared by every apply-class verb (R9)."""
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    print(prompt, end="", file=sys.stderr)
    try:
        answer = sys.stdin.readline()
    except (OSError, EOFError):
        return False
    return answer.strip().lower() in ("y", "yes")


def _retire_consented(assume_yes: bool) -> bool:
    return _consented(assume_yes, "Rename the source root to _RETIRED_...? [y/N] ")


def _run_migrate(args: Sequence[str]) -> int:
    """`ccw migrate <old-root>`: import a legacy archive through the shared capture
    routine (DESIGN section 10). Plain migrate imports only; `--retire` is a SEPARATE
    explicit step that renames the source root and does NOT import.

    A missing source is a usage error (exit 2); a source that is not a directory is
    refused conservatively (exit 2, R5). `--retire` is gated behind an explicit yes
    (--yes or an interactive prompt); a non-TTY stdin without --yes aborts having
    changed nothing (R13/F10). A plain migrate prints a one-line report, names any
    failed item on stderr (R10), and exits non-zero when any item failed."""
    rest = args[1:]
    retire = "--retire" in rest
    assume_yes = "--yes" in rest
    src_str = next((arg for arg in rest if not arg.startswith("-")), None)
    if src_str is None:
        print("Error: migrate requires <old-root>", file=sys.stderr)
        return 2
    src = Path(src_str)
    if not src.is_dir():
        print(f"Error: migrate source is not a directory: {src}", file=sys.stderr)
        return 2
    if retire:
        if not _retire_consented(assume_yes):
            print("migrate --retire aborted: no consent (use --yes)", file=sys.stderr)
            return 2
        try:
            new_path = migrate.retire(src, year_month=datetime.now(UTC).strftime("%Y-%m"))
        except OSError as exc:  # existing target or a failed rename: report, do not crash (R5)
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(str(new_path))
        return 0
    config = load_config()
    report = migrate.migrate(config, src)
    if any(outcome.action == migrate.LOCK_HELD_ACTION for outcome in report.outcomes):
        print("migrate refused: lock held by a live holder", file=sys.stderr)
        return 2
    failures = report.failures
    for outcome in failures:
        print(
            f"migrate failed: {outcome.item}: {outcome.detail or outcome.action}",
            file=sys.stderr,
        )
    stored = sum(1 for outcome in report.outcomes if outcome.action == "stored")
    print(f"migrate: {len(report.outcomes)} items, {stored} stored, {len(failures)} failed")
    return 1 if failures else 0


def _run_import(args: Sequence[str]) -> int:
    """`ccw import --from DIR`: adopt a foreign transcript tree (ticket 25.4).

    Everything is validated UP FRONT and refused as a usage error before any work
    begins: a missing or non-directory `--from` exits 2 having done nothing (R5).

    The end report distinguishes four non-failure outcomes that a single count
    would hide, because each answers a different question the operator will ask:
    what was STORED, what was already here, what branch was PRUNED, and what was
    kept but is not a session. Only `error` items make the exit code non-zero
    (R10); a pruned quarantine is a correct outcome, not a fault.

    `--dry-run` routes to `import_tree.plan`, which takes no lock and opens the
    catalog read-only, so a rehearsal on a warehouse that does not exist yet
    leaves it that way. That property is proved by snapshot in the oracle tests,
    not asserted here: exit 0 plus output is not evidence that nothing happened.
    """
    rest = args[1:]
    source_raw = _flag_value(rest, "from")
    if source_raw is None:
        print("Error: import requires --from DIR", file=sys.stderr)
        return 2
    source = Path(source_raw).expanduser()
    if not source.is_dir():
        print(f"Error: import source is not a directory: {source}", file=sys.stderr)
        return 2
    quiet = "--quiet" in rest
    config = _load(args)

    if "--dry-run" in rest:
        planned = import_tree.plan(config, source)
        failures = planned.failures
        for outcome in failures:
            print(f"import failed: {outcome.item}: {outcome.detail or outcome.action}",
                  file=sys.stderr)
        if not quiet:
            for outcome in planned.outcomes:
                if outcome.action.startswith("would-"):
                    print(f"  {outcome.action}: {outcome.item}")
            for outcome in planned.outcomes:
                if outcome.action == import_tree.SKIPPED_BRANCH_ACTION:
                    print(f"  pruned: {outcome.item}")
            would_store = sum(1 for o in planned.outcomes if o.action == "would-store")
            print(
                f"import --dry-run: {len(planned.outcomes)} items, "
                f"{would_store} would be stored, 0 written"
            )
        return 1 if failures else 0

    report = import_tree.import_tree(config, source)
    if any(outcome.action == import_tree.LOCK_HELD_ACTION for outcome in report.outcomes):
        print("import refused: lock held by a live holder", file=sys.stderr)
        return 2
    failures = report.failures
    for outcome in failures:
        print(f"import failed: {outcome.item}: {outcome.detail or outcome.action}",
              file=sys.stderr)

    def _count(action: str) -> int:
        return sum(1 for outcome in report.outcomes if outcome.action == action)

    stored = _count("stored")
    pruned = [o for o in report.outcomes if o.action == import_tree.SKIPPED_BRANCH_ACTION]
    kept = _count(import_tree.NOT_A_SESSION_ACTION)
    subagents = _count(import_tree.SUBAGENT_ACTION)
    if not quiet:
        for outcome in pruned:
            print(f"  pruned branch: {outcome.item}")
        for outcome in report.outcomes:
            if outcome.action == import_tree.NOT_A_SESSION_ACTION:
                print(f"  not a session, kept: {outcome.item} -> {outcome.detail}")
            elif outcome.action == import_tree.SUBAGENT_ACTION:
                print(f"  sub-agent, refused: {outcome.item}")
        print(
            f"import: {len(report.outcomes)} items, {stored} stored, "
            f"{len(pruned)} skipped branch, {kept} kept as not a session, "
            f"{subagents} sub-agents refused, {len(failures)} failed"
        )
    # PROJECT WHAT WE JUST STORED, for the reason sweep does (2026-08-04): a
    # stored-but-unrendered session inverts the archive-first premise, and
    # `ccw archive --verify` reported 3,194 problems the one time it happened.
    if stored:
        build_report = build.build(config)
        for outcome in build_report.failures:
            print(f"import: projection failed: {outcome.item}: {outcome.detail}",
                  file=sys.stderr)
        if build_report.failures:
            return 1
    return 1 if failures else 0


def _run_status() -> int:
    """`ccw status`: recent captures, counts, store size, last errors (DESIGN section 7).

    A pure read surface: it prints status.status_text, which reads the catalog only and
    opens no stored payload under objects/ (R6/F5). Always exits 0; this verb reports the
    warehouse, it does not judge it."""
    config = load_config()
    print(status.status_text(config))
    return 0


def _run_doctor() -> int:
    """`ccw doctor`: is capture working, and if not since when (DESIGN section 7).

    The one verb that JUDGES rather than reports, which is why it is separate
    from `status`: status answers what is in the warehouse, doctor answers
    whether the machinery works, and conflating them is what let capture sit
    broken for ten days while status looked entirely normal.

    Exits non-zero when capture is not working, so it composes into a cron job
    and a session-start check. Read-only by construction: it opens the catalog
    read-only and never creates the warehouse, because it runs precisely when
    things are already wrong."""
    report = doctor.diagnose(load_config())
    print(doctor.report_text(report))
    return 0 if report.ok else 1


def _run_verify() -> int:
    """`ccw verify`: re-hash objects against their names and cross-check the catalog.

    status.verify wraps store.verify_walk (the one hashing implementation, R9/F8) and
    reports corrupted objects, orphan objects (left in place, R4), and catalog rows whose
    object is missing. Each finding is named by its short hash on stderr so the digest is
    visible in the output; the verb exits non-zero when the store has any finding and 0
    when it is intact and cross-consistent. verify writes and removes nothing (R4)."""
    config = load_config()
    if not config.keep_objects and config.archive_root is not None:
        # Ruling (b), 2026-08-02: `ccw verify` BECOMES archive integrity. It
        # follows the DATA, not a name. Re-hashing a retired vault and reporting
        # "store intact" would be the most dangerous kind of green: a passing
        # check on the one tree that no longer holds anything.
        return _archive_verify(config.archive_root, config.archive_timezone)
    report = status.verify(config)
    findings = report.outcomes
    for outcome in findings:
        print(f"verify: {outcome.action} {outcome.item}: {outcome.detail}", file=sys.stderr)
    if not findings:
        print("verify: store intact and cross-consistent")
    return 1 if findings else 0


def _run_repair(rest: Sequence[str]) -> int:
    """`ccw repair`: re-render any of the same recent archive folders `ccw doctor`'s
    desync check flags (ticket 32 -- a real 2026-08-23 incident: the hook's detached
    render child never finished, leaving a folder's JSONL archived with none of its
    five generated files, invisible until a human noticed doctor's RED banner and
    fixed it by hand).

    A separate, explicit, WRITING verb -- doctor stays read-only by construction (its
    own module docstring), so this exists precisely so doctor's output, a public
    compatibility surface an external tool (ccw-watch) parses, never gains a silent
    write side effect.

    Resolves each broken folder's session_uuid (from its own name, R12) to a catalog
    short, then calls the SAME render path the hook's detached child uses (`ccw render
    --session s:<key>`), synchronously -- repair is an explicit operator/scheduled
    action, not a hook, so waiting on it is fine. Never touches a folder outside
    doctor's own bounded recent sample (R9: one instrument, shared).

    `--quiet` matches `sweep`'s own contract exactly (cli.py `_run_sweep`): drops the
    STDOUT summary only, so a scheduled run's log stays empty when nothing was wrong
    and non-empty exactly when it wasn't -- failures still go to stderr and the exit
    code is unaffected."""
    quiet = "--quiet" in rest
    config = _load(rest)
    folders, broken = doctor.desync_detail(config)
    if not broken:
        if not quiet:
            print(f"repair: 0 problems in the {len(folders)} most recently captured folder(s)")
        return 0
    conn = catalog.open_catalog(config.root)
    try:
        fixed = 0
        still_broken: list[str] = []
        for folder, _problems in broken:
            session_uuid = folder.name.partition("_")[2]
            row = conn.execute(
                "SELECT short FROM session WHERE session_uuid = ? "
                "ORDER BY captured_at DESC LIMIT 1",
                (session_uuid,),
            ).fetchone()
            if row is None:
                still_broken.append(f"{folder.name}: no catalog row for {session_uuid}")
                continue
            short = cast(str, row[0])
            render = subprocess.run(
                [sys.executable, "-m", "cc_warehouse", "render", "--session", f"s:{short}"],
                capture_output=True,
                text=True,
            )
            if render.returncode != 0:
                detail = render.stderr.strip() or f"exit {render.returncode}"
                still_broken.append(f"{folder.name}: render failed: {detail}")
                continue
            remaining = archive.verify_folder(folder, config.archive_timezone)
            if remaining:
                still_broken.append(f"{folder.name}: still broken: {remaining[0].problem}")
                continue
            fixed += 1
    finally:
        conn.close()
    if not quiet:
        total_problems = sum(len(p) for _, p in broken)
        print(
            f"repair: {total_problems} problem(s) in {len(broken)} folder(s) of the "
            f"{len(folders)} most recently captured: {fixed} fixed, "
            f"{len(still_broken)} still broken"
        )
    for line in still_broken:
        print(f"  {line}", file=sys.stderr)
    return 0 if not still_broken else 1


def _flag_value(args: Sequence[str], name: str) -> str | None:
    """The value following `--name`, or None. Exact equality, so `--to` never
    shadows a longer flag that happens to start with it."""
    for i, arg in enumerate(args):
        if arg == f"--{name}" and i + 1 < len(args):
            return args[i + 1]
    return None


def _run_archive(args: Sequence[str]) -> int:
    """`ccw archive --to DIR [--verify] [--zone NAME] [--rebuild]` (ticket 19,
    slice 19h; incremental behaviour and `--rebuild` added ticket 30).

    Builds the archive-first tree BESIDE the warehouse it reads, or checks an
    existing one. Everything is validated UP FRONT and refused as a usage error
    before any work begins, because the alternative is discovering the target
    was wrong after writing several gigabytes into it.

    Incremental by default: a session whose folder already matches its current
    payload, render config and renderer version is skipped without being read.
    `--rebuild` regenerates every file regardless, mirroring `ccw build
    --rebuild`.

    `--verify` writes nothing at all. That claim is not left to inspection: an
    oracle test snapshots the tree and compares it afterwards, since exit 0 plus
    output is NOT evidence that nothing happened (learned 2026-08-01, when
    `ccw sweep -h` imported 13,836 sessions while appearing to print help).
    """
    config = _load(args)
    target_raw = _flag_value(args, "to")
    if target_raw is None:
        print("Error: archive requires --to DIR", file=sys.stderr)
        return 2
    target = Path(target_raw).expanduser()

    zone = _flag_value(args, "zone") or config.archive_timezone
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        print(f"Error: --zone is not a known IANA zone: {zone!r}", file=sys.stderr)
        return 2

    if "--verify" in args:
        return _archive_verify(target, zone)

    # The one target that would make this destructive: writing the new tree on
    # top of the vault it reads from. Refused before any work, never attempted
    # and reported afterwards (R5: the conservative branch is the default).
    if target.resolve() == config.root.resolve():
        print(
            f"Error: --to must not be the warehouse itself ({config.root})",
            file=sys.stderr,
        )
        return 2

    target.mkdir(parents=True, exist_ok=True)
    rebuild = "--rebuild" in args
    report = archive.migrate(
        config.root, target, build.render_options(config), zone, rebuild=rebuild
    )
    if report.lock_held:
        # R14/R10: a refusal is named and exits non-zero, never counted as a
        # run that wrote nothing successfully.
        print(f"archive: {report.summary()}", file=sys.stderr)
        return 1
    # After the folders, because a project.json for a project with no surviving
    # session folder would describe nothing.
    projects = archive.write_project_files(config.root, target)
    for hash_, why in report.failed:
        print(f"archive: FAILED {hash_[:16]}: {why}", file=sys.stderr)
    for hash_ in report.skipped_not_a_session:
        print(f"archive: not a session (no sessionId) {hash_[:16]}", file=sys.stderr)
    print(f"{report.summary()}, {projects} project.json written")
    return 1 if report.failed else 0


def _archive_verify(target: Path, zone: str) -> int:
    """Archive integrity over a whole tree (ruling (b), 2026-08-02).

    A missing tree is an ERROR, never an empty pass: verifying nothing and
    reporting zero problems is the failure mode that reads as success.
    """
    if not target.is_dir():
        print(f"Error: no archive at {target}", file=sys.stderr)
        return 2
    folders = 0
    problems = 0
    for folder in archive.walk_folders(target):
        folders += 1
        for problem in archive.verify_folder(folder, zone):
            problems += 1
            print(
                f"archive: {folder.parent.name}/{folder.name}: {problem.problem}",
                file=sys.stderr,
            )
    if not folders:
        print(f"Error: no session folders under {target}", file=sys.stderr)
        return 2
    print(f"archive: {folders} folders checked, {problems} problems")
    return 1 if problems else 0


def _run_reindex(args: Sequence[str]) -> int:
    """`ccw reindex [--from DIR] [--to DIR] [--dry-run]` (ticket 27, slice 27.1).

    Rebuilds `catalog.sqlite` from the archive tree alone, which is what turns
    DESIGN 15's "the catalog is a disposable index" from a claim into a property
    anyone can demonstrate.

    `--to` exists so the rebuild can be PROVED against a real archive without
    replacing the catalog a live capture hook is writing to (27.2).
    """
    config = _load(args)
    source_raw = _flag_value(args, "from")
    source = Path(source_raw).expanduser() if source_raw else config.archive_root
    if source is None:
        print("Error: reindex requires --from DIR (no [archive_root] is set)", file=sys.stderr)
        return 2
    if not source.is_dir():
        print(f"Error: no archive at {source}", file=sys.stderr)
        return 2

    target_raw = _flag_value(args, "to")
    target = Path(target_raw).expanduser() if target_raw else config.root

    dry_run = "--dry-run" in args
    report = reindex.rebuild(source, target, dry_run=dry_run)

    for name, why in report.failed:
        print(f"reindex: FAILED {name}: {why}", file=sys.stderr)
    if not report.sessions:
        # Rebuilding nothing and exiting 0 is the failure mode that reads as
        # success, exactly as `archive --verify` refuses an empty tree.
        print(f"Error: no session folders under {source}", file=sys.stderr)
        return 2

    for name in report.sidecar_unreadable:
        print(f"reindex: unreadable project.json in {name}, label from the folder name")
    if report.sidecar_missing:
        print(
            f"reindex: {len(report.sidecar_missing)} project folder(s) had no project.json;"
            " label taken from the folder name and NO aliases recovered"
            f" ({', '.join(sorted(report.sidecar_missing)[:5])}"
            f"{', ...' if len(report.sidecar_missing) > 5 else ''})"
        )
    # F6: an incomplete restore that presents itself as complete is the defect
    # class this project exists to ban, so the losses are printed every time.
    print(
        "reindex: capture_event history is NOT recoverable from the tree, and an"
        " archive folder holds one copy per session uuid, so superseded versions"
        " are not restored either"
    )
    print(f"{report.summary()}{' (dry run, nothing written)' if dry_run else ''}")
    if dry_run:
        print(f"reindex: would write {target / 'catalog.sqlite'}")
    return 1 if report.failed else 0


def _print_plan(plan: relocate.RelocatePlan, header: str) -> None:
    """One rendering of a relocate plan, shared by the dry-run and the apply path (R9)."""
    print(header)
    for edit in plan.edits:
        print(f"  {edit.kind}: {edit.target}: {edit.detail}")


def _run_relocate(args: Sequence[str]) -> int:
    """`ccw relocate <repo> --to <new> [--apply] [--yes]` (DESIGN section 11).

    Dry-run is the DEFAULT: without --apply it prints the plan (including the target
    path) and mutates nothing outside the warehouse; it reads the catalog only when one
    already exists, so a dry-run never materializes state. --apply is gated behind an
    explicit yes (--yes or an
    interactive prompt); a non-TTY stdin without --yes aborts having changed nothing
    (R13/F10). A refusal from the pre-flight (existing target, cross-device, unwritable
    inventory) names the item on stderr with the Error: contract and exits 1 having
    mutated nothing; a content-rewrite failure halts the container renames (F7)."""
    rest = args[1:]
    do_apply = "--apply" in rest
    assume_yes = "--yes" in rest
    claim_ambiguous = "--claim-ambiguous" in rest
    # Track which tokens a flag consumed so --to's operand can never be mistaken for the
    # positional <repo> (a mixed-up plan would collect consent for the wrong operation).
    new_str: str | None = None
    positionals: list[str] = []
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg == "--to":
            if i + 1 >= len(rest) or rest[i + 1].startswith("-"):
                print("Error: --to requires a path", file=sys.stderr)
                return 2
            new_str = rest[i + 1]
            i += 2
            continue
        if arg.startswith("--to="):
            new_str = arg[len("--to=") :]
        elif not arg.startswith("-"):
            positionals.append(arg)
        i += 1
    if not positionals:
        print("Error: relocate requires <repo>", file=sys.stderr)
        return 2
    if not new_str:
        print("Error: relocate requires --to <new-path>", file=sys.stderr)
        return 2
    repo_str = positionals[0]
    # Refuse BEFORE planning: with HOME unset every encoded-dir candidate and the
    # source-transcript guard go inert, so even the dry-run would print a plan that
    # cannot be honoured (ticket 12a finding 2, R5/F7).
    home_problem = relocate.home_error()
    if home_problem:
        print(f"Error: {home_problem}", file=sys.stderr)
        return 1
    config = load_config()
    repo_path, new_path = Path(repo_str), Path(new_str)
    plan = relocate.plan_relocate(config, repo_path, new_path, claim_ambiguous=claim_ambiguous)
    if not do_apply:
        _print_plan(plan, f"relocate (dry-run): {repo_path} -> {new_path}")
        # Count the edits this run would MAKE. Skips are printed above by name (R10) but
        # counting a refusal as planned work overstates the blast radius before consent.
        planned = relocate.planned_changes(plan)
        print(f"{len(planned)} edits planned; re-run with --apply to execute")
        return 0
    # SHOW the plan on the apply path too, before asking. Consent for a set the operator
    # never saw is not consent (R13); the edit list used to appear on the dry-run path
    # only, so the run that actually mutates the world was the silent one.
    _print_plan(plan, f"relocate: {repo_path} -> {new_path}")
    if not _consented(assume_yes, f"Relocate {repo_path} to {new_path}? [y/N] "):
        print("relocate aborted: no consent (use --yes)", file=sys.stderr)
        return 2
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    backup_dir = config.root / "backups" / stamp
    try:
        report = relocate.apply_relocate(
            config, plan, backup_dir=backup_dir, claim_ambiguous=claim_ambiguous
        )
    except Exception as exc:  # never a traceback over a partly-mutated world (R5/F7)
        print(f"Error: relocate failed: {exc}", file=sys.stderr)
        print(f"backups and journal (if written): {backup_dir}", file=sys.stderr)
        return 1
    if any(outcome.action == relocate.LOCK_HELD_ACTION for outcome in report.outcomes):
        print("relocate refused: lock held by a live holder", file=sys.stderr)
        return 2
    for outcome in report.outcomes:
        if outcome.action == "skipped":
            print(f"relocate skipped: {outcome.item}: {outcome.detail}", file=sys.stderr)
    failures = report.failures
    for outcome in failures:
        print(f"Error: {outcome.item}: {outcome.detail or outcome.action}", file=sys.stderr)
    if failures:
        # Say what WAS already changed and where the originals are, so a halted run is
        # recoverable by hand instead of leaving the operator to guess (F6/R10).
        changed = relocate.applied_changes(report)
        if changed:
            print(f"relocate halted after {len(changed)} change(s):", file=sys.stderr)
            for outcome in changed:
                print(f"  {outcome.action}: {outcome.item}", file=sys.stderr)
            print(f"originals and journal: {backup_dir}", file=sys.stderr)
        return 1
    # A file whose layout could not be preserved is NAMED, not merely counted: relocate
    # promised to rewrite path refs, so any extra transformation has to be visible (F6/R10).
    for outcome in report.outcomes:
        if outcome.action == "rewritten" and (outcome.detail or "").startswith("reformatted"):
            print(f"relocate {outcome.detail.split(' ->')[0]}: {outcome.item}", file=sys.stderr)
    # CHANGES, not outcomes: skipped entries were reported by name above and must not be
    # counted as things this run did (F6 - the number has to mean what it says).
    print(f"relocate: {repo_path} -> {new_path} ({len(relocate.applied_changes(report))} changes)")
    return 0


def _share_flags(rest: Sequence[str]) -> tuple[list[str], str | None, bool, bool]:
    """Split `ccw share` args into (session_keys, out_dir, allow_findings, exposed).

    Positional non-flag args are s:<key> session keys; `--out DIR` names the destination;
    `--allow-findings` ships secret-shaped content verbatim; `--EXPOSED` opens the
    unscrubbed-publish comparison gate (DESIGN section 9 amendment)."""
    sessions: list[str] = []
    out: str | None = None
    allow = False
    exposed = False
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg == "--out":
            out = rest[i + 1] if i + 1 < len(rest) else None
            i += 2
        elif arg.startswith("--out="):
            out = arg[len("--out=") :]
            i += 1
        elif arg == "--allow-findings":
            allow = True
            i += 1
        elif arg == "--EXPOSED":
            exposed = True
            i += 1
        elif arg in ("--since", "--until"):
            i += 2  # the value belongs to the flag, never to the session list
        elif arg.startswith(("--since=", "--until=")):
            i += 1
        elif not arg.startswith("-"):
            sessions.append(arg)
            i += 1
        else:
            i += 1
    return sessions, out, allow, exposed


def _exposed_choice() -> str:
    """The --EXPOSED three-way gate. A non-TTY (pipe, cron, here-string) is NEVER
    consent: it returns 'A' (abort). Typing the literal word EXPOSED -> 'E';
    's'/'scrubbed' -> 'S'; anything else -> 'A'."""
    if not sys.stdin.isatty():
        return "A"
    try:
        answer = sys.stdin.readline()
    except (OSError, EOFError):
        return "A"
    stripped = answer.strip()
    if stripped == "EXPOSED":
        return "E"
    if stripped.lower() in ("s", "scrubbed"):
        return "S"
    return "A"


def _run_share_exposed(
    config: Config,
    sessions: list[str],
    out_path: Path,
    window: "share.WindowFilter | None" = None,
) -> int:
    """The `ccw share ... --EXPOSED` gate: render a scrubbed and an unscrubbed site
    to staging, print the byte-size + redaction comparison, and publish per the
    operator's typed choice. Nothing reaches --out until they confirm; a non-TTY
    aborts (DESIGN section 9 amendment, 2026-07-23)."""
    comparison = share.prepare_comparison(config, tuple(sessions), window)
    warn = sys.stderr
    print("!! --EXPOSED: this would publish UNSCRUBBED content. Nothing published yet.", file=warn)
    print("   Both versions rendered for comparison:", file=warn)
    print(f"     SCRUBBED (normal): {comparison.scrubbed_dir}", file=warn)
    print(f"     EXPOSED  (raw):    {comparison.exposed_dir}", file=warn)
    print(f"   {'session':<30}{'scrubbed':>11}{'exposed':>11}{'delta':>9}", file=warn)
    for label, scrubbed_bytes, exposed_bytes in comparison.per_session:
        delta = exposed_bytes - scrubbed_bytes
        print(
            f"   {label[:30]:<30}{scrubbed_bytes:>11,}{exposed_bytes:>11,}{delta:>+9,}",
            file=warn,
        )
    print(f"   redactions scrubbing removes: {len(comparison.hits)}", file=warn)
    print(f"   secret-shaped findings:       {len(comparison.findings)}", file=warn)
    print(f"   report: {comparison.scrubbed_dir / 'redaction-report.json'}", file=warn)
    print("   [E] publish EXPOSED to --out  (type EXPOSED to confirm)", file=warn)
    print("   [S] publish SCRUBBED to --out", file=warn)
    print("   [A] abort, publish nothing", file=warn)
    print("   > ", end="", file=warn)
    choice = _exposed_choice()
    if choice == "A":
        share.discard_comparison(comparison)
        print("share --EXPOSED: aborted, nothing published.", file=sys.stderr)
        return 1
    share.commit_comparison(comparison, out_path, keep_exposed=choice == "E")
    kept = "EXPOSED + SCRUBBED" if choice == "E" else "SCRUBBED only"
    print(f"share --EXPOSED: published {kept} -> {out_path}")
    return 0


def _run_share(args: Sequence[str]) -> int:
    """`ccw share s:<key> ... --out DIR [--allow-findings]`: sanitized static-site export.

    Redaction runs on copies only; the store and personal projections stay full fidelity
    (R4). A secret-shaped finding aborts the whole share (nothing written) and exits
    non-zero unless --allow-findings ships it verbatim (DESIGN section 9). A short with no
    current/visible head is skipped and named, and makes the exit non-zero (R10), while
    the resolvable sessions are still shared."""
    rest = args[1:]
    sessions, out, allow, exposed = _share_flags(rest)
    window, problem = _window_flags(rest)
    if problem is not None:
        print(f"Error: {problem}", file=sys.stderr)
        return 1
    windowed = window != (None, None)
    if sessions and windowed:
        print(
            "Error: ccw share selects by s:<key> hashes OR by --since/--until, "
            "never both; pick one",
            file=sys.stderr,
        )
        return 1
    if not out:
        print("Error: ccw share requires --out DIR", file=sys.stderr)
        return 2
    if not sessions and not windowed:
        print(
            "Error: ccw share requires at least one s:<key> or a --since/--until window",
            file=sys.stderr,
        )
        return 2
    out_path = Path(out)
    if _out_under_warehouse(out):
        print(
            "Error: --out must not be inside the warehouse store or projections",
            file=sys.stderr,
        )
        return 2
    if out_path.exists() and not out_path.is_dir():
        print(f"Error: --out {out_path} exists and is not a directory", file=sys.stderr)
        return 2
    if exposed:
        # The unscrubbed-publish gate owns its own comparison + consent + writes.
        keep = functools.partial(in_window, window=window) if windowed else None
        return _run_share_exposed(load_config(), sessions, out_path, keep)
    # Refuse to write into a populated dir we do not recognize as a prior share, so a
    # stray --out never overwrites unrelated files (F9-conservative; the export deletes
    # nothing, but it does overwrite its own filenames).
    if (
        out_path.is_dir()
        and any(out_path.iterdir())
        and not (out_path / "redaction-report.json").exists()
    ):
        print(
            f"Error: --out {out_path} is not empty and is not a prior share; "
            "point --out at a new or previously-shared directory",
            file=sys.stderr,
        )
        return 2
    config = load_config()
    keep = functools.partial(in_window, window=window) if windowed else None
    report = share.share(
        config, tuple(sessions), out_path, allow_findings=allow, window=keep,
        timezone=_flag_value(rest, "zone"),
    )
    if report.findings and not allow:
        for finding in report.findings:
            print(
                f"share: secret-shaped {finding.pattern} in {finding.file} line "
                f"{finding.line}; nothing written. Re-run with --allow-findings to ship it.",
                file=sys.stderr,
            )
        return 1
    for key in report.skipped:
        print(f"share: skipped {key}: no current session", file=sys.stderr)
    for key in report.errored:
        print(f"share: error on {key}: could not read or write session", file=sys.stderr)
    shared = len(sessions) - len(report.skipped) - len(report.errored)
    print(f"share: {shared} sessions, {len(report.hits)} redactions -> {report.out_dir}")
    return 1 if (report.skipped or report.errored) else 0


# Per-verb help: (verb -> (verb-specific options, takes the content flags)).
#
# The dispatcher consults this BEFORE handing a verb its arguments, so `-h` can
# never reach code that does work. That single point is the fix, not ten
# scattered checks: on 2026-08-01 eight of the ten verbs had no check at all and
# `ccw sweep -h` performed a real sweep of 13,836 sessions. A per-verb guard is
# only ever as complete as whoever remembered to add it; this one is structural,
# and test_help_is_inert enumerates _VERBS so a new verb is covered on arrival.
_VERB_OPTIONS: dict[str, tuple[tuple[tuple[str, str], ...], bool]] = {
    "hook": ((("(stdin)", "a SessionEnd JSON payload on standard input"),), False),
    "sweep": (
        (
            ("--source DIR", "walk DIR instead of ~/.claude/projects"),
            ("--since DATE", "import only sessions from DATE onward (local day)"),
            ("--until DATE", "import only sessions up to DATE, inclusive"),
            ("--dry-run", "name what a real run would import; writes NOTHING"),
            ("--quiet", "no stdout; failures and the exit code are unaffected"),
        ),
        False,
    ),
    "render": (
        (
            ("--session s:<key>", "(re)project one stored session"),
            ("<path>", "render a transcript outside the store"),
            ("--out DIR", "ad-hoc destination (default: a temp dir, path printed)"),
            ("--open", "open the rendered page in your browser when done"),
        ),
        True,
    ),
    "build": (
        (
            ("--rebuild", "regenerate every file, not just changed ones"),
            ("--include-hidden", "also project warmup / no-summary sessions"),
        ),
        True,
    ),
    "migrate": (
        (
            ("<archive>", "one-shot import of a legacy archive directory"),
            ("--retire", "rename the source aside as _RETIRED_<date>_<name> when done"),
            ("--yes", "skip the typed confirmation --retire is gated behind"),
        ),
        False,
    ),
    "import": (
        (
            ("--from DIR", "walk DIR and adopt every session transcript under it"),
            ("--dry-run", "name what a real run would import; writes NOTHING"),
            ("--quiet", "no stdout; failures and the exit code are unaffected"),
        ),
        False,
    ),
    "relocate": (
        (
            ("<repo> --to <new-path>", "move / rename a project across the external world"),
            ("--apply", "execute the plan (DRY-RUN IS THE DEFAULT; DESIGN 11)"),
            ("--yes", "skip the typed confirmation --apply is gated behind"),
            ("--claim-ambiguous", "adopt references this scan could not attribute"),
        ),
        False,
    ),
    "project": ((("<subcommand>", _PROJECT_SUBCOMMANDS),), False),
    "share": (
        (
            ("s:<key> ...", "sessions to publish, by short hash"),
            ("--out DIR", "destination directory (required)"),
            ("--since DATE", "select by window instead of hashes (local calendar day)"),
            ("--until DATE", "window end, inclusive (local calendar day)"),
            ("--allow-findings", "publish secret-shaped content verbatim"),
            ("--zone NAME", "IANA zone for folder names (default: [archive_timezone])"),
            ("--EXPOSED", "open the unscrubbed-publish comparison gate"),
        ),
        False,
    ),
    "status": ((("(no options)", "recent captures, counts, store size, last errors"),), False),
    "doctor": ((("(no options)", "is capture working, and if not since when"),), False),
    "repair": (
        (("--quiet", "no stdout on success; failures and the exit code are unaffected"),),
        False,
    ),
    "verify": ((("(no options)", "re-hash objects and cross-check the catalog"),), False),
    "archive": (
        (
            ("--to DIR", "build the archive tree at DIR (required; never the warehouse)"),
            ("--verify", "check an existing tree instead of building; writes nothing"),
            ("--zone NAME", "IANA zone for folder names (default: [archive_timezone])"),
            ("--rebuild", "regenerate every folder, not just changed ones"),
        ),
        # content=True: the archive is built by the same emitters as everything
        # else, so the same content flags govern it (R9). A tree whose rendering
        # ignored your configuration would be the one place it silently does not
        # apply.
        True,
    ),
    "reindex": (
        (
            ("--from DIR", "the archive tree to read (default: [archive_root])"),
            ("--to DIR", "where to write catalog.sqlite (default: the warehouse root)"),
            ("--dry-run", "report what a rebuild would find; writes NOTHING"),
        ),
        False,
    ),
    "version": ((("(no options)", "print the ccw version"),), False),
}


def _flag_spellings(spec: str) -> tuple[tuple[str, bool], ...]:
    """The flags one help SPEC accepts, as (name, takes_a_value).

    Specs are the human-readable strings the help already prints (`--source DIR`,
    `--EXPOSED`, `<repo> --to <new-path>`), so this reads them rather than keeping
    a second list that would drift. A `--flag` followed by a non-flag token takes
    a value; one followed by nothing, by another flag, or by `...` does not.
    """
    tokens = spec.split()
    found: list[tuple[str, bool]] = []
    for index, token in enumerate(tokens):
        if not token.startswith("--"):
            continue
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        takes_value = (
            following is not None and not following.startswith("-") and following != "..."
        )
        found.append((token, takes_value))
    return tuple(found)


def _known_flags(verb: str) -> tuple[frozenset[str], frozenset[str]]:
    """(flags taking a value, flags taking none) for `verb`.

    Derived from the SAME tables `_verb_help` prints from, which is the whole
    point (R9): a flag added later is accepted the day it is added rather than
    the day someone remembers this function. It is the unknown-flag twin of
    test_help_is_inert reading its verb list off the help text.
    """
    specific, content = _VERB_OPTIONS[verb]
    takes_value: set[str] = {"--config"}
    bare: set[str] = {"--no-config", *_HELP_FLAGS}
    for spec, _blurb in specific:
        for flag, wants_value in _flag_spellings(spec):
            (takes_value if wants_value else bare).add(flag)
    if content:
        for stem, _key, _variant, _blurb in _CONTENT_BOOL_FLAGS:
            bare.update((f"--{stem}", f"--no-{stem}"))
        for stem, _key, _variant, _values, _blurb in _CONTENT_VALUE_FLAGS:
            takes_value.add(f"--{stem}")
    return frozenset(takes_value), frozenset(bare)


def _unknown_flag(verb: str, args: Sequence[str]) -> str | None:
    """The first argument that looks like a flag and is not one, else None.

    THE DEFECT THIS CLOSES, measured 2026-08-03: `ccw sweep --totally-bogus-flag`
    exited 0, created the warehouse and imported a session, because every verb's
    hand-rolled parser looked only for the options it wanted and ignored the
    rest. Four of the five verbs sampled did real work on a typo. That is the
    same class as the 2026-08-01 `-h` incident, and it gets the same structural
    answer: one check at the dispatcher, before any handler runs, driven by a
    table nobody has to remember to update.

    Only arguments beginning with `-` are judged; everything else is a positional
    the verb owns. A known value-taking flag consumes the token after it, so a
    value that happens to start with `-` is not read as a flag and the verb's own
    parser still gets to refuse it with its own message (R5).
    """
    if verb not in _VERB_OPTIONS:
        # Internal verbs (section 7, ruled 2026-07-24) are deliberately absent
        # from the help tables and are machine-invoked, never typed.
        return None
    takes_value, bare = _known_flags(verb)
    bare = bare | _REFUSED_FLAGS.get(verb, frozenset())
    index = 0
    while index < len(args):
        argument = args[index]
        if argument.startswith("-"):
            name, separator, _value = argument.partition("=")
            if name not in takes_value and name not in bare:
                return argument
            if name in takes_value and not separator:
                index += 1
        index += 1
    return None


def _verb_help_if_asked(verb: str, args: Sequence[str]) -> str | None:
    """The verb's help text when these args ask for it, else None."""
    if verb not in _VERB_OPTIONS or not _wants_help(args):
        return None
    specific, content = _VERB_OPTIONS[verb]
    return _verb_help(verb, specific, content=content)


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch one ccw invocation; returns the process exit code."""
    args = list(argv) if argv is not None else sys.argv[1:]
    verb = args[0] if args else None
    if verb is None:
        return _bare()
    if verb in _VERSION_FLAGS:
        return _print_version()
    if verb in _HELP_FLAGS:
        print(_usage())
        return 0
    # Help BEFORE dispatch: no verb handler ever sees `-h`, so none of them can
    # act on it. Placed here rather than in each handler because completeness is
    # the whole property being bought.
    helped = _verb_help_if_asked(verb, args[1:])
    if helped is not None:
        print(helped)
        return 0
    # Unknown flags BEFORE dispatch, for exactly the same reason and one level
    # further: a handler that never sees an unrecognised option cannot act on a
    # typo. `ccw sweep --dry-runn` would otherwise perform the live sweep the
    # flag exists to rehearse (ticket 23, 2026-08-03).
    offender = _unknown_flag(verb, args[1:])
    if offender is not None:
        print(f"Error: unrecognised option {offender!r} for {verb!r}", file=sys.stderr)
        print(f"run 'ccw {verb} -h' for a verb's options", file=sys.stderr)
        return 2
    # `version` is dispatched here rather than beside `-v` above so that it, too,
    # passes the unknown-flag check; the leading-flag forms cannot carry options.
    if verb == "version":
        return _print_version()
    if verb == "hook":
        return _run_hook()
    if verb == "notify":
        return _run_notify(args)
    if verb == "sweep":
        return _run_sweep(args)
    if verb == "build":
        return _run_build(args)
    if verb == "render":
        return _run_render(args)
    if verb == "project":
        return _run_project(args)
    if verb == "migrate":
        return _run_migrate(args)
    if verb == "import":
        return _run_import(args)
    if verb == "status":
        return _run_status()
    if verb == "doctor":
        return _run_doctor()
    if verb == "repair":
        return _run_repair(args[1:])
    if verb == "verify":
        return _run_verify()
    if verb == "archive":
        return _run_archive(args)
    if verb == "reindex":
        return _run_reindex(args)
    if verb == "share":
        return _run_share(args)
    if verb == "relocate":
        return _run_relocate(args)
    # Unknown leading arg: a usage error, never a default-verb dispatch
    # (SPEC 2 DROP; test_unknown_verb_is_a_usage_error_not_a_dispatch).
    print(f"Error: unknown verb {verb!r}", file=sys.stderr)
    print(_usage(), file=sys.stderr)
    return 2
