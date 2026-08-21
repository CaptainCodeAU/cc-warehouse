#!/usr/bin/env python3
"""Build `claude-code-stats.xlsx`: a pre-aggregated workbook for charting.

Reads `sessions.sqlite` (produced by collect.py) READ-ONLY and writes ONE file:
`claude-code-stats.xlsx`, both in the resolved output root (`~/.cc-warehouse/stats`
by default; see `--out` and `common.resolve_out`).

Why aggregated rather than a dump: the raw exports are 28 MB and 53 MB, which no
language model can read. Every sheet here is a rolled-up table small enough to
paste into a prompt, while still carrying the shape a chart needs.

Usage:
  uv run python3 tools/ccstats/build_workbook.py
  uv run python3 tools/ccstats/build_workbook.py --no-titles   # strip session titles
  uv run python3 tools/ccstats/build_workbook.py --out DIR     # write elsewhere

Privacy: absolute file paths and prompt previews are NEVER included. Project
labels and session titles ARE, because a chart without them is unreadable.
`--no-titles` drops the titles too.
"""

# The long lines in this file are the README, Dictionary and Caveats prose that
# gets written INTO spreadsheet cells. Wrapping them would put line breaks in the
# cells, so the line-length rule is waived here.
# ruff: noqa: E501

from __future__ import annotations

import csv
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import facts  # noqa: E402
from common import (  # noqa: E402
    COST_NOTE,  # noqa: E402
    BadOut,
    BadWindow,
    Window,
    open_ro,
    resolve_out,
    resolve_window,
    write_manifest,
)
from xlsx import FMT_DEC2, FMT_GENERAL, FMT_INT, FMT_MONEY, Sheet, write_workbook  # noqa: E402

TXT, NUM, DEC, USD = FMT_GENERAL, FMT_INT, FMT_DEC2, FMT_MONEY

# 0 = Monday, matching datetime.weekday(). Module level because two sheets use
# it; when they lived inside one 452-line function, Hour_Heatmap defined it and
# By_Weekday quietly borrowed it. Splitting the function surfaced that.
WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def q(
    conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()
) -> list[tuple[object, ...]]:
    """Run a query. `params` binds VALUES; never format them into `sql`."""
    return conn.execute(sql, params).fetchall()



def _sheet_readme(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 01: README."""
    # ------------------------------------------------------------ 01 README

    readme = [
        ["WHAT THIS IS", "Claude Code usage statistics for one machine, pre-aggregated for charting."],
        ["GENERATED", datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")],
        ["PERIOD", f"{f['span_lo']} to {f['span_hi']} ({f['active_days']:,} days with activity)"],
        ["SOURCE", "Every session transcript in ~/.claude/projects and ~/cc-warehouse-archive, deduplicated."],
        ["TIMEZONE", f"local_* columns use {meta.get('local_timezone', '(unknown)')}, DST-aware. Raw timestamps are UTC."],
        ["TIMEZONE SOURCE", f"{meta.get('local_timezone_source', '(unknown)')}. The cc-warehouse config pins the zone, so these statistics and the archive folder names are always rendered in the same time. Any chart or page built from this workbook must state this zone."],
        ["", ""],
        ["READ FIRST", "The 'Dictionary' sheet defines every column. The 'Caveats' sheet lists EIGHT traps that will make a chart wrong. The 'Data_Coverage' sheet says which columns are usable for which period."],
        ["", ""],
        ["TRAP 1", f"A 'session' is not a file. {f['shell_pct']}% of transcript files have no assistant reply. Every sheet here already filters to the {f['sessions_real']:,} real ones."],
        ["TRAP 2", "Four different 'hours' columns exist and they measure different things. Only engaged_hours means work done."],
        ["TRAP 3", "cost_usd is API list-price equivalent, NOT a bill. This is subscription usage."],
        ["TRAP 7", f"{f['last_month']} is a PARTIAL month ({f['last_month_days']} days, ends {f['last_day']}). Its bar is short because collection stopped, not because usage fell."],
        ["TRAP 8", f"Thinking tokens only exist from {f['thinking_from']} (Claude Code {f['thinking_version']}). Zero before that means NOT RECORDED, not zero thinking."],
        ["", ""],
        ["SUGGESTED CHARTS", "Monthly / Weekly / Daily -> time series. Projects -> ranked bars. Hour_Heatmap -> weekday x hour heatmap. Model_Month -> stacked area. Tools -> ranked bars. Concurrency -> two lines (summed vs elapsed)."],
        ["NOT INCLUDED", "Absolute file paths and prompt text are deliberately excluded."],
    ]
    return Sheet("README", ["Field", "Value"], readme,
                        widths=[18, 120], autofilter=False,
                        description="Orientation.")


def _sheet_dictionary(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 02: Dictionary."""
    # -------------------------------------------------------- 02 Dictionary
    dictionary = [
        ["ALL SHEETS", "sessions", "int", "Count of REAL sessions (had at least one assistant reply). Not file count."],
        ["ALL SHEETS", "elapsed_hours", "float", "Clock time with at least one session OPEN, clipped to the calendar day so it never exceeds 24. NOT an effort measure: it is near-saturated because terminals are left open."],
        ["ALL SHEETS", "summed_hours", "float", "Session spans added up, clipped to the day. Larger than elapsed because sessions run in parallel."],
        ["ALL SHEETS", "engaged_hours", "float", "Per session: wall time minus every idle gap over 5 min, then SUMMED across sessions. The best measure of work done. May exceed 24 in a day when sessions run in parallel; that is correct."],
        ["ALL SHEETS", "active_hours", "float", "Sum of Claude Code turn_duration events. This is WALL time per turn INCLUDING idle waiting, NOT compute time. A session left open records one multi-day turn. Do not use as a work measure."],
        ["ALL SHEETS", "prompts", "int", "User messages that carried text. Excludes tool results and interrupts."],
        ["ALL SHEETS", "tool_calls", "int", "Individual tool invocations by the model."],
        ["ALL SHEETS", "tok_input", "int", "Fresh (uncached) input tokens. Small, because most input is cached."],
        ["ALL SHEETS", "tok_output", "int", "Generated tokens. INCLUDES thinking tokens; do not add them again."],
        ["ALL SHEETS", "tok_thinking", "int", "Reasoning tokens. A SUBSET of tok_output. Only recorded from Claude Code 2.1.228 onward; 0 before that means not recorded."],
        ["ALL SHEETS", "tok_cache_write", "int", "Tokens written to prompt cache. Billed at 1.25x (5 min) or 2x (1 hour) the input rate."],
        ["ALL SHEETS", "tok_cache_read", "int", "Tokens served from cache at 0.1x the input rate. The largest number by far."],
        ["ALL SHEETS", "tok_billable", "int", "input + output + cache_write. Cache reads excluded: priced separately."],
        ["ALL SHEETS", "tok_context", "int", "input + cache_read + cache_write. What the model actually read."],
        ["ALL SHEETS", "cost_usd", "float", "API list-price equivalent in USD. NOT a bill. See Caveats."],
        ["Daily/Weekly/Monthly", "period", "text", "The calendar bucket, in local time. Daily is YYYY-MM-DD."],
        ["Daily/Weekly/Monthly", "projects_touched", "int", "Distinct repositories worked on in that bucket."],
        ["Daily", "max_concurrent", "int", "Peak number of sessions open at the same instant that day."],
        ["Daily", "concurrency", "float", "summed_hours / elapsed_hours. 1.0 means never parallel; 3.0 means 3 at once on average."],
        ["Projects", "project", "text", "Normalised project label, derived from the session's real working directory."],
        ["Projects", "is_worktree_sessions", "int", "How many of this project's sessions ran in a git worktree."],
        ["Projects", "first_seen / last_seen", "text", "UTC timestamp of the earliest and latest activity."],
        ["Projects", "avg_session_minutes", "float", "Mean engaged minutes per real session."],
        ["Hour_Heatmap", "weekday", "int", "0 = Monday, 6 = Sunday. Local time."],
        ["Hour_Heatmap", "hour", "int", "0-23, local time, taken from the session's START."],
        ["Models", "model", "text", "Exact model id from the payload. '<synthetic>' is a local placeholder, never an API call."],
        ["Models", "turns", "int", "Assistant turns. One turn is one API response."],
        ["Models", "avg_out_per_turn", "float", "Mean output tokens per turn. A proxy for how much work each reply did."],
        ["Tools", "tool", "text", "Tool name as the model called it. '(error-result)' rows count failed tool results."],
        ["Skills_Agents_MCP", "kind", "text", "One of skill, plugin, agent, mcp_server, mcp_tool."],
        ["Session_Sizes", "bucket", "text", "Duration or token band. Ordered by 'sort' column, not alphabetically."],
        ["Top_Sessions", "title", "text", "Auto-generated session title. Absent when --no-titles was used."],
    ]
    return Sheet("Dictionary", ["Sheet", "Column", "Type", "Meaning"], dictionary,
                        widths=[22, 24, 8, 100],
                        description="What every column means.")


def _sheet_caveats(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 03: Caveats."""
    # ----------------------------------------------------------- 03 Caveats
    caveats = [
        [1, "A file is not a session",
         f"{f['files_total']:,} transcript files exist but only {f['sessions_real']:,} have an assistant reply ({f['shell_pct']}% are empty). The rest are SDK/hook launches and interrupted prompts.",
         f"Every sheet here already filters to real sessions. Going back to sessions.csv without WHERE is_real = 1 inflates counts about {f['inflate']}x."],
        [2, "Four different 'hours'. Only ONE means work: engaged_hours",
         f"engaged_hours ({f['engaged_h']:,}) strips idle gaps over 5 min from each session, then sums. active_hours ({f['active_h']:,}) is turn_duration, which is TURN WALL TIME INCLUDING IDLE, not compute. elapsed_hours ({f['elapsed_h']:,}) is clock time with at least one session OPEN. summed_hours ({f['summed_h']:,}) just adds session spans up.",
         f"Chart engaged_hours. Do NOT use active_hours (in July 2026 ten left-open sessions supplied 51% of it). Do NOT use elapsed_hours as an effort measure: it averages {f['mean_elapsed']}h of a 24h day because terminals get left open, so it is near-saturated and tells you almost nothing."],
        [3, "cost_usd is not money spent",
         "It is what this usage would cost at Anthropic API list prices. This machine runs a Claude Code subscription, which is not billed per token.",
         "Label any cost chart 'API list-price equivalent'. Valid for COMPARING projects and periods, invalid as a spend figure."],
        [4, "Cache reads dominate the token counts",
         f"{f['tok_cr']:,} cache-read tokens against {f['tok_out']:,} output tokens, a ratio near {f['cr_ratio']}:1.",
         "Chart cache reads separately, or use a log scale, or chart tok_billable which excludes them."],
        [5, "thinking is inside output",
         "tok_thinking is a subset of tok_output, not an addition.",
         "Never sum them. To show the split, stack tok_thinking and (tok_output - tok_thinking)."],
        [6, "Project counts differ by which key you use",
         f"{f['repos']} repositories but {f['labels']} project labels. {f['multi_label_repos']} repositories carry {f['extra_labels']} extra labels between them. Only {f['worktree_labels']} of those are git worktrees; the rest are SUBDIRECTORIES worked in directly (docs/, Outputs/, a nested sub-project), each of which Claude Code records as its own working directory.",
         "The Projects sheet is one row per LABEL. Overview counts REPOSITORIES. Both are correct; say which a chart uses. To roll subdirectories back into their parent, group sessions-real.csv by repo_root instead of project_label."],
        [7, "The most recent month is partial",
         f"Data stops {f['last_day']}. {f['last_month']} covers only {f['last_month_days']} days. Separately, {f['busiest_day']} is an extreme outlier at {f['busiest_n']:,} sessions and up to {f['peak_concurrent']} concurrent.",
         f"Either exclude {f['last_month']} from monthly charts or mark it 'partial'. The Monthly sheet has an is_partial column. For the outlier day, keep it but annotate it."],
        [9, "engaged_hours can exceed 24 in a day, and that is CORRECT",
         f"engaged_hours is summed across sessions; elapsed_hours merges them. With up to {f['peak_concurrent']} sessions running at once, a 24-hour day can legitimately hold far more than 24 engaged hours. On {f['busiest_day']} that is {f['busiest_engaged']}h of engaged work inside {f['busiest_elapsed']}h of clock time.",
         "Do not 'fix' it by capping at 24. If you need per-person time rather than per-session time, divide by max_concurrent, or chart elapsed_hours instead and say so."],
        [10, "Three things were WRONG in copies issued before 2026-08-21",
         f"(a) elapsed_hours attributed each session whole to its START date, so a 2026-06-01 to 2026-07-04 session put 804 h on one day; 73 of 153 days read over 24 h. Now clipped per day: {f['days_over_24h']} days exceed 24 h and the total fell from 7,621.7 to {f['elapsed_h']:,}. (b) local_* columns used a FIXED +10 offset and ignored the pinned config zone, so the {f['dst_sessions_all']} sessions recorded while Melbourne was on AEDT (+11, until 2026-04-04) were bucketed an hour early; 45 landed on the wrong date and weekday. Now DST-aware. (c) active_hours was mislabelled as compute time.",
         "Discard elapsed_hours, concurrency, local_hour and local_weekday from any older copy. This copy is correct on all three."],
        [8, "Thinking tokens do not exist before " + str(f["thinking_from"]),
         f"Claude Code only began emitting output_tokens_details.thinking_tokens at version {f['thinking_version']}, first seen {f['thinking_from']}. Every earlier month reads 0.",
         "A thinking-over-time chart is only valid from that date. Before it, 0 means NOT RECORDED. Do not plot it as a time series across the whole range."],
    ]
    return Sheet("Caveats", ["#", "Trap", "What is true", "What to do"], caveats,
                        widths=[4, 34, 88, 88], autofilter=False,
                        description="Read before charting.")


def _sheet_overview(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 04: Overview."""
    # ---------------------------------------------------------- 04 Overview
    t = q(conn, f"""
        SELECT COUNT(*), SUM(n_user_prompts), SUM(n_tool_uses), SUM(n_assistant_turns),
               SUM(engaged_seconds)/3600.0, SUM(active_seconds)/3600.0,
               SUM(tok_input), SUM(tok_output), SUM(tok_thinking),
               SUM(tok_cache_write), SUM(tok_cache_read), SUM(cost_usd),
               MIN(first_ts), MAX(last_ts), COUNT(DISTINCT repo_root)
        FROM session WHERE {w.session}""")[0]
    files, subs_all = q(conn, "SELECT COUNT(*), SUM(is_subagent) FROM session")[0]
    # Count sub-agents among REAL sessions, matching every other row here and
    # matching sessions-real.csv. The unfiltered figure differs by the handful
    # of sub-agent transcripts that never got a reply, and a reviewer rightly
    # flagged the one-row gap on 2026-08-21.
    subs = q(conn, f"SELECT SUM(is_subagent) FROM session WHERE {w.session}")[0][0]
    el, sm = q(conn, "SELECT SUM(elapsed_hours), SUM(summed_hours) FROM overlap_day")[0]
    days = q(conn, f"SELECT COUNT(DISTINCT local_date) FROM session WHERE {w.session}")[0][0]
    wt = q(conn, f"SELECT COUNT(*) FROM session WHERE {w.session} AND is_worktree=1")[0][0]

    def row(metric: str, value: object, note: str) -> list[object]:
        return [metric, value, note]

    overview = [
        row("Date range", f"{str(t[12])[:10]} to {str(t[13])[:10]}", "First and last activity, UTC"),
        row("Days with activity", days, "Distinct local calendar days"),
        row("Real sessions", t[0], "Had at least one assistant reply. THE session count"),
        row("Distinct transcripts", files, "After deduplication. Includes empty shells; NOT a session count"),
        row("Transcript files scanned", f["files_total"], "Same as above after dedupe; the raw file count is in collect-report.json"),
        row("Sub-agent sessions", subs, f"Nested agent runs with a reply. {subs_all:,} sub-agent transcripts exist including empty ones"),
        row("Projects (repositories)", t[14], f"Distinct repo_root. The Projects sheet has {f['labels']} rows because worktrees get their own label"),
        row("Worktree sessions", wt, "Ran inside a git worktree"),
        row("Prompts", t[1], "User messages carrying text"),
        row("Assistant turns", t[3], "One turn = one API response"),
        row("Tool calls", t[2], "Individual tool invocations"),
        row("Elapsed hours (real clock)", round(el or 0, 1), "Overlapping sessions merged. THE honest wall-clock figure"),
        row("Summed hours", round(sm or 0, 1), "Sessions added up. Inflated by parallel work"),
        row("Engaged hours", round(t[4] or 0, 1), "Idle gaps over 5 min removed. USE THIS for work done"),
        row("Turn-duration hours", round(t[5] or 0, 1), "Claude Code turn_duration. WALL time per turn INCLUDING idle. Not a work measure"),
        row("Input tokens", t[6], "Fresh, uncached"),
        row("Output tokens", t[7], "Includes thinking"),
        row("  of which thinking", t[8], "SUBSET of output, not additional"),
        row("Cache write tokens", t[9], "Billed 1.25x (5m) or 2x (1h) of input rate"),
        row("Cache read tokens", t[10], "Billed 0.1x of input rate"),
        row("Cost, API list price", round(t[11] or 0, 2), "NOT a bill. Subscription usage is not billed per token"),
    ]
    return Sheet("Overview", ["Metric", "Value", "Note"], overview,
                        formats=[TXT, TXT, TXT], widths=[28, 18, 62], autofilter=False,
                        description="Headline totals.")


def _sheet_daily(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 05: Daily."""
    # ------------------------------------------------------------- 05 Daily
    daily = q(conn, f"""
        SELECT s.local_date,
               COUNT(*), COUNT(DISTINCT s.repo_root),
               ROUND(SUM(s.engaged_seconds)/3600.0, 2),
               ROUND(SUM(s.active_seconds)/3600.0, 2),
               COALESCE(o.elapsed_hours, 0), COALESCE(o.summed_hours, 0),
               COALESCE(o.max_concurrent, 0), COALESCE(o.concurrency, 0),
               SUM(s.n_user_prompts), SUM(s.n_tool_uses),
               SUM(s.tok_input), SUM(s.tok_output), SUM(s.tok_thinking),
               SUM(s.tok_cache_write), SUM(s.tok_cache_read),
               SUM(s.tok_billable_total), ROUND(SUM(s.cost_usd), 2)
        FROM session s LEFT JOIN overlap_day o ON o.local_date = s.local_date
        WHERE {w.session_as_s} AND s.local_date IS NOT NULL
        GROUP BY s.local_date ORDER BY s.local_date""")
    return Sheet("Daily", [
        "date", "sessions", "projects_touched", "engaged_hours", "active_hours",
        "elapsed_hours", "summed_hours", "max_concurrent", "concurrency",
        "prompts", "tool_calls", "tok_input", "tok_output", "tok_thinking",
        "tok_cache_write", "tok_cache_read", "tok_billable", "cost_usd"],
        daily, formats=[TXT, NUM, NUM, DEC, DEC, DEC, DEC, NUM, DEC, NUM, NUM, NUM, NUM, NUM, NUM, NUM, NUM, USD],
        description="One row per local calendar day.")


def _sheet_weekly(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 06: Weekly."""
    # ------------------------------------------------------------ 06 Weekly
    weekly = q(conn, f"""
        SELECT strftime('%Y-W%W', s.local_date) AS wk,
               MIN(s.local_date), COUNT(*), COUNT(DISTINCT s.repo_root),
               ROUND(SUM(s.engaged_seconds)/3600.0, 2),
               ROUND(SUM(s.active_seconds)/3600.0, 2),
               SUM(s.n_user_prompts), SUM(s.n_tool_uses),
               SUM(s.tok_output), SUM(s.tok_cache_read),
               SUM(s.tok_billable_total), ROUND(SUM(s.cost_usd), 2)
        FROM session s WHERE {w.session} AND s.local_date IS NOT NULL
        GROUP BY wk ORDER BY wk""")
    return Sheet("Weekly", [
        "week", "week_starting", "sessions", "projects_touched", "engaged_hours",
        "active_hours", "prompts", "tool_calls", "tok_output", "tok_cache_read",
        "tok_billable", "cost_usd"],
        weekly, formats=[TXT, TXT, NUM, NUM, DEC, DEC, NUM, NUM, NUM, NUM, NUM, USD],
        description="One row per ISO-ish week.")


def _sheet_monthly(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 07: Monthly."""
    # ----------------------------------------------------------- 07 Monthly
    monthly = q(conn, f"""
        SELECT substr(s.local_date, 1, 7) AS mo,
               COUNT(*), COUNT(DISTINCT s.repo_root),
               COUNT(DISTINCT s.local_date),
               ROUND(SUM(s.engaged_seconds)/3600.0, 2),
               ROUND(SUM(s.active_seconds)/3600.0, 2),
               SUM(s.n_user_prompts), SUM(s.n_tool_uses), SUM(s.n_assistant_turns),
               SUM(s.tok_input), SUM(s.tok_output), SUM(s.tok_thinking),
               SUM(s.tok_cache_write), SUM(s.tok_cache_read),
               SUM(s.tok_billable_total), ROUND(SUM(s.cost_usd), 2)
        FROM session s WHERE {w.session} AND s.local_date IS NOT NULL
        GROUP BY mo ORDER BY mo""")
    # The newest month always stops on collection day, so its bar is short for a
    # reason that is not a decline. Flag it in the data rather than in a footnote.
    monthly = [
        (r[0], 1 if r[0] == f["last_month"] else 0,
         1 if r[0] >= str(f["thinking_from"])[:7] else 0, *r[1:])
        if r[0] not in (f["last_month"], f["first_month"]) else
        (r[0], 1, 1 if r[0] >= str(f["thinking_from"])[:7] else 0, *r[1:])
        for r in monthly
    ]
    return Sheet("Monthly", [
        "month", "is_partial", "thinking_recorded", "sessions", "projects_touched", "active_days", "engaged_hours",
        "active_hours", "prompts", "tool_calls", "assistant_turns", "tok_input",
        "tok_output", "tok_thinking", "tok_cache_write", "tok_cache_read",
        "tok_billable", "cost_usd"],
        monthly, formats=[TXT, NUM, NUM, NUM, NUM, NUM, DEC, DEC, NUM, NUM, NUM, NUM, NUM, NUM, NUM, NUM, NUM, USD],
        description="One row per calendar month. is_partial=1 means the month is cut short by collection date.")


def _sheet_projects(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 08: Projects."""
    # ---------------------------------------------------------- 08 Projects
    projects = q(conn, f"""
        SELECT COALESCE(project_label, '(unknown)'),
               COUNT(*), SUM(is_worktree), COUNT(DISTINCT local_date),
               ROUND(SUM(engaged_seconds)/3600.0, 2),
               ROUND(SUM(active_seconds)/3600.0, 2),
               ROUND(AVG(engaged_seconds)/60.0, 1),
               SUM(n_user_prompts), SUM(n_tool_uses), SUM(n_assistant_turns),
               SUM(tok_input), SUM(tok_output), SUM(tok_cache_write),
               SUM(tok_cache_read), SUM(tok_billable_total),
               ROUND(SUM(cost_usd), 2), MIN(first_ts), MAX(last_ts)
        FROM session WHERE {w.session}
        GROUP BY 1 ORDER BY SUM(cost_usd) DESC""")
    return Sheet("Projects", [
        "project", "sessions", "is_worktree_sessions", "active_days",
        "engaged_hours", "active_hours", "avg_session_minutes", "prompts",
        "tool_calls", "assistant_turns", "tok_input", "tok_output",
        "tok_cache_write", "tok_cache_read", "tok_billable", "cost_usd",
        "first_seen", "last_seen"],
        projects, formats=[TXT, NUM, NUM, NUM, DEC, DEC, DEC, NUM, NUM, NUM, NUM, NUM, NUM, NUM, NUM, USD, TXT, TXT],
        description="One row per project, ranked by cost.")


def _sheet_project_month(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 09: Project_Month."""
    # ----------------------------------------------------- 09 Project_Month
    # Top 12 projects by cost, everything else folded into "(other)", so a
    # stacked chart stays readable instead of showing 101 slivers.
    top = [r[0] for r in q(conn, f"""
        SELECT COALESCE(project_label, '(unknown)') FROM session WHERE {w.session}
        GROUP BY 1 ORDER BY SUM(cost_usd) DESC LIMIT 12""")]
    # Bound placeholders, not hand-quoted literals: a project label containing
    # an apostrophe used to depend on a manual `.replace("'", "''")`.
    holes = ", ".join("?" for _ in top)
    pm = q(conn, f"""
        SELECT substr(local_date, 1, 7) AS mo,
               CASE WHEN COALESCE(project_label,'(unknown)') IN ({holes})
                    THEN COALESCE(project_label,'(unknown)') ELSE '(other)' END AS proj,
               COUNT(*), ROUND(SUM(engaged_seconds)/3600.0, 2),
               SUM(tok_billable_total), ROUND(SUM(cost_usd), 2)
        FROM session WHERE {w.session} AND local_date IS NOT NULL
        GROUP BY mo, proj ORDER BY mo, SUM(cost_usd) DESC""", tuple(top))
    return Sheet("Project_Month", [
        "month", "project", "sessions", "engaged_hours", "tok_billable", "cost_usd"],
        pm, formats=[TXT, TXT, NUM, DEC, NUM, USD],
        description="Long format for a stacked area or bar chart. Top 12 projects, rest as (other).")


def _sheet_hour_heatmap(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 10: Hour_Heatmap."""
    # ------------------------------------------------------ 10 Hour_Heatmap
    hour = q(conn, f"""
        SELECT local_weekday, local_hour, COUNT(*),
               ROUND(SUM(engaged_seconds)/3600.0, 2),
               SUM(n_user_prompts), ROUND(SUM(cost_usd), 2)
        FROM session WHERE {w.session} AND local_hour IS NOT NULL
        GROUP BY 1, 2 ORDER BY 1, 2""")
    hour = [(r[0], WEEKDAY_NAMES[int(r[0])], r[1], r[2], r[3], r[4], r[5]) for r in hour]
    return Sheet("Hour_Heatmap", [
        "weekday", "weekday_name", "hour", "sessions", "engaged_hours", "prompts", "cost_usd"],
        hour, formats=[NUM, TXT, NUM, NUM, DEC, NUM, USD],
        description="Weekday x hour, from each session's START time. 0 = Monday.")


def _sheet_by_weekday(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 11: By_Weekday."""
    # --------------------------------------------------------- 11 By_Weekday
    wd = q(conn, f"""
        SELECT local_weekday, COUNT(*), COUNT(DISTINCT local_date),
               ROUND(SUM(engaged_seconds)/3600.0, 2),
               ROUND(SUM(engaged_seconds)/3600.0 / COUNT(DISTINCT local_date), 2),
               SUM(n_user_prompts), ROUND(SUM(cost_usd), 2)
        FROM session WHERE {w.session} AND local_weekday IS NOT NULL
        GROUP BY 1 ORDER BY 1""")
    wd = [(r[0], WEEKDAY_NAMES[int(r[0])], *r[1:]) for r in wd]
    return Sheet("By_Weekday", [
        "weekday", "weekday_name", "sessions", "active_days", "engaged_hours",
        "engaged_hours_per_active_day", "prompts", "cost_usd"],
        wd, formats=[NUM, TXT, NUM, NUM, DEC, DEC, NUM, USD],
        description="Rolled up to seven rows.")


def _sheet_models(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 12: Models."""
    # ------------------------------------------------------------ 12 Models
    models = q(conn, """
        SELECT model, COUNT(*), COUNT(DISTINCT session_key),
               SUM(input_tokens), SUM(output_tokens), SUM(thinking_tokens),
               SUM(cache_write_5m + cache_write_1h), SUM(cache_read),
               ROUND(1.0 * SUM(output_tokens) / COUNT(*), 1),
               ROUND(SUM(cost_usd), 2),
               MIN(ts), MAX(ts)
        FROM turn WHERE 1=1""" + w.child_keys + """ GROUP BY model ORDER BY SUM(cost_usd) DESC""")
    return Sheet("Models", [
        "model", "turns", "sessions", "tok_input", "tok_output", "tok_thinking",
        "tok_cache_write", "tok_cache_read", "avg_out_per_turn", "cost_usd",
        "first_used", "last_used"],
        models, formats=[TXT, NUM, NUM, NUM, NUM, NUM, NUM, NUM, DEC, USD, TXT, TXT],
        description="One row per model id.")


def _sheet_model_month(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 13: Model_Month."""
    # ------------------------------------------------------- 13 Model_Month
    mm = q(conn, """
        SELECT substr(ts, 1, 7) AS mo, model, COUNT(*),
               SUM(output_tokens), SUM(cache_read), ROUND(SUM(cost_usd), 2)
        FROM turn WHERE ts IS NOT NULL""" + w.child_keys + """
        GROUP BY mo, model ORDER BY mo, SUM(cost_usd) DESC""")
    return Sheet("Model_Month", [
        "month_utc", "model", "turns", "tok_output", "tok_cache_read", "cost_usd"],
        mm, formats=[TXT, TXT, NUM, NUM, NUM, USD],
        description="Model mix over time. Long format for a stacked area chart. Month is UTC.")


def _sheet_tools(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 14: Tools."""
    # ------------------------------------------------------------- 14 Tools
    tools = q(conn, """
        SELECT tool_name, COUNT(*), SUM(is_error), COUNT(DISTINCT session_key)
        FROM tool_call WHERE 1=1""" + w.child_keys + """ GROUP BY tool_name ORDER BY COUNT(*) DESC""")
    total_calls = sum(r[1] for r in tools) or 1
    tools = [(r[0], r[1], round(100.0 * r[1] / total_calls, 2), r[2], r[3]) for r in tools]
    return Sheet("Tools", [
        "tool", "calls", "pct_of_calls", "error_results", "sessions"],
        tools, formats=[TXT, NUM, DEC, NUM, NUM],
        description="Tool usage, ranked. '(error-result)' counts failed tool results, not a tool.")


def _sheet_skills_agents_mcp(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 15: Skills_Agents_MCP."""
    # -------------------------------------------------- 15 Skills_Agents_MCP
    attr = q(conn, """
        SELECT kind, name, SUM(count), COUNT(DISTINCT session_key)
        FROM attribution WHERE 1=1""" + w.child_keys + """ GROUP BY kind, name ORDER BY kind, SUM(count) DESC""")
    return Sheet("Skills_Agents_MCP", ["kind", "name", "uses", "sessions"],
                        attr, formats=[TXT, TXT, NUM, NUM],
                        description="Which skills, plugins, agents and MCP servers actually get used.")


def _sheet_worktrees(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 16: Worktrees."""
    # --------------------------------------------------------- 16 Worktrees
    wtree = q(conn, f"""
        SELECT COALESCE(worktree_name, '(none)'), COALESCE(project_label, '(unknown)'),
               COUNT(*), ROUND(SUM(engaged_seconds)/3600.0, 2),
               SUM(tok_billable_total), ROUND(SUM(cost_usd), 2),
               MIN(first_ts), MAX(last_ts)
        FROM session WHERE {w.session} AND is_worktree = 1
        GROUP BY 1, 2 ORDER BY SUM(cost_usd) DESC""")
    return Sheet("Worktrees", [
        "worktree", "project", "sessions", "engaged_hours", "tok_billable",
        "cost_usd", "first_seen", "last_seen"],
        wtree, formats=[TXT, TXT, NUM, DEC, NUM, USD, TXT, TXT],
        description="Sessions that ran inside a git worktree.")


def _sheet_concurrency(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 17: Concurrency."""
    # ------------------------------------------------------- 17 Concurrency
    conc = q(conn, """
        SELECT local_date, sessions_active, sessions_started, summed_hours,
               elapsed_hours, concurrency, max_concurrent
        FROM overlap_day""" + w.overlap_where + """ ORDER BY local_date""")
    return Sheet("Concurrency", [
        "date", "sessions_active", "sessions_started", "summed_hours",
        "elapsed_hours", "concurrency", "max_concurrent"],
        conc, formats=[TXT, NUM, NUM, DEC, DEC, DEC, NUM],
        description="elapsed_hours is real clock time, clipped to the day, so it never exceeds 24. summed_hours sums parallel sessions and legitimately can.")


def _sheet_session_sizes(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 18: Session_Sizes."""
    # ------------------------------------------------------ 18 Session_Sizes
    buckets = q(conn, f"""
        SELECT CASE
                 WHEN engaged_seconds <   60 THEN '0 under 1 min'
                 WHEN engaged_seconds <  300 THEN '1 to 5 min'
                 WHEN engaged_seconds <  900 THEN '5 to 15 min'
                 WHEN engaged_seconds < 1800 THEN '15 to 30 min'
                 WHEN engaged_seconds < 3600 THEN '30 to 60 min'
                 WHEN engaged_seconds < 7200 THEN '1 to 2 h'
                 ELSE 'over 2 h' END AS bucket,
               CASE
                 WHEN engaged_seconds <   60 THEN 1 WHEN engaged_seconds <  300 THEN 2
                 WHEN engaged_seconds <  900 THEN 3 WHEN engaged_seconds < 1800 THEN 4
                 WHEN engaged_seconds < 3600 THEN 5 WHEN engaged_seconds < 7200 THEN 6
                 ELSE 7 END AS sort,
               COUNT(*), SUM(n_user_prompts), SUM(n_tool_uses),
               SUM(tok_billable_total), ROUND(SUM(cost_usd), 2)
        FROM session WHERE {w.session} GROUP BY bucket, sort ORDER BY sort""")
    buckets = [(r[1], r[0], *r[2:]) for r in buckets]
    return Sheet("Session_Sizes", [
        "sort", "bucket", "sessions", "prompts", "tool_calls", "tok_billable", "cost_usd"],
        buckets, formats=[NUM, TXT, NUM, NUM, NUM, NUM, USD],
        description="Distribution of session length. Order by 'sort', not alphabetically.")


def _sheet_top_sessions(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 19: Top_Sessions."""
    # ------------------------------------------------------- 19 Top_Sessions
    title_col = "COALESCE(custom_title, ai_title, slug_title, '')" if keep_titles else "''"
    tops = q(conn, f"""
        SELECT COALESCE(project_label,'(unknown)'), local_date,
               ROUND(engaged_seconds/60.0, 1), ROUND(wall_seconds/3600.0, 2),
               n_user_prompts, n_tool_uses, n_assistant_turns,
               tok_output, tok_cache_read, tok_billable_total,
               ROUND(cost_usd, 2), primary_model, {title_col}
        FROM session WHERE {w.session}
        ORDER BY cost_usd DESC LIMIT 200""")
    return Sheet("Top_Sessions", [
        "project", "date", "engaged_minutes", "wall_hours", "prompts", "tool_calls",
        "assistant_turns", "tok_output", "tok_cache_read", "tok_billable",
        "cost_usd", "model", "title"],
        tops, formats=[TXT, TXT, DEC, DEC, NUM, NUM, NUM, NUM, NUM, NUM, USD, TXT, TXT],
        description="The 200 most expensive sessions.")


def _sheet_cc_versions(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 20: CC_Versions."""
    # -------------------------------------------------------- 20 CC_Versions
    vers = q(conn, f"""
        SELECT cc_version, COUNT(*), MIN(local_date), MAX(local_date),
               ROUND(SUM(engaged_seconds)/3600.0, 2), ROUND(SUM(cost_usd), 2)
        FROM session WHERE {w.session} AND cc_version IS NOT NULL
        GROUP BY cc_version ORDER BY MIN(first_ts)""")
    return Sheet("CC_Versions", [
        "claude_code_version", "sessions", "first_day", "last_day", "engaged_hours", "cost_usd"],
        vers, formats=[TXT, NUM, TXT, TXT, DEC, USD],
        description="Which Claude Code build ran each session, in first-seen order.")


def _sheet_data_coverage(conn: sqlite3.Connection, w: Window, f: dict[str, object], meta: dict[str, str], keep_titles: bool) -> Sheet:  # noqa: ARG001
    """Sheet 21: Data_Coverage."""
    # ------------------------------------------------------ 21 Data_Coverage
    # Not every column is populated for the whole period. Charting one that is
    # not gives a graph that looks like a trend and is actually a rollout.
    coverage = [
        ["tok_thinking", str(f["thinking_from"]), str(f["span_hi"]),
         f"Claude Code {f['thinking_version']} onward only",
         "NOT chartable as a time series across the full range. 0 before the start date means NOT RECORDED."],
        ["tok_input / tok_output / tok_cache_*", str(f["span_lo"]), str(f["span_hi"]),
         "Full range", "Safe to chart across the whole period."],
        ["cost_usd", str(f["span_lo"]), str(f["span_hi"]),
         "Full range, one price table",
         "Prices are pinned to one date and applied to all history, so it is a constant-price series, not a historical-price one."],
        ["engaged_hours", str(f["span_lo"]), str(f["span_hi"]),
         "Full range", "Safe. The best work measure available."],
        ["active_hours", str(f["span_lo"]), str(f["span_hi"]),
         "Full range but OUTLIER DRIVEN",
         "Measures turn wall time including idle. Ten sessions supplied 51% of July 2026. Chart only with a caveat, or not at all."],
        ["elapsed_hours / concurrency", str(f["span_lo"]), str(f["span_hi"]),
         "Full range", "Safe. Derived from session intervals."],
        ["web_search / web_fetch counts", str(f["span_lo"]), str(f["span_hi"]),
         "Present but near zero", "Server tool use is barely used in this corpus. Probably not worth a chart."],
        [f"{f['last_month']} (all columns)", f"{f['last_month']}-01", str(f["last_day"]),
         f"PARTIAL: {f['last_month_days']} days", "Exclude from monthly comparisons or mark it partial."],
        [f"{f['span_lo'][:7]} and {str(f['span_lo'])[:4]}-03 (all columns)", str(f["span_lo"]), "2026-03-31",
         "Very thin", "Few sessions. A per-session average here rests on a tiny denominator."],
    ]
    return Sheet("Data_Coverage", [
        "column_or_period", "valid_from", "valid_to", "coverage", "what to do"],
        coverage, formats=[TXT, TXT, TXT, TXT, TXT],
        widths=[36, 13, 13, 34, 96], autofilter=False,
        description="Which columns are safe to chart over which period.")


# The workbook, in order. One function per sheet, so a sheet can be built and
# asserted on its own; before this split they were 452 lines inside one call.
SHEET_BUILDERS = (
    _sheet_readme,
    _sheet_dictionary,
    _sheet_caveats,
    _sheet_overview,
    _sheet_daily,
    _sheet_weekly,
    _sheet_monthly,
    _sheet_projects,
    _sheet_project_month,
    _sheet_hour_heatmap,
    _sheet_by_weekday,
    _sheet_models,
    _sheet_model_month,
    _sheet_tools,
    _sheet_skills_agents_mcp,
    _sheet_worktrees,
    _sheet_concurrency,
    _sheet_session_sizes,
    _sheet_top_sessions,
    _sheet_cc_versions,
    _sheet_data_coverage,
)


def build(
    conn: sqlite3.Connection, window: Window, keep_titles: bool
) -> tuple[list[Sheet], dict[str, str]]:
    """Every sheet, in order, plus the collector's meta."""
    sheets: list[Sheet] = []
    meta = dict(q(conn, "SELECT key, value FROM meta"))  # type: ignore[arg-type]
    f = facts.compute(conn, window)
    sheets = [
        make(conn, window, f, meta, keep_titles) for make in SHEET_BUILDERS
    ]
    return sheets, meta

def main() -> int:
    argv = sys.argv[1:]
    keep_titles = "--no-titles" not in argv
    try:
        out = resolve_out(argv)
    except BadOut as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        window = resolve_window(argv, out, inherit=False)
    except BadWindow as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not out.db.exists():
        print(f"missing {out.db}; run collect.py first", file=sys.stderr)
        return 2

    out.ensure()
    conn = open_ro(out.db)
    sheets, meta = build(conn, window, keep_titles)
    if not any(sheet.rows for sheet in sheets):
        # An empty workbook means the window selected nothing. Refusing beats
        # writing 21 blank sheets that look like a finished export.
        print(
            f"error: the window ({window.describe()}) selects no sessions; nothing written",
            file=sys.stderr,
        )
        conn.close()
        return 1

    write_workbook(out.xlsx, sheets, title="Claude Code usage statistics")

    # A trimmed per-session export, so a reviewer can re-derive every aggregate
    # instead of taking the workbook's word for it. Paths and prompt text stay
    # excluded.
    cur = conn.execute(
        "SELECT session_uuid, project_label, repo_root, is_worktree, worktree_name,"
        " git_branch, first_ts, last_ts, local_date, local_hour, local_weekday,"
        " wall_seconds, engaged_seconds, active_seconds, idle_seconds,"
        " n_user_prompts, n_assistant_turns, n_tool_uses, n_thinking_blocks,"
        " tok_input, tok_output, tok_thinking, tok_cache_write, tok_cache_read,"
        " tok_billable_total, cost_usd, primary_model, cc_version, is_subagent"
        f" FROM session WHERE {window.session} ORDER BY first_ts"
    )
    headers = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    with out.sessions_csv.open("w", newline="", encoding="utf-8") as handle:
        handle.write(f"# {len(rows)} real sessions. No file paths, no prompt text. {COST_NOTE}\n")
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)

    # Record the window so make_docs and check_consistency inherit it instead of
    # being told again. Passing it three times by hand is how the workbook and
    # the guide came to describe different datasets.
    write_manifest(window, datetime.now(UTC).isoformat(), out)

    print(
        f"wrote {out.sessions_csv}"
        f"  ({out.sessions_csv.stat().st_size / 1e6:.2f} MB, {len(rows):,} rows)"
    )
    size_mb = out.xlsx.stat().st_size / 1e6
    print(f"wrote {out.xlsx}  ({size_mb:.2f} MB, {len(sheets)} sheets)")
    for sheet in sheets:
        print(f"  {sheet.name:<20} {len(sheet.rows):>6,} rows  {sheet.description}")
    print(f"\nwindow: {window.describe()}")
    print(f"titles included: {keep_titles}")
    print(f"prices read on : {meta.get('prices_read_on', '(unknown)')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
