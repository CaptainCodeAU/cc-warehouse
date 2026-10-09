"""Oracle tests: an ad-hoc `--out` inside the archive is refused (W-20260929-A103).

THE HOLE. `ccw render <jsonl> --out DIR` refused DIR inside the warehouse's
`objects/` or `projections/`, but not inside `archive_root`. Pointed at an
archive folder it exited 0 and overwrote the folder's five generated files; the
new `manifest.json` came from a bare render, so the folder's evidence (the
sub-agent and companion records, the refusal notes) was gone, and verify then
read the folder against a manifest that no longer described it. `ccw share
--out` used the same guard and had the same gap.

THE RULE. Both refuse any `--out` that resolves inside `archive_root`, through a
symlink or `..` as well, exactly as they refuse the store and projections (F9).

Contract: R4, F9.
"""

from pathlib import Path

import pytest

from cc_warehouse import archive, build
from cc_warehouse.config import load_config
from conftest import basic_session, mark_archive, run_cli, warehouse_root

ZONE = "UTC"
UUID = "0a103000-1111-4222-8333-444444444444"


def _archived(env: dict[str, str], tmp_path: Path) -> tuple[Path, Path, Path]:
    archive_root = tmp_path / "archive"
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(
        f'root = "{warehouse_root(env)}"\narchive_root = "{archive_root}"\n'
        f'archive_timezone = "{ZONE}"\n',
        encoding="utf-8",
    )
    mark_archive(archive_root, ZONE)
    data = basic_session(session_id=UUID)
    options = build.render_options(load_config())
    folder = archive.write_session_folder(
        archive_root, "widget", data, options, ZONE,
        fallback_stem="session",
    ).directory
    source = tmp_path / "loose.jsonl"
    source.write_bytes(data)
    return archive_root, folder, source


@pytest.mark.parametrize("form", ["plain", "dotdot", "symlink"])
def test_render_out_into_an_archive_folder_is_refused(
    ccw_env: dict[str, str], tmp_path: Path, form: str
) -> None:
    _archive_root, folder, source = _archived(ccw_env, tmp_path)
    if form == "plain":
        out = folder
    elif form == "dotdot":
        out = tmp_path / "elsewhere" / ".." / "archive" / folder.parent.name / folder.name
        (tmp_path / "elsewhere").mkdir()
    else:
        out = tmp_path / "innocent-looking"
        out.symlink_to(folder)
    manifest = (folder / "manifest.json").read_bytes()

    result = run_cli(["render", str(source), "--out", str(out)])

    assert (folder / "manifest.json").read_bytes() == manifest, "the archive folder was rewritten"
    assert result.code == 1, result
    assert "archive" in result.err


def test_share_out_into_the_archive_is_refused(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root, _folder, _source = _archived(ccw_env, tmp_path)
    out = archive_root / "a-share"

    result = run_cli(["share", "s:0000", "--out", str(out)])

    assert result.code == 2, result
    assert "archive" in result.err
    assert not out.exists()


def test_render_out_elsewhere_still_works(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """The control: the guard refuses the archive, not every --out."""
    _archive_root, _folder, source = _archived(ccw_env, tmp_path)
    out = tmp_path / "scratch-render"

    result = run_cli(["render", str(source), "--out", str(out)])

    assert result.code == 0, result.err
    assert (out / "manifest.json").is_file()
