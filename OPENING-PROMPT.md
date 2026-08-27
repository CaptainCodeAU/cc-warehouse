# Opening prompt for a fresh session

Read this whole file - it is short on purpose (restructured 2026-08-27, see "About this
file" at the bottom). It tells you what to do next and where to look for everything else.

## Next task

**Nothing is currently active. Ask the operator which of the standing candidates below to
pick up, or whether something else has come up since.**

Ticket 28.9 (`render_html`'s memory cost) is FULLY DONE - both mechanisms fixed, both
tested per the operator's real-browser bar (not `pytest` alone). Full account:
`harness/tickets/28-backlog.md`'s 28.9 entry. `render.py`'s copy-payload machinery now
runs through a per-page block cache (`_BlockCache`) - `_render_block` is a thin
cache-check wrapper, `_render_block_uncached` holds the real logic.

**A second thing is also on the table, raised 2026-08-27 but explicitly NOT started -
the operator wants it PLANNED in a fresh session before any code is written:** a
companion 3D/WebGL page for the ccstats corpus, alongside the existing 2D
`claude-code-dashboard-live.html`. Inspiration was a different project's 3D artifact
("Estate Orbit") - the operator liked its visual/interaction quality (drag-rotate/pan/
zoom, click-to-spotlight, a live filter panel), explicitly NOT its node/link data model
(planets/hubs/moons was one example, not a spec). Wants this designed ground-up for what
ccstats data actually is, with outside-the-box thinking welcome. Before planning, read
`tools/ccstats/README.md`, `tools/ccstats/PANEL-CONTRACT.md`, and
`tools/ccstats/dashboard_template.html` for what already exists; keep this project's own
house rules (self-contained HTML, no CDN, never commit/upload the output, put every real
fork to the operator as a table + a direct question).

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

## About this file

Restructured 2026-08-27: this file had grown to 1,930 lines, of which about 94% was
closed-ticket writeups and past-session narrative - useful archaeology, but not
something a fresh session needs to read to know what to do next. Everything below this
point used to be here directly; it moved to the files listed above, verified line-for-line
against the original before anything was deleted here. Nothing was lost - if you're
looking for something this file used to say and can't find it above, check
`harness/HANDOFFS.md` first (the session log is the largest single piece that moved).
