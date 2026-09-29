"""Oracle tests: the joins between today's four branches (integrate-0929).

Each branch was green on its own. These pin the places where their rules meet,
which no single branch could test ("rules meet only in production", the
reviewers' phrase):

  a. fix-doctor-quick's lock excuse reads fix-os-locks' `store.lock_acquired_at`,
     so a stale lock FILE that nobody holds excuses nothing;
  b. the `repair-summary` line fix-doctor-quick writes is the line
     fix-startup-check's hook reads: same keys, same value types;
  c. fix-parallel-reads' pooled scan still applies the quick check, and doctor
     shows one `locks` line;
  d. repair and the start-up hook end to end, through a hold and a restore;
  e. a batch lock held by ANOTHER process (as a real sweep holds it): repair's
     excuse starts at that process's real acquire time.
"""

import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

# The hook's own test driver and its real-writer fixture, reused on purpose so
# this file drives the hook exactly the way its own tests do (one harness, R9).
from test_cc_capture_freshness_timing import (  # pyright: ignore[reportPrivateUsage]
    _SUMMARY_FIXTURE,  # pyright: ignore[reportPrivateUsage]
    _doctor,  # pyright: ignore[reportPrivateUsage]
    _drive,  # pyright: ignore[reportPrivateUsage]
    _freshness,  # pyright: ignore[reportPrivateUsage]
)
from test_doctor_quick_desync import UUID_A, flip_one_byte, rich_folder, targets

from cc_warehouse import doctor, notify, store
from cc_warehouse.config import Config
from conftest import claude_projects, run_ccw, run_cli

ORIGINAL = b"line one\nline two\n"


def silent(*_args: object) -> None:
    """Stands in for a sink the test does not observe."""


def log_records(config: Config) -> list[dict[str, object]]:
    path = config.root / "logs" / "capture.jsonl"
    if not path.exists():
        return []
    return [
        cast(dict[str, object], json.loads(line))
        for line in path.read_text("utf-8").splitlines()
        if line.strip()
    ]


def summaries(config: Config) -> list[dict[str, object]]:
    return [r for r in log_records(config) if r.get("status") == "repair-summary"]


def tool_source(env: dict[str, str]) -> Path:
    beside = next(claude_projects(env).glob(f"*/{UUID_A}"))
    return beside / "tool-results" / "toolu_01stdout.txt"


def hold_tool_result(env: dict[str, str], folder: Path) -> None:
    """A changed side file whose ~/.claude source changed too: repair must hold it."""
    tool_source(env).write_bytes(ORIGINAL + b"moved on\n")
    flip_one_byte(targets(folder)["tool-result"])


# ---------------------------------------------------------------------------
# a. a stale lock file nobody holds excuses nothing
# ---------------------------------------------------------------------------


def test_a_stale_lock_file_with_a_fresh_mtime_excuses_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    hold_tool_result(ccw_env, folder)
    old = time.time() - 3600
    import os

    os.utime(folder / "manifest.json", (old, old))
    stale = config.root / "locks" / "sweep"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("99999\n", encoding="ascii")
    past = time.time() - 60
    os.utime(stale, (past, past))  # fresh enough that the damage is "after" it
    assert store.lock_acquired_at(config.root, "sweep") is None, "nobody holds it"
    assert doctor.batch_started_at(config.root) is None

    result = run_ccw(["repair"], ccw_env)

    assert result.code == 0, result.err
    assert summaries(config)[-1]["open_refusals"] == 1, "a stale lock file excused damage"
    assert not any(r.get("status") == "pending" for r in log_records(config))


# ---------------------------------------------------------------------------
# b. the repair-summary format both sides depend on
# ---------------------------------------------------------------------------


def test_the_real_repair_summary_matches_what_the_hook_reads(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    hold_tool_result(ccw_env, folder)
    assert run_ccw(["repair"], ccw_env).code == 0
    line = summaries(config)[-1]

    assert set(line) == set(_SUMMARY_FIXTURE), "writer and hook fixture keys drifted"
    for key, value in _SUMMARY_FIXTURE.items():
        assert type(line[key]) is type(value), f"{key}: {line[key]!r} vs {value!r}"
    hook = _freshness()
    parsed = hook.latest_repair_summary(config.root / "logs" / "capture.jsonl")
    assert parsed == line
    assert hook._parse_ts(line["oldest_refusal_at"]) is not None  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# c. the pooled scan keeps the quick check; one locks line
# ---------------------------------------------------------------------------


def test_doctor_shows_one_locks_line_and_one_quick_desync_line(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, _folder = rich_folder(ccw_env, tmp_path)
    report = doctor.diagnose(config, home=Path(ccw_env["HOME"]))
    names = [check.name for check in report.checks]
    assert names.count("locks") == 1, names
    assert names.count("desync") == 1, names
    desync = next(check for check in report.checks if check.name == "desync")
    assert "quick check" in desync.detail
    text = run_ccw(["doctor"], ccw_env).out
    assert sum(1 for line in text.splitlines() if line.split()[1:2] == ["locks"]) == 1, text


def test_the_pooled_quick_scan_reads_only_manifests(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The quick check's no-read promise, through fix-parallel-reads' thread pool."""
    import builtins
    import io
    import os

    config, folder = rich_folder(ccw_env, tmp_path)
    opened: list[str] = []
    real_open = builtins.open

    def wrapped(file: object, *args: object, **kwargs: object) -> object:
        if isinstance(file, (str, os.PathLike)):
            text = os.fspath(cast("str | os.PathLike[str]", file))
            if text.startswith(str(folder)):
                opened.append(text)
        return real_open(file, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "open", wrapped)
    monkeypatch.setattr(io, "open", wrapped)
    assert doctor._desync(config) == (1, 0, 0, None)  # pyright: ignore[reportPrivateUsage]
    assert opened and {Path(p).name for p in opened} == {"manifest.json"}, opened


# ---------------------------------------------------------------------------
# d. repair and the start-up hook, end to end
# ---------------------------------------------------------------------------


def test_repair_and_the_hook_through_a_hold_and_a_restore(
    ccw_env: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    hold_tool_result(ccw_env, folder)
    alerts: list[str] = []

    def record(_config: object, _title: str, message: str) -> None:
        alerts.append(message)

    monkeypatch.setattr(notify, "alert", record)
    monkeypatch.setattr(notify, "speak", silent)

    first = run_cli(["repair", "--quiet"])
    assert first.code == 0, first.err
    assert len(summaries(config)) == 1 and summaries(config)[0]["open_refusals"] == 1
    assert len(alerts) == 1, alerts

    hook = _freshness()
    now = datetime.now(UTC)
    held = _drive(hook, tmp_path, monkeypatch, capsys, _doctor(0), now + timedelta(minutes=1))
    assert "1 archive folder(s)" in held.stdout, held.stdout
    assert held.spoken == [], "the hook spoke on its first check after repair's own alert"

    tool_source(ccw_env).write_bytes(ORIGINAL)  # the original is back in ~/.claude
    second = run_cli(["repair", "--quiet"])
    assert second.code == 0, second.err
    assert summaries(config)[-1]["open_refusals"] == 0
    assert targets(folder)["tool-result"].read_bytes() == ORIGINAL, "not restored"

    cleared = _drive(hook, tmp_path, monkeypatch, capsys, _doctor(0), now + timedelta(minutes=15))
    assert "archive folder" not in cleared.stdout, cleared.stdout
    assert cleared.spoken == [] and cleared.desktop == []


# ---------------------------------------------------------------------------
# e. a batch lock held by another process, as a sweep holds it
# ---------------------------------------------------------------------------

_HOLDER = """
import sys, time
from pathlib import Path
from cc_warehouse import store
root = Path(sys.argv[1])
assert store.acquire_lock(root, "sweep")
print("held", flush=True)
sys.stdin.readline()
store.release_lock(root, "sweep")
"""


def test_repair_under_another_process_sweep_lock_uses_its_real_acquire_time(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    import os

    config, folder = rich_folder(ccw_env, tmp_path)
    tool_source(ccw_env).write_bytes(ORIGINAL + b"moved on\n")
    before_lock = targets(folder)["tool-result"]
    flip_one_byte(before_lock)  # damage from BEFORE the batch started
    earlier = time.time() - 120
    os.utime(before_lock, (earlier, earlier))
    old = time.time() - 3600
    os.utime(folder / "manifest.json", (old, old))

    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(config.root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        taken = store.lock_acquired_at(config.root, "sweep")
        assert taken is not None and abs(taken - time.time()) < 30, taken

        result = run_ccw(["repair"], ccw_env)
        assert result.code == 0, result.err
        assert summaries(config)[-1]["open_refusals"] == 1, "pre-lock damage was excused"

        # A write made AFTER the other process took its lock is its own: pending.
        agent = targets(folder)["sub-agent"]
        agent_source = next((tool_source(ccw_env).parent.parent / "subagents").glob("*.jsonl"))
        agent_source.write_bytes(agent_source.read_bytes() + b"moved on\n")
        flip_one_byte(agent)
        run_ccw(["repair"], ccw_env)
        pending = [r for r in log_records(config) if r.get("status") == "pending"]
        assert pending == [], "a folder with pre-lock damage must stay held, not pending"
    finally:
        assert holder.stdin is not None
        holder.stdin.write("\n")
        holder.stdin.flush()
        holder.wait(timeout=30)
    assert store.lock_acquired_at(config.root, "sweep") is None


def test_only_a_write_after_another_process_took_the_lock_is_pending(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    import os

    config, folder = rich_folder(ccw_env, tmp_path)
    tool_source(ccw_env).write_bytes(ORIGINAL + b"moved on\n")
    old = time.time() - 3600
    os.utime(folder / "manifest.json", (old, old))
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(config.root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        time.sleep(0.05)
        flip_one_byte(targets(folder)["tool-result"])  # written while the batch runs
        result = run_ccw(["repair"], ccw_env)
        assert result.code == 0, result.err
        assert summaries(config)[-1]["open_refusals"] == 0
        assert any(r.get("status") == "pending" for r in log_records(config))
    finally:
        assert holder.stdin is not None
        holder.stdin.write("\n")
        holder.stdin.flush()
        holder.wait(timeout=30)
    # Released: the same change is judged normally and held.
    assert run_ccw(["repair"], ccw_env).code == 0
    assert summaries(config)[-1]["open_refusals"] == 1

