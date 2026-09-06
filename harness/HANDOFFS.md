# Session handoff log

Dated, chronological account of what each past session on this repo actually did - one
entry per handoff, **newest first**. Split out of `OPENING-PROMPT.md` on 2026-08-27,
where this ran 844 lines (94% of that file's total) as an undifferentiated block with no
headers, just bold paragraphs, making it easy to read start to finish but hard to jump
into. Each entry below now has a real `###` heading so it is greppable and linkable.

Two things to know before reading:

- **Entry text is otherwise unmodified from the original**, including its own internal
  references to "above"/"below" other handoffs - those are relative to the ORIGINAL
  oldest-first reading order the prose was written in, not this file's newest-first
  layout. If an entry says "see the twelfth handoff below", look for it further DOWN
  this file's chronological numbering, not necessarily below on the page.
- **The seventeenth handoff never had its own dated entry until this split.** It existed
  only as a condensed status block inside `OPENING-PROMPT.md`'s old "ACTIVE TASK: ticket
  28.9" section. It is reconstructed here in its rightful place in the sequence.

For live "what to do next" state, read `OPENING-PROMPT.md`, not this file. For
recurring environment gotchas, read `harness/GOTCHAS.md`. For a closed ticket's full
technical account, read its file in `harness/tickets/`.

### Twenty-fourth handoff, 2026-09-06 (0.1.2 shipped; a real cross-platform test bug found and fixed; /wrap-up added)

Started from an operator question - "can PyPI auto-update from GitHub?" - answered by reading
`.github/workflows/release.yml`: the automation already existed (tag-triggered, PyPI Trusted
Publishing, no stored token) but had never fired since 0.1.1 (2026-08-09), because nobody had
pushed a `v0.1.2` tag despite `pyproject.toml` already reading 0.1.2 and `CHANGELOG.md` already
carrying that version's entry. Pushed it - which surfaced three real, previously-invisible
problems, each fixed the same session.

**1. 15 pyright-strict errors in `tests/test_render_open.py`.** `monkeypatch.setattr(notify,
"open_page", lambda path: ...)` - pyright can't propagate `open_page`'s `path: str` annotation
through a bare lambda passed to `setattr`. Fixed by replacing each lambda with a small named
function carrying the annotation directly; behaviour unchanged, 8 tests still pass.

**2. 22 tests failed ONLY on GitHub's `ubuntu-latest` runner**, never on macOS or in a locally
built Linux container (root, non-root+git, both tried and both green). Root-caused by reproducing
the exact CI condition locally rather than guessing: `config.py`'s `load_config()` checks
`XDG_CONFIG_HOME` before falling back to `$HOME/.config`. 23 test files write a sandboxed
`config.toml` under `$HOME/.config` and set `env["XDG_CONFIG_HOME"]` to match it - but only on a
plain dict used for `run_ccw`'s subprocess calls, never via `monkeypatch.setenv` on the real
process environment `run_cli`'s in-process calls actually read. On any machine where
`XDG_CONFIG_HOME` happens to already be unset (every machine tried until GitHub's runner), the
code's own fallback silently produces the same path anyway, hiding the bug for weeks - this
repo's tests hadn't run on GitHub since 2026-08-10 (see finding 3), so nobody had seen it fail.
One line in `tests/conftest.py`'s shared `ccw_env` fixture (`monkeypatch.delenv("XDG_CONFIG_HOME",
raising=False)`) fixes all 23 files at once, since every one of them computes the exact same
`$HOME/.config` value the fallback already produces. Verified by reproducing the CI condition
locally (`XDG_CONFIG_HOME=/tmp/x uv run pytest`): fails the same way without the fix, all 1222
pass with it.

**3. PyPI's GitHub Trusted Publisher link was broken since 2026-08-10**, the day the repo was
deleted and recreated for the go-public audit (ticket 28.20) - PyPI ties the link to GitHub's
internal repo ID, not the repo name, so the recreation silently orphaned it. Publish failed with
`invalid-publisher`. By the time it was checked, PyPI showed "No publishers are currently
configured" (not a stale entry - genuinely gone). Fixed by hand on pypi.org (walked the operator
through it live): re-added Owner `CaptainCodeAU`, Repository `cc-warehouse`, Workflow
`release.yml`, Environment `pypi`. `v0.1.2` published successfully afterward - confirmed against
PyPI's own JSON API, not just the green Actions checkmark.

**Standing rule added**: `commit-push-tag-workflow` memory now says push a matching `vX.Y.Z` tag
automatically whenever `pyproject.toml`'s version bumps, no asking each time (operator's explicit
authorization, given specifically because of finding 3's silent multi-week gap). A new memory,
`pypi-trusted-publisher-recovery`, records the fix for if a GitHub repo delete/recreate ever
breaks this link again.

**`/wrap-up` added** (`.claude/commands/wrap-up.md`), adapted from a much larger VM-infrastructure
version in a different project - kept the shape (derive the touched set from git alone, run the
guards fresh, three-state report vocabulary) and replaced the box/host-specific steps with this
project's own real gap: a version bump with no pushed release tag, which is exactly how finding 3
sat invisible for three weeks. First real run of it is this same session.

### Twenty-third handoff, 2026-09-06 (planning session, no code)

Started from two screenshots and two questions: why the archive folder for chorustic session
`78bb0bd1` has no `tool-results/` when the source folder does, and why only some sessions
have a `<uuid>/` folder at all. Answers: the product has never referenced `tool-results`
(census over 26 `src/` files, control hit, 0 matches), and Claude Code creates `<uuid>/` only
when it has a sidecar to put there (sub-agents, or a tool output too big to inline).

**Measured before designing.** 1,196 real sidecar dirs; child names are exactly
`tool-results/` (1,067), `subagents/` (481), `workflows/` (9), `.DS_Store`. `tool-results/`
holds 2,084 files, 135.7 MB; a byte check against every JSONL shows **65.4 MB exists in no
JSONL** (every hook-stdout file, half the overflow files, all pdf pages), because
`toolUseResult.stdout` is itself capped. First appeared 2026-05-08. Also found: the hook's
non-recursive glob misses `subagents/workflows/wf_*/agent-*.jsonl` (432 files, 33 MB; the
sweep's recursive walk has all 211 transcripts in the archive), 20 forked-skill files inside
`subagents/` copied by nothing, `<uuid>/workflows/` copied by nothing, and 35 sidecar dirs with
no transcript anywhere. Session id inside the transcript matched the dir name 450 of 450.

**Plan written, red-teamed, approved:** saved as
`harness/tickets/38-sidecars-tool-results-and-unknown-siblings.md` (`Plans/` is gitignored). Two Plan
agents (mechanism; red-team plus anomaly signal) and three Explore agents; every load-bearing
claim re-checked in source, two corrected (the layout tests will NOT break because the
session writer never creates sidecar dirs; the anomaly record must be a notice file, not a
manifest key, because the manifest is re-rendered later by a process that cannot see the
source dir and ~617 hidden sessions have none). Operator rulings taken in-session: copy the
stranded dirs under `_not-sessions/stranded-sidecars/`; doctor line informational plus a
desktop/voice alert fired once per new anomaly; all three sidecars in ticket 38. Ruling (c)
(sidecar identity from the transcript beside it) still needs its DESIGN 15 entry.

**Also closed:** the ticket 37 Part B row 1 check from handoff 22. The plugin update landed;
the newest cache copy contains `_started` and `ccw-hook.log` shows `started` lines.

Nothing in `src/`, `tests/` or `contract/` was changed. Next session: build 38a-38f.

### Twenty-second handoff, 2026-09-06 (new session)

Started from a plain question: why did one chorustic session's rendered files land nine
minutes after its JSONL, and why did its `subagents/` folders carry a date in between.
Traced through file mtimes, `capture_event`, the hook log and source. Answer: the SessionEnd
hook wrote the raw JSONL and sub-agent files, then died before the catalog row and every log;
the 12:30 daily sweep recovered it two minutes later and rendered after its full walk (ticket
34's known shape). The in-between date was the sweep rewriting every sub-agent `meta.json`.

**Ticket 37 opened and Part A closed the same day** (`harness/tickets/37-*.md`, commits
`fb08ea0`, `81784d3`, `52319d7`, `9d70689`, tag `ticket-37-part-a`). Measured: one daily
sweep rewrote 2,501 of 2,505 archive `meta.json` files because `write_subagent` wrote the
meta unconditionally and sub-agents never enter the hash pre-filter. Fixed with
`store.write_if_changed`, now the one shared compare-before-write primitive (the projection
writer, the project sidecar, the meta and the orphan note all use it); the sweep reports
`skipped_unchanged` and `refused-subagent` instead of a blanket success. Real-data
acceptance: a full `ccw sweep` over 26,708 items wrote 0 files under any `subagents/`.
Frozen `ccw` reinstalled and verified with `ccw doctor` from outside the repo.

**Part B row 1 shipped but is NOT LIVE.** `ccw-hook.py` writes a `started` line and puts
`source` and `session` on every log line. Claude Code runs the copy in
`~/.claude/plugins/cache/cc-warehouse/cc-capture/<sha>/`, which still has the old script
until the operator runs `/plugin` and updates `cc-capture@cc-warehouse`. Verified: 0 cached
copies contain `_started`. **First thing next session: check whether that update happened**
(`grep -c _started ~/.claude/plugins/cache/cc-warehouse/cc-capture/*/hooks/ccw-hook.py`).

A `/simplify` four-angle review of the first commit found four real things, all fixed in
`52319d7`: a hand-rolled compare where `build.py` already had one, the orphan note two lines
below carrying the identical bug (the standing "census the class" lesson, missed again in the
first cut), refusals reported as successes, and a session id that only worked if log lines
never interleaved. Left as ordered follow-ups in the ticket: the `killed` signal line, the
`capture_event.detail` pre-existing-folder note, and the read-side cost (each sub-agent read
3x and parsed 4x per sweep, sqlite opened per file; fix is a sub-agent hash pre-filter, a
catalog schema change that wants its own ticket).

Also committed: the `tools/ccstats` review-report work found uncommitted at session start
(`5f75844`, 320 tests green), under the operator's reaffirmed rule "always make frequent
commits and pushes". Operator also ruled: ignore `cc-warehouse-architecture/` unless it
bears on the CLI (it does not; nothing in `src/`, `plugins/` or `pyproject.toml` references it).

**What was NOT done:** ticket 37 Part B rows 2, 3, 5 and the pre-filter follow-up. Nothing
else opened.

### Twenty-first handoff, 2026-09-04 (new session)

Short session, no ticket picked up. Opened by reading `OPENING-PROMPT.md`, offered the
standing backlog candidates, and the operator instead ran `/dashboard`. Refreshed
`sessions.sqlite` (20.67s, 30,714 files parsed, 0 unreadable, 27,015 from cache) and
rebuilt the live dashboard, then answered two follow-up questions and made one small
committed change.

**"Does the HTML work offline?" - yes, and it was measured rather than asserted.** The
built page registers ZERO font faces (`document.fonts.size === 0` in a real browser), has
no `<link>`, no `@import`, no `@font-face`, no `fetch`/XHR/WebSocket, no external script
src, and exactly one absolute URL in the whole 1.7 MB file: the SVG XML namespace
`http://www.w3.org/2000/svg`, which is an identifier and is never fetched. Doctype and
`<meta charset>` are both inside the file, so nothing depends on the server's headers.

**"The fonts differ between the served page and the double-clicked file" - the stated
cause was disproved, and a different one was found but NOT confirmed.** Nothing can fail
to load, per the above, and the bytes are identical either way, so origin cannot change
font resolution. What was measured instead: this machine's default handler for BOTH
`public.html` and `http`/`https` is **Brave**, while the browser-automation tool only
drives **Chrome**, so the two pages being compared were probably in two different
browsers. Brave's own `Preferences` holds a `braveShieldsMetadata` entry for
`http://127.0.0.1` carrying a `farbling_token`, meaning Brave's fingerprinting protection
(which restricts which local fonts a page may use) has run on that origin; Shields do not
apply to `file://` URLs. That points the difference at the SERVED page, the opposite of
the initial guess. Left unconfirmed: only one browser is connected to the extension, so
Brave could not be inspected directly. Also ruled out by measurement, not by argument:
per-origin zoom (no saved zoom for `127.0.0.1` or for files), a stale/different file, and
missing fonts (`SF Mono`, `Menlo`, `Georgia`, `Arial Narrow`, `Helvetica Neue` are all
installed; only the later fallbacks `Consolas`, `DejaVu Sans Mono`, `Iowan Old Style` are
not, and they never get reached).

**Shipped: the project checklist is ordered most recently worked on first (`ca80ce7`).**
It was alphabetical, which on the real corpus means 123 rows where the two or three
projects the reader is here for sit wherever the alphabet puts them. Each canonical
project now carries its newest session date; the list sorts by that descending with the
old alphabetical order as the tiebreak, and the date renders on the right of each row
using the `.proj-item .n` style that already existed in the template but had never been
emitted. "Recent" is measured across the WHOLE embedded corpus, not the current date
range, so nudging a date picker cannot reshuffle the list under the reader's cursor.
Two new tests in `test_dashboard_headless.py`, with `dashboard_probe.js` extended to
expose `CANON_LIST`, `PROJECT_LAST_DATE` and the rendered row order. **The tests were
proved to bite**: the sort was temporarily reverted to alphabetical, they failed on the
first row, and the template was restored from a backup verified by sha256. 163 tests
green, ruff clean, verified afterwards in a real Chrome tab on the real corpus (123 rows,
every row an ISO date, monotonically descending, zero violations).

**A gotcha this session hit, worth knowing:** `cp` is interactive in this shell, so a
`cp` that overwrites an existing file BLOCKS on a `(y/n [n])` prompt instead of finishing.
It hung a 600s Bash call and, worse, left the deliberately-corrupted template in place
until the restore was redone in Python. Use a Python `write` + `os.replace` for
restore-from-backup steps, never `cp`.

**Reviewed but NOT changed: the project hide-list.** The operator asked whether any hidden
project resembled the kept ones. Measured across all 30,714 session rows with the page's
own canonicalisation and the 23 saved rules: 140 canonical projects, 71 shown, 69 hidden.
Four real candidates were surfaced - `Scaffoldings-fifty-shades-of-dotfiles` (4,005
sessions, 178.8 h, $7,170, active that day), `CaptainCodeAU-cc-print-shop` (the only `cc-`
project hidden while `cc-warehouse`, `cc-vantage` and `cc-context-forge` are all shown),
`CaptainCodeAU-EXTENSIONS-important-soonish-links` (531 sessions, active the day before),
and `CaptainCodeAU-claude-code-transcripts` - plus the tax family (~5,700 sessions, 288 h)
flagged separately as probably deliberate. **The operator chose none of them**;
`dashboard-defaults.json` is unchanged. Recorded here so a future session does not
re-derive the same list and read silence as an oversight.

### Twentieth handoff, 2026-08-28 (new session)

Opened by reading `OPENING-PROMPT.md`, then asked the operator which standing candidate to
pick up. Chose the 3D/WebGL ccstats companion page (raised 2026-08-27, explicitly not
started - the operator wanted it PLANNED first). Entered Plan Mode rather than starting
straight into code, per that instruction.

**Research before designing.** Two Explore agents in parallel read `collect.py`,
`dashboard.py`, `common.py` for the exact schema and reusable machinery; measured the
REAL corpus read-only (`~/.cc-warehouse/stats/sessions.sqlite`) rather than trusting the
README's prose: 26,403 sessions (4,042 mine / 20,353 automated / 2,008 sub-agent), 163
days, peak 28 concurrent sessions, longest session 33.5 days. Read the "Estate Orbit"
artifact the operator named as inspiration (a governance-graph 3D page using the bundled
`ForceGraph3D` library, TrackballControls, WASD/space-pan camera conventions) for its
INTERACTION quality, explicitly not its node/link data model - confirmed via
`parent_session_uuid` that ccstats has exactly one real session-to-session edge (396
parents, 2,008 sub-agent children) and is otherwise a time-interval population, not a
graph. Put two forks to the operator with an ASCII preview each (shape: Day Wall vs.
Project City vs. Swarm; renderer: hand-rolled WebGL2 vs. vendoring three.js) - Day Wall +
hand-rolled won both, matching the 2D page's own no-chart-library rule.

**Plan written to `Plans/spicy-spinning-pancake.md`** (gitignored, per this repo's own
`.gitignore` for `Plans/`), approved, then built test-first: `tests/test_daywall.py` (19
oracle tests) written BEFORE `daywall.py` existed, per this project's own rule. While
designing the payload found and fixed a real bug before it shipped: a `Lookup` over
`local_date` in first-seen order would silently SKIP a calendar day with zero sessions,
which would misalign every later day of a multi-day session once the browser-side
`dayIdx + 1` arithmetic crossed the gap - `days[]` is now a full contiguous date range,
not just the populated ones, with its own oracle test.

**Built:** `tools/ccstats/daywall.py` (its own slim 8-column payload, not an extension of
`dashboard.build_payload`; the `session_uuid` join is scoped to `is_subagent = 0` on the
parent side, since a sub-agent row carries its PARENT's uuid, not its own - the naive
join was measured to produce 35,471 spurious pairs), `daywall_template.html` (one box per
session on a WebGL2 canvas, positioned by day/hour, stacked into concurrency lanes
re-packed fresh on every filter change, hand-rolled camera + offscreen-framebuffer
picking, no library), `tests/node/daywall_probe.js` + `tests/test_daywall_headless.py` (9
tests exercising the page's real generated `<script>` block's pure-data half under Node,
mirroring `dashboard_probe.js`'s existing pattern), and `.claude/commands/daywall.md`
(mirrors `/dashboard`'s shape, shares its `dashboard-defaults.json` read-only rather than
duplicating the edit flow).

**Verified against the real corpus in a real Chrome tab**, not just `pytest` (this
project's own bar, ticket 28.9): built to a scratch `CCSTATS_OUT` first, served over
loopback, and found ONE real bug that no test had caught - `#wall{position:fixed;inset:0}`
does NOT stretch a `<canvas>` (a replaced element) the way it stretches a `<div>`; the
canvas stayed at its intrinsic 300x150 default and every box rendered off in the
literally-zero-sized viewport. Diagnosed via `getBoundingClientRect()` and
`getComputedStyle()` through `javascript_tool`, fixed with an explicit `width:100vw;
height:100vh`. After the fix: rotate/pan/zoom, click-to-spotlight (populated a real
session's project/kind/timestamps/cost/model correctly), every kind/project filter
checkbox, Reset, and Escape all confirmed working against all 8,682 real sessions, zero
console errors throughout. The scratch corpus copy (141 MB, real private data) was
deleted afterward; the real `~/.cc-warehouse/stats/` was never touched.

Committed and pushed (`0d41d3d`) after a targeted personal-data check on the 7 new/changed
files (clean). Full suite re-confirmed green after (161 ccstats tests, repo-wide ruff, the
1,198-test repo oracle suite). `OPENING-PROMPT.md`'s "Next task" section updated to close
this out and point at `/daywall`.

### Nineteenth handoff, 2026-08-27 (new session)

Opened by reading this file (the eighteenth handoff, below), then asked the operator
which of the standing backlog candidates to pick up. The operator instead asked to check
the previous session's last few messages for context - a 3D/WebGL ccstats dashboard idea,
raised but not started (see "Next task" in `OPENING-PROMPT.md`). Retrieved it by reading
the previous session's own transcript directly (`~/.claude/projects/.../*.jsonl`), not
guessed. Having seen that, the operator immediately flagged a more pressing problem:
`OPENING-PROMPT.md` itself had grown to 1,930 lines, mixing a chronological log of past
sessions with what a fresh session actually needs, and asked for a restructure plan
before any of it ran.

**This whole file is the result.** Mapped the original file's structure with a forked
sub-agent first (found 94% of it was closed-ticket writeups and past-session narrative,
only ~6% live/actionable). Two design forks were put to the operator directly: handoff-log
order (newest-first, chosen) and where to put the closed ccstats/dashboard writeups that
had no ticket file to live in (a new file next to the code, `tools/ccstats/HISTORY.md`,
chosen). The full plan was then confirmed with the operator before any file changed.

Shipped, verified line-for-line against the original before anything was deleted:
- **`harness/HANDOFFS.md`** (this file) - the session log, newest first, with real `###`
  headers. Also reconstructed the "seventeenth handoff", which had never had a dated
  entry of its own - it only existed as a status block inside the old ACTIVE TASK section.
- **`harness/GOTCHAS.md`** - the 5 recurring environment gotchas (was mislabeled "two
  environment facts" while actually holding five).
- **`tools/ccstats/HISTORY.md`** - the closed ccstats/dashboard build history.
- **`harness/tickets/28-backlog.md`**'s 28.9 entry gained the unique investigation detail
  that only lived in `OPENING-PROMPT.md` (the measurement table, stage-isolated peaks,
  the three repro-script names, the operator-approved 4-step test plan) and had a real
  self-contradiction fixed - the entry said "NOT YET IMPLEMENTED" a few paragraphs above
  its own "fully DONE" closing line.
- **`tests/test_doctor_external_contract.py`**'s docstring, which cited an
  `OPENING-PROMPT.md` section number that was about to move, repointed at the ticket file.
- **`OPENING-PROMPT.md`** itself cut from 1,930 to about 100 lines, keeping only current
  status, the open backlog, and a "Where else to look" index. A "Keep it this way" section
  was added specifically because explaining what moved isn't enough on its own - without
  an explicit instruction, the natural next move is writing a new narrative paragraph
  straight back into it, recreating the exact bloat this session fixed.

Verified, not assumed: every extracted block was diffed byte-for-byte against the
original `OPENING-PROMPT.md` content before it was deleted from there (all matched except
two intentional pointer-text edits, both fixing dangling references to the old "Two
environment facts" section name). Full suite green after every change (1,197 main-repo
tests + 132 ccstats tests passed, ruff clean); a repo-wide census (not grep - the
project's own `census.py`, control-verified) confirmed only 3 harmless historical
mentions of "OPENING-PROMPT" remained repo-wide, and the two real inbound pointers
(`harness/tickets/28-backlog.md`, `tests/test_doctor_external_contract.py`) were both
fixed. Five commits, all pushed: `003f6fb` (new files), `6e209ab` (ticket 28.9 merge),
`ad5bdd5` (test docstring fix), `a2502f7` (slim `OPENING-PROMPT.md`), `e9cd551` ("Keep it
this way" section).

**Also updated, outside this repo: this session's own persistent memory** (the project's
Claude-memory directory). Two existing memory files cited "OPENING-PROMPT.md environment
notes" by name - fixed to point at `harness/GOTCHAS.md` instead. Saved a new memory,
`opening-prompt-is-an-index-not-a-log.md`, recording the new convention so a future
session doesn't recreate this same bloat out of habit rather than by reading the file
carefully every time.

**What was NOT done:** the 3D/WebGL ccstats dashboard idea (see "Next task" in
`OPENING-PROMPT.md`) - explicitly deferred to a new session, per the operator's own
request, both before and after this restructure. Nothing from ticket 28's remaining
backlog (28.2/28.10/28.11/28.12/28.14) or `ccw share --open` was touched.

**Same session, continued afterward: the restructure above was proved with a real Herdr
test, not just trusted.** The operator asked for a genuinely fresh Claude Code session,
launched in a sibling Herdr pane with no context from this conversation, to be driven
with the real opening command ("Read OPENING-PROMPT.md and follow instructions") and
watched for gaps. None were found: it correctly read the new ~100-line file, said nothing
was active, listed both the 3D-dashboard idea and the backlog, recommended the former
(matching the file's own framing), and - when told to actually start - read the right
background files (`tools/ccstats/README.md`, `PANEL-CONTRACT.md`) before entering Plan
Mode on its own, exactly matching this project's convention. Stopped there on purpose;
letting a full planning run happen unsupervised was out of scope for a structure test.

**A second, unrelated thing came out of that test: real gaps in how to drive Herdr
itself**, found by hitting them firsthand while running the test (not from docs). Three
real errors, each with a genuine root cause, not flukes:
- `agent_pane_busy` right after `pane split` - a freshly split pane runs its own shell
  startup/onboarding script first and is not yet "available"; guessing a sleep duration
  is the wrong fix.
- `agent_prompt_stalled` on `agent prompt --wait` - Herdr's own 5-second "did it start
  working" grace period is shorter than this environment's real per-turn overhead
  (session hooks, skill loading, a custom status line), so a healthy prompt can still
  trip the check.
- `herdr pane close --pane <id>` is a syntax error - `pane close` is the one `pane`
  subcommand that wants a bare positional ID, unlike most siblings that accept `--pane`.

All three, plus the general "wait via Herdr's own event system, never poll" pattern
(proved with a real 8-second measured block through a background Monitor task, not
assumed), were written up and folded into the actual places a reader already looks -
**`~/.claude/skills/herdr/SKILL.md`** (global, loads automatically whenever Herdr is
used, any project) and a short pointer added to **`~/.claude/PAI/USER/AISTEERINGRULES.md`**
(global, loads every session). Neither file lives in this repo; noted here only because
the work happened in this session and because a future cc-warehouse session driving
Herdr benefits from knowing it's already fixed upstream, not because cc-warehouse owns
either file. A stronger rule was added after discussion: never close a pane on
`agent_status: idle` alone, since a false-early idle (a known, still-unfixed Herdr
nested-TUI quirk) plus an immediate close would silently and unrecoverably kill real,
still-running work.

**Verified twice, not once.** The same nested Herdr test (a fresh agent launching its
OWN fresh agent and waiting on it correctly) was re-run after the skill-file fix: zero
errors the second time, including on the exact three traps above, on a brand-new agent
that had only the two updated files to go on - not this conversation's context. Every
test pane was closed afterward; nothing was left running.

---

### Eighteenth handoff, 2026-08-27

**Eighteenth handoff, 2026-08-27 (new session).** Opened by reading this file, then the operator
ran `/dashboard` directly (a fresh build + real-Chrome look, nothing else) rather than picking up
ticket 28.9's own backlog candidates (28.2/28.10/28.11/28.12/28.14, `ccw share --open` - none of
these were chosen or touched this session). Two follow-up asks landed after that, both about the
live dashboard's UI, not its data pipeline.

**1. Sub-agent population split.** The operator's own framing: sub-agent runs get counted as "a
session" today, which is right for some stats and wrong for others - asked for the two groups
worked out with reasoning, not guessed. The mechanism: every `session` row already carried a
`kind` (`mine`/`subagent`/`automated`, from the sixteenth handoff's own `session_kind()`), but
ONE page-wide toggle applied that classification to every panel identically - `inRange()` fed a
single `FS` array to all 20 panels. Split into two populations instead: `FS` ("my own work" -
sub-agent NEVER counted, because a sub-agent's engaged time sits INSIDE its parent session's own
clock time, so counting it again double-counts minutes) and `FSW` ("real work done" - sub-agent
ALWAYS counted, because its cost/tokens/tool-calls are genuine extra spend, not nested time).
`inRangeInteractive`/`inRangeWorkload` replace the old single `inRange`; `DEFAULT_KINDS` dropped
to `{mine}` alone (was `{mine, subagent}`); the "sub-agent runs" checkbox was removed from the
filter bar entirely (`.claude` reader can no longer toggle it - the rule is now fixed per panel,
by design, since a single toggle literally cannot serve two contradictory questions at once).
9 of 20 panels (Projects, Repositories, Project x month, Models, Model x month, Tokens, Thinking,
Tools, Skills & agents) now read `FSW`; the rest (Daily/Weekly/Monthly, Session sizes, Hour
heatmap, By weekday, Worktrees, Top/Longest sessions, and most of Overview's 15 KPI tiles) stayed
on `FS`. Two genuine judgment calls were put to the operator as a 2-option `AskUserQuestion`
rather than decided alone: **Tools panel now counts sub-agent tool calls** (real work, delegated
or not); **the "25 most expensive sessions" leaderboard excludes sub-agent runs** (it is a
leaderboard of the operator's OWN sessions, not a cost bucket). Overview's KPI accumulation loop
was split into two passes (one over `FS`, one over `FSW`) since it mixes both kinds of tile in one
panel - `session_kind()`'s own Python-side docstring in `dashboard.py` was updated to match, since
it used to claim sub-agent was "reachable via a toggle", which is no longer true.

Verified: `tools/ccstats/tests/test_dashboard_headless.py`'s three toggle-behaviour tests were
REWRITTEN, not just made pass again - they tested the OLD one-toggle behaviour on purpose, so a
green run against the new code would have meant the fix was reverted, not confirmed. The rewrite
adds an explicit regression guard that a scenario still naming `"subagent"` in `kinds` (mimicking
the removed checkbox) has ZERO effect on either population. Full suite: 132 passed (was 129
before this session even started, unrelated to this change), ruff clean, pyright unchanged (82
pre-existing errors, all in `tools/` which is outside strict `src/` by design, confirmed via
`git stash` that the count is identical before/after). The REAL `~/.cc-warehouse/stats` dashboard
was rebuilt from live data and headless-probed against the actual generated HTML (not a test
fixture): `fsLength` 661, `fswLength` 1950, "API cost" tile `US$ 53,747` - all three independently
cross-checked against a fresh direct SQL query (`is_real=1`, the same date window, the operator's
real 23-pattern exclude list applied) and matched exactly. Opened in a real Chrome tab over
loopback: 0 console errors, "sessions with a reply" 661 / "typical session length" 45.8 min (both
`FS`-driven, sub-agent excluded) alongside "API cost" `US$ 53,747` / "tool calls" 119,546 (both
`FSW`-driven, sub-agent included) rendered correctly side by side on the same page. Commit
`ee5d65a`, pushed.

**2. Layout gap + always-visible note, both operator-reported after looking at the rebuilt
page.** The note ("Sub-agent runs are handled automatically per chart...") read as too prominent
sitting permanently in the filter bar. Converted to a small `data-tip`-driven hover icon (an "i"
in a circle, reusing the page's own existing chart-tooltip mechanism, `.cc-tooltip` /
`document.addEventListener("mouseover", ...)` - no new JS infrastructure needed). The same
mechanism was used to answer the operator's own on-the-spot question ("what is this
`2,414 · US$ 66`?" - the live count/cost of "automated one-shots", off by default) by attaching a
second tooltip directly to that checkbox, so the answer now lives on the page itself, not just in
chat. Separately, a real ~100px dead gap above the date filters: `<header class="mast">` was
wrapped in the generic `.wrap` class, whose `padding: 0 28px 96px` exists for the PANELS wrap at
the very bottom of the page - reused on the header, its 96px bottom padding just opened a gap
nothing needed. Split into a new `.mast-wrap` (same max-width/centering/side-padding, zero bottom
padding of its own) confirmed via `grep` to be the only two places `.wrap` was used before
touching either.

Verified: 132 tests still green (no test covers pixel layout or tooltip visibility - this was a
real-browser-only check, matching this project's own "the only guard against a UI regression here
is a human looking" note from the sixteenth handoff). Rebuilt the real dashboard again, opened in
a real Chrome tab: 0 console errors before and after the change; a before/after screenshot pair
confirmed the gap closed and the filter bar visibly tightened; hovering the new "i" icon and the
"automated one-shots" label both showed their correct tooltip text and stayed hidden otherwise.
Commit `8f3b4ab`, pushed.

**The operator asked whether `.claude/commands/dashboard.md` also needed updating. Checked, not
guessed: it does not.** Read the whole command file - every step (resolve `$OUT`, refresh
`sessions.sqlite`, read/write `dashboard-defaults.json`, the `--exclude`/`--include` build flags,
serve over loopback, stop the server) is about the BUILD/SERVE workflow, none of which changed
this session. Nothing in the command's own text describes the generated page's internal filter-
bar wording, tooltip behaviour, or layout, so nothing in it went stale. Confirmed to the operator
rather than editing on a guess.

**What was NOT done:** ticket 28.9 remains closed and untouched (unrelated to this session's
work). None of the standing backlog candidates (28.2/28.10/28.11/28.12/28.14, `ccw share --open`)
were picked - still open, still the operator's to choose. Step 5 of the sixteenth handoff's own
dashboard plan (client-side concurrency reimplementation) remains deferred, not touched here
either. The unresolved `dashboard-defaults.json` overwrite mystery from the sixteenth handoff is
still unresolved - not chased down this session.

**Same session, after the two fixes above shipped: a NEW idea was raised, NOT started.** The
operator looked at an unrelated artifact ("Estate Orbit" - a 3D WebGL force-graph visualization
built for a completely different project, a personal decision-log system) and liked its visual/
interaction quality (drag-rotate/pan/zoom, click-to-spotlight, a live filter panel), not its
data model. Ask: a companion 3D/WebGL page for the ccstats corpus itself, alongside the existing
2D `claude-code-dashboard-live.html` - explicitly NOT a copy of Estate Orbit's node/link scheme
(planets/hubs/moons was one example, not a spec), designed ground-up for what ccstats data
actually is. The operator wants this PLANNED in a fresh session before any code is written, and
asked for an opening prompt to paste there - one was written and handed over (not saved to a
file in this repo, since it was meant to be pasted directly), covering: what already exists to
read first (`dashboard.py`, `dashboard_template.html`, README, PANEL-CONTRACT.md), the Estate
Orbit URL with an explicit "style only, not content" scope note, real measured corpus numbers as
of today (8,682 real sessions, 140 project labels, 105 repo roots, 88 tools, 9 model version
strings/~4 families, attribution: 10 agents/5 mcp_servers/31 mcp_tools/3 plugins/53 skills,
2026-02-14 to 2026-08-27), and this project's own house rules (self-contained HTML, no CDN,
never commit/upload the output, put every real fork to the operator as a table + a direct
question). **Nothing has been designed or built yet - if the next session opening this file is
NOT the planning session the operator described, ask before assuming any shape for this feature;
none has been chosen.**

---

### Seventeenth handoff, 2026-08-24

*(This entry did not exist as a dated log entry until this file was created on 2026-08-27 -
it lived only as a condensed status block inside `OPENING-PROMPT.md`'s "ACTIVE TASK: ticket
28.9" section, with no numbered handoff of its own even though every session around it had
one. Reconstructed here, text unmodified from the original except the correction note at the
end, so the handoff sequence is complete for the first time.)*

**FIX B DONE 2026-08-24.** The operator picked server-side reuse (over client-side
reconstruction) via a 2-option table when asked directly. Root cause turned out to be broader
than the ticket's own four-level framing: each level (row, phase, turn, whole-transcript) - plus
a FIFTH pass this investigation found, `_claude_turn_count` (the header's "N you / M Claude"
split, which called `_claude_md` per turn just to test truthiness) - independently re-derived
its own markdown fragment from scratch via a fresh call chain into `_render_block`, so a block
already rendered once at row level got rendered again up to four more times. Fix: a plain
`dict[(id(block), policy) -> list[str]]` cache (`_BlockCache`), created once per `_render_page`
call and threaded as a REQUIRED parameter (no default, so a missed call site is a pyright error,
not a silent loss of caching - this caught the fifth pass, `_claude_turn_count`, before it
shipped half-fixed) through 13 functions between it and `_render_block`. `_render_block` itself
is now a thin cache-check wrapper; the old body moved verbatim to `_render_block_uncached`, so
the rendering LOGIC is byte-for-byte unchanged, only WHEN it runs changed.

Verified, not assumed: full suite 1,198 passed (up from 1,197 on `master` at session start - the
"1,175" Fix A recorded is stale, 22 unrelated tests landed since, confirmed via `git stash`),
ruff clean, pyright 0 project errors. Output proved BYTE-IDENTICAL before/after on a real 9.7 MB
session (`cmp` on all four projection files, `git stash`/`stash pop`). Isolated to Fix B alone
(holding Fix A constant via `git stash`), wall time on the ticket's synthetic repro dropped ~31%
(0.511s -> 0.350s); peak memory stayed flat (28.00 -> 28.03 MiB, noise-level) - exactly as
predicted for this shape, since server-side reuse cuts redundant CPU/allocation work, not the
final page weight (only the unchosen client-side-reconstruction shape would have done that). A
new test, `test_render_block_is_memoized_across_copy_levels`
(`tests/test_render_html.py`), pins the cache's own invariant (no `(block, policy)` pair computed
twice) rather than only the byte-equality the existing locked test already covers; confirmed it
actually catches a regression by manually bypassing the cache in a throwaway script, which
reproduced up to 10 calls for a single block.

Real-browser check done per the operator's explicit requirement, and went further than Fix A's
own check: the real session's `conversation.html` served over loopback and opened in a real
Chrome tab via `claude-in-chrome` - zero console errors on load and after every interaction.
Reading the system clipboard triggered an OS permission prompt that froze one `javascript_tool`
call (worked around by not retrying it, per the dialog-avoidance rule in this file's own
system prompt); verification instead read the DOM directly, which the operator-approved plan's
own step 4 explicitly allows as an alternative to a literal clipboard read. EVERY
`[data-copy-src]` element on the real rendered page - 2,013 of them, covering all four levels
(1,477 row/block, 509 phase, 24 turn, 1 whole-transcript) plus the header meta and files index -
was base64-decoded and confirmed to be a substring of the real `transcript.md` fetched from the
same server: 2,013 of 2,013 passing, the same guarantee
`test_copy_as_markdown_payloads_equal_transcript_fragments` checks, now proven against a live
browser-rendered page. Real clicks on the whole-transcript, row-level and phase-level copy
buttons produced zero console errors.

**Not yet committed as of writing this paragraph** - `src/cc_warehouse/render.py`,
`tests/test_render_html.py`, `harness/tickets/28-backlog.md`, and this file are all modified in
the working tree. Full account and exact numbers: `harness/tickets/28-backlog.md`'s 28.9 entry.

**Correction, added 2026-08-27**: the "not yet committed" line just above is stale. This work
was committed as `7842549` before the eighteenth handoff's own session even started - that
session found and fixed the stale claim in this file's banner, and this note fixes it here too.

---

### Sixteenth handoff, 2026-08-24

**Sixteenth handoff, 2026-08-24 (new session).** Opened by reading this file (the fifteenth
handoff, above), which pointed straight at ticket 28.9 Fix B. Before touching it, the operator
asked to look at a specific number on the live dashboard - `~/.cc-warehouse/stats/claude-code-
dashboard-live.html`'s "1.2 min / typical session length" tile looked wrong - and asked for a
thorough, wide-blast-radius investigation into whether the dashboard's numbers were correct at
all: double-counted, missing, or stale values were all named as suspects. Fix B was NOT started
this session either.

**Investigation, not guesswork.** Three parallel Explore agents each read one full source file
(`dashboard.py`, `dashboard_template.html`, `collect.py`) and reported every SQL query, every
JS computation, and every column derivation verbatim with file:line refs. Every consequential
finding was then independently re-verified first-hand: real `sqlite3` queries against
`~/.cc-warehouse/stats/sessions.sqlite` (read-only), a real `find` census of both source trees'
sub-agent filenames, and a decode of the actual bytes in the shipped HTML file. Four real,
distinct defects were found and confirmed, none of them guesses:

1. **A sub-agent transcript existing in BOTH the archive and the live tree was stored TWICE.**
   `collect.py:1364-1367` keyed a scanned transcript by its raw filename stem; the archive names
   a sub-agent `<id>.jsonl`, the live tree keeps Claude Code's own `agent-<id>.jsonl` - different
   stems, different dedup keys, so the "duplicate payloads collapsed" pass never paired them.
   Measured: 1,908 pairs, all with IDENTICAL size/cost/engaged-time (1,908 of 1,908), inflating
   every summed figure corpus-wide by +US$5,750, +119 engaged hours, +69,518 turn rows.
2. **`is_real = 1` blended three unrelated populations into one "session" count**: the
   operator's own interactive sessions (`entrypoint` `cli`/`local-agent`/NULL, the last being
   138 real sessions that predate Claude Code recording the field at all, 2026-02-14..03-11),
   automated one-shot API calls (`entrypoint='sdk-cli'` - one prompt, a few seconds, zero tool
   calls: hooks, titling), and Task sub-agent runs (`is_subagent=1`). Measured: 46.5% of
   "sessions" in the default range were the latter two. This, not arithmetic, is why the tile
   read 1.2 min - the median was correct for the 6,443-row set the page was actually counting;
   that row set was never "your sessions".
3. **The tile itself measured `wall_seconds` (raw file span, includes idle), not
   `engaged_seconds`**, contradicting `PANEL-CONTRACT.md`'s own house rule and the tile's own
   label, with no disclosure either way.
4. **The shipped page carried NO project exclusions at all** (`default_unticked_projects: []`,
   verified by decoding the real HTML's embedded payload) even though
   `~/.cc-warehouse/stats/dashboard-defaults.json` listed six real patterns - `dashboard.py`
   never read that file, only `.claude/commands/dashboard.md`'s own flag-passing did, so a
   direct run (which is what built the page currently on disk) silently dropped them.

Full measured comparison (default range): page showed 6,443 "sessions" / 1.2 min typical /
US$65,310; the operator's true 666-673 interactive sessions measured 55-116 min typical (wall
vs. engaged) / US$54,229-54,524 - sessions +867%, tool calls +65%, replies +62%, cost +20%,
typical length 96x too low.

**Plan approved via ExitPlanMode, then a 2-option question on the one real design fork**: keep
all three populations but split them behind a toggle (recommended - sub-agent cost is real
money, hiding it is worse than blending it), vs. hard-filter to interactive sessions only and
drop the other two from the page entirely. **Operator chose the toggle**, with the exact default
tick-state specified in the question's own preview.

**Four fixes shipped, in dependency order, each proved red-then-green against a real `git
stash` of just its own production diff:**

1. **The double-count (D1)** - `collect.py:1364-1367` strips a leading `agent-` from a
   sub-agent's key before building its cache/dedupe identity; `CACHE_SCHEMA_VERSION` bumped
   1->2 so the one already-populated `scan-cache.sqlite` (97.9% of the corpus, all from a prior
   run) can't serve a stale per-tree row back out under the OLD key. Verified against real data:
   `is_real=1` row count dropped from 10,128 to 8,264 on rebuild, sub-agent files ~halved (3,821
   -> ~1,930), matching the measured 1,908-pair defect almost exactly (small residual is normal
   corpus growth between the two measurements, this machine captures continuously).
2. **The population split (D2)** - new `dashboard.py` classifier `session_kind()` (`is_subagent`
   wins first -> `subagent`; `entrypoint='sdk-cli'` -> `automated`; everything else, including
   the pre-field-recording NULL rows -> `mine`), a new `kind` column in the embedded payload
   (`lookups.kinds` + one int per `S` row, looked up by NAME client-side via `KIND_IDX`, never a
   hardcoded 0/1/2), and a new "Count as a session" control in the page's existing top filter
   bar - `[x] my sessions N  [ ] sub-agent runs N · US$c  [ ] automated one-shots N · US$c` -
   defaulting to `mine` only, each label live-updating via a new `kindCounts()` (date+project
   filtered, kind-toggle-independent on purpose, so a reader sees what TICKING a box would add
   rather than watching a number vanish the moment they tick it).
3. **The tile (D3)** - `dashboard_template.html`'s Overview panel now sorts/medians
   `IDX.S.engagedSec`, not `wallSec`; the note now says which column and which populations
   ("whichever kinds are ticked above").
4. **The exclusions (D4), two parts.** `dashboard.py` gained `load_default_filters()`, reading
   `<out_root>/dashboard-defaults.json` directly as a fallback when no `--include`/`--exclude`
   flag is given, so a direct run and a `/dashboard` run can no longer disagree. Separately, a
   real correctness bug found alongside it: `state.excluded` was keyed on the RAW project index
   while the Projects/Project-month panels grouped by the CANONICAL name (auto agent-worktree
   folders folded onto their parent, `CANON_PROJECT`) - un-ticking a parent left its worktree
   children ticked, and their hours reappeared folded under the very name just excluded. Fixed
   by keying BOTH sides on the canonical name (`CANON_LIST`, `defaultExcludedNames()`); the
   project checklist now also shows one row per real project instead of one per throwaway
   agent-worktree folder, a side benefit of the same fix.

**Step 5 of the approved plan (make the Concurrency panel and its two Overview tiles obey the
new project/kind filters too, via a client-side interval sweep over per-session start/end
timestamps) was explicitly named as the one deferrable piece in the plan itself, and was
deferred** - real timezone-aware calendar-day clipping (`build_overlap` in `collect.py`) is
genuinely complex to reimplement correctly client-side, the panel was never the operator's
actual complaint, and a wrong reimplementation would be worse than an honestly-labelled
limitation. Took the plan's own documented fallback instead: the D1 fix already cleans
`overlap_day`'s numbers (it's built from the same, now-deduplicated `session` table), and the
two Overview tiles' notes now say "whole corpus" on the tile itself, closing a real disclosure
gap `PANEL-CONTRACT.md` had claimed was already closed but wasn't.

**A new headless test harness, `tools/ccstats/tests/node/dashboard_probe.js`, is the other
lasting change.** Before this session `dashboard_template.html`'s client-side JS had ZERO test
coverage - nothing had ever executed it - which is how all four defects above shipped with a
fully green `pytest` suite. The harness runs the REAL generated `<script>` block (not a copy)
under Node's `vm` module against a minimal hand-built DOM stub (real enough for this page's
exact usage: id lookups, classList, dataset, one delegated `querySelectorAll` target; a broader
page rewrite would need it extended, which is intentional - it forces a human to look rather
than silently degrading). One non-obvious mechanic worth remembering: `vm.Script.runInContext`
does NOT attach top-level `let`/`const` bindings as properties of the context object (only `var`
would), so reading `context.FS` after the script runs returns `undefined` even though the
script ran fine - the fix is appending a small epilogue INSIDE the same script text
(`;globalThis.__probe = { state, ... };`) so it shares the real lexical scope, and using
closures/accessor functions (`getFS: () => FS`) for anything the page later REASSIGNS (`FS =
[]` inside `recomputeFilteredSessions`), since a captured snapshot goes stale the moment a
scenario re-triggers `renderAll()`. `test_dashboard_headless.py` (new) builds a tiny synthetic
`sessions.sqlite` with hand-computed expected numbers - 5 "mine" rows with engaged minutes
10/20/30/40/50 (median 30, cost $15.00 exactly), 2 sub-agent and 2 automated rows, one project
and its auto-worktree-suffixed child - and asserts the ACTUAL rendered tile text and `FS.length`
against those hand-computed numbers, never against `dashboard.py`'s own aggregation code, so a
bug in either the Python payload builder or the page's own JS is equally able to fail it. Also
confirms the canonical-exclusion fix directly: excluding the parent's name removes the worktree
child's session too.

**Verified for real, at every layer, matching this project's own "test the code, don't just
read the output" lesson**: 6 new headless tests + 7 new `session_kind()` tests + 8 new sub-agent
dedup tests, all proved red-then-green against real `git stash`ed production diffs; full
ccstats suite grew 110 -> 131 passing; main repo's 1,197-test oracle suite and pyright stayed
untouched and green (one pre-existing, unrelated pyright gap in `tests/test_render_open.py`,
confirmed via `git status` to predate this session, not touched); ruff clean repo-wide. A
scratch rebuild (`CCSTATS_OUT` pointed at a session-scratchpad dir, never
`~/.cc-warehouse/stats`) was run through the real `collect.py` + `dashboard.py` pipeline on this
machine's REAL corpus and opened in an actual Chrome tab via `claude-in-chrome` (loopback-served
on `127.0.0.1:8931`, `file://` is refused by the browser tool - see `harness/GOTCHAS.md`):
zero console errors on load and after interaction; the default view read exactly "668
sessions with a reply" / "55.6 min typical session length" / "US$ 54,506 API cost", matching the
headless probe's own numbers to the byte; ticking "sub-agent runs" live-recomputed every tile
with no reload (668 -> 2,184 sessions, "typical session length" 55.6 -> 4.6 min - directly
demonstrating the exact mechanism that produced the original 1.2 min bug - and API cost US$
54,506 -> 60,053, matching 54,506+5,547 exactly); the project checklist showed one row per real
project, named worktrees (e.g. `-.worktrees-ui-first`) correctly left un-folded per the existing
rule. Server killed and tab closed afterward.

Two commits, both pushed: `cf71d3c` (the collect.py dedup fix + its tests) and `4898c5f` (the
dashboard classifier, toggle, tile fix, exclusion fixes, the new Node harness, and their tests).
Every fix was verified against a session-scratchpad copy FIRST, before touching real data.

**The real `~/.cc-warehouse/stats` was then rebuilt for real, with the operator's explicit
go-ahead (asked via a 2-option question).** `collect.py`: `real_sessions` 10,128 -> 8,265 (the
D1 dedup fix landing on the real corpus, matching the scratch-run's proportional drop almost
exactly). `dashboard.py`: the real, already-existing `dashboard-defaults.json` (32 raw project
names, six patterns, saved by a prior session's `/dashboard` run) was picked up automatically
via `load_default_filters()` with NO flags passed - confirmed by decoding the rebuilt page's own
embedded payload (`default_unticked_projects`: 32 entries, was `[]`) - proving the D4 fix on the
real file it was written to fix, not just the synthetic one. Opened in a real Chrome tab
(loopback, `127.0.0.1:8932`): default view **488 sessions, 53.2 min typical session length**
(was 1.2 min), "Projects: 20 excluded" (32 raw names folded to 20 canonical, the D4b fix),
zero console errors. Both temporary HTTP servers (scratch on 8931, real on 8932) were killed and
both tabs closed afterward; nothing was left running.

**Three more operator follow-ups, same session, after seeing the toggle live, all DONE:**

1. **"sub-agent runs" now defaults ON too** (`DEFAULT_KINDS` -> `{mine, subagent}`), only
   "automated one-shots" still defaults off - a sub-agent is real work done on the operator's
   behalf, same as watching a Task call run. `test_dashboard_headless.py`'s default-view test
   rewritten for the new 7-row default population (was 5); a new test covers explicitly
   dropping to mine-only, since that is now the thing a reader has to opt INTO, not the default.
2. **The filterbar and panel-nav layout were tightened.** The filterbar wrapped onto three
   lines once the toggle row landed, with the summary line stranded alone on its own row -
   restructured into two explicit rows instead of one unconstrained wrapping flex row.
   Fixing this surfaced a real, separate bug: the sticky panel-nav bar below it was pinned at
   `top: 49px`, a hardcoded guess matching the OLD single-row filterbar height, already stale
   the moment the toggle row was added - replaced with `setNavTop()`, which measures the
   filterbar's real rendered height (re-measured on resize) instead of guessing. The panel-nav
   links themselves were also restyled from plain inline text (read as one continuous run) into
   bordered chips, with a permanent edge-fade (`mask-image`) on the scrolling strip as a visual
   "there's more this way" cue. `dashboard_probe.js`'s DOM stub gained `document.querySelector`,
   `document.documentElement`, and real `style.setProperty`/`getBoundingClientRect` stubs,
   needed by the above - the harness needing extension for a UI-only change is by design (its
   own header comment says so), not a gap.
3. **The real, saved `~/.cc-warehouse/stats/dashboard-defaults.json` held the WRONG exclude
   list**, discovered when the operator looked at the live "Projects" dropdown and it didn't
   match what they remembered dictating. Confirmed by direct comparison: the file on disk (6
   generic patterns - `.claude-worktrees-agent-`, `.worktree`, `private-tmp-`,
   `private-var-folders-`, `scratchpad`, `orchestration-drill`, mtime 2026-08-24T01:25, before
   this session started) does not match `CLAUDE.md`'s own "Fourth round" record of the
   operator's real 23-pattern list from 2026-08-22. **This was not introduced by this
   session** - the file was never written by anything in this session, only read, and its
   mtime predates this session's start. Something earlier today (not identified, not this
   session) replaced the operator's real list with a generic scratch/noise filter. Restored the
   real 23-pattern list from `CLAUDE.md` verbatim (tmp-file + `os.replace`, R2's idiom, even
   though this file lives outside the repo entirely). One value needed reconstruction:
   `CLAUDE.md` redacts the operator's real local username as `<local-username>-` (this repo's
   own privacy rule for anything git-tracked); the real machine account is `fonzarelli` -
   confirmed, not assumed, by checking that real `project_label` values starting with
   `fonzarelli-` actually exist in the corpus (`fonzarelli-.claude`, `fonzarelli-Temp`, etc. -
   Claude config/library folders outside `~/CODE`, exactly what that pattern exists to catch)
   before writing it. Dashboard rebuilt with the restored list: 58 raw names -> 57 canonical
   exclusions (was 32 -> 20 under the stale list), "my sessions" 564 (was 668). Verified in a
   real Chrome tab, zero console errors. **This file lives outside the repo
   (`~/.cc-warehouse/stats/`, not tracked in git at all per this project's own DATA-vs-CODE
   separation) - nothing to commit for this fix, it is a local-data correction only.**

One commit, pushed (`c10c851`, items 1-2; item 3 has no git artifact by design - see above).
132 ccstats tests passing, ruff clean.

**What was NOT done:** ticket 28.9 Fix B, again untouched - this is now the SECOND handoff in a
row where an operator-initiated redirect landed before Fix B was ever started (see "Next task"
at the top of this file). Step 5 of the dashboard plan (client-side concurrency reimplementation)
was explicitly deferred, not forgotten - see above. **Also unresolved and worth a future
session's attention, not chased down here**: WHAT overwrote the real `dashboard-defaults.json`
with a generic list sometime before 2026-08-24T01:25 - no session's own account in this file
claims to have done it, and the mechanism is unknown.


---

### Fifteenth handoff, 2026-08-24

**Fifteenth handoff, 2026-08-24 (new session).** Opened by reading this file (the fourteenth
handoff, above), which pointed straight at ticket 28.9 Fix B. Before touching that, the
operator asked for the `claude-code-dashboard-live.html` file to be opened in a real browser
(served over loopback, per `harness/GOTCHAS.md` - the browser tool refuses
`file://`), which was done cleanly, then killed on request. The operator then set a standing
preference, now recorded in memory (`give-full-paths-and-links.md`): use `~/...` in any path
shown to them, never the literal `/Users/<name>/...` form (it leaks the machine's real
username into anything that records the text), and do not spin up a local server by default
for a plain file path - only when the browser tool itself needs one.

Asked how deterministic `dashboard.py` is and how long the pipeline takes, and told to go
measure it rather than guess. **A real mistake happened here**: checking `dashboard.py
--help` (which the script does not support) actually ran `collect.py` for real against the
LIVE `~/.cc-warehouse/stats/` data instead of a scratch copy - this session's own memory rule
about testing with `CCSTATS_OUT` was not applied. Disclosed immediately, confirmed harmless
(refreshed the real stats DB early, touched nothing session-related, no `.building` file left
behind), and the operator approved rebuilding the live dashboard page to match. Measured
result, real data: `dashboard.py` is deterministic except one timestamp field (byte-identical
output twice, confirmed with `cmp` after normalising that one field); the full pipeline
(`collect.py` + `dashboard.py`) takes under 10 seconds warm, ~30-45s cold (estimate from an
earlier session's own measurement on a then-smaller corpus).

**The operator then asked to check whether real sessions in `~/.claude` were going
uncaptured**, suspecting the SessionEnd hook itself might not be firing. It was firing fine
(307/307 real hook-log entries "ok", zero errors) - the real, live finding was a 37-session
backlog from the prior ~2 hours, which `ccw sweep` cleared. **The operator explicitly rejected
this as "just a temporary manual fix"** and asked for the actual mechanism and real, durable
fixes, presented as options first. That investigation surfaced two independent, previously
undiscovered real bugs, found by reading logs and code directly rather than guessing:

1. **The weekly `ccw archive --to` job had been silently failing for two weeks** (612 real
   items failing, 0 folders written on its last real run) - `archive.migrate`'s vault-gone
   fallback path (a stale/missing archive folder falls back to reading the OLD vault store)
   was never updated when `objects/` was retired (ticket 27.4, 2026-08-20), so it tried to
   read a directory that no longer exists. Fixed same-session, oracle-tests-first, verified
   on real production data (`ccw archive --to ~/cc-warehouse-archive`: 612 failed -> 8 failed
   after the first fix, then 8 -> 0 after a second fix for the genuinely-permanent case
   below). Commits `db03dd6` (the vault-fallback fix, landed BEFORE the plan-mode arc below)
   and `24c9ea6` (the permanent-non-session case).
2. **`sweep()` has no per-item exception boundary at all** (`capture_transcript`'s own
   docstring already said so: "any deeper failure propagates to the caller's never-raise
   boundary" - the HOOK path has one, `_run_hook`; sweep does not) - one contended catalog
   write can silently abort the ENTIRE daily sweep batch mid-run, with nothing printed or
   logged, and everything still queued in that run simply never attempted (picked up by the
   next sweep, not lost, but invisible in between). This exact gap was already flagged, not
   yet fixed, in `harness/tickets/31-sweep-full-corpus-cost.md` section 31.4 (2026-08-20,
   "logging only... the retry loop stays unshipped... blocked on a confirmed exception").

**Entered plan mode** (operator-approved, `Plans/majestic-floating-cray.md`) to design real
fixes rather than another catch-up, after two Explore-agent codebase surveys both failed
twice on a transient Anthropic API 529 (server overloaded) - rather than keep retrying, every
file was read directly instead (`capture.py`, `catalog.py`, `store.py`, `sweep.py`, `cli.py`,
`notify.py`, `doctor.py`, `contract/DESIGN.md`'s R14, the freshness-check plugin and its
tests). The operator's own explanation of `win_go_app_test`'s rapid-fire session bursts
(Herdr/subagent-driven automated testing, confirmed NORMAL, not a bug to chase) shaped the
final plan: the real fix is tolerating that load, not investigating that project further.

**Four pieces shipped, each oracle-tests-first (red confirmed against unfixed code, then
green), each committed and pushed separately:**

- **Retry-with-backoff on catalog writes** (`capture.py`, commit `5aef3d3`). The real answer
  to "run captures without stepping on each other": SQLite's own reserved lock (`BEGIN
  IMMEDIATE` + the existing 5s `busy_timeout`) already coordinates writers (R14) - the gap
  was giving up after exactly one wait. `_capture_locked`'s two catalog calls now retry up to
  3 times on `sqlite3.OperationalError` matching "locked"/"busy" only; any other exception
  still raises immediately, unchanged.
- **Sweep per-item safety net + a durable failure log** (`sweep.py`, commit `a19710a`),
  directly answering both "stop one bad session from killing the batch" and "log bad sessions
  for review". `_capture_item` now catches any exception (matching `_archive_subagent`'s own
  existing pattern a few lines above it in the same file), logs it to the same
  `logs/capture.jsonl` the hook path's stage-failure logging already uses, and lets the batch
  continue. `BatchReport`/`ItemOutcome`'s shape is unchanged.
- **Watch the 3 real launchd jobs for failures** (`plugins/cc-capture/hooks/ccw-freshness-
  check.py`, commit `8d88cea`), directly answering "watch the daily/weekly jobs" - `ccw
  doctor`'s own PASS/FAIL verdict never covered these at all, which is exactly why the
  archive-job incident above sat unnoticed for two weeks. Shells out to `launchctl print
  gui/<uid>/<label>` for `com.captaincodeau.ccw-sweep`/`-archive`/`-repair`, best-effort and
  guarded (never blocks session start; a missing `launchctl`, e.g. non-macOS, reads as
  unknown, not broken).
- **Backlog growth-rate context on an already-escalating alert** (same file, commit
  `e35b7b6`), answering "alarm on a fast-growing backlog, not just a broken job" - applying
  this file's own hard-learned lesson (ticket 24.7's first draft alarmed on the raw
  uncaptured count and fired every session on a healthy machine): the growth rate rides along
  as context on a message the doctor-streak signal ALREADY decided to show, never as an
  independent trigger, because this session's own real numbers (37 in ~2h from ordinary
  multi-session usage, ~18/hr) are not reliably distinguishable from a real problem by rate
  alone.

**Verified against real production state at every step, not just pytest**: full suite grew
from 1,175 to 1,197 passing tests across the arc; ruff and pyright stayed clean throughout
(one pre-existing, unrelated pyright gap in `tests/test_render_open.py` predates this
session, confirmed via `git stash`, not touched). The frozen `ccw` binary was reinstalled
(`uv_tool_reinstall_current_project --no-extras`) after the code changes - this session
independently re-discovered the "editing the repo does not change what runs" trap
`CLAUDE.md`'s own hard rule already documents, the first time by forgetting it (an accidental
real-data `collect.py` run, see above), the second time by verifying a fix against the OLD
binary and getting confused before catching it. The real weekly `ccw archive --to` job was
run for real (`517 folders written, 0 failed`, exit 0) and the real launchd job was
kickstarted end-to-end (`launchctl kickstart`), confirmed via a background wait to finish
with `last exit code = 0`, and the freshness-check script confirmed silent afterward. The
plugin cache (a SEPARATE deployment surface from the `ccw` binary - Claude Code reads
`~/.claude/plugins/cache/cc-warehouse/cc-capture/<commit-hash>/`, not this repo directly) was
stale until the operator ran `/plugin marketplace update cc-warehouse` and `/reload-plugins`
themselves at the end of the session; confirmed byte-identical to this repo's copy afterward
(`diff`, exit 0) against the new cache directory `e35b7b6bb2bc`, matching this session's own
final commit hash exactly.

**What was NOT done:** ticket 28.9 Fix B (see "Next task" at the top of this file - entirely
untouched this session, the redirect happened before it was ever started). No other open
item from this file's own tracking was touched.


---

### Fourteenth handoff, 2026-08-24

**Fourteenth handoff, 2026-08-24 (new session).** Opened by reading this file (the thirteenth
handoff, above), which pointed straight at ticket 28.9's "ACTIVE TASK" section and its
operator-approved two-fix plan. Did Fix A only, exactly as that section specified: build it,
test it for real (gates + re-profile + a real Chrome tab), stop before Fix B.

**Fix A DONE.** `_render` and `_render_page` (`src/cc_warehouse/render.py`) now encode each
fragment to UTF-8 bytes and join with `b"\n".join(...)` instead of joining `str` and encoding
afterward - the fix scoped to exactly these two functions' final join, not the "dozens of call
sites" the ticket's own plan predicted might be needed, because encoding at that one boundary
per function was enough to stop the astral-plane 4x-inflation from reaching the whole document.
`render_markdown`/`render_html`'s PUBLIC return type changed from `tuple[str, str]` to
`tuple[bytes, bytes]` (both `build.py` call sites were encoding the result immediately anyway,
so `build.py` simplified rather than grew). That public-type change reached ~40 call sites
across 10 test files (`test_matrix.py`, `test_real_shapes.py`, `test_render_html.py`,
`test_render_html_regressions.py`, `test_render_md.py`, `test_render_md_regressions.py`,
`test_surrogates.py`, `test_thinking_withheld.py`, `test_truncation.py`, `test_chrome.py`) -
each fixed by decoding to `str` once at the point of use (a shared helper where one already
existed, e.g. `test_matrix.py`'s `_rendered`, otherwise a small local wrapper), with zero
assertion logic changed anywhere. `test_surrogates.py` needed one real adaptation, not just a
decode: two tests used to call `.encode("utf-8")` on the result to prove a lone surrogate didn't
break rendering; that encode now happens INSIDE `render_markdown`/`render_html`, so calling the
function at all (and it not raising) is now the assertion.

**Verified, not assumed, at every step**: full suite 1,175 passed, ruff clean, pyright 0 errors
(one pre-existing, unrelated pyright gap in `tests/test_render_open.py` was found and confirmed
via `git stash` to predate this session - not touched, out of scope for this ticket). Output
proved byte-identical before/after via `git stash`/`stash pop` around the production diff, on
TWO independent payloads: the ticket's own synthetic repro (1.60 MiB in, 40 turns) and a real
8.3 MB session pulled from this machine's own `~/.claude/projects` - all 5 projection files
(`transcript.md`, `transcript.compact.md`, `conversation.html`, `conversation.compact.html`,
`manifest.json`) matched with `cmp` both times. Peak memory on the synthetic repro dropped from
61.16 MiB to 28.00 MiB (peak/input ratio 38.18x -> 17.48x) - beating the ticket's own ~26 MiB /
~27x estimate, because the fix landed in both `_render` (markdown, called a second time inside
`_render_page` for the whole-transcript copy payload) and `_render_page` (HTML) rather than only
the HTML page's own join the estimate was based on.

**The real-browser check ran twice** - the Chrome extension was not connected on the first
attempt (a live occurrence of the same environment gap prior handoffs hit, not a new finding),
and the operator was asked to reconnect it rather than the session skipping the check or
declaring the fix done on `pytest` alone. On retry: the real 8.3 MB session's `conversation.html`
served over `127.0.0.1:8917` and opened in an actual Chrome tab via `claude-in-chrome`. Zero
console errors on load and after interaction. All four copy-button levels clicked with the
clipboard read back programmatically (`navigator.clipboard.readText()`, comparing against
`transcript.md` fetched from the same server): the whole-transcript button's output is
CHARACTER-IDENTICAL to `transcript.md` (545,316 chars, `===` true), and the row/phase/turn
buttons' output is each a substring of it - directly exercising
`test_copy_as_markdown_payloads_equal_transcript_fragments`'s own guarantee outside pytest, not
just trusting the test. Icons (including the astral-plane ones Fix A is about) rendered correctly
and round-tripped through copy intact, e.g. a row-level copy came back as
`"<details>\n<summary>🧩 session events</summary>..."` (a real 🧩 JIGSAW PUZZLE PIECE,
un-mangled).

One commit, pushed: `fb85934`, `fix: cut render_html/render_markdown peak memory 2x (ticket
28.9, Fix A)`. `harness/tickets/28-backlog.md`'s 28.9 entry and this file's "ACTIVE TASK" section
were both updated in place with the full account, matching every other closed step in this file.

**The operator then said: do Fix B in a new session, stop here now.** Fix B (the four-level
copy-as-markdown base64 duplication, Mechanism 2 in the ACTIVE TASK section above) was NOT
started - no code read or written toward it beyond what the investigation already covered before
this handoff. The two candidate shapes (server-side reuse vs. client-side reconstruction) are
still an open pick for whichever session does Fix B; see step 3 of the plan above. This file's
top "Next task" pointer and the ACTIVE TASK section's own status line were updated to send a
fresh session straight at Fix B rather than back through Fix A's now-closed investigation.

**What was NOT done:** Fix B, and everything downstream of it in the plan (step 4's browser
test). Nothing else was touched this handoff.


---

### Thirteenth handoff, 2026-08-24

**Thirteenth handoff, 2026-08-24 (new session).** Opened by reading this file, then asked the
operator to pick a starting point from ticket 28's backlog via a 4-option question (`--open`
28.1 / `--limit` on sweep 28.3 / the `render_html` perf issue 28.9 / stop for now). Operator
picked `--open`.

**28.1 DONE, scoped to `ccw render` only.** `notify.open_folder` reveals the folder a capture
landed in; nothing opened the actual rendered page. Read the specimen's own four `--open` sites
(`claude_code_transcripts/cli.py`, stdlib `webbrowser.open`) for the shape, then built the
cc-warehouse equivalent rather than porting it: `notify._open_with_system_default` is now the one
shared platform-opener primitive (R9, the exact C12 pattern ticket 28.13's architecture review had
just recommended), with `open_folder` (existing, reveals a folder) and the new `open_page` (opens
one file) as thin named wrappers. `cli.py` gained `_open_rendered_page`, which picks the archive
folder's `conversation.html` when `archive_root` is configured (mirroring `_reveal_target`'s own
"the archive is the deliverable" precedent) or the personal `projections/` copy otherwise, wired
to a new `--open` flag on both the `--session s:<key>` and ad-hoc forms of `ccw render`.
Best-effort throughout (DESIGN 12): a broken opener can never fail a render.

`ccw share`'s multi-session `index.html` was deliberately left out of this pass to keep the change
small and testable in one sitting; flagged in the ticket's own DONE note as a fast follow-up if
wanted, not attempted here.

8 new oracle tests (`tests/test_render_open.py`), proved red-then-green with a real `git stash` of
just the production diff (7 of 8 failed pre-fix; the 8th, a pre-existing typo-guard regression
test, was correctly unaffected). One test written for a third scenario -
`keep_projections=false` with no `archive_root`, meant to prove `--open` is a silent no-op with
nothing to open - was dropped after measuring that `config.py`'s own `_keep_projections` refusal
makes that combination unreachable: it silently falls back to `keep_projections=True` rather than
ever leaving a session with nowhere to render. The no-op branch in `_open_rendered_page` stays as
defensive code, not something a real config can trigger. Full suite: 1,163 passed, ruff clean,
pyright 0 errors on `src`/`tests`.

Ticket 28's own entry (`harness/tickets/28-backlog.md`) and this file's "Also on record, not
scheduled" section above were both updated in place to mark 28.1 done, rather than left to drift
the way 28.19 did.

One commit, pushed (production + tests + doc updates together, since the change is small).

**What was NOT done:** nothing new opened this part of the handoff. See the continuation directly
below for 28.3, picked next in the same session.


**Same day, continuing the thirteenth handoff.** Asked the operator to pick again from the
remaining backlog via a 3-option question (`--limit` on sweep 28.3 / the `render_html` perf issue
28.9 / stop for now). Operator picked `--limit` on sweep.

**28.3 DONE.** `ccw sweep --limit N` (and `--limit=N`) caps `sweep._walk_source`'s transcript list
to the first N in sorted (path) order - useful for exercising a slice of a source tree that can run
to tens of thousands of files in a real deployment, without walking the whole thing. Applied
identically to a real sweep and to `--dry-run` (one walk implementation, one place the cap lives).
It bounds candidates WALKED, never sessions STORED: the existing already-known skip still applies
on top, and the orphan-object catch-up pass (reads `objects/`, not the source tree) is untouched.
A malformed value (missing, non-numeric, zero, or negative) is a usage error, exit 2, matching
`--source`'s own validation posture - a silent `--limit 0` would look identical to a fresh, empty
warehouse. Narrowing a run loses nothing: a later unlimited sweep still picks up whatever a limited
one left behind, the same property `--since`/`--until` already have.

12 new oracle tests (`tests/test_sweep_limit.py`), proved red-then-green with a real `git stash` of
just the production diff (8 of 12 failed pre-fix; the other 4, the usage-error tests, were already
satisfied by the pre-existing "unrecognised option" guard before `--limit` was a known flag -
correctly unaffected, not a gap). Full suite: 1,175 passed, ruff clean, pyright 0 errors.

One commit, pushed. Ticket 28's own entry and this file's backlog pointer were both updated in
place.

**What was NOT done:** nothing new opened this handoff. Standing candidates for a future session:
ticket 28's remaining backlog items (28.2, 28.9, 28.10, 28.11, 28.12, 28.14), and `ccw share --open`
as a possible fast follow-up to 28.1's work above.


---

### Twelfth handoff, 2026-08-23

**Twelfth handoff, same day, same session, prompted by the operator's own tip ("you can always use
Herdr to launch a claude code session in a new pane... to do a fresh test without context
pollution") plus three follow-up questions.**

**Herdr verification, not just unit tests.** Split a sibling pane, started a fresh Claude Code
session (`herdr agent start`), ran `/plugin marketplace update cc-warehouse` in it (confirmed:
"Updated 1 marketplace, 1 plugin bumped", and the cache grew a new commit directory,
`~/.claude/plugins/cache/cc-warehouse/cc-capture/<new-hash>/`, already carrying the SessionStart
entry). Started a SECOND, genuinely fresh session and confirmed via the shared hook log
(`~/.claude/logs/ccw-hook.log`) that Claude Code's own SessionStart plumbing - not a manual script
invocation - actually fired `ccw-freshness-check.py` and logged a fresh, correct "ok" line. Closed
both test panes afterward.

**The operator then asked three questions, all answered by checking live state rather than
assuming:** (1) had the discarded `gz-claude-code-plugins` commit been reverted - no, not yet, but
confirmed harmless (`extraKnownMarketplaces` in `~/.claude/settings.json` has NO entry for that
marketplace at all - fully removed, not just disabled); (2) the full path to `cc-capture` and
whether it is the same one in this repo - yes, source at
`plugins/cc-capture/` here, running copy at
`~/.claude/plugins/cache/cc-warehouse/cc-capture/<commit-hash>/`; (3) what could prevent this exact
mistake from recurring, "not even accidentally".

**Answering (3) surfaced a SECOND real defect, this time in `ccw doctor` itself**, found while
designing the safeguard rather than assumed: `_hook_commands` globbed every plugin's cached
`hooks.json` with no regard for whether Claude Code still had that plugin enabled, so a retired
plugin's leftover cache directory (proven to exist on this exact machine -
`~/.claude/plugins/cache/gz-claude-code-plugins/claude-transcript-exporter/d8107737a5ee/`, and it
even carries Claude Code's OWN `.orphaned_at` marker, timestamp 2026-08-10T10:01:39Z, ~23 minutes
after the ticket 28.19 commit) could still be reported as a working capture hook. Fixed
oracle-tests-first (3 new tests in `tests/test_doctor.py`, proved red against the pre-fix code:
a plugin absent from `enabledPlugins`, one explicitly `false`, and the positive case of one that
really is `true`): `doctor.py` now reads `enabledPlugins` and only counts a plugin-sourced hook when
its exact `plugin@marketplace` key is `true` there, and the `hook` line now NAMES the serving
plugin (`found via cc-capture@cc-warehouse: ...`). Verified against real data via the editable dev
build (`uv run ccw doctor`): correctly ignores the real orphaned `gz-claude-code-plugins` cache and
correctly names `cc-capture@cc-warehouse`. One incidental fix along the way: a docstring using the
word "identical" tripped the R8/F6 guarantee-words fence
(`tests/test_fences.py::test_guarantee_words_cite_their_proving_test`) - reworded rather than
exempted, since the word was decorative prose, not an actual guarantee this function proves.

**A new hard rule went into `CLAUDE.md`** naming `cc-capture@cc-warehouse` as the only live capture
plugin and stating the exact check to run (`enabledPlugins`) before touching any hook file in any
repo. **Two memory files were also written/updated** (outside this repo, in the project's
Claude-memory directory): `ccw-deployment-on-this-machine.md` gained the plugin-migration facts and
the `.orphaned_at` timeline; a new `verify-live-state-before-editing-hooks.md` (type: feedback)
records the general lesson - check a tool's own live enabled-state before editing its
config, never infer it from a repo's docs - for reuse beyond this repo.

**The operator then chose, from a 3-option question, to "clean it up"**: in
`gz-claude-code-plugins`, `git revert --no-edit` undid the discarded commit (history preserved,
nothing force-pushed), and both that repo's top-level README and the plugin's own README gained a
prominent "RETIRED 2026-08-10" notice pointing at `cc-capture@cc-warehouse` in this repo. Both
commits pushed.

Five commits this handoff, all pushed to cc-warehouse: the `_run_hook` skip-reporting fix, the
freshness-check rebuild in the right plugin, the `doctor.py` `enabledPlugins` safeguard, and the
`CLAUDE.md` hard rule (four separate commits from earlier in the day, listed here for completeness)
plus none new to cc-warehouse in this specific handoff beyond what the "24.7 DONE" and
`enabledPlugins` sections above already cover. Two commits pushed to `gz-claude-code-plugins`: the
revert and the retirement-notice docs commit. Full cc-warehouse suite re-confirmed green after
every change this handoff: 1,155 tests, ruff clean, pyright 0 errors.

**What was NOT done:** nothing from items 1-7, or from tickets 24.7/28.13/28.19/28.22/30, remains
open as of this twelfth handoff. The `gz-claude-code-plugins` repo itself was NOT archived on
GitHub - the operator picked the middle option (revert + retirement notice), not the "archive the
whole repo too" option, so that remains available as a future ask if wanted but is not done. The
only standing candidate for a future session is ticket 28's backlog register (28.1, 28.2, 28.3,
28.9, 28.10, 28.11, 28.12, 28.14).


---

### Eleventh handoff, 2026-08-23

**Later the same day (eleventh handoff).** Given a straight choice between ticket 24.7
(session-start capture freshness) and a ticket 28.9 performance fix, the operator picked 24.7,
after first asking to confirm before the change touched a second, live repo (`gz-claude-code-plugins`)
whose `hooks.json` controls what runs at every real SessionStart on this machine - confirmed
before any edit there.

Two fixes landed, one per repo. In cc-warehouse: `_run_hook`'s `CCW_SKIP_HOOK=1` path used to
return 0 with zero record anywhere; it now reports `skipped_disabled` through the same
`notify.report` path `skipped_unchanged` already uses, proved red-then-green
(`tests/test_capture.py::test_kill_switch_reports_skipped_rather_than_silently`).

In the plugin repo: a new `SessionStart` hook, `ccw-freshness-check.py`, registered in
`hooks.json` beside the existing `SessionEnd` capture hook. **A real design correction was
found and fixed before shipping, not after**: the ticket's own wording ("reads ticket 23's gap
figure") reads as "alarm on the Uncaptured: N count", and the first draft did exactly that with
fixed numeric thresholds. Run against this machine's real data, it printed ALERT on a perfectly
healthy install, because that count sits at 250-350 here permanently (old sessions predating the
archive, hidden/warmup sessions) and `doctor.py` itself marks it "ok", never blocking. Rebuilt to
key the alarm on `ccw doctor`'s own PASS/FAIL exit code instead - the same signal `ccw-watch`
already relies on - escalating on consecutive broken session-starts in a row (a streak persisted
in `~/.claude/logs/ccw-freshness-state.json`), with the raw gap figure riding along as context
rather than as the trigger. Verified against real data three ways: the real 298-uncaptured healthy
machine now prints nothing; a simulated 6-session outage (`CCW_BIN` pointed at a fake failing
`ccw`) escalated mild -> WARNING (streak 2-4) -> ALERT (streak 5+); a simulated recovery went
silent and reset to streak 0 immediately.

The plugin repo had no test suite at all before this. Its first test file,
`tests/test_freshness_check.py` (stdlib `unittest`, no new dependency, 14 tests), covers the
escalation tiers, the streak persistence, the `uv tool run` fence (matched narrowly against the
argv-list shape so it does not flag the historical incident documentation already in `ccw-hook.py`'s
own docstring), and a hand-kept mirror of cc-warehouse's `CCW_*` env var list (necessarily
hand-kept, not a live cross-repo import - the two repos share no dependency). All 14 passed. Full
account, including why the fences do not live in cc-warehouse itself (hardcoding a sibling repo's
local path would violate this project's own "no personal machine paths" rule): the "24.7 DONE
2026-08-23" section of `harness/tickets/24-make-capture-work.md`.

Full cc-warehouse suite re-confirmed green after the fix: 1,138 tests, ruff clean, pyright 0
errors.

**CORRECTION, same handoff, found immediately after the operator read the summary above:** the
SessionStart hook had been built and pushed into the WRONG, DEAD plugin. `claude-transcript-
exporter@gz-claude-code-plugins` was already retired - ticket 28.19 had moved the plugin into this
very repo two weeks earlier (2026-08-10, `4b8dde4`, installed as `cc-capture@cc-warehouse`), and
this file's own "Also on record" list and CLAUDE.md's OPEN/next section were both stale about it,
still calling 28.19 open. Proof: `~/.claude/settings.json`'s `enabledPlugins` carries only
`"cc-capture@cc-warehouse": true` - the old slug is not merely `false`, it is absent entirely, and
the plugin cache for it is pinned to a commit from before this session even started.

Redone in the right place: `ccw-freshness-check.py` and the `SessionStart` hooks.json entry now
live in `plugins/cc-capture/hooks/` (this repo), identical logic to the discarded copy. This time
the oracle tests landed inside cc-warehouse's OWN gated suite
(`tests/test_cc_capture_freshness.py`, pytest, 14 tests) instead of a hand-rolled `unittest` file in
a separate repo - the original ticket's "the fences belong in this repo" is now literally true,
since the plugin genuinely is in this repo. One test could not exist in the discarded version at
all: a LIVE check that every `CCW_*` name the wrapper sets is a real name in
`cc_warehouse.config.ENV_VARS`, importing that module directly rather than hand-mirroring its
contents. Verified against real data again in the new location: the real machine (310 chronic
uncaptured, healthy doctor verdict) produces no output and one `"status": "ok"` log line.
**"Left in place rather than deleted" below is STALE as of the twelfth handoff - see that section**;
ticket 28.19's own entry in `harness/tickets/28-backlog.md` was corrected from open to
`DONE 2026-08-10`. Full account: `harness/tickets/24-make-capture-work.md`'s "24.7 DONE" section
and `harness/tickets/28-backlog.md`'s corrected 28.19 entry.

Full cc-warehouse suite re-confirmed green after the correction: 1,152 tests, ruff clean, pyright 0
errors.

**What was NOT done, as of the eleventh handoff:** nothing from items 1-7, or from tickets
24.7/28.13/28.22/30, remained open. Ticket 28.19 was not open either - it was already done, the
record was just wrong. **This was not actually the end of the day - see the twelfth handoff below
for real-data verification via Herdr, a second real defect found and fixed in `ccw doctor` itself,
and cleanup of the discarded repo.**


---

### Tenth handoff, 2026-08-23

**Later the same day (tenth handoff).** Given a straight choice between "incremental collect" and
picking an item from ticket 28's backlog, the operator picked incremental collect. See the
correction inside item 7 above for the full technical account - short version: `collect.py` now
caches each transcript's own scan result in a sibling `scan-cache.sqlite`, keyed by path + size +
mtime, so an unchanged file (almost all of them, once a session ends) is reused instead of being
re-read and re-parsed. A price or timezone change auto-invalidates the whole cache, since both are
baked into every cached row (`cost_usd`, `local_date`/`local_hour`) and an old row would otherwise
keep reporting stale numbers forever. `--no-cache` and `--limit`'s "never overwrite the cache with
a partial slice" behaviour are both new flags/rules, documented in `README.md`.

11 new tests (110 total), each proved red-then-green against a real `git stash` of just the
production changes. Measured on the real archive via a `CCSTATS_OUT` scratch dir (never touching
`~/.cc-warehouse/stats`): 26.9s cold, 7.5s warm with nothing changed - roughly 3.6x. A follow-up
attempt to shave the warm run further (reusing a cache hit's own raw JSON text instead of decoding
then re-encoding it) was tried and measured to make no real difference, so it was reverted in favour
of the simpler, symmetric code rather than kept on the assumption it must help.

One commit, pushed. Full suite re-confirmed green (1,137 main-repo tests, 110 ccstats tests, ruff
clean on both).

**What was NOT done:** item 7 is now fully closed - nothing from items 1-7 remains open. Standing
candidates for a future session, unchanged from the ninth handoff: ticket 24.7 (session-start
capture freshness, partly closed already from outside this repo) and the remaining items in ticket
28's backlog register.


---

### Ninth handoff, 2026-08-23

**Later the same day (ninth handoff).** Given the two remaining candidates, ticket 28.13 (the
architecture board) and ccstats polish, and told to do both, one at a time.

**Ticket 28.13.** The named review skill was not enabled in this session, so 5 parallel read-only
agents substituted for it - the same lens split as the 2026-07-24 review, plus a new lens for
`archive.py`, a 900+ line module that postdates that review entirely and had never been looked at
by this board. Two of the agents' findings were consequential enough to verify first-hand rather
than trust: both turned out to be real, LIVE bugs, not just architecture debt, and were fixed the
same session with oracle tests written first, proved red-then-green against the pre-fix code -
`write_subagent` silently dropping a same-size, content-different re-capture with no record
anywhere (worse than the session-writer twin ticket 30 had just fixed, since sub-agents have no
manifest to record a refusal in), and `ccw share --out` having no guard against writing inside the
warehouse's own store (unlike its `ccw render --out` sibling). The whole board was then re-derived
and re-ranked at HEAD, with the new top recommendation (C12) being exactly the lesson those two
bugs taught: one shared "replace if larger" rule instead of three near-identical copies. Three
commits, all pushed: `d9a2227` (the write_subagent fix), `4824098` (the share guard fix), `e067c8c`
(the board itself).

**ccstats polish.** Split all three flagged long functions (`collect.scan_transcript`,
`facts.compute`, `make_docs.main`) into named helpers, verified byte-identical against real data
before and after every split via `git stash` - a frozen transcript set, the same real
`sessions.sqlite`, and a real `DATA-GUIDE.md` regeneration (which caught and let a real
transcription slip get fixed before it shipped, rather than after). Also re-checked the pinned
model prices against the live pricing page: everything matched except Claude Sonnet 5's active
introductory rate, which the operator chose not to adopt (kept the post-intro steady-state price
instead, recorded in a comment so a future session does not read it as a missed update). One
commit, pushed (`dcac852`). "Incremental collect" (the third flagged ccstats item, a real feature
rather than a cleanup) was left alone, as scoped from the start.

Four commits this half of the session, all pushed: `d9a2227`, `4824098`, `e067c8c`, `dcac852`.
Full suite re-confirmed green after every change (1,124 main-repo tests, 99 ccstats tests, ruff
clean, pyright 0 errors on `src`/`tests`).

**What was NOT done:** nothing from items 1-7, ticket 28.22, or ticket 30's flagged defect remains
open as of this ninth handoff. Standing candidates for a future session: ticket 24.7 (session-start
capture freshness - partly closed already from outside this repo), the remaining items in ticket
28's backlog register, and ccstats' "incremental collect" (item 7's one leftover, a real feature,
not a cleanup - re-reads all ~25k transcripts every run, roughly 25 seconds).


---

### Eighth handoff, 2026-08-23

**Later the same day (eighth handoff).** Given the choice between ticket 30's equal-size defect
(item 4) and ticket 28.22 (item 5) and told to do both, picking which one to start with. Started
with 28.22 (the recommendation, since it was quick and closed a real risk): read `ccw-watch`'s
actual source in `fifty-shades-of-dotfiles` rather than trust this repo's own prior description of
what it depends on, found that description was imprecise (ccw-watch never matches on the word
"hook"), and wrote `tests/test_doctor_external_contract.py` pinning the real, narrower contract by
running ccw-watch's own sed/grep commands against real `ccw doctor` output - verified red-then-green
by mutating the wording it depends on and watching the test catch it. Then ticket 30's equal-size
defect: `write_session_folder` now compares actual bytes (not just size) when an offered payload
matches the archived one's length, taking the same conservative "refuse and record" branch as a
smaller payload when they differ. Verified the SAME way - a real `git stash` of just the production
fix showed every new/changed test fail against the pre-fix code, the end-to-end one with the exact
real-world "JSONL does not match manifest source_hash" symptom, before all passed once restored.

One incidental fix along the way: a doc edit for 28.22 named `fifty-shades-of-dotfiles`'s own
tracked copy of the script by its internal path, which uses that repo's OWN home-dir-mirroring
folder convention, not a real username - but the packaging gate's privacy-scan heuristic (`test_
packaging.py`) reads any slash-separated "home" segment followed by a word as a real user's home
directory, so it went red. Reworded the doc rather than touched the locked scan test.

Four commits, all pushed: `a197853` (PANEL-CONTRACT.md), `f60bc24` (ticket 27.8's decision record),
`32a31a3` (ticket 28.22's fence test), `f7f598c` + `962680a` (the packaging-gate reword and ticket
30's fix, split because the test file landed a commit early by an unintentional `git add` carry-over
- harmless, but worth knowing the history looks that way if anyone reads it later). Full suite
re-confirmed green after every change (1,122 tests, ruff clean, pyright 0 errors).

**What was NOT done:** nothing from items 1-5 remains open as of this eighth handoff. Ticket 28.13
(re-derive the architecture board) and ccstats polish (item 7) are the standing next candidates;
neither started this session.


---

### Seventh handoff, 2026-08-23

**2026-08-23 session (the one that produced this seventh handoff).** Opened by reading this file
(the sixth handoff, above) and asking the operator, in plain language, what to do about the two
threads it left open: the item-3 decision (ticket 27.8) and the item-2 loose end (the panel-contract
doc). The operator first asked for a plain-language explanation of what `keep_objects`/`store.py`
(the vault) vs `archive_root` (the archive folder) actually do before deciding anything on 27.8 -
answered by a sub-agent verifying the real mechanism from source (`config.py:162`,
`capture.py:189-261`, and the 7 specific tests named in the 2026-08-22 ticket-27.8 entry), not from
memory or this file's own prior summary. Given that explanation, the operator chose to KEEP BOTH
(the vault stays as a safety net) - see the correction inside item 3 above. That decision is now
recorded in `CLAUDE.md`, `harness/tickets/27-collapse-to-one-folder.md`, and `contract/DESIGN.md`
section 15; **item 3 has no remaining work and should not be re-opened without a new, explicit
reason.**

Separately, the operator said "write it now" for the panel-contract doc. Read
`dashboard_template.html` and `dashboard.py` directly to write `tools/ccstats/PANEL-CONTRACT.md` -
the data model, every chart/format helper, the house rules from `CHART-BRIEF.md`, and one fully
annotated example panel (Daily) - plus a one-line pointer from `tools/ccstats/README.md`. See the
correction inside the "One loose end" section above; that loose end is CLOSED.

One stale line noticed but NOT fixed, flagged instead: `tools/ccstats/README.md`'s "Scope, stated
rather than hidden" paragraph still says "Top sessions shows the top 50... not 200," but this file's
own item-2 "Fourth round" notes say that panel is 25, not 50, as of 2026-08-22. Out of scope for
this session's actual task; worth a one-line fix next time that file is touched.

**What was NOT done, as of the seventh handoff:** nothing from items 1-3 remains open. The next
real work is whatever the operator picks from "Also on record, not scheduled" below or
`CLAUDE.md`'s OPEN/next section - ticket 30's equal-size payload defect, ticket 28.22, ticket
28.13, or ccstats polish (item 7) are the standing candidates, none started this session.

