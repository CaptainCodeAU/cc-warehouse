"""The numbers quoted in prose, computed once and shared.

Both the workbook's README/Caveats sheets and DATA-GUIDE.md quote figures inside
sentences. Typing them by hand is what let the two drift apart on 2026-08-21:
the Caveats sheet carried literals frozen at the time the code was written while
the Overview sheet queried live, so one workbook stated two different session
counts. Every quoted number now comes from here.

Every figure is filtered to real sessions (`is_real = 1`) and to the `--since`
window, so a windowed workbook can never quote a whole-corpus number in its own
prose.
"""

from __future__ import annotations

import sqlite3
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import collect
from common import Window, read_meta

# The TEMP table holding the selected session keys. TEMP so it works on the
# read-only connection every ccstats command opens, and so it cannot touch the
# database file. Dropped and rebuilt per call, since one connection may be asked
# about several different selections in a row.
SELECTED = "_ccstats_selected"

# Figures that DELIBERATELY ignore both the window and any project selection,
# and why. Declared here rather than known by whoever happens to have read
# `_timezone_dst`, because a whole-corpus number sitting unlabelled inside a
# file called "filtered" is the same defect class as a `scope` string that
# describes a filter the query never applied.
#
# `export.py` copies this into the card, so a consumer is TOLD which figures
# are exceptions instead of having to notice that one of them never moves.
WHOLE_CORPUS_FACTS = {
    "dst_sessions_all": (
        "the whole corpus, always: this counts the sessions affected by a "
        "timezone bug that has been fixed, and a window excluding that period "
        "would render the sentence as 'the 0 sessions that were wrong'"
    ),
}

# Claude Code began emitting `output_tokens_details.thinking_tokens` at this
# version. Established by census, not assumption: 2.1.227 (2026-08-11) records
# none, 2.1.228 (2026-08-12) records it, and every later version does.
THINKING_FIRST_VERSION = "2.1.228"


def _one(conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> tuple[object, ...]:
    row = conn.execute(sql, params).fetchone()
    return row if row is not None else ()


def _core_counts(conn: sqlite3.Connection, win: str) -> dict[str, object]:
    """Totals across every real session in the window: counts, engagement,
    tokens, cost, project shape."""
    files_total, sessions_real, subagents = _one(
        conn, f"SELECT COUNT(*), SUM(is_real), SUM(is_subagent) FROM session WHERE 1=1{win}"
    )
    (
        prompts, tool_calls, turns, engaged_s, active_s, wall_s,
        tok_in, tok_out, tok_think, tok_cw, tok_cr, cost,
        repos, labels, worktree_sessions, active_days, span_lo, span_hi,
    ) = _one(
        conn,
        "SELECT SUM(n_user_prompts), SUM(n_tool_uses), SUM(n_assistant_turns),"
        " SUM(engaged_seconds), SUM(active_seconds), SUM(wall_seconds),"
        " SUM(tok_input), SUM(tok_output), SUM(tok_thinking),"
        " SUM(tok_cache_write), SUM(tok_cache_read), SUM(cost_usd),"
        " COUNT(DISTINCT repo_root), COUNT(DISTINCT project_label),"
        " SUM(is_worktree), COUNT(DISTINCT local_date), MIN(first_ts), MAX(last_ts)"
        f" FROM session WHERE is_real = 1{win}",
    )
    subs_real = _one(conn, f"SELECT SUM(is_subagent) FROM session WHERE is_real=1{win}")[0]
    return {
        "files_total": files_total,
        "sessions_real": sessions_real,
        "subagents": subagents,
        "subagents_real": subs_real,
        "prompts": prompts,
        "tool_calls": tool_calls,
        "turns": turns,
        "engaged_h": round((engaged_s or 0) / 3600.0, 1),
        "active_h": round((active_s or 0) / 3600.0, 1),
        "wall_h": round((wall_s or 0) / 3600.0, 1),
        "tok_in": tok_in,
        "tok_out": tok_out,
        "tok_think": tok_think,
        "tok_cw": tok_cw,
        "tok_cr": tok_cr,
        "cost": round(cost or 0, 2),
        "repos": repos,
        "labels": labels,
        "worktree_sessions": worktree_sessions,
        "active_days": active_days,
        "span_lo": str(span_lo)[:10],
        "span_hi": str(span_hi)[:10],
    }


def _recorded_zone(conn: sqlite3.Connection) -> object:
    """The timezone the COLLECTOR used, read from the database it wrote.

    Not this process's `collect._LOCAL_TZ`, which is detected at import from
    config and environment. Which calendar day a session lands on depends on
    the zone, so recomputing a subset with a different one from the stored table
    would bucket the same sessions into different days with nothing to show for
    it. The collector records what it used in `meta.local_timezone`; that is the
    answer, and it travels with the data.

    An unreadable or unknown zone falls back to this process's own rather than
    failing: a card built in the wrong calendar is recoverable and visible in
    `scope`, a crashed daily job is neither.
    """
    name = read_meta(conn).get("local_timezone", "")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return collect._LOCAL_TZ


def _overlap_days(
    conn: sqlite3.Connection, chosen: str, window: Window, *, filtered: bool
) -> list[tuple[object, ...]]:
    """The `overlap_day` rows for this selection.

    With NO project selection this reads the stored table, which `collect.py`
    already built over the whole corpus - the cheap path, and the one that keeps
    an unfiltered card byte-for-byte what it always was.

    With a selection it RECOMPUTES, because `overlap_day` is pre-aggregated per
    day across every project and has no `project_label` column: there is nothing
    in it to filter on. `collect.overlap_rows` is the same function that built
    the table, so the two cannot disagree about the day-clipping.

    Takes the `Window` OBJECT, not its rendered SQL. The first version sniffed
    the predicate string to decide which branch to take and parsed the dates
    back out of a WHERE clause it had just produced - a round trip through SQL
    for two values the caller was already holding.

    THE DATE WINDOW IS APPLIED TO THE DAY ROWS, NEVER TO THE SESSIONS, and the
    parameter is `chosen` (the project predicate alone) rather than the full
    `win` for exactly that reason. `session.local_date` is a session's START
    day, so selecting sessions by it drops one that began before the window and
    ran into it - along with every clipped slice it contributed to days that ARE
    in the window. The stored path never had this problem because it filters
    already-bucketed days. Measured when this shipped that way: 4 sessions,
    335.6 summed hours and 13.3 clock hours missing from a real card.
    """
    if not filtered:
        return conn.execute(f"SELECT * FROM overlap_day{window.overlap_where}").fetchall()
    pairs = conn.execute(
        "SELECT first_ts, last_ts FROM session WHERE is_real = 1"
        f" AND first_ts IS NOT NULL AND last_ts IS NOT NULL{chosen}"
    ).fetchall()
    lo, hi = window.since, window.until
    return [
        r
        for r in collect.overlap_rows(pairs, _recorded_zone(conn))
        if (not lo or str(r[0]) >= lo) and (not hi or str(r[0]) <= hi)
    ]


def _hours_and_overlap(
    conn: sqlite3.Connection, days: list[tuple[object, ...]], keys: str
) -> dict[str, object]:
    """Clock-time figures over the selected days (concurrency, not per-session sums)."""
    # Column order is `overlap_day`'s own: date, active, started, summed, elapsed, ...
    elapsed = [float(r[4] or 0) for r in days]
    summed_h = round(sum(float(r[3] or 0) for r in days), 1)
    elapsed_h = round(sum(elapsed), 1)
    mean_elapsed = round(sum(elapsed) / len(elapsed), 1) if elapsed else 0
    max_elapsed = round(max(elapsed), 1) if elapsed else 0
    over24 = sum(1 for e in elapsed if e > 24.001)
    turn_rows = _one(conn, f"SELECT COUNT(*) FROM turn{keys}")[0]
    tool_rows = _one(conn, f"SELECT COUNT(*) FROM tool_call{keys}")[0]
    return {
        "elapsed_h": elapsed_h,
        "summed_h": summed_h,
        "mean_elapsed": mean_elapsed,
        "max_elapsed": max_elapsed,
        "days_over_24h": over24,
        "turn_rows": turn_rows,
        "tool_rows": tool_rows,
    }


def _month_boundaries(conn: sqlite3.Connection, win: str) -> dict[str, object]:
    """The first and last calendar month in the window, both partial, plus when
    thinking-token recording began. A bar chart shows a short bar at each end
    for reasons that are not a change in usage."""
    last_month, last_day, last_month_days = _one(
        conn,
        f"SELECT substr(MAX(local_date),1,7), MAX(local_date),"
        f" (SELECT COUNT(DISTINCT local_date) FROM session WHERE is_real=1{win}"
        f"  AND substr(local_date,1,7) = substr((SELECT MAX(local_date)"
        f"  FROM session WHERE is_real=1{win}),1,7))"
        f" FROM session WHERE is_real = 1{win}",
    )
    first_month, first_day, first_month_days = _one(
        conn,
        f"SELECT substr(MIN(local_date),1,7), MIN(local_date),"
        f" (SELECT COUNT(DISTINCT local_date) FROM session WHERE is_real=1{win}"
        f"  AND substr(local_date,1,7) = substr((SELECT MIN(local_date)"
        f"  FROM session WHERE is_real=1{win}),1,7))"
        f" FROM session WHERE is_real = 1{win}",
    )
    thinking_from = _one(
        conn, f"SELECT MIN(local_date) FROM session WHERE is_real=1 AND tok_thinking > 0{win}"
    )[0]
    return {
        "first_month": first_month,
        "first_day": first_day,
        "first_month_days": first_month_days,
        "last_month": last_month,
        "last_day": last_day,
        "last_month_days": last_month_days,
        "thinking_from": thinking_from,
        "thinking_version": THINKING_FIRST_VERSION,
    }


def _busiest_day(
    conn: sqlite3.Connection, win: str, days: list[tuple[object, ...]]
) -> dict[str, object]:
    """The single busiest day in the window, and the selection's concurrency peak.

    THE EMPTY CASE IS REAL NOW. `GROUP BY ... LIMIT 1` returns NO ROW when the
    selection matches nothing, and this used to unpack that into two names and
    raise. It could not happen while the only filter was a date window over a
    corpus that always had sessions in it; a project selection that matches
    nothing is an ordinary thing for an operator to do, so it must report zero
    rather than crash.
    """
    busiest = _one(
        conn,
        f"SELECT local_date, COUNT(*) FROM session WHERE is_real=1{win}"
        " GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
    )
    busiest_day, busiest_n = busiest if busiest else (None, 0)
    # EARLIEST day attaining the peak, not the latest. This replaced
    # `SELECT MAX(max_concurrent), local_date`, whose bare-MAX idiom returns the
    # companion column of the first row reaching the max - and `overlap_day` is
    # keyed by date, so that was the earliest. A plain `max` over `(peak, date)`
    # tuples breaks the tie the other way and silently moved the answer on the
    # UNFILTERED path, which three other commands read.
    ranked = [(int(r[6] or 0), str(r[0])) for r in days]
    peak_c = max((c for c, _ in ranked), default=None)
    peak_day = next((d for c, d in sorted(ranked, key=lambda x: x[1]) if c == peak_c), None)
    busiest_engaged = (
        _one(
            conn,
            f"SELECT ROUND(SUM(engaged_seconds)/3600.0,1) FROM session WHERE is_real=1{win}"
            " AND local_date = ?",
            (busiest_day,),
        )[0]
        if busiest_day
        else None
    )
    busiest_elapsed = next(
        (round(float(r[4] or 0), 3) for r in days if str(r[0]) == str(busiest_day)), None
    )
    return {
        "busiest_day": busiest_day,
        "busiest_n": busiest_n,
        "busiest_engaged": busiest_engaged,
        "busiest_elapsed": busiest_elapsed,
        "peak_concurrent": peak_c,
        "peak_concurrent_day": peak_day,
    }


def _project_labels(conn: sqlite3.Connection, win: str) -> dict[str, object]:
    """How project_label (a working directory) diverges from repo_root (a
    repository) - worktrees and subdirectories both mint extra labels."""
    multi_repos, extra_labels = _one(
        conn,
        "SELECT COUNT(*), COALESCE(SUM(n - 1), 0) FROM (SELECT COUNT(DISTINCT project_label) n"
        f" FROM session WHERE is_real = 1{win} GROUP BY repo_root HAVING n > 1)",
    )
    wt_labels = _one(
        conn,
        f"SELECT COUNT(DISTINCT project_label) FROM session WHERE is_real=1 AND is_worktree=1{win}",
    )[0]
    return {
        "multi_label_repos": multi_repos,
        "extra_labels": extra_labels,
        "worktree_labels": wt_labels,
    }


def _timezone_dst(conn: sqlite3.Connection, win: str) -> dict[str, object]:
    """UTC-offset distribution and the DST-fix correction figure."""
    offsets = conn.execute(
        "SELECT tz_offset, COUNT(*) FROM session WHERE is_real = 1"
        f" AND tz_offset IS NOT NULL{win} GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    # Deliberately NOT windowed. Notes describing a bug that was fixed have to
    # quote the whole corpus, or a window that excludes the affected period
    # renders the sentence as "the 0 sessions that were wrong", which is both
    # meaningless and reads as a denial that anything was wrong.
    dst_all = _one(
        conn, "SELECT COUNT(*) FROM session WHERE is_real = 1 AND tz_offset = '+1100'"
    )[0]
    return {
        "offsets": offsets,
        "dst_sessions": next((n for o, n in offsets if o == "+1100"), 0),
        "dst_sessions_all": dst_all,
    }


def _derived_ratios(core: dict[str, object]) -> dict[str, object]:
    """Small percentages computed from other facts rather than a fresh query."""
    files_total = core["files_total"]
    sessions_real = core["sessions_real"]
    tok_out = core["tok_out"]
    tok_cr = core["tok_cr"]
    shells = (files_total or 0) - (sessions_real or 0)
    shell_pct = round(100.0 * shells / files_total, 1) if files_total else 0.0
    inflate = round(files_total / sessions_real, 1) if sessions_real else 0.0
    cr_ratio = round(tok_cr / tok_out) if tok_out else 0
    return {"shell_pct": shell_pct, "inflate": inflate, "cr_ratio": cr_ratio}


def _select_projects(conn: sqlite3.Connection, projects: list[str]) -> str:
    """Load the selected sessions into a TEMP table and return the predicate.

    A TEMP TABLE rather than an `IN (?, ?, ...)` list threaded through every
    query. `win` is interpolated into as many as four places in a single
    statement here, so carrying a parameter tuple alongside it would mean
    getting the ordering right at 15 call sites; a table turns the predicate
    back into a constant string with no parameters, which is exactly the shape
    the existing `win`/`keys`/`dwin` plumbing already expects.

    The labels themselves ARE bound. They come off disk as folder names, so
    interpolating them would make a project called `it's` a syntax error and
    anything worse a real one.
    """
    conn.execute(f"DROP TABLE IF EXISTS temp.{SELECTED}")
    conn.execute(f"CREATE TEMP TABLE {SELECTED} (key TEXT PRIMARY KEY)")
    if projects:
        holes = ", ".join("?" for _ in projects)
        conn.execute(
            f"INSERT OR IGNORE INTO {SELECTED} (key)"
            f" SELECT key FROM session WHERE project_label IN ({holes})",
            tuple(projects),
        )
    return f" AND key IN (SELECT key FROM {SELECTED})"


def compute(
    conn: sqlite3.Connection,
    window: Window | None = None,
    projects: list[str] | None = None,
) -> dict[str, object]:
    """Every number any prose string needs, honouring the window and selection.

    The window forms come from `common.Window`, which is the ONE place they are
    derived. They used to be rebuilt here and again in build_workbook.py, two
    implementations of one filter kept in step by hand.

    `projects` is the list of `project_label`s to count, or None for all of
    them. `None` and `[]` are DIFFERENT: `None` means "no project filter", `[]`
    means "a filter that matched nothing", and an operator whose patterns
    matched nothing must get zero rather than silently get the whole corpus.
    """
    window = window or Window()
    since = window.since
    win = window.and_clause
    keys = f" WHERE 1=1{window.child_keys}" if window.active else ""
    filtered = projects is not None
    chosen = ""

    if projects is not None:
        chosen = _select_projects(conn, projects)
        win += chosen
        # The child tables reach `session` through a subquery, so the selection
        # has to go INSIDE it or turn/tool_call counts quietly stay corpus-wide.
        # `Window` builds that form, here as everywhere else: rebuilding the
        # literal here would be one form constructed two ways.
        keys = f" WHERE 1=1{window.child_keys_and(chosen)}"

    core = _core_counts(conn, win)
    facts: dict[str, object] = {"since": since, **core}
    # Computed ONCE and shared: the filtered path walks every selected session
    # through the clip-and-merge, and both helpers below want the same answer.
    days = _overlap_days(conn, chosen, window, filtered=filtered)
    facts.update(_hours_and_overlap(conn, days, keys))
    facts.update(_month_boundaries(conn, win))
    facts.update(_busiest_day(conn, win, days))
    facts.update(_project_labels(conn, win))
    facts.update(_timezone_dst(conn, win))
    facts.update(_derived_ratios(core))
    return facts
