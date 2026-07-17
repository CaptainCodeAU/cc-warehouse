"""Oracle tests: object store primitives (slice 1, the trial run).

Contract: DESIGN sections 1-2, 13; rules R1, R2, R14; FINDINGS F1, F2, F3.
"""

import hashlib
import os
from pathlib import Path
from typing import cast

import pytest

from cc_warehouse import store

DATA = b'{"type": "user", "line": 1}\n'
# Same length, different bytes: the F1 pair.
SAME_SIZE_A = b'{"payload": "AAAA"}\n'
SAME_SIZE_B = b'{"payload": "BBBB"}\n'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_sha256_hex_matches_hashlib() -> None:
    assert store.sha256_hex(DATA) == sha(DATA)


def test_atomic_write_creates_file_with_exact_bytes(tmp_path: Path) -> None:
    target = tmp_path / "out.bin"
    store.atomic_write(target, DATA)
    assert target.read_bytes() == DATA


def test_atomic_write_tmp_in_same_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2: the tmp file must live in the target's directory so os.replace is
    a same-filesystem atomic rename."""
    calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def recording_replace(src: str | Path, dst: str | Path) -> None:
        calls.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", recording_replace)
    target = tmp_path / "sub" / "out.bin"
    target.parent.mkdir()
    store.atomic_write(target, DATA)
    assert len(calls) == 1
    src, dst = calls[0]
    assert Path(dst) == target
    assert Path(src).parent == target.parent
    # No tmp litter left behind.
    assert list(target.parent.iterdir()) == [target]


def test_interrupted_write_leaves_no_partial_final_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2: kill the writer mid-write (simulated: os.replace never happens) and
    the final path never shows a partial file; a re-run completes cleanly."""

    def failing_replace(src: str | Path, dst: str | Path) -> None:
        raise OSError("simulated crash before rename")

    target = tmp_path / "out.bin"
    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError):
        store.atomic_write(target, DATA)
    assert not target.exists()

    monkeypatch.undo()
    store.atomic_write(target, DATA)
    assert target.read_bytes() == DATA


def test_interrupted_overwrite_keeps_old_content_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2: a failed overwrite must leave the previous complete file untouched."""
    target = tmp_path / "out.bin"
    store.atomic_write(target, DATA)

    def failing_replace(src: str | Path, dst: str | Path) -> None:
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError):
        store.atomic_write(target, b"partial new content")
    assert target.read_bytes() == DATA


def test_put_stores_at_sharded_path(tmp_path: Path) -> None:
    """DESIGN section 1: objects/<hh>/<sha256>.jsonl named by the payload's own hash."""
    result = store.put(tmp_path, DATA)
    digest = sha(DATA)
    assert result.sha256 == digest
    assert result.created is True
    expected = tmp_path / "objects" / digest[:2] / f"{digest}.jsonl"
    assert result.path == expected
    assert expected.read_bytes() == DATA
    assert store.object_path(tmp_path, digest) == expected


def test_put_same_size_different_content_stores_two_objects(tmp_path: Path) -> None:
    """F1: two same-size, different-content payloads are two distinct sessions,
    never deduped by any size shortcut."""
    assert len(SAME_SIZE_A) == len(SAME_SIZE_B)
    ra = store.put(tmp_path, SAME_SIZE_A)
    rb = store.put(tmp_path, SAME_SIZE_B)
    assert ra.sha256 != rb.sha256
    assert ra.created and rb.created
    assert store.get(tmp_path, ra.sha256) == SAME_SIZE_A
    assert store.get(tmp_path, rb.sha256) == SAME_SIZE_B


def test_put_existing_hash_is_noop(tmp_path: Path) -> None:
    """F3/R14: storing an object whose hash already exists is a no-op."""
    first = store.put(tmp_path, DATA)
    second = store.put(tmp_path, DATA)
    assert second.sha256 == first.sha256
    assert first.created is True
    assert second.created is False
    assert first.path.read_bytes() == DATA


def test_has_and_get_roundtrip(tmp_path: Path) -> None:
    digest = store.put(tmp_path, DATA).sha256
    assert store.has(tmp_path, digest) is True
    assert store.has(tmp_path, "0" * 64) is False
    assert store.get(tmp_path, digest) == DATA
    with pytest.raises(FileNotFoundError):
        store.get(tmp_path, "0" * 64)


def test_verify_walk_all_ok(tmp_path: Path) -> None:
    store.put(tmp_path, SAME_SIZE_A)
    store.put(tmp_path, SAME_SIZE_B)
    results = list(store.verify_walk(tmp_path))
    assert len(results) == 2
    assert all(r.ok for r in results)
    assert {r.expected_sha256 for r in results} == {sha(SAME_SIZE_A), sha(SAME_SIZE_B)}


def test_verify_walk_reports_corruption(tmp_path: Path) -> None:
    """The re-hash walk detects an object whose bytes no longer match its name.
    (The test corrupts the file directly; nothing in cc-warehouse may.)"""
    result = store.put(tmp_path, DATA)
    result.path.write_bytes(b"corrupted bytes")
    bad = [r for r in store.verify_walk(tmp_path) if not r.ok]
    assert len(bad) == 1
    assert bad[0].path == result.path
    assert bad[0].expected_sha256 == result.sha256
    assert bad[0].actual_sha256 == sha(b"corrupted bytes")


def test_lock_is_exclusive_while_holder_lives(tmp_path: Path) -> None:
    """R14: locks/<op> with O_EXCL semantics; a second taker is refused."""
    assert store.acquire_lock(tmp_path, "sweep") is True
    lock_file = tmp_path / "locks" / "sweep"
    assert lock_file.exists()
    assert lock_file.read_text().strip() == str(os.getpid())
    assert store.acquire_lock(tmp_path, "sweep") is False
    store.release_lock(tmp_path, "sweep")
    assert not lock_file.exists()
    assert store.acquire_lock(tmp_path, "sweep") is True


def test_stale_lock_from_dead_pid_is_taken_over(tmp_path: Path) -> None:
    """DESIGN section 13: a lock whose recorded PID is dead is stale."""
    from conftest import DEAD_PID

    lock_file = tmp_path / "locks" / "sweep"
    lock_file.parent.mkdir(parents=True)
    lock_file.write_text(str(DEAD_PID))
    assert store.acquire_lock(tmp_path, "sweep") is True
    assert lock_file.read_text().strip() == str(os.getpid())


def test_concurrent_puts_of_same_payload_never_tear(tmp_path: Path) -> None:
    """F3: identity-idempotence makes racing writers harmless: after N threaded
    puts of one payload, exactly one complete object exists."""
    import threading

    results: list[object] = []

    def worker() -> None:
        try:
            results.append(store.put(tmp_path, DATA))
        except Exception as exc:  # noqa: BLE001 - collected for the assertion
            results.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors
    puts = cast(list[store.PutResult], results)
    assert len({p.sha256 for p in puts}) == 1
    objects = list((tmp_path / "objects").rglob("*.jsonl"))
    assert len(objects) == 1
    assert objects[0].read_bytes() == DATA
    litter = [
        p for p in (tmp_path / "objects").rglob("*") if p.is_file() and p.suffix != ".jsonl"
    ]
    assert not litter
