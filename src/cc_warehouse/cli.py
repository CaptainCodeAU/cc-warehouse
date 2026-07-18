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
from pathlib import Path
from typing import cast

from cc_warehouse import build, capture, catalog, notify, registry, status, store, sweep
from cc_warehouse.config import Config, load_config
from cc_warehouse.render import RenderOptions


def _stub() -> int:
    """Placeholder for a verb whose slice has not landed yet."""
    print("Error: not implemented", file=sys.stderr)
    return 1


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
    This is deliberately minimal (no argparse); the full flag layering lands in slice 13."""
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
    rebuild = "--rebuild" in rest
    include_hidden = "--include-hidden" in rest
    config = load_config()
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
    form; `--out DIR` names the ad-hoc destination. Deliberately minimal (no argparse);
    the full flag layering lands in slice 13."""
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


def _render_session(session_key: str) -> int:
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
    config = load_config()
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


def _render_options() -> RenderOptions:
    """Ad-hoc render honors the personal render config when a warehouse is configured,
    and falls back to defaults otherwise; it never opens the catalog or the store."""
    try:
        return build.render_options(load_config())
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


def _render_adhoc(source: str, out: str | None) -> int:
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
    build.write_projection(directory, data, _render_options(), force=False)
    if out is None:
        print(str(directory))
    return 0


def _run_render(args: Sequence[str]) -> int:
    """`ccw render`: dispatch the --session (catalog) and ad-hoc (path) forms."""
    session, out, source = _render_flags(args[1:])
    if session is not None:
        return _render_session(session)
    if source is not None:
        return _render_adhoc(source, out)
    print("Error: render requires --session s:<key> or a transcript path", file=sys.stderr)
    return 1


def _run_project(args: Sequence[str]) -> int:
    """`ccw project rename <id> <label>`: a label edit (DESIGN section 2); nothing on
    disk moves here, the next `ccw build` relocates the projection dirs. The wider
    project verb surface (list/show/move/merge) lands in later slices."""
    rest = args[1:]
    if not rest:
        print("Error: project requires a subcommand (rename)", file=sys.stderr)
        return 1
    if rest[0] != "rename":
        print(f"Error: unknown project subcommand {rest[0]!r}", file=sys.stderr)
        return 1
    if len(rest) < 3:
        print("Error: project rename requires <id> <label>", file=sys.stderr)
        return 1
    id_str, label = rest[1], rest[2]
    try:
        project_id = int(id_str)
    except ValueError:
        print(f"Error: project id must be an integer, got {id_str!r}", file=sys.stderr)
        return 1
    if not label.strip():
        print("Error: project rename requires a non-empty label", file=sys.stderr)
        return 1
    config = load_config()
    conn = catalog.open_catalog(config.root)
    try:
        exists = (
            conn.execute("SELECT 1 FROM project WHERE id = ?", (project_id,)).fetchone()
            is not None
        )
        if not exists:  # renaming a project that does not exist is an error, not a no-op
            print(f"Error: no project with id {project_id}", file=sys.stderr)
            return 1
        registry.rename_project(conn, project_id, label)
    finally:
        conn.close()
    return 0


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


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch one ccw invocation; returns the process exit code."""
    args = list(argv) if argv is not None else sys.argv[1:]
    verb = args[0] if args else None
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
    if verb == "status":
        return _run_status()
    if verb == "verify":
        return _run_verify()
    return _stub()
