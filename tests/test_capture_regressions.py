"""Contract-derived regression tests for the slice-4 fixer clusters (C1/C5/C2).

These are NOT part of the original frozen oracle suite: they pin behaviors the
slice-4 fixer established from SPEC/DESIGN (not from the code) so they cannot
silently regress later. Derived from DESIGN section 12 (notifications off the
hook's critical path; every sink best-effort) and SPEC section 3 (the four-rung
resolution ladder, unresolved included). See HARNESS section 8, slice-04 retro.
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

from conftest import (
    basic_session,
    catalog_rows,
    entry,
    hook_payload,
    jsonl,
    run_ccw,
    session_count,
    warehouse_root,
    write_transcript,
)


def _webhook_config(root: Path, url: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_text(f'[[notify.webhook]]\nname = "sink"\nurl = "{url}"\n')


class _BlockingSink(BaseHTTPRequestHandler):
    """Accepts the connection, then stalls the response past the connect budget.

    An inline POST would block on this until its ~2s timeout; a detached helper
    leaves the hook unaffected."""

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        time.sleep(5.0)
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


def test_webhook_post_is_off_the_hook_critical_path(ccw_env: dict[str, str]) -> None:
    """C1 / DESIGN 12: webhook POSTs run in a detached notify-only helper, so a
    blocking sink never delays the hook. If they ran inline the hook would stall on
    the connect budget; here it must return fast while the capture still stores."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BlockingSink)
    server.daemon_threads = True
    server.block_on_close = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        _webhook_config(warehouse_root(ccw_env), f"http://127.0.0.1:{port}/h")
        transcript = write_transcript(ccw_env, basic_session())
        start = time.monotonic()
        result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
        elapsed = time.monotonic() - start
        assert result.code == 0, result.err
        assert elapsed < 1.5, f"hook blocked {elapsed:.2f}s on a slow sink (inline POST?)"
        assert session_count(ccw_env) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_unresolved_rung_stores_rather_than_dropping(ccw_env: dict[str, str]) -> None:
    """C5 / SPEC 3: a capture with no payload cwd, no jsonl cwd, and an unusable
    transcript parent dir name is attributed to the _unresolved bucket and stored,
    never error-dropped (the did-we-lose-anything principle)."""
    data = jsonl(entry("user", "prompt with no cwd", "2026-01-05T10:00:00.000Z", cwd=None))
    transcript = write_transcript(ccw_env, data, encoded_dir=" ")
    result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, cwd=None))
    assert result.code == 0, result.err
    rows = cast(
        list[tuple[object, ...]],
        catalog_rows(ccw_env, "SELECT resolution_source FROM session"),
    )
    assert rows == [("unresolved",)]


def test_broken_audit_log_never_breaks_capture(ccw_env: dict[str, str]) -> None:
    """C2 / DESIGN 12: a failing log sink (logs/ is a regular file, so the append
    raises) is swallowed best-effort; the capture still stores its object, row, and
    the one stored event."""
    root = warehouse_root(ccw_env)
    root.mkdir(parents=True, exist_ok=True)
    (root / "logs").write_text("not a directory\n")
    transcript = write_transcript(ccw_env, basic_session())
    result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
    assert result.code == 0, result.err
    assert session_count(ccw_env) == 1
    actions = [
        cast(tuple[str], r)[0]
        for r in cast(
            list[tuple[object, ...]],
            catalog_rows(ccw_env, "SELECT action FROM capture_event"),
        )
    ]
    assert actions == ["stored"]
