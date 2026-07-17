"""Oracle tests: the SessionEnd capture hook (slice 4).

Contract: SPEC section 2.6 (KEEP: stdin payload contract, kill switch,
never-raise posture, detached render, elapsed reporting) with DESIGN section 4
mechanics (hash-first identity, atomic store write, transactional catalog row,
duplicate-notification suppression); FINDINGS F1, F2, F3, F7, F9.

Frozen here (Phase 2 decisions): the duplicate-invocation suppression window is
10 seconds; resolution source labels are payload_cwd / jsonl_cwd /
transcript_dir / unresolved.
"""

import hashlib
import sqlite3
import subprocess
import time
from types import SimpleNamespace
from typing import cast

import pytest

from conftest import (
    DEFAULT_CWD,
    DEFAULT_UUID,
    basic_session,
    catalog_path,
    catalog_rows,
    claude_projects,
    entry,
    hook_payload,
    jsonl,
    run_ccw,
    run_cli,
    session_count,
    spawn_ccw,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)


def backdate_events(env: dict[str, str]) -> None:
    """Push existing capture events out of the duplicate-suppression window."""
    with sqlite3.connect(catalog_path(env)) as conn:
        conn.execute("UPDATE capture_event SET at = '2026-01-01T00:00:00Z'")
        conn.commit()


def test_hook_stores_object_row_and_event(ccw_env: dict[str, str]) -> None:
    data = basic_session()
    transcript = write_transcript(ccw_env, data)
    result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
    assert result.code == 0, result.err

    digest = hashlib.sha256(data).hexdigest()
    stored = warehouse_root(ccw_env) / "objects" / digest[:2] / f"{digest}.jsonl"
    assert stored.read_bytes() == data

    rows = cast(
        list[tuple[object, ...]],
        catalog_rows(
            ccw_env,
            "SELECT hash, session_uuid, cwd, resolution_source, summary FROM session",
        ),
    )
    assert rows == [
        (digest, DEFAULT_UUID, DEFAULT_CWD, "payload_cwd", "Please fix the flux capacitor")
    ]
    events = cast(
        list[tuple[object, ...]],
        catalog_rows(ccw_env, "SELECT action, elapsed_ms FROM capture_event"),
    )
    assert len(events) == 1
    action, elapsed = events[0]
    assert action == "stored"
    assert isinstance(elapsed, int) and elapsed >= 0


def test_hook_never_modifies_the_source_transcript(ccw_env: dict[str, str]) -> None:
    """F9: capture sources are read-only, forever."""
    transcript = write_transcript(ccw_env, basic_session())
    before = tree_snapshot(claude_projects(ccw_env))
    run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
    assert tree_snapshot(claude_projects(ccw_env)) == before


def test_kill_switch_skips_everything(ccw_env: dict[str, str]) -> None:
    """SPEC 2.6 KEEP: the env kill switch no-ops the hook."""
    transcript = write_transcript(ccw_env, basic_session())
    env = dict(ccw_env) | {"CCW_SKIP_HOOK": "1"}
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript))
    assert result.code == 0
    assert session_count(ccw_env) == 0


@pytest.mark.parametrize("payload", ["", "not json", '{"session_id": "x"}'])
def test_invalid_payload_exits_clean_without_raising(
    ccw_env: dict[str, str], payload: str
) -> None:
    """SPEC 2.6 KEEP: missing/invalid payload -> error notify, exit WITHOUT
    raising into the harness; conservative branch stores nothing (F7)."""
    result = run_ccw(["hook"], ccw_env, stdin=payload)
    assert result.code == 0
    assert "Traceback" not in result.err
    assert session_count(ccw_env) == 0


def test_missing_transcript_reports_error_and_stores_nothing(
    ccw_env: dict[str, str],
) -> None:
    payload = hook_payload(claude_projects(ccw_env) / "nope" / "missing.jsonl")
    result = run_ccw(["hook"], ccw_env, stdin=payload)
    assert result.code == 0
    assert "Traceback" not in result.err
    assert session_count(ccw_env) == 0
    log = warehouse_root(ccw_env) / "logs" / "capture.jsonl"
    assert log.exists()
    assert "error" in log.read_text()


def test_unchanged_refire_skips_by_hash_equality(ccw_env: dict[str, str]) -> None:
    """F1: the re-fire skip decision is hash equality against the catalog,
    never a size proxy; outcome reported as skipped_unchanged."""
    transcript = write_transcript(ccw_env, basic_session())
    run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
    backdate_events(ccw_env)
    result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
    assert result.code == 0
    assert session_count(ccw_env) == 1
    actions = [
        cast(tuple[str], r)[0]
        for r in cast(
            list[tuple[object, ...]], catalog_rows(ccw_env, "SELECT action FROM capture_event")
        )
    ]
    assert actions.count("stored") == 1
    assert "skipped_unchanged" in actions


def test_duplicate_invocation_within_window_is_suppressed(
    ccw_env: dict[str, str],
) -> None:
    """DESIGN section 4: both capture paths fire; the second invocation inside
    the window logs duplicate-invocation and emits no notifications."""
    transcript = write_transcript(ccw_env, basic_session())
    run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
    result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
    assert result.code == 0
    actions = [
        cast(tuple[str], r)[0]
        for r in cast(
            list[tuple[object, ...]], catalog_rows(ccw_env, "SELECT action FROM capture_event")
        )
    ]
    assert "duplicate-invocation" in actions
    assert session_count(ccw_env) == 1


def test_grown_transcript_is_captured_as_new_version(ccw_env: dict[str, str]) -> None:
    """DESIGN section 2: append-only growth hashes differently and becomes the
    session's new canonical version; all versions kept."""
    data = basic_session()
    transcript = write_transcript(ccw_env, data)
    run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
    backdate_events(ccw_env)

    grown = data + jsonl(entry("user", "one more prompt", "2026-01-05T11:00:00.000Z"))
    transcript.write_bytes(grown)
    result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
    assert result.code == 0
    assert session_count(ccw_env) == 2

    h_old = hashlib.sha256(data).hexdigest()
    h_new = hashlib.sha256(grown).hexdigest()
    rows = dict(
        cast(
            list[tuple[str, str | None]],
            catalog_rows(ccw_env, "SELECT hash, supersedes FROM session"),
        )
    )
    assert rows[h_old] is None
    assert rows[h_new] == h_old
    objects_dir = warehouse_root(ccw_env) / "objects"
    assert len(list(objects_dir.rglob("*.jsonl"))) == 2


def test_concurrent_hook_invocations_one_row_no_torn_files(
    ccw_env: dict[str, str],
) -> None:
    """F3: N simultaneous SessionEnd invocations for one session yield exactly
    one session row, one valid object, no torn files, and one stored event."""
    data = basic_session()
    transcript = write_transcript(ccw_env, data)
    payload = hook_payload(transcript)
    procs = [spawn_ccw(["hook"], ccw_env, payload) for _ in range(8)]
    for proc in procs:
        proc.wait(timeout=60)
        assert proc.returncode == 0

    assert session_count(ccw_env) == 1
    digest = hashlib.sha256(data).hexdigest()
    objects_dir = warehouse_root(ccw_env) / "objects"
    stored = list(objects_dir.rglob("*"))
    files = [p for p in stored if p.is_file()]
    assert [p.name for p in files] == [f"{digest}.jsonl"]
    assert files[0].read_bytes() == data
    actions = [
        cast(tuple[str], r)[0]
        for r in cast(
            list[tuple[object, ...]], catalog_rows(ccw_env, "SELECT action FROM capture_event")
        )
    ]
    assert actions.count("stored") == 1


def test_resolution_falls_back_to_jsonl_cwd(ccw_env: dict[str, str]) -> None:
    """SPEC section 3 KEEP: payload cwd -> first jsonl cwd -> transcript parent
    dir, each with a reported source label."""
    transcript = write_transcript(ccw_env, basic_session())
    result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, cwd=None))
    assert result.code == 0
    rows = cast(
        list[tuple[object, ...]],
        catalog_rows(ccw_env, "SELECT cwd, resolution_source FROM session"),
    )
    assert rows == [(DEFAULT_CWD, "jsonl_cwd")]


def test_resolution_falls_back_to_transcript_dir(ccw_env: dict[str, str]) -> None:
    data = jsonl(
        entry("user", "prompt with no cwd", "2026-01-05T10:00:00.000Z", cwd=None),
    )
    transcript = write_transcript(ccw_env, data, encoded_dir="-home-alice-projects-widget")
    result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, cwd=None))
    assert result.code == 0
    rows = cast(
        list[tuple[object, ...]],
        catalog_rows(ccw_env, "SELECT resolution_source FROM session"),
    )
    assert rows == [("transcript_dir",)]


def test_hook_spawns_detached_render_child(
    ccw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC 2.5/5 KEEP: a detached child (start_new_session, stdio to DEVNULL)
    renders `ccw render --session s:<key>`; capture never waits on it."""
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_popen(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    transcript = write_transcript(ccw_env, basic_session())
    result = run_cli(["hook"], stdin=hook_payload(transcript))
    assert result.code == 0

    render_calls = [
        (args, kwargs)
        for args, kwargs in calls
        if any("render" in str(part) for part in args)
    ]
    assert len(render_calls) == 1
    args, kwargs = render_calls[0]
    argv = [str(part) for part in cast(tuple[object, ...], args[0])]
    assert "--session" in argv
    assert any(part.startswith("s:") for part in argv)
    assert kwargs.get("start_new_session") is True
    assert kwargs.get("stdout") == subprocess.DEVNULL
    assert kwargs.get("stderr") == subprocess.DEVNULL


def test_skip_path_honors_open_folder_opt_in(
    ccw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC 2.6 KEEP: the skip branch still honors the open-folder opt-in."""
    from cc_warehouse import notify

    transcript = write_transcript(ccw_env, basic_session())
    run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript))
    backdate_events(ccw_env)

    opened: list[str] = []

    def record_open(config: object, path: object) -> None:
        opened.append(str(path))

    monkeypatch.setattr(notify, "open_folder", record_open)
    monkeypatch.setenv("CCW_OPEN_FOLDER", "1")
    result = run_cli(["hook"], stdin=hook_payload(transcript))
    assert result.code == 0
    assert opened, "open_folder was not invoked on the skip path"


def test_hook_is_fast_even_for_a_large_transcript(ccw_env: dict[str, str]) -> None:
    """BRAINSTORM capture lock: hash + store + catalog row in milliseconds; the
    slow rendering happens in the detached child. Budget: 10s wall for ~20MB
    including interpreter startup (generous; catches accidental rendering)."""
    big_line = entry("user", "x" * 100_000, "2026-01-05T10:00:00.000Z")
    data = jsonl(*([big_line] * 200))
    transcript = write_transcript(ccw_env, data)
    start = time.monotonic()
    result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript), timeout=30)
    elapsed = time.monotonic() - start
    assert result.code == 0
    assert elapsed < 10
