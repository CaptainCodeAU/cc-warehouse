# Ticket 42: close the logging and alerting gaps found in the 2026-09-09 capture incident

Opened 2026-09-09. **Item #1 DONE and LIVE the same day** (real desktop/voice
notification wired into `ccw-freshness-check.py`'s WARN/ALERT tiers, pushed
`a781555`, verified live end to end - see `harness/HANDOFFS.md`'s
thirty-seventh entry for the full account). **Items #2, #3, #4, #5, #6 and #7
are DONE (2026-09-09); one of the two unranked design-tradeoff items closed
the same day via ticket 37 Part B. Still NOT started: the remaining unranked
item (registering capture logic in `settings.json` directly). #6 is coded,
tested and verified against real data but NOT yet reinstalled into the frozen
`ccw` - needs the operator's go-ahead first, per this repo's own standing
practice for anything that changes the live capture path.**
Follow-up
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

**2. DONE 2026-09-09.** HIGH value / LOW-MEDIUM effort - `ccw sweep` per-run summary logging
(ticket 41 Finding 2). Scope: `cli.py::_run_sweep`, mirroring
`_log_repair_outcome`'s "always write regardless of `--quiet`" pattern.
Extend the same treatment to standalone `ccw build` and `ccw archive` for
consistency - today only `ccw repair` reliably records "I ran and here's
what happened."
**Shipped as `_log_run_summary` (new `cli.py` helper), wired into `_run_sweep` and
`_run_build` including their lock-refusal paths, exactly as scoped.** `ccw archive`
did NOT get one, found by execution rather than by plan: the first attempt broke a
real, load-bearing contract (`test_archive_cli.py::test_archive_leaves_the_source_
warehouse_byte_identical` - "archive builds BESIDE the warehouse, touching nothing
under it," and a `capture.jsonl` write IS a warehouse write). Reverted the archive
call sites; kept a scope note in `cli.py` and a new oracle test proving the
warehouse's log is untouched by a real `ccw archive` run
(`test_run_summary_logging.py::test_archive_writes_no_capture_jsonl_record_of_any_kind`).
`reconcile._EXCLUDED_PREFIXES` gained `"sweep: "`/`"build: "` (no `"archive: "`, for
the same reason) so a run summary is never misread as a lost session. New tests in
`tests/test_run_summary_logging.py`; full account: `contract/DESIGN.md` section 15,
"2026-09-09, ticket 42 #2/#3/#7".

**3. DONE 2026-09-09.** HIGH value / MEDIUM effort - make `ccw sweep`'s per-item errors reach
`capture.jsonl`, not just stderr. Scope: `sweep.py::_capture_item`
(~line 395-412). Today a sweep-discovered unreadable-transcript error is
invisible to `capture.jsonl`-based tooling entirely (including proposal #5
below), even though the identical error via the live hook IS logged there -
an inconsistency between the two capture paths for the same failure.
**Shipped exactly as scoped.** `sweep._log_item_failure` widened from taking an
`Exception` to a `detail: str`, so `_capture_item` can call the SAME writer on
`capture_transcript`'s graceful `CaptureResult(action="error")` return, not just on a
raised exception - the raising path's message shape is unchanged, so old records
stay comparable. Two new oracle tests in `tests/test_sweep_graceful_error_logging.py`:
a real sweep against a `chmod(0)` transcript reaches `capture.jsonl`, and the exact
message shape survives `reconcile.find_unrecoverable`'s excluded-prefix filter (it
names a real session, unlike proposal #2's run summaries). Full account:
`contract/DESIGN.md` section 15, "2026-09-09, ticket 42 #2/#3/#7".

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
repair`'s live run WAS then triggered, with the operator's explicit go-ahead**:
announced 15 newly-confirmed unrecoverable sessions (the 14-day alert window;
6 of the 21 fall outside it), wrote the dedup record for each, fired one
real desktop+voice alert. `ccw doctor`'s new `reconcile` line confirmed it
afterward ("15 session(s) on record as unrecoverable"), and a second `ccw
repair` run correctly stayed silent (dedup verified live, not just in tests).
Full account: `harness/HANDOFFS.md`'s forty-first handoff.

**6. DONE 2026-09-09.** MEDIUM value / MEDIUM effort - build a hook-dispatch-gap detector
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
**Shipped as scoped**: new `doctor._dispatch_gap(config, walk_root, home)`, a new
non-blocking `dispatch` line in `diagnose()` (placed right after `overdue`, same
"in the order an operator would ask them" ordering the module's own docstring
names). Reads `ccw-hook.log`'s own `started` lines (full session-id field, not
the short hash `capture.jsonl` uses) within `_DISPATCH_WINDOW` (7 days, same
bounded-recency posture as `_COMPANIONS_WINDOW`); walks only UNARCHIVED source
transcripts via `sweep.source_transcripts`, flagging one whose last activity
(R12, payload-derived) is older than `_DISPATCH_GRACE_SECONDS` (15 min) but still
inside the window, and absent from the started-set. Three "cannot answer"
states all read `ok=True` with an explanatory detail, same posture as
`sidecars`/`history`/`prompts`/`companions`/`reconcile`: no `ccw-hook.log` yet,
an archived session (sweep worked without the hook, which is fine), and a gap
older than the window (`ccw reconcile` is the permanent record for that, not
this line). 7 new oracle tests in `tests/test_doctor.py`; full suite 1604
passed (was 1593), ruff and pyright strict clean project-wide. **Verified
against real data, read-only, no reinstall needed** (doctor checks are dev-checkout
code, `uv run ccw doctor` on this machine): found a genuine, real dispatch gap
- 4 sessions on this machine with zero `ccw-hook.log` entries, doctor's overall
exit code stayed 0 as designed. Not yet deployed to the frozen install; that
needs the operator's go-ahead per this repo's own standing practice.

**7. DONE 2026-09-09.** LOW value / LOW effort, hygiene - stop `ccw-hook.log` lying about
success (Finding A above). Have `_run_hook` print its actual outcome to
stdout, and have `ccw-hook.py`'s wrapper report that instead of a
hardcoded "ok" on exit-0. No new alerting; stops the first file anyone
greps during an incident (this investigation included) from systematically
misreporting graceful-failure cases as success.
**RE-MEASURED before shipping, not just argued: `~/.claude/logs/ccw-hook.log`, 1,238
real rows, `ccw-hook` source is 70 `started` + 61 `ok` + ZERO `error`, ever.** Shipped
as scoped, plus one operator decision found while scoping: whether the wrapper should
ALSO speak the new status. Confirmed via AskUserQuestion before building - no, log
only, no second voice: `ccw hook` already speaks a graceful `error` result itself
(`notify.SPEAKING_STATUSES` includes `"error"`, and the wrapper hands the child
`CCW_VOICE_URL`/`CCW_VOICE_ID`), so a second alert from this wrapper would be the
operator hearing the same failure twice. `cli._run_hook` prints one outcome line
(`"ok: captured"` / `"error: <detail>"` / `"skipped_unchanged"` / `"skipped_disabled"`
/ `"duplicate-invocation"`) before returning 0 on every path (SPEC 2.6/F7 unchanged);
the wrapper reads it and logs a NEW status, `"capture-error"`, kept out of its own
voice gate rather than reusing `"error"`. Deploy-order safety (the tool reinstall and
the plugin update land independently, in either order) is pinned by a dedicated test.
New tests in `tests/test_hook_prints_outcome.py` and four added to
`tests/test_cc_capture_hook_started.py`. Full account: `contract/DESIGN.md` section
15, "2026-09-09, ticket 42 #2/#3/#7".

## Also worth weighing, not ranked as a numbered fix (design tradeoff, needs a decision first)

- **CLOSED 2026-09-09, by ticket 37 Part B (`cd84020`), same day this ticket was
  opened - this bullet was stale and said the opposite until corrected.** Moving
  the hook's synchronous sidecar/external-file copying
  (`_archive_sidecars_of`/`_archive_external_of`, capture.py:440-547) off the
  SessionEnd timing budget, per the addendum's cross-vendor research: the
  community-convergent pattern for a hook that must do real work is to detach it
  rather than trust Claude Code to wait. **Built the same day, wider than this
  bullet's own two named functions**: all four companion calls detach into a new
  `ccw companions` child, plus `logs/capture.jsonl` logging and a non-blocking
  `ccw doctor` `companions` check for error visibility - deployed live and
  verified the same day. See `harness/tickets/37-*.md`'s "Part B DONE,
  2026-09-09" section and `harness/HANDOFFS.md`'s thirty-ninth handoff for the
  full account.
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
