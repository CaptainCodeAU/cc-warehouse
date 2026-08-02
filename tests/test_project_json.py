"""Oracle tests: project.json, the file that makes the catalog disposable (19f).

DESIGN 15, 2026-08-02: "CATALOG: DEMOTED TO A DISPOSABLE INDEX. Project LABELS
survive without it, because the label IS the parent folder name. What does not
survive is `project_alias` (121 rows), which maps the paths Claude Code used to
the name the operator chose; losing it splits a renamed project in two on the
next capture."

Until this file exists that claim is FALSE, and a claim like that is exactly the
guarantee drift F6 exists to ban. These tests are the proof, and the central one
is the round trip: delete the catalog, rescan, and the labels and aliases come
back.
"""

import json
from pathlib import Path

from cc_warehouse import archive, catalog, registry
from cc_warehouse.render import RenderOptions
from conftest import (
    catalog_path,
    entry,
    hook_payload,
    jsonl,
    run_ccw,
    run_cli,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
OPTS = RenderOptions()
UUID_A = "a2111111-2222-3333-4444-555555555551"
UUID_B = "a2111111-2222-3333-4444-555555555552"

CWD_A = "/home/alice/projects/widget"
CWD_B = "/home/alice/projects/gadget"


def session(uuid: str, cwd: str) -> bytes:
    return jsonl(
        entry(
            "user",
            "Do the thing",
            "2026-05-07T03:47:45.000Z",
            session_id=uuid,
            cwd=cwd,
            gitBranch="main",
        ),
        entry(
            "assistant",
            [{"type": "text", "text": "Done."}],
            "2026-05-07T03:47:50.000Z",
            session_id=uuid,
            cwd=cwd,
        ),
    )


def capture(env: dict[str, str], uuid: str, cwd: str, encoded: str) -> None:
    data = session(uuid, cwd)
    transcript = write_transcript(
        env, data, session_id=uuid, encoded_dir=encoded, name=f"{uuid}.jsonl"
    )
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, cwd=cwd, session_id=uuid))
    assert result.code == 0, result.err


# ---------------------------------------------------------------------------
# The file exists and says what it must
# ---------------------------------------------------------------------------


def test_each_project_folder_gets_a_project_json(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    capture(ccw_env, UUID_A, CWD_A, "-home-alice-projects-widget")
    capture(ccw_env, UUID_B, CWD_B, "-home-alice-projects-gadget")
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0

    labels = [d for d in target.iterdir() if d.is_dir()]
    assert len(labels) == 2
    for label_dir in labels:
        assert (label_dir / "project.json").is_file(), label_dir


def test_project_json_carries_the_label_and_the_known_paths(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Label plus the encoded dirs and cwds Claude Code used. Those aliases are
    the part the catalog owns exclusively; the label is recoverable from the
    folder name, the aliases are not recoverable from anything."""
    capture(ccw_env, UUID_A, CWD_A, "-home-alice-projects-widget")
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0

    label_dir = next(d for d in target.iterdir() if d.is_dir())
    payload = json.loads((label_dir / "project.json").read_text(encoding="utf-8"))
    assert payload["label"] == label_dir.name
    paths = {alias["path"] for alias in payload["aliases"]}
    assert CWD_A in paths
    assert "-home-alice-projects-widget" in paths
    kinds = {alias["kind"] for alias in payload["aliases"]}
    assert "cwd" in kinds
    assert "encoded_dir" in kinds


def test_project_json_survives_a_rename(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The failure this file prevents, stated as a test: an operator renames a
    project, the catalog is later lost, and the next capture cannot tell that
    the old encoded path belongs to the new name."""
    capture(ccw_env, UUID_A, CWD_A, "-home-alice-projects-widget")
    conn = catalog.open_catalog(warehouse_root(ccw_env))
    try:
        project_id = registry.project_for_path(conn, CWD_A, "cwd")
        assert project_id is not None
        registry.rename_project(conn, project_id, "Widget Works")
        conn.commit()
    finally:
        conn.close()

    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0
    label_dir = next(d for d in target.iterdir() if d.is_dir())
    payload = json.loads((label_dir / "project.json").read_text(encoding="utf-8"))
    assert payload["label"] == "Widget Works"
    assert CWD_A in {a["path"] for a in payload["aliases"]}


# ---------------------------------------------------------------------------
# THE ROUND TRIP: the claim, proved
# ---------------------------------------------------------------------------


def test_deleting_the_catalog_loses_nothing_the_archive_can_rebuild(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The whole point of 19f, asserted end to end. Take the aliases from the
    catalog, throw the catalog away, rebuild them from the tree alone, and
    require the two to agree exactly."""
    capture(ccw_env, UUID_A, CWD_A, "-home-alice-projects-widget")
    capture(ccw_env, UUID_B, CWD_B, "-home-alice-projects-gadget")
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0

    conn = catalog.open_catalog(warehouse_root(ccw_env))
    try:
        before = {
            (str(row[0]), str(row[1]), str(row[2]))
            for row in conn.execute(
                "SELECT p.label, a.path, a.kind FROM project_alias a"
                " JOIN project p ON p.id = a.project_id"
            ).fetchall()
        }
    finally:
        conn.close()
    assert before, "fixture stored no aliases; every assertion below would be vacuous"

    catalog_path(ccw_env).unlink()
    rebuilt = archive.read_projects(target)
    after = {
        (project.label, alias.path, alias.kind)
        for project in rebuilt
        for alias in project.aliases
    }
    assert after == before


def test_read_projects_works_with_no_catalog_present(tmp_path: Path) -> None:
    """Read from the TREE, never from a database. If read_projects needed the
    catalog, project.json would be decorative."""
    label_dir = tmp_path / "widget"
    label_dir.mkdir()
    (label_dir / "project.json").write_text(
        json.dumps(
            {
                "label": "widget",
                "aliases": [{"path": "/home/alice/projects/widget", "kind": "cwd"}],
            }
        ),
        encoding="utf-8",
    )
    projects = archive.read_projects(tmp_path)
    assert len(projects) == 1
    assert projects[0].label == "widget"
    assert projects[0].aliases[0].path == "/home/alice/projects/widget"


def test_a_project_folder_with_no_project_json_is_skipped_not_fatal(
    tmp_path: Path,
) -> None:
    """R5: a tree missing one sidecar must still yield the others. A rescan that
    dies on the first gap is a rescan nobody can use on a real archive."""
    good = tmp_path / "widget"
    good.mkdir()
    (good / "project.json").write_text(
        json.dumps({"label": "widget", "aliases": []}), encoding="utf-8"
    )
    (tmp_path / "gadget").mkdir()
    projects = archive.read_projects(tmp_path)
    assert [p.label for p in projects] == ["widget"]


def test_a_corrupt_project_json_is_skipped_not_fatal(tmp_path: Path) -> None:
    good = tmp_path / "widget"
    good.mkdir()
    (good / "project.json").write_text(
        json.dumps({"label": "widget", "aliases": []}), encoding="utf-8"
    )
    bad = tmp_path / "gadget"
    bad.mkdir()
    (bad / "project.json").write_text("{ not json", encoding="utf-8")
    assert [p.label for p in archive.read_projects(tmp_path)] == ["widget"]


# ---------------------------------------------------------------------------
# It behaves like everything else in the archive
# ---------------------------------------------------------------------------


def test_writing_project_json_is_idempotent(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    capture(ccw_env, UUID_A, CWD_A, "-home-alice-projects-widget")
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0
    first = tree_snapshot(target)
    assert run_cli(["archive", "--to", str(target)]).code == 0
    assert tree_snapshot(target) == first


def test_project_json_is_not_mistaken_for_a_session_folder(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """walk_folders yields session DIRECTORIES; a sidecar file at the label level
    must not be walked into or counted."""
    capture(ccw_env, UUID_A, CWD_A, "-home-alice-projects-widget")
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0
    folders = list(archive.walk_folders(target))
    assert len(folders) == 1
    assert all(f.name != "project.json" for f in folders)


def test_verify_ignores_the_project_json_sidecar(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    capture(ccw_env, UUID_A, CWD_A, "-home-alice-projects-widget")
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0
    result = run_cli(["archive", "--to", str(target), "--verify"])
    assert result.code == 0, result.err + result.out
