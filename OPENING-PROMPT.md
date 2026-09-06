# Opening prompt for a fresh session

Read this whole file - it is short on purpose (restructured 2026-08-27, see "About this
file" at the bottom). It tells you what to do next and where to look for everything else.

## Next task

**ACTIVE: ticket 38, archive the `tool-results/` and `workflows/` sidecars and add an
unknown-sibling signal. The plan is complete, red-teamed and approved (2026-09-06):
read `harness/tickets/38-sidecars-tool-results-and-unknown-siblings.md` first (the same
text also sits in the gitignored `Plans/can-i-get-you-compiled-pumpkin.md`), then start
at its section 9 (housekeeping is already done by the planning session: this pointer and handoff 23) and
build slices 38a-38f in order, oracle tests first.** The short version: Claude Code has
written `<uuid>/tool-results/` beside every big-output session since 2026-05-08 (1,067
dirs, 135.7 MB, 65.4 MB of it in no JSONL) and nothing in `src/` ever looked at it; the
plan adds a generic sidecar copier, a `sidecars.py` known-names list with a fence, a
`sidecars.json` notice + log line + desktop/voice alert for any future unknown sibling,
an informational `sidecars` doctor line, and version 0.1.3. Three rulings are already
taken by the operator and recorded in the plan (copy stranded dirs under
`_not-sessions/`, informational doctor line plus OS alert, all three sidecars in scope);
ruling (c) still needs its DESIGN 15 entry. The ticket file exists and holds the plan;
slice 38f appends its DONE block.

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
- **Cross-project ccw-provisioning design with `fifty-shades-of-dotfiles`, one clause
  open.** `docs/agent-setup-contract.md` and `contract/PROPOSALS/doctor-json-config-
  fields.md` shipped 2026-09-06 (25th handoff). The other project flagged after the fact
  that the doc's "upgrade to latest PyPI on every run" line conflicts with a pin+floor+
  notify policy it says the operator ruled directly to it - not yet corrected here. Check
  whether this got resolved before assuming the doc is current.

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
