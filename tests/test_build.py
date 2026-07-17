"""Oracle tests: projection build orchestration (slice 8) and the F5 read path.

Contract: DESIGN sections 1 (projection naming, disposability), 4, 6 (version
supersession, label-rename relocation, hidden sessions); rules R4 (deletions
only inside projections/), R6, R12; FINDINGS F4, F5.
"""

import sqlite3
from pathlib import Path
from typing import cast

from cc_warehouse import catalog, status, store
from cc_warehouse.config import Config
from conftest import (
    basic_session,
    catalog_path,
    entry,
    hook_payload,
    jsonl,
    record_opens,
    run_ccw,
    run_cli,
    warehouse_root,
    write_transcript,
)

FOUR_FILES = {
    "transcript.md",
    "transcript.compact.md",
    "conversation.html",
    "conversation.compact.html",
}


def capture(env: dict[str, str], data: bytes, **kwargs: str) -> None:
    transcript = write_transcript(env, data, **kwargs)  # type: ignore[arg-type]
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, cwd=None))
    assert result.code == 0, result.err


def backdate_events(env: dict[str, str]) -> None:
    with sqlite3.connect(catalog_path(env)) as conn:
        conn.execute("UPDATE capture_event SET at = '2026-01-01T00:00:00Z'")
        conn.commit()


def session_dirs(env: dict[str, str]) -> list[Path]:
    projections = warehouse_root(env) / "projections"
    if not projections.exists():
        return []
    return sorted(p for p in projections.glob("*/*") if p.is_dir())


def test_build_writes_the_named_projection_with_4_files_and_manifest(
    ccw_env: dict[str, str],
) -> None:
    """Frozen naming: projections/<label>/<YYYY-MM-DD>_<slug>_s-<hash12>/ with
    the date from JSONL internals (R12), never file mtimes."""
    capture(ccw_env, basic_session())
    result = run_cli(["build"])
    assert result.code == 0, result.err
    dirs = session_dirs(ccw_env)
    assert len(dirs) == 1
    d = dirs[0]
    assert d.parent.name == "widget"
    assert d.name.startswith("2026-01-05_fix-flux_s-")
    names = {p.name for p in d.iterdir()}
    assert FOUR_FILES <= names
    assert "manifest.json" in names


def test_build_is_incremental_and_rebuild_regenerates(ccw_env: dict[str, str]) -> None:
    capture(ccw_env, basic_session())
    assert run_cli(["build"]).code == 0
    files = sorted(session_dirs(ccw_env)[0].iterdir())
    stamps = [(p.name, p.stat().st_mtime_ns) for p in files]
    assert run_cli(["build"]).code == 0
    assert [(p.name, p.stat().st_mtime_ns) for p in files] == stamps
    assert run_cli(["build", "--rebuild"]).code == 0
    after = [(p.name, p.stat().st_mtime_ns) for p in sorted(session_dirs(ccw_env)[0].iterdir())]
    assert after != stamps


def test_superseded_version_leaves_one_canonical_dir(ccw_env: dict[str, str]) -> None:
    """DESIGN section 6: exactly one browsable dir per session UUID; removing
    the superseded projection dir is a sanctioned in-projections deletion (R4)."""
    import hashlib

    data = basic_session()
    transcript = write_transcript(ccw_env, data)
    assert run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript)).code == 0
    assert run_cli(["build"]).code == 0
    backdate_events(ccw_env)

    grown = data + jsonl(entry("user", "more", "2026-01-05T11:00:00.000Z"))
    transcript.write_bytes(grown)
    assert run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript)).code == 0
    assert run_cli(["build"]).code == 0

    dirs = session_dirs(ccw_env)
    assert len(dirs) == 1
    new_short = hashlib.sha256(grown).hexdigest()[:12]
    assert dirs[0].name.endswith(f"s-{new_short}")


def test_label_rename_relocates_projection_dirs(ccw_env: dict[str, str]) -> None:
    """DESIGN section 6: the tree follows label renames on incremental build;
    the emptied old label dir goes away (sanctioned projection-space deletion)."""
    capture(ccw_env, basic_session())
    assert run_cli(["build"]).code == 0
    rows = cast(
        list[tuple[object, ...]],
        catalog.open_catalog(warehouse_root(ccw_env)).execute("SELECT id FROM project").fetchall(),
    )
    project_id = cast(int, rows[0][0])
    assert run_cli(["project", "rename", str(project_id), "renamed-widget"]).code == 0
    assert run_cli(["build"]).code == 0
    projections = warehouse_root(ccw_env) / "projections"
    assert (projections / "renamed-widget").is_dir()
    assert not (projections / "widget").exists()


def test_hidden_sessions_are_not_rendered_by_default(ccw_env: dict[str, str]) -> None:
    capture(ccw_env, jsonl(entry("user", "warmup", "2026-01-05T10:00:00.000Z")))
    assert run_cli(["build"]).code == 0
    assert session_dirs(ccw_env) == []
    assert run_cli(["build", "--include-hidden"]).code == 0
    assert len(session_dirs(ccw_env)) == 1


def test_colliding_labels_produce_two_complete_projections(
    ccw_env: dict[str, str],
) -> None:
    """F4 oracle: two projects whose paths derive to one display form still get
    two complete projections; the s-<hash12> suffix keeps dirs collision-free."""
    uuid_b = "99999999-8888-7777-6666-555555555555"
    capture(
        ccw_env,
        basic_session(cwd="/home/alice/projects/app.x"),
        encoded_dir="-home-alice-projects-app-x",
    )
    capture(
        ccw_env,
        basic_session(cwd="/home/alice/projects/app-x", session_id=uuid_b),
        encoded_dir="-home-alice-projects-app-x",
        session_id=uuid_b,
    )
    assert run_cli(["build"]).code == 0
    dirs = session_dirs(ccw_env)
    assert len(dirs) == 2
    for d in dirs:
        assert FOUR_FILES <= {p.name for p in d.iterdir()}


def test_recent_listing_opens_zero_stored_payloads(ccw_env: dict[str, str]) -> None:
    """F5 oracle: listings read the catalog only; with 50 real objects in the
    store, listing recent sessions opens none of them."""
    root = warehouse_root(ccw_env)
    conn = catalog.open_catalog(root)
    from cc_warehouse import registry

    project = registry.resolve_project(
        conn, cwd="/home/alice/projects/widget", encoded_dir=None, now="2026-01-05T12:00:00Z"
    )
    for i in range(50):
        data = basic_session(prompt=f"session number {i}")
        put = store.put(root, data)
        meta = catalog.SessionMeta(
            sha256=put.sha256,
            source_kind="claude_code",
            session_uuid=f"00000000-0000-0000-0000-{i:012d}",
            slug=None,
            git_branch=None,
            cwd="/home/alice/projects/widget",
            first_ts="2026-01-05T10:00:00.000Z",
            last_ts="2026-01-05T10:00:05.000Z",
            size_bytes=len(data),
            line_count=2,
            skipped_lines=0,
            summary=f"session number {i}",
            hidden=False,
            resolution_source="payload_cwd",
        )
        catalog.add_session(conn, meta, project.project_id, "2026-01-05T12:00:00Z")
    conn.commit()
    conn.close()

    config = Config(root=root)
    with record_opens(root / "objects") as opens:
        listed = status.recent_sessions(config, limit=10)
        assert len(listed) == 10
        cli_result = run_cli(["status"])
        assert cli_result.code == 0
    assert opens == [], f"listing opened stored payloads: {opens}"
