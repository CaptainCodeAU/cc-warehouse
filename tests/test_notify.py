"""Oracle tests: notification sinks (slice 4).

Contract: DESIGN section 12 (all sinks best-effort and non-blocking, webhook
events default ok+error with skipped silent, JSONL audit log O_APPEND); SPEC
section 5 (KEEP the best-effort posture: capture never fails on notification
infrastructure).
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cc_warehouse import notify
from cc_warehouse.config import Config
from conftest import (
    basic_session,
    hook_payload,
    run_ccw,
    session_count,
    warehouse_root,
    write_transcript,
)


class _Recorder(BaseHTTPRequestHandler):
    received: list[bytes] = []

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", "0"))
        _Recorder.received.append(self.rfile.read(length))
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


def start_server() -> tuple[ThreadingHTTPServer, int]:
    _Recorder.received = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def wait_for_posts(min_count: int, deadline_s: float = 10.0) -> list[bytes]:
    start = time.monotonic()
    while time.monotonic() - start < deadline_s:
        if len(_Recorder.received) >= min_count:
            break
        time.sleep(0.05)
    return list(_Recorder.received)


def webhook_config(root: Path, url: str, events: list[str] | None = None) -> None:
    lines = ['[[notify.webhook]]', 'name = "test-sink"', f'url = "{url}"']
    if events is not None:
        lines.append(f"events = {json.dumps(events)}")
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_text("\n".join(lines) + "\n")


def test_append_log_is_append_only_jsonl(tmp_path: Path) -> None:
    """DESIGN section 13: the audit log is the sanctioned O_APPEND exception;
    appends accumulate single JSON lines and never truncate."""
    config = Config(root=tmp_path / "warehouse")
    notify.append_log(config, {"status": "ok", "session": "s:abc"})
    notify.append_log(config, {"status": "error", "session": "s:def"})
    log = tmp_path / "warehouse" / "logs" / "capture.jsonl"
    lines = log.read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["status"] == "ok"
    assert second["status"] == "error"


def test_unreachable_webhook_never_breaks_capture(ccw_env: dict[str, str]) -> None:
    """Best-effort posture: a dead sink is logged, never raised; capture
    succeeds regardless."""
    webhook_config(warehouse_root(ccw_env), "http://127.0.0.1:9/unreachable")
    transcript = write_transcript(ccw_env, basic_session())
    result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
    assert result.code == 0, result.err
    assert session_count(ccw_env) == 1


def test_webhook_receives_ok_event_on_capture(ccw_env: dict[str, str]) -> None:
    server, port = start_server()
    try:
        webhook_config(warehouse_root(ccw_env), f"http://127.0.0.1:{port}/hook")
        transcript = write_transcript(ccw_env, basic_session())
        result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
        assert result.code == 0, result.err
        posts = wait_for_posts(1)
        assert posts, "no webhook POST arrived for a stored capture"
    finally:
        server.shutdown()


def test_webhook_silent_on_skip_by_default(ccw_env: dict[str, str]) -> None:
    """DESIGN section 12: default events are ok+error; skipped/unchanged is
    silent unless opted into."""
    import sqlite3

    from conftest import catalog_path

    server, port = start_server()
    try:
        webhook_config(warehouse_root(ccw_env), f"http://127.0.0.1:{port}/hook")
        transcript = write_transcript(ccw_env, basic_session())
        run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
        wait_for_posts(1)
        baseline = len(_Recorder.received)
        with sqlite3.connect(catalog_path(ccw_env)) as conn:
            conn.execute("UPDATE capture_event SET at = '2026-01-01T00:00:00Z'")
            conn.commit()
        result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
        assert result.code == 0
        time.sleep(2)
        assert len(_Recorder.received) == baseline
    finally:
        server.shutdown()


def test_webhook_events_list_can_opt_into_skips(ccw_env: dict[str, str]) -> None:
    import sqlite3

    from conftest import catalog_path

    server, port = start_server()
    try:
        webhook_config(
            warehouse_root(ccw_env),
            f"http://127.0.0.1:{port}/hook",
            events=["skipped_unchanged"],
        )
        transcript = write_transcript(ccw_env, basic_session())
        run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
        baseline = len(_Recorder.received)
        with sqlite3.connect(catalog_path(ccw_env)) as conn:
            conn.execute("UPDATE capture_event SET at = '2026-01-01T00:00:00Z'")
            conn.commit()
        result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
        assert result.code == 0
        posts = wait_for_posts(baseline + 1)
        assert len(posts) > baseline, "no webhook POST for an opted-in skip event"
    finally:
        server.shutdown()
