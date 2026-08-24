"""Oracle tests: one item's capture failure must not abort the whole sweep batch
(ticket 31.4's other flagged gap, operator-approved follow-up 2026-08-24 -- see
Plans/majestic-floating-cray.md).

Contract: `harness/tickets/31-sweep-full-corpus-cost.md` section 31.4's own account of
the SWEEP path -- unlike the hook path's `_run_hook` (a top-level never-raise
boundary), `sweep()` has NO per-item exception boundary at all: one raise aborts
`sweep.sweep()` entirely, mid-batch, with nothing printed or logged, and everything
still queued in that run is simply never attempted (picked up by the next sweep
instead, not lost). R5/R10/F6: a failure must be named, logged, and the batch must
continue -- the exact pattern `_archive_subagent` already uses a few lines above
`_capture_item` in this same module.
"""

import sqlite3
from pathlib import Path

import pytest

import cc_warehouse.capture as capture_module
from conftest import basic_session, catalog_rows, run_cli, warehouse_root, write_transcript

UUID_A = "a4111111-1111-4111-8111-111111111111"
UUID_B = "b4222222-2222-4222-8222-222222222222"
UUID_C = "c4333333-3333-4333-8333-333333333333"


def test_one_bad_session_does_not_abort_the_rest_of_the_batch(
    ccw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE real incident this session found: a burst of sessions, one hits a
    transient failure, and (before this fix) every OTHER session still queued in
    the same sweep run was silently never attempted -- not because it also
    failed, but because the batch died on the first exception."""
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    write_transcript(ccw_env, basic_session(session_id=UUID_B), session_id=UUID_B)
    write_transcript(ccw_env, basic_session(session_id=UUID_C), session_id=UUID_C)

    real = capture_module.capture_transcript

    def flaky(config: object, path: Path, *, session_id: object, cwd: object) -> object:
        if path.stem == UUID_B:
            raise sqlite3.OperationalError("database is locked")
        return real(config, path, session_id=session_id, cwd=cwd)  # type: ignore[arg-type]

    monkeypatch.setattr(capture_module, "capture_transcript", flaky)

    result = run_cli(["sweep"])

    # R5/R10: a batch with a real failure in it exits non-zero -- that part is
    # correct and unchanged. What this test pins is that the OTHER two items were
    # still attempted and stored, not silently dropped along with the bad one.
    assert result.code == 1, result.out + result.err
    assert "b4222222" in result.err  # the bad item is named, not swallowed
    rows = catalog_rows(ccw_env, "SELECT session_uuid FROM session ORDER BY session_uuid")
    uuids = {r[0] for r in rows}  # type: ignore[index]
    assert uuids == {UUID_A, UUID_C}, (
        "the two healthy sessions must still be captured even though the batch "
        f"contained a failure; got {uuids}"
    )


def test_the_failure_is_named_by_item_and_logged_for_review(
    ccw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Answers the operator's explicit ask: a failed capture must be reviewable
    later, not just silently absorbed. Reuses the SAME durable log
    (`notify.append_log` -> `<warehouse_root>/logs/capture.jsonl`) the hook path's
    own stage-failure logging already writes to (ticket 31.4), rather than a new
    log file."""
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    def always_broken(config: object, path: Path, *, session_id: object, cwd: object) -> object:
        raise ValueError("simulated real bug, not contention")

    monkeypatch.setattr(capture_module, "capture_transcript", always_broken)

    result = run_cli(["sweep"])

    assert result.code == 1, result.out + result.err  # R5/R10: a real failure exits non-zero
    log = (warehouse_root(ccw_env) / "logs" / "capture.jsonl").read_text(encoding="utf-8")
    assert f"{UUID_A}.jsonl" in log
    assert "ValueError" in log
    assert "simulated real bug" in log
