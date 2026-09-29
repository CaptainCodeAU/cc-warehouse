"""Oracle tests: an archive_root that overlaps the warehouse root is refused (W-20260929-A101).

THE HOLE. `build._prune` deletes every directory under `<root>/projections/` that
the current heads do not name (R4 allows deletion there and nowhere else). An
`archive_root` at or inside the warehouse root puts archived sessions in that
path, or lets a project whose label is literally `projections` do the same: the
build then deletes archived sessions, the one tree R4 says it may never touch.

THE RULE. The archive and the warehouse never share a directory in either
direction; every writer refuses the layout before it writes (the same gate as
the ticket 44a marker check), doctor fails it, config records it, and the labels
that name warehouse directories (`projections`, `objects`, `logs`) are reserved
so no project folder can take those names.

Contract: R4, R5, F6, F9.
"""

from pathlib import Path

import pytest

from cc_warehouse import archive, build, capture, doctor
from cc_warehouse.config import Config, load_config
from conftest import basic_session, mark_archive, run_cli, warehouse_root, write_transcript

ZONE = "UTC"
UUID = "0a101000-1111-4222-8333-444444444444"
CWD = "/home/alice/projects/widget"


def _configure(env: dict[str, str], archive_root: Path, *, keep_objects: bool = True) -> Config:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [
        f'root = "{warehouse_root(env)}"',
        f'archive_root = "{archive_root}"',
        f'archive_timezone = "{ZONE}"',
        f"keep_objects = {'true' if keep_objects else 'false'}",
    ]
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    mark_archive(archive_root, ZONE)
    return load_config()


def _plant_archived_session(archive_root: Path) -> Path:
    """An archive folder as an older install would have left it."""
    folder = archive_root / "widget" / f"20260105-100000+0000_{UUID}"
    folder.mkdir(parents=True)
    (folder / f"{UUID}.jsonl").write_bytes(basic_session(session_id=UUID))
    return folder


# ---------------------------------------------------------------------------
# The reproduction
# ---------------------------------------------------------------------------


def test_a_build_never_deletes_an_archive_that_sits_inside_projections(
    ccw_env: dict[str, str],
) -> None:
    root = warehouse_root(ccw_env)
    archive_root = root / "projections" / "archive"
    config = _configure(ccw_env, archive_root)
    folder = _plant_archived_session(archive_root)
    transcript = write_transcript(ccw_env, basic_session(session_id="other-1"), session_id="x")
    capture.capture_transcript(config, transcript, session_id=None, cwd=CWD)

    report = build.build(config)

    assert (folder / f"{UUID}.jsonl").is_file(), "the build deleted an archived session"
    assert report.failures, "the build ran against an overlapping layout instead of refusing"


@pytest.mark.parametrize(
    "where",
    ["root", "inside", "contains"],
    ids=["same", "archive-inside-root", "root-inside-archive"],
)
def test_every_overlap_is_refused_by_the_writer_gate(
    ccw_env: dict[str, str], tmp_path: Path, where: str
) -> None:
    root = warehouse_root(ccw_env)
    archive_root = {
        "root": root,
        "inside": root / "archive",
        "contains": root.parent,
    }[where]
    config = _configure(ccw_env, archive_root)

    refusal = archive.root_refusal(config)

    assert refusal is not None and refusal.failures
    assert "warehouse root" in refusal.outcomes[0].detail
    assert any("warehouse root" in error for error in config.config_errors)
    ok, detail = doctor._archive_root_check(config)  # pyright: ignore[reportPrivateUsage]
    assert not ok and "warehouse root" in detail


def test_a_separate_archive_is_still_accepted(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """The control: the gate must not refuse the ordinary layout."""
    config = _configure(ccw_env, tmp_path / "elsewhere")
    assert archive.root_refusal(config) is None
    assert not any("warehouse root" in error for error in config.config_errors)
    assert doctor._archive_root_check(config)[0]  # pyright: ignore[reportPrivateUsage]


def test_the_hook_refuses_an_overlapping_archive_without_a_vault(
    ccw_env: dict[str, str],
) -> None:
    """With no vault the refusal is raised to the hook's own boundary, exactly as
    an unmarked root is (ticket 44a), and nothing lands in the overlapping tree."""
    root = warehouse_root(ccw_env)
    archive_root = root / "projections" / "archive"
    config = _configure(ccw_env, archive_root, keep_objects=False)
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID), session_id=UUID)

    with pytest.raises(archive.ArchiveRootRefused, match="warehouse root"):
        capture.capture_transcript(config, transcript, session_id=UUID, cwd=CWD)

    assert not list(archive_root.rglob("*.jsonl"))


def test_ccw_archive_to_refuses_a_target_inside_the_warehouse(ccw_env: dict[str, str]) -> None:
    root = warehouse_root(ccw_env)
    _configure(ccw_env, root.parent / "separate")
    target = root / "projections" / "x"

    result = run_cli(["archive", "--to", str(target), "--init"])

    assert result.code == 2, result
    assert "warehouse" in result.err
    assert not target.exists()


# ---------------------------------------------------------------------------
# Reserved labels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label", ["projections", "objects", "logs"])
def test_warehouse_directory_names_are_reserved_labels(label: str, tmp_path: Path) -> None:
    folder = build.archive_dir(tmp_path, label, "2026-01-05T10:00:00Z", UUID, ZONE)
    assert folder.parent.name == f"_{label}"
    assert label in build.RESERVED_LABELS


def test_an_archive_root_that_links_into_the_warehouse_is_refused(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    root = warehouse_root(ccw_env)
    real = root / "projections" / "archive"
    real.mkdir(parents=True)
    link = tmp_path / "looks-separate"
    link.symlink_to(real)
    config = _configure(ccw_env, link)

    refusal = archive.root_refusal(config)

    assert refusal is not None and "warehouse root" in refusal.outcomes[0].detail
