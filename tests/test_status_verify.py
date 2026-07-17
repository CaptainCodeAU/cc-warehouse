"""Oracle tests: ccw status and ccw verify (slice 9).

Contract: DESIGN section 7 (status reads catalog + log only), section 13
(orphan objects reported, sweep re-adopts); rules R4 (verify never mutates),
R6; FINDINGS F5.
"""

import hashlib

from cc_warehouse import catalog
from conftest import (
    basic_session,
    hook_payload,
    record_opens,
    run_ccw,
    run_cli,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)


def capture_one(env: dict[str, str]) -> bytes:
    data = basic_session()
    transcript = write_transcript(env, data)
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript))
    assert result.code == 0, result.err
    return data


def test_status_reads_catalog_and_log_only(ccw_env: dict[str, str]) -> None:
    """F5/R6: status opens zero stored payloads."""
    capture_one(ccw_env)
    with record_opens(warehouse_root(ccw_env) / "objects") as opens:
        result = run_cli(["status"])
    assert result.code == 0
    assert result.out.strip()
    assert opens == []


def test_verify_green_on_an_intact_store(ccw_env: dict[str, str]) -> None:
    capture_one(ccw_env)
    result = run_cli(["verify"])
    assert result.code == 0, result.err


def test_verify_detects_corrupted_object(ccw_env: dict[str, str]) -> None:
    data = capture_one(ccw_env)
    digest = hashlib.sha256(data).hexdigest()
    stored = warehouse_root(ccw_env) / "objects" / digest[:2] / f"{digest}.jsonl"
    stored.write_bytes(b"corrupted")
    result = run_cli(["verify"])
    assert result.code != 0
    assert digest[:12] in result.out + result.err


def test_verify_reports_orphan_object_without_deleting_it(
    ccw_env: dict[str, str],
) -> None:
    """DESIGN section 13: an orphan object (store write landed, catalog row did
    not) is reported; nothing removes it (R4). Sweep adoption is proven in
    test_sweep_adopts_orphan_store_objects."""
    capture_one(ccw_env)
    orphan_data = basic_session(prompt="orphaned capture")
    digest = hashlib.sha256(orphan_data).hexdigest()
    orphan = warehouse_root(ccw_env) / "objects" / digest[:2] / f"{digest}.jsonl"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(orphan_data)
    result = run_cli(["verify"])
    assert result.code != 0
    assert digest[:12] in result.out + result.err
    assert orphan.read_bytes() == orphan_data


def test_verify_reports_row_whose_object_is_missing(ccw_env: dict[str, str]) -> None:
    capture_one(ccw_env)
    conn = catalog.open_catalog(warehouse_root(ccw_env))
    ghost = "12" * 32
    meta = catalog.SessionMeta(
        sha256=ghost,
        source_kind="claude_code",
        session_uuid="dddddddd-1111-2222-3333-444444444444",
        slug=None,
        git_branch=None,
        cwd="/home/alice/projects/widget",
        first_ts="2026-01-05T10:00:00.000Z",
        last_ts="2026-01-05T10:00:05.000Z",
        size_bytes=1,
        line_count=1,
        skipped_lines=0,
        summary="ghost",
        hidden=False,
        resolution_source="payload_cwd",
    )
    from cc_warehouse import registry

    project = registry.resolve_project(
        conn, cwd="/home/alice/projects/widget", encoded_dir=None, now="2026-01-05T12:00:00Z"
    )
    catalog.add_session(conn, meta, project.project_id, "2026-01-05T12:00:00Z")
    conn.commit()
    conn.close()
    result = run_cli(["verify"])
    assert result.code != 0
    assert ghost[:12] in result.out + result.err


def test_verify_never_modifies_the_store(ccw_env: dict[str, str]) -> None:
    """R4: verify is read-only over objects."""
    capture_one(ccw_env)
    objects = warehouse_root(ccw_env) / "objects"
    before = tree_snapshot(objects)
    run_cli(["verify"])
    assert tree_snapshot(objects) == before
