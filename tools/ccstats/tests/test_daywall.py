"""Oracle tests for `daywall.py`, the 3D companion page's builder.

Written before daywall.py exists, per this project's own rule ("Oracle tests
before implementation. Never port tests from the specimen suite.") The 2D
dashboard's own payload is untouched by any of this - `build_daywall_payload`
is a separate, slimmer query, not an extension of `dashboard.build_payload`.
"""

from __future__ import annotations

import sqlite3

import common
import daywall
import pytest
from common import Window
from dashboard import KIND_AUTOMATED, KIND_MINE, KIND_NAMES, KIND_SUBAGENT


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
    session_uuid: str,
    first_ts: str,
    last_ts: str,
    date: str,
    project: str = "demo",
    engaged: float = 60.0,
    cost: float = 0.5,
    model: str = "claude-opus-5",
    is_subagent: int = 0,
    entrypoint: str | None = "cli",
    parent_session_uuid: str | None = None,
    tz_offset: str | None = "+1000",
) -> None:
    conn.execute(
        "INSERT INTO session (key, session_uuid, first_ts, last_ts, local_date,"
        " local_hour, tz_offset, engaged_seconds, cost_usd, project_label,"
        " primary_model, is_subagent, entrypoint, parent_session_uuid, is_real)"
        " VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
        (
            key, session_uuid, first_ts, last_ts, date, tz_offset, engaged,
            cost, project, model, is_subagent, entrypoint, parent_session_uuid,
        ),
    )
    conn.commit()


# --------------------------------------------------------------- payload shape


def test_cols_matches_the_emitted_row_width() -> None:
    conn = _make_db()
    _insert(
        conn, "s1", session_uuid="s1",
        first_ts="2026-06-10T00:32:24.000Z", last_ts="2026-06-10T01:02:24.000Z",
        date="2026-06-10",
    )
    payload, unmatched = daywall.build_daywall_payload(conn, Window())
    assert unmatched == []
    assert len(payload["cols"]["S"]) == len(payload["S"][0])


def test_lookups_kinds_matches_dashboard_kind_names() -> None:
    conn = _make_db()
    _insert(
        conn, "s1", session_uuid="s1",
        first_ts="2026-06-10T00:32:24.000Z", last_ts="2026-06-10T01:02:24.000Z",
        date="2026-06-10",
    )
    payload, _ = daywall.build_daywall_payload(conn, Window())
    assert payload["lookups"]["kinds"] == KIND_NAMES


def test_days_lookup_is_sorted_ascending_with_no_gaps_in_index() -> None:
    conn = _make_db()
    for i, date in enumerate(["2026-06-12", "2026-06-10", "2026-06-11"]):
        _insert(
            conn, f"s{i}", session_uuid=f"s{i}",
            first_ts=f"{date}T00:00:00.000Z", last_ts=f"{date}T00:10:00.000Z",
            date=date,
        )
    payload, _ = daywall.build_daywall_payload(conn, Window())
    assert payload["days"] == sorted(payload["days"])
    assert payload["days"] == ["2026-06-10", "2026-06-11", "2026-06-12"]


def test_a_calendar_day_with_zero_sessions_still_gets_a_dayIdx_slot() -> None:
    """The browser side walks dayIdx+1, +2, ... to mean the next REAL
    calendar day when clipping a multi-day session. If a quiet day were
    simply absent from `days`, that walk would land on the wrong date the
    moment it crossed the gap."""
    conn = _make_db()
    _insert(
        conn, "early", session_uuid="early",
        first_ts="2026-06-10T00:00:00.000Z", last_ts="2026-06-10T00:10:00.000Z",
        date="2026-06-10",
    )
    _insert(
        conn, "late", session_uuid="late",
        first_ts="2026-06-13T00:00:00.000Z", last_ts="2026-06-13T00:10:00.000Z",
        date="2026-06-13",
    )
    payload, _ = daywall.build_daywall_payload(conn, Window())
    assert payload["days"] == ["2026-06-10", "2026-06-11", "2026-06-12", "2026-06-13"]
    day_col = payload["cols"]["S"].index("dayIdx")
    got = sorted(row[day_col] for row in payload["S"])
    assert got == [0, 3]


def test_a_session_is_classified_the_same_way_dashboard_does() -> None:
    conn = _make_db()
    _insert(
        conn, "mine", session_uuid="mine",
        first_ts="2026-06-10T00:00:00.000Z", last_ts="2026-06-10T00:10:00.000Z",
        date="2026-06-10", entrypoint="cli",
    )
    _insert(
        conn, "auto", session_uuid="auto",
        first_ts="2026-06-10T00:00:00.000Z", last_ts="2026-06-10T00:10:00.000Z",
        date="2026-06-10", entrypoint="sdk-cli",
    )
    payload, _ = daywall.build_daywall_payload(conn, Window())
    kind_col = payload["cols"]["S"].index("kind")
    kinds = {row[kind_col] for row in payload["S"]}
    assert KIND_NAMES[list(kinds)[0]] in (KIND_MINE, KIND_AUTOMATED)
    got = {KIND_NAMES[row[kind_col]] for row in payload["S"]}
    assert got == {KIND_MINE, KIND_AUTOMATED}


# ----------------------------------------------------------- day/second math


def test_start_seconds_is_local_midnight_offset_not_utc() -> None:
    """first_ts is UTC; tz_offset +1000 means local time is 10 hours ahead.
    00:32:24 UTC -> 10:32:24 local -> 37944 seconds after local midnight."""
    conn = _make_db()
    _insert(
        conn, "s1", session_uuid="s1",
        first_ts="2026-06-10T00:32:24.000Z", last_ts="2026-06-10T00:32:24.000Z",
        date="2026-06-10", tz_offset="+1000",
    )
    payload, _ = daywall.build_daywall_payload(conn, Window())
    start_col = payload["cols"]["S"].index("startSec")
    assert payload["S"][0][start_col] == 10 * 3600 + 32 * 60 + 24


def test_start_seconds_wraps_past_local_midnight_into_the_next_day() -> None:
    """22:00 UTC + 10h offset = 08:00 the NEXT local day. local_date must
    already reflect that (it is computed server-side by collect.py); this
    just checks startSec agrees with the stored local_date rather than
    silently producing a startSec >= 86400."""
    conn = _make_db()
    _insert(
        conn, "s1", session_uuid="s1",
        first_ts="2026-06-10T22:00:00.000Z", last_ts="2026-06-10T22:05:00.000Z",
        date="2026-06-11", tz_offset="+1000",
    )
    payload, _ = daywall.build_daywall_payload(conn, Window())
    start_col = payload["cols"]["S"].index("startSec")
    assert payload["S"][0][start_col] == 8 * 3600


def test_a_null_tz_offset_never_crashes_the_build() -> None:
    conn = _make_db()
    _insert(
        conn, "s1", session_uuid="s1",
        first_ts="2026-06-10T00:00:00.000Z", last_ts="2026-06-10T00:10:00.000Z",
        date="2026-06-10", tz_offset=None,
    )
    payload, _ = daywall.build_daywall_payload(conn, Window())
    assert len(payload["S"]) == 1


def test_dur_seconds_is_unclipped_even_across_many_days() -> None:
    """Clipping to day boundaries is a BROWSER-side concern (state can
    change), so the payload must carry the real, unclipped span. Real corpus
    fact: the longest session is 33.5 days."""
    conn = _make_db()
    _insert(
        conn, "s1", session_uuid="s1",
        first_ts="2026-01-01T00:00:00.000Z", last_ts="2026-02-03T00:00:00.000Z",
        date="2026-01-01",
    )
    payload, _ = daywall.build_daywall_payload(conn, Window())
    dur_col = payload["cols"]["S"].index("durSec")
    assert payload["S"][0][dur_col] == 33 * 86400


# ------------------------------------------------------------- parent edges


def test_a_subagent_links_to_its_real_parent() -> None:
    conn = _make_db()
    _insert(
        conn, "parent-1", session_uuid="uuid-a",
        first_ts="2026-06-10T00:00:00.000Z", last_ts="2026-06-10T01:00:00.000Z",
        date="2026-06-10", is_subagent=0,
    )
    _insert(
        conn, "agent:child-1", session_uuid="uuid-a",  # sub-agent carries the PARENT's uuid
        first_ts="2026-06-10T00:05:00.000Z", last_ts="2026-06-10T00:10:00.000Z",
        date="2026-06-10", is_subagent=1, parent_session_uuid="uuid-a",
    )
    payload, _ = daywall.build_daywall_payload(conn, Window())
    assert len(payload["P"]) == 1
    child_idx, parent_idx = payload["P"][0]
    kind_col = payload["cols"]["S"].index("kind")
    assert KIND_NAMES[payload["S"][parent_idx][kind_col]] != KIND_SUBAGENT
    assert KIND_NAMES[payload["S"][child_idx][kind_col]] == KIND_SUBAGENT


def test_the_naive_join_bug_does_not_reappear() -> None:
    """session_uuid is NOT unique: every sub-agent row carries its PARENT's
    session_uuid, not its own. A join on session_uuid alone (without also
    requiring is_subagent = 0 on the parent side) matches every sub-agent
    against every OTHER sub-agent sharing that uuid too. Real corpus measured
    2026-08-27: the naive join produced 35,471 spurious pairs. Three
    sub-agents sharing one parent must yield exactly 3 edges, never 3x3."""
    conn = _make_db()
    _insert(
        conn, "parent-1", session_uuid="uuid-a",
        first_ts="2026-06-10T00:00:00.000Z", last_ts="2026-06-10T01:00:00.000Z",
        date="2026-06-10", is_subagent=0,
    )
    for i in range(3):
        _insert(
            conn, f"agent:child-{i}", session_uuid="uuid-a",
            first_ts="2026-06-10T00:05:00.000Z", last_ts="2026-06-10T00:10:00.000Z",
            date="2026-06-10", is_subagent=1, parent_session_uuid="uuid-a",
        )
    payload, _ = daywall.build_daywall_payload(conn, Window())
    assert len(payload["P"]) == 3


def test_a_child_whose_parent_is_out_of_window_is_dropped_not_dangling() -> None:
    conn = _make_db()
    _insert(
        conn, "agent:orphan", session_uuid="uuid-missing",
        first_ts="2026-06-10T00:05:00.000Z", last_ts="2026-06-10T00:10:00.000Z",
        date="2026-06-10", is_subagent=1, parent_session_uuid="uuid-missing",
    )
    payload, _ = daywall.build_daywall_payload(conn, Window())
    assert payload["P"] == []


# --------------------------------------------------------------------- window


def test_since_until_bound_what_gets_embedded() -> None:
    conn = _make_db()
    _insert(
        conn, "early", session_uuid="early",
        first_ts="2026-06-01T00:00:00.000Z", last_ts="2026-06-01T00:10:00.000Z",
        date="2026-06-01",
    )
    _insert(
        conn, "late", session_uuid="late",
        first_ts="2026-06-20T00:00:00.000Z", last_ts="2026-06-20T00:10:00.000Z",
        date="2026-06-20",
    )
    payload, _ = daywall.build_daywall_payload(conn, Window(since="2026-06-15"))
    assert payload["days"] == ["2026-06-20"]


# --------------------------------------------------------------------- render


def test_render_raises_if_the_marker_is_missing(tmp_path, monkeypatch) -> None:
    bad_template = tmp_path / "bad.html"
    bad_template.write_text("<html>no marker here</html>", encoding="utf-8")
    monkeypatch.setattr(daywall, "TEMPLATE", bad_template)
    with pytest.raises(SystemExit):
        daywall.render({"S": []})


def test_render_substitutes_the_data_marker(tmp_path, monkeypatch) -> None:
    template = tmp_path / "t.html"
    template.write_text(
        "<script>const DATA = /*__CCSTATS_DATA_JSON__*/;</script>", encoding="utf-8"
    )
    monkeypatch.setattr(daywall, "TEMPLATE", template)
    html = daywall.render({"S": [], "days": []})
    assert '"days":[]' in html.replace(" ", "")


# ----------------------------------------------------------------------- CLI


def test_main_refuses_a_fenced_out_path() -> None:
    assert daywall.main(["--out", str(common.HOME / ".claude")]) == 2


def test_main_reports_missing_db(tmp_path) -> None:
    assert daywall.main(["--out", str(tmp_path)]) == 1


def test_main_writes_the_page_and_exits_zero(tmp_path) -> None:
    conn = _make_db()
    _insert(
        conn, "s1", session_uuid="s1",
        first_ts="2026-06-10T00:00:00.000Z", last_ts="2026-06-10T00:10:00.000Z",
        date="2026-06-10",
    )
    db_path = tmp_path / "sessions.sqlite"
    disk_conn = sqlite3.connect(db_path)
    disk_conn.executescript("\n".join(conn.iterdump()))
    disk_conn.close()

    exit_code = daywall.main(["--out", str(tmp_path)])
    assert exit_code == 0
    out_file = tmp_path / "claude-code-daywall.html"
    assert out_file.exists()
    assert "__CCSTATS_DATA_JSON__" not in out_file.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.building"))


def test_bad_filter_flag_exits_two(tmp_path) -> None:
    assert daywall.main(["--out", str(tmp_path), "--exclude"]) == 2


def test_bad_window_exits_two(tmp_path) -> None:
    assert daywall.main(["--out", str(tmp_path), "--since", "2026-6-8"]) == 2
