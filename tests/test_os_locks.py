"""Oracle tests: batch locks are kernel flocks the OS releases when the
holder dies (W-20260929-A84; ruling: Gavin, "OS-released lock").

The old lock was an O_EXCL file holding a PID, trusted through
`os.kill(pid, 0)`. That fails two ways a review proved: a PID reused by an
unrelated process after the holder died reads as a live holder forever, and
any "age" rule meant to fix that can free a lock whose holder is still
running. A flock has neither problem: the kernel drops it when the last
descriptor holding it closes, however the process ended, so nothing is
recorded that could go stale. The PID still written into the file is for a
human reading it; nothing trusts it.

Rulings for the design (conductor, 2026-09-29): a probe (`lock_is_held`)
asks with LOCK_SH|LOCK_NB and never creates a file; an acquirer that races a
probe retries for up to a second; the file exists only while held (release
unlinks it while still holding, and an acquirer re-checks the inode after
winning); the file's mtime is the moment it was acquired; the old PID
mechanism survives only where `fcntl` cannot be imported.
"""

import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from cc_warehouse import store
from conftest import DEAD_PID, lock_held_elsewhere


def _lock(root: Path, name: str = "sweep") -> Path:
    return root / "locks" / name


def test_a_holder_killed_with_sigkill_frees_the_lock(tmp_path: Path) -> None:
    with lock_held_elsewhere(tmp_path, "sweep") as holder:
        assert store.lock_is_held(tmp_path, "sweep") is True
        assert store.acquire_lock(tmp_path, "sweep") is False
        holder.send_signal(signal.SIGKILL)
        holder.wait(timeout=10)
        assert store.lock_is_held(tmp_path, "sweep") is False
        assert store.acquire_lock(tmp_path, "sweep") is True
    store.release_lock(tmp_path, "sweep")


def test_a_reused_pid_in_the_file_is_not_a_holder(tmp_path: Path) -> None:
    """The pid-reuse class: the file names a LIVE process that never took
    the lock (here, a sleeping child standing in for whatever reused the
    PID). Under the PID rule that read as held forever."""
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        lock = _lock(tmp_path)
        lock.parent.mkdir(parents=True)
        lock.write_text(str(sleeper.pid), encoding="ascii")
        assert store.lock_is_held(tmp_path, "sweep") is False
        assert store.acquire_lock(tmp_path, "sweep") is True
        store.release_lock(tmp_path, "sweep")
    finally:
        sleeper.kill()
        sleeper.wait(timeout=10)


def test_old_format_files_with_dead_or_live_pids_read_as_free(tmp_path: Path) -> None:
    """The two stale `capture-*` files in the real locks/ today are this
    shape. They are not deleted by anyone; the new code simply takes them."""
    locks = tmp_path / "locks"
    locks.mkdir()
    (locks / "capture-aaaa").write_text(str(DEAD_PID), encoding="ascii")
    (locks / "capture-bbbb").write_text(str(os.getpid()), encoding="ascii")
    for name in ("capture-aaaa", "capture-bbbb"):
        assert store.lock_is_held(tmp_path, name) is False
        assert store.acquire_lock(tmp_path, name) is True
        store.release_lock(tmp_path, name)


_RACER = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    from cc_warehouse import store
    go = float(sys.argv[3])
    while time.time() < go:
        time.sleep(0.001)
    ok = store.acquire_lock(Path(sys.argv[1]), sys.argv[2])
    print("won" if ok else "lost", flush=True)
    time.sleep(2.5)
    """
)


def test_racing_acquirers_across_processes_have_exactly_one_winner(tmp_path: Path) -> None:
    go = time.time() + 1.5
    racers = [
        subprocess.Popen(
            [sys.executable, "-c", _RACER, str(tmp_path), "sweep", str(go)],
            stdout=subprocess.PIPE,
            text=True,
        )
        for _ in range(8)
    ]
    results = [r.communicate(timeout=30)[0].strip() for r in racers]
    assert sorted(results) == ["lost"] * 7 + ["won"]


def test_a_probe_never_creates_a_file(tmp_path: Path) -> None:
    assert store.lock_is_held(tmp_path, "sweep") is False
    assert not _lock(tmp_path).exists()
    assert not (tmp_path / "locks").exists()


def test_a_probe_sees_a_holder_in_another_process_and_its_clean_exit(tmp_path: Path) -> None:
    with lock_held_elsewhere(tmp_path, "build"):
        assert store.lock_is_held(tmp_path, "build") is True
    assert store.lock_is_held(tmp_path, "build") is False


def test_release_removes_the_file_and_a_second_take_in_process_is_refused(
    tmp_path: Path,
) -> None:
    assert store.acquire_lock(tmp_path, "sweep") is True
    assert _lock(tmp_path).exists()
    assert store.acquire_lock(tmp_path, "sweep") is False
    store.release_lock(tmp_path, "sweep")
    assert not _lock(tmp_path).exists()
    assert store.acquire_lock(tmp_path, "sweep") is True
    store.release_lock(tmp_path, "sweep")


def test_releasing_a_lock_this_process_does_not_hold_leaves_it(tmp_path: Path) -> None:
    with lock_held_elsewhere(tmp_path, "sweep"):
        store.release_lock(tmp_path, "sweep")
        assert _lock(tmp_path).exists()
        assert store.lock_is_held(tmp_path, "sweep") is True


def test_an_acquirer_that_wins_an_unlinked_inode_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one race unlink-on-release opens: B opened the file, A released
    (unlinking it), and B's flock then succeeds on an inode no path names.
    B must notice and take the lock on the real path instead."""
    locks = tmp_path / "locks"
    locks.mkdir()
    stale_path = locks / "sweep"
    stale_path.write_text("", encoding="ascii")
    stale_fd = os.open(stale_path, os.O_RDWR)
    stale_path.unlink()
    real_open = store._open_lock_file  # pyright: ignore[reportPrivateUsage]
    calls = {"n": 0}

    def first_open_is_stale(path: Path) -> int:
        calls["n"] += 1
        return stale_fd if calls["n"] == 1 else real_open(path)

    monkeypatch.setattr(store, "_open_lock_file", first_open_is_stale)
    assert store.acquire_lock(tmp_path, "sweep") is True
    assert calls["n"] >= 2
    assert _lock(tmp_path).exists()
    # The lock this process holds is the one on the path: another process
    # asking sees it held.
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; from pathlib import Path; from cc_warehouse import store; "
         "print(store.lock_is_held(Path(sys.argv[1]), 'sweep'))", str(tmp_path)],
        capture_output=True, text=True, timeout=30,
    )
    assert probe.stdout.strip() == "True"
    store.release_lock(tmp_path, "sweep")


def test_the_lock_files_mtime_is_the_moment_it_was_acquired(tmp_path: Path) -> None:
    """fix-doctor-quick's rule "a file written after the lock was taken" reads
    this. An old file left behind must not lend its old mtime to a new lock."""
    lock = _lock(tmp_path)
    lock.parent.mkdir(parents=True)
    lock.write_text(str(DEAD_PID), encoding="ascii")
    os.utime(lock, (1_000_000_000, 1_000_000_000))
    before = time.time()
    assert store.acquire_lock(tmp_path, "sweep") is True
    after = time.time()
    taken = store.lock_acquired_at(tmp_path, "sweep")
    assert taken is not None
    assert before - 1 <= taken <= after + 1
    assert lock.stat().st_mtime == taken
    store.release_lock(tmp_path, "sweep")
    assert store.lock_acquired_at(tmp_path, "sweep") is None


def test_lock_acquired_at_is_none_for_a_file_nobody_holds(tmp_path: Path) -> None:
    lock = _lock(tmp_path)
    lock.parent.mkdir(parents=True)
    lock.write_text(str(os.getpid()), encoding="ascii")
    assert store.lock_acquired_at(tmp_path, "sweep") is None


def test_an_acquirer_waits_out_a_momentary_probe(tmp_path: Path) -> None:
    """A probe holds LOCK_SH for an instant; an acquirer that lands in that
    instant must retry (up to a second) instead of reporting "busy"."""
    import fcntl

    lock = _lock(tmp_path)
    lock.parent.mkdir(parents=True)
    lock.write_text("", encoding="ascii")
    fd = os.open(lock, os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_SH)

    def let_go() -> None:
        time.sleep(0.3)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    releaser = threading.Thread(target=let_go)
    releaser.start()
    try:
        assert store.acquire_lock(tmp_path, "sweep") is True
    finally:
        releaser.join()
    store.release_lock(tmp_path, "sweep")


def test_a_real_holder_is_refused_within_about_a_second(tmp_path: Path) -> None:
    with lock_held_elsewhere(tmp_path, "sweep"):
        start = time.monotonic()
        assert store.acquire_lock(tmp_path, "sweep") is False
        assert time.monotonic() - start < 3


def test_without_fcntl_the_labelled_pid_fallback_still_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store, "fcntl", None)
    assert store.acquire_lock(tmp_path, "sweep") is True
    assert _lock(tmp_path).read_text(encoding="ascii").strip() == str(os.getpid())
    assert store.lock_is_held(tmp_path, "sweep") is True
    assert store.acquire_lock(tmp_path, "sweep") is False
    store.release_lock(tmp_path, "sweep")
    assert not _lock(tmp_path).exists()


def test_the_pid_fallback_is_labelled_in_the_source() -> None:
    source = Path(store.__file__).read_text(encoding="utf-8")
    assert "PID FALLBACK" in source


# ---------------------------------------------------------------------------
# `ccw doctor` names the locks held right now (ruling 2026-09-29), so the
# deploy step "reinstall ccw when no batch is running" can be checked by eye:
# an old ccw (PID files) and a new one (flocks) do not see each other's locks.
# ---------------------------------------------------------------------------


def _locks_line(out: str) -> str:
    lines = [ln for ln in out.splitlines() if ln.split()[1:2] == ["locks"]]
    assert len(lines) == 1, out
    return lines[0]


def test_doctor_names_a_lock_held_by_another_process(ccw_env: dict[str, str]) -> None:
    from conftest import run_ccw, warehouse_root

    root = warehouse_root(ccw_env)
    with lock_held_elsewhere(root, "sweep"):
        line = _locks_line(run_ccw(["doctor"], ccw_env).out)
    assert "sweep" in line
    assert "FAIL" not in line


def test_doctor_says_none_and_ignores_unheld_pid_files(ccw_env: dict[str, str]) -> None:
    from conftest import run_ccw, warehouse_root

    locks = warehouse_root(ccw_env) / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    (locks / "capture-cccc").write_text(str(os.getpid()), encoding="ascii")
    line = _locks_line(run_ccw(["doctor"], ccw_env).out)
    assert "none held" in line
    assert "capture-cccc" not in line


def test_the_mtime_is_stamped_even_when_the_pid_text_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The human-readable text is best effort (a full disk can refuse it);
    the acquire-time mtime is not, because another check reads it."""
    lock = _lock(tmp_path)
    lock.parent.mkdir(parents=True)
    lock.write_text(str(DEAD_PID), encoding="ascii")
    os.utime(lock, (1_000_000_000, 1_000_000_000))

    def refuse_write(_fd: int, _data: bytes) -> int:
        raise OSError(28, "No space left on device")

    def refuse_truncate(_fd: int, _length: int) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(store.os, "write", refuse_write)  # pyright: ignore[reportPrivateImportUsage]
    monkeypatch.setattr(store.os, "ftruncate", refuse_truncate)  # pyright: ignore[reportPrivateImportUsage]
    before = time.time()
    assert store.acquire_lock(tmp_path, "sweep") is True
    monkeypatch.undo()
    assert lock.stat().st_mtime >= before - 1
    store.release_lock(tmp_path, "sweep")
