# Ticket 05: sweep

Slice 5 of 13. Depends on: 04 (reuses capture_transcript verbatim).

Tracer bullet: `ccw sweep` walks ~/.claude/projects (or --source), captures
every payload the catalog lacks through the SAME routine as the hook, adopts
orphan store objects, and never aborts on a bad item.

## Work order (template from harness/prompts/implementer.md)

- SLICE: sweep
- GOAL: make the slice-5 oracle tests pass with a lock-guarded, idempotent,
  continue-past-failures sweep.
- ORACLE TESTS: tests/test_sweep.py (all).
- CONTRACT EXCERPTS: DESIGN sections 4 (sweep paragraph), 13; SPEC sections
  8 (agent-* exclusion) and 9 (batch posture); DESIGN 14 rules R5, R9, R10,
  R14; FINDINGS F3, F7, F9.
- ADJACENT BEHAVIORS: capture.capture_transcript (slice 4: sweep carries ZERO
  capture logic of its own, R9/F8), store.acquire_lock / release_lock
  (slice 1), reports.BatchReport / ItemOutcome (the shared batch shape).
- TOUCHES: src/cc_warehouse/sweep.py, src/cc_warehouse/cli.py (sweep verb).

## Phase 2 decisions frozen in the tests

- locks/sweep via the slice-1 lock helpers: a live holder makes sweep exit
  non-zero having captured nothing; a dead-PID lock is taken over.
- agent-*.jsonl files are skipped by default (config opt-in later).
- An unreadable item: reported by NAME in the end report, left untouched,
  batch continues; any item failure makes the exit code non-zero.
- After the source walk, uncataloged objects already in the store are
  adopted into the catalog (DESIGN section 13 orphan story).
- Sources are read-only, forever (byte-identical tree after sweep).

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only.

## DONE 2026-07-18

Slice 05 COMPLETE through the full harness loop. Implementer diff green on first
gate pass (7 oracle tests); sweep reuses capture.capture_transcript verbatim per
file (R9/F8), store.acquire_lock/release_lock for locks/sweep (R14), and
reports.BatchReport/ItemOutcome (the shared batch shape). Reviewers A/B in parallel
plus the /code-review Standards+Spec third lens. Operator triage: 7 clusters, 3
CONFIRMED + fixed in 1 fixer round (of 3), 4 REJECTED (recorded):
- C1 (R5/F7): an unreadable source subdirectory was silently skipped by rglob; the
  walk now uses os.walk(onerror=...) so a directory-listing error is a named failed
  item with a non-zero exit, never a silent under-capture.
- C2 (R5): a malformed `--source` (missing / empty / flag-like value) now fails
  conservatively (usage error, captures nothing) instead of silently sweeping the
  default tree; the `--source=DIR` form is also supported.
- C3 (R8-spirit): a live lock holder reports a distinct refusal and is not counted
  as a batch item.
Rejected (recorded, not dropped): C4 orphan filename-vs-content = ccw verify's
domain (slice 9), torn-tmp refuted (the store's atomic-write tmp is dot-prefixed);
C5 cwd=None attribution refuted (capture resolves from the source path's jsonl cwd /
encoded dir); C6 in-progress two-rows = intended supersedes; C7 swept-no-render =
batch tool, render is build's incremental job. D1 (forward cwd encoder +
registry.move_project claim) stays a FOLLOW-UP; it does not ride this slice.

Contract-derived regression tests (this ticket owns them by citation, HARNESS
section 4 precedent): tests/test_sweep_regressions.py (RT-C1 unreadable-subdir
named, RT-C2 valueless/empty --source refused, RT-C5 swept session attributes to
its project). Operator black-box verified 31/31 in fresh temp dirs independent of
the fixer self-report. Gates: 7 oracle + 4 regression green, pyright strict 0, ruff
clean; full suite 55 failed / 94 passed, red for the right reason.
