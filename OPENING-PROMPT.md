# Opening prompt for a fresh session

Read this whole file - it is short on purpose (restructured 2026-08-27, see "About this
file" at the bottom). It tells you what to do next and where to look for everything else.

## Next task

**PRIORITY ORDER, set 2026-09-09, supersedes "nothing is queued" below until
someone changes it.** Everything found during the 2026-09-09 capture-alert
incident (tickets 41/42) now sits at the top of the queue, ahead of the
standing backlog, in this order - two of these items were found to overlap
with existing open tickets, so those are merged in rather than duplicated:

1. **Ticket 42 #1 - DONE, same day (2026-09-09).** Real desktop/voice
   notification now wired into `ccw-freshness-check.py`'s WARN/ALERT tiers
   (desktop from streak 2, voice from streak 5+); the tier-0 first miss stays
   quiet on purpose. **NOT LIVE YET** - the plugin cache still holds the old
   script; run `/plugin` and update `cc-capture@cc-warehouse` to pick it up
   (verify with `grep _desktop_alert` against the newest
   `~/.claude/plugins/cache/cc-warehouse/cc-capture/*/hooks/ccw-freshness-check.py`).
   **While confirming this, found ticket 37 Part B's mechanism happening
   chronically right now** (2 sessions today with a `started` hook line and
   no `ok`/`error`, no catalog row, both the day's two largest payloads) -
   full evidence appended to `harness/tickets/37-*.md`'s dated 2026-09-09
   section. Not fixed; needs an operator ruling on detaching the hook's
   synchronous copying (ticket 42's unranked design item).
2. **Ticket 42 #4** - fix or relabel `ccw status`'s "Recent errors" section.
   **Do this before revisiting ticket 31.4's stalled decision** (see
   ticket 31's own file, "2026-09-09 cross-reference" note): one of the two
   signals ticket 31.4 was watching for its lock-contention retry-loop
   decision can never fire, by construction, so that decision has been
   resting partly on a broken instrument, not a real "hasn't recurred."
3. **Revisit ticket 31.4's retry-loop decision** once #2 lands and has run
   for a while - the monitoring signal will finally be real.
4. **Ticket 42 #5** - build the capture.jsonl-vs-archive reconciliation
   check (the single highest-value fix for real, permanent data loss - see
   ticket 41 Finding 5). **This also closes ticket 28.10's long-standing
   "cross-tree reconciliation as a test, not a hand-check" gap** (see
   ticket 28's own file, "2026-09-09 cross-reference" note) - design it once
   for both, don't build it twice.
5. **Rest of ticket 42's ranked list** (#2, #3, #6, #7, plus the two
   unranked design-tradeoff items) - see
   `harness/tickets/42-capture-logging-and-alerting-gaps.md`.
6. **Ticket 41 Finding 1** - stop a live SessionStart hook from silently
   running this repo's dev checkout instead of the installed `ccw` (small,
   standalone, can be done any time in this sequence).
7. **The standing backlog below, unchanged** - ticket 28's remaining items,
   version cuts, ticket 19 leftovers, etc.

Full incident account and every finding's evidence:
`harness/tickets/41-capture-alert-incident-2026-09-09.md` +
`harness/tickets/41-addendum-rca-evidence-2026-09-09.md`. Full fix list:
`harness/tickets/42-capture-logging-and-alerting-gaps.md`.

---

**TICKET 39 IS SHIPPED, LIVE, AND CLOSED, 2026-09-08.** All of 39a-39g landed,
including the operator-gated reinstall and back-fill. `ccw` on this machine is the
frozen `0.1.4` (confirmed both by `ccw doctor`'s `install` line and PEP 610's
`direct_url.json`), a real `ccw sweep` ran against the real archive
(`31031 items, 16 stored, 3344 with sidecars, 0 failed`) and triggered a clean
full-corpus re-render, and `ccw archive --to ~/cc-warehouse-archive --verify`
reports `29593 folders checked, 0 problems`. Real post-run numbers:
`Prompts: 1489/28940 session(s) have prompts.jsonl, 649 reference paste-cache
files`. Full account: `harness/tickets/39-archive-what-a-session-points-at.md`'s
"TICKET 39 IS SHIPPED AND LIVE" block at the very bottom.

**`v0.1.4` is also released to PyPI**, tagged and pushed via `/wrap-up`'s own
release step: gates + publish both green
(`https://github.com/CaptainCodeAU/cc-warehouse/actions/runs/34198334692`), and
the published wheel/sdist sha256 hashes match a local `uv build` exactly -
verified from the outside, not just a green CI run.

**CORRECTED 2026-09-09: no longer nothing queued** - see the priority order at
the very top of this file. Ticket 39 itself closed that track; what follows is
kept for its historical detail on how 39 was built, not as the active pointer.

For historical detail on how 39 was built, 39f added the config switch
`archive_history_prompts` (one early-return added to `sweep._process_history`'s and
`_plan_history`'s existing early-return chain, gating the whole combined
snapshot+split+gather pass together) and one new corpus-wide, non-blocking check -
`status.paste_gap`/`paste_line` - wired into `ccw status` and a new `ccw doctor`
"prompts" line. 39b-39e built the gather machinery itself (`external.py`'s
file-history/todos mirror, `history.jsonl`'s whole-file content-addressed snapshot,
the per-session `prompts.jsonl` split, and the paste-cache gather); see the ticket's
own `39b`/`39c`/`39d`/`39e DONE` blocks for that detail rather than duplicating it
here.
**CORRECTED: THE LIVE BACK-FILL HAS BEEN RUN, 2026-09-08, same day as the paragraph
above this one was originally written.** It read "still has not been run" for a
short window earlier the same day while the operator's go-ahead was pending; that
is no longer the state. See the "TICKET 39 IS SHIPPED AND LIVE" block for the real
numbers.
The short version: ticket 38 covered the sidecars INSIDE a session directory; 39 covers
the stores OUTSIDE it, which are siblings of `projects/` and so need catalog-driven
discovery rather than a scan beside the transcript. Measured 2026-09-07:
`~/.claude/file-history/` is 1,010 session-keyed entries / 911 MB whose bytes are in no
JSONL, `history.jsonl` is 18,295 rows that 100% carry a `sessionId`, and `paste-cache/`
is reachable only by joining through it, where 272 of 2,186 referenced hashes ARE ALREADY
GONE. Two operator rulings are recorded in the ticket (archive all of file-history;
`~/.claude/MEMORY/` becomes ticket 40, not 39).
**What 38 left you to build on**, all shipped 2026-09-08 in 0.1.3:
`store.write_if_absent` (refuse on any difference, never overwrite a copy),
`archive.copy_sidecar_dir` / `_mirror_tree` (recursive, ignores `.DS_Store` at any
depth), `archive.write_sidecar_notice` (a per-session anomaly record with NO timestamp,
deliberately), the non-blocking `ccw doctor` `sidecars` line, and `notify.alert`
(a detached desktop notification, fired only when a notice changes to non-empty).
Reuse them rather than writing twins.

**TICKET 38 IS DONE (2026-09-08), shipped as 0.1.3.** Slices 38a-38f landed in one
session, six commits `2a041f4`..`36940f0`, test count 1,269 -> 1,364. `tool-results/` and
`workflows/` are archived, unknown siblings announce themselves, and three sub-agent bugs
nobody was looking for got fixed on the way. **38g is NOT DONE** (a render marker for
`<persisted-output>` plus a `persisted` manifest key) and needs its own ruling, because it
moves default output and therefore re-baselines the golden matrix anchor. Full account:
that ticket file's DONE block.

**Ticket 37 Part B row 1 IS LIVE** (the check handoff 22 asked for): the newest plugin
cache copy `~/.claude/plugins/cache/cc-warehouse/cc-capture/2f374c2eddf9/hooks/ccw-hook.py`
contains `_started`, and `~/.claude/logs/ccw-hook.log` shows `started` lines (verified
2026-09-06). Ticket 37 Part B rows 2, 3, 5 and the sub-agent pre-filter follow-up stay
open in `harness/tickets/37-*.md`.

Ticket 28.9 (`render_html`'s memory cost) is FULLY DONE - both mechanisms fixed, both
tested per the operator's real-browser bar (not `pytest` alone). Full account:
`harness/tickets/28-backlog.md`'s 28.9 entry. `render.py`'s copy-payload machinery now
runs through a per-page block cache (`_BlockCache`) - `_render_block` is a thin
cache-check wrapper, `_render_block_uncached` holds the real logic.

**The 3D/WebGL ccstats companion page (raised 2026-08-27) is DONE, 2026-08-28.**
`tools/ccstats/daywall.py` + `daywall_template.html` build `claude-code-daywall.html`: one
box per session on a hand-rolled WebGL2 canvas (no library, matching the 2D page's own
rule), positioned by calendar day and hour, stacked into concurrency lanes, with gold
thread-beads for the 2,008 real sub-agent-to-parent edges. `/daywall` builds and serves it
(mirrors `/dashboard`, shares its `dashboard-defaults.json`). Verified against the real
corpus (8,682 sessions) in a real Chrome tab - rotate/pan/zoom, click-to-spotlight, every
filter, zero console errors - and against a headless Node probe (9 tests) for the page's
pure-data half. Full account: `harness/HANDOFFS.md`'s twentieth handoff, and
`tools/ccstats/README.md`'s "The 3D companion page" section.

**Standing backlog candidates, none picked yet** (ticket 28's other open items):
secret redaction on personal projections (28.2), test gaps (28.10), markdown/HTML for
sub-agents (28.11), re-homing an orphaned sub-agent when its parent arrives (28.12),
`prefers-color-scheme` for shared pages (28.14), and `ccw share --open` as a possible
fast follow-up to `ccw render --open` (28.1, already done). Full entries:
`harness/tickets/28-backlog.md`.

**Also still open, not scheduled:**
- **Ticket 41 (new, 2026-09-09): capture-alert incident + root-cause pass, NOT
  started.** A 56-uncaptured alert traced to a mostly-pre-existing backlog (not ~50
  sessions failing at once), root-caused to Claude Code never invoking the SessionEnd
  hook for 12 of 14 sessions that ended that day (outside this repo's own code/logs).
  Confirmed real gaps worth fixing: a live SessionStart hook can silently run this
  repo's dev checkout instead of the installed `ccw`; `ccw sweep` has no durable log
  record on a successful run; and a source-file-vanishes-before-capture blind spot
  that no `ccw doctor` check can ever detect. **CRITICAL, still genuinely open: 3
  specific sessions (5604f5fd/bf09caea/313b7e02) have NO trace anywhere on this
  machine - not source, not archive - and whether they held real content is
  unresolved.** Full raw evidence, plus external research on Claude Code's own documented
  hook-reliability limitations, in the companion addendum file. See
  `harness/tickets/41-capture-alert-incident-2026-09-09.md` and
  `harness/tickets/41-addendum-rca-evidence-2026-09-09.md`.
- **Ticket 42 (new, 2026-09-09): 7 ranked, scoped fixes for the logging/
  alerting gaps ticket 41 found, NOT started.** Two new structural findings
  beyond 41: `ccw-hook.log`'s "ok" status is unreliable for ANY graceful
  failure (not just the 3 sessions in 41), and `ccw status`'s "Recent
  errors" can never show anything (the code path that would log an error
  row is never called). Core gap: the ALERT tier that fired during the
  incident never actually notifies (voice/desktop) - it only prints to
  stdout, pull-based not push-based, which is why a peer session had to
  relay it manually. Cheapest, highest-value fix (#1, ~10 lines) is wiring
  real notification into that tier. See
  `harness/tickets/42-capture-logging-and-alerting-gaps.md`.
- **Ticket 31's lock-contention mechanism is still UNPROVEN.** Debug logging shipped;
  the retry loop was deliberately not written until the real exception is observed. Do
  not design a fix for an unconfirmed cause. See `harness/tickets/31-sweep-full-corpus-cost.md`.
- **Version cuts not started:** v1.1 proper (FTS5 + `ccw search` + HTML archive search +
  `ccw import`/inbox), v1.2 (`ccw mcp`), ticket 19 leftovers (`share` 19g, and
  `status`/`relocate`/`project` on archive labels), DESIGN 15 item 7 (registry
  backup/export story).
- **Unresolved and worth a future session's attention**: something overwrote the real
  `~/.cc-warehouse/stats/dashboard-defaults.json` with a generic exclude list sometime
  before 2026-08-24T01:25 - no session's own account claims to have done it, and the
  mechanism is unknown. It was restored once (16th handoff, see `harness/HANDOFFS.md`);
  if it happens again, that's the lead to chase.
- **Cross-project ccw-provisioning design with `fifty-shades-of-dotfiles`: DONE, both
  sides consistent.** `docs/agent-setup-contract.md` and `contract/PROPOSALS/doctor-json-
  config-fields.md` shipped 2026-09-06 (25th handoff). Its version-upgrade wording was
  briefly wrong (said "latest PyPI on every run"); operator confirmed the real policy is
  pin + floor + notify and the doc was corrected the same day. Nothing open here.

## Hard rules

This repo's `CLAUDE.md` (repo root) is the actual contract - read it, it is not
duplicated here. In particular: **`cc-capture@cc-warehouse` in `plugins/cc-capture/`
(this repo) is the only live capture plugin** - verify against `enabledPlugins` before
touching any hook file, never against a repo's docs. `ccw` is installed as a FROZEN
snapshot - after any change you want the hook to pick up, run
`uv_tool_reinstall_current_project --no-extras` from the repo root.

## Where else to look

This file used to hold everything below in one 1,930-line block. It is now split by
what kind of information it is:

- **`harness/HANDOFFS.md`** - the full session-by-session history, newest first. Read
  the top few entries for recent context; the rest is archaeology.
- **`harness/GOTCHAS.md`** - recurring environment gotchas (the `file://`-browser
  refusal, the SSH key dropping out, `ccw doctor` reporting `editable` from inside this
  repo, and others). Task-independent - check it whenever something environmental looks
  wrong, not just when starting new work.
- **`harness/tickets/<nn>-*.md`** - one file per ticket, each carrying its own dated
  DONE/CLOSED account. `28-backlog.md` is the backlog register referenced above.
- **`tools/ccstats/HISTORY.md`** - the closed build history for the stats dashboard
  tooling (`tools/` sits outside the ticket system). `tools/ccstats/README.md` and
  `tools/ccstats/PANEL-CONTRACT.md` describe what it does today.
- **`contract/DESIGN.md` section 15** - decisions and the reasoning behind them,
  append-only. **`contract/HARNESS.md` section 8** - per-slice process lessons and
  retros, append-only (stale since 2026-08-20 - the handoff log above took over its
  job informally; worth the operator's call on whether it resumes or stays superseded).
- **`cc-warehouse-architecture/SOURCE.md`** - the architecture review board, owned by
  `/architecture`.

## Keep it this way

**When this session ends, do not write a new narrative paragraph into this file.** That
habit is exactly how this file grew to 1,930 lines before 2026-08-27. Instead:
- If today's work is worth a dated record, add a new entry to the TOP of
  `harness/HANDOFFS.md` (newest-first).
- If a genuinely new, task-independent environment gotcha showed up, add it to
  `harness/GOTCHAS.md`.
- Only touch THIS file's "Next task" / backlog sections above if the live status
  actually changed - what's active now, what's still open, what's newly closed. Keep it
  short; a one-line pointer to the ticket file or handoff entry beats a paragraph here.

## About this file

Restructured 2026-08-27: this file had grown to 1,930 lines, of which about 94% was
closed-ticket writeups and past-session narrative - useful archaeology, but not
something a fresh session needs to read to know what to do next. Everything below this
point used to be here directly; it moved to the files listed above, verified line-for-line
against the original before anything was deleted here. Nothing was lost - if you're
looking for something this file used to say and can't find it above, check
`harness/HANDOFFS.md` first (the session log is the largest single piece that moved).
