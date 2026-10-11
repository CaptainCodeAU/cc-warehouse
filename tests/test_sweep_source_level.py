"""Oracle tests: the stranded-sidecar pass reads a `--source` root at its real level
(W-20261011-A01).

FOUND 2026-10-11 by the A59 red-team review. The pass listed "project dirs" as the
children of whatever root the sweep was given. Pointed at one project dir, it took
that project's own subfolders (`memory/`, a session's `<uuid>/`) for projects and
planned their children as stranded sidecars: `memory/WORK` would have been copied
into `_not-sessions/stranded-sidecars/`. Pointed at `~/.claude`, it took
`projects/` for a project and every project dir for a stranded sidecar.

THE RULE: project dirs are counted from the default source tree when the walk root
is inside it or above it, and from the walk root otherwise (a copied tree elsewhere,
the old behaviour). `ccw sweep`, its dry run and `ccw status` share one helper
(`sweep.project_dirs`), so they cannot disagree (R9).
"""

from pathlib import Path

from test_project_memory_skip import ENCODED, UUID_A, configure, projects, put, session

from cc_warehouse import status, sweep
from conftest import run_ccw, write_transcript

UUID_STRANDED = "a5911111-2222-3333-4444-5555555555aa"


def tree(env: dict[str, str]) -> None:
    """One real session, a memory/ folder with a subfolder, and one genuinely
    stranded sidecar dir (a `<uuid>/tool-results/` with no `<uuid>.jsonl`)."""
    write_transcript(env, session(UUID_A), session_id=UUID_A)
    put(env, f"{ENCODED}/memory/WORK/notes.md", b"a note\n")
    put(env, f"{ENCODED}/{UUID_STRANDED}/tool-results/out.txt", b"output\n")


def stranded(report_outcomes: list[tuple[str, str, str]]) -> list[str]:
    return [item for item, _action, detail in report_outcomes if "no transcript" in detail]


def planned(env: dict[str, str], tmp_path: Path, root: Path) -> list[str]:
    cfg = configure(env, tmp_path / "archive", keep_objects=False)
    report = sweep.plan(cfg, root)
    return stranded([(o.item, o.action, o.detail) for o in report.outcomes])


def test_the_default_root_plans_only_the_real_stranded_dir(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    tree(ccw_env)
    assert planned(ccw_env, tmp_path, projects(ccw_env)) == [UUID_STRANDED]


def test_one_project_dir_as_root_plans_the_same(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    tree(ccw_env)
    assert planned(ccw_env, tmp_path, projects(ccw_env) / ENCODED) == [UUID_STRANDED]


def test_dot_claude_as_root_plans_the_same(ccw_env: dict[str, str], tmp_path: Path) -> None:
    tree(ccw_env)
    assert planned(ccw_env, tmp_path, projects(ccw_env).parent) == [UUID_STRANDED]


def test_status_counts_the_same_at_every_level(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    tree(ccw_env)
    cfg = configure(ccw_env, tmp_path / "archive", keep_objects=False)
    for root in (projects(ccw_env), projects(ccw_env) / ENCODED, projects(ccw_env).parent):
        assert status.sidecar_gap(cfg, source=root).stranded == 1, root


def test_a_real_sweep_of_one_project_dir_never_copies_its_own_folders(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    tree(ccw_env)
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root, keep_objects=False)
    result = run_ccw(["sweep", "--source", str(projects(ccw_env) / ENCODED)], ccw_env)
    assert result.code == 0, result.err
    names = {p.name for p in archive_root.rglob("*")}
    assert UUID_STRANDED in names
    assert "WORK" not in names
    assert "memory" not in names


def test_a_copied_tree_elsewhere_keeps_the_old_reading(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Outside the default source nothing says which level is the projects tree,
    so the walk root is taken as one, exactly as before."""
    elsewhere = tmp_path / "copy"
    (elsewhere / ENCODED / UUID_STRANDED / "tool-results").mkdir(parents=True)
    (elsewhere / ENCODED / UUID_STRANDED / "tool-results" / "out.txt").write_bytes(b"x\n")
    assert planned(ccw_env, tmp_path, elsewhere) == [UUID_STRANDED]
    assert sweep.project_dirs(elsewhere) == [elsewhere / ENCODED]
