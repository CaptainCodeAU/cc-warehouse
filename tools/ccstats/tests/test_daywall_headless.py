"""Runs the REAL generated `daywall_template.html` <script> block's PURE-DATA
half (clipToDays, packLanes, recomputeFiltered) headlessly under Node
(`tests/node/daywall_probe.js`). The WebGL half cannot run under Node at all
-- see `daywall_probe.js`'s own docstring for how the probe forces the
no-WebGL fallback path while still exercising these functions directly.

Same motivation as `test_dashboard_headless.py`: before this suite existed,
nothing had ever executed this page's client-side JS.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import daywall
import pytest
from common import Window

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")

PROBE = Path(__file__).parent / "node" / "daywall_probe.js"


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE session ("
        " key TEXT, session_uuid TEXT, first_ts TEXT, last_ts TEXT,"
        " local_date TEXT, local_hour INT, tz_offset TEXT,"
        " engaged_seconds REAL, cost_usd REAL, project_label TEXT,"
        " primary_model TEXT, is_subagent INT, entrypoint TEXT,"
        " parent_session_uuid TEXT, is_real INT)"
    )
    conn.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    return conn


def _insert(
    conn: sqlite3.Connection,
    key: str,
    *,
    first_ts: str,
    last_ts: str,
    date: str,
    project: str = "demo",
    engaged: float = 3000.0,
    cost: float = 1.0,
    is_subagent: int = 0,
    entrypoint: str | None = "cli",
) -> None:
    conn.execute(
        "INSERT INTO session (key, session_uuid, first_ts, last_ts, local_date,"
        " local_hour, tz_offset, engaged_seconds, cost_usd, project_label,"
        " primary_model, is_subagent, entrypoint, parent_session_uuid, is_real)"
        " VALUES (?, ?, ?, ?, ?, 0, '+0000', ?, ?, ?, 'claude-opus-5', ?, ?, NULL, 1)",
        (key, key, first_ts, last_ts, date, engaged, cost, project, is_subagent, entrypoint),
    )
    conn.commit()


PARENT = "demo-parent"
WORKTREE_CHILD = "demo-parent-.claude-worktrees-agent-a1b2c3d4e5f60718"


def _build_html(tmp_path: Path) -> Path:
    conn = _make_db()
    _insert(
        conn, "keep-1",
        first_ts="2026-06-10T09:00:00.000Z", last_ts="2026-06-10T10:00:00.000Z",
        date="2026-06-10", project="keep",
    )
    _insert(
        conn, "drop-1",
        first_ts="2026-06-10T09:15:00.000Z", last_ts="2026-06-10T10:15:00.000Z",
        date="2026-06-10", project="drop",
    )
    _insert(
        conn, "parent-1",
        first_ts="2026-06-11T09:00:00.000Z", last_ts="2026-06-11T10:00:00.000Z",
        date="2026-06-11", project=PARENT,
    )
    _insert(
        conn, "child-1",
        first_ts="2026-06-11T09:05:00.000Z", last_ts="2026-06-11T09:10:00.000Z",
        date="2026-06-11", project=WORKTREE_CHILD,
    )
    payload, unmatched = daywall.build_daywall_payload(conn, Window())
    assert unmatched == []
    html = daywall.render(payload)
    out = tmp_path / "daywall.html"
    out.write_text(html, encoding="utf-8")
    return out


def _run_probe(html_path: Path, scenario: dict[str, object] | None = None) -> dict[str, object]:
    argv = [NODE, str(PROBE), str(html_path)]
    if scenario is not None:
        argv.append(json.dumps(scenario))
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, f"probe crashed: {proc.stderr}"
    return json.loads(proc.stdout)


def test_the_page_loads_without_throwing(tmp_path: Path) -> None:
    html_path = _build_html(tmp_path)
    result = _run_probe(html_path)
    assert result["runError"] is None, result["runError"]


def test_default_view_includes_every_kind_and_project(tmp_path: Path) -> None:
    html_path = _build_html(tmp_path)
    result = _run_probe(html_path)
    assert result["sessionCount"] == 4
    assert result["dayCount"] == 2


def test_a_three_day_session_clips_into_exactly_three_segments_at_the_right_boundaries(
    tmp_path: Path,
) -> None:
    html_path = _build_html(tmp_path)
    # dayIdx 0, starting 23:00 (82800s), running 26 hours (93600s): ends at
    # dayIdx 2, 01:00. Must clip to [0: 82800-86400], [1: 0-86400], [2: 0-3600].
    result = _run_probe(html_path, scenario={"clipToDaysCases": [[0, 82800, 93600]]})
    segs = result["clipToDaysResults"][0]
    assert len(segs) == 3
    assert segs[0] == {"dayIdx": 0, "startSec": 82800, "endSec": 86400}
    assert segs[1] == {"dayIdx": 1, "startSec": 0, "endSec": 86400}
    assert segs[2] == {"dayIdx": 2, "startSec": 0, "endSec": 3600}


def test_a_33_day_session_does_not_blow_up(tmp_path: Path) -> None:
    html_path = _build_html(tmp_path)
    result = _run_probe(
        html_path, scenario={"clipToDaysCases": [[0, 0, 33 * 86400]]}
    )
    segs = result["clipToDaysResults"][0]
    assert len(segs) == 33
    assert segs[0]["dayIdx"] == 0
    assert segs[-1]["dayIdx"] == 32


def test_a_zero_duration_session_still_yields_one_visible_segment(tmp_path: Path) -> None:
    html_path = _build_html(tmp_path)
    result = _run_probe(html_path, scenario={"clipToDaysCases": [[5, 100, 0]]})
    segs = result["clipToDaysResults"][0]
    assert len(segs) == 1
    assert segs[0]["startSec"] == 100
    assert segs[0]["endSec"] == 101


def test_lane_packing_gives_the_known_lane_numbers_for_known_overlaps(tmp_path: Path) -> None:
    html_path = _build_html(tmp_path)
    # A: 0-100, B: 50-150 (overlaps A -> lane 1), C: 100-200 (A has ended,
    # but B has not -> lane 0, reusing A's freed lane, not a new lane 2).
    case = [
        {"dayIdx": 0, "startSec": 0, "endSec": 100},
        {"dayIdx": 0, "startSec": 50, "endSec": 150},
        {"dayIdx": 0, "startSec": 100, "endSec": 200},
    ]
    result = _run_probe(html_path, scenario={"packLanesCases": [case]})
    got = result["packLanesResults"][0]
    assert got["laneCount"] == 2
    lanes_by_start = {s["startSec"]: s["lane"] for s in got["segments"]}
    assert lanes_by_start == {0: 0, 50: 1, 100: 0}


def test_excluding_a_project_renumbers_the_remaining_lane_with_no_gap(tmp_path: Path) -> None:
    """"keep" (09:00) and "drop" (09:15) overlap, so with both present "drop"
    sits in lane 1. Excluding "drop" must leave "keep" in lane 0 -- not lane
    0 with an empty lane 1 still implied, and not left in some stale lane
    1 from before. recomputeFiltered() re-packs from scratch every call, so
    this is really a test that the WHOLE pipeline is stateless, not just
    packLanes in isolation."""
    html_path = _build_html(tmp_path)

    both = _run_probe(html_path)
    drop_lanes = {s["lane"] for s in both["draw"] if s["dayIdx"] == 0}
    assert drop_lanes == {0, 1}

    without_drop = _run_probe(html_path, scenario={"excludedCanonical": ["drop"]})
    assert without_drop["sessionCount"] == 3
    day0 = [s for s in without_drop["draw"] if s["dayIdx"] == 0]
    assert len(day0) == 1
    assert day0[0]["lane"] == 0


def test_excluding_the_canonical_parent_also_excludes_its_worktree_child(tmp_path: Path) -> None:
    """The bug this guards (same shape as dashboard_template.html's own
    equivalent test): `state.excluded` must be keyed on the CANONICAL
    project name, not the raw project index, or excluding "demo-parent"
    would leave its "-.claude-worktrees-agent-<hex>" child ticked."""
    html_path = _build_html(tmp_path)
    result = _run_probe(html_path, scenario={"excludedCanonical": [PARENT]})
    assert result["sessionCount"] == 2  # only "keep" and "drop" survive


def test_threads_toggle_off_removes_every_thread(tmp_path: Path) -> None:
    html_path = _build_html(tmp_path)
    on = _run_probe(html_path)
    off = _run_probe(html_path, scenario={"threads": False})
    assert off["threads"] == []
    # not asserting `on["threads"]` is non-empty here: the fixture's
    # parent/child rows have unrelated session_uuids (no real P edge), so
    # both are legitimately empty -- this only guards the OFF switch itself.
    assert on["threads"] == []
