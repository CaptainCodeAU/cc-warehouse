"""Oracle tests: `ccw sweep --limit N` (ticket 28.3).

A real `~/.claude/projects` can run to tens of thousands of transcripts, and
there was no way to exercise a slice of one - every rehearsal or test run
walked the whole tree. `--limit N` caps `_walk_source`'s candidate list to the
first N transcripts in sorted (path) order, applied identically to a real
sweep and to `--dry-run` (R9: one walk implementation, one place the cap
lives). It bounds WALK candidates, never sessions stored: composes with the
already-known skip exactly as an unlimited sweep does, and a later,
higher-or-unlimited sweep still picks up whatever a limited run left behind -
the same "narrowing loses nothing" property `--since`/`--until` already have.

Contract: DESIGN section 4 (sweep), R5 (a malformed flag refuses loudly rather
than running unbounded or silently doing zero), R10 (batch failures are named).
"""

from typing import cast

from conftest import (
    basic_session,
    catalog_rows,
    run_ccw,
    session_count,
    write_transcript,
)

UUID_A = "a0000000-1111-2222-3333-444444444444"
UUID_B = "b0000000-1111-2222-3333-444444444444"
UUID_C = "c0000000-1111-2222-3333-444444444444"


def seed_three_sessions(env: dict[str, str]) -> None:
    """All three under the SAME project dir, so the walk's sort order is a
    plain UUID sort - the fixture this file relies on for a deterministic
    "which one got kept" answer."""
    for uuid in (UUID_A, UUID_B, UUID_C):
        write_transcript(env, basic_session(session_id=uuid), session_id=uuid)


def stored_uuids(env: dict[str, str]) -> set[str]:
    rows = catalog_rows(env, "SELECT session_uuid FROM session")
    return {cast(tuple[str], r)[0] for r in rows}


# --- caps a real sweep ----------------------------------------------------


def test_limit_caps_how_many_transcripts_are_stored(ccw_env: dict[str, str]) -> None:
    seed_three_sessions(ccw_env)
    result = run_ccw(["sweep", "--limit", "1"], ccw_env)
    assert result.code == 0, result.err
    assert session_count(ccw_env) == 1
    assert "1 stored" in result.out, result.out


def test_limit_picks_the_first_transcript_in_sorted_order(ccw_env: dict[str, str]) -> None:
    """Deterministic, not "some subset": the walk sorts, so the cap always
    keeps the same one for a given source tree."""
    seed_three_sessions(ccw_env)
    result = run_ccw(["sweep", "--limit", "1"], ccw_env)
    assert result.code == 0, result.err
    assert stored_uuids(ccw_env) == {UUID_A}


def test_limit_equal_to_the_spelling_form_also_works(ccw_env: dict[str, str]) -> None:
    """`--limit=N` is accepted the same as `--limit N`."""
    seed_three_sessions(ccw_env)
    result = run_ccw(["sweep", "--limit=2"], ccw_env)
    assert result.code == 0, result.err
    assert session_count(ccw_env) == 2


def test_limit_larger_than_the_source_tree_is_a_harmless_no_op(
    ccw_env: dict[str, str],
) -> None:
    seed_three_sessions(ccw_env)
    result = run_ccw(["sweep", "--limit", "100"], ccw_env)
    assert result.code == 0, result.err
    assert session_count(ccw_env) == 3


def test_a_later_unlimited_sweep_picks_up_what_a_limited_one_left(
    ccw_env: dict[str, str],
) -> None:
    """Narrowing a run must never be the thing that loses a session (the same
    property the --since/--until window already has)."""
    seed_three_sessions(ccw_env)
    first = run_ccw(["sweep", "--limit", "1"], ccw_env)
    assert first.code == 0, first.err
    assert session_count(ccw_env) == 1

    second = run_ccw(["sweep"], ccw_env)
    assert second.code == 0, second.err
    assert session_count(ccw_env) == 3
    assert stored_uuids(ccw_env) == {UUID_A, UUID_B, UUID_C}


# --- composes with --dry-run and --quiet ----------------------------------


def test_limit_composes_with_dry_run(ccw_env: dict[str, str]) -> None:
    seed_three_sessions(ccw_env)
    result = run_ccw(["sweep", "--dry-run", "--limit", "1"], ccw_env)
    assert result.code == 0, result.err
    assert f"{UUID_A}.jsonl" in result.out
    assert f"{UUID_B}.jsonl" not in result.out
    assert f"{UUID_C}.jsonl" not in result.out
    assert session_count(ccw_env) == 0, "--dry-run must still write nothing"


def test_limit_composes_with_quiet(ccw_env: dict[str, str]) -> None:
    seed_three_sessions(ccw_env)
    result = run_ccw(["sweep", "--quiet", "--limit", "1"], ccw_env)
    assert result.code == 0, result.err
    assert not result.out.strip(), f"--quiet still printed: {result.out!r}"
    assert session_count(ccw_env) == 1


# --- usage errors ----------------------------------------------------------


def test_limit_with_no_value_is_a_usage_error(ccw_env: dict[str, str]) -> None:
    seed_three_sessions(ccw_env)
    result = run_ccw(["sweep", "--limit"], ccw_env)
    assert result.code == 2
    assert "--limit" in result.err
    assert session_count(ccw_env) == 0


def test_limit_with_a_non_numeric_value_is_a_usage_error(ccw_env: dict[str, str]) -> None:
    seed_three_sessions(ccw_env)
    result = run_ccw(["sweep", "--limit", "many"], ccw_env)
    assert result.code == 2
    assert "--limit" in result.err
    assert session_count(ccw_env) == 0


def test_limit_zero_is_a_usage_error_not_a_silent_no_op(ccw_env: dict[str, str]) -> None:
    """A silent `--limit 0` would look identical to a fresh, empty warehouse;
    refusing loudly (R5) is what tells the two apart."""
    seed_three_sessions(ccw_env)
    result = run_ccw(["sweep", "--limit", "0"], ccw_env)
    assert result.code == 2
    assert "--limit" in result.err
    assert session_count(ccw_env) == 0


def test_limit_negative_is_a_usage_error(ccw_env: dict[str, str]) -> None:
    seed_three_sessions(ccw_env)
    result = run_ccw(["sweep", "--limit", "-1"], ccw_env)
    assert result.code == 2
    assert "--limit" in result.err
    assert session_count(ccw_env) == 0


# --- help surface -----------------------------------------------------------


def test_limit_is_listed_in_sweep_help(ccw_env: dict[str, str]) -> None:
    result = run_ccw(["sweep", "-h"], ccw_env)
    assert result.code == 0
    assert "--limit" in result.out
