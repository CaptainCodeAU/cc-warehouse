# Ticket 31 is closed. Opening prompt for a fresh session, continuing ticket 27

Read `CLAUDE.md` first, as always. This file is a pointer into where the
previous session left off, not a replacement for it.

## Where things stand (as of tag `slice-31.5`, 2026-08-20)

**Ticket 31 (sweep full-corpus cost) is FULLY CLOSED.** 31.1 (folded into
31.2), 31.2, 31.3, 31.4, and 31.5 are all DONE. Gates at close: `uv run
pytest` 1109 passed (the one remaining failure, `tests/test_packaging.py::
test_every_shipped_file_is_tracked_by_git` over `.envrc`, predates this
session - `.envrc` was already untracked at session start and this ticket
never touched it; it is a pre-existing packaging-hygiene gap, not a
regression), `uv run pyright` 0 errors, `uv run ruff check` clean,
`tests/golden/matrix-anchor` untouched (61 passed on its own run).

Full account, in order of detail: `harness/tickets/31-sweep-full-corpus-
cost.md` (31.4/31.5 sections, "What shipped" + the recorded decisions);
`contract/DESIGN.md` section 15, entries "2026-08-20, ticket 31.4" and
"2026-08-20, ticket 31.5"; `contract/HARNESS.md` section 8, the 2026-08-20
entry "A TICKET NAMED ONE FUNCTION; THE REAL GAP WAS IN A CALLER IT DIDN'T
NAME" (the process lesson worth reading before scoping a debug-logging
ticket the same way again).

**31.4 in one paragraph.** The ticket asked for debug logging around
`capture._capture_locked`'s post-archive-write steps, not a retry loop (the
lock-contention mechanism was never proven, only suspected from one broken
folder). That shipped exactly as scoped: `catalog.add_session` and
`catalog.record_event` are each wrapped in a narrow try/except that logs
WHICH stage failed to the existing `logs/capture.jsonl` audit log, then
re-raises unconditionally - behavior is unchanged except for the added line.
Reading BOTH of `_capture_locked`'s callers (not just the function the
ticket named) before writing anything found something the ticket had not:
the hook path already reports failures via `notify.report`; the SWEEP path
(`sweep.sweep` -> `_capture_item`, called by `_run_sweep` with no per-item
exception handling at all) can abort an entire sweep mid-batch with nothing
printed or logged. That gap is recorded, not fixed - it is still an
unconfirmed mechanism, same as the original lock-contention question, and
should be diagnosed from a real exception if one recurs rather than assumed.
Decision recorded: 31.3 does NOT make the retry loop moot (it only removed
`skipped_unchanged` writes, never the `stored`-path writes the contention
theory is actually about).

**31.5 in one paragraph.** `ccw doctor` gained a new blocking `desync`
check: it verifies the 25 most-recently-STARTED archive folders (by
payload-derived start time, R12, never mtime) against `archive.
verify_folder` - the same instrument `ccw archive --verify` uses, run on a
small bounded recent sample instead of the full 21,000+ folder tree, so it
stays SessionStart-cheap. Deliberate scope, recorded: an old desync outside
the sample is NOT caught here on purpose; `ccw archive --verify` (by hand or
the weekly job) is still the complete answer. `ccw doctor`'s existing
`ccw-watch`-parsed text (the `hook` line, the `Uncaptured: N session(s)`
figure) is untouched - `desync` is a new, separately-named check.

**Cheap check done first, per the previous handoff's own instruction: no
real post-31.3 launchd sweep run exists yet.** 31.3 was tagged 08:10-08:11
UTC on 2026-08-20; that day's 12:30-local (02:30 UTC) sweep ran BEFORE the
deploy and shows the pre-31.3 shape in `capture_event` (16,382 individual
`skipped_unchanged` rows). Tomorrow's 12:30 run is still the first real
test of whether the daily job is actually fast now. The ~91% gap between
every per-item mechanism this investigation found (~72 s) and the one
34.5-minute daily run that started it all is STILL not explained by
anything in this codebase - it stays an open question, not assumed closed.

## What to do next: ticket 27, `harness/tickets/27-collapse-to-one-folder.md`

This is the project's actual ACTIVE TRACK per `CLAUDE.md`'s OPEN/next
section (tickets 22-27, in order; 22-26 closed; 27 is the only one left and
is unblocked). Ticket 31 was a same-day detour opened from a live incident,
now closed; ticket 27 was already in progress before it and is where the
project resumes.

**27.1 DONE 2026-08-05** (`ccw reindex` shipped) and **27.2 DONE**: the
real-data comparison verdict is "the catalog is disposable for sessions and
labels, NOT YET for aliases" (114 of 4,913 recovered after a rebuild, 2.3% -
that gap is ticket 28.21, tracked separately). So the next open step is
**27.3**, not the beginning:

- **27.3** sets `keep_objects = false` in `~/.config/cc-warehouse/
  config.toml` (a new line; the key runs on its `config.py` default of
  `True` today, and is reversible by deleting the line). **This edits the
  operator's REAL, LIVE machine config, not just this repo** - confirm with
  the operator before making the change, even though it is a one-line,
  reversible edit; it changes what the capture hook actually does on every
  future session end.
- **27.4 is marked DESTRUCTIVE in the ticket file itself**: rename
  `objects/` aside (not delete), exercise capture/sweep/build/verify/status
  and a real session end, and only delete once all of those pass - **the
  principal runs that command, at the moment of running, not in advance**.
  A green gate earlier in the ticket is not consent (ticket 27.9's own
  withdrawal is the standing example of exactly this distinction - it stays
  WITHDRAWN regardless of what else goes green).
- 27.5-27.8 follow after (root-into-archive decision, the `ccw archive --to`
  guard, reconciling `ccw verify` with ruling (b), retiring `store.py`).
  Read the ticket file's own text for each; it carries the scoping
  constraints in full.

## Standing rule, unchanged

Two slices in ticket 27 (27.4, and the withdrawn-forever 27.9) need the
principal's explicit word at the moment of running. 27.9 stays withdrawn
regardless of what else in this project goes green.
