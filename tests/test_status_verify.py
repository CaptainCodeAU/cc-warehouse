"""Oracle tests: ccw status and ccw verify (slice 9).

Contract: DESIGN section 7 (status reads catalog + log only), section 13
(orphan objects reported, sweep re-adopts); rules R4 (verify never mutates),
R6; FINDINGS F5.
"""

import hashlib
import json

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


def _append_log_record(env: dict[str, str], **fields: object) -> None:
    """Write one capture.jsonl line directly, the same six-field shape every
    real writer (notify.append_log and its callers) produces."""
    record: dict[str, object] = {
        "at": "2026-01-01T00:00:00+00:00",
        "status": "error",
        "session": None,
        "project": None,
        "message": "(no detail)",
        "elapsed_ms": None,
    }
    record.update(fields)
    log_dir = warehouse_root(env) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "capture.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def test_status_recent_errors_says_none_with_no_log(ccw_env: dict[str, str]) -> None:
    """Ticket 42 #4: with no capture.jsonl at all, status reports no errors
    rather than crashing (R5 -- a missing log is not a capture failure)."""
    capture_one(ccw_env)
    result = run_cli(["status"])
    assert result.code == 0, result.err
    lines = result.out.splitlines()
    idx = lines.index("Recent errors:")
    assert lines[idx + 1] == "  (none)"


def test_status_shows_a_real_error_from_the_log(ccw_env: dict[str, str]) -> None:
    """Ticket 42 Finding B: `catalog.record_event` is never called with
    action="error" anywhere, so a real capture error (unreadable transcript,
    lock unavailable, ...) only ever reaches logs/capture.jsonl. status must
    read it from there, not from the permanently-empty catalog table."""
    capture_one(ccw_env)
    _append_log_record(
        ccw_env, at="2026-01-01T00:00:00+00:00", message="unreadable transcript /x: boom"
    )
    result = run_cli(["status"])
    assert result.code == 0, result.err
    assert "unreadable transcript /x: boom" in result.out


def test_status_recent_errors_excludes_non_error_records(
    ccw_env: dict[str, str],
) -> None:
    """capture.jsonl also carries "ok" and "skipped_unchanged" records
    (every capture, not just failures); only status="error" belongs under
    Recent errors."""
    capture_one(ccw_env)
    _append_log_record(ccw_env, status="ok", message="stored fine")
    result = run_cli(["status"])
    assert result.code == 0, result.err
    assert "stored fine" not in result.out
    lines = result.out.splitlines()
    idx = lines.index("Recent errors:")
    assert lines[idx + 1] == "  (none)"


def test_status_recent_errors_are_newest_first_and_bounded(
    ccw_env: dict[str, str],
) -> None:
    """Matches the old catalog query's contract: newest first, capped at
    _ERROR_LIMIT (5) even when the log holds more."""
    capture_one(ccw_env)
    for n in range(7):
        _append_log_record(
            ccw_env,
            at=f"2026-01-01T00:00:0{n}+00:00",
            message=f"error number {n}",
        )
    result = run_cli(["status"])
    assert result.code == 0, result.err
    lines = result.out.splitlines()
    idx = lines.index("Recent errors:")
    error_lines = lines[idx + 1 : idx + 6]
    assert len(error_lines) == 5
    assert "error number 6" in error_lines[0], "newest is not first"
    assert "error number 2" in error_lines[4], "did not cap at 5"
    assert not any("error number 0" in ln or "error number 1" in ln for ln in error_lines)


def test_status_ignores_a_malformed_log_line(ccw_env: dict[str, str]) -> None:
    """A corrupted or partial capture.jsonl line (e.g. an interrupted append)
    must not crash status; it is skipped, and real errors around it still
    show (R5)."""
    capture_one(ccw_env)
    log_dir = warehouse_root(ccw_env) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "capture.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{not valid json\n")
    _append_log_record(ccw_env, message="a real error survives the bad line")
    result = run_cli(["status"])
    assert result.code == 0, result.err
    assert "a real error survives the bad line" in result.out
