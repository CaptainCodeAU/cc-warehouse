# Ticket 32: the detached render child can fail with zero trace, and nothing repairs it

Opened and CLOSED 2026-08-23, from a real live incident the same day.

## Why this ticket exists

A captured session (`CaptainCodeAU-win_go_app_test/20260823-183049+1000_9029cc5b-...`)
had its JSONL archived and its catalog row written -- the hook reported "ok" and
`logs/capture.jsonl` has the line to prove it -- but its five generated files
(`archive.GENERATED_NAMES`: manifest, transcript.md/.compact.md,
conversation.html/.compact.html) never existed. `ccw doctor`'s desync check
(ticket 31.5) caught it (5 problems, all one session missing all five files),
but diagnosing and fixing it needed manual detective work: no crash report, no
OOM/jetsam event, no sleep/wake interruption, and no "error" line anywhere.
Manually re-running `ccw render --session s:<key>` fixed it instantly, which
ruled out a reproducible bug in the render logic itself -- the render CHILD
simply never finished, for a reason that left no trace to find.

Root-caused as far as the evidence goes, not further: `_render_session`
(cli.py) has its own try/except around the read+write portion (which DOES
call `notify.report` on failure -- that's how a render error would normally
surface), but the catalog lookup just before it (`catalog.open_catalog`, the
`SELECT ... WHERE short = ?`, `build.head_for_short`) is NOT inside that
try/except. Anything failing there -- and this session's own catalog row
existed fine, so it is not proven to be catalog contention specifically,
consistent with ticket 31.4's still-unconfirmed lock-contention question --
would raise all the way up through `main()`, uncaught, with its stdout/stderr
going to DEVNULL by the locked SPEC section 5 decision ("all stdio to
DEVNULL", **KEEP** verbatim). That combination is what made it invisible:
not one bug, but an escape hatch with no floor under it.

**This is the SAME shape as ticket 31.4's "no reporting path at all" finding**,
on a different pipeline (render, not sweep's catalog-write stage) -- the third
occurrence of a related defect class in this project. Per this project's own
standing lesson ("the same defect class recurs across modules"), the fix
targets the SHAPE (an uncaught exception before a verb's own error path, in a
process whose stdio is deliberately silent) rather than only this one instance.

## What shipped

### 32.1 Crash visibility: `__main__.py` gains a safety net, SPEC untouched

`__main__.py` is used ONLY by the two detached children (render, spawned by
the hook; notify, spawned by `notify.report`'s webhook path) -- the `ccw`
console script maps straight to `cli.main` (`pyproject.toml`
`[project.scripts]`), so an ordinary `ccw <verb>` invocation never goes
through it. That made it the one place to add a catch-all WITHOUT touching
SPEC section 5's locked "all stdio to DEVNULL" line: `_run()` wraps `main()`,
and on any otherwise-uncaught exception appends one line to the existing
`logs/capture.jsonl` (via `notify.append_log`, the already-sanctioned O_APPEND
write, DESIGN R2) before re-raising -- the crash, exit code, and stderr
traceback are all UNCHANGED; only a durable record now exists first. Kept to
`notify.append_log` rather than the fuller `notify.report` deliberately: the
latter also spawns a detached notify-helper child, and that child ALSO runs
through `__main__.py` -- calling it from inside a crash handler for THIS path
risks recursing if the notify verb itself were ever what's broken.

This was found to be a real, live gap by trying to write the test first: a
locked oracle test (`tests/test_capture.py::test_hook_spawns_detached_render_child`,
SPEC 2.5/5 KEEP) pins `stdout=DEVNULL, stderr=DEVNULL` on the render child's
Popen call, so the original instinct (redirect the child's own stdio to a log
file) would have meant editing a locked contract test to make new code pass --
exactly the "contract fences: narrow, never dodge" trap. Reading SPEC.md
section 5 confirmed DEVNULL is the actual locked decision, not incidental;
`__main__.py`'s catch-all achieves the same visibility without touching it.

**Oracle tests**: `tests/test_render_child_crash_log.py` (new, 2 tests) --
corrupts `catalog.sqlite` so the exception fires exactly where the real
incident's silence points (before `_render_session`'s own try/except), runs
`python -m cc_warehouse render ...` as a genuine subprocess (matching
production's actual invocation shape), and pins both that the crash is now
logged AND that the original exception/exit code/stderr still propagate
unchanged. RED confirmed before the `__main__.py` change (missing log line),
GREEN after.

### 32.2 Self-healing: `ccw repair`, a new verb -- `doctor` stays untouched

`ccw doctor`'s own module docstring is explicit: "READ-ONLY BY CONSTRUCTION,
which is not a nicety here: doctor runs when things are broken, so it must
not materialise a warehouse that was never there." Its text output is also a
documented external compatibility surface (`ccw-watch`, a different repo,
parses it with sed/grep -- ticket 28.22's fence). Adding a write side effect
to `doctor`, even behind a flag, would cut against both. Instead: `ccw
repair`, a new, separate, explicitly-named verb.

`doctor._desync_detail` was refactored into a public `doctor.desync_detail`
(the recency-scan + `archive.verify_folder` walk, ONE place, ticket 31.5's
existing `_DESYNC_SAMPLE` bound respected exactly) that both `doctor._desync`
(the existing summary) and `cli._run_repair` now share (R9) -- `_desync`'s own
signature and behavior are unchanged, proven by the pre-existing desync tests
staying green untouched. `repair` resolves each broken folder's session_uuid
(from its own name, R12) to a catalog short key, then calls the SAME `ccw
render --session s:<key>` path a human would run by hand, synchronously
(repair is an explicit operator/scheduled action, not a hook, so waiting on it
costs nothing) -- verifies the fix actually took before counting it fixed, and
reports `N fixed, M still broken` with per-folder detail on stderr for
anything it could not resolve.

**Oracle tests**: `tests/test_repair.py` (new, 3 tests) -- fixes a folder
missing all five generated files (the real incident's exact shape) and
confirms `doctor` is green afterward; is a byte-for-byte no-op when nothing is
broken; and respects the same `_DESYNC_SAMPLE` bound `doctor` does (an old,
out-of-sample desync is deliberately not `repair`'s job either -- `ccw archive
--verify`, by hand or the weekly job, is still the full-tree answer).

**Verified on real data**: `ccw repair` run against the live warehouse (22,000+
archive folders, `desync` already 0 after the incident was fixed by hand)
correctly reported "0 problems in the 25 most recently captured folder(s)" and
wrote nothing.

## What was deliberately NOT done

- **Not wired into any scheduled job.** `repair` is on-demand only for now.
  `ccw-watch` (a different repo) already prints a RED banner with a fix
  pointer at every session start when desync is found -- `repair` turns that
  from a multi-step manual diagnosis into one command, which is most of the
  practical win. Wiring it into the existing daily `com.captaincodeau.ccw-sweep`
  launchd job (or elsewhere) is a system-level change outside this repo and
  was left for the principal to decide, not assumed.
- **The exact trigger for the original crash stays unconfirmed**, matching
  ticket 31.4's own precedent of not designing a fix for an unproven cause.
  32.1 makes the NEXT occurrence (if any) diagnosable from `logs/capture.jsonl`
  instead of requiring the same manual forensics this ticket started from.

## Gates

Full suite: 1136 passed (5 new: 2 in `test_render_child_crash_log.py`, 3 in
`test_repair.py`), `uv run ruff check .` clean, `uv run pyright` 0 errors.
`tests/golden/matrix-anchor` untouched -- no projected byte moved, no default
output changed.
