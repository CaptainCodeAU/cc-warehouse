"""The elapsed-hours defect: a day cannot hold more than 24 hours.

Session intervals used to be attributed WHOLE to their start date and never
clipped, so one session running 2026-06-01 to 2026-07-04 put 804 hours onto a
single day. 73 of 153 days read over 24 h and 87.6% of the corpus total sat on
physically impossible days. Found by a reviewer, not by this code.
"""

from __future__ import annotations

import sqlite3

import collect
import pytest
from common import DAY_SECONDS


def make_db(rows: list[tuple[str, str, str]]) -> sqlite3.Connection:
    """A conn holding just what build_overlap reads: (local_date, first, last)."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE session (local_date TEXT, first_ts TEXT, last_ts TEXT, is_real INT)"
    )
    conn.executemany(
        "INSERT INTO session VALUES (?,?,?,1)", rows
    )
    return conn


def days(conn: sqlite3.Connection) -> dict[str, tuple[float, float, int]]:
    return {
        r[0]: (r[4], r[3], r[6])  # elapsed, summed, max_concurrent
        for r in conn.execute("SELECT * FROM overlap_day").fetchall()
    }


def test_a_session_spanning_four_days_does_not_put_96_hours_on_one_day() -> None:
    conn = make_db([("2026-06-01", "2026-06-01T00:00:00Z", "2026-06-05T00:00:00Z")])
    collect.build_overlap(conn)
    result = days(conn)
    assert len(result) >= 4, "the span must be spread across the days it touches"
    for date, (elapsed, _summed, _peak) in result.items():
        assert elapsed <= 24.001, f"{date} reports {elapsed} h in a 24 h day"


def test_no_day_can_ever_exceed_twenty_four_hours() -> None:
    conn = make_db(
        [
            ("2026-06-01", "2026-06-01T00:00:00Z", "2026-07-04T16:00:00Z"),  # the real one
            ("2026-06-01", "2026-06-01T03:00:00Z", "2026-06-08T06:00:00Z"),
            ("2026-06-01", "2026-06-01T04:00:00Z", "2026-06-02T08:00:00Z"),
        ]
    )
    collect.build_overlap(conn)
    worst = max(v[0] for v in days(conn).values())
    assert worst <= 24.001, f"worst day is {worst} h"


def test_overlapping_sessions_are_merged_not_added() -> None:
    """Two sessions covering the same two hours are two hours of clock time."""
    conn = make_db(
        [
            ("2026-06-10", "2026-06-10T01:00:00Z", "2026-06-10T03:00:00Z"),
            ("2026-06-10", "2026-06-10T01:30:00Z", "2026-06-10T03:00:00Z"),
        ]
    )
    collect.build_overlap(conn)
    elapsed, summed, peak = days(conn)["2026-06-10"]
    assert elapsed == pytest.approx(2.0, abs=0.01), "merged clock time"
    assert summed == pytest.approx(3.5, abs=0.01), "summed session time"
    assert peak == 2


def test_disjoint_sessions_are_not_merged() -> None:
    conn = make_db(
        [
            ("2026-06-10", "2026-06-10T01:00:00Z", "2026-06-10T02:00:00Z"),
            ("2026-06-10", "2026-06-10T05:00:00Z", "2026-06-10T06:00:00Z"),
        ]
    )
    collect.build_overlap(conn)
    elapsed, summed, peak = days(conn)["2026-06-10"]
    assert elapsed == pytest.approx(2.0, abs=0.01)
    assert summed == pytest.approx(2.0, abs=0.01)
    assert peak == 1, "never simultaneous"


def test_sessions_started_and_sessions_active_are_different_counts() -> None:
    """A session started yesterday is ACTIVE today but not STARTED today."""
    conn = make_db([("2026-06-10", "2026-06-10T22:00:00Z", "2026-06-12T02:00:00Z")])
    collect.build_overlap(conn)
    rows = {
        r[0]: (r[1], r[2])
        for r in conn.execute(
            "SELECT local_date, sessions_active, sessions_started FROM overlap_day"
        )
    }
    assert len(rows) >= 2
    started = sum(v[1] for v in rows.values())
    assert started == 1, "counted as started exactly once"
    assert all(v[0] >= 1 for v in rows.values()), "active on every day it touches"


def test_a_zero_length_session_does_not_crash_or_divide_by_zero() -> None:
    conn = make_db([("2026-06-10", "2026-06-10T01:00:00Z", "2026-06-10T01:00:00Z")])
    collect.build_overlap(conn)
    elapsed, summed, _peak = days(conn)["2026-06-10"]
    assert elapsed == 0.0
    assert summed == 0.0


def test_a_backwards_session_is_skipped_rather_than_producing_negative_time() -> None:
    conn = make_db([("2026-06-10", "2026-06-10T05:00:00Z", "2026-06-10T01:00:00Z")])
    collect.build_overlap(conn)
    assert conn.execute("SELECT COUNT(*) FROM overlap_day").fetchone()[0] == 0


def test_the_day_constant_is_what_the_clip_uses() -> None:
    assert DAY_SECONDS == 86400.0
