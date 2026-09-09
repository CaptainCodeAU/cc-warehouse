"""Oracle tests: the SessionEnd wrapper writes a `started` line BEFORE it runs
`ccw hook` (ticket 37 part B, first item).

Found 2026-09-06 on the live archive: a hook wrote the raw JSONL and 26
sub-agent folders into the archive and then died before the catalog row, the
`capture.jsonl` line and the wrapper's own `ok` line. Three instruments said
"no such capture" while the disk said "captured". The wrapper only ever logged
AFTER `ccw hook` returned, so a hook killed mid-run left nothing at all.

A `started` line with the session id turns that into a one-grep diagnosis: a
`started` with no matching `ok`/`error` is a hook that died. Nothing parses
this log's status values (the freshness check only appends to it; `ccw-watch`
reads `ccw doctor`, not this file), so a new value is safe to add.
"""

import io
import json
from pathlib import Path
from types import ModuleType

import pytest

from conftest import UrlopenStub, load_hook_module


def _lines(log: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def hook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Path]:
    module = load_hook_module("ccw_hook", "ccw-hook.py")
    log = tmp_path / "ccw-hook.log"
    monkeypatch.setattr(module, "LOG", log)
    monkeypatch.setattr(module, "VOICE_URL", "http://127.0.0.1:9/never")
    # A ccw that succeeds instantly, so the wrapper's normal path runs end to end.
    fake = tmp_path / "ccw"
    fake.write_text("#!/bin/sh\necho captured\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("CCW_BIN", str(fake))
    return module, log


def _run(module: ModuleType, monkeypatch: pytest.MonkeyPatch, payload: str) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    return int(module.main())


PAYLOAD = json.dumps({"session_id": "abc-123", "transcript_path": "/x/abc-123.jsonl"})


def test_started_is_written_first_and_every_line_carries_the_session(
    hook: tuple[ModuleType, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, log = hook
    assert _run(module, monkeypatch, PAYLOAD) == 0
    lines = _lines(log)
    assert [line["status"] for line in lines] == ["started", "ok"]
    assert [line["session"] for line in lines] == ["abc-123", "abc-123"]
    assert lines[0]["detail"] == "/x/abc-123.jsonl"
    assert {line["source"] for line in lines} == {"ccw-hook"}


def test_started_survives_a_payload_that_is_not_json(
    hook: tuple[ModuleType, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The line exists to be there when things go wrong; a bad payload is one
    of those things and must not be the reason there is no line."""
    module, log = hook
    _run(module, monkeypatch, "not json at all")
    started = _lines(log)[0]
    assert started["status"] == "started"
    assert started["session"] is None


def test_started_does_not_raise_the_voice_alert(
    hook: tuple[ModuleType, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _ = hook
    calls: list[str] = []

    def fake_urlopen(*args: object, **kwargs: object) -> UrlopenStub:
        calls.append("voice")
        return UrlopenStub()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    _run(module, monkeypatch, PAYLOAD)
    assert calls == []


def test_a_started_with_no_end_is_what_a_killed_hook_leaves(
    hook: tuple[ModuleType, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The diagnosis this line buys: a hook that dies inside `ccw hook` leaves
    `started` and nothing after it."""
    module, log = hook

    def die(*args: object, **kwargs: object) -> None:
        raise SystemExit(137)

    monkeypatch.setattr(module.subprocess, "run", die)
    with pytest.raises(SystemExit):
        _run(module, monkeypatch, json.dumps({"session_id": "s-killed"}))
    lines = _lines(log)
    assert len(lines) == 1
    assert lines[0]["status"] == "started"
    assert lines[0]["session"] == "s-killed"


# ---------------------------------------------------------------------------
# Ticket 42 #7: the wrapper reads `ccw hook`'s own outcome line instead of
# treating exit 0 as proof of success.
# ---------------------------------------------------------------------------


def _write_fake_ccw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout_line: str) -> None:
    fake = tmp_path / "ccw"
    fake.write_text(f"#!/bin/sh\necho '{stdout_line}'\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("CCW_BIN", str(fake))


def test_a_graceful_capture_error_is_logged_as_capture_error_not_ok(
    hook: tuple[ModuleType, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE GAP THIS CLOSES (Finding A, measured 2026-09-09): a `ccw hook` that
    exits 0 but printed a graceful `error` result used to log `ok` here, every
    time -- 1,238 real rows, zero ever said `error`. `ccw hook` now prints its
    real outcome; this wrapper must read it rather than trust the exit code
    alone."""
    module, log = hook
    _write_fake_ccw(tmp_path, monkeypatch, "error: unreadable transcript /x/abc.jsonl: boom")

    assert _run(module, monkeypatch, PAYLOAD) == 0
    lines = _lines(log)
    assert [line["status"] for line in lines] == ["started", "capture-error"]
    assert "unreadable transcript" in str(lines[-1]["detail"])


def test_a_graceful_capture_error_does_not_speak_a_second_time(
    hook: tuple[ModuleType, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ccw hook` already spoke this failure itself (notify.SPEAKING_STATUSES
    includes "error", and this wrapper hands it CCW_VOICE_URL/CCW_VOICE_ID) --
    the wrapper must not also POST to the voice URL, or the operator hears the
    same failure twice."""
    module, _ = hook
    _write_fake_ccw(tmp_path, monkeypatch, "error: unreadable transcript /x/abc.jsonl: boom")
    calls: list[str] = []

    def fake_urlopen(*args: object, **kwargs: object) -> UrlopenStub:
        calls.append("voice")
        return UrlopenStub()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    _run(module, monkeypatch, PAYLOAD)
    assert calls == []


def test_a_non_zero_exit_still_speaks(
    hook: tuple[ModuleType, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure `ccw hook` could NOT report itself (a non-zero exit) is a
    genuinely different case from a graceful `error` result, and must still
    reach the voice URL -- this wrapper's own voice gate must not have been
    widened by mistake."""
    module, _ = hook

    class Result:
        returncode = 1
        stdout = ""
        stderr = "boom"

    def fake_run(*args: object, **kwargs: object) -> Result:
        return Result()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    calls: list[str] = []

    def fake_urlopen(*args: object, **kwargs: object) -> UrlopenStub:
        calls.append("voice")
        return UrlopenStub()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    _run(module, monkeypatch, PAYLOAD)
    assert calls == ["voice"]


def test_old_ccw_with_no_outcome_line_still_logs_ok(
    hook: tuple[ModuleType, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deploy-order safety: an OLD `ccw hook` that prints nothing on success
    (pre-ticket-42-#7) must still log `ok`, so the tool reinstall and the
    plugin update can land in either order."""
    module, log = hook
    fake = tmp_path / "ccw"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("CCW_BIN", str(fake))

    assert _run(module, monkeypatch, PAYLOAD) == 0
    lines = _lines(log)
    assert [line["status"] for line in lines] == ["started", "ok"]
