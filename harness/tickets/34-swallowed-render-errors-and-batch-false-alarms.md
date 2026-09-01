# Ticket 34: swallowed render errors, and doctor crying wolf mid-batch

Opened and CLOSED 2026-09-01, the two findings ticket 33 explicitly deferred
("Left for a future ticket" / "not revisited") from the same red-team audit.
Operator reviewed both, said "be thorough," and asked for both to be fixed
in one session.

## 34.1 A real render failure was silently swallowed, with zero trace

### Why this ticket exists

`build.py`'s `_mirror` and `cli.py`'s `_mirror_to_archive` both wrapped their
one call to `archive.write_session_folder` in `except Exception: return`,
justified in each docstring as protecting DESIGN 12's "a detached child must
never turn a stored capture into a lost one". That justification over-reached.

Both functions have exactly one caller (confirmed via the census tool, not
grep), and both callers already have their own correctly-designed handler for
this exact failure, one frame up:

- `cli.py`'s `_render_session` already wraps its call to `_mirror_to_archive`
  in an outer `except Exception as exc:` (DESIGN section 4's documented
  contract for this exact call site) that reports a best-effort error
  notification and exits non-zero, without touching capture or catalog state.
- `build.py`'s `build()` already wraps its call to `_mirror` in a per-head
  `except Exception as exc:` implementing the R10 "name it, record an `error`
  `ItemOutcome`, and carry on" pattern, which also correctly skips pruning the
  retired-dirs set on an incomplete build.

The inner swallow prevented the exception from ever reaching either already-
correct handler, so a real mirror failure looked exactly like a clean,
silent success. This is the FINDINGS F7 shape by name ("any error on the
evidence path aborts the action for that item and reports it") and violates
DESIGN section 13 ("item-level errors: report + skip item, never
reclassify"). It is also concretely what happened on 2026-08-04: `cli.py`'s
own `_run_sweep` comment records a sweep that stored 642 sessions with zero
rendered pages, discovered only by a manual `ccw archive --verify`.

Confirmed NOT a locked contract decision (contract/DESIGN.md, SPEC.md,
FINDINGS.md all searched; DESIGN section 12/13 and FINDINGS F7 argue directly
AGAINST the swallow, not for it), so no principal ruling or contract
amendment was needed here, unlike ticket 33.

### What shipped

Removed both inner `try/except Exception: return` wrappers. Exceptions from
`archive.write_session_folder` now propagate to the existing outer handlers
unchanged; no new logging machinery was added because none was needed - the
outer handlers already log/report correctly once they can see the failure.
Both docstrings rewritten to explain the correction.

**Oracle tests** (5 new): `tests/test_build_incremental.py` pins that a
mirror failure is reported as `1 failed` (not `1 built`) and that pruning is
skipped for a build with a failed head (a genuinely retired projection dir,
created via the existing "grown payload lands in a new dir" fixture, must
survive when the head that would have retired it also failed). Also fixed a
pre-existing counting-unit assumption while writing these:
`tests/test_build_incremental.py`'s stderr assertion pins the exact message
(`"RuntimeError: simulated mirror failure"`). `tests/test_render_child_crash_log.py`
pins that `ccw render --session` returns non-zero and leaves an `error`
record in `logs/capture.jsonl` (the same durable sink ticket 32's detached-
child crash log already uses) when the mirror write fails. RED confirmed
against the pre-fix code via `git stash` (old code returned 0 / "1 built" /
no log record in each case), GREEN after.

## 34.2 `ccw doctor`'s desync check cried wolf mid-batch

### Why this ticket exists

`ccw sweep` can capture hundreds of sessions in under two minutes, then
render them afterward through `build.build()`, which takes real wall-clock
time. Measured live 2026-09-01: a 446-session sweep batch, one ordinary
session (`dbb9acea-...`) took 7m14s from capture (02:34:22 UTC) to fully
rendered (02:41:36 UTC). `ccw doctor`'s desync check (`_DESYNC_SAMPLE = 25`
most-recently-captured folders) sampled mid-batch at 02:34:46 UTC - 24
seconds after that session was captured - and reported it, and ~21 others
still in the same queue, as broken. `ccw-watch`'s RED "capture is NOT
working" banner fired from exactly this reading. By the time anyone looked
by hand, `build()` had long since finished and the archive was clean (`ccw
archive --verify`: 26,696 folders, 0 problems) - the alarm was real at the
moment it fired, but describing a normal queue, not a failure.

### What shipped

`store.py` gained one new public function, `lock_is_held(root, name)`, a
pure read (reuses the existing private `_read_lock_holder`/`_pid_is_alive`,
never acquires or mutates anything) answering "is a process holding
`locks/<name>` still alive". `build.build()` holds its own lock for its
entire per-head loop, so this stays true for exactly as long as a
sweep-triggered batch is actually rendering - not a guessed duration.

`doctor._desync` now classifies each broken folder as PENDING rather than a
blocking problem when BOTH: every one of its problems is a missing-generated-
file problem (`FolderProblem.problem` starting with `"missing "`, the one
shape produced for a not-yet-rendered file) - narrowed on purpose so a hash
mismatch, an unreadable manifest, a missing/altered sub-agent, or a bad
folder name NEVER counts as pending regardless of timing, because none of
those describe "still queued" - AND EITHER the sweep or build lock is
currently held (covers the bulk-batch case, via `lock_is_held`), OR the
folder was captured within `_PENDING_GRACE_SECONDS` (120s) of now (covers the
live hook's own single-session detached render child, which holds no lock at
all). Pending folders are still counted and surfaced in the detail text
(`"0 problems, 3 pending render(s) in the 25 most recently captured
folder(s)"`) rather than made invisible; only the blocking exit code ignores
them. `desync_detail` (the shared function `ccw repair` also reads) is
UNCHANGED - repair still attempts every raw problem it finds, since a
redundant render of a folder that turns out to already be current is
harmless and idempotent.

**Oracle tests** (4 new, `tests/test_doctor.py`): an old, genuinely broken
folder with no lock held still fails doctor (the negative case that matters
most - proves the carve-out did not quietly widen); a freshly-captured
missing-render folder with no lock held is pending, not blocking, and
`report.ok` stays true; the same old folder becomes pending while the
build lock is held by a live PID (this test's own, matching
`lock_is_held`'s liveness definition) and reverts to blocking once the lock
releases, isolating the lock signal from recency; a hash-mismatch
(`_tamper`) on a FRESHLY captured folder still fails doctor even though it
would qualify for the grace window on timing alone, pinning the "only
missing-file problems, never a mix" narrowing. One existing test
(`test_desync_check_is_bounded_to_the_recent_sample`) updated for `_desync`'s
new 4-tuple return (`checked, problems, pending, first`); its own assertions
were unaffected since it only ever produces hash-mismatch problems, which
are never pending. RED confirmed against the pre-fix code via `git stash`
(the old 3-tuple unpack raised `ValueError`, and after adapting the assertion
shape, all four new tests failed for the right reason), GREEN after. Two of
the four new tests were written with a wrong assumption on the first pass
(`basic_session`'s fixed 2026-01-05 fixture timestamp is not "now"; the
pending count was first asserted per-folder instead of per-problem,
inconsistent with how `problems` was already counted) and corrected before
being trusted - recorded here because both are exactly the kind of small,
easy-to-miss test bug this project's own oracle-test discipline exists to
force out via RED-before-GREEN, not because either was a product defect.

## Gates

Full suite: 1208 passed (1201 after ticket 33, plus 7 new here: 2 in
`test_build_incremental.py`, 1 in `test_render_child_crash_log.py`, 4 in
`test_doctor.py`). `uv run ruff check .` clean. `uv run pyright` 0 new
errors (15 pre-existing, unrelated, in `tests/test_render_open.py`,
reconfirmed present on a clean `git stash` baseline the same way ticket 33
did).
