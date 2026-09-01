# Ticket 35: durable logging for `ccw build` and `ccw repair`

Opened and CLOSED 2026-09-01, the operator's explicit follow-up request after
ticket 34: "put some logs in place so that if these different types of
situations or edge cases emerge, then everything gets logged in some file
with relevant information that would help us in the future for debugging".
Design left to this session's judgment.

## Why this ticket exists

`notify.append_log`/`logs/capture.jsonl` was already a working, durable,
structured sink - used by hook captures (`_run_hook`), sweep's per-item
capture failures (`sweep._log_item_failure`), and, since ticket 34, render-
child failures (`_render_session`'s error path, now that its inner swallow
is gone).

Three other outcome surfaces did NOT go through it at all, only ever
reaching `print(..., file=sys.stderr)`/stdout - durable exactly when the
calling process happened to be redirected to a file (true for the three
scheduled launchd jobs, false for any manual/interactive run):

1. `cli.py::_run_build`'s per-item failures.
2. `cli.py::_run_sweep`'s own post-capture `build.build()` failures (the
   same 2026-08-04 shape ticket 34.1 already fixed the swallow for, one
   layer further out: the failure now reaches the handler, but the handler
   itself only printed).
3. `cli.py::_run_repair`'s outcomes - BOTH directions. Still-broken folders
   at least reached stderr; a SUCCESSFUL fix under `--quiet` (the scheduled
   job's own flag) left literally no trace anywhere that repair had run, let
   alone what it recovered. "It worked" was strictly less recoverable than
   "it failed."

## What shipped

Two new small helpers in `cli.py`:

- `_log_build_failure(config, outcome, via)` - one durable record per failed
  `ItemOutcome`, called from both `_run_build` and `_run_sweep`'s build step
  (`via` distinguishes `"build"` from `"sweep-triggered build"` in the
  message text).
- `_log_repair_outcome(config, status, session, message)` - one durable
  record per `ccw repair` outcome, fixed or still-broken, called from all
  four branches of its per-folder loop (no catalog row / render subprocess
  failed / still broken after re-verify / fixed). Called REGARDLESS of
  `--quiet`: quiet only ever controlled the stdout summary (matching `ccw
  sweep`'s own established contract), never the durable record.

Both extend the SAME `capture.jsonl` file and the SAME six-field schema
(`at`, `status`, `session`, `project`, `message`, `elapsed_ms`) every
existing writer already uses, rather than inventing a parallel log or a new
JSON key - matching this project's own repeated convention for exactly this
kind of addition (`capture.py`'s `_log_stage_failure`, `__main__.py`'s
`_log_crash`: both fold the extra context into `message` as a prefix, not a
new field). Confirmed no production code reads `capture.jsonl` at all (only
tests assert on it), so there was no schema contract to break either way -
the message-prefix convention was a deliberate consistency choice, not a
forced one. Both helpers are best-effort, matching `append_log`'s own
swallow-on-`OSError` contract: a logging failure can never turn a working
build/sweep/repair run into a failing one.

The existing human-readable stdout/stderr output is unchanged; this is
additive only.

## Oracle tests (4 new, `tests/test_batch_failure_logging.py`)

- A real per-item `ccw build` failure (forced via `monkeypatch` on
  `archive.write_session_folder`, in-process so the patch is visible) is
  logged with an `error` record naming the failure.
- The same, triggered via `ccw sweep`'s own post-capture build step.
- A `ccw repair --quiet` run that successfully fixes a broken folder leaves
  an `ok`-status `"repair: fixed"` record naming the recovered session, even
  though stdout is empty.
- A `ccw repair --quiet` run against a folder that cannot actually be fixed
  (constructed as a REAL failure, not a simulated one: the catalog's
  recorded hash for the row is corrupted so the render subprocess's own
  integrity check genuinely fails - this crosses a real process boundary,
  which `monkeypatch` cannot reach) leaves an `error`-status record, even
  though stdout is empty.

RED confirmed before implementing (all four failed against the pre-fix
code - the fourth failure's own log inspection incidentally proved the
underlying `_render_session` crash-logging from ticket 34 already fires
correctly for that subprocess, which is a DIFFERENT record than the one this
ticket adds; the assertion was written to check for the new repair-specific
record specifically, and correctly did not match the pre-existing one).
GREEN after.

## Gates

Full suite: 1210 passed (1208 after ticket 34, plus 2 net new files' worth
collapsing to 4 new tests here - `test_repair.py`'s existing coverage was
untouched). `uv run ruff check .` clean. `uv run pyright` 0 new errors from
this ticket's own files (16 total at the time of this run: the same 15
pre-existing, unrelated errors in `tests/test_render_open.py` ticket 34
already reconfirmed via a clean baseline, unaffected by this change).

Two pre-existing, OUT-OF-SCOPE `test_packaging.py` failures were observed
while gating this ticket and are NOT part of it: `test_no_forbidden_content_in_the_artifact`
flags a real home-directory path leaked into `docs/operations.md`, committed
in `46a8757` ("docs: close deployment/hook documentation gaps (ticket 36)"),
a parallel session's own work. Left for that ticket to fix.
