"""Oracle tests: `reconcile.py` and its `ccw reconcile`/`ccw repair` wiring
(ticket 42 #5; closes ticket 28.10's "cross-tree reconciliation as a test, not a
hand-check" gap in the same pass).

THE FAILURE THIS EXISTS FOR: ticket 41 Finding 5 found one session with a logged
capture error and no trace anywhere -- source, archive, or catalog -- gone for good.
Measuring the real log on 2026-09-09 found the true figure was 21, not 3, running at
roughly 1-2 a week since 2026-08-08: nothing before this cross-checked a capture
error against whether the session it named ever actually landed anywhere.

THE THREE INSTRUMENTS, and why all three must miss: a session present in the source
tree, the archive, or the catalog is not lost, whichever one instrument still has
it. Requiring all three to agree is the conservative direction (a lock-contention
error that later succeeded resolves to a session the archive or catalog DOES have,
so it drops out by evidence rather than a growing list of exception shapes).

TWO SPEEDS: `find_unrecoverable` is the expensive cross-check (source + archive +
catalog); `known_unrecoverable_count`/`known_unrecoverable_uuids` are cheap reads of
the dedup ledger `ccw repair` writes back into capture.jsonl, so `ccw doctor` can
call them on every SessionStart hot path without a directory walk.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cc_warehouse import reconcile
from cc_warehouse.config import Config
from conftest import basic_session, run_ccw, warehouse_root, write_transcript

ZONE = "Australia/Melbourne"
LOST_UUID = "11111111-1111-4111-8111-111111111111"
ARCHIVED_UUID = "22222222-2222-4222-8222-222222222222"


def configure(env: dict[str, str], archive_root: Path) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [
        f'root = "{warehouse_root(env)}"',
        f'archive_timezone = "{ZONE}"',
        f'archive_root = "{archive_root}"',
    ]
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def append_log(env: dict[str, str], **fields: object) -> None:
    """Write one capture.jsonl line directly, the real six/seven-field shape
    every writer (notify.append_log and its callers) produces."""
    record: dict[str, object] = {
        "at": datetime.now(UTC).isoformat(),
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


# ---------------------------------------------------------------------------
# find_unrecoverable: the expensive cross-check
# ---------------------------------------------------------------------------


def test_a_session_missing_from_all_three_is_unrecoverable(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE POSITIVE CASE: an error record naming a uuid absent from source,
    archive, and catalog alike is exactly what this exists to catch."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    append_log(
        ccw_env,
        session_uuid=LOST_UUID,
        message=f"unreadable transcript /x/{LOST_UUID}.jsonl: boom",
        at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
    )
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)

    findings = reconcile.find_unrecoverable(
        config, home=Path(ccw_env["HOME"]), now=datetime.now(UTC)
    )

    assert any(f.session_uuid == LOST_UUID for f in findings), findings


def test_a_session_present_in_the_archive_is_not_unrecoverable(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE NEGATIVE CONTROL: the same shape of error record, but for a session
    that IS actually archived (e.g. a lock-contention error that later
    succeeded) must never be flagged."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=ARCHIVED_UUID), session_id=ARCHIVED_UUID)
    assert run_ccw(["sweep"], ccw_env).code == 0
    append_log(
        ccw_env,
        session_uuid=ARCHIVED_UUID,
        message=f"capture lock unavailable for {ARCHIVED_UUID}",
        at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
    )
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)

    findings = reconcile.find_unrecoverable(
        config,
        home=Path(ccw_env["HOME"]),
        now=datetime.now(UTC),
    )

    assert findings == (), (
        "an already-archived session's error record was flagged as a loss: "
        f"{findings}"
    )


def test_a_fresh_error_is_not_yet_alarmable(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """The grace period: an error logged moments ago might still resolve
    itself (a retry, the next sweep) before it is fair to call it lost."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    append_log(
        ccw_env,
        session_uuid=LOST_UUID,
        message=f"unreadable transcript /x/{LOST_UUID}.jsonl: boom",
        at=datetime.now(UTC).isoformat(),
    )
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)

    findings = reconcile.find_unrecoverable(
        config, home=Path(ccw_env["HOME"]), now=datetime.now(UTC)
    )

    assert findings == (), "a record only seconds old was already alarmed on"


def test_since_window_excludes_older_records(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """`since` scopes the alert-facing call to recent activity; a genuinely old
    record still exists (found with since=None) but drops out of a window."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    old_at = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    append_log(
        ccw_env,
        session_uuid=LOST_UUID,
        message=f"unreadable transcript /x/{LOST_UUID}.jsonl: boom",
        at=old_at,
    )
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    now = datetime.now(UTC)

    windowed = reconcile.find_unrecoverable(
        config, since=now - reconcile.DEFAULT_WINDOW, home=Path(ccw_env["HOME"]), now=now
    )
    unbounded = reconcile.find_unrecoverable(config, home=Path(ccw_env["HOME"]), now=now)

    assert windowed == (), "a 30-day-old record was inside the 14-day window"
    assert any(f.session_uuid == LOST_UUID for f in unbounded), unbounded


def test_excluded_prefixes_are_never_treated_as_a_session_loss(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`repair: `, `companions: `, `post-archive-write failure at `, `could not
    read sidecar `, and `refused sidecar ` all describe an ALREADY-archived
    session or a sidecar file, never the session's own loss -- real shapes this
    codebase's own writers produce (cli._log_repair_outcome,
    cli._log_companions, capture._log_stage_failure, capture.log_sidecar_trouble)."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    prefixes = (
        "repair: ",
        "companions: ",
        "post-archive-write failure at ",
        "could not read sidecar ",
        "refused sidecar ",
    )
    old_at = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    for i, prefix in enumerate(prefixes):
        append_log(
            ccw_env,
            session_uuid=f"3333333{i}-3333-4333-8333-333333333333",
            message=f"{prefix}something about {LOST_UUID}",
            at=old_at,
        )
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)

    findings = reconcile.find_unrecoverable(
        config, home=Path(ccw_env["HOME"]), now=datetime.now(UTC)
    )

    assert findings == (), findings


def test_old_records_resolve_identity_from_prose(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Every record written before ticket 42 #5 carries no `session_uuid` field
    at all -- the prose fallback must still find the uuid inside `message`."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    append_log(
        ccw_env,
        message=f"unreadable transcript /x/{LOST_UUID}.jsonl: boom",
        at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
    )
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)

    findings = reconcile.find_unrecoverable(
        config, home=Path(ccw_env["HOME"]), now=datetime.now(UTC)
    )

    assert any(f.session_uuid == LOST_UUID for f in findings), findings


def test_no_candidates_skips_the_archive_walk(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stated cost guarantee: zero candidates costs one file read, nothing
    else. Proven by making the archive walk explode if it is ever reached."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)

    def _boom(_root: Path | None) -> set[str]:
        raise AssertionError("the archive walk ran with zero candidates")

    monkeypatch.setattr(reconcile, "archived_session_uuids", _boom)

    findings = reconcile.find_unrecoverable(
        config, home=Path(ccw_env["HOME"]), now=datetime.now(UTC)
    )

    assert findings == ()


def test_malformed_log_lines_do_not_crash(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    log_dir = warehouse_root(ccw_env) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "capture.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{not valid json\n")
    append_log(
        ccw_env,
        message=f"unreadable transcript /x/{LOST_UUID}.jsonl: boom",
        at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
    )
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)

    findings = reconcile.find_unrecoverable(
        config, home=Path(ccw_env["HOME"]), now=datetime.now(UTC)
    )

    assert any(f.session_uuid == LOST_UUID for f in findings), findings


def test_no_log_file_reads_as_no_findings(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)

    findings = reconcile.find_unrecoverable(
        config, home=Path(ccw_env["HOME"]), now=datetime.now(UTC)
    )

    assert findings == ()


# ---------------------------------------------------------------------------
# known_unrecoverable_count / known_unrecoverable_uuids: the cheap ledger read
# ---------------------------------------------------------------------------


def test_known_unrecoverable_reads_only_the_dedup_ledger(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)

    append_log(ccw_env, message=f"unreadable transcript /x/{LOST_UUID}.jsonl: boom")
    count, latest = reconcile.known_unrecoverable_count(config)
    assert count == 0, "a raw 'error' record must not count as a KNOWN loss"
    assert latest is None

    append_log(
        ccw_env,
        status="unrecoverable",
        session_uuid=LOST_UUID,
        message="confirmed unrecoverable",
    )
    count, latest = reconcile.known_unrecoverable_count(config)
    assert count == 1
    assert latest is not None
    assert reconcile.known_unrecoverable_uuids(config) == frozenset({LOST_UUID})


# ---------------------------------------------------------------------------
# ccw reconcile (read-only verb)
# ---------------------------------------------------------------------------


def test_ccw_reconcile_lists_unrecoverable_sessions(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    append_log(
        ccw_env,
        session_uuid=LOST_UUID,
        message=f"unreadable transcript /x/{LOST_UUID}.jsonl: boom",
        at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
    )

    result = run_ccw(["reconcile"], ccw_env)

    assert result.code == 1, result.err
    assert LOST_UUID in result.out


def test_ccw_reconcile_is_clean_with_nothing_lost(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)

    result = run_ccw(["reconcile"], ccw_env)

    assert result.code == 0, result.err
    assert "0 session" in result.out


def test_ccw_reconcile_writes_nothing(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Read-only, per its own contract: the log file it read is unchanged."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    append_log(
        ccw_env,
        session_uuid=LOST_UUID,
        message=f"unreadable transcript /x/{LOST_UUID}.jsonl: boom",
        at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
    )
    log_path = warehouse_root(ccw_env) / "logs" / "capture.jsonl"
    before = log_path.read_bytes()

    run_ccw(["reconcile"], ccw_env)

    assert log_path.read_bytes() == before


# ---------------------------------------------------------------------------
# ccw repair: announce + dedup, and the early-return trap
# ---------------------------------------------------------------------------


def test_repair_announces_and_dedups_new_unrecoverable_sessions(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    append_log(
        ccw_env,
        session_uuid=LOST_UUID,
        message=f"unreadable transcript /x/{LOST_UUID}.jsonl: boom",
        at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
    )

    first = run_ccw(["repair"], ccw_env)
    assert first.code == 0, first.err
    assert "1 newly-confirmed unrecoverable" in first.out

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    assert reconcile.known_unrecoverable_uuids(config) == frozenset({LOST_UUID})

    second = run_ccw(["repair"], ccw_env)
    assert second.code == 0, second.err
    assert "newly-confirmed" not in second.out, "the same loss re-alarmed on a second run"


def test_repair_runs_reconciliation_even_when_nothing_is_desynced(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE TRAP THIS GUARDS AGAINST: repair's desync check early-returns when
    nothing needs re-rendering -- the normal daily case on a healthy machine.
    Reconciliation must run BEFORE that return or it never runs on exactly the
    machines where it matters."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=ARCHIVED_UUID), session_id=ARCHIVED_UUID)
    assert run_ccw(["sweep"], ccw_env).code == 0
    append_log(
        ccw_env,
        session_uuid=LOST_UUID,
        message=f"unreadable transcript /x/{LOST_UUID}.jsonl: boom",
        at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
    )

    result = run_ccw(["repair"], ccw_env)

    assert result.code == 0, result.err
    assert "0 problems" in result.out, "fixture had a real desync; test setup is wrong"
    assert "1 newly-confirmed unrecoverable" in result.out


def test_repair_quiet_still_dedups_but_prints_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    append_log(
        ccw_env,
        session_uuid=LOST_UUID,
        message=f"unreadable transcript /x/{LOST_UUID}.jsonl: boom",
        at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
    )

    result = run_ccw(["repair", "--quiet"], ccw_env)

    assert result.code == 0, result.err
    assert result.out == "", f"--quiet still printed to stdout: {result.out!r}"
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    assert reconcile.known_unrecoverable_uuids(config) == frozenset({LOST_UUID}), (
        "the dedup record must still be written under --quiet"
    )
