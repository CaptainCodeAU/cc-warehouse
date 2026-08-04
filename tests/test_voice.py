"""Oracle tests: the voice sink (DESIGN section 12).

Contract: DESIGN 12 names four sinks - desktop, voice, webhooks, log - and puts
voice OFF the hook's critical path; R8 (no guarantee the suite does not prove);
F6 (never silent about loss); SPEC 5 (a notification POST carries a short connect
budget so a slow sink cannot stall the hook).

WHY THIS EXISTS. `config.voice_url` and `config.voice_id` have parsed since slice
13 and were consumed by NOTHING: `notify.py` implemented append_log,
post_webhooks and open_folder, and its own docstring said "desktop/voice sinks
join in slice 13". Slice 13 landed; they did not. A config key that parses,
is tested, and does nothing is exactly the F6 shape this project exists to
eliminate - the tool advertising a capability it does not have.

WHAT IS PORTED, and from where. The behaviour is taken from the frozen specimen
at `claude-code-transcripts/src/claude_code_transcripts/notify.py:52`, which is
what actually spoke on this machine until 2026-07-24. Its `report()` decided:

    stored  -> desktop AND voice
    skipped -> desktop only, no voice
    failed  -> desktop AND voice

so success and failure speak and a duplicate stays silent. That is reproduced
here exactly, at the principal's instruction ("matching exactly what I had").
The transport is `urllib.request`, not the specimen's `curl` subprocess, because
this module already POSTs webhooks that way and a second HTTP idiom would be a
second thing to get wrong (R9).

NOT ported in this slice: the desktop sink. DESIGN 12 calls it "ALWAYS on
(locked)" and it is equally absent; it is named here so its absence is recorded
rather than forgotten.
"""

import json
import subprocess
import urllib.request
from typing import Any

import pytest

from cc_warehouse import notify
from cc_warehouse.config import Config, load_config
from conftest import basic_session, hook_payload, run_ccw, run_cli, write_transcript

VOICE_URL = "http://localhost:8888/notify"
VOICE_ID = "fTtv3eikoepIosk8dTZ5"


def configure(env: dict[str, str], *, voice: bool, voice_id: bool = True) -> None:
    cfg = __import__("pathlib").Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [f'root = "{env["CCW_ROOT"]}"']
    if voice:
        lines.append("[notify]")
        lines.append(f'voice_url = "{VOICE_URL}"')
        if voice_id:
            lines.append(f'voice_id = "{VOICE_ID}"')
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


class _Captured:
    """Records what would have been POSTed, instead of POSTing it."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(request: Any, timeout: float = 0.0) -> Any:  # noqa: ANN401
            self.posts.append(
                (str(request.full_url), json.loads(bytes(request.data).decode()))
            )

            class _Response:
                def read(self) -> bytes:
                    return b""

                def __enter__(self) -> "_Response":
                    return self

                def __exit__(self, *_: object) -> None:
                    return None

            return _Response()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def _config(env: dict[str, str]) -> Config:
    return load_config()


# ---------------------------------------------------------------------------
# The sink itself
# ---------------------------------------------------------------------------


def test_speak_posts_the_message_to_the_configured_url(
    ccw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(ccw_env, voice=True)
    captured = _Captured()
    captured.install(monkeypatch)

    notify.speak(_config(ccw_env), "Transcript captured to widget")

    assert len(captured.posts) == 1
    url, payload = captured.posts[0]
    assert url == VOICE_URL
    assert payload["message"] == "Transcript captured to widget"
    assert payload["voice_enabled"] is True


def test_speak_carries_the_voice_id_when_one_is_configured(
    ccw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(ccw_env, voice=True)
    captured = _Captured()
    captured.install(monkeypatch)
    notify.speak(_config(ccw_env), "hello")
    assert captured.posts[0][1]["voice_id"] == VOICE_ID


def test_speak_omits_the_voice_id_when_none_is_configured(
    ccw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The specimen sends the key only when set; a null id is not the same as
    the server's default and must not be sent as one."""
    configure(ccw_env, voice=True, voice_id=False)
    captured = _Captured()
    captured.install(monkeypatch)
    notify.speak(_config(ccw_env), "hello")
    assert "voice_id" not in captured.posts[0][1]


def test_speak_is_silent_when_no_url_is_configured(
    ccw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opt-in, exactly as the specimen: unset means nothing is attempted at all."""
    configure(ccw_env, voice=False)
    captured = _Captured()
    captured.install(monkeypatch)
    notify.speak(_config(ccw_env), "hello")
    assert captured.posts == []


def test_speak_never_raises_when_the_voice_server_is_down(
    ccw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """DESIGN 12: every sink is best-effort. A dead voice server is the common
    case (the server is a local process that may not be running)."""
    configure(ccw_env, voice=True)

    def explode(*_: object, **__: object) -> None:
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", explode)
    notify.speak(_config(ccw_env), "hello")  # must not raise


# ---------------------------------------------------------------------------
# WHICH events speak: success and failure, never a duplicate
# ---------------------------------------------------------------------------


def _run_helper(record: dict[str, object]) -> None:
    assert run_cli(["notify", "--record", json.dumps(record)]).code == 0


def test_a_successful_capture_speaks(
    ccw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(ccw_env, voice=True)
    captured = _Captured()
    captured.install(monkeypatch)
    _run_helper({"status": "ok", "session": "abc123", "project": "payload_cwd",
                 "message": "captured", "elapsed_ms": 12})
    assert len(captured.posts) == 1
    assert "captur" in captured.posts[0][1]["message"].lower()


def test_a_failed_capture_speaks_the_reason(
    ccw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """F6: a failure that says nothing is the shape this whole track exists to
    stop. Ten days of silent breakage is what it costs."""
    configure(ccw_env, voice=True)
    captured = _Captured()
    captured.install(monkeypatch)
    _run_helper({"status": "error", "session": None, "project": None,
                 "message": "unreadable transcript /tmp/x", "elapsed_ms": 3})
    assert len(captured.posts) == 1
    spoken = captured.posts[0][1]["message"]
    assert "fail" in spoken.lower()
    assert "unreadable transcript" in spoken


def test_an_unchanged_refire_stays_silent(
    ccw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The specimen spoke on stored and failed, and NOT on skipped. Re-ending the
    same session must not talk at you."""
    configure(ccw_env, voice=True)
    captured = _Captured()
    captured.install(monkeypatch)
    _run_helper({"status": "skipped_unchanged", "session": "abc123",
                 "project": None, "message": "unchanged", "elapsed_ms": 1})
    assert captured.posts == []


# ---------------------------------------------------------------------------
# It has to actually be reached from a real capture
# ---------------------------------------------------------------------------


def test_the_helper_is_spawned_for_voice_even_with_no_webhooks(
    ccw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE TRAP: the detached helper returned early when no webhook was
    configured, so a voice-only setup would have been wired up and never
    reached. Voice is the only sink most people configure."""
    configure(ccw_env, voice=True)
    spawned: list[list[str]] = []

    def fake_popen(argv: list[str], **_: object) -> object:
        spawned.append(list(argv))

        class _P:
            pid = 1

        return _P()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    transcript = write_transcript(ccw_env, basic_session())
    assert run_cli(["hook"], stdin=hook_payload(transcript)).code == 0

    assert any("notify" in argv for argv in spawned), (
        "the notify helper was never spawned, so voice could never fire"
    )


def test_no_helper_is_spawned_when_nothing_is_configured(
    ccw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unchanged behaviour: with neither webhooks nor voice there is nothing to
    do off-path, and spawning a process per capture to do nothing is waste."""
    configure(ccw_env, voice=False)
    spawned: list[list[str]] = []

    def fake_popen(argv: list[str], **_: object) -> object:
        spawned.append(list(argv))

        class _P:
            pid = 1

        return _P()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    transcript = write_transcript(ccw_env, basic_session())
    assert run_cli(["hook"], stdin=hook_payload(transcript)).code == 0
    assert not any("notify" in argv for argv in spawned)


def test_a_dead_voice_server_does_not_fail_the_capture(ccw_env: dict[str, str]) -> None:
    """End to end through the real hook, with a voice_url pointing at a port
    nothing is listening on: the capture still succeeds and still exits 0."""
    cfg = __import__("pathlib").Path(ccw_env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(
        f'root = "{ccw_env["CCW_ROOT"]}"\n[notify]\nvoice_url = "http://127.0.0.1:9/notify"\n',
        encoding="utf-8",
    )
    ccw_env["XDG_CONFIG_HOME"] = str(cfg.parent)
    transcript = write_transcript(ccw_env, basic_session())
    result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
    assert result.code == 0, result.err
