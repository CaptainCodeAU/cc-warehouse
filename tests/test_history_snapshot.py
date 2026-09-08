"""Oracle tests: the whole-file, content-addressed `history.jsonl` snapshot (39c).

    <root>/_not-sessions/history-jsonl-snapshots/<sha256_12>.jsonl

`history.jsonl` is not session-keyed like `file-history/` or `todos/` (39b): it is
one shared file for the whole machine, so there is no session folder to nest it
under. The backstop this slice exists for is stated in the ticket: it catches the
14% of `history.jsonl` rows with no archived session, future format drift, and any
bug in a later per-session split (39d), none of which a per-session copy alone
could ever cover.

CONTENT-ADDRESSED ON PURPOSE, and that is why the write is an exists()-only check
rather than `store.write_if_absent`'s refuse-and-record: the filename IS the hash,
so `exists()` already means "these are the same bytes" (F1/F4). A second write of
identical content is a true no-op; two different snapshots simply get two names.

Contract: DESIGN R2, R4 as amended, R9; FINDINGS F1, F4.
"""

from pathlib import Path

import pytest

from cc_warehouse import archive, store

SNAPSHOT_A = b'{"display":"fix the flux capacitor","sessionId":"aaaa"}\n'
SNAPSHOT_B = b'{"display":"a completely different prompt","sessionId":"bbbb"}\n'


def test_history_snapshot_path_is_content_addressed(tmp_path: Path) -> None:
    expected = store.sha256_hex(SNAPSHOT_A)[:12]
    target = archive.history_snapshot_path(tmp_path, SNAPSHOT_A)
    assert target == (
        tmp_path / "_not-sessions" / "history-jsonl-snapshots" / f"{expected}.jsonl"
    )


def test_history_snapshot_path_computes_no_io(tmp_path: Path) -> None:
    """Pure path computation: asking for the path must not create anything,
    since doctor calls this on every run just to check whether a file exists."""
    archive.history_snapshot_path(tmp_path, SNAPSHOT_A)
    assert not (tmp_path / "_not-sessions").exists()


def test_write_history_snapshot_lands_under_not_sessions(tmp_path: Path) -> None:
    target = archive.write_history_snapshot(tmp_path, SNAPSHOT_A)
    assert target.read_bytes() == SNAPSHOT_A
    assert target.parent == tmp_path / "_not-sessions" / "history-jsonl-snapshots"


def test_two_different_snapshots_land_at_two_different_paths(tmp_path: Path) -> None:
    first = archive.write_history_snapshot(tmp_path, SNAPSHOT_A)
    second = archive.write_history_snapshot(tmp_path, SNAPSHOT_B)
    assert first != second
    assert first.read_bytes() == SNAPSHOT_A
    assert second.read_bytes() == SNAPSHOT_B


def test_a_second_write_of_the_same_bytes_writes_nothing_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exists()-only check must actually stop a second write, not merely
    overwrite with identical bytes: monkeypatch the one write primitive to raise
    if it is ever called a second time for this same content."""
    archive.write_history_snapshot(tmp_path, SNAPSHOT_A)

    def _boom(path: Path, data: bytes) -> None:
        raise AssertionError("a second write for identical content must not happen")

    monkeypatch.setattr(store, "atomic_write", _boom)
    target = archive.write_history_snapshot(tmp_path, SNAPSHOT_A)
    assert target.read_bytes() == SNAPSHOT_A


def test_the_reserved_label_keeps_the_rebuilder_away(tmp_path: Path) -> None:
    """`_not-sessions` is already in `build.RESERVED_LABELS`, so the new
    subdirectory needs no rebuild-safety work of its own -- pinned directly so a
    future rename of that constant cannot silently drop this store into the
    rebuilder's path."""
    from cc_warehouse import build

    assert archive.NOT_SESSIONS_LABEL in build.RESERVED_LABELS
