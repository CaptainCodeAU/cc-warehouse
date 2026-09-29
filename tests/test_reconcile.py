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
from conftest import basic_session, mark_archive, run_ccw, warehouse_root, write_transcript

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
    mark_archive(archive_root, ZONE)


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
    read sidecar `, `refused sidecar `, and (ticket 42 #2) `sweep: `/`build: `
    all describe an ALREADY-archived session, a sidecar file, or a per-RUN
    summary naming no session at all -- never the session's own loss. Real
    shapes this codebase's own writers produce (cli._log_repair_outcome,
    cli._log_companions, capture._log_stage_failure, capture.log_sidecar_trouble,
    cli._log_run_summary). `ccw archive` has no such summary at all -- see
    cli._run_archive's own scope note."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    prefixes = (
        "repair: ",
        "companions: ",
        "post-archive-write failure at ",
        "could not read sidecar ",
        "refused sidecar ",
        "sweep: ",
        "build: ",
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


# ---------------------------------------------------------------------------
# Empty sessions are not losses (W-20260929-A60, ruling: Gavin, 2026-09-29)
# ---------------------------------------------------------------------------
#
# THE FALSE ALARM THIS EXISTS FOR: `ccw repair` announced "5 sessions are
# permanently unrecoverable. Their transcripts vanished before capture." All 5
# were sessions where nothing was said, so Claude Code never wrote a transcript
# and nothing was lost. THE RULING: a session whose only `history.jsonl` input is
# `/quit` or `/exit` is empty; a session with ZERO history rows is empty only when
# `~/.claude/session-env/<uuid>` exists as a directory (option B). Zero rows alone
# is NOT enough: measured 2026-09-29, 3,550 real September headless (`sdk-cli`)
# sessions with typed prompts had no history rows at all. Every doubt (missing or
# unreadable history, a history file that starts after the session ended, a
# session-env that is not a directory) fails toward ALERTING.
#
# History rows are copied in SHAPE from a real row: the five keys every one of
# 22,822 real rows carries (`display`, `pastedContents`, `project`, `sessionId`,
# `timestamp` as integer milliseconds), with an externalised or inlined paste as
# `{"<n>": {"id": <int>, "type": "text", ...}}`. The text is invented.

QUIT_UUID = "33333333-3333-4333-8333-333333333333"
EXIT_UUID = "44444444-4444-4444-8444-444444444444"
SILENT_UUID = "55555555-5555-4555-8555-555555555555"
REAL_UUID = "66666666-6666-4666-8666-666666666666"
OTHER_UUID = "77777777-7777-4777-8777-777777777777"


def history_row(session_uuid: str, display: str, *, at: datetime, pasted: object = None) -> str:
    row: dict[str, object] = {
        "display": display,
        "pastedContents": pasted if pasted is not None else {},
        "timestamp": int(at.timestamp() * 1000),
        "project": "/Users/alice/proj",
        "sessionId": session_uuid,
    }
    return json.dumps(row)


def write_history(env: dict[str, str], *lines: str) -> Path:
    """`~/.claude/history.jsonl` in the sandbox, always led by an OLDER row from
    an unrelated session, so the file demonstrably covers the time the lost
    sessions ran (the truncation guard is tested on its own, below)."""
    three_days_ago = datetime.now(UTC) - timedelta(days=3)
    old = history_row(OTHER_UUID, "an older unrelated prompt", at=three_days_ago)
    path = Path(env["HOME"]) / ".claude" / "history.jsonl"
    path.write_text("\n".join((old, *lines)) + "\n", encoding="utf-8")
    return path


def make_session_env(env: dict[str, str], session_uuid: str) -> Path:
    path = Path(env["HOME"]) / ".claude" / "session-env" / session_uuid
    path.mkdir(parents=True)
    return path


def log_lost(env: dict[str, str], *uuids: str) -> None:
    for session_uuid in uuids:
        append_log(
            env,
            session_uuid=session_uuid,
            message=f"unreadable transcript /x/{session_uuid}.jsonl: boom",
            at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        )


def lost_uuids(env: dict[str, str], archive_root: Path) -> set[str]:
    config = Config(root=warehouse_root(env), archive_root=archive_root, archive_timezone=ZONE)
    findings = reconcile.find_unrecoverable(config, home=Path(env["HOME"]), now=datetime.now(UTC))
    return {f.session_uuid for f in findings}


@pytest.mark.parametrize("display", ["/quit", "/exit", " /quit"])
def test_a_quit_or_exit_only_session_is_not_unrecoverable(
    ccw_env: dict[str, str], tmp_path: Path, display: str
) -> None:
    """RULING, arm 1. `" /quit"` is a real variant (1 of 22,822 rows measured),
    so surrounding whitespace is stripped before the exact match."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    at = datetime.now(UTC) - timedelta(hours=3)
    write_history(ccw_env, history_row(QUIT_UUID, display, at=at))
    log_lost(ccw_env, QUIT_UUID)

    assert lost_uuids(ccw_env, archive_root) == set()


def test_zero_history_rows_with_a_session_env_dir_is_not_unrecoverable(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """RULING, arm 2 (option B): nothing typed at all, in an interactive session."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_history(ccw_env)
    make_session_env(ccw_env, SILENT_UUID)
    log_lost(ccw_env, SILENT_UUID)

    assert lost_uuids(ccw_env, archive_root) == set()


def test_zero_history_rows_without_a_session_env_dir_still_alerts(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE CASE OPTION B EXISTS FOR: a headless session never writes history rows
    even when it has real prompts, so zero rows alone proves nothing."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_history(ccw_env)
    log_lost(ccw_env, SILENT_UUID)

    assert lost_uuids(ccw_env, archive_root) == {SILENT_UUID}


@pytest.mark.parametrize(
    "displays",
    [
        ["a real prompt"],
        ["a real prompt", "/quit"],
        ["/clear"],
        ["/model", "/exit"],
        ["exit"],
        ["/QUIT"],
    ],
)
def test_a_session_with_any_other_input_still_alerts(
    ccw_env: dict[str, str], tmp_path: Path, displays: list[str]
) -> None:
    """Real input, and everything OUTSIDE the ruling: other slash commands, the
    bare word `exit` (7 real rows) and case variants are not silenced."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    at = datetime.now(UTC) - timedelta(hours=3)
    write_history(ccw_env, *(history_row(REAL_UUID, d, at=at) for d in displays))
    make_session_env(ccw_env, REAL_UUID)
    log_lost(ccw_env, REAL_UUID)

    assert lost_uuids(ccw_env, archive_root) == {REAL_UUID}


def test_a_paste_only_row_is_real_input(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Edge case 4: `pastedContents` present means something was said, whatever
    `display` reads."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    pasted = {"1": {"id": 1, "type": "text", "contentHash": "0123456789abcdef"}}
    write_history(
        ccw_env,
        history_row(REAL_UUID, "/quit", at=datetime.now(UTC) - timedelta(hours=3), pasted=pasted),
    )
    log_lost(ccw_env, REAL_UUID)

    assert lost_uuids(ccw_env, archive_root) == {REAL_UUID}


def test_missing_history_fails_toward_alerting(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Edge case 1: without history.jsonl nothing proves a session was empty."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    make_session_env(ccw_env, SILENT_UUID)
    log_lost(ccw_env, SILENT_UUID)

    assert lost_uuids(ccw_env, archive_root) == {SILENT_UUID}


def test_unreadable_history_fails_toward_alerting(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    (Path(ccw_env["HOME"]) / ".claude" / "history.jsonl").mkdir()
    make_session_env(ccw_env, SILENT_UUID)
    log_lost(ccw_env, SILENT_UUID)

    assert lost_uuids(ccw_env, archive_root) == {SILENT_UUID}


def test_a_session_env_that_is_not_a_directory_fails_toward_alerting(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_history(ccw_env)
    env_dir = Path(ccw_env["HOME"]) / ".claude" / "session-env"
    env_dir.mkdir(parents=True)
    (env_dir / SILENT_UUID).write_text("", encoding="utf-8")
    log_lost(ccw_env, SILENT_UUID)

    assert lost_uuids(ccw_env, archive_root) == {SILENT_UUID}


def test_zero_rows_in_a_history_that_starts_after_the_session_still_alerts(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Edge case 5: when every surviving history row is NEWER than the error, the
    file cannot vouch that the session said nothing (its rows may have been cut)."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    newer = history_row(OTHER_UUID, "a newer prompt", at=datetime.now(UTC) - timedelta(minutes=5))
    (Path(ccw_env["HOME"]) / ".claude" / "history.jsonl").write_text(newer + "\n", encoding="utf-8")
    make_session_env(ccw_env, SILENT_UUID)
    log_lost(ccw_env, SILENT_UUID)

    assert lost_uuids(ccw_env, archive_root) == {SILENT_UUID}


def _record_alerts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from cc_warehouse import notify

    fired: list[str] = []

    def record(_config: Config, _title: str, message: str) -> None:
        fired.append(message)

    def silent(_config: Config, _message: str) -> None:
        return None

    monkeypatch.setattr(notify, "alert", record)
    monkeypatch.setattr(notify, "speak", silent)
    return fired


def test_repair_writes_no_record_and_no_alert_for_empty_sessions(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported incident, end to end: every empty shape at once, nothing
    announced and nothing added to the dedup ledger."""
    from conftest import run_cli

    fired = _record_alerts(monkeypatch)
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    at = datetime.now(UTC) - timedelta(hours=3)
    write_history(
        ccw_env, history_row(QUIT_UUID, "/quit", at=at), history_row(EXIT_UUID, "/exit", at=at)
    )
    make_session_env(ccw_env, SILENT_UUID)
    log_lost(ccw_env, QUIT_UUID, EXIT_UUID, SILENT_UUID)

    result = run_cli(["repair"])

    assert result.code == 0, result.err
    assert "newly-confirmed" not in result.out
    assert fired == []
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    assert reconcile.known_unrecoverable_uuids(config) == frozenset()


def test_repair_on_a_mix_announces_exactly_the_real_losses(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conftest import run_cli

    fired = _record_alerts(monkeypatch)
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    at = datetime.now(UTC) - timedelta(hours=3)
    write_history(
        ccw_env,
        history_row(QUIT_UUID, "/quit", at=at),
        history_row(EXIT_UUID, "/exit", at=at),
        history_row(REAL_UUID, "a real prompt", at=at),
    )
    make_session_env(ccw_env, SILENT_UUID)
    log_lost(ccw_env, QUIT_UUID, EXIT_UUID, SILENT_UUID, REAL_UUID, LOST_UUID)

    result = run_cli(["repair"])

    assert result.code == 0, result.err
    assert "2 newly-confirmed unrecoverable" in result.out
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    assert reconcile.known_unrecoverable_uuids(config) == frozenset({REAL_UUID, LOST_UUID})
    assert len(fired) == 1, fired
    assert fired[0].startswith("cc-warehouse: 2 sessions are permanently unrecoverable."), fired


# ---------------------------------------------------------------------------
# Retraction records (W-20260929-A61; ruling: Gavin, 2026-09-29, option b)
# ---------------------------------------------------------------------------
#
# The empty-session ruling above only stops NEW announcements. Sessions `ccw
# repair` had already announced stay in the append-only ledger, so doctor kept
# counting them (56 on the real machine, 38 of them empty). `ccw repair` now
# appends one `unrecoverable-retracted` record per recorded uuid the same
# classifier calls empty, and the cheap readers subtract it. No line of
# capture.jsonl is ever rewritten or removed.

RETRACTED = "unrecoverable-retracted"


def log_recorded(env: dict[str, str], *uuids: str) -> None:
    """The dedup record `ccw repair` wrote before the empty-session ruling."""
    for session_uuid in uuids:
        append_log(
            env,
            status="unrecoverable",
            session_uuid=session_uuid,
            message=f"confirmed unrecoverable: unreadable transcript /x/{session_uuid}.jsonl",
        )


def ledger(env: dict[str, str]) -> list[dict[str, object]]:
    path = warehouse_root(env) / "logs" / "capture.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def retractions(env: dict[str, str]) -> list[dict[str, object]]:
    return [r for r in ledger(env) if r.get("status") == RETRACTED]


def empty_and_real_fixture(env: dict[str, str], archive_root: Path) -> None:
    """QUIT said only /quit, SILENT has no rows and a session-env dir, REAL typed
    a prompt: all three were announced before the ruling."""
    configure(env, archive_root)
    at = datetime.now(UTC) - timedelta(hours=3)
    write_history(
        env, history_row(QUIT_UUID, "/quit", at=at), history_row(REAL_UUID, "a real prompt", at=at)
    )
    make_session_env(env, SILENT_UUID)
    log_lost(env, QUIT_UUID, SILENT_UUID, REAL_UUID)
    log_recorded(env, QUIT_UUID, SILENT_UUID, REAL_UUID)


def test_doctor_count_excludes_retracted_uuids(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    from conftest import run_cli

    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    log_recorded(ccw_env, LOST_UUID, QUIT_UUID)
    append_log(ccw_env, status=RETRACTED, session_uuid=QUIT_UUID, message="retracted")

    result = run_cli(["doctor"])

    assert "1 session(s) on record as unrecoverable" in result.out, result.out
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    assert reconcile.known_unrecoverable_uuids(config) == frozenset({LOST_UUID})


def test_duplicate_records_count_once_and_orphan_retractions_are_ignored(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Edge cases 1 and 2: two unrecoverable lines for one uuid count once, and a
    retraction naming a uuid with no unrecoverable record changes nothing."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    log_recorded(ccw_env, LOST_UUID, LOST_UUID)
    append_log(ccw_env, status=RETRACTED, session_uuid=OTHER_UUID, message="retracted")
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)

    count, latest = reconcile.known_unrecoverable_count(config)

    assert count == 1
    assert latest is not None
    assert reconcile.known_unrecoverable_uuids(config) == frozenset({LOST_UUID})


def test_the_cheap_count_never_reads_history(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Edge case 3: `known_unrecoverable_count` is on the SessionStart path."""

    def forbidden(_home: Path) -> None:
        raise AssertionError("history.jsonl read on the SessionStart path")

    monkeypatch.setattr(reconcile, "_read_history", forbidden)
    archive_root = tmp_path / "archive"
    empty_and_real_fixture(ccw_env, archive_root)
    append_log(ccw_env, status=RETRACTED, session_uuid=QUIT_UUID, message="retracted")
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)

    assert reconcile.known_unrecoverable_count(config)[0] == 2
    assert reconcile.known_unrecoverable_uuids(config) == frozenset({SILENT_UUID, REAL_UUID})


def test_repair_retracts_each_newly_empty_recorded_uuid_exactly_once(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    from conftest import run_cli

    archive_root = tmp_path / "archive"
    empty_and_real_fixture(ccw_env, archive_root)
    log_recorded(ccw_env, SILENT_UUID)  # edge case 1: a duplicate line, retracted once
    before = ledger(ccw_env)

    first = run_cli(["repair"])

    assert first.code == 0, first.err
    after_first = ledger(ccw_env)
    assert after_first[: len(before)] == before, "an existing ledger line was rewritten"
    assert sorted(str(r["session_uuid"]) for r in retractions(ccw_env)) == sorted(
        [QUIT_UUID, SILENT_UUID]
    )
    recorded_keys = {k for k in before[-1]}
    assert all(set(r) == recorded_keys for r in retractions(ccw_env)), retractions(ccw_env)
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    assert reconcile.known_unrecoverable_uuids(config) == frozenset({REAL_UUID})

    second = run_cli(["repair"])

    assert second.code == 0, second.err
    assert ledger(ccw_env) == after_first, "a second repair appended again"


def test_a_recorded_uuid_that_is_still_unrecoverable_is_not_retracted(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """REAL typed a prompt; LOST has no rows and no session-env dir (a headless
    session): both stay on record."""
    from conftest import run_cli

    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    at = datetime.now(UTC) - timedelta(hours=3)
    write_history(ccw_env, history_row(REAL_UUID, "a real prompt", at=at))
    log_lost(ccw_env, REAL_UUID, LOST_UUID)
    log_recorded(ccw_env, REAL_UUID, LOST_UUID)

    result = run_cli(["repair"])

    assert result.code == 0, result.err
    assert retractions(ccw_env) == []
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    assert reconcile.known_unrecoverable_uuids(config) == frozenset({REAL_UUID, LOST_UUID})


def test_a_retraction_raises_no_alert(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conftest import run_cli

    fired = _record_alerts(monkeypatch)
    archive_root = tmp_path / "archive"
    empty_and_real_fixture(ccw_env, archive_root)

    result = run_cli(["repair"])

    assert result.code == 0, result.err
    assert len(retractions(ccw_env)) == 2, "control: the fixture must retract something"
    assert fired == []


def test_an_unreadable_history_retracts_nothing(ccw_env: dict[str, str], tmp_path: Path) -> None:
    from conftest import run_cli

    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    (Path(ccw_env["HOME"]) / ".claude" / "history.jsonl").mkdir()
    make_session_env(ccw_env, SILENT_UUID)
    log_lost(ccw_env, SILENT_UUID)
    log_recorded(ccw_env, SILENT_UUID)

    result = run_cli(["repair"])

    assert result.code == 0, result.err
    assert retractions(ccw_env) == []
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    assert reconcile.known_unrecoverable_uuids(config) == frozenset({SILENT_UUID})


def test_repair_reads_history_at_most_once_and_only_when_needed(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One read covers both the new-loss check and the retraction pass; a ledger
    with nothing left to reconsider and no candidate costs no read at all."""
    from conftest import run_cli

    real_read = reconcile._read_history  # pyright: ignore[reportPrivateUsage]
    calls: list[Path] = []

    def counting(home: Path) -> object:
        calls.append(home)
        return real_read(home)

    monkeypatch.setattr(reconcile, "_read_history", counting)
    archive_root = tmp_path / "archive"
    empty_and_real_fixture(ccw_env, archive_root)
    log_lost(ccw_env, LOST_UUID)  # an unannounced loss: find_unrecoverable needs history too

    assert run_cli(["repair"]).code == 0
    assert len(calls) == 1, calls


def test_repair_skips_history_when_nothing_is_left_to_reconsider(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every recorded uuid already retracted, and no fresh candidate: no read."""
    from conftest import run_cli

    calls: list[Path] = []

    def counting(home: Path) -> None:
        calls.append(home)

    monkeypatch.setattr(reconcile, "_read_history", counting)
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    log_recorded(ccw_env, QUIT_UUID)
    append_log(ccw_env, status=RETRACTED, session_uuid=QUIT_UUID, message="retracted")

    assert run_cli(["repair"]).code == 0
    assert calls == [], "history read with nothing to reconsider"


def test_a_retracted_uuid_announced_again_counts_again(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Out of scope in the ruling, pinned so the behaviour is chosen, not
    accidental: the LATEST record for a uuid decides, so a later unrecoverable
    record after a retraction puts it back on record."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    log_recorded(ccw_env, LOST_UUID)
    append_log(ccw_env, status=RETRACTED, session_uuid=LOST_UUID, message="retracted")
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    assert reconcile.known_unrecoverable_uuids(config) == frozenset()

    log_recorded(ccw_env, LOST_UUID)

    assert reconcile.known_unrecoverable_uuids(config) == frozenset({LOST_UUID})
    assert reconcile.known_unrecoverable_count(config)[0] == 1
