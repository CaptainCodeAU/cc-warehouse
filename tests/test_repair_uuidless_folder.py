"""Oracle tests: `ccw repair` fixes a uuid-less session folder (W-20261011-A02).

FOUND 2026-10-11 by the A59 red-team review. A payload with no `sessionId` (a
`claude -p` stream-json capture) is archived as `<stamp>_session-<short>/`
(`build.session_stem`, W-20261001-A56). Repair read everything after the first `_`
of a folder name as the session uuid, so for such a folder it looked up
`session_uuid = 'session-<short>'`, found no row, said "no catalog row" and exited 1,
leaving the folder broken. It must resolve the folder through the short instead.
"""

from pathlib import Path

from test_project_memory_skip import ENCODED, configure, put, stream_json

from cc_warehouse import build
from conftest import catalog_rows, run_ccw


def uuidless_folder(env: dict[str, str], archive_root: Path) -> tuple[Path, str]:
    configure(env, archive_root, keep_objects=False)
    put(env, f"{ENCODED}/armA.jsonl", stream_json())
    result = run_ccw(["sweep"], env)
    assert result.code == 0, result.err
    rows = catalog_rows(env, "SELECT short FROM session WHERE session_uuid IS NULL")
    assert len(rows) == 1, "fixture made no uuid-less row; the test would prove nothing"
    short = str(rows[0][0])  # pyright: ignore[reportUnknownArgumentType, reportIndexIssue]
    (folder,) = [p for p in archive_root.rglob(f"*_session-{short}") if p.is_dir()]
    return folder, short


def test_the_stem_round_trips() -> None:
    assert build.short_from_stem(build.session_stem(None, "abc123def456")) == "abc123def456"
    assert build.short_from_stem("a5911111-2222-3333-4444-555555555551") is None


def test_repair_fixes_a_uuidless_folder_missing_a_generated_file(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    folder, short = uuidless_folder(ccw_env, tmp_path / "archive")
    generated = sorted(folder.glob("*.html"))
    assert generated, f"fixture folder holds no html to remove: {sorted(folder.iterdir())}"
    generated[0].rename(tmp_path / generated[0].name)
    result = run_ccw(["repair"], ccw_env)
    assert "no catalog row" not in result.err, result.err
    assert result.code == 0, result.err
    assert (folder / generated[0].name).is_file()
    assert f"session-{short}" not in result.err
