"""Oracle tests: `ccw sweep` also walks the projects folders `extra_sources` names.

W-20261015-A01 (engage #1470), Gavin's ruling cc-warehouse-main Q2: 1, 2026-10-15.
A second Claude Code home (`CLAUDE_CONFIG_DIR`, here `~/.claude_v2`) writes its
transcripts to its own `projects/` folder. The nightly sweep walked only
`~/.claude/projects`, so 59 sessions sat in that second home with no archived copy
until a hand-run `ccw sweep --source ~/.claude_v2/projects` on 2026-10-14.

The setting is a list of extra projects folders, walked after the default one by a
plain `ccw sweep` (and named by `--dry-run`). An explicit `--source` still means
exactly that one folder. A listed folder that does not exist is not a failure, the
same as a missing default source (R5).
"""

from pathlib import Path

from cc_warehouse.config import load_config
from conftest import basic_session, mark_archive, run_ccw, warehouse_root, write_transcript

ZONE = "Australia/Melbourne"
UUID_MAIN = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
UUID_SECOND = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
PROJECTIONS = ("transcript.md", "conversation.html", "manifest.json")


def configure(env: dict[str, str], archive_root: Path, extra: list[str]) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    listed = ", ".join(f'"{p}"' for p in extra)
    (cfg / "config.toml").write_text(
        f'root = "{warehouse_root(env)}"\n'
        f'archive_timezone = "{ZONE}"\n'
        f'archive_root = "{archive_root}"\n'
        f"extra_sources = [{listed}]\n",
        encoding="utf-8",
    )
    env["XDG_CONFIG_HOME"] = str(cfg.parent)
    mark_archive(archive_root, ZONE)


def second_home_transcript(env: dict[str, str], session_id: str) -> Path:
    """A transcript where a second Claude home would put it."""
    project = Path(env["HOME"]) / ".claude_v2" / "projects" / "-home-alice-projects-makeitso"
    project.mkdir(parents=True, exist_ok=True)
    path = project / f"{session_id}.jsonl"
    path.write_bytes(basic_session(session_id=session_id))
    return path


def session_folders(archive_root: Path) -> dict[str, Path]:
    return {
        s.name.rsplit("_", 1)[-1]: s
        for proj in archive_root.iterdir()
        if proj.is_dir() and not proj.name.startswith("_")
        for s in proj.iterdir()
        if s.is_dir()
    }


# --- config ---------------------------------------------------------------


def test_extra_sources_defaults_to_none() -> None:
    assert load_config(env={"HOME": "/home/alice"}, no_config=True).extra_sources == ()


def test_extra_sources_reads_a_list_and_expands_home(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "cc-warehouse"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text(
        'extra_sources = ["~/.claude_v2/projects", "/srv/other/projects"]\n', encoding="utf-8"
    )
    cfg = load_config(xdg_config_home=tmp_path, env={"HOME": str(tmp_path / "home")})
    assert cfg.extra_sources == (
        Path("~/.claude_v2/projects").expanduser(),
        Path("/srv/other/projects"),
    )
    assert cfg.config_errors == ()


def test_extra_sources_that_is_not_a_list_is_a_recorded_problem(tmp_path: Path) -> None:
    """A typo of the right TYPE is still a typo: a bare string must not silently mean
    "no extra sources" (the `[relocate].roots` rule)."""
    cfg_dir = tmp_path / "cc-warehouse"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text(
        'extra_sources = "~/.claude_v2/projects"\n', encoding="utf-8"
    )
    cfg = load_config(xdg_config_home=tmp_path, env={"HOME": str(tmp_path / "home")})
    assert cfg.extra_sources == ()
    assert any("extra_sources" in problem for problem in cfg.config_errors)


# --- sweep ----------------------------------------------------------------


def test_a_plain_sweep_archives_both_homes_readably(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE LOAD-BEARING TEST: the second home's session reaches the archive, with its
    pages, from the same `ccw sweep` the nightly job runs, beside the main home's."""
    archive = tmp_path / "archive"
    second = Path(ccw_env["HOME"]) / ".claude_v2" / "projects"
    configure(ccw_env, archive, [str(second)])
    write_transcript(ccw_env, basic_session(session_id=UUID_MAIN), session_id=UUID_MAIN)
    source = second_home_transcript(ccw_env, UUID_SECOND)

    result = run_ccw(["sweep"], ccw_env)

    assert result.code == 0, result.err
    folders = session_folders(archive)
    assert set(folders) == {UUID_MAIN, UUID_SECOND}, folders
    folder = folders[UUID_SECOND]
    assert next(folder.glob("*.jsonl")).read_bytes() == source.read_bytes()
    missing = [f for f in PROJECTIONS if not (folder / f).is_file()]
    assert not missing, f"second-home session is not readable, missing: {missing}"


def test_dry_run_names_the_second_home_and_writes_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive = tmp_path / "archive"
    second = Path(ccw_env["HOME"]) / ".claude_v2" / "projects"
    configure(ccw_env, archive, [str(second)])
    second_home_transcript(ccw_env, UUID_SECOND)

    result = run_ccw(["sweep", "--dry-run"], ccw_env)

    assert result.code == 0, result.err
    assert f"would-store: {UUID_SECOND}.jsonl" in result.out
    assert session_folders(archive) == {}


def test_an_explicit_source_still_means_only_that_folder(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive = tmp_path / "archive"
    second = Path(ccw_env["HOME"]) / ".claude_v2" / "projects"
    configure(ccw_env, archive, [str(second)])
    main = write_transcript(ccw_env, basic_session(session_id=UUID_MAIN), session_id=UUID_MAIN)
    second_home_transcript(ccw_env, UUID_SECOND)

    result = run_ccw(["sweep", "--source", str(main.parent.parent)], ccw_env)

    assert result.code == 0, result.err
    assert set(session_folders(archive)) == {UUID_MAIN}


def test_a_listed_folder_that_does_not_exist_is_not_a_failure(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R5: a missing source is an empty walk, never a crash or a failed night."""
    archive = tmp_path / "archive"
    configure(ccw_env, archive, [str(tmp_path / "nowhere" / "projects")])
    write_transcript(ccw_env, basic_session(session_id=UUID_MAIN), session_id=UUID_MAIN)

    result = run_ccw(["sweep"], ccw_env)

    assert result.code == 0, result.err
    assert set(session_folders(archive)) == {UUID_MAIN}
