"""A sub-agent transcript that exists in BOTH the archive and the live tree
used to be stored TWICE, because the two trees name the same sub-agent
differently and the collector keyed on the raw filename:

  archive: subagents/<id>.jsonl        -> key "agent:<id>"
  live:    subagents/agent-<id>.jsonl  -> key "agent:agent-<id>"

Different keys, so the "duplicate payloads collapsed" pass never paired them
- both were parsed and inserted as separate `session` rows. Measured on the
real corpus: 1,908 such pairs, +US$5,750, +119 engaged hours, every figure
that sums `session` double-counted (2026-08-24 dashboard investigation).

The fix normalises a sub-agent's key to the identity Claude Code itself uses
(strip a leading `agent-`), so both trees collapse to one row - exactly like
a top-level session's `<uuid>.jsonl` already does.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import collect
import pytest

from conftest import assistant, payload, user

SUBAGENT_TURN = payload(
    user("2026-06-10T01:00:00.000Z"),
    assistant("2026-06-10T01:00:05.000Z", out=100),
)


def _archive_root(tmp_path: Path) -> Path:
    return tmp_path / "archive"


def _live_root(tmp_path: Path) -> Path:
    return tmp_path / "live"


def _write_archive_subagent(tmp_path: Path, agent_id: str, data: bytes) -> None:
    folder = _archive_root(tmp_path) / "demo-project" / f"20260610-010000_parent-{agent_id}"
    subs = folder / "subagents"
    subs.mkdir(parents=True, exist_ok=True)
    (subs / f"{agent_id}.jsonl").write_bytes(data)


def _write_live_subagent(tmp_path: Path, session_dir: str, agent_id: str, data: bytes) -> None:
    subs = _live_root(tmp_path) / "demo-project" / session_dir / "subagents"
    subs.mkdir(parents=True, exist_ok=True)
    (subs / f"agent-{agent_id}.jsonl").write_bytes(data)


def _run(tmp_path: Path, monkeypatch) -> Path:
    out_root = tmp_path / "out"
    monkeypatch.setattr(collect, "ARCHIVE", _archive_root(tmp_path))
    monkeypatch.setattr(collect, "LIVE", _live_root(tmp_path))
    monkeypatch.setattr(sys, "argv", ["collect.py", "--out", str(out_root), "--quiet"])
    assert collect.main() == 0
    return out_root


def _subagent_rows(out_root: Path) -> list[tuple[str, str, int]]:
    conn = sqlite3.connect(out_root / "sessions.sqlite")
    rows = conn.execute(
        "SELECT key, source_tree, size_bytes FROM session WHERE is_subagent = 1 ORDER BY key"
    ).fetchall()
    conn.close()
    return rows


def test_archive_and_live_copies_of_one_subagent_collapse_to_one_row(
    tmp_path: Path, monkeypatch
) -> None:
    _write_archive_subagent(tmp_path, "a00aa5fd7d8ffdea0", SUBAGENT_TURN)
    _write_live_subagent(tmp_path, "parent-session-dir", "a00aa5fd7d8ffdea0", SUBAGENT_TURN)

    out_root = _run(tmp_path, monkeypatch)
    rows = _subagent_rows(out_root)

    assert len(rows) == 1, f"expected exactly one sub-agent row, got {rows!r}"
    assert rows[0][0] == "agent:a00aa5fd7d8ffdea0"


def test_two_genuinely_distinct_subagents_each_keep_their_own_row(
    tmp_path: Path, monkeypatch
) -> None:
    """The fix must not over-collapse: two different sub-agents, one archive-only
    and one live-only, are unrelated and must both survive."""
    _write_archive_subagent(tmp_path, "aaaaaaaaaaaaaaaaa", SUBAGENT_TURN)
    _write_live_subagent(tmp_path, "parent-session-dir", "bbbbbbbbbbbbbbbbb", SUBAGENT_TURN)

    out_root = _run(tmp_path, monkeypatch)
    rows = _subagent_rows(out_root)

    assert {r[0] for r in rows} == {
        "agent:aaaaaaaaaaaaaaaaa",
        "agent:bbbbbbbbbbbbbbbbb",
    }


def test_the_larger_copy_wins_regardless_of_which_tree_it_is_in(
    tmp_path: Path, monkeypatch
) -> None:
    """Same identity, genuinely different content (one has an extra turn).
    The larger file must win - this is the existing size-ordering rule
    (DESIGN R1/R12), unaffected by the key-normalisation fix."""
    small = SUBAGENT_TURN
    large = SUBAGENT_TURN + assistant("2026-06-10T01:05:00.000Z", out=50).encode() + b"\n"
    assert len(large) > len(small)

    _write_archive_subagent(tmp_path, "cccccccccccccccc", small)
    _write_live_subagent(tmp_path, "parent-session-dir", "cccccccccccccccc", large)

    out_root = _run(tmp_path, monkeypatch)
    rows = _subagent_rows(out_root)

    assert len(rows) == 1
    assert rows[0][2] == len(large), "the larger (live) copy should have won"


def test_report_reflects_the_collapse_not_a_double_count(tmp_path: Path, monkeypatch) -> None:
    _write_archive_subagent(tmp_path, "dddddddddddddddd", SUBAGENT_TURN)
    _write_live_subagent(tmp_path, "parent-session-dir", "dddddddddddddddd", SUBAGENT_TURN)

    out_root = _run(tmp_path, monkeypatch)
    import json

    report = json.loads((out_root / "collect-report.json").read_text())
    assert report["transcript_files_found"] == 2
    assert report["distinct_sessions"] == 1
    assert report["duplicate_payloads_collapsed"] == 1


def test_cache_schema_version_was_bumped() -> None:
    """A version bump forces one full rescan after this fix ships, so no
    row published under the OLD (buggy) per-tree key can survive into a
    cache built by the fixed code."""
    assert collect.CACHE_SCHEMA_VERSION >= 2


@pytest.mark.parametrize("stem", ["agent-x", "agent-", "agent-agent-x"])
def test_prefix_stripped_exactly_once(tmp_path: Path, monkeypatch, stem: str) -> None:
    """Only ONE leading `agent-` is ever stripped, matching how Claude Code
    itself names these files - a sub-agent id that happens to start with the
    literal text "agent-" is not something this corpus produces (ids are hex
    strings), but the stripping must not be greedy/recursive regardless."""
    data = SUBAGENT_TURN
    subs = _live_root(tmp_path) / "demo-project" / "parent-session-dir" / "subagents"
    subs.mkdir(parents=True, exist_ok=True)
    (subs / f"{stem}.jsonl").write_bytes(data)
    monkeypatch.setattr(collect, "ARCHIVE", tmp_path / "no-archive")
    monkeypatch.setattr(collect, "LIVE", _live_root(tmp_path))
    monkeypatch.setattr(sys, "argv", ["collect.py", "--out", str(tmp_path / "out"), "--quiet"])
    assert collect.main() == 0
    rows = _subagent_rows(tmp_path / "out")
    assert len(rows) == 1
    expected = stem[len("agent-") :] if stem.startswith("agent-") else stem
    assert rows[0][0] == f"agent:{expected}"
