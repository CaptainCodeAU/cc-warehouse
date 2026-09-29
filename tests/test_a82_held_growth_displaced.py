"""Oracle tests: three more A82 rulings (W-20260929-A82; Gavin, 2026-09-29).

1. An unreadable manifest makes its folder HELD, not a failure: `ccw build`, every
   sweep and the weekly `ccw archive --to` skip it, log it and add it to the
   refusal ledger, and the run does not fail for that reason alone. `ccw repair`
   then counts it in `repair-summary` and raises its one alert, even when the
   folder is outside the 25-folder sample.
2. "The sub-agent grew" means it was APPENDED to: larger, and the sha256 of its
   first <recorded bytes> bytes equals the kept record. A larger file that is not
   the old bytes plus more is an unexplained change (held), everywhere.
3. Nothing ever deletes or rewrites what repair set aside under
   `_not-sessions/displaced/`, and no check treats it as a stray.
"""

import json
from pathlib import Path
from typing import cast

import pytest
from test_doctor_quick_desync import UUID_A, flip_one_byte, rich_folder, targets

from cc_warehouse import archive, doctor, notify, store
from cc_warehouse.config import Config
from conftest import (
    basic_session,
    claude_projects,
    entry,
    jsonl,
    run_ccw,
    run_cli,
    write_transcript,
)

UUID_NEW = "eeeeeeee-5555-4555-8555-eeeeeeeeeeee"


def silent(*_args: object) -> None:
    """Stands in for a voice sink the test does not observe."""


def log_records(config: Config) -> list[dict[str, object]]:
    path = config.root / "logs" / "capture.jsonl"
    if not path.exists():
        return []
    return [
        cast(dict[str, object], json.loads(line))
        for line in path.read_text("utf-8").splitlines()
        if line.strip()
    ]


def open_refusals_now(config: Config) -> object:
    summaries = [r for r in log_records(config) if r.get("status") == "repair-summary"]
    return summaries[-1]["open_refusals"]


def full_problems(config: Config) -> list[str]:
    _folders, broken = doctor.desync_detail(config)
    return [p.problem for _f, found in broken for p in found]


def manifest_of(folder: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads((folder / "manifest.json").read_text("utf-8")))


def break_manifest(folder: Path) -> None:
    (folder / "manifest.json").write_bytes(b"{ not json")


# ---------------------------------------------------------------------------
# 1. an unreadable manifest is held, and the run does not fail for it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verb", (["build"], ["build", "--rebuild"], ["sweep", "--quiet"], ["archive-to"])
)
def test_an_unreadable_manifest_holds_the_folder_without_failing_the_run(
    ccw_env: dict[str, str], tmp_path: Path, verb: list[str]
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    break_manifest(folder)
    if verb[0] == "sweep":
        write_transcript(ccw_env, basic_session(session_id=UUID_NEW), session_id=UUID_NEW)
    args = ["archive", "--to", str(config.archive_root)] if verb == ["archive-to"] else verb

    result = run_ccw(args, ccw_env)

    assert result.code == 0, f"{args} failed for a held folder: {result.err!r}"
    assert (folder / "manifest.json").read_bytes() == b"{ not json", "the manifest was replaced"
    held = [r for r in log_records(config) if r.get("status") == "writer-held"]
    assert held and held[-1].get("session_uuid") == UUID_A, held


def test_repair_counts_and_alerts_a_writer_held_folder_outside_its_sample(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    break_manifest(folder)
    assert run_ccw(["build"], ccw_env).code == 0
    later = "2026-02-01T10:00:00.000Z"
    write_transcript(
        ccw_env,
        jsonl(
            entry("user", "a newer session", later, session_id=UUID_NEW),
            entry("assistant", "working on it", later, session_id=UUID_NEW),
        ),
        session_id=UUID_NEW,
    )
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    monkeypatch.setattr(doctor, "_DESYNC_SAMPLE", 1)
    sampled, _broken = doctor.desync_detail(config)
    assert folder not in sampled, "fixture: the held folder is out of the sample"
    alerts: list[str] = []

    def record(_config: object, _title: str, message: str) -> None:
        alerts.append(message)

    monkeypatch.setattr(notify, "alert", record)
    monkeypatch.setattr(notify, "speak", silent)

    first = run_cli(["repair", "--quiet"])
    assert first.code == 0, first.err
    assert open_refusals_now(config) == 1
    assert len(alerts) == 1, alerts
    second = run_cli(["repair", "--quiet"])
    assert second.code == 0
    assert len(alerts) == 1, "the held folder alerted again"
    assert open_refusals_now(config) == 1


# ---------------------------------------------------------------------------
# 2. growth is an append, proved by the prefix hash
# ---------------------------------------------------------------------------


def grow_not_append(folder: Path) -> Path:
    """Larger than the record, but the first bytes are not the recorded bytes."""
    agent = targets(folder)["sub-agent"]
    data = bytearray(agent.read_bytes())
    data[data.index(b"reviewer")] = ord("R")
    agent.write_bytes(bytes(data) + b'{"type":"other","extra":true}\n')
    return agent


def change_source(env: dict[str, str]) -> None:
    beside = next(claude_projects(env).glob(f"*/{UUID_A}"))
    source = next((beside / "subagents").glob("*.jsonl"))
    source.write_bytes(source.read_bytes() + b"moved on\n")


def test_build_keeps_the_old_record_for_a_larger_sub_agent_that_is_not_an_append(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    before = manifest_of(folder)["subagents"]
    grow_not_append(folder)
    assert run_ccw(["build", "--rebuild"], ccw_env).code == 0
    assert manifest_of(folder)["subagents"] == before, "a non-append was adopted as growth"
    assert any("sub-agent" in p for p in full_problems(config))


def test_repair_holds_a_larger_sub_agent_that_is_not_an_append(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    change_source(ccw_env)
    grow_not_append(folder)
    assert run_ccw(["repair"], ccw_env).code == 0
    assert open_refusals_now(config) == 1
    assert any("sub-agent" in p for p in full_problems(config))


@pytest.mark.parametrize(
    ("now", "grew"),
    (
        (b"abcdef", True),  # the recorded bytes plus more
        (b"abc", False),  # unchanged: nothing grew
        (b"ab", False),  # shorter
        (b"abX", False),  # same size, different
        (b"abXdef", False),  # longer, but not the recorded bytes first
    ),
)
def test_growth_is_the_recorded_bytes_plus_more(now: bytes, grew: bool) -> None:
    record: dict[str, object] = {"sha256": store.sha256_hex(b"abc"), "bytes": 3}
    assert archive._appended(now, record) is grew  # pyright: ignore[reportPrivateUsage]


def test_a_true_append_is_still_adopted_by_build_and_repair(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    agent = targets(folder)["sub-agent"]
    agent.write_bytes(agent.read_bytes() + b'{"type":"other","extra":true}\n')
    assert run_ccw(["repair"], ccw_env).code == 0
    assert full_problems(config) == []
    assert open_refusals_now(config) == 0


# ---------------------------------------------------------------------------
# 3. displaced copies are never deleted, rewritten or called strays
# ---------------------------------------------------------------------------


def displaced_snapshot(config: Config) -> dict[str, tuple[bytes, int]]:
    root = cast(Path, config.archive_root) / "_not-sessions" / "displaced"
    return {
        p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_nothing_touches_a_displaced_copy(ccw_env: dict[str, str], tmp_path: Path) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    flip_one_byte(targets(folder)["tool-result"])
    assert run_ccw(["repair"], ccw_env).code == 0
    before = displaced_snapshot(config)
    assert before, "fixture: repair set a changed copy aside"

    write_transcript(ccw_env, basic_session(session_id=UUID_NEW), session_id=UUID_NEW)
    for args in (
        ["build", "--rebuild"],
        ["sweep", "--quiet"],
        ["archive", "--to", str(config.archive_root)],
        ["archive", "--to", str(config.archive_root), "--rebuild"],
        ["repair"],
    ):
        result = run_ccw(args, ccw_env)
        assert result.code == 0, f"{args}: {result.err!r}"
        assert "displaced" not in result.err, f"{args} reported a displaced copy: {result.err!r}"
    verify = run_ccw(["archive", "--to", str(config.archive_root), "--verify"], ccw_env)
    assert verify.code == 0, verify.out
    doctor_run = run_ccw(["doctor"], ccw_env)
    assert "displaced" not in doctor_run.out, doctor_run.out

    assert displaced_snapshot(config) == before, "a displaced copy was deleted or rewritten"


def test_a_second_restore_of_other_bytes_adds_a_copy_and_keeps_the_first(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    path = targets(folder)["tool-result"]
    flip_one_byte(path)
    assert run_ccw(["repair"], ccw_env).code == 0
    first = displaced_snapshot(config)
    path.write_bytes(b"line one\nline TWO\n")
    assert run_ccw(["repair"], ccw_env).code == 0
    second = displaced_snapshot(config)
    assert len(second) == 2, second.keys()
    assert all(second[name] == first[name] for name in first), "the first copy changed"
