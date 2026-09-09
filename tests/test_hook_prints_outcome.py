"""Oracle tests: `ccw hook` prints one outcome line to stdout before returning,
always 0 (ticket 42 #7).

Nothing in `contract/SPEC.md`/`contract/DESIGN.md` locks this verb's stdout as
empty (checked before writing this); SPEC 2.6/F7 (never-raise, always exit 0)
is unchanged -- this line is additive, and `ccw-hook.py`'s wrapper already
discards stdout on today's `ok` path.
"""

import sqlite3
import stat

from conftest import (
    basic_session,
    catalog_path,
    hook_payload,
    run_ccw,
    write_transcript,
)

UUID_A = "aaaaaaaa-3333-4444-8555-666666666666"


def backdate_events(env: dict[str, str]) -> None:
    """Push existing capture events out of the 10s duplicate-suppression window
    (test_capture.py's own helper, duplicated rather than imported since it is
    module-local there)."""
    with sqlite3.connect(catalog_path(env)) as conn:
        conn.execute("UPDATE capture_event SET at = '2026-01-01T00:00:00Z'")
        conn.commit()


def test_a_fresh_capture_prints_ok_and_still_exits_zero(ccw_env: dict[str, str]) -> None:
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, session_id=UUID_A))
    assert result.code == 0
    assert result.out.strip() == "ok: captured"


def test_a_graceful_error_prints_error_and_still_exits_zero(ccw_env: dict[str, str]) -> None:
    """The exact case Finding A was about: `capture_transcript` returns an
    `error` result rather than raising (R5/R10) -- the exit code must stay 0
    (never-raise, F7), and the real outcome must now be visible on stdout."""
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    transcript.chmod(0)
    try:
        result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, session_id=UUID_A))
        assert result.code == 0, "the hook must never fail the session end (SPEC 2.6)"
        assert result.out.strip().startswith("error:")
        assert "unreadable transcript" in result.out
    finally:
        transcript.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_ccw_skip_hook_prints_skipped_disabled(ccw_env: dict[str, str]) -> None:
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    env = dict(ccw_env)
    env["CCW_SKIP_HOOK"] = "1"
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, session_id=UUID_A))
    assert result.code == 0
    assert result.out.strip() == "skipped_disabled"


def test_an_unchanged_refire_prints_skipped_unchanged(ccw_env: dict[str, str]) -> None:
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    payload = hook_payload(transcript, session_id=UUID_A)
    assert run_ccw(["hook"], ccw_env, stdin=payload).code == 0
    backdate_events(ccw_env)  # clear the 10s duplicate-invocation window

    result = run_ccw(["hook"], ccw_env, stdin=payload)
    assert result.code == 0
    assert result.out.strip() == "skipped_unchanged"


def test_a_duplicate_invocation_within_the_window_prints_it(ccw_env: dict[str, str]) -> None:
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    payload = hook_payload(transcript, session_id=UUID_A)
    assert run_ccw(["hook"], ccw_env, stdin=payload).code == 0

    result = run_ccw(["hook"], ccw_env, stdin=payload)
    assert result.code == 0
    assert result.out.strip() == "duplicate-invocation"
