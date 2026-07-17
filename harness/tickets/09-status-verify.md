# Ticket 09: status + verify CLI

Slice 9 of 13. Depends on: 01 (wraps the slice-1 verify walk), 02, 04.

Tracer bullet: `ccw status` reads catalog + log only; `ccw verify` wraps the
store's re-hash walk and cross-checks it against the catalog in both
directions.

## Work order (template from harness/prompts/implementer.md)

- SLICE: status + verify CLI
- GOAL: make the slice-9 oracle tests pass without ever opening a stored
  payload outside the verify walk itself.
- ORACLE TESTS: tests/test_status_verify.py (all),
  tests/test_build.py::test_recent_listing_opens_zero_stored_payloads.
- CONTRACT EXCERPTS: DESIGN sections 7 (status/verify rows), 13 (orphan
  story); DESIGN 14 rules R4, R6, R12; FINDINGS F5.
- ADJACENT BEHAVIORS: store.verify_walk (slice 1: verify WRAPS it, never
  re-implements hashing), catalog reads, reports.BatchReport.
- TOUCHES: src/cc_warehouse/status.py, src/cc_warehouse/cli.py (status +
  verify verbs).

## Phase 2 decisions frozen in the tests

- status: exit 0, non-empty output, zero opens under objects/ (audit-hook
  proven); recent_sessions(config, limit) lists from the catalog only.
- verify: exit 0 on an intact store; non-zero naming the short hash for a
  corrupted object, an orphan object (reported, never deleted), or a session
  row whose object is missing. Verify never mutates the store.

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only.
