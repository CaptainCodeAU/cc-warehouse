"""Command-line entry point for ccw / cc-warehouse (DESIGN section 7).

Slice 4 wires the `hook` verb through the shared capture pipeline plus a `render` stub
(the projection renderer lands in slice 8). Every other verb keeps its Phase-2 stub
behavior (Error on stderr, exit 1) until its slice lands.
"""

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from cc_warehouse import capture, notify, sweep
from cc_warehouse.config import Config, load_config


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
    if verb == "render":
        # Ad-hoc / detached projection renderer lands in slice 8; until then it behaves
        # like every other unimplemented verb so the rest of the suite stays red for the
        # stub reason, and the detached child spawned by capture is a harmless no-op.
        return _stub()
    return _stub()
