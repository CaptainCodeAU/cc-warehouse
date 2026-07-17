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
