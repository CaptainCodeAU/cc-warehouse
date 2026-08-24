"""The dashboard used to blend three unrelated populations into one "session"
count: the operator's own interactive sessions, Task sub-agent runs, and
automated one-shot API calls (hooks, titling). Measured 2026-08-24: 46.5% of
"sessions" in a typical range are the latter two, which is why "typical
session length" read 1.2 minutes instead of the true ~116 minutes.

`session_kind()` is the one place that classification happens (dashboard.py),
so a test here is the only guard against it drifting out of sync with the
page's own toggle. `test_dashboard_kind_toggle.py` covers the browser-side
half (the filter and the tile math); this file covers the Python half (the
classification itself and the payload column it produces).
"""

from __future__ import annotations

import sqlite3

import dashboard
from common import Window
from dashboard import KIND_AUTOMATED, KIND_MINE, KIND_NAMES, KIND_SUBAGENT, session_kind


def test_a_subagent_row_is_always_subagent_regardless_of_entrypoint() -> None:
    assert session_kind(1, "cli") == KIND_SUBAGENT
    assert session_kind(1, "sdk-cli") == KIND_SUBAGENT
    assert session_kind(1, None) == KIND_SUBAGENT


def test_sdk_cli_is_automated() -> None:
    assert session_kind(0, "sdk-cli") == KIND_AUTOMATED


def test_cli_is_mine() -> None:
    assert session_kind(0, "cli") == KIND_MINE


def test_local_agent_is_mine() -> None:
    assert session_kind(0, "local-agent") == KIND_MINE


def test_null_entrypoint_is_mine() -> None:
    """Real corpus fact (verified against sessions.sqlite, 2026-08-24): the
    138 real sessions with a NULL entrypoint all predate Claude Code
    recording the field (2026-02-14..2026-03-11) and are genuinely
    interactive - average 14.2 min, 7.2 prompts. They must not fall through
    to "automated"."""
    assert session_kind(0, None) == KIND_MINE


def test_kind_names_order_is_the_contract_the_page_indexes_into() -> None:
    """The payload stores a small int, not a string; the page looks it up in
    `DATA.lookups.kinds`. Reordering this list without a matching template
    change would silently relabel every session on the page."""
    assert KIND_NAMES == [KIND_MINE, KIND_SUBAGENT, KIND_AUTOMATED]


# --------------------------------------------------------------- payload wiring


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
    conn.execute(
        "CREATE TABLE tool_call (session_key TEXT, tool_name TEXT, is_error INT)"
    )
    conn.execute("CREATE TABLE attribution (session_key TEXT, kind TEXT, name TEXT, count INT)")
    conn.execute(
        "CREATE TABLE overlap_day (local_date TEXT, sessions_active INT,"
        " sessions_started INT, summed_hours REAL, elapsed_hours REAL,"
        " concurrency REAL, max_concurrent INT)"
    )
    conn.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    return conn


def _insert(conn: sqlite3.Connection, key: str, is_subagent: int, entrypoint: str | None) -> None:
    conn.execute(
        "INSERT INTO session (key, local_date, local_hour, local_weekday, project_label,"
        " repo_root, is_worktree, engaged_seconds, cost_usd, tok_input, tok_output,"
        " tok_cache_write, tok_cache_read, tok_thinking, cc_version, primary_model,"
        " wall_seconds, active_seconds, n_user_prompts, n_tool_uses, n_assistant_turns,"
        " is_subagent, entrypoint, is_real)"
        " VALUES (?, '2026-06-10', 10, 2, 'demo', '/x/demo', 0, 60.0, 0.5, 10, 20, 0, 0, 0,"
        " 'v1', 'claude-opus-5', 60.0, 60.0, 1, 0, 1, ?, ?, 1)",
        (key, is_subagent, entrypoint),
    )
    conn.commit()


def test_payload_carries_one_kind_column_and_a_kinds_lookup() -> None:
    conn = _make_db()
    _insert(conn, "mine-1", 0, "cli")
    _insert(conn, "sub-1", 1, "cli")
    _insert(conn, "auto-1", 0, "sdk-cli")
    _insert(conn, "old-1", 0, None)

    payload, unmatched = dashboard.build_payload(conn, Window())
    assert unmatched == []

    kind_col = payload["cols"]["S"].index("kind")
    assert payload["lookups"]["kinds"] == KIND_NAMES

    # S rows are in local_date/local_hour order with ties broken by SQLite's
    # own row order; all four fixtures share date/hour, so recover identity
    # via cost/project instead of relying on ORDER BY - simplest is to just
    # re-run the same SELECT the payload builder used, in insertion order.
    rows = conn.execute("SELECT key FROM session ORDER BY local_date, local_hour").fetchall()
    kinds_by_row_position = [row[kind_col] for row in payload["S"]]
    keys_in_row_order = [r[0] for r in rows]
    got = dict(zip(keys_in_row_order, kinds_by_row_position, strict=True))

    assert KIND_NAMES[got["mine-1"]] == KIND_MINE
    assert KIND_NAMES[got["sub-1"]] == KIND_SUBAGENT
    assert KIND_NAMES[got["auto-1"]] == KIND_AUTOMATED
    assert KIND_NAMES[got["old-1"]] == KIND_MINE
