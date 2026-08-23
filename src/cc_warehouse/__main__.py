"""`python -m cc_warehouse` entry point: the detached render and notify children are
spawned this way (SPEC section 2.5 / section 5). Thin wrapper; all logic lives in
cli.main. The one thing added here that main() itself does not do: an otherwise-uncaught
exception is logged before the process exits.

WHY THIS EXISTS, not decoration. This path's stdio is DEVNULL by SPEC (section 5,
locked verbatim: "all stdio to DEVNULL" for the detached child's Popen call), so an
exception escaping main() before reaching a verb's own error-notify path leaves
LITERALLY no trace anywhere -- confirmed live 2026-08-23: a captured session (JSONL +
catalog row both written, hook reported "ok") whose render child produced none of its
four generated files, and no crash report, no OOM/jetsam event, no sleep/wake
interruption, and no "error" line in logs/capture.jsonl. The exception happened
somewhere between `_render_session`'s own catalog lookup and its try/except, which is
exactly the gap this closes, without touching the locked stdio decision at all: the
child's stdio stays DEVNULL, only a durable log line gets added first.
"""

import sys

from cc_warehouse.cli import main


def _log_crash(exc: BaseException) -> None:
    """Best-effort: append one line to logs/capture.jsonl before this detached
    child's stdio (DEVNULL by SPEC) would otherwise discard the exception with
    no trace anywhere. Never raises -- a broken config here must not replace
    the original exception with a new one."""
    try:
        from datetime import UTC, datetime

        from cc_warehouse import notify
        from cc_warehouse.config import load_config

        config = load_config()
        notify.append_log(
            config,
            {
                "at": datetime.now(UTC).isoformat(),
                "status": "error",
                "session": None,
                "project": None,
                "message": f"detached child crashed ({' '.join(sys.argv[1:])}): {exc!r}",
                "elapsed_ms": None,
            },
        )
    except Exception:
        return


def _run() -> int:
    try:
        return main()
    except Exception as exc:
        _log_crash(exc)
        raise


if __name__ == "__main__":
    sys.exit(_run())
