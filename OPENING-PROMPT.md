# Opening prompt for a fresh session, 2026-08-22 (fifth handoff, item 2 now fully closed)

## Next task: ticket 27.5-27.8 (item 3 below). Items 1 and 2 are BOTH fully
## DONE. Read "One loose end inside item 2" just below before starting item 3
## - it is small, but it is a real unanswered question, not a settled one.

### One loose end inside item 2, not urgent, not blocking

The prior session's second open thread (deterministic generation of
`dashboard_template.html`) WAS investigated this session, by a sub-agent, in
depth as asked. Measured, not guessed: the file is 1,118 lines / 59,228
bytes, ~55% mechanical (CSS palette, SVG/JS chart primitives, effects/
controls wiring - already factored into shared functions, called once each,
so there is little duplicated boilerplate left to extract) and ~45%
editorial (the 20 panel definitions, 469 lines, each mixing bespoke
aggregation logic with bespoke caption wording - inherently not scriptable).

The sub-agent's recommendation was NOT a codegen script. It was: write a
short "panel contract" doc so a future edit reads that doc plus one example
panel, instead of the whole 1,118-line file - the real cost driver is
context size, not duplicated code, and a small CSS-palette codegen would
save little (15 lines, rarely edited).

This was put to the operator as a 2-option decision (write the doc now /
skip). **The operator never picked either option** - the conversation moved
straight into giving the `--include`/`--exclude` list instead, and it was
never revisited across the rest of the session despite four more rounds of
dashboard work landing on the exact file this would apply to. Nothing was
written. Ask the operator before doing anything here; do not assume "yes"
just because the file has since had six more rounds of hand-edits that a
panel-rules doc would have made cheaper.

---

## The order, with the reasoning

### 1. Protect `temp/ccstats/` and stop its disk leak - DONE 2026-08-21

**Correction, found while doing this**: the handover line above said "136 MB
left behind per run". It was not per run: `Path.replace()` overwrote the same
`.prev` every time, so exactly one stale copy existed at any moment (measured:
`sessions.sqlite` 143,695,872 bytes, `.prev` 143,646,720 bytes, one of each).
The defect was a permanent doubling of a 137 MB file, not a growing pile.

Two operator rulings taken this session:

- **Code -> `tools/ccstats/`.** Tracked, outside `src/`, no contract ruling
  needed. `src/cc_warehouse/` as a `ccw stats` verb is still open, blocked on
  the `contract/BRAINSTORM.md` warehouse-vs-`cc-vantage` line; NOT attempted.
- **Generated files -> `~/.cc-warehouse/stats/`**, outside the repo and
  untracked, overridable with a new `--out DIR` flag (or `CCSTATS_OUT` env).
  **`~/cc-warehouse-stats/` (the old location, 373 MB including the old
  `.prev`) was explicitly left alone during this work.** The operator then
  deleted it themselves later the same session, once `CHART-BRIEF.md` (the
  one file only that folder held that the new one did not) was moved across
  by hand. **`~/cc-warehouse-stats/` no longer exists; confirmed gone
  2026-08-21.** `~/.cc-warehouse/stats/` is now the only copy and holds all 20
  files, `CHART-BRIEF.md` included.

What changed: `temp/ccstats/` -> `tools/ccstats/`, committed. `common.py` gained
`resolve_out`/`Out`, replacing 5 copies of a hardcoded `OUT_DIR` with one
resolution, fenced against `~/.claude`, the archive, the warehouse data root
and this repo (refuses loudly, like `parse_since` does for a bad date).
`collect.py`'s `.prev` rename is gone, replaced by `tempfile.mkstemp` +
`os.replace` (DESIGN R2's own idiom): the live database is only ever replaced
by a complete build, a crash mid-build can no longer corrupt it, and a leftover
`*.building` file is reported (`collect-report.json` -> `stale_building_files`)
rather than auto-deleted. `pyproject.toml` and `tests/test_packaging.py` both
gained `tools` in their exclude/`FORBIDDEN_DIRS` lists, keeping the sdist clean
(verified by building a real sdist: `tools` absent from its 162 members).

Verified: all three gates green (ruff, pyright, 1,112-test oracle suite,
including `test_packaging.py`); the ccstats suite grew from 72 to 86 tests (one
per new behaviour) and passes; a full real-data run (`verify.py snapshot` ->
`collect.py` -> `build_workbook.py --since 2026-06-08` -> `make_docs.py` ->
`check_consistency.py` -> `verify.py compare`) landed in `~/.cc-warehouse/stats/`
with 0 problems, `check_consistency.py` reporting all 14 shared figures
consistent; a second `collect.py` run left exactly one `sessions.sqlite` and no
`.prev`/`.building` file, anywhere; `--out` writes to an arbitrary directory and
is refused for `~/.claude`.

### 2. Build an interactive stats dashboard - DONE, CLOSED 2026-08-22

**Both threads this file used to hand to "the next session" are now
resolved.** The `--include`/`--exclude` list was given and applied (see
below). The codegen investigation ran and its outcome is the loose-end note
at the very top of this file. Everything below this line, through "Fourth
round", is history kept intact rather than rewritten; skip to "Fourth round"
for what actually changed most recently.

The operator wants a browser dashboard, like the one already sitting at
`~/.cc-warehouse/stats/claude-code-dashboard.html`, but with two live controls:
a date range (start AND end) and a list of projects to EXCLUDE. "How you build
it is up to you" - the operator's own words - but being able to change the
range and the exclude-list themselves, without asking anyone to re-run
anything, is the actual ask, so treat "if possible" as "strongly preferred",
not as optional.

**What the existing dashboard actually is, measured, not guessed:**

- 270 KB, one file, no external assets. 19 `<svg>` charts, 1 `<table>`, and
  exactly one `<script>` block - and that block is ~250 bytes of scroll-reveal
  animation (`IntersectionObserver`), nothing to do with data.
- It carries **no embedded JSON, no chart library, no client-side filtering at
  all.** Every chart is a static SVG baked once, at generation time, for one
  fixed window (its `<title>` literally says "Claude Code usage - 2026-06-08
  to 2026-08-21").
- **Nothing in this repo built it.** It was built by Claude Chat for Web
  (claude.ai), reading three files by hand: `claude-code-stats.xlsx`,
  `DATA-GUIDE.md`, `sessions-real.csv`. `CHART-BRIEF.md` (moved into
  `~/.cc-warehouse/stats/` by the operator this session) is the actual brief
  that was used to build it - **READ IT FIRST.** It carries hard rules that
  must carry over to anything new: chart `engaged_hours` only, never
  `active_hours`; label the cost axis "API list-price equivalent, not billed
  spend"; print the timezone (`Australia/Melbourne`, from cc-warehouse's own
  config, not the machine clock) beside any hour-of-day chart; `project_label`
  (80 rows, what was actually worked in) vs `repo_root` (67 repos,
  subdirectories folded into their parent) are DIFFERENT keys and any panel
  must say which one it uses; both end months of a window are partial and must
  say so on the chart itself, not only in prose.
- That brief's own decision #1 says the current dashboard deliberately has NO
  client-side filtering, because the window was fixed before the data was
  handed over. That decision is exactly what the operator now wants reversed.

**The real gap, and why this is not a copy-paste job:**

A live date range needs BOTH ends. `common.Window` (`tools/ccstats/common.py`)
only has `since`. `--until` does not exist anywhere in `ccstats` yet - it was
already named as missing polish in item 7 below, written before this request
existed. Adding the `until` half to `Window` is very likely a PREREQUISITE
here, not extra scope layered on top.

Project EXCLUSION does not exist in any form. `Window` has never filtered on
`project_label`. This is new, not an extension of something that half-exists.

**The design call to make first, before writing any code:**

Two shapes, genuinely different amounts of work. The operator said "how you
want to do it is up to you" - so the next session should pick one and say why,
or ask, rather than default to whichever is fastest to type:

1. **Regenerate on demand.** A new script (maybe `tools/ccstats/dashboard.py`)
   takes `--since`, `--until`, `--exclude-project NAME` (repeatable) and bakes
   ONE static HTML, same editorial style as today's, for exactly that slice.
   Changing the range means re-running a command. Cheapest, and it is the same
   shape every other ccstats script already uses (`resolve_out`, `Window`, one
   pass over `sessions.sqlite`).
2. **Live in the browser.** Generate once, embed a small aggregate (most
   likely per `local_date` x `project_label`: hours, cost, sessions, tokens -
   NOT full per-session rows, which would run to tens of MB) as JSON in the
   page, and write vanilla JS (no CDN; this project is self-contained by
   habit) that recomputes totals and redraws the SVGs whenever the date
   pickers or the project checklist change. Matches "I want to be able to
   specify..." more literally - it reads as a live control, not a re-run trigger.
   More work: the SVG-drawing logic has to exist in JS too, not only Python.

Recommendation, not a decision made here: **(2).** The operator's own words
were about changing things themselves, which is what "specify" usually means
when someone says it about a UI, not about re-running a script. But this is a
real fork with a real cost difference, so confirm before committing to it.

**Where the data comes from:** `~/.cc-warehouse/stats/sessions.sqlite`, table
`session` (`local_date`, `project_label`, `repo_root`, `engaged_seconds`,
`cost_usd`, the token columns, `is_worktree`, `is_real`; open read-only via
`common.open_ro`, exactly like every other ccstats script). The pre-aggregated
CSVs (`daily.csv`, `projects.csv`, etc.) are already summed over the WHOLE
current window and cannot be re-sliced by excluding one project without
re-querying the database.

**Privacy, non-negotiable:** this file holds real project labels (folder
names) per session - the same thing the existing dashboard already ships, and
the operator already treats as fine to keep local. It must stay a LOCAL file
under `~/.cc-warehouse/stats/`, opened straight from disk in a browser, and
must NEVER be uploaded via the Artifact tool or any other external host: that
folder is explicitly gitignored and "must never be committed" per
`tools/ccstats/README.md`'s own Safety section, and an upload would publish
that same private data externally regardless of who is asked to view it.
**The dashboard's own on-page reminder of this ("this file is private, do not
upload it") was removed 2026-08-22 along with the Caveats panel it lived in -
see "Fourth round" below. The rule itself still applies in full; only the
on-page text is gone.**

**DONE 2026-08-21. Option 2 (live in the browser) was chosen, confirmed with
the operator first via a decision table + AskUserQuestion, per their standing
format preference.** The operator's own follow-up sharpened the ask further:
one filter bar at the TOP of the page, applying to every panel underneath -
explicitly not a per-section control. Built that way.

What shipped: `tools/ccstats/dashboard.py` (new) queries `sessions.sqlite`
directly - `session`, `turn`, `tool_call`, `attribution`, `overlap_day` - and
embeds a compact per-session dataset (row-major arrays against small
project/repo/model/tool lookup tables, never a repeated string per row) into
`tools/ccstats/dashboard_template.html` (new, the CSS/JS shell, reusing the
static dashboard's exact design tokens - paper/ink/signal-red palette, Arial
Narrow + Georgia + monospace, the hatch pattern for partial data) via a
`/*__CCSTATS_DATA_JSON__*/` marker substitution. Output:
`claude-code-dashboard-live.html`, one file, no external assets, no network
calls, no build step. `common.py` gained `--until` (`parse_until`,
`Window.until`, all five `Window` SQL-form properties extended) - the
prerequisite item 7 already flagged; closed here instead of twice.

19 panels, all reading `sessions.sqlite` directly rather than the
pre-aggregated CSVs (which are already summed over one fixed window and
cannot be resliced): Overview, Daily, Weekly, Monthly (partial-month
detection now keys off the READER's chosen range, not a fixed window),
Session sizes, Projects, Repositories, Project x month, Models, Model x
month, Tokens, Thinking, Hour heatmap, By weekday, Tools, Skills & agents,
Worktrees, Top sessions, CC versions, plus a static Caveats panel. CHART-BRIEF
rules carried over and checked by execution, not assumed: engaged_hours only
(never active_hours), the Melbourne timezone label, is_real=1 filtering, the
"cost is not a bill" disclaimer placed ON the four cost-primary charts
themselves (Projects/Repositories/Models/Model x month), not only in prose,
and the 2026-08-12 thinking-token recording-start date stated on that panel.
**CC versions and Caveats were both REMOVED 2026-08-22, see "Fourth round".**

**Scope trims, stated rather than hidden**: Concurrency reads whole-corpus
`overlap_day` (real interval-overlap math, not reconstructable from a
per-session duration) and narrows only by date, not by the project filter -
the panel says so. Worktrees reports counts only, no `worktree_name` list.
Top sessions shows 50, not 200. Every other panel is fully live on both
filters, wired to the one filter bar per the operator's requirement.
**Top sessions is now 25, not 50, and Concurrency's bars are now weekly, not
daily - see "Fourth round".**

**Verified, not just eyeballed**: no browser was available this session
(`mcp__claude-in-chrome` reported "Browser extension is not connected"), so
correctness was proved a different way. `uv run pytest tools/ccstats/tests -q`
- 99 tests (86 prior + 13 new for `--until`), ruff clean. The generated file's
actual `<script>` block was executed HEADLESS under Node (`vm.runInContext`
against a minimal `document` stub) three ways: (1) default full range, 0 of
19 panels threw, KPI totals (9,628 sessions, 1,509.5h, $78,051.13) matched an
independent recomputation done separately from the embedded JSON, not through
the dashboard's own code; (2) a real filtered scenario (July 2026, the
busiest project excluded) also matched an independent recomputation exactly
(1,989 sessions, 275.45h, $18,445.69 both ways); (3) a genuinely empty date
range (2020-01-01..02, 0 sessions) rendered 0 panel errors, the actual risk
case for divide-by-zero on an empty array. What was NOT verified: how it
actually looks and behaves in a real browser (mouse clicks on the project
checklist, the sticky bar's scroll behaviour, visual match to the static
dashboard's spacing) - Node proves the math and that nothing throws, not
pixel rendering. **A real browser WAS available 2026-08-22 and was used
extensively - see "Fourth round".**

Also fixed along the way: `tests/test_ccstats_fences.py::test_no_module_can_
delete_anything` caught a real defect before it shipped - the first draft of
`dashboard.py`'s atomic write called `.unlink()` on its own temp file when a
write failed. Rewritten to match `collect.py`'s own idiom exactly: build into
a `.building` file, one `os.replace`, and on failure leave it for the
operator rather than auto-deleting it. The fence did its job.

**Addendum, same session, two operator follow-ups after seeing the first cut:**

1. The Overview panel above shipped with only 5 KPI tiles. The operator
   attached a screenshot of the STATIC dashboard's Overview (15 tiles) and
   asked for the same depth. `facts.py` (the "numbers quoted in prose"
   module) turned out to be the wrong source for most of them - it was
   written for the .xlsx/DATA-GUIDE.md pair, not the HTML dashboard, which
   was built separately by a different process reading raw CSVs by hand and
   inventing its own KPI set (median/mean session, the missing-day callout).
   Matched anyway, mostly by inference from the screenshot's own wording plus
   `facts.py`'s confirmed formulas (`wall_h`, `active_h`, `elapsed_h` from
   `overlap_day`, `SUM(n_user_prompts)`/`SUM(n_tool_uses)`/
   `SUM(n_assistant_turns)` at the session-row level, never the child
   tables). `dashboard.py`'s `S` rows grew 5 columns (`wall_seconds`,
   `active_seconds`, `n_user_prompts`, `n_tool_uses`, `n_assistant_turns`) to
   support it. All 15 tiles are reactive to both filters except three
   explicitly marked otherwise (session-open hours and peak-concurrent stay
   whole-corpus, date-range only, same reason as the Concurrency panel; the
   two "full embedded range" comparison tiles deliberately read from the
   UNFILTERED `DATA.S`, on purpose, since that is the whole point of a
   concentration/drop-off figure).

   Verification here found and corrected ITS OWN false alarm, worth recording
   because it is the exact shape [[explain-only-what-you-measured]] warns
   about: a first check used `ntile(1000)` in SQL to estimate the median
   session length and got ~28.5s, versus the dashboard's computed 11.6s (0.2
   min), a 2.5x gap that looked like a real bug. It was the CHECK that was
   wrong, not the code: `ntile` distributes 9,628 rows into 1,000 buckets
   unevenly on a heavily right-skewed distribution, so "bucket 500" is not
   actually the 50th-percentile position. An exact `ROW_NUMBER()`-based
   median gave 11.634s, matching the dashboard exactly. Confirmed a second,
   independent way: narrowing the date picker to 2026-06-08 onward (close to
   the original screenshot's own window) reproduced the screenshot's "75
   days / 72 active / 3 missing" figure exactly, INCLUDING the same three
   missing dates (24 Jun, 27-28 Jul) and the same "1.1 min" median - strong
   evidence the formula, not just the arithmetic, matches what built the
   original.

2. The operator also asked, separately, whether a real charting LIBRARY
   could give the page more "effects" - it read as static next to the
   original. Answered by explaining the tradeoff rather than guessing what
   they meant: this project's own stated habit is "no CDN, self-contained by
   habit" (from this very item's investigation section above), and a real
   library like D3 would mean vendoring 100-250 KB inline or breaking the
   single-file/no-network guarantee the privacy section demands. Built the
   vanilla equivalent instead: a custom styled tooltip (`.cc-tooltip`,
   replacing the native SVG `<title>`, which is slow and unstyled - every
   chart's `<g><title>` wrapper became a `data-tip` attribute read by one
   delegated `mouseover`/`mousemove`/`mouseout` handler), a hover-brighten on
   every bar/cell (`rect.mark:hover`), an `IntersectionObserver` scroll-
   reveal fade-in on each panel (mirrors the ORIGINAL static dashboard's own
   ~250-byte technique, mentioned in this item's investigation section
   above), and a brief cross-fade on `#panels` when a filter changes. All
   respect `prefers-reduced-motion`. NOT built: animated bar-height
   transitions on filter change (would need persistent per-bar DOM nodes
   instead of the current full-innerHTML-replace redraw, a bigger structural
   change) - noted as a possible follow-up, not attempted.

   The three Node correctness harnesses (full range, a real filtered
   scenario, and the Overview cross-check) all needed their own DOM stubs
   extended (`document.createElement`, `document.body`, `querySelectorAll`)
   to keep running headless after the effects landed - none of that code
   path had existed before. Re-ran all three after both rounds: 0 panel
   errors, all totals still matched independent recomputations exactly, 99
   tests still green, ruff clean.

**Third round of follow-ups, same session, all DONE 2026-08-21**: the
Overview panel grew from 5 to 15 KPI tiles (matching a screenshot of the
static dashboard's own Overview, cross-checked against `facts.py` where a
definition existed there); dollar figures switched to `US$` everywhere;
default start date set to 2026-06-08 (was the earliest embedded date); a
`--exclude-project` flag was added, then GENERALIZED the same session into
`--include`/`--exclude` (both repeatable, substring match against
`project_label`, `--include` an allowlist and `--exclude` a denylist that
narrows it further) after the operator asked for partial-name matching
rather than exact project names; the two strikethrough "naive number"
comparisons became plain parenthetical text (operator: "the strikethrough is
absolutely hideous"); every "vs. the full embedded range" comparison was
removed from the 15 tiles at the operator's explicit request ("everything
else becomes noise") - two tiles (`time with a session open`,
`most sessions running at once`) are STILL whole-corpus under the hood
(real interval-overlap math can't be sliced by project with the data
embedded), the caveat text is just gone from the page now, flagged to the
operator in chat rather than on the page; the API-cost tile's model
breakdown was changed from per-version to per-FAMILY (opus/sonnet/haiku/fable,
version numbers summed together) using a simple leading-letters regex on the
model string; the project-filter popup was widened twice, finally to
`min(96vw,900px)` with per-item ellipsis truncation for the rare 100+
character auto-generated names (measured: 118 distinct labels, avg 49.8
chars, max 196 - only ~14 exceed 80 chars) plus a `title` attribute so a
truncated name is still readable on hover. Every change re-verified the same
way as the rounds before it: real database cross-checks (model-family
percentages, substring-match counts, allowlist+denylist composition all
independently confirmed against direct SQL/counts), 99 tests, ruff clean.

**Fourth round, 2026-08-22 session, item 2 fully CLOSED.** A real browser was
available this whole session (`mcp__claude-in-chrome`). One environment note
worth keeping: `file://` URLs are refused by the navigate tool ("Can't
interact with browser-internal or unparseable URLs") even with a fresh tab,
tried three times. Worked around by serving `~/.cc-warehouse/stats` with
`uv run python3 -m http.server 8721 --bind 127.0.0.1` (loopback only) each
time a visual check was needed, then killing it after. Reuse this pattern
rather than re-discovering it.

1. **The operator's real `--include`/`--exclude` list, given this session and
   applied.** Final exclude list (no include list given, so nothing is
   allowlisted - everything not excluded stays ticked): `private-`,
   `<local-username>-`, `Tools-google-auth-2fa-exporter`, `Tools-clawfidence`,
   `Scripts-littlesnitch_blocklist`, `Scripts-devtools-snippets`,
   `Scaffoldings-`, `Playground-skills_playground`, `Ideas-Whryte_app_clone`,
   `Ideas-GitFoot_FluidAudio_vanilla`, `Ideas-Browser_Automation_System`,
   `CaptainCodeAU-Tax_`, `CaptainCodeAU-claude-code-transcripts`,
   `CaptainCodeAU-EXTENSIONS-`, `CaptainCodeAU-Proxmox-`,
   `CaptainCodeAU-Plex_Server`, `CaptainCodeAU-SCAFFOLDINGS-`, `3rdParty-`,
   `CaptainCodeAU-tax`, `CaptainCodeAU-wisdom_grabber`, `Ideas-GitFoot`,
   `CaptainCodeAU-hermes`, `CaptainCodeAU-cc-print-shop`. Printed the live
   118-project list from `sessions.sqlite` first so the operator could
   copy/paste real names rather than guess them; two case-mismatch misses
   (`CaptainCodeAU-tax-data-sprint` vs `Tax_`, `CaptainCodeAU-SCRIPTS-` vs
   `Scripts-`) were caught and flagged before the operator asked for
   case-insensitive matching outright.

2. **Case-insensitive `--include`/`--exclude` matching.** `resolve_unticked()`
   in `dashboard.py` lower-cases both sides before the substring check (was
   exact-case `pattern in name`). Verified with a probe insert/compare, not
   just by re-running the build.

3. **Default end date now tracks the reader's real "today"**, not the day
   the file was built. `todayLocal()` (local, not UTC, calendar date) +
   `DEFAULT_TO = todayLocal() < DATA.max_date ? todayLocal() : DATA.max_date`
   added to `dashboard_template.html`; `DEFAULT_FROM`'s own 2026-06-08 default
   is untouched. Verified by running the generated file's own script headless
   under Node against the live embedded data: `todayLocal()` correctly
   returned the real machine date while `DEFAULT_TO` correctly clamped to the
   newest embedded day when today's data was not embedded yet.

4. **"Where the work moved, month by month" (the `proj-month` heatmap), TWO
   separate real bugs, both operator-reported, both fixed:**
   - Month column headers (e.g. "2026-06", "2026-07", "2026-08") were
     rendering stacked on top of each other, unreadable. Cause: `heatmap()`'s
     default `cellW` (26 SVG units) was sized for 1-2 char labels (used
     correctly by the OTHER heatmap call, weekday x hour, 24 short columns);
     a 7-char month key needed much more room. Fixed by passing `cellW: 60`
     for this call specifically.
   - Long project row labels were losing characters off the START (e.g.
     "CaptainCodeAU-COWORK..." rendered as "OWORK-Best-Practice-Docs..."),
     because row labels are right-anchored and grow LEFTWARD past x=0, which
     the SVG viewBox clips. Fixed generically inside `heatmap()`: labels now
     truncate with an ellipsis to what the label column can actually hold
     (~8px/char, tuned against the real rendered names after an initial
     6.5px/char estimate still clipped by ~3 characters), with the full name
     still reachable via the existing `data-tip` hover tooltip.
   - **A THIRD, worse bug in the same panel was found only after the operator
     reported "text very large, alignment issues" post-fix**: for a narrow
     date range (few month columns), the heatmap's own natural width (e.g.
     390 SVG units for 3 months) was far below the page's real rendered
     panel width (measured 1,170px via `getBoundingClientRect()`), so the
     browser stretched the whole viewBox - text included - by 3x to fill the
     container. `barChart()` already guards against exactly this
     (`Math.max(660, ...)`, matching the page's own `.chart-svg{min-width:
     660px}`); `heatmap()` had no equivalent floor. Fixed by growing `cellW`
     (not padding blank space) so the natural width always reaches 660,
     mirroring how `barChart()`'s own bars already expand to fill its floor.
     Verified by DOM measurement before and after: viewBox went from
     `0 0 390 260` rendered at 1170px (3.0x stretch) to `0 0 660 260` at
     1170px (1.77x), in the same range as the "Top 15 by cost" panel's own
     1.3x - no longer an outlier.

5. **"How much time overlapped, whole corpus" (Concurrency), operator-flagged
   as "tremendous number of bars".** These bars are per DAY, not per project
   (the panel has no project dimension at all, by design - it needs real
   interval-overlap math across every project). A ~75-day default range gave
   75 thin daily bars. Rolled up to one bar per ISO week (11 bars for the
   default range) inside the panel's own render function: `summedHours` and
   `elapsedHours` are safely additive across days (each day is a disjoint,
   non-overlapping clock-time slice), `concurrency` is RECOMPUTED from the
   weekly sums rather than averaged day-to-day, and `maxConcurrent` is the
   max of the days' own peaks (the true weekly peak occurs within some single
   day, and that day's own figure is already its true instantaneous max - no
   session-level reconstruction needed). Verified two ways: an independent
   Python rollup against the live database matched the panel's own 11 bars
   exactly (1,188.7h / 941.3h / 811.0h / ... down to 533.0h), and the same
   figures were then read directly off the rendered chart in the browser and
   matched again.

6. **Project-list "noise" consolidation, operator-flagged on "Top 15 by
   cost" and (by the operator's own words) likely elsewhere too.** Measured
   first, not assumed: only 2 panels actually GROUP by project at all -
   "Top 15 by cost" and the month-by-month heatmap (a separate "repos" panel
   already exists, keyed on `repo_root`, and already folds ordinary
   subdirectories and named worktrees into their parent - that panel was
   left untouched). The real noise turned out to be a narrower thing than
   "worktree labels" in general: Claude Code's own background-agent tooling
   creates a throwaway folder per agent run
   (`.claude/worktrees/agent-<random hex>`), and each one gets counted as
   its own `project_label` / `repo_root` because Git genuinely treats a
   linked worktree as its own toplevel. Measured: 15 such rows, 30 sessions
   total, 12 of them for `cc-warehouse` alone. Put to the operator as a
   2-option decision (fold only this auto-generated pattern / fold
   everything the same way `repo_root` already does); **the operator chose
   "fold only the junk"**. Implemented as `canonicalProjectName()` (a regex
   stripping the `-.claude-worktrees-agent-<hex>` suffix) applied only inside
   the two grouping panels via a shared `CANON_PROJECT` lookup array - real
   named worktrees (`-.worktree-web`) and genuinely separate sub-repos
   (`-DIB-governor`) are deliberately left alone, since those are real,
   distinct work. Verified: an independent Python rollup (fold logic +
   exclude list both applied) matched the live panel's "42 projects in
   range" figure and its top-15 dollar amounts exactly, including
   `cc-warehouse` at US$ 3,948.02 (base US$ 3,774.78 + the 12 folded-in
   agent-worktree sessions summing to US$ 173.24, cross-checked
   independently too).

7. **Title changed** from "Claude Code, your own slice" to
   ".cc-warehouse / stats" (the page's `<h1>`; the `<title>` tag itself,
   "Claude Code, live", was not part of the ask and is unchanged).

8. **"Models by cost in range" now groups by model FAMILY** (opus/sonnet/
   haiku/fable, version numbers summed together), not by exact model
   string, per the operator's explicit ask. The Overview KPI tile already
   did this with its own local `modelFamily()` function; hoisted that to a
   shared top-level function so both panels use identical logic instead of
   risking two copies drifting apart, and matched its existing
   `<synthetic>`-row exclusion (a $0 placeholder for an interrupted reply,
   not a real priced model). Verified against a direct SQL rollup (with the
   exclude list applied): opus US$ 38,138.38, fable US$ 9,424.43, sonnet
   US$ 6,167.83, haiku US$ 64.34 - matched the rendered US$ 38.1k / 9.4k /
   6.2k / 64 exactly.

9. **"Top 8 in each kind" alignment fix, operator-flagged.** Was a 2-column
   CSS grid (`.grid2`); since each kind (agent/mcp_server/mcp_tool/plugin/
   skill) has a different row count and label lengths, the two columns never
   lined up cleanly. Switched to a single stacked column (`.stack1`, a plain
   flex column with a 26px gap) per the operator's own suggestion. The now-
   fully-unused `.grid2` CSS rule and its media query were deleted rather
   than left dead.

10. **Sessions tables, operator-requested change plus a new addition.** "The
    50 most expensive sessions in range" is now "The 25 most expensive
    sessions in range" (`slice(0, 50)` -> `slice(0, 25)`). Added a new panel,
    "The 25 longest sessions in range" (`longest-sessions`), same columns,
    sorted by engaged hours descending instead of cost descending.

11. **"Claude Code builds in range" panel removed entirely**, per the
    operator's explicit "it's kind of useless, get rid of it." Only the
    display panel was removed - the underlying `ccVersion` data column and
    lookup table in the embedded payload are untouched, so nothing else in
    the file lost data it depends on.

12. **The Caveats section ("What would make these charts wrong") removed
    entirely**, per the operator's explicit "it comes across very negative."
    Removed the `CAVEATS` array, its rendering block and nav link inside
    `renderAll()`, and the now-dead `.panel.dark`/`.cav-grid`/`.cav`/
    `.cav-t`/`.cav-d` CSS rules. **Flagged to the operator in chat, not
    silently dropped**: this section was the ONLY place the page told a
    reader "this file is private, do not upload it." That specific reminder
    is now gone from the page itself; the underlying privacy rule (never
    upload this file, it embeds real folder names) still fully applies per
    this document's own Privacy paragraph above - it is just no longer
    printed on the page for a reader who has not seen this file or
    `tools/ccstats/README.md`.

13. **A space added after "US$" everywhere**, per the operator's explicit
    ask. Both dollar-formatting functions (`fmtUSD`, `fmtUSDFull` in
    `dashboard_template.html`) changed from `"US$" + ...` to `"US$ " + ...`;
    these are the only two places the string "US$" is built anywhere in the
    file, confirmed by grep before editing, so no dollar figure on the page
    was missed.

**Verification method for this whole round**: `ruff check` and the 99-test
`pytest` suite stayed green throughout and after every change (no NEW tests
were added this round - every change here is in `dashboard_template.html`'s
client-side JS, which the Python test suite does not and cannot exercise;
`dashboard.py`'s own case-insensitivity change likewise has no dedicated
pytest coverage, only the ad-hoc DB probe described above). Every numeric
claim above was independently cross-checked against `sessions.sqlite` with a
fresh Python query, separate from the dashboard's own code, THEN confirmed
a second time by opening the real rebuilt file in a live Chrome tab (via the
local http-server workaround) and reading the same numbers off the actual
rendered page - not assumed from the JS alone. Browser console was checked
for errors after every rebuild (`read_console_messages`, pattern
`error|Error|exception|NaN|undefined`); none were found at any point this
round. **What is still NOT covered by an automated test**: none of
`dashboard_template.html`'s JS is under `pytest` at all, by design (it is a
generated static asset, not a `ccw` module) - the only guard against a
future regression in any of these 13 fixes is a human, or a future session,
re-opening the file in a browser and looking. Worth remembering before
trusting a future "the tests still pass" as proof this page still renders
correctly.

### 3. Ticket 27.5-27.8, the last open track

**27.1-27.4 are CLOSED**, including the `objects/` delete, re-verified
2026-08-21 (see the ticket; CLAUDE.md and the ticket both claimed the opposite
until then). What remains:

- **27.5** decide whether `root` moves into the archive
- **27.6** re-read the `ccw archive --to` guard
- **27.7** reconcile `ccw verify` with ruling (b)
- **27.8** retire `store.py`

**27.8 may now be much smaller than written.** `keep_objects=false` is live and
`objects/` is gone, so `store.py`'s object surface has no callers left on the
capture path. MEASURE that before planning; do not assume it.

**27.9 IS WITHDRAWN AND STAYS WITHDRAWN.** Nothing is ever deleted from
`~/.claude`. A satisfied gate is not consent.

### 4. Ticket 30's flagged-for-later: the equal-size payload defect

A real fidelity bug, in ticket 29's family. When a re-captured payload is the
SAME SIZE as the archived one but has different content, the JSONL is correctly
left alone, but `refused` stays False, so the folder's rendered markdown and
HTML describe the NEW payload while the JSONL beside them still holds the OLD
bytes. Mechanism 2 fixed the size-known-different case; this is the equal-size
case. Recorded at the end of `harness/tickets/30-incremental-archive-rebuild.md`.

Correctness of the deliverable beats everything below it.

### 5. Ticket 28.22: fence `ccw doctor`'s text output

`~/.local/bin/ccw-watch` (a DIFFERENT repo, `fifty-shades-of-dotfiles`) runs at
every Claude Code SessionStart and parses `ccw doctor` with a regex: the `hook`
line's wording and the `Uncaptured: N session(s)` figure. **Nothing in this
repo's suite protects that shape**, so a reformat breaks an external consumer
with nothing here going red. Pin the exact substrings a known-external parser
depends on, not the whole output.

Cheap, and this session nearly tripped over `doctor`'s output twice.

### 6. Ticket 28.13: re-derive the architecture board

Now urgent in a way it was not before. **The board's every `file:line` was
derived at master `1517bba`, and that commit no longer exists** - nor
`18fa5be`. Both were lost when the repository was deleted and re-created on
2026-08-10 for the go-public audit (28.20). So the refs are anchored to
nothing and their decay cannot even be measured: `git rev-list 1517bba..HEAD`
does not run. A decay banner recording this now sits at the top of
`cc-warehouse-architecture/SOURCE.md`; the cards are untouched.

The card REASONING still stands. Only the line numbers are dead. The fix is a
fresh review at a live commit, via `/architecture`, never hand-patching refs.

### 7. ccstats polish, once item 1 has made it safe

In rough value order: ~~`--until` (only `--since` exists...)~~ **DONE, landed
as part of item 2 above (2026-08-21) - closed here instead of twice, as
already noted.** Remaining: split the three long functions
(`collect.scan_transcript` 330, `make_docs.main` 273, `facts.compute` 153) ·
re-check model prices (pinned at 2026-06-24, every dollar figure drifts) ·
incremental collect (re-reads all 25k transcripts every run, ~25 s).

---

## Also on record, not scheduled

- **Ticket 24.7**, session-start capture freshness. Partly closed from outside
  this repo by `ccw-watch`, which this repo does not own or control.
- **Ticket 28**, the backlog register. Still open in it: `--open` (28.1),
  optional secret redaction on personal projections (28.2), `--limit` on sweep
  (28.3), `render_html` costing 74x the payload (28.9), test gaps (28.10),
  markdown/HTML for sub-agents (28.11), re-homing an orphaned sub-agent when
  its parent arrives (28.12), `prefers-color-scheme` for shared pages (28.14),
  move the plugin into this repo (28.19).
- **Ticket 31's inherited open question:** the lock-contention mechanism is
  still UNPROVEN. Debug logging shipped; the retry loop was deliberately not
  written until the real exception is observed. Do not design a fix for an
  unconfirmed cause.
- **Version cuts not started:** v1.1 proper (FTS5 + `ccw search` + HTML archive
  search + `ccw import`/inbox), v1.2 (`ccw mcp`), ticket 19 leftovers (`share`
  19g, and `status`/`relocate`/`project` on archive labels), DESIGN 15 item 7
  (registry backup/export story).

## Two environment facts that will bite

- **`ccw doctor` run from inside this repo reports `editable`, and that is not
  a rule violation.** `.envrc` (tracked 2026-08-21) sources `.venv/bin/activate`,
  so `.venv/bin/ccw` shadows `~/.local/bin/ccw` on PATH and doctor truthfully
  describes the venv copy - not what the hook runs. The install IS frozen.
  Unambiguous check:
  `env -u VIRTUAL_ENV PATH="$HOME/.local/bin:/usr/bin:/bin" ~/.local/bin/ccw doctor`
- **The SSH key drops out of the agent** (ticket 28.15, seen again 2026-08-21).
  `ssh-add -l` reported "no identities" and `git push` failed on access rights.
  Commits `3b284e5` and `a366275` are LOCAL AND UNPUSHED. The operator must run
  `ssh-add` themselves; a session cannot.
- **NEW, 2026-08-22: `file://` navigation is refused by the Chrome browser
  tool** (`mcp__claude-in-chrome__navigate`), even to a brand-new tab -
  "Can't interact with browser-internal or unparseable URLs." To visually
  check any local HTML file (this dashboard included), serve its directory
  over loopback first: `uv run python3 -m http.server <port> --bind
  127.0.0.1` from that directory, navigate to `http://127.0.0.1:<port>/file`,
  then kill the server when done. Worked cleanly every time this session.

## What the previous session did

This session closed out item 2 in full - see "Fourth round, 2026-08-22
session" above for the complete 13-item account (the operator's real
`--include`/`--exclude` list, case-insensitive matching, a live "today"
default end date, three real bugs found and fixed in the month-by-month
heatmap including a 3x text-stretch bug only surfaced after the first fix
looked "done", a daily-to-weekly rollup of the Concurrency panel, folding 15
auto-generated agent-worktree rows into their real projects, a title change,
model-family grouping, a layout fix, a 50->25 sessions-table change plus a
new 25-longest table, two whole panels removed at the operator's request,
and a spacing fix applied dashboard-wide) - and ran the codegen-scoping
investigation the prior session deferred, whose outcome did NOT get a
decision from the operator (see "One loose end inside item 2" at the very
top of this file).

Every fix was verified twice: once against `sessions.sqlite` independently
(fresh SQL/Python, never through the dashboard's own code), and a second
time by actually opening the rebuilt file in a live Chrome tab and reading
the same numbers or looking at the same panel with the harness's own eyes -
a real browser was available all session, unlike the session that built the
dashboard originally. `file://` URLs turned out to be blocked by the browser
tool; the loopback-http-server workaround (see "Two environment facts"
above) should save the next session from re-discovering that.

**What was NOT done, on purpose or otherwise:** item 3 (ticket 27.5-27.8) was
not started - all of this session's time went to item 2's follow-ups, which
kept arriving faster than they could be closed. No pytest coverage was added
for anything in this round, since every change lives in
`dashboard_template.html`'s client-side JS, which the Python suite does not
reach at all - the only regression guard for any of today's 13 fixes is a
human looking at the page again later.
