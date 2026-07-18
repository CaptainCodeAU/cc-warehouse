"""Contract-derived regression tests for ccw sweep (slice 5, post-review).

These are NOT the frozen oracle suite (tests/test_sweep.py); they are the
operator-written, contract-derived regressions the HARNESS precedent calls for
(slice-03/04), pinning behaviors the reviewers confirmed but the oracle did not
cover. Cited in harness/tickets/05-sweep.md.

- RT-C1 (R5/F7): an unreadable source SUBDIRECTORY is a named failure, never a
  silent under-capture (rglob swallowed it; the fix walks with os.walk onerror).
- RT-C2 (R5): a malformed `--source` fails conservatively (reports, exits
  non-zero, captures nothing) instead of silently sweeping the default tree.
- RT-C5 (R3/SPEC-3): a swept session attributes to the right project from the
  transcript's own cwd (sweep passes no payload cwd; capture resolves the ladder),
  pinning that swept sessions are never mis-bucketed to `_unresolved`.
"""

import stat
from typing import cast

from conftest import (
    basic_session,
    catalog_rows,
    claude_projects,
    run_ccw,
    session_count,
    write_transcript,
)

UUID_A = "aaaaaaaa-1111-2222-3333-444444444444"
UUID_B = "bbbbbbbb-1111-2222-3333-444444444444"
UUID_V = "dddddddd-1111-2222-3333-444444444444"


def _seed_two(env: dict[str, str]) -> None:
    write_transcript(
        env,
        basic_session(cwd="/home/alice/projects/widget", session_id=UUID_A),
        session_id=UUID_A,
    )
    write_transcript(
        env,
        basic_session(cwd="/home/alice/projects/gadget", session_id=UUID_B),
        session_id=UUID_B,
        encoded_dir="-home-alice-projects-gadget",
    )


def test_sweep_names_an_unreadable_source_subdir(ccw_env: dict[str, str]) -> None:
    """RT-C1 (R5/F7): a permission-denied source subdirectory is reported by name,
    makes the exit non-zero, and does NOT stop the readable siblings from capturing.
    A silent skip (rglob's behavior) would under-capture yet report success."""
    _seed_two(ccw_env)
    vault = claude_projects(ccw_env) / "-home-alice-projects-vault"
    vault.mkdir(parents=True)
    write_transcript(
        ccw_env,
        basic_session(cwd="/home/alice/projects/vault", session_id=UUID_V),
        session_id=UUID_V,
        encoded_dir="-home-alice-projects-vault",
    )
    vault.chmod(0)
    try:
        result = run_ccw(["sweep"], ccw_env)
        assert result.code != 0, result.out
        assert session_count(ccw_env) == 2
        assert vault.name in result.out + result.err
    finally:
        vault.chmod(stat.S_IRWXU)


def test_sweep_rejects_a_valueless_source_flag(ccw_env: dict[str, str]) -> None:
    """RT-C2 (R5): `ccw sweep --source` with no value must fail conservatively,
    capturing nothing, instead of silently sweeping the default ~/.claude/projects."""
    _seed_two(ccw_env)
    result = run_ccw(["sweep", "--source"], ccw_env)
    assert result.code != 0
    assert session_count(ccw_env) == 0


def test_sweep_rejects_an_empty_source_flag(ccw_env: dict[str, str]) -> None:
    """RT-C2 (R5): `--source ""` must not resolve to the cwd and sweep it; it fails
    conservatively and captures nothing."""
    _seed_two(ccw_env)
    result = run_ccw(["sweep", "--source", ""], ccw_env)
    assert result.code != 0
    assert session_count(ccw_env) == 0


def test_swept_session_attributes_to_its_project(ccw_env: dict[str, str]) -> None:
    """RT-C5 (R3/SPEC-3): a swept session resolves to the right project from the
    transcript's own cwd (sweep supplies no payload cwd). The two seeds land in two
    distinct projects via the jsonl_cwd rung, never the _unresolved bucket."""
    _seed_two(ccw_env)
    assert run_ccw(["sweep"], ccw_env).code == 0
    rows = cast(
        list[tuple[object, ...]],
        catalog_rows(
            ccw_env,
            "SELECT session_uuid, cwd, resolution_source, project_id FROM session",
        ),
    )
    by_uuid = {cast(str, r[0]): r for r in rows}
    assert set(by_uuid) == {UUID_A, UUID_B}
    _, a_cwd, a_src, a_pid = by_uuid[UUID_A]
    _, b_cwd, b_src, b_pid = by_uuid[UUID_B]
    assert a_cwd == "/home/alice/projects/widget"
    assert b_cwd == "/home/alice/projects/gadget"
    assert a_src == "jsonl_cwd"
    assert b_src == "jsonl_cwd"
    assert a_pid is not None and b_pid is not None
    assert a_pid != b_pid
