# Ticket 41 addendum: raw RCA evidence, 2026-09-09

Companion to `harness/tickets/41-capture-alert-incident-2026-09-09.md`. That
file has the synthesized findings and proposed fixes; THIS file has the raw
evidence behind them, so a future session can verify a claim or extend the
investigation without re-running the same fact-finding. Produced via the
RootCauseAnalysis skill (forked execution) dispatching three parallel
read-only forensic agents - `q1-source-faulttree`, `q1-log-timeline`,
`q1-system-schedule` - plus direct follow-up checks by the lead session.
Nothing was modified; no `ccw` write command was run.

All times UTC unless marked local (Melbourne, UTC+10 in September). Incident
window: 2026-09-09T00:00:00Z - 02:28:09Z.

---

## Agent 1 - q1-source-faulttree (code-level fault tree)

Ranked candidate mechanisms, from the actual source, with file:line
citations:

1. **Wrapper can be SIGKILLed with zero completion log (top-ranked).**
   `ccw-hook.py` writes a `started` line (lines 155-178), then `main()`
   spawns `ccw hook` as a subprocess with `timeout=40` (lines 203-215).
   `hooks.json` caps the whole wrapper at 45s. A `subprocess.TimeoutExpired`
   at 40s IS caught and logged as `error` (lines 213-215) - not silent. But
   if total wall time (spawn overhead + subprocess + `report()`'s file I/O)
   exceeds the outer 45s, Claude Code SIGKILLs the whole `python3` process -
   uncatchable, no `except` runs, nothing after `started` is ever logged.
   `ccw-hook.py`'s own docstring (lines 159-163) documents this exact
   failure already happened for real once, 2026-09-06: "a hook wrote the raw
   JSONL... then was killed before the catalog row... every log said 'no
   such capture' while the disk said 'captured'."
2. **0.1.4 (installed 2026-09-08 16:32 local, ~17.5h before the incident)
   added new synchronous I/O inside the hook's timed critical path.**
   `direct_url.json` + tool-dir mtime confirm the reinstall time. Tickets 38
   and 39b (same day) added `_archive_sidecars_of` (capture.py:440-488) and
   `_archive_external_of` (capture.py:491-547, file-history/todos, ~929MB /
   1,056 dirs measured elsewhere) - both called synchronously inside
   `_capture_locked` (capture.py:234-251), i.e. inside the 40s hook budget,
   before the catalog row is written. This is new work vs. the prior week.
   Render itself is NOT on this path (detached child, cli.py:448-456) - that
   part is exonerated.
3. **Catalog contention has no hard ceiling, just three stacked waits.**
   `busy_timeout=5000` (catalog.py:141) x `CATALOG_RETRY_ATTEMPTS=3`
   (capture.py:42) = up to ~15s of legitimate blocking under contention. The
   code cites a real precedent of 58 sessions ending in a 2.6h stretch
   (2026-08-03, ccw-hook.py:198). Combined with #2's added I/O, a plausible
   compounding factor - not proven from code alone.
4. **Per-hash lock (capture.py:116-127, `_LOCK_WAIT_S=30`) only serializes
   re-fires of the SAME session** - unlikely driver of a multi-session
   incident. Not evidenced as a cause here.
5. **Scheduled-job lock overlap** (`doctor._batch_render_in_progress`,
   doctor.py:435-442) - structurally possible if a prior manual sweep held
   the lock late into the night, but no evidence either way was found from
   source alone.

Agent's own weighting: #1 and #2 ranked highest (a proven recurring failure
class in this exact file, compounded by a same-day-prior deploy that
shrunk the safety margin); #3 as a plausible compounding factor; #4/#5
structurally possible but unevidenced.

---

## Agent 2 - q1-system-schedule (system/schedule correlation)

All directly observed, nothing inferred:

- **Scheduled jobs** (plist + `launchctl print`): `ccw-sweep` daily 12:30
  local, `ccw-repair` daily 12:45 local (15min after sweep by design, avoid
  lock contention), `ccw-archive` weekly Sun 03:00 local. All three:
  `state=not running`, `last exit code=0`. `runs=9`/`9`/`1` are LIFETIME
  counts, not "ran today" - `launchctl print` has no per-run timestamp.
- **Log files**: `ccw-sweep.log` and `ccw-repair.log` both 0 bytes (mtimes 4
  Aug, 23 Aug - stale; `--quiet` suppresses stdout on success).
  `ccw-archive.log` is 122KB, last written Sep 6 03:03 local, matching its
  weekly schedule exactly - no crash signature there.
- **The real evidence is `capture.jsonl`, not the log files.** `ccw-repair`
  fired at its NORMAL scheduled time: 23 `"repair: fixed"` entries starting
  2026-09-09T02:45:30Z (=12:45:30 local), 17 minutes AFTER the incident
  window closed (02:28:09Z) - i.e. it ran on schedule, not as an early or
  wake-triggered catch-up. Inside the incident window itself, `capture.jsonl`
  has only 4 entries total: 1 success (01:10Z) and 3 `"unreadable transcript
  ... No such file or directory"` errors (01:56Z, 02:15Z, 02:17Z) - flagged
  for the code/log agents, became Finding 5 below.
- **Sleep/wake/reboot**: `last reboot` shows only Aug 31 / Aug 14 / Aug 8 -
  none on 2026-09-09. `pmset -g log` has no sleep/wake state-change lines in
  its retained history at all (verified via a field-3 category tally as a
  control - only "Assertions" category lines exist). Amphetamine (PID 1376)
  held a continuous sleep-preventing assertion for 51+ hours as of the check
  - the machine was very likely awake continuously through and before the
  window. No sleep/wake/reboot contribution.
- **Parallel-agent fan-out hypothesis: tested directly, NOT supported.**
  Python scan of all 25,074 transcripts under `~/.claude/projects/*/*.jsonl`,
  hourly UTC histogram of session-start timestamps: 09-08T20:00=1,
  09-09T00:00=4, 01:00=3, 02:00=11, 03:00=2. Only 11 sessions started inside
  the incident window itself, across 4 projects (fifty-shades-of-dotfiles=5,
  cleaner-temp=3, go-research=2, Network-Plan=1), no tight cluster - ordinary
  single-user churn, not an automated/orchestrated burst.

Agent's own conclusion: nothing on the scheduling/sleep/reboot/volume side
explains the gap; the cause is in the hook/lock logic itself, matching
Agent 1's direction, not a system-level trigger.

---

## Agent 3 - q1-log-timeline (log timeline reconstruction) - the decisive report

Walked every top-level (non-subagent) transcript under
`~/.claude/projects/**/*.jsonl` (25,074 files). 14 have their last real
message timestamp inside the incident window - i.e. 14 sessions genuinely
ended/went quiet during it. Cross-checked all 14 UUIDs against the ENTIRE
`ccw-hook.log` history (1,212 lines, back to Aug 4), not just the window.

**Order-of-magnitude correction: the 56-uncaptured figure was NOT "50
sessions ended in this window."** Only 14 real session-ends happened in the
2.5h window; the first freshness-check reading at 00:02Z already showed 39
uncaptured - i.e. most of the "56" was a pre-existing, cumulative backlog
from before the window started, not sessions failing within it.

Of the 14:

- **12 have ZERO entries anywhere in `ccw-hook.log`, ever** - not "fired
  outside the window," never invoked at all. Spans 4 different project
  directories, ruling out one project's local hook config as the cause -
  system-wide. UUIDs (uuid@last-message-time(project)):
  `3fd2772f@00:02:20(go-research)`, `c9eeafed@00:15:11(fifty-shades)`,
  `dff7440a@00:17:46(fifty-shades)`, `b27898d8@00:26:28(cleaner-temp)`,
  `9e626da1@01:13:07(go-research)`, `7dde9ee2@01:15:47(fifty-shades)`,
  `4ce9a9c0@01:30:41(Network-Plan)`, `1f0d24c4@02:12:28(cleaner-temp)`,
  `cd61754c@02:21:26(cleaner-temp)`, `1d2eeaa3@02:22:47(fifty-shades)`,
  `895d55a9@02:25:25(fifty-shades)`, `3a51f54e@02:25:39(fifty-shades)`.
  All 12 are confirmed captured now (checked separately by the lead
  session against the current archive - e.g. `1d2eeaa3` and `3a51f54e` both
  appear in the 02:45:09Z repair-batch folder listing already recorded in
  ticket 41's main file), i.e. `ccw sweep`'s independent source-tree scan
  recovered them even though the live hook never fired - sweep does not
  depend on the hook having run.
- **1 session (`0f4e889c-066a-4e78-8a2b-5bb684539b59`, go-research) got a
  `started` entry at 00:01:34Z with no later `ok`/`error` anywhere and no
  `capture.jsonl` entry** - matches Agent 1's SIGKILL-between-started-and-
  finish signature (not the 40s subprocess timeout, which IS caught).
- **1 session (`838a0b24-9600-42fa-9275-2ea0c669c01b`, go-research) captured
  completely normally** at 01:09:59-01:10:00Z (`ccw-hook.log`) matched by a
  `capture.jsonl` `"ok"`/`"captured"` entry at 01:10:00.724699Z, short id
  `62fe1cc52c77`, ~700ms later - proves capture wasn't universally broken
  during the window.
- **Clustering check (was this a collision/race?): NOT a mass simultaneous
  failure.** Only 5 `started` entries total in the whole window, gaps of
  4105s/2800s/1140s/120s - no two within 10s of each other. Real
  session-END clusters DO exist in the transcript data (00:01:33 & 00:02:20,
  47s apart; 02:22:47/02:25:25/02:25:39, three within ~3min, two 14s apart)
  but NONE of those clustered sessions produced any `ccw-hook.log` entry at
  all - reinforcing "hook not invoked" over "hooks raced and collided."

### Finding 5 (surfaced here, elevated to a numbered Finding in the main
ticket): the "false success" trio

3 sessions show `started`->`ok` in `ccw-hook.log` (subprocess exited 0) but
`capture.jsonl` logged a SIMULTANEOUS `error`: `"unreadable transcript ...
No such file or directory"` for the exact same path, at the exact same
second:

```
ccw-hook.log:
{"ts":"2026-09-09T01:56:39+00:00","session":"5604f5fd-8fab-40bf-8ca9-69e5b1a93c47","status":"started","detail":".../Network-Plan/5604f5fd-....jsonl"}
{"ts":"2026-09-09T01:56:39+00:00","session":"5604f5fd-8fab-40bf-8ca9-69e5b1a93c47","status":"ok","detail":""}
{"ts":"2026-09-09T02:15:39+00:00","session":"bf09caea-0fb3-4305-a0a7-0ad06137e541","status":"started","detail":".../fifty-shades-of-dotfiles/bf09caea-....jsonl"}
{"ts":"2026-09-09T02:15:39+00:00","session":"bf09caea-0fb3-4305-a0a7-0ad06137e541","status":"ok","detail":""}
{"ts":"2026-09-09T02:17:39+00:00","session":"313b7e02-3fff-4ae4-8122-44c013a0fe70","status":"started","detail":".../fifty-shades-of-dotfiles/313b7e02-....jsonl"}
{"ts":"2026-09-09T02:17:39+00:00","session":"313b7e02-3fff-4ae4-8122-44c013a0fe70","status":"ok","detail":""}

capture.jsonl (same 3, matching timestamps):
{"at":"2026-09-09T01:56:39.171440+00:00","status":"error","session":null,"message":"unreadable transcript .../Network-Plan/5604f5fd-....jsonl: [Errno 2] No such file or directory: '...'"}
{"at":"2026-09-09T02:15:39.721136+00:00","status":"error", ... "unreadable transcript .../bf09caea-....jsonl: [Errno 2] No such file or directory..."}
{"at":"2026-09-09T02:17:39.734229+00:00","status":"error", ... "unreadable transcript .../313b7e02-....jsonl: [Errno 2] No such file or directory..."}
```

For all three, `started` and `ok` are logged in the SAME second - the whole
hook invocation, including the internal `ccw hook` subprocess, completed in
under one second, which is fast even by this pipeline's normal standards and
consistent with the transcript being gone (or never fully written) at the
moment the hook tried to read it, not a slow failure.

### Backlog clearance (corroborates the main ticket's earlier finding)

`capture.jsonl` shows 23 `"repair: fixed"` entries at 02:45:08-02:45:37Z,
matching the main ticket's timeline exactly.

Agent's stated boundary: root cause of WHY Claude Code didn't invoke the
hook for the 12 (a Claude-Code-side dispatch question, not `ccw`'s own code)
is NOT determined by these logs - `ccw-hook.log` only records what happens
AFTER Claude Code invokes the wrapper. Open for further investigation if
needed, outside this repo's own code.

---

## Lead session's own follow-up (after the 3 agent reports), direct checks only

**1. Located the exact code path for the "false success" trio - and found it
is DESIGNED behavior, not an oversight, with one real gap in it:**

- `capture.capture_transcript` (capture.py:694-713): on `OSError` reading the
  transcript, returns a `CaptureResult(..., "error", ...)` rather than
  raising - documented in its own docstring as deliberate, "so a batch
  caller (sweep/migrate) can report the item and continue" (R5/R10).
- `cli._run_hook` (cli.py:549-582): documented `"always exit 0 (never-raise,
  F7)"` - ANY failure, including this one, is logged via `notify.report`/
  `_report_capture` and then the function returns 0 regardless. This is also
  deliberate (F7: a hook must never crash Claude Code's own hook runner).
- **So the exit-0 behavior itself is correct, documented design - not the
  bug.** The real gap: nothing consumes the `error` records
  `capture.jsonl` correctly writes to trigger an automatic retry. A session
  that hits this path is only ever recovered if its source `.jsonl` still
  exists in `~/.claude/projects` the NEXT time `ccw sweep` scans the tree
  (sweep's set-diff only sees files currently present - `status.uncaptured_gap`,
  status.py:84-107, is explicit: "Reads only directory entries"). If the
  source file is gone by then, the session is invisible to EVERY existing
  `ccw doctor` check, forever - there is no code path anywhere in this
  project that would ever flag it again.

**2. Checked whether the 3 sessions' source files were renamed rather than
lost (ticket 38's documented `.orphaned-<n>-<hash>.jsonl` pattern) - NOT
FOUND.** `find ~/.claude/projects -iname '<uuid>*'` for all three UUIDs
returns nothing, at any depth searched, under any name. Control check (a
known real orphaned file elsewhere) confirms the search itself works.

**3. Checked the archive for all three UUIDs directly - NOT FOUND there
either.** No archive folder for any of the three exists.

**Conclusion of this follow-up: these 3 specific sessions currently have NO
trace anywhere on this machine - not in source, not archived, not renamed.**
This narrowly revises the main ticket's earlier "nothing was lost" verdict,
which was based on a source-vs-archive diff that structurally cannot see a
session whose source file is already gone from both sides. Best working
hypothesis, NOT confirmed: these were very short-lived, effectively-empty
sessions (start-to-`ok` in under 1 second) that Claude Code itself may never
have durably written - but this is inference, not verified fact, and is the
single most important open item carried into the main ticket.

---

## Part 2 - external research: is Claude Code hook unreliability a known, documented issue?

Added 2026-09-09, a second research pass at the operator's explicit request
("do serious fact-finding... increase blast radius") to answer two follow-up
questions Part 1 left open: why does Claude Code's own dispatch skip some
hooks, and what should this project change in response. Method: 9 parallel
web-research subagents (via the Research skill) plus a Claude-Code-settings
specialist agent, each independently verifying claims against primary
sources (official docs fetched and grepped directly, `gh issue view`/`gh
search` against `anthropics/claude-code`, `CHANGELOG.md`, the npm registry)
rather than trusting search-summary paraphrases. One agent explicitly caught
and discarded a fabricated docs quote a summarizing pass had produced -
noted here as a real instance of the verification discipline working, not a
hypothetical.

### What's officially documented (highest confidence - direct primary source)

- **No Claude Code documentation anywhere promises a SessionEnd hook will
  fire for every session.** Confirmed by direct grep of the raw fetched docs
  pages (`code.claude.com/docs/en/hooks`, `.../hooks-guide`) for
  guarantee/best-effort language - none found for SessionEnd specifically.
  The one "best-effort" phrase on those pages describes the Bash `if`
  command-matcher pattern, unrelated to firing reliability.
- **SessionEnd hooks share a 1.5-SECOND default execution budget, combined
  across all SessionEnd hooks on the machine** - dramatically shorter than
  every other hook type's default (600s for `command`/`http`/`mcp_tool`
  hooks elsewhere). Setting an explicit per-hook `timeout` raises this
  budget to match, capped at 60s. This is THE most concrete, documented
  mechanism behind "my SessionEnd hook silently didn't finish" reports
  generally.
- **Verified against our own config:** `plugins/cc-capture/hooks/hooks.json`
  sets `"timeout": 45` on our SessionEnd hook - so our effective budget
  should already be raised to 45s, not stuck at 1.5s, PROVIDED the version
  of Claude Code running honors that (see next point).
- **`CHANGELOG.md` (raw, direct download) confirms a real, repeated history
  of SessionEnd/SessionStart-specific reliability bugs being found and
  fixed**, most relevantly: v2.1.74 "Fixed SessionEnd hooks being killed
  after 1.5s on exit regardless of `hook.timeout` - now configurable via
  `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS`"; v2.1.69 "Fixed plugin
  Stop/SessionEnd/etc hooks not firing after any `/plugin` operation."
  **This machine runs Claude Code 2.1.266** (`claude --version`, checked
  directly) - well past both fix versions, so neither of those two specific
  historical bugs should be affecting us today. `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS`
  is not set in this environment (checked directly) - irrelevant here since
  we already set a per-hook `timeout` that should achieve the same effect.

### The plugin-vs-settings.json reliability gap - real, multiple independent confirmations, still open

At least three separate, unrelated GitHub issues (#33458, #34573, #51420 -
different hook events, different reporters, different client surfaces)
show the identical shape: a hook registered via a plugin's `hooks.json`
goes silently quiet while the SAME config registered directly in
`settings.json`/`settings.local.json` keeps working, in the same session.
The richest thread, **#16288 ("Plugin hooks not loaded from external
hooks.json file"), is still OPEN** as of this research, with a
community-reverse-engineered root cause: plugin hook loading is
fire-and-forget async at startup, and hook dispatch for events other than
`SessionStart` doesn't wait for it to finish - `SessionStart` itself is
explicitly excluded from the bug this way, `SessionEnd` is not confirmed
either way in that specific thread, but #33458 confirms SessionEnd
specifically has its own, separate plugin-scope bug (fixed at v2.1.69,
which we're past).

**Checked directly against this machine:** our `enabledPlugins` state is
clean - `cc-capture@cc-warehouse: true` in the global `~/.claude/settings.json`,
no conflicting `enabledPlugins` key in any of the 4 affected projects'
local settings files (would shadow/drop it per a separate documented bug,
#27247 - ruled out). No orphaned plugin cache entries for the currently
active `cc-capture` version (`68d5fa775651`) - only genuinely superseded old
versions carry `.orphaned_at` markers. So the specific, previously-fixed
plugin-scope bugs don't explain our incident; the general "plugin-scope is
structurally less reliable" risk from the still-open #16288 remains a live,
unresolved risk class regardless.

### Confirmed failure mechanisms relevant to our own hook's design

- **A SessionEnd hook doing real async work can be killed before completion
  regardless of configured timeout** (#41577, direct quote: "Claude Code
  exits almost immediately... even when a generous timeout is configured,
  tested up to 90s"). Matches this ticket's Finding 4 fault-tree hypothesis
  #1 (SIGKILL near the timeout boundary) almost exactly.
- **The single most consistently recommended mitigation, converged on
  independently by 3+ separate research angles and real GitHub issue
  threads**: detach heavy/slow work inside the hook with something like
  `nohup ... & disown; exit 0` so Claude Code's own process teardown can't
  kill it mid-task - at the documented cost of losing the ability to report
  an error back to Claude Code for that detached piece. Directly relevant
  to our own hook's synchronous sidecar/external-file copying
  (`capture.py:440-547`, already flagged in Finding 4's proposed fix as a
  candidate to move off the hook's timed critical path).
- Anthropic's own docs describe a SEPARATE, distinct silent-failure class,
  not previously considered here: a single schema-invalid hook entry
  anywhere in a settings file (e.g. `matcher` as an array on an old
  version) silently disables EVERY hook in that whole file, with no error
  surfaced anywhere including `claude doctor`. Not confirmed as a factor in
  this incident, but worth a periodic sanity check of our own hooks.json's
  schema validity.

### Explicitly did NOT hold up under verification (recorded so it's not re-investigated)

- A first-pass summarized fetch produced a plausible-sounding "quote" -
  *"Claude Code makes a best-effort attempt to run SessionEnd hooks before
  exiting, but they aren't guaranteed to fire. If you kill the process or
  your system loses power, the hooks won't run."* - that does NOT exist
  anywhere in the actual docs, confirmed by direct grep of the raw
  downloaded page. Caught and discarded by the researching agent itself.
  Treat any future citation of this exact sentence as a hallucination.
- No specific Claude Code version is documented anywhere as "the fix" for
  general hook reliability - version-specific fixes exist (see above) but
  they're narrow, not a single blanket resolution.
- No documented or reported hard limit on concurrent Claude Code sessions
  per machine was found; the "many sessions ending near each other
  overwhelms the hook" hypothesis (this ticket's Finding 4 fault-tree
  candidate #3) is neither confirmed nor contradicted by any public
  evidence - it remains an open, untested hypothesis specific to our own
  machine.

### Sources (all URLs verified reachable and read directly by the researching agents, not snippet-only)

Highest-value citations: official docs `code.claude.com/docs/en/hooks` and
`.../hooks-guide`; `CHANGELOG.md` raw file
(`raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md`);
GitHub issues #41577, #33458, #6428, #17885, #32712, #35892, #16288, #27247,
#20265, #16047, #77078 (Windows, open, unrelated platform but same failure
CLASS), #79508 (a case where an Anthropic collaborator directly disputed a
"SessionEnd doesn't fire" report and pointed at the 1.5s budget instead -
useful caution against taking every such report at face value). Full
per-agent reports with complete citation lists are preserved in this
session's own transcript; this section is the synthesized, cross-checked
subset judged load-bearing enough to act on.
