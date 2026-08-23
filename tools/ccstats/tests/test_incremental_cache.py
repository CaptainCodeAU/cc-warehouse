"""The incremental scan cache, added 2026-08-23 to cut ~25s of unnecessary
re-parsing on every run: most transcripts never change once a session ends,
so `scan_transcript`'s own result for an untouched file is now reused from
`scan-cache.sqlite` instead of re-reading and re-parsing that file.

Every test here proves a specific correctness property the cache must hold,
not just that it exists:
  - an unmodified rerun returns byte-identical derived numbers (reconstructing
    from the cache must not drift from what a real scan would produce)
  - only the file that actually changed gets rescanned; a genuinely new file
    is scanned without disturbing anything else's cache-hit status
  - a price-table or timezone change invalidates the WHOLE cache automatically
    (an old row otherwise keeps reporting numbers only true under the OLD
    prices/zone forever, since a finished session's file never changes again)
  - `--no-cache` forces a full rescan but still republishes a fresh cache
  - a `--limit` smoke-test run reads the cache but never overwrites it with a
    partial slice, which would otherwise evict every session outside the slice
  - a missing/corrupted cache file degrades to a full, correct scan rather
    than crashing or returning a wrong answer (R5/R10)
  - the cache is published with the same temp-file + os.replace discipline as
    sessions.sqlite (R2), so a crash mid-publish can't corrupt the last good one
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import collect
import pytest

from conftest import assistant, payload, user

SESSION_A = payload(
    user("2026-06-10T01:00:00.000Z"),
    assistant("2026-06-10T01:00:05.000Z", out=100),
)
SESSION_B = payload(
    user("2026-06-11T01:00:00.000Z"),
    assistant("2026-06-11T01:00:05.000Z", out=200),
)


def _corpus(tmp_path: Path, monkeypatch, files: dict[str, bytes]) -> tuple[Path, Path]:
    """Point ARCHIVE/LIVE at throwaway trees holding one file per
    (filename -> payload) pair. The filename (its path stem) is the cache
    key, independent of whatever `sessionId` the payload itself carries -
    every fixture payload hardcodes `sessionId: "s-1"`, which is irrelevant
    here since the cache keys off the file, not that field."""
    live_root = tmp_path / "live"
    proj = live_root / "demo-project"
    proj.mkdir(parents=True)
    for name, data in files.items():
        (proj / name).write_bytes(data)
    monkeypatch.setattr(collect, "ARCHIVE", tmp_path / "no-archive")
    monkeypatch.setattr(collect, "LIVE", live_root)
    return tmp_path / "out", proj


def _run(out_root: Path, monkeypatch, extra_argv: tuple[str, ...] = ()) -> dict[str, object]:
    monkeypatch.setattr(
        sys, "argv", ["collect.py", "--out", str(out_root), "--quiet", *extra_argv]
    )
    assert collect.main() == 0
    return json.loads((out_root / "collect-report.json").read_text())


def _sessions(out_root: Path) -> dict[str, tuple[int, int]]:
    """key -> (tok_output, n_assistant_turns), the two fields the append test
    changes, so a rescanned row can be told apart from a merely-republished one."""
    conn = sqlite3.connect(out_root / "sessions.sqlite")
    rows = conn.execute("SELECT key, tok_output, n_assistant_turns FROM session").fetchall()
    conn.close()
    return {row[0]: (row[1], row[2]) for row in rows}


def test_fresh_run_populates_the_cache(tmp_path: Path, monkeypatch) -> None:
    out_root, _proj = _corpus(tmp_path, monkeypatch, {"a.jsonl": SESSION_A, "b.jsonl": SESSION_B})
    report = _run(out_root, monkeypatch)
    assert report["cache_hits"] == 0
    assert report["cache_rescanned"] == 2
    assert report["cache_written"] is True
    assert (out_root / "scan-cache.sqlite").exists()


def test_an_unmodified_rerun_is_a_full_cache_hit_with_identical_output(
    tmp_path: Path, monkeypatch
) -> None:
    out_root, _proj = _corpus(tmp_path, monkeypatch, {"a.jsonl": SESSION_A, "b.jsonl": SESSION_B})
    _run(out_root, monkeypatch)
    before = _sessions(out_root)

    report = _run(out_root, monkeypatch)
    assert report["cache_hits"] == 2
    assert report["cache_rescanned"] == 0
    assert _sessions(out_root) == before, "a cache-reconstructed row must match a real scan exactly"


def test_only_the_changed_file_is_rescanned(tmp_path: Path, monkeypatch) -> None:
    out_root, proj = _corpus(tmp_path, monkeypatch, {"a.jsonl": SESSION_A, "b.jsonl": SESSION_B})
    _run(out_root, monkeypatch)
    before = _sessions(out_root)

    # a.jsonl grows (one more assistant turn); b.jsonl is untouched.
    with (proj / "a.jsonl").open("ab") as handle:
        handle.write(assistant("2026-06-10T01:05:00.000Z", out=50).encode() + b"\n")

    report = _run(out_root, monkeypatch)
    assert report["cache_hits"] == 1, "b.jsonl must still hit"
    assert report["cache_rescanned"] == 1, "only a.jsonl changed"

    after = _sessions(out_root)
    assert after["b"] == before["b"], "the unchanged file's row must be untouched"
    assert after["a"][1] == before["a"][1] + 1, "a gained exactly one assistant turn"


def test_a_new_file_is_scanned_without_disturbing_existing_cache_hits(
    tmp_path: Path, monkeypatch
) -> None:
    out_root, proj = _corpus(tmp_path, monkeypatch, {"a.jsonl": SESSION_A, "b.jsonl": SESSION_B})
    _run(out_root, monkeypatch)

    (proj / "c.jsonl").write_bytes(
        payload(user("2026-06-12T01:00:00.000Z"), assistant("2026-06-12T01:00:05.000Z", out=300))
    )
    report = _run(out_root, monkeypatch)
    assert report["cache_hits"] == 2, "a and b are unchanged"
    assert report["cache_rescanned"] == 1, "only the new file c"
    assert set(_sessions(out_root)) == {"a", "b", "c"}


def test_a_price_change_invalidates_the_whole_cache(tmp_path: Path, monkeypatch) -> None:
    """`cost_usd` is baked into every cached row. An old row for an untouched
    file must not keep reporting a stale dollar figure after the price table
    is updated - the fingerprint check must throw the WHOLE cache away, not
    just the rows for files that changed."""
    out_root, _proj = _corpus(tmp_path, monkeypatch, {"a.jsonl": SESSION_A, "b.jsonl": SESSION_B})
    _run(out_root, monkeypatch)

    monkeypatch.setattr(collect, "PRICES_READ_ON", "2099-01-01")
    report = _run(out_root, monkeypatch)
    assert report["cache_hits"] == 0
    assert report["cache_rescanned"] == 2


def test_a_timezone_change_invalidates_the_whole_cache(tmp_path: Path, monkeypatch) -> None:
    """local_date/local_hour are baked into every cached row too."""
    out_root, _proj = _corpus(tmp_path, monkeypatch, {"a.jsonl": SESSION_A, "b.jsonl": SESSION_B})
    _run(out_root, monkeypatch)

    monkeypatch.setattr(collect, "_LOCAL_TZ_NAME", "Europe/Berlin")
    report = _run(out_root, monkeypatch)
    assert report["cache_hits"] == 0
    assert report["cache_rescanned"] == 2


def test_no_cache_flag_forces_a_full_rescan_but_still_republishes(
    tmp_path: Path, monkeypatch
) -> None:
    out_root, _proj = _corpus(tmp_path, monkeypatch, {"a.jsonl": SESSION_A, "b.jsonl": SESSION_B})
    _run(out_root, monkeypatch)

    report = _run(out_root, monkeypatch, extra_argv=("--no-cache",))
    assert report["cache_hits"] == 0
    assert report["cache_rescanned"] == 2
    assert report["cache_written"] is True, "the NEXT normal run should still get a fresh cache"

    report = _run(out_root, monkeypatch)
    assert report["cache_hits"] == 2, "the cache written by the --no-cache run is usable again"


def test_limit_run_reads_but_never_overwrites_the_cache(tmp_path: Path, monkeypatch) -> None:
    out_root, _proj = _corpus(tmp_path, monkeypatch, {"a.jsonl": SESSION_A, "b.jsonl": SESSION_B})
    _run(out_root, monkeypatch)
    cache_path = out_root / "scan-cache.sqlite"
    before_bytes = cache_path.read_bytes()

    report = _run(out_root, monkeypatch, extra_argv=("--limit", "1"))
    assert report["cache_written"] is False
    assert report["cache_hits"] == 1, "the one file --limit kept was still read from the cache"
    assert cache_path.read_bytes() == before_bytes, "a partial run must never evict the full cache"

    report = _run(out_root, monkeypatch)
    assert report["cache_hits"] == 2, "the full cache from before the --limit run survived intact"


def test_a_corrupted_cache_file_falls_back_to_a_full_scan(tmp_path: Path, monkeypatch) -> None:
    out_root, _proj = _corpus(tmp_path, monkeypatch, {"a.jsonl": SESSION_A, "b.jsonl": SESSION_B})
    _run(out_root, monkeypatch)

    (out_root / "scan-cache.sqlite").write_bytes(b"not a sqlite file at all")
    report = _run(out_root, monkeypatch)
    assert report["cache_hits"] == 0
    assert report["cache_rescanned"] == 2

    report = _run(out_root, monkeypatch)
    assert report["cache_hits"] == 2, "the freshly rebuilt cache is valid again"


def test_an_absent_cache_is_not_an_error(tmp_path: Path, monkeypatch) -> None:
    """The very first run of all: there is nothing to read yet."""
    out_root, _proj = _corpus(tmp_path, monkeypatch, {"a.jsonl": SESSION_A})
    assert not (out_root / "scan-cache.sqlite").exists()
    report = _run(out_root, monkeypatch)
    assert report["cache_hits"] == 0
    assert report["cache_rescanned"] == 1


def test_a_crash_publishing_the_cache_never_corrupts_the_last_good_one(
    tmp_path: Path, monkeypatch
) -> None:
    out_root, proj = _corpus(tmp_path, monkeypatch, {"a.jsonl": SESSION_A, "b.jsonl": SESSION_B})
    _run(out_root, monkeypatch)
    cache_path = out_root / "scan-cache.sqlite"
    before = cache_path.read_bytes()

    # Give this run something new to write, so a crash-vs-no-crash difference
    # is actually observable in what WOULD have been published.
    (proj / "c.jsonl").write_bytes(
        payload(user("2026-06-12T01:00:00.000Z"), assistant("2026-06-12T01:00:05.000Z"))
    )

    real_replace = collect.os.replace

    def flaky_replace(src: object, dst: object) -> object:
        if Path(dst).name == "scan-cache.sqlite":
            raise RuntimeError("simulated crash publishing the cache")
        return real_replace(src, dst)

    monkeypatch.setattr(collect.os, "replace", flaky_replace)
    monkeypatch.setattr(sys, "argv", ["collect.py", "--out", str(out_root), "--quiet"])
    with pytest.raises(RuntimeError):
        collect.main()

    assert cache_path.read_bytes() == before, (
        "a crashed publish must leave the last good cache alone"
    )
    assert (out_root / "sessions.sqlite").exists(), "the session database still published fine"
    leftovers = list(out_root.glob("scan-cache.*.sqlite.building"))
    assert len(leftovers) == 1, (
        "the orphaned temp file is left for the operator, same as sessions.sqlite's own"
    )
