"""`--until`, added 2026-08-21 as the dashboard's date-range prerequisite.

`Window` only had `since` before this. These tests cover the `until` half and
the combined since+until case; `test_regressions.py` bug 2 already covers the
since-only forms and is left alone.
"""

from __future__ import annotations

import sqlite3

import pytest
from common import BadWindow, Window, parse_until


@pytest.mark.parametrize("bad", ["2026-6-8", "2026-6-08", "garbage", "26-06-08", ""])
def test_unpadded_or_malformed_until_is_refused(bad: str) -> None:
    with pytest.raises(BadWindow):
        parse_until(["--until", bad])


def test_impossible_calendar_date_is_refused() -> None:
    with pytest.raises(BadWindow):
        parse_until(["--until", "2026-13-99"])


def test_until_without_a_value_is_refused() -> None:
    with pytest.raises(BadWindow):
        parse_until(["--until"])


def test_a_real_date_is_accepted_and_absence_means_no_upper_bound() -> None:
    assert parse_until(["--until", "2026-08-21"]) == "2026-08-21"
    assert parse_until([]) == ""


def test_until_alone_bounds_only_the_top() -> None:
    w = Window(until="2026-08-21")
    assert w.session == "is_real = 1 AND local_date <= '2026-08-21'"
    assert w.session_as_s == "s.is_real = 1 AND s.local_date <= '2026-08-21'"
    assert w.overlap_where == " WHERE local_date <= '2026-08-21'"
    assert w.active


def test_since_and_until_together_are_anded() -> None:
    w = Window(since="2026-06-08", until="2026-08-21")
    assert w.session == "is_real = 1 AND local_date >= '2026-06-08' AND local_date <= '2026-08-21'"
    assert (
        w.session_as_s
        == "s.is_real = 1 AND s.local_date >= '2026-06-08' AND s.local_date <= '2026-08-21'"
    )
    assert w.and_clause == " AND local_date >= '2026-06-08' AND local_date <= '2026-08-21'"
    assert "session_key IN" in w.child_keys
    assert w.session in w.child_keys
    assert w.describe() == "2026-06-08 to 2026-08-21"


def test_until_alone_describes_as_through() -> None:
    assert Window(until="2026-08-21").describe() == "through 2026-08-21"


def test_neither_bound_is_unchanged_from_before() -> None:
    w = Window()
    assert w.session == "is_real = 1"
    assert w.session_as_s == "s.is_real = 1"
    assert w.overlap_where == ""
    assert w.child_keys == ""
    assert w.and_clause == ""
    assert not w.active
    assert w.describe() == "full range"


def test_until_narrows_a_real_table() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE session (key TEXT, is_real INT, local_date TEXT)")
    conn.executemany(
        "INSERT INTO session VALUES (?,?,?)",
        [
            ("a", 1, "2026-06-07"),
            ("b", 1, "2026-06-08"),
            ("c", 1, "2026-07-01"),
            ("d", 0, "2026-06-07"),
        ],
    )
    w = Window(since="2026-06-08", until="2026-06-30")
    sessions = conn.execute(f"SELECT COUNT(*) FROM session WHERE {w.session}").fetchone()[0]
    assert sessions == 1, "b only: c is past --until, a is before --since, d is not real"
