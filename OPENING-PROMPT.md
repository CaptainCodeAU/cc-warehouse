# Opening prompt for a fresh session, 2026-08-21 (fourth handoff of the day)

## Next task: TWO things before item 3. Read "Item 2's two open threads" just
## below first, then work item 3 (ticket 27.5-27.8). Item 1 is fully DONE.
## The order is decided; do not re-litigate it.

### Item 2's two open threads, both explicitly deferred to this session by the operator

1. **Apply the operator's `--include`/`--exclude` list.** The dashboard build
   (item 2 below) now takes `--include SUBSTRING` / `--exclude SUBSTRING`
   (both repeatable, substring match against `project_label`) to set which
   projects start ticked/unticked in the live page's checklist - see item 2's
   third-round addendum for exactly how these compose. **The operator said,
   verbatim, they will give the actual list of substrings in this fresh
   session** - it was NOT given in the prior session, so nothing is baked in
   yet. Ask for it, then run `uv run python3 tools/ccstats/dashboard.py`
   with the right flags and hand back the file. Do not guess the list.
2. **Investigate deterministic generation of `dashboard_template.html`, in
   depth.** The operator's own words: take it "in depth" this session, not a
   quick pass. The prior session's parting note (in item 2's addendum) scoped
   the question but did not start it: which parts of that file are genuinely
   mechanical (the CSS palette, the chart-drawing primitives, maybe the KPI
   tile scaffolding) versus which need editorial judgement each time (caption
   wording, what a new panel should say) - only the former is a good target
   for a script/codegen approach that would cost fewer tokens per future
   edit. Scope it, then propose an approach, before rewriting anything.

Plus "anything else that's pending" (the operator's own phrase) - read the
rest of this file for what that covers; nothing here is being narrowed
silently.

The operator asked for the remaining work to be ordered and handed over. It is
ordered here. Work down the list. Ask before starting anything NOT on it.

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

### 2. Build an interactive stats dashboard (operator request, 2026-08-21) - shipped, TWO THREADS STILL OPEN

**The dashboard itself shipped, three rounds of follow-ups deep. Two threads
are explicitly deferred to the NEXT session - see "Item 2's two open
threads" at the very top of this file before reading anything below.** The
investigation just below is the ORIGINAL brief this was built from; left
intact rather than rewritten. See the DONE block just before item 3 for what
actually shipped, round by round.

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

**Scope trims, stated rather than hidden**: Concurrency reads whole-corpus
`overlap_day` (real interval-overlap math, not reconstructable from a
per-session duration) and narrows only by date, not by the project filter -
the panel says so. Worktrees reports counts only, no `worktree_name` list.
Top sessions shows 50, not 200. Every other panel is fully live on both
filters, wired to the one filter bar per the operator's requirement.

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
pixel rendering. Worth a real look next time a browser is available.

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

**Operator ask for a FUTURE session, not started**: investigate how much of
`dashboard_template.html`'s generation could become deterministic/scripted
rather than requiring an LLM to hand-edit template strings for every tweak
(a KPI wording change, a new tile, a color adjustment) - the goal is fewer
tokens spent per future edit. Worth scoping before attempting: which parts
are genuinely mechanical (the CSS palette, the chart-drawing primitives) vs.
which need editorial judgement each time (KPI caption wording, what a new
panel should say) - only the former is a good target for codegen/scripting.

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

In rough value order: `--until` (only `--since` exists, so no closed period can
be charted - **this is also the prerequisite item 2's date-range control
needs; doing it there instead of twice is fine**) · split the three long
functions (`collect.scan_transcript` 330, `make_docs.main` 273, `facts.compute`
153) · re-check model prices (pinned at 2026-06-24, every dollar figure
drifts) · incremental collect (re-reads all 25k transcripts every run, ~25 s).

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

## What the previous session did

Completed item 1 in full: moved `temp/ccstats/` to `tools/ccstats/`, fixed the
`.prev` disk leak with an atomic `tempfile.mkstemp` + `os.replace` publish, added
`resolve_out`/`Out` (a fenced, single-resolution write root replacing 5 hardcoded
copies of `OUT_DIR`), and added `--out DIR` / `CCSTATS_OUT`. Kept the packaging
gate green by adding `tools` to `pyproject.toml`'s sdist exclude and
`tests/test_packaging.py`'s `FORBIDDEN_DIRS`. Verified all of it: all 3 gates
green, the ccstats suite grew 72 -> 86 tests, and a full real-data run through
all 5 scripts landed cleanly in `~/.cc-warehouse/stats/` (see item 1's DONE
note above for the exact figures).

The operator then asked whether `~/cc-warehouse-stats/` (the old location) was
safe to delete. It was NOT quite: `CHART-BRIEF.md` existed only there, not
regenerated by anything. The operator moved it across by hand, then deleted the
old folder themselves. **`~/cc-warehouse-stats/` is gone; confirmed 2026-08-21.**

Separately noticed while checking: `claude-code-dashboard.html` had ALREADY
appeared in the new `~/.cc-warehouse/stats/` before this session put anything
there, byte-identical to the old copy, same mtime, different inode - so not a
hardlink or symlink, something else copied it. Not explained; not this
session's doing. Worth a glance if it matters later, but it did not block
anything here.

The operator then asked for an interactive version of that dashboard (own date
range, own project-exclude list), and asked for this to be investigated and
written up here rather than built now - see item 2 above for the full findings
and the two-option design fork. Nothing for item 2 has been built. Read
`CHART-BRIEF.md` (now in `~/.cc-warehouse/stats/`) before starting it; it is
the actual style brief the current dashboard was built from.

**Standing lesson from the session before this one, still true**: verified
OUTPUTS are not verified CODE. Five real defects in this same stats tooling
were found by an external reviewer, not by self-checks, before item 1 even
began (`elapsed_hours` off by 2.3x from un-clipped day boundaries, a fixed +10
timezone offset that mis-bucketed 577 sessions, hardcoded prose numbers that
disagreed with the live sheets, unfiltered totals mixed with filtered ones,
`active_hours` documented as compute time when it is wall time including idle).
Test the code, not just its output, especially before building item 2 on top
of it.

**This session (the one this handoff is being written from) built item 2 in
full and iterated on it four more rounds from live operator feedback** - see
item 2's addendum, below its investigation section, for the complete
round-by-round record (KPI tiles, dark theme, US$, the include/exclude
substring filter, the strikethrough removal, and the rest). It ends here with
two threads explicitly handed to the NEXT session rather than guessed at: the
operator's actual `--include`/`--exclude` list (not given yet), and an
in-depth look at deterministic/scripted generation of
`dashboard_template.html` - both flagged at the very top of this file. No
browser was available to this session at any point; every check that would
normally be "open it and look" was instead done by running the page's own
JavaScript headless under Node against the real database and cross-checking
the numbers independently - a real limitation, not a shortcut, and worth
someone actually opening the file in a browser when one is next available.
