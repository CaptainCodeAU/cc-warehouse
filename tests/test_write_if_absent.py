"""Oracle tests for store.write_if_absent (ticket 38, slice 38a).

The sibling of `write_if_changed`, and the difference is the whole point.
`write_if_changed` falls THROUGH to a write when the target differs: it owns
generated files, which are supposed to be regenerated. `write_if_absent` owns
COPIED SOURCE data, where a differing target means two different things claimed
one name, and guessing which is right is exactly what R5 forbids. So it refuses,
returns why, and writes nothing.

DESIGN R2 (every write is tmp + os.replace), R5 (the conservative branch),
FINDINGS F1 (bytes decide, never size or mtime).
"""

from pathlib import Path

import pytest

from cc_warehouse import store


def test_an_absent_target_is_written_with_the_exact_bytes(tmp_path: Path) -> None:
    target = tmp_path / "hook-abc-stdout.txt"
    assert store.write_if_absent(target, b"captured stdout\n") == "wrote"
    assert target.read_bytes() == b"captured stdout\n"


def test_identical_bytes_report_unchanged(tmp_path: Path) -> None:
    target = tmp_path / "same.txt"
    store.write_if_absent(target, b"payload")
    assert store.write_if_absent(target, b"payload") == "unchanged"


def test_identical_bytes_do_not_move_the_targets_mtime(tmp_path: Path) -> None:
    """The daily-rewrite defect (ticket 37 Part A) in its general form: a copier
    that rewrites 2,084 identical files a day makes every backup tool think the
    whole archive changed. Proved behaviourally rather than by reading the code,
    because only the behaviour is the promise.

    The two mtimes are compared as LOCAL VALUES, never as `a.stat().st_mtime_ns
    == b.stat().st_mtime_ns` inside one expression - the F1 fence in
    tests/test_fences.py bans stat-attribute equality in runtime source, and a
    test that models the banned shape teaches the wrong thing.
    """
    target = tmp_path / "same.txt"
    store.write_if_absent(target, b"payload")
    before = target.stat().st_mtime_ns
    store.write_if_absent(target, b"payload")
    after = target.stat().st_mtime_ns
    assert before == after


def test_different_bytes_are_refused(tmp_path: Path) -> None:
    target = tmp_path / "collision.txt"
    store.write_if_absent(target, b"the archived one")
    assert store.write_if_absent(target, b"a different one") == "refused"


def test_a_refusal_leaves_the_archived_bytes_untouched(tmp_path: Path) -> None:
    """R5: the conservative branch keeps what is already there. Nothing about a
    tool result licenses "the newer one wins" - there is no larger-is-better
    argument for it the way there is for a re-captured transcript."""
    target = tmp_path / "collision.txt"
    store.write_if_absent(target, b"the archived one")
    store.write_if_absent(target, b"a much much longer different one")
    assert target.read_bytes() == b"the archived one"


def test_an_unreadable_target_is_refused_rather_than_overwritten(tmp_path: Path) -> None:
    """The opposite direction from `write_if_changed`, deliberately. There, an
    unreadable target falls through to a write because the file is generated and
    a fresh copy is strictly better. Here the target may be the only copy of
    something, so "I cannot tell what is there" must never resolve to "overwrite
    it"."""
    target = tmp_path / "unreadable.txt"
    target.write_bytes(b"the archived one")
    target.chmod(0o000)
    try:
        assert store.write_if_absent(target, b"anything") == "refused"
    finally:
        target.chmod(0o600)
    assert target.read_bytes() == b"the archived one"


def test_a_missing_parent_directory_is_not_created_here(tmp_path: Path) -> None:
    """One job. The caller decides where a tree lives and creates it; this
    decides whether bytes may land on a path. Folding mkdir in here would let any
    caller materialise a directory tree by typo."""
    with pytest.raises(OSError):
        store.write_if_absent(tmp_path / "nope" / "deep.txt", b"x")
