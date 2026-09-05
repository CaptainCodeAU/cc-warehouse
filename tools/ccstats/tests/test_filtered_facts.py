"""`facts.compute` narrowed to a date window AND a set of projects.

The operator's actual requirement, clarified after the first build shipped
whole-corpus numbers: the stats for a start date through now, for their selected
projects only, as one combined total, in a file some other program renders.

WHY THIS FILE EXISTS SEPARATELY FROM `test_exports.py`. The dangerous failure
here is not a crash, it is a figure that quietly ignores the filter and reports
the whole corpus while sitting in a file labelled "filtered". Every test below
therefore compares a FILTERED figure against an UNFILTERED one and demands they
differ, rather than asserting a filtered figure equals a number typed here - a
hand-typed expected value cannot tell "correctly filtered" from "filter silently
dropped" when the fixture is small.
"""

from __future__ import annotations

import sqlite3
from zoneinfo import ZoneInfo

import collect
import facts
import pytest
from common import Window
from test_exports import SESSION_DEFAULTS


def make_db(rows: list[tuple[str, str, str]]) -> sqlite3.Connection:
    """`(key, local_date, project_label)` triples in the real session schema.

    A row may carry two extra members, `(first_ts, last_ts)`, to make a session
    that SPANS days. The fixture had none for its first version, and that is
    precisely why its tests all passed while `elapsed_h` was losing 335 real
    hours: every session began and ended inside one day, so a bug that drops
    sessions by their START date could not show.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(collect.session_ddl())
    conn.execute(
        "CREATE TABLE turn ("
        " session_key TEXT, ordinal INTEGER, ts TEXT, model TEXT, effort TEXT,"
        " service_tier TEXT, speed TEXT, stop_reason TEXT, input_tokens INTEGER,"
        " output_tokens INTEGER, cache_write_5m INTEGER, cache_write_1h INTEGER,"
        " cache_read INTEGER, thinking_tokens INTEGER, web_search_requests INTEGER,"
        " web_fetch_requests INTEGER, cost_usd REAL)"
    )
    conn.execute(
        "CREATE TABLE tool_call (session_key TEXT, ts TEXT, tool_name TEXT, is_error INTEGER)"
    )
    conn.execute("CREATE TABLE attribution (session_key TEXT, kind TEXT, name TEXT, count INTEGER)")
    conn.execute(
        "CREATE TABLE overlap_day ("
        " local_date TEXT PRIMARY KEY, sessions_active INTEGER,"
        " sessions_started INTEGER, summed_hours REAL, elapsed_hours REAL,"
        " concurrency REAL, max_concurrent INTEGER)"
    )
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    # UTC, so which calendar day a session lands on is the same on every
    # machine that runs this suite. `facts._recorded_zone` reads this key, so
    # the fixture and the code under test agree by construction rather than by
    # both happening to sit in Australia/Melbourne.
    conn.execute("INSERT INTO meta VALUES ('local_timezone', 'UTC')")

    for entry in rows:
        key, day, label = entry[:3]
        first, last = (
            entry[3:5] if len(entry) >= 5 else (f"{day}T09:00:00+00:00", f"{day}T10:00:00+00:00")
        )
        row = dict(SESSION_DEFAULTS)
        row.update(
            key=key, local_date=day, local_hour=9, project_label=label,
            repo_root=f"/repo/{label}",
            first_ts=first, last_ts=last,
            source_path=f"/src/{key}.jsonl",
        )
        names = ", ".join(row)
        holes = ", ".join("?" for _ in row)
        conn.execute(f"INSERT INTO session ({names}) VALUES ({holes})", tuple(row.values()))
        conn.execute(
            "INSERT INTO turn VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, 1, f"{day}T09:01:00+00:00", "claude-opus-5", None, "standard",
             "standard", "end_turn", 100, 200, 300, 0, 400, 50, 0, 0, 1.5),
        )
        conn.execute(
            "INSERT INTO tool_call VALUES (?,?,?,?)",
            (key, f"{day}T09:02:00+00:00", "Bash", 0),
        )
    # Built with the SAME function collect.py uses, not with plausible-looking
    # literals. An unfiltered call reads this stored table while a filtered one
    # recomputes, so hand-written rows would have the tests comparing two
    # different arithmetics and calling the difference a filter.
    conn.executemany(
        "INSERT INTO overlap_day VALUES (?,?,?,?,?,?,?)",
        collect.overlap_rows(
            conn.execute("SELECT first_ts, last_ts FROM session WHERE is_real = 1").fetchall(),
            ZoneInfo("UTC"),
        ),
    )
    conn.commit()
    return conn


# 2026-07-01 deliberately carries THREE sessions and 2026-07-02 two, so
# "busiest day" has a single unambiguous answer. The first version of this
# fixture gave both days two, and `ORDER BY count DESC LIMIT 1` then picked one
# arbitrarily - a test that would have passed or failed on sqlite's whim.
ROWS = [
    ("a1", "2026-05-01", "alpha"),
    ("a2", "2026-07-01", "alpha"),
    ("a3", "2026-07-01", "alpha"),
    ("b1", "2026-07-01", "beta"),
    ("b2", "2026-07-02", "beta"),
    ("g1", "2026-07-02", "gamma"),
]


@pytest.fixture
def conn() -> sqlite3.Connection:
    return make_db(ROWS)


def test_without_a_selection_nothing_changes(conn: sqlite3.Connection) -> None:
    """The control. `projects=None` must be the behaviour the three existing
    callers (`build_workbook`, `make_docs`, `check_consistency`) already get."""
    assert facts.compute(conn, Window())["sessions_real"] == 6


def test_a_selection_narrows_the_session_count(conn: sqlite3.Connection) -> None:
    assert facts.compute(conn, Window(), projects=["alpha"])["sessions_real"] == 3


def test_a_selection_of_everything_matches_no_selection(conn: sqlite3.Connection) -> None:
    """Naming every project must equal naming none - if it does not, the
    predicate is dropping rows for some reason other than the filter."""
    everything = facts.compute(conn, Window(), projects=["alpha", "beta", "gamma"])
    assert everything["sessions_real"] == facts.compute(conn, Window())["sessions_real"]


def test_an_empty_selection_selects_nothing(conn: sqlite3.Connection) -> None:
    """`[]` is not `None`. An operator whose patterns matched no project must
    get zero, not silently get the whole corpus."""
    assert facts.compute(conn, Window(), projects=[])["sessions_real"] in (0, None)


def test_the_window_and_the_selection_both_apply(conn: sqlite3.Connection) -> None:
    """Two filters, and both must bite: alpha has three sessions, one of them
    before the window opens."""
    assert facts.compute(conn, Window("2026-06-08"), projects=["alpha"])["sessions_real"] == 2


# --------------------------------------------------------------- no free passes
# One test per source table. A figure drawn from a table the predicate forgot
# would otherwise sit in a "filtered" file reporting the whole corpus - the
# exact defect class this whole file exists to make impossible.


def test_turn_derived_figures_are_filtered(conn: sqlite3.Connection) -> None:
    whole = facts.compute(conn, Window())["turn_rows"]
    part = facts.compute(conn, Window(), projects=["alpha"])["turn_rows"]
    assert part < whole, "turn rows ignored the project selection"


def test_tool_call_derived_figures_are_filtered(conn: sqlite3.Connection) -> None:
    whole = facts.compute(conn, Window())["tool_rows"]
    part = facts.compute(conn, Window(), projects=["alpha"])["tool_rows"]
    assert part < whole, "tool_call rows ignored the project selection"


def test_cost_and_tokens_are_filtered(conn: sqlite3.Connection) -> None:
    whole = facts.compute(conn, Window())
    part = facts.compute(conn, Window(), projects=["alpha"])
    assert part["cost"] < whole["cost"]
    assert part["tok_out"] < whole["tok_out"]
    assert part["engaged_h"] < whole["engaged_h"]


def test_overlap_derived_figures_are_filtered(conn: sqlite3.Connection) -> None:
    """THE ONE THAT COULD NOT BE DONE WITHOUT THE EXTRACTION.

    `overlap_day` is pre-aggregated per day across every project and has no
    `project_label` column, so these eight figures used to be unfilterable.
    They are now recomputed from the selected sessions through
    `collect.overlap_rows` - the same function that builds the table.
    """
    whole = facts.compute(conn, Window())
    part = facts.compute(conn, Window(), projects=["alpha"])
    assert part["elapsed_h"] < whole["elapsed_h"], "clock hours ignored the selection"
    assert part["summed_h"] < whole["summed_h"]


def test_the_busiest_day_is_the_busiest_selected_day(conn: sqlite3.Connection) -> None:
    """gamma ran only on 2026-07-02, so selecting it must move the busiest day
    off 2026-07-01, which is the busiest day of the whole corpus."""
    assert facts.compute(conn, Window())["busiest_day"] == "2026-07-01"
    assert facts.compute(conn, Window(), projects=["gamma"])["busiest_day"] == "2026-07-02"


def test_project_label_counts_are_filtered(conn: sqlite3.Connection) -> None:
    assert facts.compute(conn, Window(), projects=["alpha"])["labels"] == 1
    assert facts.compute(conn, Window())["labels"] == 3


def test_month_boundaries_are_filtered(conn: sqlite3.Connection) -> None:
    """alpha's earliest session is 2026-05-01; beta's is 2026-07-01."""
    assert facts.compute(conn, Window(), projects=["alpha"])["first_day"] == "2026-05-01"
    assert facts.compute(conn, Window(), projects=["beta"])["first_day"] == "2026-07-01"


def test_a_selection_leaves_no_temporary_table_behind(conn: sqlite3.Connection) -> None:
    """The filter is implemented with a TEMP table of selected keys. A second
    call must not trip over the first one's leftovers."""
    facts.compute(conn, Window(), projects=["alpha"])
    facts.compute(conn, Window(), projects=["beta"])
    assert facts.compute(conn, Window(), projects=["alpha"])["sessions_real"] == 3


def test_a_project_name_with_a_quote_does_not_break_the_query(conn: sqlite3.Connection) -> None:
    """Project labels come off disk. They are bound as parameters, never
    interpolated, so a name like `it's` is data rather than syntax."""
    assert facts.compute(conn, Window(), projects=["it's-a-name"])["sessions_real"] in (0, None)


# ------------------------------------------------- the declared exceptions
# One figure in `facts.compute` deliberately ignores both filters. That is
# allowed; being UNLABELLED is not. These pin the exception list itself, so a
# future unfiltered figure has to be declared rather than quietly added.


def test_the_declared_exception_really_does_ignore_the_selection(
    conn: sqlite3.Connection,
) -> None:
    """If this ever starts moving, the declaration is stale and must go."""
    whole = facts.compute(conn, Window())
    part = facts.compute(conn, Window(), projects=["alpha"])
    for name in facts.WHOLE_CORPUS_FACTS:
        assert whole[name] == part[name], f"{name} is filtered now; drop its declaration"


def test_every_declared_exception_is_a_real_fact_key(conn: sqlite3.Connection) -> None:
    """A declaration naming a key that no longer exists would be a warning
    about nothing, printed into every card forever."""
    produced = facts.compute(conn, Window())
    for name in facts.WHOLE_CORPUS_FACTS:
        assert name in produced, f"{name} is declared but no longer produced"


def test_each_exception_says_why(conn: sqlite3.Connection) -> None:
    """The card carries these verbatim to a reader who has no access to this
    repository, so a bare key name would tell them nothing."""
    for name, reason in facts.WHOLE_CORPUS_FACTS.items():
        assert len(reason) > 40, f"{name}'s reason is too short to be useful"


# ------------------------------------------------- sessions that cross a day
# The regression that shipped: `_overlap_days` recomputed from sessions chosen
# by `local_date`, which is the session's START day, while the stored path it
# was replacing filtered the pre-bucketed DAY rows. A session beginning before
# the window and running into it was therefore dropped whole, taking every
# clipped slice it contributed to in-window days with it. Measured on the real
# corpus at the time: 4 such sessions, 335.6 summed hours, silently missing.

SPANNING = [
    # starts the day BEFORE the window opens, runs six hours into it
    ("x1", "2026-06-30", "alpha", "2026-06-30T21:00:00+00:00", "2026-07-01T03:00:00+00:00"),
    ("x2", "2026-07-02", "alpha", "2026-07-02T09:00:00+00:00", "2026-07-02T10:00:00+00:00"),
    ("x3", "2026-07-02", "beta", "2026-07-02T11:00:00+00:00", "2026-07-02T12:00:00+00:00"),
]


@pytest.fixture
def spanning() -> sqlite3.Connection:
    return make_db(SPANNING)


def test_a_session_that_started_before_the_window_still_counts_inside_it(
    spanning: sqlite3.Connection,
) -> None:
    """Its three in-window hours belong to 2026-07-01 and must not vanish."""
    window = Window("2026-07-01")
    whole = facts.compute(spanning, window)["elapsed_h"]
    part = facts.compute(spanning, window, projects=["alpha", "beta"])["elapsed_h"]
    assert part == whole, "the recompute dropped a session by its start date"


def test_naming_every_project_equals_naming_none_for_clock_time(
    spanning: sqlite3.Connection,
) -> None:
    """The strongest available check on the whole filter: a selection of
    everything must be a no-op. `sessions_real` alone could not catch this -
    the dropped session was outside the window by start date either way."""
    window = Window("2026-07-01")
    everything = sorted({label for _, _, label, *_ in SPANNING})
    whole = facts.compute(spanning, window)
    part = facts.compute(spanning, window, projects=everything)
    for key in ("elapsed_h", "summed_h", "mean_elapsed", "max_elapsed", "sessions_real"):
        assert part[key] == whole[key], f"{key} differs when the selection is everything"


def test_the_peak_day_tie_is_broken_the_same_way_it_always_was(
    spanning: sqlite3.Connection,
) -> None:
    """Two days peaking equally must resolve to the EARLIER one.

    Not an arbitrary choice: `SELECT MAX(max_concurrent), local_date` returned
    the companion column of the first row reaching the max, and `overlap_day`
    is keyed by date, so that was the earliest. Replacing the query with a
    Python `max` over `(peak, date)` tuples silently flipped it to the latest.
    """
    whole = facts.compute(spanning, Window())
    part = facts.compute(spanning, Window(), projects=["alpha", "beta"])
    assert part["peak_concurrent_day"] == whole["peak_concurrent_day"]
