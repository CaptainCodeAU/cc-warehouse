"""Oracle tests: `keep_projections`, the switch that ends the double tree (19j).

Retiring `projections/` does not stay retired on its own. The capture path and
`ccw build` both write into it, so a rename alone leaves it regrowing one folder
per session while LOOKING done. This key is what makes the retirement stick.

Staged on purpose, and reversible by one line:

    archive_root unset                      no archive at all (the default)
    archive_root set                        DUAL-WRITE, both trees current
    archive_root set + keep_projections=false   archive only, the old tree stops

The middle stage is not ceremony. It is what let the archive be proven against a
real 13,836-session corpus while the tree the operator actually used stayed
untouched, and it is what makes going back cost one line instead of a rebuild.

Contract: DESIGN 15 2026-08-02 (archive-first: `projections/` is dropped);
R4 (projections are disposable BY DEFINITION, which is what makes this the one
sanctioned deletion); R5 (the conservative branch is the default).
"""

from pathlib import Path

from cc_warehouse import archive
from conftest import (
    entry,
    hook_payload,
    jsonl,
    run_ccw,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "e9111111-2222-3333-4444-555555555551"
CWD = "/home/alice/projects/widget"


def session(uuid: str) -> bytes:
    return jsonl(
        entry(
            "user",
            "Do the thing",
            "2026-05-07T03:47:45.000Z",
            session_id=uuid,
            cwd=CWD,
            gitBranch="main",
        ),
        entry(
            "assistant",
            [{"type": "text", "text": "Done."}],
            "2026-05-07T03:47:50.000Z",
            session_id=uuid,
            cwd=CWD,
        ),
    )


def configure(
    env: dict[str, str], *, archive_root: Path | None, keep: bool | None
) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [f'root = "{warehouse_root(env)}"', f'archive_timezone = "{ZONE}"']
    if archive_root is not None:
        lines.append(f'archive_root = "{archive_root}"')
    if keep is not None:
        lines.append(f"keep_projections = {'true' if keep else 'false'}")
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def capture_and_render(env: dict[str, str], uuid: str) -> None:
    transcript = write_transcript(env, session(uuid), session_id=uuid, name=f"{uuid}.jsonl")
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, cwd=CWD, session_id=uuid))
    assert result.code == 0, result.err
    from conftest import catalog_rows

    rows = catalog_rows(env, "SELECT short FROM session")
    assert rows, "fixture stored nothing; every assertion below is vacuous"
    short = str(tuple(rows[0])[0])  # type: ignore[index]
    rendered = run_ccw(["render", "--session", f"s:{short}"], env)
    assert rendered.code == 0, rendered.err


def projection_dirs(env: dict[str, str]) -> list[Path]:
    projections = warehouse_root(env) / "projections"
    if not projections.is_dir():
        return []
    return [p for p in projections.glob("*/*") if p.is_dir()]


# ---------------------------------------------------------------------------
# The default is unchanged behaviour
# ---------------------------------------------------------------------------


def test_the_default_still_writes_projections(ccw_env: dict[str, str]) -> None:
    """Absent the key entirely, nothing about the capture path moves."""
    configure(ccw_env, archive_root=None, keep=None)
    capture_and_render(ccw_env, UUID_A)
    assert len(projection_dirs(ccw_env)) == 1


def test_dual_write_writes_both_trees(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """The middle stage: archive on, old tree still current."""
    target = tmp_path / "archive"
    configure(ccw_env, archive_root=target, keep=None)
    capture_and_render(ccw_env, UUID_A)
    assert len(projection_dirs(ccw_env)) == 1
    assert len(list(archive.walk_folders(target))) == 1


# ---------------------------------------------------------------------------
# Off: the retirement sticks
# ---------------------------------------------------------------------------


def test_with_keep_off_the_archive_is_written_and_projections_are_not(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The point of the slice. Without this, a retired `projections/` regrows one
    folder per session while looking retired."""
    target = tmp_path / "archive"
    configure(ccw_env, archive_root=target, keep=False)
    capture_and_render(ccw_env, UUID_A)
    assert len(list(archive.walk_folders(target))) == 1
    assert projection_dirs(ccw_env) == []


def test_a_retired_projections_dir_is_not_recreated(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Stronger than the above: retire the directory itself, then capture, and
    require that the directory does not come back at all."""
    target = tmp_path / "archive"
    configure(ccw_env, archive_root=target, keep=False)
    capture_and_render(ccw_env, UUID_A)
    projections = warehouse_root(ccw_env) / "projections"
    assert not projections.exists(), "the retired tree was recreated"


def test_ccw_build_also_stops_writing_projections(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The capture path is not the only writer. A `ccw build` that still filled
    the old tree would undo the retirement on the next rebuild."""
    target = tmp_path / "archive"
    configure(ccw_env, archive_root=target, keep=False)
    capture_and_render(ccw_env, UUID_A)
    result = run_ccw(["build", "--rebuild"], ccw_env)
    assert result.code == 0, result.err
    assert projection_dirs(ccw_env) == []


def test_build_still_refreshes_the_archive_when_projections_are_off(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`ccw build` must keep meaning something once the old tree is gone: it is
    the verb that rebuilds after a render change, and it has to rebuild the tree
    that still exists."""
    target = tmp_path / "archive"
    configure(ccw_env, archive_root=target, keep=False)
    capture_and_render(ccw_env, UUID_A)
    folder = next(archive.walk_folders(target))
    (folder / "transcript.md").unlink()

    result = run_ccw(["build", "--rebuild"], ccw_env)
    assert result.code == 0, result.err
    assert (folder / "transcript.md").is_file(), "build did not restore the archive file"


# ---------------------------------------------------------------------------
# The footgun, closed
# ---------------------------------------------------------------------------


def test_keep_off_without_an_archive_is_refused_and_projections_survive(
    ccw_env: dict[str, str],
) -> None:
    """R5, the conservative branch. `keep_projections = false` with no
    `archive_root` would mean a capture that renders NOWHERE - a warehouse that
    silently stops producing anything readable. The setting is ignored, the
    projection is written, and the contradiction is RECORDED rather than obeyed.
    """
    configure(ccw_env, archive_root=None, keep=False)
    capture_and_render(ccw_env, UUID_A)
    assert len(projection_dirs(ccw_env)) == 1, "output stopped with nowhere else to go"


def test_the_refusal_is_recorded_in_config_errors(ccw_env: dict[str, str]) -> None:
    """Never silent (F6): an ignored setting the operator deliberately typed has
    to say why it was ignored."""
    from cc_warehouse.config import load_config

    configure(ccw_env, archive_root=None, keep=False)
    config = load_config(
        xdg_config_home=Path(ccw_env["HOME"]) / ".config",
        env={"HOME": ccw_env["HOME"], "CCW_ROOT": ccw_env["CCW_ROOT"]},
    )
    assert config.keep_projections is True, "the unsafe combination was obeyed"
    assert any("keep_projections" in problem for problem in config.config_errors)
