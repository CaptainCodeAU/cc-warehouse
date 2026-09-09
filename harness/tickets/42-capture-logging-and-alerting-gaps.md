# Ticket 42: close the logging and alerting gaps found in the 2026-09-09 capture incident

Opened 2026-09-09. **Item #1 DONE and LIVE the same day** (real desktop/voice
notification wired into `ccw-freshness-check.py`'s WARN/ALERT tiers, pushed
`a781555`, verified live end to end - see `harness/HANDOFFS.md`'s
thirty-seventh entry for the full account). Items #2-#7 and the two unranked
design-tradeoff items are still NOT started. Follow-up
to ticket 41 (`harness/tickets/41-capture-alert-incident-2026-09-09.md` and
its addendum), which found the incident's actual backlog was harmless but
surfaced structural gaps in how this project logs and alerts on capture
failures. The operator asked two direct questions after reading 41: "how do
we make sure everything gets logged" and "how do we get notified
immediately so we can act." This ticket is the scoped answer to both,
produced by a dedicated read-only logging/alerting audit agent. Full detail
and file:line citations for every item below are that agent's original
report, preserved in this session's transcript; this ticket is the
triaged, ranked version meant to be picked up and built from directly.

## Two structural findings, beyond anything ticket 41 already named

**A) `ccw-hook.log`'s "ok" status is unreliable, structurally, not just for
the 3 sessions in ticket 41 Finding 5.** `cli._run_hook` (cli.py:549-582)
always exits 0 and prints nothing, on every path except a literal crash or
subprocess timeout/OSError. `ccw-hook.py`'s wrapper only distinguishes
"ok" from "error" by that exit code. So `ccw-hook.log` says "ok" for EVERY
graceful in-process failure - an unreadable transcript, a lock timeout, any
exception `_run_hook`'s own except-block swallows - not just the specific 3
sessions already found. Finding 5 was the first known INSTANCE of this; the
blind spot itself is general.

**B) `catalog.record_event` is never called with `action="error"`
anywhere in this codebase** (checked: capture.py:224, capture.py:278,
sweep.py:162 - all three call sites, none pass "error"). Consequence:
`status.py::status_text`'s "Recent errors" section (`WHERE action =
'error'`, status.py:325-331) is permanently empty by construction,
regardless of what's actually failing. `ccw status` cannot show a real
capture error today, full stop.

## The core alerting gap - why this incident needed a peer session to notice

`ccw-freshness-check.py`'s WARN/ALERT escalation tiers - the actual
mechanism ticket 24.7 was built for, and the one that fired during this
incident - **never trigger a desktop notification or voice alert.**
`report()` (line ~166) only speaks/alerts on `status == "error"`; the
streak-escalation calls in `main()` use `"warn"`/`"alert"`, which fall
through to a plain `print(message)` - surfaced only as SessionStart hook
stdout, which only reaches a human if a NEW session happens to start and
someone reads it. That is exactly what happened here: a peer session's own
SessionStart hook printed it, and a human had to relay it manually. The
mechanism is pull-based, wearing the shape of a push-based alert.

## Ranked proposals

**1. DONE 2026-09-09.** HIGH value / LOW effort - wire real notification into the WARN/ALERT
tiers. Scope: `plugins/cc-capture/hooks/ccw-freshness-check.py::main()`,
the `report("warn"/"alert", message)` calls. This file deliberately doesn't
import `cc_warehouse`, so it needs its own ~10-line copy of the `osascript`
Popen technique `notify.alert` already uses elsewhere. Closes the single
biggest gap this incident exposed, cheaply, with no new reconciliation
logic required. **Do this first.**

**2. HIGH value / LOW-MEDIUM effort - `ccw sweep` per-run summary logging**
(ticket 41 Finding 2). Scope: `cli.py::_run_sweep`, mirroring
`_log_repair_outcome`'s "always write regardless of `--quiet`" pattern.
Extend the same treatment to standalone `ccw build` and `ccw archive` for
consistency - today only `ccw repair` reliably records "I ran and here's
what happened."

**3. HIGH value / MEDIUM effort - make `ccw sweep`'s per-item errors reach
`capture.jsonl`, not just stderr.** Scope: `sweep.py::_capture_item`
(~line 395-412). Today a sweep-discovered unreadable-transcript error is
invisible to `capture.jsonl`-based tooling entirely (including proposal #5
below), even though the identical error via the live hook IS logged there -
an inconsistency between the two capture paths for the same failure.

**4. DONE 2026-09-09.** MEDIUM value / LOW effort - fix or retire `ccw status`'s "Recent
errors" section (Finding B above). Either wire error results into
`catalog.record_event` (needs minor restructuring in
`capture.py::capture_transcript`/`_capture_locked`, since the
unreadable-transcript and lock-unavailable paths currently return before a
catalog connection even opens), or relabel/remove the section so it stops
implying a capability that doesn't exist.
**Shipped as a third option, found while scoping**: point `status._recent_errors`
at `logs/capture.jsonl` instead, which every real error source already writes to
(`notify.append_log`'s shared six-field schema) - reusing the same JSON-lines
parsing `doctor._companions_stalled` already does. Confirmed by re-reading
DESIGN section 7's own `ccw status` contract that this was the ORIGINAL spec
("reads catalog + log"); the catalog-only implementation was the drift. 6 new
oracle tests in `tests/test_status_verify.py`; full suite 1547 passed, ruff and
pyright strict clean. Committed `acf5975`, reinstalled live and verified against
the real warehouse the same day. Full account: `harness/HANDOFFS.md`'s fortieth
handoff.

**5. DONE 2026-09-09 (scope B+D).** HIGH value / MEDIUM-HIGH effort - build the Finding-5
reconciliation check. The single highest-value fix relative to the incident's worst
possible outcome (permanent, silent data loss) and the most novel piece of
logic proposed here - nothing today cross-checks `capture.jsonl`'s error
records against whether the affected session ever actually got archived.
Mechanism: parse `capture.jsonl` for `status: "error"` lines (bounded
window, e.g. 7-14 days); for each, check whether the source file OR an
archive folder now exists for that session - if NEITHER, the session is
permanently unrecoverable exactly like ticket 41's Finding 5, and this
should alert loudly (desktop + a distinct spoken sentence, not just another
log line nobody consumes). Prerequisite refinement: today the error
record's session identity is embedded in free prose inside `message`
("unreadable transcript /path/.../<uuid>.jsonl: ..."), not a structured
field - worth making that a first-class field on error-shaped
`capture.jsonl` records rather than parsing prose. Natural home: `doctor.py`
(new Check) or a new small `reconcile.py`. Natural cadence: daily, via the
existing `ccw repair` job (12:45 local, right after sweep has had its shot
at reclaiming the source file for that day).
**Shipped as scope "B+D"** (both offered, operator picked both): new
`src/cc_warehouse/reconcile.py` (`find_unrecoverable`, the expensive
source+archive+catalog cross-check; `known_unrecoverable_count`/
`_uuids`, the cheap dedup-ledger read `ccw doctor`'s new non-blocking
`reconcile` line uses so the SessionStart hot path never risks ticket 41
Finding 1's timeout again); the `session_uuid` structured field added at the
3 call sites that can supply a real identity (`cli._report_capture`/
`_run_hook`, `sweep._log_item_failure`), prose-regex fallback kept
permanently for older records; a new read-only `ccw reconcile` verb (option
D: prints the full unbounded history, not just the 14-day alert window);
`ccw repair` now runs reconciliation BEFORE its desync early-return (so it
still runs on the normal healthy-machine day) and announces new losses once
per run (desktop + voice), deduped via its own record written back into
capture.jsonl. **Measured live before building, and confirmed again after**:
the real figure is 21 permanently unrecoverable sessions, not 3 - including
the exact 3 (5604f5fd/bf09caea/313b7e02) ticket 41 already flagged as an
unresolved critical unknown. 22 new oracle tests; full suite 1574 passed,
ruff and pyright strict clean, project-wide. Committed `2d58f73`, reinstalled
live, `ccw reconcile` run for real and found the same 21 by UUID. **`ccw
repair`'s live run (which would write the dedup ledger for real and fire a
real desktop+voice alert) was deliberately NOT triggered manually this
session** - left for the operator's word, or for the existing 12:45 daily
job to pick up naturally. Full account: `harness/HANDOFFS.md`'s forty-first
handoff.

**6. MEDIUM value / MEDIUM effort - build a hook-dispatch-gap detector**
(ticket 41 Finding 4's mechanism, made concrete). Sketch: parse
`ccw-hook.log` for session UUIDs with at least one `"started"` entry
(bounded window, same posture as `_DESYNC_SAMPLE`); walk
`~/.claude/projects/**/*.jsonl` (reuse `sweep.source_transcripts`) for
sessions whose last activity (`_last_activity`, already exists) is older
than a short grace period (10-15 min, well short of `_overdue`'s 24h); flag
any not in the "started" set. This answers "did Claude Code even try to
tell us," a genuinely different question from `status.uncaptured_gap`
("is it captured"). Root cause of WHY is outside this repo (Claude Code's
own dispatch, per ticket 41's addendum) - make this non-blocking like
`sidecars`/`history`/`prompts`, visibility only. Lower priority than #5:
sweep already nets the DATA for this specific mechanism (ticket 41 confirms
nothing was lost from it alone), so this is about faster observability, not
recovering something currently at risk - though a second bug landing
unnoticed on top of a dispatch gap is exactly how incidents compound.

**7. LOW value / LOW effort, hygiene - stop `ccw-hook.log` lying about
success** (Finding A above). Have `_run_hook` print its actual outcome to
stdout, and have `ccw-hook.py`'s wrapper report that instead of a
hardcoded "ok" on exit-0. No new alerting; stops the first file anyone
greps during an incident (this investigation included) from systematically
misreporting graceful-failure cases as success.

## Also worth weighing, not ranked as a numbered fix (design tradeoff, needs a decision first)

- **Moving the hook's synchronous sidecar/external-file copying**
  (`_archive_sidecars_of`/`_archive_external_of`, capture.py:440-547) **off
  the SessionEnd timing budget**, per the addendum's cross-vendor research:
  the community-convergent pattern for a hook that must do real work is to
  detach it (`nohup ... & disown; exit 0`) rather than trust Claude Code to
  wait, at the cost of losing that piece's ability to report an error back
  synchronously. Ties into ticket 41 Finding 4's proposed fix. Needs a
  design decision (how to preserve error visibility for detached work,
  likely via the same `capture.jsonl` reconciliation proposal #5 would
  build anyway) before scoping as a concrete diff.
- **Registering capture logic in `settings.json` directly instead of
  solely via the plugin's `hooks.json`**, as a redundancy hedge against the
  still-open, unresolved plugin-scope reliability gap (`#16288`, addendum
  Part 2). Not proposed as a concrete change here - would need to weigh
  against the plugin-packaging convenience this repo currently relies on
  (see CLAUDE.md's own emphasis on `cc-capture@cc-warehouse` being THE live
  plugin, verified via `enabledPlugins`).

## Provenance

Produced by a dedicated read-only logging/alerting audit agent
(`ccw-logging-audit`), dispatched alongside the RootCauseAnalysis and
external-research passes recorded in ticket 41 and its addendum. No files
were edited and no `ccw` write command was run during the audit itself.
