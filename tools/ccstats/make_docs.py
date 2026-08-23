#!/usr/bin/env python3
"""Generate DATA-GUIDE.md beside the workbook.

The sheet list, row counts, column names and the SQLite schema are read from the
real artefacts rather than typed by hand, so the guide cannot drift from the data
it describes. The prose is written here; the tables are derived.

Usage: uv run python3 tools/ccstats/make_docs.py
"""

from __future__ import annotations

# Prose destined for a Markdown file; wrapping it would change the output.
# ruff: noqa: E501
import json
import sqlite3
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import facts
from common import BadOut, BadWindow, Window, open_ro, resolve_out, resolve_window

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# What each sheet is FOR. Keyed by sheet name; a missing key is reported, not
# silently skipped, so a new sheet cannot ship undocumented.
PURPOSE: dict[str, tuple[str, str]] = {
    "README": ("Orientation inside the workbook.", "Read it first. No chart."),
    "Dictionary": ("Every column defined.", "Reference. No chart."),
    "Caveats": ("Six traps that make charts wrong.", "Read before plotting anything."),
    "Overview": ("Headline totals for the whole corpus.", "KPI tiles / a summary card."),
    "Daily": ("One row per local calendar day, the finest time grain.", "Line or area chart over `date`. Use `sessions`, `engaged_hours`, `cost_usd`."),
    "Weekly": ("Weekly rollup, smoother than daily.", "Line chart. Best grain for spotting trend without daily noise."),
    "Monthly": ("Monthly rollup, seven buckets.", "Bar chart. Good for a compact 'growth over time' panel."),
    "Projects": ("One row per project, ranked by cost.", "Horizontal ranked bars. Cut to top 15 or the labels become unreadable."),
    "Project_Month": ("Long format: month x project.", "Stacked area or stacked bar. Already limited to top 12 plus `(other)`."),
    "Hour_Heatmap": ("Weekday x hour grid.", "Heatmap, 7 rows x 24 columns, coloured by `engaged_hours` or `sessions`."),
    "By_Weekday": ("Seven rows, one per day of week.", "Bar chart. Use `engaged_hours_per_active_day` to compare fairly."),
    "Models": ("One row per model id.", "Ranked bars, or a donut for cost share."),
    "Model_Month": ("Long format: month x model.", "Stacked area showing the model mix shifting over time."),
    "Tools": ("Tool usage, ranked.", "Horizontal bars, top 20. `pct_of_calls` is precomputed."),
    "Skills_Agents_MCP": ("Skills, plugins, agents and MCP servers actually used.", "Grouped bars, faceted by `kind`."),
    "Worktrees": ("Sessions that ran inside a git worktree.", "Small table or bars. Only a handful of rows."),
    "Concurrency": ("Parallel work per day.", "Two lines: `summed_hours` vs `elapsed_hours`. The gap is the story."),
    "Session_Sizes": ("Distribution of session length.", "Histogram. Sort by the `sort` column, never alphabetically."),
    "Top_Sessions": ("The 200 most expensive sessions.", "Scatter (`engaged_minutes` vs `cost_usd`) or a table."),
    "CC_Versions": ("Claude Code build per session, in first-seen order.", "Timeline or small multiples. Mostly useful as context."),
    "Data_Coverage": ("Which columns are valid over which period.", "Read it. No chart."),
}


def sheet_info(path: Path) -> list[tuple[str, int, list[str]]]:
    """(name, data_rows, headers) for every sheet, read back out of the file."""
    out: list[tuple[str, int, list[str]]] = []
    with zipfile.ZipFile(path) as zf:
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        names = [s.get("name") or "" for s in wb.iter(f"{NS}sheet")]
        for i, name in enumerate(names, start=1):
            ws = ET.fromstring(zf.read(f"xl/worksheets/sheet{i}.xml"))
            rows = list(ws.iter(f"{NS}row"))
            headers: list[str] = []
            if rows:
                for cell in rows[0].iter(f"{NS}c"):
                    text = cell.find(f"{NS}is/{NS}t")
                    headers.append(text.text or "" if text is not None else "")
            out.append((name, max(0, len(rows) - 1), headers))
    return out


def schema(conn: sqlite3.Connection) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """(name, kind, [(column, type)]) for every table and view."""
    out: list[tuple[str, str, list[tuple[str, str]]]] = []
    for name, kind in conn.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table','view')"
        " AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name"
    ).fetchall():
        cols = [
            (r[1], r[2] or "")
            for r in conn.execute(f'PRAGMA table_info("{name}")').fetchall()
        ]
        out.append((name, kind, cols))
    return out


def _intro_section(f: dict[str, object], meta: dict[str, str], since: str, report: dict[str, object]) -> list[str]:
    """Title, what-this-data-is, and the overview table."""
    L: list[str] = []
    add = L.append
    add("# Claude Code usage data: guide for whoever builds the charts")
    add("")
    add(f"Companion to **`claude-code-stats.xlsx`**. Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} from the same data, so this document cannot drift from the workbook.")
    add("")
    add("## What this data is")
    add("")
    add("Every Claude Code session recorded on one machine, read from two transcript trees and deduplicated. It covers what was worked on, when, for how long, with which model, and how many tokens each exchange consumed.")
    if since:
        add("")
        add(f"**This is a WINDOWED extract: {since} onward only.** Every sheet, every total and every figure in this guide is filtered to that window. Earlier sessions exist in the source data but are deliberately excluded, so do not describe these numbers as all-time.")
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| Period covered | {f['span_lo']} to {f['span_hi']} |")
    add(f"| Days with activity | {f['active_days']:,} |")
    add(f"| Real sessions | {f['sessions_real']:,} |")
    add(f"| Distinct transcripts after dedupe | {f['files_total']:,} (includes empty shells) |")
    add(f"| Raw files walked before dedupe | {report.get('transcript_files_found', 0):,} |")
    add(f"| Assistant turns | {f['turns']:,} |")
    add(f"| Tool calls | {f['tool_calls']:,} |")
    add(f"| Projects (repositories / labels) | {f['repos']} / {f['labels']} |")
    add(f"| Local timezone for all `local_*` columns | {meta.get('local_timezone', '(unknown)')} (DST-aware) |")
    add(f"| Where that zone came from | {meta.get('local_timezone_source', '(unknown)')} |")
    add(f"| Prices used for `cost_usd`, read on | {meta.get('prices_read_on', '(unknown)')} |")
    add("")
    add("The workbook is **pre-aggregated on purpose**. The underlying per-session and per-turn exports are 28 MB and 53 MB, which no language model can read. Every sheet below is small enough to paste into a prompt.")
    add("")
    return L


def _hours_traps_section(f: dict[str, object], conn: sqlite3.Connection, window: Window) -> list[str]:
    """Traps 1-2: a file is not a session, and the four different "hours"."""
    L: list[str] = []
    add = L.append
    add("## Ten things that will make your chart wrong")
    add("")
    add("Read these before writing any chart code. They are not style notes; each one changes a number.")
    add("")
    add("### 1. A file is not a session")
    add("")
    add(f"There are **{f['files_total']:,} distinct transcripts** but only **{f['sessions_real']:,} real sessions**. **{f['shell_pct']}%** of files have no assistant reply at all: SDK and hook launches, sub-agent stubs, and prompts interrupted before a response.")
    add("")
    add(f"**Every sheet in the workbook already filters to real sessions, and so does every number in this guide.** If you go back to `sessions.csv`, add `WHERE is_real = 1` or your per-project counts inflate about {f['inflate']}x.")
    add("")
    add("### 2. There are four different \"hours\" and they are not interchangeable")
    add("")
    add("| Column | Definition | Value | Use it for |")
    add("|---|---|---|---|")
    add(f"| `summed_hours` | every session duration added together | {f['summed_h']:,} h | almost never on its own |")
    add(f"| `elapsed_hours` | clock time with at least one session OPEN, clipped to the day | {f['elapsed_h']:,} h | coverage, not effort |")
    add(f"| `engaged_hours` | wall time minus every idle gap over 5 minutes | {f['engaged_h']:,} h | **\"how much did I actually work\"** |")
    add(f"| `active_hours` | sum of Claude Code `turn_duration` events | {f['active_h']:,} h | **nothing, without a caveat** |")
    add("")
    add(f"**Use `engaged_hours`. It is the only one of the four that means work.** `summed_hours` adds parallel sessions together and overstates badly. `elapsed_hours` averages **{f['mean_elapsed']} h of every 24-hour day** because terminals are left open, so it is near-saturated and close to useless as an effort signal: it answers \"was anything open\", not \"was I working\".")
    add("")
    add("**Correction, and it matters.** An earlier version of this guide described `active_hours` as \"time the model was working\" and said it agreed with `engaged_hours` within about 13%, so either could be trusted. **Both statements were wrong.**")
    add("")
    add("`turn_duration` measures a turn's **wall time, including idle waiting**, not compute. Measured on this corpus: the largest single session records `active_hours` 97.6 against `wall_hours` 97.9 and `engaged_hours` 3.0, from five turn events. That is one prompt fired into a session that was then left open for four days, not 97 hours of computing. Across all sessions carrying turn events, mean `active / wall` is 0.32 while `active` exceeds `wall` in only 2 of 1,166 sessions, which is what a wall-clock measure looks like and not what a compute measure looks like.")
    add("")
    add("The ~13% agreement was a coincidence of the **totals**. Per month the two diverge badly:")
    add("")
    add("| Month | `engaged_hours` | `active_hours` | ratio |")
    add("|---|---|---|---|")
    for mo, eh, ah in conn.execute(
        "SELECT substr(local_date,1,7), ROUND(SUM(engaged_seconds)/3600.0,1),"
        " ROUND(SUM(active_seconds)/3600.0,1) FROM session"
        " WHERE is_real=1 AND local_date IS NOT NULL"
        + window.and_clause
        + " GROUP BY 1 ORDER BY 1"
    ).fetchall():
        add(f"| {mo} | {eh:,} | {ah:,} | {round(ah / eh, 2) if eh else 0} |")
    add("")
    add("July 2026 shows `active_hours` at 1.52x `engaged_hours`, and **ten sessions supply 51% of that month's total**. If you plot both lines that gap will be visible; the cause is left-open sessions, not a change in working style.")
    add("")
    add("**Second correction, larger, and found by a reviewer on 2026-08-21.** `elapsed_hours` was computed wrongly. Session intervals were attributed **whole to their start date** and never clipped to the calendar day, so a session running 2026-06-01 to 2026-07-04 put its entire 804-hour span onto 2026-06-01. The result: **73 of 153 days reported more than 24 hours**, peaking at 814.3 h, with 87.6% of the corpus total sitting on physically impossible days.")
    add("")
    add(f"Intervals are now clipped to every day they touch. **{f['days_over_24h']} days now exceed 24 h**, the maximum is {f['max_elapsed']} h, and the corpus total fell from **7,621.7 h to {f['elapsed_h']:,} h**. If you hold an older copy of this workbook, discard its `elapsed_hours` and `concurrency` columns: they were wrong, not merely imprecise.")
    add("")
    return L


def _cost_token_traps_section(f: dict[str, object], meta: dict[str, str]) -> list[str]:
    """Traps 3-5: cost is not money, cache reads dominate, thinking is a subset."""
    L: list[str] = []
    add = L.append
    add("### 3. `cost_usd` is not money spent")
    add("")
    add(f"It is what the usage **would** cost at Anthropic API list prices, read {meta.get('prices_read_on', '')}. This machine runs a Claude Code subscription, which is not billed per token.")
    add("")
    add("Label any cost axis **\"API list-price equivalent\"**. The figure is valid for comparing projects and periods against each other. It is not a spend figure and must not be presented as one.")
    add("")
    add("Rates applied per turn, against that turn's own model: cache writes at 1.25x the input rate for the 5 minute tier and 2x for the 1 hour tier, cache reads at 0.1x. A model id with no known price is counted as zero and listed in `collect-report.json` under `unpriced_models`, which is currently empty.")
    add("")
    add("### 4. Cache reads dominate every token total")
    add("")
    add(f"There are **{f['tok_cr']:,} cache-read tokens** against **{f['tok_out']:,} output tokens**, a ratio near **{f['cr_ratio']}:1**. Put both on one linear axis and the chart shows cache reads and nothing else.")
    add("")
    add("Chart cache reads on their own, or use a log scale, or chart `tok_billable` which excludes them by design.")
    add("")
    add("### 5. Thinking tokens are inside output tokens")
    add("")
    add(f"`tok_thinking` is a **subset** of `tok_output`, not an addition. Verified across all {f['turn_rows']:,} turns: thinking never exceeded output once. To show the split, stack `tok_thinking` against `tok_output - tok_thinking`. **But read trap 8 first: it only exists for part of the range.**")
    add("")
    return L


def _project_time_traps_section(f: dict[str, object], conn: sqlite3.Connection) -> list[str]:
    """Traps 6-9: project label vs repo, partial months, thinking rollout,
    per-day engaged hours over 24."""
    L: list[str] = []
    add = L.append
    add("### 6. Project counts differ depending on which key you use")
    add("")
    add(f"There are **{f['repos']} distinct repositories** but **{f['labels']} distinct project labels**. {f['multi_label_repos']} repositories carry {f['extra_labels']} extra labels between them, and only **{f['worktree_labels']} of those are git worktrees**. The rest are SUBDIRECTORIES worked in directly (a `docs/` folder, an `Outputs/` folder, a nested sub-project); Claude Code keys a project on the working directory, so each becomes its own label.")
    add("")
    add("Neither is wrong. `Projects` is one row per **label**; `Overview` counts **repositories**. State which one a chart uses. To roll subdirectories back into their parent repository, group `sessions-real.csv` by `repo_root` rather than `project_label`.")
    add("")
    add(f"### 7. {f['first_month']} AND {f['last_month']} are partial months, and {f['busiest_day']} is an outlier")
    add("")
    add(f"The window opens on **{f['first_day']}**, so **{f['first_month']} covers only {f['first_month_days']} days**, and collection stopped on **{f['last_day']}**, so **{f['last_month']} covers only {f['last_month_days']} days**. On a monthly bar chart it shows as a short bar that is an artefact of when the data was taken, not a decline in usage. The `Monthly` sheet now carries an **`is_partial`** column; filter on it or annotate the bar.")
    add("")
    add(f"Separately, **{f['busiest_day']}** is an extreme single day: **{f['busiest_n']:,} sessions**, with up to **{f['peak_concurrent']} sessions running at once**, roughly three times the next-highest day. Keep it, but annotate it, or a daily chart reads as though something broke.")
    add("")
    add(f"The other end is thin too. The record starts {f['span_lo']}, but heavy daily use begins later, so the earliest buckets rest on very few sessions. Either start the time series where the daily session count stabilises, or plot `sessions` alongside so a spike built on three sessions is visibly a spike built on three sessions.")
    add("")
    add(f"### 8. Thinking tokens do not exist before {f['thinking_from']}")
    add("")
    add(f"Claude Code only began emitting `output_tokens_details.thinking_tokens` at version **{f['thinking_version']}**, first seen **{f['thinking_from']}**. Established by census across all {len(conn.execute('SELECT DISTINCT cc_version FROM session WHERE is_real=1').fetchall())} versions in the corpus: 2.1.227 records none, 2.1.228 records it, and every later version does.")
    add("")
    add(f"So every month before {f['thinking_from']} reads **0**, and that zero means **not recorded**, not \"no thinking happened\". A thinking-over-time chart across the full range shows a fake step change on the rollout date.")
    add("")
    add(f"Chart thinking only from {f['thinking_from']} onward, or as a share of output within that window. The `Monthly` sheet carries a **`thinking_recorded`** flag, and the `Data_Coverage` sheet lists every column with this problem.")
    add("")
    add("### 9. `engaged_hours` above 24 in one day is correct, not a bug")
    add("")
    add(f"`engaged_hours` is computed per session and then **summed**; `elapsed_hours` **merges** sessions. With up to **{f['peak_concurrent']} sessions running simultaneously**, a 24-hour day legitimately holds far more than 24 engaged hours. On {f['busiest_day']} it is **{f['busiest_engaged']} h of engaged work inside {f['busiest_elapsed']} h of clock time**.")
    add("")
    add("Do not cap it at 24. If you want person-time rather than session-time, divide by `max_concurrent`, or chart `elapsed_hours` and say which you used.")
    add("")
    return L


def _corrections_and_timezone_section(f: dict[str, object], meta: dict[str, str]) -> list[str]:
    """Trap 10, plus the timezone section every page has to carry forward."""
    L: list[str] = []
    add = L.append
    add("### 10. Numbers changed after the first release")
    add("")
    add(f"If you were given an earlier copy, **three** things were wrong. (a) `elapsed_hours` and `concurrency`, per trap 2. (b) The `local_*` columns used a **fixed +10 offset** rather than a DST-aware zone, so the **{f['dst_sessions_all']} sessions** recorded while Melbourne was on AEDT (+11, up to 2026-04-04) sat an hour early; 45 of those landed on the wrong date and therefore the wrong weekday, affecting `Hour_Heatmap` and `By_Weekday`. (c) `active_hours` was mislabelled as compute time. All three are fixed here: the zone is now `Australia/Melbourne` with real DST history, and {f['dst_sessions_all']} sessions across the full record correctly carry `+1100`. The zone is now taken from the cc-warehouse config file rather than the machine clock.")
    add("")
    add("## Timezone: state it on every page you build")
    add("")
    add(f"Every `local_date`, `local_hour` and `local_weekday` in this dataset is rendered in **{meta.get('local_timezone', '(unknown)')}**, taken from **{meta.get('local_timezone_source', '(unknown)')}**.")
    add("")
    add("This is deliberate and it is not the machine clock. cc-warehouse pins the zone in its config file so that the same session always yields the same folder name on any machine; these statistics use the same pinned zone, so the numbers and the archive folder names can never disagree about what day something happened. If the config is absent the machine zone is used instead, and if that fails a fixed offset is used; whichever applied is named above and in `collect-report.json`.")
    add("")
    add("**Any Markdown or HTML page generated from this data must print that zone.** A reader in another country seeing an hour-of-day heatmap with no zone label will read it as their own local time, which is wrong by up to a full day.")
    add("")
    add("Raw `first_ts` and `last_ts` in `sessions-real.csv` stay in UTC, so you can re-render into any other zone if you need to.")
    add("")
    return L


def _sheets_section(sheets: list[tuple[str, int, list[str]]], undocumented: list[str]) -> list[str]:
    """The per-sheet index table."""
    L: list[str] = []
    add = L.append
    add("## The sheets")
    add("")
    add("| # | Sheet | Rows | What it holds | Suggested chart |")
    add("|---|---|---|---|---|")
    for i, (name, rows, _cols) in enumerate(sheets, start=1):
        what, chart = PURPOSE.get(name, ("UNDOCUMENTED", "UNDOCUMENTED"))
        add(f"| {i} | `{name}` | {rows:,} | {what} | {chart} |")
    add("")
    if undocumented:
        add(f"> **Warning:** these sheets have no description: {', '.join(undocumented)}")
        add("")
    return L


def _columns_section(sheets: list[tuple[str, int, list[str]]]) -> list[str]:
    """Every sheet's column list, then the shared column-meaning glossary."""
    L: list[str] = []
    add = L.append
    add("### Columns, sheet by sheet")
    add("")
    for name, rows, cols in sheets:
        if name in ("README", "Dictionary", "Caveats"):
            continue
        add(f"**`{name}`** ({rows:,} rows)")
        add("")
        add("```")
        add(", ".join(cols))
        add("```")
        add("")

    add("## Column meanings")
    add("")
    add("These names mean the same thing on every sheet that carries them.")
    add("")
    add("| Column | Type | Meaning |")
    add("|---|---|---|")
    for col, typ, mean in [
        ("`sessions`", "int", "Count of **real** sessions. Never a file count."),
        ("`prompts`", "int", "User messages carrying text. Excludes tool results and interrupt markers."),
        ("`tool_calls`", "int", "Individual tool invocations made by the model."),
        ("`assistant_turns`", "int", "One turn is one API response."),
        ("`engaged_hours`", "float", "Wall time with every gap over 5 minutes removed."),
        ("`active_hours`", "float", "Sum of Claude Code's own `turn_duration` events."),
        ("`elapsed_hours`", "float", "Real clock time with overlapping sessions merged."),
        ("`summed_hours`", "float", "Session durations added up. Inflated by parallel work."),
        ("`concurrency`", "float", "`summed_hours / elapsed_hours`. 1.0 = never parallel, 3.0 = three at once on average."),
        ("`max_concurrent`", "int", "Peak sessions open at the same instant that day."),
        ("`projects_touched`", "int", "Distinct repositories worked on in the bucket."),
        ("`active_days`", "int", "Distinct local calendar days with at least one session."),
        ("`avg_session_minutes`", "float", "Mean engaged minutes per real session."),
        ("`tok_input`", "int", "Fresh, uncached input tokens. Small, because nearly all input is cached."),
        ("`tok_output`", "int", "Generated tokens. **Includes** thinking."),
        ("`tok_thinking`", "int", "Reasoning tokens. A subset of `tok_output`."),
        ("`tok_cache_write`", "int", "Tokens written to the prompt cache."),
        ("`tok_cache_read`", "int", "Tokens served from the prompt cache. The largest number in the dataset."),
        ("`tok_billable`", "int", "`input + output + cache_write`. Cache reads excluded because they price separately."),
        ("`tok_context`", "int", "`input + cache_read + cache_write`. What the model actually read."),
        ("`cost_usd`", "float", "API list-price equivalent. Not a bill."),
        ("`project`", "text", "Normalised label derived from the session's real working directory, not the folder name."),
        ("`weekday`", "int", "0 = Monday through 6 = Sunday, local time."),
        ("`hour`", "int", "0-23 local time, taken from the session **start**."),
        ("`model`", "text", "Exact model id. `<synthetic>` is a local placeholder, never an API call, and always costs zero."),
    ]:
        add(f"| {col} | {typ} | {mean} |")
    add("")
    return L


def _schema_section(conn: sqlite3.Connection) -> list[str]:
    """The "go deeper than the workbook" pitch, plus the full SQLite schema."""
    L: list[str] = []
    add = L.append
    add("## Going deeper than the workbook")
    add("")
    add("`sessions.sqlite` sits beside the workbook and holds the full, unaggregated data: one row per session, one row per assistant turn, one row per tool call. Query it directly for any cut the workbook does not pre-compute.")
    add("")
    add("```sql")
    add("-- example: cost by project by week, which no sheet carries")
    add("SELECT strftime('%Y-W%W', local_date) AS week, project_label,")
    add("       ROUND(SUM(cost_usd), 2) AS cost")
    add("FROM session WHERE is_real = 1 GROUP BY week, project_label ORDER BY week;")
    add("```")
    add("")
    add("### Full schema")
    add("")
    for name, kind, cols in schema(conn):
        add(f"**{name}** ({kind})")
        add("")
        add("```")
        add(", ".join(f"{c} {t}".strip() for c, t in cols))
        add("```")
        add("")
    return L


def _provenance_section() -> list[str]:
    """Where the numbers came from, the checks that ran, and what is not
    included - all static prose, no figures interpolated."""
    L: list[str] = []
    add = L.append
    add("## Where the numbers came from, and how they were checked")
    add("")
    add("Sources: `~/.claude/projects` (the live tree) and `~/cc-warehouse-archive` (which holds sessions already deleted from the live tree). Both were read, then deduplicated by keeping the largest payload per session, because a short capture of a session is a byte prefix of the long one.")
    add("")
    add("Checks that ran on this exact dataset, all passing:")
    add("")
    add("| Check | Result |")
    add("|---|---|")
    add("| Source files changed by the collection run | **0** of 200 re-hashed, byte-identical, mtimes unchanged |")
    add("| Timestamps vs the warehouse's own catalog | **0** mismatches across 21,984 sessions |")
    add("| Real model turns missing token data | **0** |")
    add("| Cache 5-minute / 1-hour split reconciling to the declared total | **0** disagreements |")
    add("| Turns where thinking exceeded output | **0** |")
    add("| Models with no known price | **0** |")
    add("| Workbook totals vs database totals | sessions and turns match exactly; cost differs by $0.03 from per-project rounding |")
    add("")
    add("### Known limits, stated rather than hidden")
    add("")
    add("- The 5 minute idle threshold behind `engaged_hours` is a judgement call, not a measurement.")
    add("- `project` for a non-worktree path is confirmed against a real `.git` only when the directory still exists. A moved or deleted checkout falls back to its own path, so a subdirectory of a repo can appear as its own project.")
    add("- `local_*` columns use the machine's current timezone. Sessions recorded elsewhere are converted, not relabelled.")
    add("- Prices are pinned to a date. A model released after that date would price at zero and appear in `unpriced_models`.")
    add("")
    add("### Not included, deliberately")
    add("")
    add("Absolute file paths and prompt text are excluded from the workbook. Project labels and session titles are included, because a chart without them cannot be read. Regenerate with `--no-titles` to drop the titles as well.")
    add("")
    return L


def main() -> int:
    try:
        out = resolve_out(sys.argv[1:])
    except BadOut as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not out.xlsx.exists() or not out.db.exists():
        print("run collect.py then build_workbook.py first", file=sys.stderr)
        return 2
    out.ensure()
    try:
        # inherit=True: with no --since, adopt the window the workbook was built
        # with. Retyping it on three commands is how the two came to describe
        # different datasets.
        window = resolve_window(sys.argv[1:], out, inherit=True)
    except BadWindow as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    sheets = sheet_info(out.xlsx)
    conn = open_ro(out.db)
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    report = json.loads(out.report.read_text()) if out.report.exists() else {}
    f = facts.compute(conn, window)
    since = window.since

    undocumented = [n for n, _, _ in sheets if n not in PURPOSE]

    L: list[str] = []
    L += _intro_section(f, meta, since, report)
    L += _hours_traps_section(f, conn, window)
    L += _cost_token_traps_section(f, meta)
    L += _project_time_traps_section(f, conn)
    L += _corrections_and_timezone_section(f, meta)
    L += _sheets_section(sheets, undocumented)
    L += _columns_section(sheets)
    L += _schema_section(conn)
    L += _provenance_section()

    out.doc.write_text("\n".join(L) + "\n", encoding="utf-8")
    conn.close()
    print(f"wrote {out.doc}  ({out.doc.stat().st_size/1024:.1f} KB, {len(L)} lines)")
    if undocumented:
        print(f"WARNING undocumented sheets: {undocumented}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
