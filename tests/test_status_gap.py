"""Oracle tests: the uncaptured gap, and `ccw status` reporting it (23b).

Contract: DESIGN section 7, `ccw status` row as amended 2026-08-03 ("plus the
UNCAPTURED GAP, how many sessions and sub-agents exist in the source tree with
no archive folder. Reads catalog + log + the source tree, read-only").

WHY THE FIGURE BELONGS IN THE PRODUCT. It was computed by throwaway script three
times in one day on 2026-08-03, and each script had to re-derive the same
comparison. It is also the number that makes the whole capture story legible: on
that day the warehouse held 13,836 sessions and the source tree held 1,857 the
archive had never seen, and nothing in `ccw` could say so.

INSTRUMENT, and its stated blind spot. The comparison is by UUID: a source
transcript is `<uuid>.jsonl` and an archive folder is `<stamp>_<uuid>`, so this
is a set difference over names with no file opened and nothing hashed. That is
deliberate, because `status` must stay cheap enough to run constantly. The blind
spot is a source file whose stem is not a bare UUID (Claude Code sometimes
writes `<uuid>.orphaned-<n>-<hash>.jsonl`); such a file reads as uncaptured even
when its payload is archived. Counting it as a gap is the safe direction to be
wrong in, and `ccw doctor` (23c) can afford the exact answer.
"""

from pathlib import Path

from conftest import (
    basic_session,
    run_ccw,
    subagent_session,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
UUID_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"


def configure(env: dict[str, str], archive_root: Path | None) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [f'root = "{warehouse_root(env)}"', f'archive_timezone = "{ZONE}"']
    if archive_root is not None:
        lines.append(f'archive_root = "{archive_root}"')
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def test_status_reports_sessions_the_archive_has_never_seen(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Two transcripts on disk, nothing swept: the gap is two and status says so."""
    configure(ccw_env, tmp_path / "archive")
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    write_transcript(ccw_env, basic_session(session_id=UUID_B), session_id=UUID_B)

    result = run_ccw(["status"], ccw_env)

    assert result.code == 0, result.err
    assert "2" in result.out, f"the gap of 2 is not reported: {result.out!r}"
    assert "uncaptured" in result.out.lower(), result.out


def test_the_gap_closes_after_a_sweep(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """THE PROPERTY THAT MAKES IT WORTH PRINTING: it goes to zero when the work
    is done, so a non-zero figure always means something is outstanding."""
    configure(ccw_env, tmp_path / "archive")
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    assert run_ccw(["sweep"], ccw_env).code == 0
    result = run_ccw(["status"], ccw_env)

    assert result.code == 0, result.err
    line = next(
        (ln for ln in result.out.splitlines() if "uncaptured" in ln.lower()), ""
    )
    assert line, f"no uncaptured line at all: {result.out!r}"
    assert "0 session" in line, f"gap did not close: {line!r}"


def test_sub_agents_are_counted_separately(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """They are not sessions (ruling (a) as amended by ticket 21) and there were
    1,420 of them outstanding on 2026-08-03, so folding them into one number
    would hide the larger half of the problem."""
    configure(ccw_env, tmp_path / "archive")
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    write_transcript(
        ccw_env,
        subagent_session(agent_id="a94d30c1d877f964d", parent_uuid=UUID_A),
        session_id=UUID_A,
        name="agent-a94d30c1d877f964d.jsonl",
    )

    result = run_ccw(["status"], ccw_env)

    assert result.code == 0, result.err
    line = next((ln for ln in result.out.splitlines() if "uncaptured" in ln.lower()), "")
    assert "1 session" in line, line
    assert "1 sub-agent" in line, line


def test_status_writes_nothing_to_the_source_tree(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Sources are read-only (F9). Computing a gap must not change the thing it
    is measuring."""
    configure(ccw_env, tmp_path / "archive")
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    projects = Path(ccw_env["HOME"]) / ".claude" / "projects"
    before = tree_snapshot(projects)

    run_ccw(["status"], ccw_env)

    assert tree_snapshot(projects) == before


def test_status_says_so_when_no_archive_is_configured(ccw_env: dict[str, str]) -> None:
    """With no archive_root there is no archive to be behind, and reporting every
    session as uncaptured would be alarming and false. Say which it is."""
    configure(ccw_env, None)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    result = run_ccw(["status"], ccw_env)

    assert result.code == 0, result.err
    line = next((ln for ln in result.out.splitlines() if "uncaptured" in ln.lower()), "")
    assert "no archive" in line.lower(), f"did not name the reason: {line!r}"


def test_non_transcript_files_are_not_counted(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The source tree carries `.meta.json` sidecars and stray files; only
    transcripts are sessions."""
    configure(ccw_env, tmp_path / "archive")
    projects = Path(ccw_env["HOME"]) / ".claude" / "projects" / "-home-alice-x"
    projects.mkdir(parents=True, exist_ok=True)
    (projects / "notes.txt").write_text("not a transcript", encoding="utf-8")
    (projects / "thing.meta.json").write_text("{}", encoding="utf-8")

    result = run_ccw(["status"], ccw_env)

    line = next((ln for ln in result.out.splitlines() if "uncaptured" in ln.lower()), "")
    assert "0 session" in line, line
