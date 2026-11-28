"""Oracle tests: ccw's sweep side for an archive on a share that is mounted
only while the sweep runs (Network_Plan close.md items 5, 6 and 8, 28 Nov 2026).

THREE PROPERTIES, one section each.

A. THE ITEM IN FLIGHT. `RootGuard` checks the root marker before every writing
   item, so a share that drops BETWEEN items is caught. What it cannot see is
   the drop DURING an item: every archive writer used `mkdir(parents=True)`, so
   a root that vanished after the check was created again on the local disk,
   and a bare mount point left behind was written into. `archive.make_folder`
   checks the marker at the moment a folder is made and never creates the root.

B. A REFUSED HOOK CAPTURE IS OWED TO THE ARCHIVE. Between sweeps a box's mount
   point is empty, so every SessionEnd capture is refused by the archive and
   kept in the vault. The next sweep finds that session's hash already stored
   and skips it, and the build ran only when the sweep stored something, so the
   refused session never reached the archive (finding by cc-warehouse-main,
   checked at 466d2ee). The hook now records that a build is owed; the sweep
   builds when one is.

C. THE HEARTBEAT. After a sweep that did not lose its root, a small JSON file
   says which machine swept, when, and whether the share was written: on the
   share (`_heartbeat.json`) and locally (`heartbeat.json`, the copy `ccw
   doctor` reads). The keys are a contract with the doctor job, fixed in plan
   2026-11-28-ccw-share-sweep-side.md, plus `share_written_at`.

Every sweep runs in a sandbox (HOME, CCW_ROOT under tmp_path); no test sleeps
in real time (the root wait's sleep and clock are swapped).
"""

import json
import socket
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import cc_warehouse
import cc_warehouse.build as build_module
from cc_warehouse import archive, capture
from cc_warehouse.config import Config
from conftest import (
    basic_session,
    lock_held_elsewhere,
    mark_archive,
    run_cli,
    subagent_session,
    warehouse_root,
    write_transcript,
)

ZONE = "UTC"
UUID_A = "a8311111-1111-4111-8111-111111111111"
UUID_B = "b8322222-2222-4222-8222-222222222222"
UUID_C = "c8333333-3333-4333-8333-333333333333"
CWD_A = "/home/alice/projects/widget"
CWD_B = "/home/alice/projects/gadget"
HEARTBEAT_KEYS = {
    "machine", "at", "ccw_version", "items", "stored", "failed", "archive_root", "share",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeTime:
    """A clock that only moves when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def no_real_waits(monkeypatch: pytest.MonkeyPatch) -> FakeTime:
    fake = FakeTime()
    monkeypatch.setattr(archive, "root_wait_sleep", fake.sleep)
    monkeypatch.setattr(archive, "root_wait_clock", fake.clock)
    return fake


def configure(
    env: dict[str, str], tmp_path: Path, *, keep_objects: bool = False, mark: bool = True
) -> Path:
    archive_root = tmp_path / "share" / "cc-warehouse-archive"
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [
        f'root = "{warehouse_root(env)}"',
        f'archive_timezone = "{ZONE}"',
        f'archive_root = "{archive_root}"',
        f"keep_objects = {'true' if keep_objects else 'false'}",
    ]
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if mark:
        mark_archive(archive_root, ZONE)
    else:
        archive_root.mkdir(parents=True, exist_ok=True)
    return archive_root


def seed(env: dict[str, str], uuid: str, cwd: str = CWD_A) -> Path:
    encoded = cwd.replace("/", "-")
    return write_transcript(
        env, basic_session(cwd=cwd, session_id=uuid), session_id=uuid, encoded_dir=encoded
    )


def folders_named(archive_root: Path, uuid: str) -> list[Path]:
    if not archive_root.is_dir():
        return []
    return [p for p in archive.walk_folders(archive_root) if p.name.endswith(uuid)]


def label_dirs(archive_root: Path) -> set[str]:
    return {p.name for p in archive_root.iterdir() if p.is_dir()}


def hide_marker(archive_root: Path) -> Callable[[], None]:
    marker = archive_root / archive.ROOT_MARKER
    aside = archive_root.parent / "marker-aside.json"

    def drop() -> None:
        marker.rename(aside)

    return drop


def restore_marker(archive_root: Path) -> None:
    (archive_root.parent / "marker-aside.json").rename(archive_root / archive.ROOT_MARKER)


def when_folder_is_named(
    monkeypatch: pytest.MonkeyPatch, uuid: str, action: Callable[[], None]
) -> None:
    """Run `action` once, at the moment a writer has passed every earlier check
    and computes the folder for `uuid`: the window an in-flight drop hits."""
    real = build_module.archive_dir
    fired: list[bool] = []

    def wrapped(*args: object, **kwargs: object) -> Path:
        result: Path = real(*args, **kwargs)  # type: ignore[arg-type]
        if result.name.endswith(uuid) and not fired:
            fired.append(True)
            action()
        return result

    monkeypatch.setattr(build_module, "archive_dir", wrapped)


def local_heartbeat(env: dict[str, str]) -> dict[str, object]:
    return json.loads((warehouse_root(env) / "heartbeat.json").read_text(encoding="utf-8"))


def count_builds(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    real = build_module.build
    calls: list[int] = []

    def wrapped(*args: object, **kwargs: object) -> object:
        calls.append(1)
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(build_module, "build", wrapped)
    return calls


# ---------------------------------------------------------------------------
# A. The marker is checked when each project folder is made
# ---------------------------------------------------------------------------


def proven(root: Path) -> Path:
    """A root this process has proven, as every writing entry point does."""
    mark_archive(root, ZONE)
    return archive.require_root(root, ZONE, warehouse_root=None)


def test_make_folder_refuses_a_bare_mount_point_and_creates_nothing(tmp_path: Path) -> None:
    """The share dropped after the root was proven and left a bare mount point:
    an empty folder with no marker (a box between sweeps)."""
    mount = proven(tmp_path / "mnt" / "archive")
    (mount / archive.ROOT_MARKER).rename(tmp_path / "aside.json")
    with pytest.raises(archive.RootGone):
        archive.make_folder(mount, mount / "widget" / "20260105-100000+0000_x")
    assert list(mount.iterdir()) == []


def test_make_folder_never_creates_the_root_itself(tmp_path: Path) -> None:
    gone = proven(tmp_path / "mnt" / "archive")
    gone.rename(tmp_path / "unmounted")
    with pytest.raises(OSError):
        archive.make_folder(gone, gone / "widget" / "f")
    assert not gone.exists()


def test_make_folder_makes_every_level_below_a_marked_root(tmp_path: Path) -> None:
    root = proven(tmp_path / "archive")
    target = root / "widget" / "f" / "subagents" / "g"
    archive.make_folder(root, target)
    assert target.is_dir()
    archive.make_folder(root, target)  # idempotent
    assert target.is_dir()


def test_make_folder_refuses_a_folder_outside_the_root(tmp_path: Path) -> None:
    root = mark_archive(tmp_path / "archive", ZONE)
    with pytest.raises(ValueError):
        archive.make_folder(root, tmp_path / "elsewhere" / "f")
    assert not (tmp_path / "elsewhere").exists()


def test_make_below_never_recreates_a_vanished_session_folder(tmp_path: Path) -> None:
    """Sidecars and sub-agents go INTO an existing session folder; a folder
    that vanished with its share is never made again from below."""
    session = tmp_path / "archive" / "widget" / "f"
    with pytest.raises(FileNotFoundError):
        archive.make_below(session, session / "tool-results" / "x")
    assert not (tmp_path / "archive").exists()


def test_write_subagent_refuses_a_root_without_its_marker(tmp_path: Path) -> None:
    """The orphan branch of write_subagent makes a folder under the root."""
    root = proven(tmp_path / "archive")
    (root / archive.ROOT_MARKER).rename(tmp_path / "aside.json")
    with pytest.raises(archive.RootGone):
        archive.write_subagent(root, "widget", subagent_session(parent_uuid=UUID_A), ZONE)
    assert list(root.iterdir()) == []


def test_marker_removed_between_two_project_folders_stops_before_the_second(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = configure(ccw_env, tmp_path)
    seed(ccw_env, UUID_A, CWD_A)
    seed(ccw_env, UUID_B, CWD_B)
    no_real_waits(monkeypatch)
    # The share drops right after the first project's folder is written.
    real = archive.write_source
    done: list[str] = []

    def wrapped(*args: object, **kwargs: object) -> Path:
        result: Path = real(*args, **kwargs)  # type: ignore[arg-type]
        if not done:
            done.append(result.parent.parent.name)
            hide_marker(root)()
        return result

    monkeypatch.setattr(archive, "write_source", wrapped)

    result = run_cli(["sweep"])

    assert result.code != 0, result.out + result.err
    assert "sweep stopped:" in result.err, result.err
    assert label_dirs(root) == set(done), (label_dirs(root), done)


def test_marker_removed_while_an_item_is_in_flight_creates_no_folder(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The drop lands after RootGuard's check and before the folder is made."""
    root = configure(ccw_env, tmp_path)
    seed(ccw_env, UUID_A, CWD_B)
    no_real_waits(monkeypatch)
    when_folder_is_named(monkeypatch, UUID_A, hide_marker(root))

    result = run_cli(["sweep"])

    assert result.code != 0, result.out + result.err
    assert "sweep stopped:" in result.err, result.err
    assert folders_named(root, UUID_A) == []
    assert label_dirs(root) == set(), label_dirs(root)


def test_root_vanishing_while_an_item_is_in_flight_is_never_recreated(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unmounted share on a Mac: the path is simply gone. `mkdir(parents=True)`
    used to bring it back as a plain local folder holding one session."""
    root = configure(ccw_env, tmp_path)
    aside = root.with_name(root.name + "-while-unmounted")
    seed(ccw_env, UUID_A)
    no_real_waits(monkeypatch)

    def unmount() -> None:
        root.rename(aside)

    when_folder_is_named(monkeypatch, UUID_A, unmount)

    result = run_cli(["sweep"])

    assert result.code != 0, result.out + result.err
    assert not root.exists()


# ---------------------------------------------------------------------------
# B. A hook capture the archive refused is built by the next sweep
# ---------------------------------------------------------------------------


def _hook_capture_refused(env: dict[str, str], tmp_path: Path) -> Path:
    """The SessionEnd capture on a box between sweeps: an empty mount point,
    the vault on. Run through the library, not the hook verb, so no detached
    render child can write the folder later and pass the test for it."""
    root = configure(env, tmp_path, keep_objects=True, mark=False)
    transcript = seed(env, UUID_A)
    config = Config(
        root=warehouse_root(env), archive_root=root, archive_timezone=ZONE, keep_objects=True
    )
    result = capture.capture_transcript(config, transcript, session_id=UUID_A, cwd=CWD_A)
    assert result.action == "stored"
    assert list(root.iterdir()) == []
    return root


def test_a_refused_hook_capture_reaches_the_archive_at_the_next_sweep(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    root = _hook_capture_refused(ccw_env, tmp_path)
    assert (warehouse_root(ccw_env) / archive.OWED_FILE).is_file()
    mark_archive(root, ZONE)  # the sweep's mount is up

    result = run_cli(["sweep"])

    assert result.code == 0, result.out + result.err
    assert "0 stored" in result.out, result.out
    [folder] = folders_named(root, UUID_A)
    assert (folder / f"{UUID_A}.jsonl").is_file()
    assert (folder / "manifest.json").is_file()


def test_a_refused_parent_gets_its_sub_agents_not_the_orphan_folder(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Red-team R7: the sub-agent pass runs before the build, so a parent the
    archive refused had no folder and its sub-agents went to
    `_orphaned-subagents/` for good. The session pass now files it first."""
    root = configure(ccw_env, tmp_path, keep_objects=True, mark=False)
    transcript = seed(ccw_env, UUID_A)
    agents = transcript.parent / UUID_A / "subagents"
    agents.mkdir(parents=True)
    (agents / "agent-a94d30c1d877f964d.jsonl").write_bytes(subagent_session(parent_uuid=UUID_A))
    config = Config(
        root=warehouse_root(ccw_env), archive_root=root, archive_timezone=ZONE, keep_objects=True
    )
    assert capture.capture_transcript(
        config, transcript, session_id=UUID_A, cwd=CWD_A
    ).action == "stored"
    assert list(root.iterdir()) == []
    mark_archive(root, ZONE)

    result = run_cli(["sweep"])

    assert result.code == 0, result.out + result.err
    assert not (root / archive.ORPHAN_LABEL).exists(), sorted(p.name for p in root.iterdir())
    [folder] = folders_named(root, UUID_A)
    assert any((folder / archive.SUBAGENTS_DIR).iterdir())
    assert (folder / "manifest.json").is_file()


def test_after_the_owed_build_the_next_quiet_sweep_does_not_build(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The build's check of every folder is most of a night's cost on the
    share (W-20261015-A01): owed once means built once."""
    root = _hook_capture_refused(ccw_env, tmp_path)
    mark_archive(root, ZONE)
    builds = count_builds(monkeypatch)
    assert run_cli(["sweep"]).code == 0
    assert builds == [1]
    assert run_cli(["sweep"]).code == 0
    assert builds == [1]


def test_a_sweep_with_nothing_stored_and_nothing_owed_does_not_build(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(ccw_env, tmp_path)
    seed(ccw_env, UUID_A)
    assert run_cli(["sweep"]).code == 0
    builds = count_builds(monkeypatch)
    assert run_cli(["sweep"]).code == 0
    assert builds == []


def test_a_refusal_after_the_last_build_is_owed_again(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(ccw_env, tmp_path)
    seed(ccw_env, UUID_A)
    assert run_cli(["sweep"]).code == 0
    archive.mark_owed(warehouse_root(ccw_env), datetime.now(UTC) + timedelta(seconds=1))
    builds = count_builds(monkeypatch)
    assert run_cli(["sweep"]).code == 0
    assert builds == [1]


def test_owed_keeps_the_newest_time_when_writers_race(tmp_path: Path) -> None:
    """Several hook captures can record at once; an older one landing last
    must never move `last` backwards (cc-warehouse-main's note, 7:49 PM)."""
    root = tmp_path / "warehouse"
    newer = datetime(2026, 11, 28, 9, 0, tzinfo=UTC)
    archive.mark_owed(root, newer)
    archive.mark_owed(root, newer - timedelta(minutes=5))
    recorded = json.loads((root / archive.OWED_FILE).read_text(encoding="utf-8"))
    assert recorded["last"] == newer.isoformat()


def test_an_unreadable_owed_record_builds_rather_than_skips(tmp_path: Path) -> None:
    root = tmp_path / "warehouse"
    root.mkdir()
    (root / archive.OWED_FILE).write_text("{not json", encoding="utf-8")
    assert archive.archive_owed(root) is True


def test_no_build_record_means_a_build_is_owed(tmp_path: Path) -> None:
    """Red-team R1: a catalog filled before the record existed."""
    assert archive.archive_owed(tmp_path) is True


def test_a_build_record_and_no_refusal_means_nothing_owed(tmp_path: Path) -> None:
    archive.mark_built(tmp_path, datetime.now(UTC))
    assert archive.archive_owed(tmp_path) is False


def test_a_catalog_filled_with_no_archive_is_filed_by_the_first_sweep(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Red-team R1, day one on codebox: its sessions were stored by a ccw
    with no archive_root, so no refusal was ever recorded. The first sweep
    with an archive stores 0 and still files them."""
    transcript = seed(ccw_env, UUID_A)
    config = Config(root=warehouse_root(ccw_env), archive_root=None, keep_objects=True)
    assert capture.capture_transcript(
        config, transcript, session_id=UUID_A, cwd=CWD_A
    ).action == "stored"
    root = configure(ccw_env, tmp_path, keep_objects=True)
    assert not (warehouse_root(ccw_env) / archive.BUILT_FILE).exists()

    result = run_cli(["sweep"])

    assert result.code == 0, result.out + result.err
    assert "0 stored" in result.out, result.out
    [folder] = folders_named(root, UUID_A)
    assert (folder / "manifest.json").is_file()
    assert local_heartbeat(ccw_env)["unfiled"] == 0


def test_a_failed_head_is_counted_unfiled_and_does_not_keep_the_night_owed(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A heartbeat never reads as a good sweep over sessions the archive
    lacks (red-team R1), and one head that always fails does not make every
    night an owed night with a share stat per session (review finding 5)."""
    root = configure(ccw_env, tmp_path)
    seed(ccw_env, UUID_A)
    real = build_module._mirror  # pyright: ignore[reportPrivateUsage]

    def broken(*args: object, **kwargs: object) -> str | None:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(build_module, "_mirror", broken)
    run_cli(["sweep"])
    assert local_heartbeat(ccw_env)["unfiled"] == 1
    assert (warehouse_root(ccw_env) / archive.BUILT_FILE).is_file()

    builds = count_builds(monkeypatch)
    run_cli(["sweep"])
    assert builds == []
    assert local_heartbeat(ccw_env)["unfiled"] == 1  # carried, not reset

    # The next build that runs files it and the count clears.
    monkeypatch.setattr(build_module, "_mirror", real)
    seed(ccw_env, UUID_B)
    assert run_cli(["sweep"]).code == 0
    assert local_heartbeat(ccw_env)["unfiled"] == 0
    assert folders_named(root, UUID_A)


def test_unfiled_is_carried_when_the_sweep_runs_no_build(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(ccw_env, tmp_path)
    seed(ccw_env, UUID_A)
    assert run_cli(["sweep"]).code == 0
    builds = count_builds(monkeypatch)
    assert run_cli(["sweep"]).code == 0
    assert builds == []
    assert local_heartbeat(ccw_env)["unfiled"] == 0


# ---------------------------------------------------------------------------
# C. The heartbeat
# ---------------------------------------------------------------------------


def test_a_good_sweep_writes_both_heartbeats_with_the_contract_keys(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    root = configure(ccw_env, tmp_path)
    seed(ccw_env, UUID_A)
    assert run_cli(["sweep"]).code == 0

    local = local_heartbeat(ccw_env)
    remote = json.loads((root / archive.HEARTBEAT_REMOTE).read_text(encoding="utf-8"))
    assert set(local) == HEARTBEAT_KEYS | {"share_written_at", "unfiled"}, local
    assert local["unfiled"] == 0
    assert local == remote
    assert local["machine"] == socket.gethostname()
    assert local["ccw_version"] == cc_warehouse.__version__
    assert local["share"] == "written"
    assert local["stored"] == 1 and local["failed"] == 0
    assert isinstance(local["items"], int) and local["items"] >= 1
    assert local["archive_root"] == str(root)
    at = datetime.fromisoformat(str(local["at"]))
    assert at.utcoffset() == timedelta(0)
    assert local["share_written_at"] == local["at"]


def test_a_sweep_that_lost_its_root_writes_no_heartbeat(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = configure(ccw_env, tmp_path)
    seed(ccw_env, UUID_A)
    no_real_waits(monkeypatch)
    when_folder_is_named(monkeypatch, UUID_A, hide_marker(root))
    assert run_cli(["sweep"]).code != 0
    assert not (warehouse_root(ccw_env) / "heartbeat.json").exists()
    assert not (root / archive.HEARTBEAT_REMOTE).exists()


def test_a_refused_sweep_writes_no_heartbeat(ccw_env: dict[str, str], tmp_path: Path) -> None:
    configure(ccw_env, tmp_path, mark=False)
    seed(ccw_env, UUID_A)
    assert run_cli(["sweep"]).code != 0
    assert not (warehouse_root(ccw_env) / "heartbeat.json").exists()


def _drop_marker_after_build(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """The share goes away after the sweep's build, before its heartbeat."""
    real = build_module.build

    def wrapped(*args: object, **kwargs: object) -> object:
        report = real(*args, **kwargs)  # type: ignore[arg-type]
        hide_marker(root)()
        return report

    monkeypatch.setattr(build_module, "build", wrapped)


def test_share_unproven_at_the_end_writes_only_the_local_heartbeat(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = configure(ccw_env, tmp_path)
    seed(ccw_env, UUID_A)
    _drop_marker_after_build(monkeypatch, root)
    run_cli(["sweep"])
    local = local_heartbeat(ccw_env)
    assert local["share"] == "unreachable"
    assert "share_written_at" not in local  # never written before
    assert not (root / archive.HEARTBEAT_REMOTE).exists()


def test_share_written_at_is_carried_forward_from_the_last_written_sweep(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = configure(ccw_env, tmp_path)
    seed(ccw_env, UUID_A)
    assert run_cli(["sweep"]).code == 0
    first = local_heartbeat(ccw_env)
    assert first["share"] == "written"

    seed(ccw_env, UUID_B)
    _drop_marker_after_build(monkeypatch, root)
    run_cli(["sweep"])
    second = local_heartbeat(ccw_env)
    assert second["share"] == "unreachable"
    assert second["at"] != first["at"]
    assert second["share_written_at"] == first["at"]


def test_a_failed_remote_write_never_fails_the_sweep(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    root = configure(ccw_env, tmp_path)
    seed(ccw_env, UUID_A)
    (root / archive.HEARTBEAT_REMOTE).mkdir()  # a replace onto a folder fails

    result = run_cli(["sweep"])

    assert result.code == 0, result.out + result.err
    assert local_heartbeat(ccw_env)["share"] == "unreachable"
    log = (warehouse_root(ccw_env) / "logs" / "capture.jsonl").read_text(encoding="utf-8")
    assert archive.HEARTBEAT_REMOTE in log


def test_no_archive_root_means_no_heartbeat(ccw_env: dict[str, str]) -> None:
    write_transcript(ccw_env, basic_session(session_id=UUID_C), session_id=UUID_C)
    assert run_cli(["sweep"]).code == 0
    assert not (warehouse_root(ccw_env) / "heartbeat.json").exists()


def test_the_remote_heartbeat_is_invisible_to_the_archive_walkers(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A FILE at the root is never a label: verify and reindex see 0 problems,
    so neither name needs a RESERVED_LABELS entry."""
    root = configure(ccw_env, tmp_path)
    seed(ccw_env, UUID_A)
    assert run_cli(["sweep"]).code == 0
    (root / "_catalog-backup.sqlite").write_bytes(b"SQLite format 3\x00")
    assert (root / archive.HEARTBEAT_REMOTE).is_file()
    walked = [p.name for p in archive.walk_folders(root)]
    assert walked == [f.name for f in folders_named(root, UUID_A)]
    verify = run_cli(["archive", "--to", str(root), "--verify"])
    assert verify.code == 0, verify.out + verify.err
    assert "0 problems" in verify.out, verify.out


# ---------------------------------------------------------------------------
# Review findings (independent review, 28 Nov 2026)
# ---------------------------------------------------------------------------


def test_a_root_checked_by_root_problem_alone_is_never_recreated(tmp_path: Path) -> None:
    """Finding 2: the detached companions child checks its root with
    `root_problem`, not `require_root`. That check alone must arm the
    per-folder check, or a sub-agent written after the share drops makes the
    root again on the local disk."""
    root = mark_archive(tmp_path / "share" / "archive", ZONE)
    assert archive.root_problem(root, ZONE, warehouse_root=None) is None
    root.rename(tmp_path / "share" / "unmounted")
    with pytest.raises(OSError):
        archive.write_subagent(root, "widget", subagent_session(parent_uuid=UUID_A), ZONE)
    assert not root.exists()


def test_a_build_that_found_its_lock_held_is_not_recorded_as_built(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Finding 3: a held build lock builds nothing, so the owed record stays
    and the heartbeat claims no unfiled count it never measured."""
    _hook_capture_refused(ccw_env, tmp_path)
    root = tmp_path / "share" / "cc-warehouse-archive"
    mark_archive(root, ZONE)
    with lock_held_elsewhere(warehouse_root(ccw_env), "build"):
        run_cli(["sweep"])
    assert not (warehouse_root(ccw_env) / archive.BUILT_FILE).exists()
    assert "unfiled" not in local_heartbeat(ccw_env)
    assert archive.archive_owed(warehouse_root(ccw_env)) is True


def test_the_owed_record_is_written_after_the_catalog_row(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 4: a build that reads its heads after the owed record must see
    the session, so the record comes after `catalog.add_session`."""
    from cc_warehouse import catalog

    order: list[str] = []
    real_add = catalog.add_session
    real_mark = archive.mark_owed

    def add(*args: object, **kwargs: object) -> object:
        order.append("row")
        return real_add(*args, **kwargs)  # type: ignore[arg-type]

    def mark(*args: object, **kwargs: object) -> None:
        order.append("owed")
        real_mark(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(catalog, "add_session", add)
    monkeypatch.setattr(archive, "mark_owed", mark)
    _hook_capture_refused(ccw_env, tmp_path)
    assert order == ["row", "owed"], order


_RACER = """
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from cc_warehouse import archive
sys.stdin.readline()
base = datetime(2026, 11, 28, 9, 0, tzinfo=UTC)
archive.mark_owed(Path(sys.argv[1]), base + timedelta(seconds=int(sys.argv[2])))
"""


def test_concurrent_owed_writers_never_move_last_backwards(tmp_path: Path) -> None:
    """Finding 6: hook processes racing on the record keep the newest time."""
    import subprocess
    import sys

    root = tmp_path / "warehouse"
    root.mkdir()
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _RACER, str(root), str(i)],
            stdin=subprocess.PIPE,
            text=True,
        )
        for i in range(8)
    ]
    for proc in procs:  # release them together
        assert proc.stdin is not None
        proc.stdin.write("go\n")
        proc.stdin.close()
    for proc in procs:
        assert proc.wait(timeout=30) == 0
    recorded = json.loads((root / archive.OWED_FILE).read_text(encoding="utf-8"))
    newest = datetime(2026, 11, 28, 9, 0, tzinfo=UTC) + timedelta(seconds=7)
    assert recorded["last"] == newest.isoformat()


def test_a_filed_owed_session_is_one_item_in_the_summary(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Review nit: filing replaces the path's skipped outcome; no double count."""
    _hook_capture_refused(ccw_env, tmp_path)
    mark_archive(tmp_path / "share" / "cc-warehouse-archive", ZONE)
    assert run_cli(["sweep"]).code == 0
    assert local_heartbeat(ccw_env)["items"] == 1
