"""Oracle tests: the sweep pauses for a vanished archive root, then carries on
(W-20261002-A72; principal ruling 2026-10-02, "wait, then carry on").

THE INCIDENT. The archive root is an SMB share. On 2026-10-02 the 02:00 sweep
ran for seven hours; the share dropped at 02:31 and came back at 02:34, and the
sweep, which checked the root marker once at entry, failed 767 items: one
`.tmp` write lost mid-item, then 766 sub-agents refused with `Permission
denied: '/Volumes/mac'`. The share dropped four times in six days.

THE RULING. When the root stops being proven mid-run, the sweep waits,
re-checking every 30 s for up to 15 min, then carries on. An item that failed
because the root vanished under it is retried once when the root returns. A
root that never returns stops the run with ONE line, not a failure per item.

Every test drives the real CLI in-process and swaps only the sleep and the
clock (`archive.root_wait_sleep` / `archive.root_wait_clock`), so no test
sleeps in real time. "Vanished" is the root directory renamed aside, which is
what an unmounted share looks like to `root_problem` (no such directory).
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import cc_warehouse.build as build_module
import cc_warehouse.capture as capture_module
from cc_warehouse import archive
from conftest import (
    basic_session,
    catalog_rows,
    mark_archive,
    run_cli,
    warehouse_root,
    write_transcript,
)

ZONE = "UTC"
UUID_A = "a7211111-1111-4111-8111-111111111111"
UUID_B = "b7222222-2222-4222-8222-222222222222"
UUID_C = "c7233333-3333-4333-8333-333333333333"
UUID_D = "d7244444-4444-4444-8444-444444444444"
UUID_E = "e7255555-5555-4555-8555-555555555555"


class FakeTime:
    """A clock that only moves when the code under test sleeps."""

    def __init__(self, on_sleep: Callable[[int], None] | None = None) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []
        self.on_sleep = on_sleep

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        if self.on_sleep is not None:
            self.on_sleep(len(self.sleeps))


def install(monkeypatch: pytest.MonkeyPatch, fake: FakeTime) -> None:
    monkeypatch.setattr(archive, "root_wait_sleep", fake.sleep)
    monkeypatch.setattr(archive, "root_wait_clock", fake.clock)


def configure(env: dict[str, str], tmp_path: Path, *, with_archive: bool = True) -> Path:
    """config.toml under the sandboxed HOME. `keep_objects = false`, the live
    machine's setting: the archive is the only copy, so an archive write that
    fails fails the capture instead of being logged and swallowed."""
    archive_root = tmp_path / "share" / "cc-warehouse-archive"
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [f'root = "{warehouse_root(env)}"', f'archive_timezone = "{ZONE}"']
    if with_archive:
        lines += [f'archive_root = "{archive_root}"', "keep_objects = false"]
        mark_archive(archive_root, ZONE)
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return archive_root


def seed(env: dict[str, str], *uuids: str) -> None:
    for uuid in uuids:
        write_transcript(env, basic_session(session_id=uuid), session_id=uuid)


class Share:
    """The archive root as a mount that can drop and come back."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.aside = root.with_name(root.name + "-while-unmounted")

    def drop(self) -> None:
        self.root.rename(self.aside)

    def restore(self) -> None:
        self.aside.rename(self.root)


def cataloged(env: dict[str, str]) -> set[str]:
    rows = catalog_rows(env, "SELECT session_uuid FROM session")
    return {str(r[0]) for r in rows}  # type: ignore[index]


def log_records(env: dict[str, str]) -> list[dict[str, object]]:
    path = warehouse_root(env) / "logs" / "capture.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def pauses(env: dict[str, str]) -> list[dict[str, object]]:
    return [r for r in log_records(env) if r.get("status") == archive.ROOT_PAUSED]


def capture_then(
    monkeypatch: pytest.MonkeyPatch, after_uuid: str, action: Callable[[], None]
) -> None:
    """Run `action` once, right after `after_uuid` has been captured."""
    real = capture_module.capture_transcript
    fired: list[bool] = []

    def wrapped(config: object, path: Path, *, session_id: object, cwd: object) -> object:
        result = real(config, path, session_id=session_id, cwd=cwd)  # type: ignore[arg-type]
        if path.stem == after_uuid and not fired:
            fired.append(True)
            action()
        return result

    monkeypatch.setattr(capture_module, "capture_transcript", wrapped)


# ---------------------------------------------------------------------------
# The ruling's three outcomes
# ---------------------------------------------------------------------------


def test_root_vanishes_between_items_and_returns_nothing_fails(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    share = Share(configure(ccw_env, tmp_path))
    seed(ccw_env, UUID_A, UUID_B, UUID_C)
    fake = FakeTime(on_sleep=lambda n: share.restore() if n == 1 else None)
    install(monkeypatch, fake)
    capture_then(monkeypatch, UUID_A, share.drop)

    result = run_cli(["sweep"])

    assert result.code == 0, result.out + result.err
    assert "sweep failed" not in result.err
    assert cataloged(ccw_env) == {UUID_A, UUID_B, UUID_C}
    assert fake.sleeps == [archive.ROOT_WAIT_POLL_SECONDS]
    logged = pauses(ccw_env)
    assert len(logged) == 1, logged
    assert UUID_B in str(logged[0]["message"])
    assert "paused" in result.out, result.out


def test_root_vanishes_during_an_item_and_that_item_is_retried_once(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Last night's first failure: the drop hit mid-write and the item raised."""
    share = Share(configure(ccw_env, tmp_path))
    seed(ccw_env, UUID_A, UUID_B, UUID_C)
    fake = FakeTime(on_sleep=lambda n: share.restore() if n == 1 else None)
    install(monkeypatch, fake)
    real = capture_module.capture_transcript
    attempts: list[str] = []

    def wrapped(config: object, path: Path, *, session_id: object, cwd: object) -> object:
        attempts.append(path.stem)
        if path.stem == UUID_B and attempts.count(UUID_B) == 1:
            share.drop()
            raise FileNotFoundError(2, "No such file or directory", "x.meta.json.abc.tmp")
        return real(config, path, session_id=session_id, cwd=cwd)  # type: ignore[arg-type]

    monkeypatch.setattr(capture_module, "capture_transcript", wrapped)

    result = run_cli(["sweep"])

    assert result.code == 0, result.out + result.err
    assert attempts.count(UUID_B) == 2
    assert cataloged(ccw_env) == {UUID_A, UUID_B, UUID_C}
    assert len(pauses(ccw_env)) == 1
    # The first attempt's failure was the root's, not the item's: it must not
    # sit in the audit log as a lost session for `reconcile` to find.
    errors = [r for r in log_records(ccw_env) if r.get("status") == "error"]
    assert errors == [], errors


def test_root_never_returns_stops_with_one_line(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    share = Share(configure(ccw_env, tmp_path))
    seed(ccw_env, UUID_A, UUID_B, UUID_C, UUID_D)
    fake = FakeTime()
    install(monkeypatch, fake)
    capture_then(monkeypatch, UUID_A, share.drop)

    result = run_cli(["sweep"])

    assert result.code != 0, result.out + result.err
    lines = [line for line in result.err.splitlines() if line.strip()]
    assert len(lines) == 1, result.err
    assert lines[0].startswith("sweep stopped:"), lines[0]
    assert "3 item(s) not attempted" in lines[0], lines[0]
    assert "MISSING" in lines[0], lines[0]
    for uuid in (UUID_B, UUID_C, UUID_D):
        assert uuid not in result.err
    # It waited the full cap, polling at the agreed interval, and no longer.
    assert sum(fake.sleeps) == archive.ROOT_WAIT_CAP_SECONDS
    assert set(fake.sleeps) == {archive.ROOT_WAIT_POLL_SECONDS}
    assert not (warehouse_root(ccw_env) / "locks" / "sweep").exists()
    summaries = [
        r for r in log_records(ccw_env)
        if r.get("status") == "error" and str(r.get("message", "")).startswith("sweep: ")
    ]
    assert len(summaries) == 1 and "stopped" in str(summaries[0]["message"]), summaries
    assert cataloged(ccw_env) == {UUID_A}


def test_root_returns_as_a_bare_mount_point_and_nothing_is_written_into_it(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W-20260929-A108: an unmarked leftover directory at the mount path."""
    share = Share(configure(ccw_env, tmp_path))
    seed(ccw_env, UUID_A, UUID_B, UUID_C)
    fake = FakeTime()
    install(monkeypatch, fake)

    def drop_and_leave_a_directory() -> None:
        share.drop()
        share.root.mkdir()

    capture_then(monkeypatch, UUID_A, drop_and_leave_a_directory)

    result = run_cli(["sweep"])

    assert result.code != 0
    assert result.err.startswith("sweep stopped:"), result.err
    assert "2 item(s) not attempted" in result.err
    assert list(share.root.iterdir()) == []


def test_root_returns_with_a_different_zone_marker_and_is_not_proven(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    share = Share(configure(ccw_env, tmp_path))
    seed(ccw_env, UUID_A, UUID_B, UUID_C)
    fake = FakeTime()
    install(monkeypatch, fake)

    def drop_and_mount_another_zone() -> None:
        share.drop()
        share.root.mkdir()
        archive.init_root(share.root, "Asia/Tokyo")

    capture_then(monkeypatch, UUID_A, drop_and_mount_another_zone)

    result = run_cli(["sweep"])

    assert result.code != 0
    assert result.err.startswith("sweep stopped:"), result.err
    assert "zone mismatch" in result.err
    assert [p.name for p in share.root.iterdir()] == [archive.ROOT_MARKER]


# ---------------------------------------------------------------------------
# What must NOT change
# ---------------------------------------------------------------------------


def test_an_ordinary_item_failure_with_the_root_fine_never_waits(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(ccw_env, tmp_path)
    seed(ccw_env, UUID_A, UUID_B, UUID_C)
    fake = FakeTime()
    install(monkeypatch, fake)
    real = capture_module.capture_transcript

    def wrapped(config: object, path: Path, *, session_id: object, cwd: object) -> object:
        if path.stem == UUID_B:
            raise ValueError("an ordinary bug, nothing to do with the share")
        return real(config, path, session_id=session_id, cwd=cwd)  # type: ignore[arg-type]

    monkeypatch.setattr(capture_module, "capture_transcript", wrapped)

    result = run_cli(["sweep"])

    assert result.code == 1
    assert f"sweep failed: {UUID_B}.jsonl" in result.err
    assert "stopped" not in result.err
    assert fake.sleeps == []
    assert cataloged(ccw_env) == {UUID_A, UUID_C}


def test_no_archive_root_configured_means_no_checks_at_all(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(ccw_env, tmp_path, with_archive=False)
    seed(ccw_env, UUID_A, UUID_B)
    fake = FakeTime()
    install(monkeypatch, fake)
    calls: list[Path] = []
    real_problem = archive.root_problem

    def counted(root: Path, zone: str, *, warehouse_root: Path | None) -> str | None:
        calls.append(root)
        return real_problem(root, zone, warehouse_root=warehouse_root)

    monkeypatch.setattr(archive, "root_problem", counted)

    result = run_cli(["sweep"])

    assert result.code == 0, result.err
    assert cataloged(ccw_env) == {UUID_A, UUID_B}
    assert calls == []
    assert fake.sleeps == []


def test_the_pre_check_runs_per_written_item_and_never_for_unchanged_ones(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """~30k items a night are `skipped_unchanged` and write nothing; they must
    not pay for a check on the share. The first run is the positive control:
    the same counter must see one check per item that does write."""
    configure(ccw_env, tmp_path)
    seed(ccw_env, UUID_A, UUID_B, UUID_C, UUID_D, UUID_E)
    install(monkeypatch, FakeTime())
    items: list[str] = []
    real_ready = archive.RootGuard.ready

    def counted(self: archive.RootGuard, item: str) -> bool:
        items.append(item)
        return real_ready(self, item)

    monkeypatch.setattr(archive.RootGuard, "ready", counted)

    first = run_cli(["sweep"])
    assert first.code == 0, first.err
    first_items = [i for i in items if i.endswith(".jsonl")]
    assert sorted(first_items) == sorted(f"{u}.jsonl" for u in (
        UUID_A, UUID_B, UUID_C, UUID_D, UUID_E
    )), items

    items.clear()
    second = run_cli(["sweep"])
    assert second.code == 0, second.err
    assert [i for i in items if i.endswith(".jsonl")] == [], items


# ---------------------------------------------------------------------------
# The sweep-triggered build has the same exposure
# ---------------------------------------------------------------------------


def test_root_vanishes_during_the_sweep_triggered_build_and_returns(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    share = Share(configure(ccw_env, tmp_path))
    seed(ccw_env, UUID_A, UUID_B, UUID_C)
    fake = FakeTime(on_sleep=lambda n: share.restore() if n == 1 else None)
    install(monkeypatch, fake)
    real_mirror = build_module._mirror  # pyright: ignore[reportPrivateUsage]
    mirrored: list[str] = []

    def wrapped(*args: object, **kwargs: object) -> object:
        out = real_mirror(*args, **kwargs)  # type: ignore[arg-type]
        mirrored.append(str(args[2]))
        if len(mirrored) == 1:
            share.drop()
        return out

    monkeypatch.setattr(build_module, "_mirror", wrapped)

    result = run_cli(["sweep"])

    assert result.code == 0, result.out + result.err
    assert "projection failed" not in result.err
    assert len(mirrored) == 3, mirrored
    assert fake.sleeps == [archive.ROOT_WAIT_POLL_SECONDS]
    logged = pauses(ccw_env)
    assert len(logged) == 1 and "build" in str(logged[0]["message"]), logged
