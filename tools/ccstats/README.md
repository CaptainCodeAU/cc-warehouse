# ccstats: Claude Code session statistics

A read-only collector that turns every session transcript on this machine into a
queryable dataset for plotting. Scratch tooling, tracked here so it cannot be lost
the way an untracked `temp/` folder can, but not part of `ccw`: not subject to
pyright strict, the oracle suite, or the packaging test (see the repo's own
`pyproject.toml` / `tests/test_packaging.py`, both of which exclude `tools/`). See
`Plans/there-are-unexplored-code-async-ripple.md` for the reasoning and the
measurements behind every design choice.

## Run it

```
uv run python3 tools/ccstats/verify.py snapshot     # fingerprint the sources
uv run python3 tools/ccstats/collect.py             # scan everything, ~22 s
uv run python3 tools/ccstats/build_workbook.py --since 2026-06-08   # the .xlsx
#   the window is recorded in export-manifest.json; the two commands below
#   inherit it, so it is stated ONCE
uv run python3 tools/ccstats/make_docs.py            # inherits the window
uv run python3 tools/ccstats/check_consistency.py   # inherits the window
uv run python3 tools/ccstats/dashboard.py            # the LIVE interactive dashboard
uv run pytest tools/ccstats/tests -q                # 99 tests
uv run python3 tools/ccstats/verify.py compare      # prove nothing changed
```

Every command above accepts `--out DIR` to write somewhere other than the
default (see **Where it writes**, below).

Inside Claude Code, working in this repo, `/dashboard` does the last of those (`dashboard.py`)
for you interactively - see **The live dashboard**, below.

| Script | Does |
|---|---|
| `collect.py` | the one pass over every transcript; writes `sessions.sqlite` and 9 CSVs |
| `build_workbook.py` | 20 pre-aggregated sheets as `claude-code-stats.xlsx` (`--no-titles` to strip session titles) |
| `make_docs.py` | `DATA-GUIDE.md`, generated from the workbook so it cannot drift |
| `dashboard.py` | `claude-code-dashboard-live.html`: one file, live date-range + project-exclude controls, no re-run needed to change them (see below) |
| `xlsx.py` | a dependency-free .xlsx writer (the project is stdlib-only) |
| `facts.py` | the numbers quoted in prose, computed once so the two artefacts cannot disagree |
| `check_consistency.py` | fence: asserts the workbook and the guide state the same figures |
| `verify.py` | proves read-only by execution and reconciles against `catalog.sqlite` |
| `common.py` | paths, the write-root resolver and its fence, the cost disclaimer, the ONE `--since`/`--until` window implementation |
| `tests/` | 99 tests, one per defect found (plus the `--until` coverage). `uv run pytest tools/ccstats/tests -q` |

## The live dashboard

**Quickest way to build and open it:** inside Claude Code, working anywhere in this repo, type
`/dashboard`. It's a project-local slash command (`.claude/commands/dashboard.md`, only usable in
this project) that:

1. Asks whether to refresh the underlying data first (skipped automatically on a first run, since
   there is nothing to refresh yet).
2. Asks which projects to hide first (or reuses your answer from last time - saved privately at
   `dashboard-defaults.json` beside the dashboard itself, same folder, same "never commit, never
   upload" rule).
3. Runs the build below for you.
4. Serves the result over a local link and hands it to you (a plain `file://` path is refused by
   the browser tool, so this is needed even for a local file).
5. Shuts that link down once you confirm you're done looking - the page keeps working in an
   already-open tab either way, since everything is baked into the one file.

Tested end to end 2026-08-23 via a separate Claude Code session (driven through Herdr) and a real
Chrome tab: build, serve, live filter interaction, and shutdown all confirmed working, with zero
console errors and the real `~/.cc-warehouse/stats/` files left untouched (the test used
`CCSTATS_OUT` to point everywhere at a scratch folder instead - see Step 0 of the command file).

Read the command file itself for the exact steps `/dashboard` follows. The rest of this section
explains what it's building and why, for anyone running `dashboard.py` by hand instead.

**Editing or adding a panel?** Read `PANEL-CONTRACT.md` first, plus one example panel in
`dashboard_template.html` - not the whole 1,170-line file. It documents the shared data model,
chart helpers, and house rules every panel follows.

`dashboard.py` queries `sessions.sqlite` directly (not the pre-aggregated CSVs,
which are already summed over one fixed window) and embeds a compact
per-session dataset into `claude-code-dashboard-live.html`: every session's
date/hour/weekday, project, repo, engaged/wall/active seconds, cost, token
breakdown, prompt/tool-use/turn counts, worktree flag, model and CC version,
plus per-session model/tool/skill breakdowns and the `overlap_day` table, all
as row-major arrays referencing small lookup tables (project/repo/model/tool
names), never repeated per row.

Open the file in a browser. A sticky bar at the top has a date-from, date-to
and a searchable project-exclude checklist; every panel below redraws from
that one choice, entirely in the page's own JavaScript, with no re-run and no
network request. `--since`/`--until` on the command bound what gets embedded
(a smaller file, if wanted); they do not need to match the range a reader
starts on, which the page's own date pickers default to the embedded data's
full span.

The Overview panel carries 15 KPI tiles matching the definitions in `facts.py`
where one exists (engaged/wall/active hours, prompts, tool uses, assistant
turns, tokens, cost) plus a couple invented for this page in the same spirit
(median/mean session length, the missing-active-day callout), all in plain
operator-facing wording (a "sessions with a reply" tile, not a raw
"is_real" one). Dollar figures are `US$`, not bare `$`. The two naive-vs-
corrected number pairs (engaged vs. session-span hours, median vs. mean
session length) read as one sentence with the naive figure in parentheses,
not a struck-through line - the operator found the strikethrough itself
ugly, independent of the numbers being right. No "vs. the full embedded
range" comparison text anywhere in these tiles (operator: "everything else
becomes noise") - EXCEPT that `time with a session open` and
`most sessions running at once` are still computed whole-corpus under the
hood (real interval-overlap math, can't be sliced by project with the data
embedded); the caveat text is gone from the page, so that limitation is
recorded here instead. The API-cost tile's model breakdown is by FAMILY
(opus/sonnet/haiku/fable), not by version - `claude-opus-4-8` and
`claude-opus-5` count as one `opus` share. No chart library: a small custom
tooltip (`data-tip` + one delegated hover handler, replacing the native SVG
`<title>`), a scroll-reveal fade-in per panel, and a brief cross-fade on
filter change are all plain CSS/JS, honouring `prefers-reduced-motion`.

One dark theme, not a light/dark toggle (operator preference, 2026-08-21):
every color lives in one `:root` block, including the JS chart-drawing
constants (they read `var(--signal)` etc from the same block, via an inline
`<svg>`'s normal CSS cascade, rather than duplicating hex values). Contrast
checked against WCAG AA (4.5:1) for every text/background pair, not
eyeballed - the one that fell short (chart axis labels) was tuned up; it was
still an improvement on the original static dashboard's own equivalent.

The page opens to 2026-06-08 onward by default (operator preference,
2026-08-21), not the full embedded range - widen it with the date pickers.
`--exclude SUBSTRING` / `--include SUBSTRING` (both repeatable) bake a
starting checklist state into the page: every project is still embedded and
still choosable either way, this only sets what's ticked when the page first
opens, and Reset restores it. Substring, not exact-match: a pattern matches
`project_label` if it appears anywhere in it, so a project_label is itself a
valid (exact-match) pattern. `--exclude` is a denylist; `--include` is an
allowlist; given both, `--exclude` narrows `--include`'s allowlist further.
A pattern matching nothing only warns at build time (stderr), it does not
fail the build. The project-filter popup itself is wide (`min(96vw,900px)`)
so nearly every name fits on one line; the rare 100+ character
auto-generated name (measured: 118 labels, avg 49.8 chars, max 196) still
truncates with an ellipsis rather than blowing the popup out for everyone,
with the full name available via a hover title.

**Scope, stated rather than hidden**: `Concurrency` reads from `overlap_day`
(real interval-overlap math, not a per-session sum) and narrows only with the
date range, not the project-exclude filter, which the panel itself says.
`Worktrees` reports counts only (no `worktree_name` breakdown). `Top sessions`
shows the top 50 by cost in range, not 200. Every other panel is fully live on
both filters.

## Where it writes

Everything lands in **`~/.cc-warehouse/stats/`** by default: outside this repo
(a tracked folder inside it is a second publication surface, the same reason
`~/cc-warehouse-stats/` was never inside the repo either) and untracked, since
it holds real absolute paths, project names and a prompt preview per session.

Override with `--out DIR` on any command, or set `CCSTATS_OUT` once so every
command agrees without repeating the flag (`--out` wins if both are given).
`resolve_out` (in `common.py`) refuses a destination inside `~/.claude`, the
archive, the warehouse data root, or this repository, the same way `--since`
refuses an unpadded date: loudly, before any write happens.

| File | What it is |
|---|---|
| `sessions.sqlite` | the dataset: `session`, `turn`, `tool_call`, `attribution`, `overlap_day`, `meta`, plus 6 views |
| `sessions.csv` `turns.csv` | raw rows, one line per session / per assistant turn |
| `projects.csv` `daily.csv` `hourly.csv` `models.csv` `tools.csv` `attribution.csv` `overlap.csv` | the views, ready to plot |
| `collect-report.json` | what was scanned, the totals, and the self-check results |
| `claude-code-dashboard-live.html` | the interactive dashboard (see **The live dashboard**, below) |

## Verify it

```
uv run python3 tools/ccstats/verify.py snapshot   # BEFORE
uv run python3 tools/ccstats/collect.py
uv run python3 tools/ccstats/verify.py compare    # AFTER
```

`compare` re-hashes 200 source transcripts and fails if a single byte or mtime
moved, and reconciles timestamps and line counts against `ccw`'s own
`catalog.sqlite`. The read-only claim is proved by execution, not by reading the
source, because this project has been burned by a read-only-looking command
before.

## Safety

- Reads with `read_bytes()` only. No `unlink`, `rmtree`, `os.remove`, `shutil`.
- The only directory written to is the resolved output root (see **Where it
  writes**), fenced against `~/.claude`, the archive, the warehouse data root
  and this repository however it is set.
- `sessions.sqlite` is published by building into a fresh temp file beside it
  and `os.replace`-ing it onto the target: one atomic rename, never a delete,
  and never a second copy left behind. This replaced a real leak: earlier
  versions renamed the previous database aside to `sessions.sqlite.prev` on
  every run and never removed it, permanently doubling a 137 MB file. A crash
  mid-build can leave an orphaned `*.sqlite.building` file; it is reported (in
  `collect-report.json` under `stale_building_files`) and left for the
  operator to remove, never deleted automatically.
- Never touches `~/.claude`, the archive, or the warehouse.
- The output folder holds real absolute paths, project names and a prompt
  preview per session. **It must never be committed.** It sits outside the repo
  for that reason.

## Timezone

`local_date`, `local_hour` and `local_weekday` are rendered in the zone
**cc-warehouse's own config pins**, read from `archive_timezone` in
`~/.config/cc-warehouse/config.toml` (or `$XDG_CONFIG_HOME`, then
`<data-root>/config.toml`).

That file is the authority, not the machine clock, and its own comment says why:
the zone is pinned "so the same session yields the same folder name on any
machine forever". The archive tree is already named in that zone, so deriving
these columns from anything else would put the statistics and the folder names
in two different times.

Order: `CCSTATS_TZ` env -> config `archive_timezone` -> machine
`/etc/localtime` -> a fixed offset. An unknown zone in the config is ignored
rather than raised, matching `config._archive_timezone` (R5). Whichever source
applied is recorded in `meta.local_timezone_source`, in `collect-report.json`,
in the workbook's README sheet and in `DATA-GUIDE.md`, so a page built from this
data can print it.

## Reading the numbers

### Three different "hours", and they are not interchangeable

| Column | Means | Use it for |
|---|---|---|
| `wall_seconds` | last timestamp minus first | how long a session stayed open |
| `engaged_seconds` | wall time with every gap over 5 minutes removed | actual time at the keyboard |
| `active_seconds` | sum of Claude Code's own `turn_duration` events | time the model was working |

`wall` is far larger than the other two because sessions get left open. `engaged`
and `active` are derived independently and land close together, which is the
cross-check that either can be trusted.

`overlap_day` is the fourth number and the important one for any "hours per day"
chart: `summed_hours` adds every session up, `elapsed_hours` merges overlapping
sessions into real clock time, and `concurrency` is the ratio. Several sessions
run at once on this machine, so summing durations overstates a day badly.

### `is_real` is not optional

About 63% of transcript files have no assistant turn at all. They are SDK,
hook and sub-agent launches, or prompts that were interrupted before a reply.
They are still real files with real timestamps, so they are kept, but any
"sessions per project" chart must filter `WHERE is_real = 1` or it overstates by
roughly 2.7x.

### Tokens

- `tok_thinking` is a **subset** of `tok_output`. Never add them.
- `tok_billable_total` = input + output + cache writes. Cache reads are excluded
  because they are priced separately, at a tenth of the input rate.
- `tok_context_total` = input + cache read + cache write, which is what the model
  actually saw. This is the number that shows how much context work happened.
- Cache writes are split into `_5m` and `_1h` because the 1 hour tier costs 2x
  the input rate against 1.25x for 5 minutes, and most writes here are the 1h tier.

### What the dollar column is not

`cost_usd` is what this usage **would** have cost at Anthropic API list prices,
pinned in `PRICES` at the top of `collect.py` (re-checked 2026-08-23 against the
live pricing page; `PRICES_READ_ON` in that file is the source of truth for the
date, not this README). It is a usage-weight number for comparing projects and
periods.

**It is not a bill.** Claude Code subscription usage is not billed per token. Do
not present this figure as money spent.

A model id that does not resolve to a known price is counted as **zero** and
listed in `collect-report.json` under `unpriced_models`, so a newly released
model can never quietly deflate the totals. Check that field after every run.

`<synthetic>` is not an unpriced model. It is a placeholder turn Claude Code
writes locally when a reply is interrupted, so there is no API call and no cost.

## Handy queries

```sql
-- top projects by real sessions and cost
SELECT project_label, sessions_real, engaged_hours, cost_usd FROM v_project LIMIT 20;

-- daily timeline, honest hours
SELECT local_date, sessions, elapsed_hours, summed_hours, max_concurrent
FROM overlap_day ORDER BY local_date;

-- when do I actually work (0 = Monday)
SELECT local_weekday, local_hour, engaged_hours FROM v_hourly;

-- which tools and skills do I really use
SELECT * FROM v_tool LIMIT 25;
SELECT * FROM v_attribution WHERE kind = 'skill';

-- worktrees only
SELECT worktree_name, COUNT(*) FROM session WHERE is_worktree = 1 GROUP BY 1;
```

## Known limits, stated rather than hidden

- Sessions are deduplicated by picking the **largest** payload per identity. This
  is an ordering comparison, never an equality test. Between two captures of one
  session the short one is a byte prefix of the long one.
- `repo_root` for a non-worktree path is confirmed by walking up to a `.git` only
  when the directory still exists. A deleted or moved checkout degrades to its
  own cwd, so a subdirectory of a repo can appear as its own project.
- The 5 minute idle threshold (`IDLE_GAP_SECONDS`) is a judgement call, not a
  measurement. Change it and re-run if it does not match how you work.
- Local date and hour use this machine's current timezone. Sessions recorded in
  another zone are converted, not relabelled.
