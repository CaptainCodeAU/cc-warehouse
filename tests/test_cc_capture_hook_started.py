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

from conftest import load_hook_module


class _Closer:
    def close(self) -> None:
        return None


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

    def fake_urlopen(*args: object, **kwargs: object) -> _Closer:
        calls.append("voice")
        return _Closer()

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
