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

from cc_warehouse import archive
from conftest import (
    basic_session,
    hook_payload,
    run_ccw,
    run_cli,
    settle_companions,
    settle_render,
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


def _log_records(env: dict[str, str]) -> list[dict[str, object]]:
    log_path = warehouse_root(env) / "logs" / "capture.jsonl"
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines()]


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


def test_sweep_run_summary_is_written_even_when_quiet(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    result = run_ccw(["sweep", "--quiet"], ccw_env)
    assert result.code == 0
    assert result.out == "", "--quiet must still drop the stdout summary"

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
    import os

    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    lock = warehouse_root(ccw_env) / "locks" / "sweep"
    lock.parent.mkdir(parents=True)
    lock.write_text(str(os.getpid()))

    result = run_ccw(["sweep"], ccw_env)
    assert result.code == 2

    summaries = _run_summaries(ccw_env, "sweep")
    assert summaries, "a sweep lock refusal left no durable trace"
    assert summaries[-1]["status"] == "error"
    assert "lock held" in str(summaries[-1]["message"])


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
# ccw archive: DELIBERATELY OUT OF SCOPE, and pinned as such.
#
# `_run_archive` does NOT get a run summary, unlike sweep/build above. Found while
# building this: `test_archive_cli.py::test_archive_leaves_the_source_warehouse_
# byte_identical` pins a real, load-bearing contract -- `ccw archive` builds the
# tree BESIDE the warehouse it reads, touching nothing under `config.root`, which
# is the whole safety argument for running it against a live warehouse. A
# capture.jsonl write IS a warehouse write. Ticket 41 Finding 2's actual incident
# was about `ccw sweep`; extending "the same treatment" to archive "for
# consistency" would trade a real, tested invariant for a log line this verb's
# own scheduled job already gets from stdout (`ccw-archive.log`,
# docs/operations.md).
# ---------------------------------------------------------------------------


def test_archive_writes_no_capture_jsonl_record_of_any_kind(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, session_id=UUID_A)).code == 0
    # Wait out the hook's own DETACHED companions child (ticket 37 Part B) before
    # taking the baseline -- it writes "companions-done" to this same log on its
    # own schedule, and that is not archive's doing.
    settle_companions(ccw_env)
    before = len(_log_records(ccw_env))

    result = run_ccw(["archive", "--to", str(archive_root)], ccw_env)
    assert result.code == 0

    assert len(_log_records(ccw_env)) == before, "ccw archive wrote to the warehouse's own log"


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
