"""Oracle tests: one durable capture.jsonl record per `ccw sweep`/`ccw build`/
`ccw archive` INVOCATION, success or failure (ticket 42 #2).

THE GAP THIS CLOSES. Before this, a run that captured or rendered anything
with zero failures left no durable trace at all -- the launchd stdout log is
empty by design under `--quiet`, and `launchctl print` gives only a lifetime
run count. `ccw archive` wrote nothing to capture.jsonl from any path, success
or failure. Ticket 41's own incident had to reconstruct "did sweep run today"
from indirect signals for exactly this reason.

Mirrors `_log_repair_outcome`'s own contract (`tests/test_batch_failure_logging.py`):
written REGARDLESS of `--quiet`, same six-field schema, extra context folded
into `message` rather than a new JSON key.
"""

import json
from pathlib import Path

import pytest
from test_repair import _age_capture, _break_render  # pyright: ignore[reportPrivateUsage]

from cc_warehouse import archive
from conftest import (
    basic_session,
    hook_payload,
    lock_held_elsewhere,
    mark_archive,
    run_ccw,
    run_cli,
    settle_companions,
    settle_log_status,
    settle_render,
    the_dated_run_line,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-2222-4333-8444-555555555555"
UUID_B = "bbbbbbbb-2222-4333-8444-555555555555"


def configure_archive(env: dict[str, str], archive_root: Path) -> None:
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


def _log_records(env: dict[str, str]) -> list[dict[str, object]]:
    log_path = warehouse_root(env) / "logs" / "capture.jsonl"
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines()]


def start_pid_of(record: dict[str, object], verb: str) -> int:
    """The pid a `<verb> started (pid N)` line names; a positive integer or the test fails."""
    text = str(record["message"]).removeprefix(f"{verb} started (pid ").removesuffix(")")
    assert text.isdigit() and int(text) > 0, record
    return int(text)


def start_pid(record: dict[str, object]) -> int:
    return start_pid_of(record, "sweep")


def _run_summaries(env: dict[str, str], verb: str) -> list[dict[str, object]]:
    return [
        r for r in _log_records(env) if str(r.get("message", "")).startswith(f"{verb}: ")
    ]


# ---------------------------------------------------------------------------
# ccw sweep
# ---------------------------------------------------------------------------


def test_sweep_writes_one_ok_run_summary(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    assert run_ccw(["sweep"], ccw_env).code == 0

    summaries = _run_summaries(ccw_env, "sweep")
    assert len(summaries) == 1, summaries
    assert summaries[0]["status"] == "ok"
    assert "1 stored" in str(summaries[0]["message"])


def test_sweep_run_summary_says_how_long_the_run_took(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """W-20261010-A12: launchd keeps no durations, so the run summary carries
    the run's own elapsed time; before this it was always null."""
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0

    (summary,) = _run_summaries(ccw_env, "sweep")
    elapsed = summary["elapsed_ms"]
    assert isinstance(elapsed, int) and elapsed >= 0, summary


def test_sweep_writes_a_start_line_before_its_run_summary(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """W-20260930-A28: a sweep killed mid-run must leave a trace, so the start is
    recorded before the work, and the summary still closes it afterwards. The
    start line is NOT a run summary: its message has its own `sweep started`
    prefix, so every `sweep: ` reader (one summary per invocation) is unchanged."""
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0

    records = _log_records(ccw_env)
    starts = [i for i, r in enumerate(records) if r.get("status") == "sweep-started"]
    ends = [i for i, r in enumerate(records) if str(r.get("message", "")).startswith("sweep: ")]
    assert len(starts) == 1, records
    assert len(ends) == 1, records
    assert starts[0] < ends[0], records
    start = records[starts[0]]
    assert start["message"] == f"sweep started (pid {start_pid(start)})"
    assert start["session"] is None


def test_a_sweep_dry_run_writes_no_start_line(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    assert run_ccw(["sweep", "--dry-run"], ccw_env).code == 0

    assert [r for r in _log_records(ccw_env) if r.get("status") == "sweep-started"] == []


def test_sweep_run_summary_is_written_even_when_quiet(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    result = run_ccw(["sweep", "--quiet"], ccw_env)
    assert result.code == 0
    the_dated_run_line(result.out, "sweep")  # --quiet keeps only this line

    summaries = _run_summaries(ccw_env, "sweep")
    assert summaries, "a quiet, fully-successful sweep left no durable trace"
    assert summaries[0]["status"] == "ok"


def test_sweep_triggered_build_failure_also_writes_an_error_run_summary(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-item build failure record (ticket 35) and the new per-run
    summary (ticket 42 #2) are both present -- one names the item, the other
    says the run as a whole failed."""
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated sweep-triggered build failure")

    monkeypatch.setattr(archive, "write_session_folder", boom)
    result = run_cli(["sweep"])
    assert result.code == 1

    summaries = _run_summaries(ccw_env, "sweep")
    assert summaries, "a failed sweep left no run summary"
    assert summaries[-1]["status"] == "error"
    assert "1 failed" in str(summaries[-1]["message"])


def test_sweep_lock_refusal_is_logged(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    with lock_held_elsewhere(warehouse_root(ccw_env), "sweep"):
        result = run_ccw(["sweep"], ccw_env)
    assert result.code == 2

    summaries = _run_summaries(ccw_env, "sweep")
    assert summaries, "a sweep lock refusal left no durable trace"
    assert summaries[-1]["status"] == "error"
    assert "lock held" in str(summaries[-1]["message"])


# ---------------------------------------------------------------------------
# ccw repair (W-20261010-A12)
# ---------------------------------------------------------------------------


def _repair_records(env: dict[str, str]) -> tuple[int, int, list[dict[str, object]]]:
    """(index of the one start, index of the one summary, every record)."""
    records = _log_records(env)
    starts = [i for i, r in enumerate(records) if r.get("status") == "repair-started"]
    ends = [i for i, r in enumerate(records) if r.get("status") == "repair-summary"]
    assert len(starts) == 1, records
    assert len(ends) == 1, records
    return starts[0], ends[0], records


def test_repair_writes_a_start_line_before_any_work(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A repair killed mid-run leaves a start with no summary after it. The
    start precedes even the per-folder records, so it is written before work."""
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    _break_render(folder)
    _age_capture(ccw_env, UUID_A, seconds_ago=3600)
    before = len(_log_records(ccw_env))

    assert run_ccw(["repair", "--quiet"], ccw_env).code == 0

    start, end, records = _repair_records(ccw_env)
    assert start == before, records[before:]
    assert start < end
    pid = start_pid_of(records[start], "repair")
    assert records[start]["message"] == f"repair started (pid {pid})"
    assert records[start]["session"] is None


def test_repair_summary_counts_the_work_and_the_time(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """One folder checked and re-rendered: the summary says so in its fields
    and its message, keeps the two fields the start-up hook reads, and
    carries the run's elapsed time."""
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    _break_render(folder)
    _age_capture(ccw_env, UUID_A, seconds_ago=3600)

    assert run_ccw(["repair", "--quiet"], ccw_env).code == 0

    _start, end, records = _repair_records(ccw_env)
    summary = records[end]
    assert summary["status"] == "repair-summary"
    assert summary["open_refusals"] == 0
    assert summary["oldest_refusal_at"] is None
    assert (summary["checked"], summary["fixed"], summary["still_broken"]) == (1, 1, 0)
    assert (summary["held"], summary["pending"]) == (0, 0)
    elapsed = summary["elapsed_ms"]
    assert isinstance(elapsed, int) and elapsed >= 0, summary
    assert summary["message"] == (
        "repair: 1 checked, 1 fixed, 0 still broken, 0 held, 0 pending; 0 open refusal(s)"
    )


# ---------------------------------------------------------------------------
# ccw build
# ---------------------------------------------------------------------------


def test_build_writes_one_ok_run_summary(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, session_id=UUID_A)).code == 0
    settle_render(warehouse_root(ccw_env), 1)

    result = run_ccw(["build"], ccw_env)
    assert result.code == 0

    summaries = _run_summaries(ccw_env, "build")
    assert summaries, "a fully-successful build left no run summary"
    assert summaries[-1]["status"] == "ok"


def test_build_failure_writes_an_error_run_summary(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, session_id=UUID_A)).code == 0

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated build failure")

    monkeypatch.setattr(archive, "write_session_folder", boom)
    result = run_cli(["build", "--rebuild"])
    assert result.code == 1

    summaries = _run_summaries(ccw_env, "build")
    assert summaries, "a failed build left no run summary"
    assert summaries[-1]["status"] == "error"
    assert "1 failed" in str(summaries[-1]["message"])


# ---------------------------------------------------------------------------
# ccw archive (W-20261010-A12)
#
# Until 2026-10-10 archive was pinned OUT of scope: it builds the tree BESIDE
# the warehouse and touched nothing under `config.root`. Gavin ruled that day
# that a build run appends its start and its run summary to logs/capture.jsonl,
# so all three scheduled jobs are logged alike (a folder held for repair adds
# its older `writer-held` line between them). Nothing else under the warehouse
# changes (test_archive_cli.py pins that), and `--verify` still writes nothing.
# ---------------------------------------------------------------------------


def _archive_baseline(ccw_env: dict[str, str], archive_root: Path) -> int:
    configure_archive(ccw_env, archive_root)
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, session_id=UUID_A)).code == 0
    settle_companions(ccw_env)
    settle_log_status(ccw_env, "render-done")
    return len(_log_records(ccw_env))


def test_archive_writes_a_start_line_and_a_timed_run_summary(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """W-20261010-A12, Gavin's ruling: the archive job is logged like the other
    two, a start before the work and a summary with its elapsed time after."""
    archive_root = tmp_path / "archive"
    before = _archive_baseline(ccw_env, archive_root)

    assert run_ccw(["archive", "--to", str(archive_root)], ccw_env).code == 0

    added = _log_records(ccw_env)[before:]
    assert [r["status"] for r in added] == ["archive-started", "ok"], added
    start, summary = added
    pid = start_pid_of(start, "archive")
    assert start["message"] == f"archive started (pid {pid})"
    message = str(summary["message"])
    assert message.startswith("archive: ") and "0 failed" in message, summary
    assert "project.json written" in message, summary
    elapsed = summary["elapsed_ms"]
    assert isinstance(elapsed, int) and elapsed >= 0, summary


def test_archive_verify_still_writes_nothing_to_the_log(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    _archive_baseline(ccw_env, archive_root)
    assert run_ccw(["archive", "--to", str(archive_root)], ccw_env).code == 0
    before = len(_log_records(ccw_env))

    run_ccw(["archive", "--to", str(archive_root), "--verify"], ccw_env)

    assert len(_log_records(ccw_env)) == before


# ---------------------------------------------------------------------------
# The one dated line each scheduled job prints to its own log (W-20261010-A12,
# Gavin's Q9 ruling (b), and 2026-10-10: --quiet keeps that one line).
# ---------------------------------------------------------------------------

def test_a_quiet_sweep_prints_one_dated_summary_line(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    configure_archive(ccw_env, tmp_path / "archive")
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    result = run_ccw(["sweep", "--quiet"], ccw_env)

    assert result.code == 0
    assert the_dated_run_line(result.out, "sweep") == "sweep: 1 items, 1 stored, 0 failed"


def test_a_quiet_repair_prints_one_dated_summary_line(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    configure_archive(ccw_env, tmp_path / "archive")
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0

    result = run_ccw(["repair", "--quiet"], ccw_env)

    assert result.code == 0
    assert the_dated_run_line(result.out, "repair") == (
        "repair: 1 checked, 0 fixed, 0 still broken, 0 held, 0 pending; 0 open refusal(s)"
    )


def test_archive_ends_with_one_dated_summary_line(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    _archive_baseline(ccw_env, archive_root)

    result = run_ccw(["archive", "--to", str(archive_root)], ccw_env)

    assert result.code == 0
    the_dated_run_line(result.out, "archive")


def test_the_dated_line_is_melbourne_twelve_hour_time() -> None:
    """A known instant, read independently: 16:51 UTC on 9 Oct 2026 is
    3:51 AM Saturday 10 Oct in Melbourne (AEDT, UTC+11)."""
    from datetime import UTC, datetime

    from cc_warehouse.cli import dated_run_line

    at = datetime(2026, 10, 9, 16, 51, 51, tzinfo=UTC)
    assert dated_run_line(at, ZONE, "sweep: 1 items", 7_444_000) == (
        "3:51 AM Sat 10 Oct: sweep: 1 items, took 2 h 4 min"
    )
    assert dated_run_line(at, ZONE, "repair: x", 412) == "3:51 AM Sat 10 Oct: repair: x, took 0.4 s"
    assert dated_run_line(at, ZONE, "repair: x", 65_000).endswith("took 1 min 5 s")
    assert dated_run_line(at, ZONE, "repair: x", 12_300).endswith("took 12 s")
    # Truncated, never rounded up across a boundary, and never negative.
    assert dated_run_line(at, ZONE, "repair: x", 9_999).endswith("took 9.9 s")
    assert dated_run_line(at, ZONE, "repair: x", 999).endswith("took 0.9 s")
    assert dated_run_line(at, ZONE, "repair: x", -1_500).endswith("took 0.0 s")


def test_a_failed_sweep_run_summary_appears_in_ccw_status(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closes the loop end to end: a failed run summary is a status="error"
    record like any other, so `ccw status`'s "Recent errors" (ticket 42 #4,
    which already reads capture.jsonl generically) shows it with no code
    change of its own needed."""
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated sweep-triggered build failure")

    monkeypatch.setattr(archive, "write_session_folder", boom)
    assert run_cli(["sweep"]).code == 1

    result = run_cli(["status"])
    assert result.code == 0, result.err
    assert "sweep: " in result.out
    assert "1 failed" in result.out


# ---------------------------------------------------------------------------
# Refused and crashed runs (review of 71d5aec, 2026-10-10; Gavin: "all three
# jobs"). Every refusal leaves a start, a `refused: ` end and the dated line;
# a Python error leaves a `crashed: ` end and still fails as before.
# ---------------------------------------------------------------------------


def _unmark(archive_root: Path) -> None:
    (archive_root / archive.ROOT_MARKER).unlink()


def _starts_and_ends(env: dict[str, str], verb: str) -> list[str]:
    """The run's own lines, in order: 'start' or the end record's message."""
    out: list[str] = []
    for r in _log_records(env):
        if r.get("status") == f"{verb}-started":
            out.append("start")
        elif verb == "repair" and r.get("status") == "repair-summary":
            out.append(str(r["message"]))
        elif verb != "repair" and str(r.get("message", "")).startswith(f"{verb}: "):
            out.append(str(r["message"]))
    return out


def test_a_sweep_refused_for_a_missing_archive_logs_a_refusal_not_an_item_count(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """It ran nothing, so it must not read as a run that finished with one
    failed item: that is what the start-up hook softens to a WARNING."""
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    _unmark(archive_root)

    result = run_ccw(["sweep", "--quiet"], ccw_env)

    assert result.code == 1
    lines = _starts_and_ends(ccw_env, "sweep")
    assert lines[0] == "start" and len(lines) == 2, lines
    assert lines[1].startswith("sweep: refused: "), lines
    assert the_dated_run_line(result.out, "sweep").startswith("sweep: refused: ")


def test_a_sweep_lock_refusal_prints_its_dated_line(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    configure_archive(ccw_env, tmp_path / "archive")
    with lock_held_elsewhere(warehouse_root(ccw_env), "sweep"):
        result = run_ccw(["sweep", "--quiet"], ccw_env)
    assert result.code == 2
    assert the_dated_run_line(result.out, "sweep").startswith("sweep: refused: ")


def test_a_repair_refused_for_a_missing_archive_leaves_a_start_an_end_and_a_line(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    _unmark(archive_root)

    result = run_ccw(["repair", "--quiet"], ccw_env)

    assert result.code == 1
    lines = _starts_and_ends(ccw_env, "repair")
    assert len(lines) == 2 and lines[0] == "start", lines
    assert lines[1].startswith("repair: refused: ") and "open refusal(s)" in lines[1], lines
    assert the_dated_run_line(result.out, "repair").startswith("repair: refused: ")


def test_an_archive_refused_for_a_missing_marker_leaves_a_start_an_end_and_a_line(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    _archive_baseline(ccw_env, archive_root)
    _unmark(archive_root)

    result = run_ccw(["archive", "--to", str(archive_root)], ccw_env)

    assert result.code == 1
    lines = _starts_and_ends(ccw_env, "archive")
    assert len(lines) == 2 and lines[0] == "start", lines
    assert lines[1].startswith("archive: refused: "), lines
    assert the_dated_run_line(result.out, "archive").startswith("archive: refused: ")


def test_an_archive_lock_refusal_prints_its_dated_line(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    _archive_baseline(ccw_env, archive_root)
    with lock_held_elsewhere(warehouse_root(ccw_env), archive.ARCHIVE_LOCK):
        result = run_ccw(["archive", "--to", str(archive_root)], ccw_env)
    assert result.code == 1
    assert the_dated_run_line(result.out, "archive").startswith("archive: refused: ")


@pytest.mark.parametrize("verb", ["sweep", "repair", "archive"])
def test_a_crash_mid_run_leaves_a_crashed_end_and_still_raises(
    verb: str, ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cc_warehouse import doctor, sweep

    archive_root = tmp_path / "archive"
    _archive_baseline(ccw_env, archive_root)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated crash")

    target = {"sweep": (sweep, "sweep"), "repair": (doctor, "desync_detail"),
              "archive": (archive, "migrate")}[verb]
    monkeypatch.setattr(*target, boom)
    args = ["archive", "--to", str(archive_root)] if verb == "archive" else [verb]
    with pytest.raises(RuntimeError, match="simulated crash"):
        run_cli(args)

    lines = _starts_and_ends(ccw_env, verb)
    assert lines[-2] == "start", lines
    assert lines[-1].startswith(f"{verb}: crashed: RuntimeError: simulated crash"), lines
