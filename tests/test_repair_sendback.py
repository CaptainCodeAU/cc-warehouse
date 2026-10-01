"""Oracle tests: the A82 send-back (W-20260929-A82, 2026-09-29; ruling: Gavin,
"send back"). A wide review proved six holes in 51523da in a sandbox:

  1. a temp-shaped name (`.<name>.<8 chars>.tmp`, store.atomic_write's mkstemp) was
     recorded in a manifest, and the keep-old rule then kept it forever;
  2. the batch-lock excuse covered damage made BEFORE the lock was taken, so a
     15:30 repair inside the 12:30 sweep's lock never alarmed;
  3. a missing manifest re-rendered over damage, and an unreadable one let the next
     build adopt it;
  4. repair refused ccw's own `custom-title.json` / `prompts.jsonl` rewrites;
  5. a refused companion or sub-agent had no working way back: the fix restores it
     byte for byte from `~/.claude` when a source file's sha256 equals the kept
     record, and stays refused otherwise;
  6. repair's intentional exit 1 went through the start-up hook's job-failure path:
     exit 1 now means repair itself failed, and every run writes one
     `repair-summary` line that counts EVERY open refusal, sampled or not.
"""

import json
import os
import time
from pathlib import Path
from typing import cast

import pytest
from test_doctor_quick_desync import UUID_A, flip_one_byte, rich_folder, targets

from cc_warehouse import archive, capture, doctor, notify, store
from cc_warehouse.config import Config
from cc_warehouse.render import RenderOptions
from conftest import (
    basic_session,
    claude_projects,
    entry,
    jsonl,
    run_ccw,
    run_cli,
    write_transcript,
)

ZONE = "Australia/Melbourne"


def silent(*_args: object) -> None:
    """Stands in for a desktop or voice sink the test does not observe."""


@pytest.fixture(autouse=True)
def quiet_sinks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notify, "alert", silent)
    monkeypatch.setattr(notify, "speak", silent)


def manifest_of(folder: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads((folder / "manifest.json").read_text("utf-8")))


def full_problems(config: Config) -> list[str]:
    _folders, broken = doctor.desync_detail(config)
    return [p.problem for _f, found in broken for p in found]


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


def source_of(env: dict[str, str], kind: str) -> Path:
    beside = next(claude_projects(env).glob(f"*/{UUID_A}"))
    if kind == "tool-result":
        return beside / "tool-results" / "toolu_01stdout.txt"
    return next((beside / "subagents").glob("*.jsonl"))


# ---------------------------------------------------------------------------
# 1. temp-shaped names are never recorded and never kept
# ---------------------------------------------------------------------------

TMP = ".late.txt.k3j2h1ab.tmp"


def unit_folder(root: Path) -> Path:
    return archive.write_session_folder(
        root, "widget", basic_session(session_id=UUID_A), RenderOptions(), ZONE
    , fallback_stem="session").directory


def rerender(root: Path, *, rebuild: bool = True) -> None:
    archive.write_session_folder(
        root, "widget", basic_session(session_id=UUID_A), RenderOptions(), ZONE, rebuild=rebuild
    , fallback_stem="session")


def test_a_temp_file_mid_copy_is_never_recorded(tmp_path: Path) -> None:
    folder = unit_folder(tmp_path)
    (folder / "tool-results").mkdir()
    (folder / "tool-results" / TMP).write_bytes(b"half a copy")
    rerender(tmp_path)
    names = [r["name"] for r in cast(list[dict[str, object]], manifest_of(folder)["tool_results"])]
    assert TMP not in names, names


def test_a_temp_name_already_in_a_manifest_is_dropped_not_kept(tmp_path: Path) -> None:
    """The edge census's live shape: an older render recorded the tmp, then the
    copier renamed it. The keep-old rule must not keep a temp name forever."""
    folder = unit_folder(tmp_path)
    (folder / "tool-results").mkdir()
    (folder / "tool-results" / "late.txt").write_bytes(b"the finished copy")
    manifest = manifest_of(folder)
    manifest["tool_results"] = [
        {"name": TMP, "sha256": store.sha256_hex(b"half a copy"), "bytes": 11}
    ]
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    rerender(tmp_path, rebuild=False)

    names = [r["name"] for r in cast(list[dict[str, object]], manifest_of(folder)["tool_results"])]
    assert names == ["late.txt"], names
    assert archive.verify_folder(folder, ZONE) == []


def test_a_stray_temp_file_is_reported_by_repair_not_recorded(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    (folder / "tool-results" / TMP).write_bytes(b"half a copy")
    result = run_ccw(["repair"], ccw_env)
    assert result.code == 0, result.err
    assert TMP in result.err, result.err
    assert any(
        r.get("status") == "repair-stray-temp" and TMP in str(r.get("message"))
        for r in log_records(config)
    )
    assert (folder / "tool-results" / TMP).exists(), "a stray temp file was removed (R4)"


# ---------------------------------------------------------------------------
# 2. the lock excuse covers only files written after the lock was taken
# ---------------------------------------------------------------------------


def age(path: Path, hours: float) -> None:
    moment = time.time() - hours * 3600
    os.utime(path, (moment, moment))


def test_damage_older_than_the_lock_is_refused_on_day_one(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The 3-day sandbox: damage made at 11:00, sweep lock taken 12:30, repair
    15:30. The damaged file is newer than its manifest but OLDER than the lock."""
    config, folder = rich_folder(ccw_env, tmp_path)
    source_of(ccw_env, "tool-result").write_bytes(b"the source changed too\n")  # no restore
    damaged = targets(folder)["tool-result"]
    flip_one_byte(damaged)
    age(folder / "manifest.json", 6)
    age(damaged, 4)
    assert store.acquire_lock(config.root, "build")
    try:
        age(config.root / "locks" / "build", 3)
        run_ccw(["repair"], ccw_env)
    finally:
        store.release_lock(config.root, "build")
    latest = summaries(config)[-1]
    assert latest["open_refusals"] == 1, latest
    assert not any(r.get("status") == "pending" for r in log_records(config))


def test_a_write_after_the_lock_was_taken_is_pending(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    age(folder / "manifest.json", 6)
    assert store.acquire_lock(config.root, "sweep")
    try:
        age(config.root / "locks" / "sweep", 1)
        flip_one_byte(targets(folder)["custom-title"])
        flip_one_byte(targets(folder)["tool-result"])
        result = run_cli(["repair", "--quiet"])
    finally:
        store.release_lock(config.root, "sweep")
    assert result.code == 0, result.err
    assert summaries(config)[-1]["open_refusals"] == 0
    assert any(r.get("status") == "pending" for r in log_records(config))


def test_doctor_uses_the_same_lock_rule(ccw_env: dict[str, str], tmp_path: Path) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    damaged = targets(folder)["tool-result"]
    damaged.write_bytes(damaged.read_bytes()[:-1])
    age(folder / "manifest.json", 6)
    age(damaged, 4)
    assert store.acquire_lock(config.root, "build")
    try:
        age(config.root / "locks" / "build", 3)
        _c, problems, pending, _f = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
    finally:
        store.release_lock(config.root, "build")
    assert (problems, pending) == (1, 0), "damage older than the lock was excused"


# ---------------------------------------------------------------------------
# 3. the two back doors
# ---------------------------------------------------------------------------


def test_a_missing_manifest_is_not_rerendered_over_damage(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    damaged = targets(folder)["tool-result"]
    source = source_of(ccw_env, "tool-result")
    source.write_bytes(b"the source moved on too\n")  # no intact source to restore from
    flip_one_byte(damaged)
    before = damaged.read_bytes()
    (folder / "manifest.json").unlink()

    run_ccw(["repair"], ccw_env)

    assert not (folder / "manifest.json").exists(), "repair re-rendered over damage"
    assert damaged.read_bytes() == before
    assert summaries(config)[-1]["open_refusals"] == 1


def test_a_missing_manifest_with_intact_files_is_still_rerendered(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The ticket 32 case this must not break: the render child died, and every
    copied file still matches its source in ~/.claude byte for byte."""
    config, folder = rich_folder(ccw_env, tmp_path)
    (folder / "manifest.json").unlink()
    result = run_ccw(["repair"], ccw_env)
    assert result.code == 0, result.err
    assert (folder / "manifest.json").exists()
    assert full_problems(config) == []


def test_an_unreadable_manifest_is_not_replaced_by_build(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    flip_one_byte(targets(folder)["sub-agent"])
    (folder / "manifest.json").write_bytes(b"{ not json")
    run_ccw(["build", "--rebuild"], ccw_env)
    assert (folder / "manifest.json").read_bytes() == b"{ not json", "build replaced it"
    assert any("unreadable manifest" in p for p in full_problems(config))


# ---------------------------------------------------------------------------
# 4. ccw's own write_if_changed files are explained
# ---------------------------------------------------------------------------


def test_a_rename_during_a_resume_is_rerendered_not_refused(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    transcript = next(claude_projects(ccw_env).glob(f"*/{UUID_A}.jsonl"))
    grown = transcript.read_bytes() + jsonl(
        entry("user", "resumed", "2026-01-05T11:00:00.000Z", session_id=UUID_A)
    )
    write_transcript(ccw_env, grown, session_id=UUID_A, encoded_dir=transcript.parent.name)
    stored = capture.capture_transcript(
        config, transcript, session_id=UUID_A, cwd=None, defer_companions=True
    )
    assert stored.action == "stored"
    archive.write_custom_title(folder, b'{"customTitle":"renamed mid resume"}\n')

    result = run_ccw(["repair"], ccw_env)

    assert result.code == 0, result.err
    assert summaries(config)[-1]["open_refusals"] == 0
    assert full_problems(config) == []


# ---------------------------------------------------------------------------
# 5. restore byte for byte from ~/.claude when the source matches the record
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ("tool-result", "sub-agent"))
def test_repair_restores_a_changed_file_from_its_intact_source(
    ccw_env: dict[str, str], tmp_path: Path, kind: str
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    path = targets(folder)[kind]
    original = path.read_bytes()
    assert source_of(ccw_env, kind).read_bytes() == original, "fixture: intact source"
    flip_one_byte(path)
    damaged = path.read_bytes()

    result = run_ccw(["repair"], ccw_env)

    assert result.code == 0, result.err
    assert path.read_bytes() == original, "not restored byte for byte"
    assert full_problems(config) == []
    assert summaries(config)[-1]["open_refusals"] == 0
    displaced = list((config.archive_root / "_not-sessions" / "displaced").rglob("*"))  # type: ignore[operator]
    assert any(p.is_file() and p.read_bytes() == damaged for p in displaced), (
        "the damaged bytes were destroyed instead of set aside"
    )


def test_repair_restores_a_deleted_companion_file(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    path = targets(folder)["tool-result"]
    original = path.read_bytes()
    path.unlink()
    result = run_ccw(["repair"], ccw_env)
    assert result.code == 0, result.err
    assert path.read_bytes() == original
    assert full_problems(config) == []


def test_no_matching_source_stays_refused(ccw_env: dict[str, str], tmp_path: Path) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    source_of(ccw_env, "tool-result").write_bytes(b"the source changed as well\n")
    path = targets(folder)["tool-result"]
    flip_one_byte(path)
    damaged = path.read_bytes()
    run_ccw(["repair"], ccw_env)
    assert path.read_bytes() == damaged, "restored from a source that does not match"
    assert summaries(config)[-1]["open_refusals"] == 1


# ---------------------------------------------------------------------------
# 6. exit code, summary line, open refusals outside the sample
# ---------------------------------------------------------------------------


def hold_evidence(env: dict[str, str], tmp_path: Path) -> tuple[Config, Path]:
    """A refusal with no way to restore: the source changed too."""
    config, folder = rich_folder(env, tmp_path)
    source_of(env, "tool-result").write_bytes(b"the source changed as well\n")
    flip_one_byte(targets(folder)["tool-result"])
    return config, folder


def test_a_refusal_exits_zero_and_writes_one_summary(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, _folder = hold_evidence(ccw_env, tmp_path)
    first = run_ccw(["repair"], ccw_env)
    assert first.code == 0, "a refusal went through the job-failure exit code"
    assert len(summaries(config)) == 1
    summary = summaries(config)[0]
    assert summary["open_refusals"] == 1
    refused_at = next(
        r["at"] for r in log_records(config) if r.get("status") == "repair-refused"
    )
    assert summary["oldest_refusal_at"] == refused_at
    assert str(summary["message"]).startswith("repair: ")

    second = run_ccw(["repair"], ccw_env)
    assert second.code == 0
    assert len(summaries(config)) == 2
    assert summaries(config)[1]["oldest_refusal_at"] == refused_at, "the clock restarted"


def test_repair_still_exits_one_when_it_fails_itself(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A render that fails is repair's own failure: that kind of thing, and only
    that kind, keeps exit 1 for the hook's job-failure path."""
    import subprocess

    config, folder = rich_folder(ccw_env, tmp_path)
    for name in archive.GENERATED_NAMES:
        (folder / name).unlink()

    def failing_render(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, "", "render broke (test)")

    monkeypatch.setattr(subprocess, "run", failing_render)
    result = run_cli(["repair", "--quiet"])
    assert result.code == 1
    assert summaries(config)[-1]["open_refusals"] == 0


def test_a_refused_folder_pushed_out_of_the_sample_stays_open(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, folder = hold_evidence(ccw_env, tmp_path)
    assert run_ccw(["repair"], ccw_env).code == 0
    assert summaries(config)[-1]["open_refusals"] == 1
    for day in range(30):
        session_id = f"f{day:07d}-6666-4666-8666-ffffffffffff"
        stamp = f"2026-03-{day + 1:02d}T10:00:00.000Z"
        write_transcript(
            ccw_env,
            jsonl(
                entry("user", f"newer {day}", stamp, session_id=session_id),
                entry("assistant", "ok, working on it now", stamp, session_id=session_id),
            ),
            session_id=session_id,
        )
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    sampled, _broken = doctor.desync_detail(config)
    assert folder not in sampled, "fixture: the refused folder is out of the sample"

    assert run_ccw(["repair"], ccw_env).code == 0
    assert summaries(config)[-1]["open_refusals"] == 1, "the refusal self-cleared"

    # And it is really RE-CHECKED out there: once a human puts the original
    # back, the next run sees the folder verify clean and closes the refusal
    # (without the re-check it would stay counted forever).
    targets(folder)["tool-result"].write_bytes(b"line one\nline two\n")
    assert run_ccw(["repair"], ccw_env).code == 0
    assert summaries(config)[-1]["open_refusals"] == 0, "an out-of-sample fix was never seen"


def test_an_open_refusal_resolves_once_the_folder_verifies_clean(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, folder = hold_evidence(ccw_env, tmp_path)
    damaged = targets(folder)["tool-result"]
    assert run_ccw(["repair"], ccw_env).code == 0
    assert summaries(config)[-1]["open_refusals"] == 1
    damaged.write_bytes(b"line one\nline two\n")  # a human put the original back
    assert run_ccw(["repair"], ccw_env).code == 0
    assert summaries(config)[-1]["open_refusals"] == 0
    assert any(r.get("status") == "repair-refusal-resolved" for r in log_records(config))
