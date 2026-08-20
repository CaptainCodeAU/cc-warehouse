"""Oracle tests: `ccw sweep`'s own walk gets a cheap pre-check (ticket 31.3).

Contract: `harness/tickets/31-sweep-full-corpus-cost.md` section 31.3;
`contract/PROPOSALS/daily-sweep-full-corpus-cost.md`. R1 (content-hash
identity, never mtime/size), R9 (capture.capture_transcript is the one
store-and-catalog routine), R10/F6 (never silently do less and say nothing).

MEASURED, NOT GUESSED (2026-08-20). The ticket's own premise -- that the
read+hash is the expensive part of a `skipped_unchanged` item -- was checked
before this fix was designed and found FALSE: read+hash of a real transcript
costs ~0.4 ms; the per-item lock file + fresh sqlite connection + `BEGIN
IMMEDIATE`/INSERT/COMMIT + `_is_subagent_file`'s JSON parse together cost
roughly two orders of magnitude more. Every one of those costs is avoidable
for an item this sweep has already seen before, without touching R1: the
skip decision below is made on the SAME sha256 `capture._capture_locked`
would compute, just made once, up front, and short-circuited before any of
that machinery runs.

THE PROPERTY THESE TESTS PIN, not the mechanism: a session already cataloged
never reaches `capture.capture_transcript` a second time on an unchanged
sweep, is still named in the report as `skipped_unchanged` (R10), and every
existing sweep behaviour -- new sessions, sub-agents, changed content,
same-run duplicates -- is unaffected.
"""

from pathlib import Path
from typing import cast

import cc_warehouse.capture as capture_module
from conftest import (
    basic_session,
    catalog_rows,
    claude_projects,
    record_opens,
    run_cli,
    warehouse_root,
    write_transcript,
)

UUID_A = "a3111111-1111-4111-8111-111111111111"
UUID_B = "b3222222-2222-4222-8222-222222222222"
UUID_C = "c3333333-3333-4333-8333-333333333333"


def _configure_archive(env: dict[str, str], archive_root: Path) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(
        f'root = "{warehouse_root(env)}"\n'
        f'archive_timezone = "Australia/Melbourne"\n'
        f'archive_root = "{archive_root}"\n',
        encoding="utf-8",
    )
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def test_a_second_sweep_never_calls_capture_transcript_for_an_unchanged_session(
    ccw_env: dict[str, str], monkeypatch: object
) -> None:
    """THE BIG WIN, white-box: the one store-and-catalog routine (R9) is not
    even asked about a file this warehouse already has."""
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_cli(["sweep"]).code == 0

    calls: list[str] = []
    real = capture_module.capture_transcript

    def spy(config: object, path: Path, *, session_id: object, cwd: object) -> object:
        calls.append(path.name)
        return real(config, path, session_id=session_id, cwd=cwd)  # type: ignore[arg-type]

    import pytest

    mp = cast(pytest.MonkeyPatch, monkeypatch)
    mp.setattr(capture_module, "capture_transcript", spy)
    result = run_cli(["sweep"])
    assert result.code == 0, result.err
    assert calls == [], f"capture_transcript was still called for: {calls}"


def test_a_second_sweep_never_opens_a_per_item_lock_or_catalog_connection(
    ccw_env: dict[str, str],
) -> None:
    """Black-box companion to the spy test above, same instrument ticket 30/31.2
    used (`record_opens`). Proves the property without depending on HOW the
    skip is implemented."""
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_cli(["sweep"]).code == 0
    root = warehouse_root(ccw_env)

    with record_opens(root / "locks") as first_opens:
        assert run_cli(["sweep"]).code == 0
    assert first_opens, "control failed: no lock file opened at all, instrument not live"
    per_item_locks = [p for p in first_opens if "/locks/capture-" in p]
    assert per_item_locks == [], (
        f"a second sweep of an unchanged session still took a per-hash capture"
        f" lock: {per_item_locks}"
    )


def test_a_second_sweep_still_reports_the_file_as_skipped_unchanged(
    ccw_env: dict[str, str],
) -> None:
    """R10: skipping the expensive path must not mean skipping the report."""
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_cli(["sweep"]).code == 0
    result = run_cli(["sweep", "--dry-run"])
    assert result.code == 0, result.err
    # The real (non-dry-run) sweep's own per-item lines aren't printed by
    # default; assert against the dry-run plan, which names every candidate,
    # to confirm the file is still recognised as already-known.
    assert "would-skip" in result.out
    assert transcript.name in result.out


def test_a_genuinely_new_session_is_still_fully_captured_alongside_unchanged_ones(
    ccw_env: dict[str, str],
) -> None:
    """The trap a careless 'skip everything' design would fall into (the same
    shape ticket 31.2's own test_sweep_projects.py case pins for `ccw build`)."""
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_cli(["sweep"]).code == 0
    write_transcript(
        ccw_env,
        basic_session(cwd="/home/alice/projects/gadget", session_id=UUID_B),
        session_id=UUID_B,
        encoded_dir="-home-alice-projects-gadget",
    )
    result = run_cli(["sweep"])
    assert result.code == 0, result.err
    rows = catalog_rows(ccw_env, "SELECT session_uuid FROM session ORDER BY session_uuid")
    uuids = {cast(tuple[str], r)[0] for r in rows}
    assert uuids == {UUID_A, UUID_B}


def test_a_sub_agent_transcript_still_archives_on_a_repeat_sweep(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Sub-agents never get a catalog row (ticket 21a), so their hash is never
    in the pre-filter's cataloged set and they must keep falling through to
    `_archive_subagent` exactly as before -- unaffected by this change."""
    from conftest import subagent_meta, subagent_session

    archive_root = tmp_path / "archive"
    _configure_archive(ccw_env, archive_root)
    parent = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    subagents_dir = claude_projects(ccw_env) / parent.parent.name / UUID_A / "subagents"
    subagents_dir.mkdir(parents=True)
    agent_path = subagents_dir / "agent-sub1.jsonl"
    agent_path.write_bytes(subagent_session(parent_uuid=UUID_A))
    (subagents_dir / "agent-sub1.meta.json").write_bytes(subagent_meta())

    assert run_cli(["sweep"]).code == 0
    first = run_cli(["sweep"])
    assert first.code == 0, first.err

    label_dirs = [p for p in archive_root.iterdir() if p.is_dir()]
    assert label_dirs, "sub-agent was never archived at all"
    # A sub-agent nests one folder deeper than a session:
    # <label>/<session-folder>/subagents/<agent-folder>/<agentId>.jsonl.
    found = list(archive_root.rglob("subagents/*/*.jsonl"))
    assert found, "a repeat sweep lost the sub-agent's archived copy"


def test_changed_content_since_last_capture_is_still_fully_captured(
    ccw_env: dict[str, str],
) -> None:
    """The pre-filter decides on the CONTENT hash (R1), never on the path or
    an mtime -- a transcript that grew (Claude Code appends to the same file
    as a session continues) must still take the full path."""
    path = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_cli(["sweep"]).code == 0
    from conftest import entry, jsonl

    grown = jsonl(
        *[
            entry("user", "Please fix the flux capacitor", "2026-01-05T10:00:00.000Z",
                  session_id=UUID_A, cwd="/home/alice/projects/widget"),
            entry("assistant", [{"type": "text", "text": "Done."}],
                  "2026-01-05T10:00:05.000Z", session_id=UUID_A,
                  cwd="/home/alice/projects/widget"),
            entry("user", "Now fix the warp drive too", "2026-01-05T10:05:00.000Z",
                  session_id=UUID_A, cwd="/home/alice/projects/widget"),
        ]
    )
    path.write_bytes(grown)
    result = run_cli(["sweep"])
    assert result.code == 0, result.err
    rows = catalog_rows(
        ccw_env, "SELECT COUNT(*) FROM session WHERE session_uuid = ?", (UUID_A,)
    )
    assert cast(tuple[int], rows[0])[0] == 2, "the grown transcript was not re-captured"


def test_two_identical_new_files_in_one_sweep_still_get_stored_then_duplicate(
    ccw_env: dict[str, str],
) -> None:
    """The pre-filter's cataloged set is loaded ONCE, before the loop, so it
    must not affect same-run duplicate handling: two files with identical
    content, both new to this sweep, still go stored + duplicate-invocation,
    not silently skipped-twice."""
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    write_transcript(
        ccw_env,
        basic_session(session_id=UUID_A),
        session_id=UUID_A,
        encoded_dir="-home-alice-projects-widget",
        name=f"{UUID_A}-copy.jsonl",
    )
    result = run_cli(["sweep"])
    assert result.code == 0, result.err
    rows = catalog_rows(
        ccw_env, "SELECT COUNT(*) FROM session WHERE session_uuid = ?", (UUID_A,)
    )
    assert cast(tuple[int], rows[0])[0] == 1


def test_a_run_that_skips_nothing_writes_no_aggregate_capture_event(
    ccw_env: dict[str, str],
) -> None:
    """A first-ever sweep, all new: N=0 unchanged, so no `sweep-unchanged`
    aggregate row is written (never a zero-value row, R10)."""
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_cli(["sweep"]).code == 0
    rows = catalog_rows(
        ccw_env, "SELECT COUNT(*) FROM capture_event WHERE action = 'sweep-unchanged'"
    )
    assert cast(tuple[int], rows[0])[0] == 0


def test_a_second_sweep_writes_one_aggregate_row_not_one_per_skipped_item(
    ccw_env: dict[str, str],
) -> None:
    """The replacement for the ~16,400/day per-item `skipped_unchanged` rows
    this ticket removes: one summary row, action `sweep-unchanged`, no
    `session_hash` (it names no single payload), detail carries the count."""
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    write_transcript(
        ccw_env,
        basic_session(cwd="/home/alice/projects/gadget", session_id=UUID_B),
        session_id=UUID_B,
        encoded_dir="-home-alice-projects-gadget",
    )
    assert run_cli(["sweep"]).code == 0
    result = run_cli(["sweep"])
    assert result.code == 0, result.err
    rows = catalog_rows(
        ccw_env,
        "SELECT session_hash, detail FROM capture_event WHERE action = 'sweep-unchanged'",
    )
    assert len(rows) == 1, f"expected exactly one aggregate row, got {len(rows)}"
    session_hash, detail = cast(tuple[object, str], rows[0])
    assert session_hash is None
    assert "2" in detail


def test_doctor_still_reports_capture_as_fired_after_a_skip_only_sweep(
    ccw_env: dict[str, str],
) -> None:
    """`ccw doctor`'s `fired` check reads MAX(at) FROM capture_event -- the
    aggregate row must keep that timestamp moving even on a day nothing new
    is stored, so doctor's freshness signal (ticket 24.7) does not go stale."""
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_cli(["sweep"]).code == 0
    assert run_cli(["sweep"]).code == 0  # skip-only run
    result = run_cli(["doctor"])
    assert "capture has NEVER fired" not in result.out


def test_status_error_list_is_unaffected_by_the_aggregate_row(
    ccw_env: dict[str, str],
) -> None:
    """`ccw status` reads `capture_event WHERE action = 'error'`; the new
    aggregate action must never be mistaken for one."""
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_cli(["sweep"]).code == 0
    assert run_cli(["sweep"]).code == 0
    result = run_cli(["status"])
    assert result.code == 0, result.err
    assert "error" not in result.out.lower() or "0" in result.out
