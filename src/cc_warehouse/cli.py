"""Command-line entry point for ccw / cc-warehouse (DESIGN section 7).

Slice 8 wires the `build`, `render`, and `project rename` verbs onto the shared
build orchestration (build.write_projection / build.projection_dir are the single
projection implementation, R9). Every not-yet-landed verb keeps its Phase-2 stub
behavior (Error on stderr, exit 1) until its slice lands. This module holds no write
handle and removes nothing itself: build.py owns projection removal and the store
owns the one write primitive (R2/R4 fences).
"""

import json
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from cc_warehouse import (
    build,
    capture,
    catalog,
    migrate,
    notify,
    registry,
    relocate,
    share,
    status,
    store,
    sweep,
)
from cc_warehouse.config import Config, load_config
from cc_warehouse.render import RenderOptions

# The v1 verb table (DESIGN section 7). The order is the help listing order;
# every name here must appear in `ccw -h` (test_help_lists_every_v1_verb).
_VERBS: tuple[tuple[str, str], ...] = (
    ("hook", "capture a session from a SessionEnd payload on stdin"),
    ("sweep", "import transcripts the hook missed (--source DIR)"),
    ("render", "(re)build the 4 files for --session s:<key>, or an ad-hoc <path>"),
    ("build", "rebuild projections from the catalog (--rebuild, content flags)"),
    ("migrate", "one-shot import of a legacy archive"),
    ("relocate", "move / rename a project across the external world"),
    ("project", "list / show / rename / move / merge projects"),
    ("share", "build a sanitized static site for chosen sessions"),
    ("status", "recent captures, counts, store size, last errors"),
    ("verify", "re-hash objects and cross-check the catalog"),
    ("version", "print the ccw version"),
)

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
_FULL = "full"
_COMPACT = "compact"

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
)


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
            notify.open_folder(config, str(config.root / "projections"))
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
    config = load_config()
    report = sweep.sweep(config, source)
    if any(outcome.action == sweep.LOCK_HELD_ACTION for outcome in report.outcomes):
        print("sweep refused: lock held by a live holder", file=sys.stderr)
        return 2
    failures = report.failures
    for outcome in failures:
        print(f"sweep failed: {outcome.item}: {outcome.detail or outcome.action}", file=sys.stderr)
    stored = sum(1 for outcome in report.outcomes if outcome.action == "stored")
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
    return 0


def _run_build(args: Sequence[str]) -> int:
    """`ccw build`: project the catalog into projections/ (DESIGN sections 1, 6).

    Incremental by default; --rebuild regenerates every file, --include-hidden also
    projects warmup/no-summary sessions. A live locks/build holder makes build refuse
    without projecting anything (R14). Otherwise prints a one-line report and names any
    failed item (R10); exits non-zero when the build was refused or an item failed."""
    rest = args[1:]
    if _wants_help(rest):
        print(_verb_help(
            "build",
            (
                ("--rebuild", "regenerate every file, not just changed ones"),
                ("--include-hidden", "also project warmup / no-summary sessions"),
            ),
            content=True,
        ))
        return 0
    rebuild = "--rebuild" in rest
    include_hidden = "--include-hidden" in rest
    config = _load(rest)
    report = build.build(config, rebuild=rebuild, include_hidden=include_hidden)
    if any(outcome.action == build.BUILD_LOCK_HELD for outcome in report.outcomes):
        print("build refused: lock held by a live holder", file=sys.stderr)
        return 2
    built = sum(1 for outcome in report.outcomes if outcome.action == "built")
    failures = report.failures
    for outcome in failures:
        print(f"build failed: {outcome.item}: {outcome.detail or outcome.action}", file=sys.stderr)
    print(f"build: {len(report.outcomes)} sessions, {built} built, {len(failures)} failed")
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


def _render_session(session_key: str, rest: Sequence[str]) -> int:
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
        data = store.get(config.root, head.hash)
        build.write_projection(directory, data, build.render_options(config), force=False)
    except Exception as exc:  # the detached child's only surviving signal (DESIGN 4)
        try:
            notify.report(config, notify.NotifyEvent("error", short, None, repr(exc), None))
        except Exception:
            pass
        return 1
    if config.open_folder:
        try:
            notify.open_folder(config, str(directory))
        except Exception:
            pass
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


def _render_adhoc(source: str, out: str | None, rest: Sequence[str]) -> int:
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
    return 0


def _run_render(args: Sequence[str]) -> int:
    """`ccw render`: dispatch the --session (catalog) and ad-hoc (path) forms."""
    rest = args[1:]
    if _wants_help(rest):
        print(_verb_help(
            "render",
            (
                ("--session s:<key>", "(re)project one stored session"),
                ("<path>", "render a transcript outside the store"),
                ("--out DIR", "ad-hoc destination (default: a temp dir, path printed)"),
            ),
            content=True,
        ))
        return 0
    session, out, source = _render_flags(rest)
    if session is not None:
        return _render_session(session, rest)
    if source is not None:
        return _render_adhoc(source, out, rest)
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


def _run_status() -> int:
    """`ccw status`: recent captures, counts, store size, last errors (DESIGN section 7).

    A pure read surface: it prints status.status_text, which reads the catalog only and
    opens no stored payload under objects/ (R6/F5). Always exits 0; this verb reports the
    warehouse, it does not judge it."""
    config = load_config()
    print(status.status_text(config))
    return 0


def _run_verify() -> int:
    """`ccw verify`: re-hash objects against their names and cross-check the catalog.

    status.verify wraps store.verify_walk (the one hashing implementation, R9/F8) and
    reports corrupted objects, orphan objects (left in place, R4), and catalog rows whose
    object is missing. Each finding is named by its short hash on stderr so the digest is
    visible in the output; the verb exits non-zero when the store has any finding and 0
    when it is intact and cross-consistent. verify writes and removes nothing (R4)."""
    config = load_config()
    report = status.verify(config)
    findings = report.outcomes
    for outcome in findings:
        print(f"verify: {outcome.action} {outcome.item}: {outcome.detail}", file=sys.stderr)
    if not findings:
        print("verify: store intact and cross-consistent")
    return 1 if findings else 0


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


def _run_share_exposed(config: Config, sessions: list[str], out_path: Path) -> int:
    """The `ccw share ... --EXPOSED` gate: render a scrubbed and an unscrubbed site
    to staging, print the byte-size + redaction comparison, and publish per the
    operator's typed choice. Nothing reaches --out until they confirm; a non-TTY
    aborts (DESIGN section 9 amendment, 2026-07-23)."""
    comparison = share.prepare_comparison(config, tuple(sessions))
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
    sessions, out, allow, exposed = _share_flags(args[1:])
    if not out:
        print("Error: ccw share requires --out DIR", file=sys.stderr)
        return 2
    if not sessions:
        print("Error: ccw share requires at least one s:<key>", file=sys.stderr)
        return 2
    out_path = Path(out)
    if out_path.exists() and not out_path.is_dir():
        print(f"Error: --out {out_path} exists and is not a directory", file=sys.stderr)
        return 2
    if exposed:
        # The unscrubbed-publish gate owns its own comparison + consent + writes.
        return _run_share_exposed(load_config(), sessions, out_path)
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
    report = share.share(config, tuple(sessions), out_path, allow_findings=allow)
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


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch one ccw invocation; returns the process exit code."""
    args = list(argv) if argv is not None else sys.argv[1:]
    verb = args[0] if args else None
    if verb is None:
        return _bare()
    if verb in _VERSION_FLAGS or verb == "version":
        return _print_version()
    if verb in _HELP_FLAGS:
        print(_usage())
        return 0
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
    if verb == "status":
        return _run_status()
    if verb == "verify":
        return _run_verify()
    if verb == "share":
        return _run_share(args)
    if verb == "relocate":
        return _run_relocate(args)
    # Unknown leading arg: a usage error, never a default-verb dispatch
    # (SPEC 2 DROP; test_unknown_verb_is_a_usage_error_not_a_dispatch).
    print(f"Error: unknown verb {verb!r}", file=sys.stderr)
    print(_usage(), file=sys.stderr)
    return 2
