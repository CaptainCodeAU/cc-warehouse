"""Oracle tests: ccw sweep (slice 5).

Contract: DESIGN section 4 (same store routine per file, locks/sweep O_EXCL,
safe any time), section 13 (orphan adoption); SPEC sections 8 (agent-* default
exclusion) and 9 (batch failure posture); rules R10, R14; FINDINGS F3, F7, F9.
"""

import hashlib
import os
import stat
from pathlib import Path
from typing import cast

from conftest import (
    DEAD_PID,
    basic_session,
    catalog_rows,
    claude_projects,
    run_ccw,
    session_count,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)

UUID_A = "aaaaaaaa-1111-2222-3333-444444444444"
UUID_B = "bbbbbbbb-1111-2222-3333-444444444444"
UUID_C = "cccccccc-1111-2222-3333-444444444444"


def seed_two_sessions(env: dict[str, str]) -> tuple[Path, Path]:
    a = write_transcript(
        env,
        basic_session(cwd="/home/alice/projects/widget", session_id=UUID_A),
        session_id=UUID_A,
    )
    b = write_transcript(
        env,
        basic_session(cwd="/home/alice/projects/gadget", session_id=UUID_B),
        session_id=UUID_B,
        encoded_dir="-home-alice-projects-gadget",
    )
    return a, b


def test_sweep_captures_what_the_hook_missed(ccw_env: dict[str, str]) -> None:
    seed_two_sessions(ccw_env)
    write_transcript(
        ccw_env,
        basic_session(session_id=UUID_C),
        session_id=UUID_C,
        name=f"agent-{UUID_C}.jsonl",
    )
    result = run_ccw(["sweep"], ccw_env)
    assert result.code == 0, result.err
    assert session_count(ccw_env) == 2
    uuids = {
        cast(tuple[str], r)[0]
        for r in cast(
            list[tuple[object, ...]],
            catalog_rows(ccw_env, "SELECT session_uuid FROM session"),
        )
    }
    assert uuids == {UUID_A, UUID_B}


def test_sweep_is_idempotent(ccw_env: dict[str, str]) -> None:
    """F3/R14: a second sweep is a hash-idempotent no-op, one row per session."""
    seed_two_sessions(ccw_env)
    assert run_ccw(["sweep"], ccw_env).code == 0
    assert run_ccw(["sweep"], ccw_env).code == 0
    assert session_count(ccw_env) == 2


def test_sweep_never_modifies_the_source_tree(ccw_env: dict[str, str]) -> None:
    """F9: sweep sources are read-only."""
    seed_two_sessions(ccw_env)
    before = tree_snapshot(claude_projects(ccw_env))
    run_ccw(["sweep"], ccw_env)
    assert tree_snapshot(claude_projects(ccw_env)) == before


def test_sweep_refuses_to_run_beside_a_live_holder(ccw_env: dict[str, str]) -> None:
    """R14: locks/sweep with O_EXCL semantics; a live holder wins."""
    seed_two_sessions(ccw_env)
    lock = warehouse_root(ccw_env) / "locks" / "sweep"
    lock.parent.mkdir(parents=True)
    lock.write_text(str(os.getpid()))
    result = run_ccw(["sweep"], ccw_env)
    assert result.code != 0
    assert session_count(ccw_env) == 0
    assert lock.read_text().strip() == str(os.getpid())


def test_sweep_takes_over_a_stale_lock(ccw_env: dict[str, str]) -> None:
    """DESIGN section 13: a lock whose recorded PID is dead is stale."""
    seed_two_sessions(ccw_env)
    lock = warehouse_root(ccw_env) / "locks" / "sweep"
    lock.parent.mkdir(parents=True)
    lock.write_text(str(DEAD_PID))
    result = run_ccw(["sweep"], ccw_env)
    assert result.code == 0
    assert session_count(ccw_env) == 2


def test_sweep_continues_past_item_failures_and_names_them(
    ccw_env: dict[str, str],
) -> None:
    """F7/R10: an unreadable item is reported and left alone; the batch
    completes for everything else and the end report names the failure."""
    seed_two_sessions(ccw_env)
    broken = write_transcript(
        ccw_env,
        basic_session(session_id=UUID_C, cwd="/home/alice/projects/broken"),
        session_id=UUID_C,
        encoded_dir="-home-alice-projects-broken",
    )
    broken.chmod(0)
    try:
        result = run_ccw(["sweep"], ccw_env)
        assert result.code != 0
        assert session_count(ccw_env) == 2
        assert broken.name in result.out + result.err
    finally:
        broken.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_sweep_adopts_orphan_store_objects(ccw_env: dict[str, str]) -> None:
    """DESIGN section 13: a crash between store write and catalog row leaves an
    orphan object; sweep re-adopts it (objects are content-named, so this is safe)."""
    data = basic_session()
    digest = hashlib.sha256(data).hexdigest()
    orphan = warehouse_root(ccw_env) / "objects" / digest[:2] / f"{digest}.jsonl"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(data)
    result = run_ccw(["sweep"], ccw_env)
    assert result.code == 0
    rows = cast(
        list[tuple[object, ...]],
        catalog_rows(ccw_env, "SELECT hash FROM session"),
    )
    assert (digest,) in rows
