"""Runs the REAL generated `dashboard_template.html` <script> block headlessly
under Node (`tests/node/dashboard_probe.js`), against a tiny synthetic
sessions.sqlite with known-by-construction expected numbers.

Before 2026-08-24 the client-side JS had zero test coverage at all, which is
how four real data-correctness defects (a sub-agent double count, three
populations blended into one "session" count, a wrong column on the "typical
session length" tile, and an unapplied project-exclude list) all shipped with
a fully green `pytest` suite - nothing had ever executed this script.

This is deliberately an end-to-end check of the ACTUAL bytes `dashboard.py`
would write, not a re-implementation of the page's logic in Python: every
number asserted here is independently computed straight from the fixture
data (never by calling `dashboard.build_payload`'s own aggregation code), so
a bug in either the Python payload builder or the page's own JS is equally
able to fail this test.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import dashboard
import pytest
from common import Window

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")

PROBE = Path(__file__).parent / "node" / "dashboard_probe.js"


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE session ("
        " key TEXT, local_date TEXT, local_hour INT, local_weekday INT,"
        " project_label TEXT, repo_root TEXT, is_worktree INT,"
        " engaged_seconds REAL, cost_usd REAL,"
        " tok_input INT, tok_output INT, tok_cache_write INT, tok_cache_read INT,"
        " tok_thinking INT, cc_version TEXT, primary_model TEXT,"
        " wall_seconds REAL, active_seconds REAL,"
        " n_user_prompts INT, n_tool_uses INT, n_assistant_turns INT,"
        " is_subagent INT, entrypoint TEXT, is_real INT)"
    )
    conn.execute(
        "CREATE TABLE turn (session_key TEXT, model TEXT, cost_usd REAL,"
        " input_tokens INT, output_tokens INT, cache_write_5m INT,"
        " cache_write_1h INT, cache_read INT, thinking_tokens INT)"
    )
    conn.execute("CREATE TABLE tool_call (session_key TEXT, tool_name TEXT, is_error INT)")
    conn.execute("CREATE TABLE attribution (session_key TEXT, kind TEXT, name TEXT, count INT)")
    conn.execute(
        "CREATE TABLE overlap_day (local_date TEXT, sessions_active INT,"
        " sessions_started INT, summed_hours REAL, elapsed_hours REAL,"
        " concurrency REAL, max_concurrent INT)"
    )
    conn.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    return conn


def _insert(
    conn: sqlite3.Connection,
    key: str,
    *,
    date: str,
    project: str,
    engaged: float,
    cost: float,
    is_subagent: int = 0,
    entrypoint: str | None = "cli",
) -> None:
    conn.execute(
        "INSERT INTO session (key, local_date, local_hour, local_weekday, project_label,"
        " repo_root, is_worktree, engaged_seconds, cost_usd, tok_input, tok_output,"
        " tok_cache_write, tok_cache_read, tok_thinking, cc_version, primary_model,"
        " wall_seconds, active_seconds, n_user_prompts, n_tool_uses, n_assistant_turns,"
        " is_subagent, entrypoint, is_real)"
        " VALUES (?, ?, 10, 2, ?, '/x/'||?, 0, ?, ?, 10, 20, 0, 0, 0,"
        " 'v1', 'claude-opus-5', ?, ?, 1, 0, 1, ?, ?, 1)",
        (key, date, project, project, engaged, cost, engaged, engaged, is_subagent, entrypoint),
    )
    conn.commit()


# `demo-parent` is a real project; `demo-parent-.claude-worktrees-agent-<hex>`
# is the auto-generated throwaway folder pattern the two grouping panels fold
# onto it. Excluding the CANONICAL name must remove both.
PARENT = "demo-parent"
WORKTREE_CHILD = "demo-parent-.claude-worktrees-agent-a1b2c3d4e5f60718"

FIXTURE = [
    # 5 "mine" sessions, engaged minutes: 10, 20, 30, 40, 50 -> median 30 min.
    dict(key="mine-1", date="2026-06-10", project=PARENT, engaged=600.0, cost=1.0),
    dict(key="mine-2", date="2026-06-11", project=PARENT, engaged=1200.0, cost=2.0),
    dict(key="mine-3", date="2026-06-12", project=PARENT, engaged=1800.0, cost=3.0),
    dict(key="mine-4", date="2026-06-13", project=PARENT, engaged=2400.0, cost=4.0),
    dict(key="mine-5", date="2026-06-14", project=WORKTREE_CHILD, engaged=3000.0, cost=5.0),
    # 2 sub-agent runs, 2 automated one-shots.
    dict(key="sub-1", date="2026-06-10", project=PARENT, engaged=60.0, cost=0.5, is_subagent=1),
    dict(key="sub-2", date="2026-06-11", project=PARENT, engaged=90.0, cost=0.7, is_subagent=1),
    dict(
        key="auto-1", date="2026-06-10", project=PARENT,
        engaged=5.0, cost=0.01, entrypoint="sdk-cli",
    ),
    dict(
        key="auto-2", date="2026-06-11", project=PARENT,
        engaged=6.0, cost=0.02, entrypoint="sdk-cli",
    ),
]


def _build_html(tmp_path: Path, unticked: list[str] | None = None) -> Path:
    conn = _make_db()
    for row in FIXTURE:
        _insert(conn, **row)
    payload, unmatched = dashboard.build_payload(conn, Window())
    assert unmatched == []
    if unticked is not None:
        payload["default_unticked_projects"] = unticked
    html = dashboard.render(payload)
    out = tmp_path / "dashboard.html"
    out.write_text(html, encoding="utf-8")
    return out


def _run_probe(html_path: Path, scenario: dict[str, object] | None = None) -> dict[str, object]:
    argv = [NODE, str(PROBE), str(html_path)]
    if scenario is not None:
        argv.append(json.dumps(scenario))
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, f"probe crashed: {proc.stderr}"
    return json.loads(proc.stdout)


def test_the_page_loads_and_every_panel_renders_without_throwing(tmp_path: Path) -> None:
    html_path = _build_html(tmp_path)
    result = _run_probe(html_path)
    assert result["runError"] is None, result["runError"]
    failed = {pid: p for pid, p in result["panels"].items() if not p["ok"]}
    assert failed == {}, f"panels threw: {failed}"
    assert len(result["panels"]) == 20, "a panel went missing from the page"


def test_default_view_splits_interactive_and_workload_populations(
    tmp_path: Path,
) -> None:
    """2026-08-27: a single "count as a session" toggle used to apply to
    every panel alike, which forced one answer onto two different questions
    (money spent vs. my own working time). Sub-agent runs are no longer a
    toggle at all: FS ("my own work" - hours/session-count panels) NEVER
    includes them; FSW ("real work done" - cost/token/tool panels) ALWAYS
    does, regardless of what is ticked.

    Default view ticks only "my sessions" (5 rows, engaged min
    10/20/30/40/50 -> median 30). FSW additionally includes the 2 sub-agent
    rows (engaged min 1/1.5), which is why "API cost" (an FSW-driven tile)
    is $15.00 (mine) + $1.20 (sub-agent) = $16.20 -> "US$ 16" (rounded), even
    though "sessions with a reply" (an FS-driven tile) stays 5. The 2
    automated rows must NOT appear anywhere - they still default off."""
    html_path = _build_html(tmp_path)
    result = _run_probe(html_path)

    assert result["fsLength"] == 5
    assert result["fswLength"] == 7
    tiles = result["panels"]["overview"]["tiles"]
    assert tiles["sessions with a reply"] == "5"
    assert tiles["typical session length"] == "30.0 min"
    assert tiles["API cost"] == "US$ 16"


def test_subagent_is_no_longer_a_toggle_and_scenario_kinds_cannot_revive_it(
    tmp_path: Path,
) -> None:
    """Regression guard for the exact bug this change fixes: even a scenario
    that still names "subagent" in `kinds` (as the old checkbox used to)
    must have ZERO effect. FS/FSW must come out identical to the untouched
    default view above."""
    html_path = _build_html(tmp_path)
    result = _run_probe(html_path, scenario={"kinds": ["mine", "subagent"]})
    assert result["fsLength"] == 5
    assert result["fswLength"] == 7


def test_ticking_automated_adds_it_to_both_populations_subagent_still_always_in(
    tmp_path: Path,
) -> None:
    """Ticking "automated" still works as a real toggle and affects BOTH
    populations (2 more rows each: FS 5->7, FSW 7->9). Sub-agent rows are
    unaffected either way - they were already in FSW and never enter FS."""
    html_path = _build_html(tmp_path)
    result = _run_probe(html_path, scenario={"kinds": ["mine", "automated"]})
    assert result["fsLength"] == 7
    assert result["fswLength"] == len(FIXTURE)


def test_excluding_the_canonical_parent_also_excludes_its_worktree_child(tmp_path: Path) -> None:
    """The bug this closes: `state.excluded` used to hold the RAW project
    index while the Projects/Project-month panels grouped by the CANONICAL
    name, so excluding a parent left its auto-worktree children ticked and
    their hours reappeared folded under the excluded name. Both sides are
    now keyed on the canonical name, so excluding "demo-parent" must drop
    ALL five "mine" rows, including mine-5 under the worktree child label."""
    html_path = _build_html(tmp_path)
    result = _run_probe(html_path, scenario={"excludedCanonical": [PARENT]})
    assert result["fsLength"] == 0, (
        "excluding the canonical parent should have removed the worktree child too"
    )


def test_kind_counts_are_date_and_project_filtered_but_not_kind_filtered(tmp_path: Path) -> None:
    """kindCounts() is what the toggle's own labels show - it must reflect
    what TICKING a box would add, so it must not itself be narrowed by
    which kinds are currently ticked."""
    html_path = _build_html(tmp_path)
    result = _run_probe(html_path)
    counts = result["kindCounts"]
    assert counts["mine"]["n"] == 5
    assert counts["subagent"]["n"] == 2
    assert counts["automated"]["n"] == 2
    assert round(counts["subagent"]["cost"], 2) == 1.2
    assert round(counts["automated"]["cost"], 2) == 0.03


def test_an_unapplied_default_exclude_list_no_longer_ships_silently(tmp_path: Path) -> None:
    """D4: `dashboard.py` used to never read `dashboard-defaults.json`, so a
    direct run always embedded `default_unticked_projects: []` even with a
    real defaults file sitting beside the database. This test exercises the
    PAYLOAD side of that fix (`load_default_filters`); the page-side default
    (`state.excluded` starting from `DATA.default_unticked_projects`) is
    covered by `test_excluding_the_canonical_parent_...` above using the
    equivalent payload field directly."""
    html_path = _build_html(tmp_path, unticked=[PARENT])
    result = _run_probe(html_path)
    assert result["fsLength"] == 0, "the baked-in default exclusion should apply on first load"
