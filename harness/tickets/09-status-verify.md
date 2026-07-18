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

## DONE 2026-07-19

Slice 09 COMPLETE through the full harness loop. Implementer diff green on first gate
pass (6 status_verify + the F5 test_recent_listing_opens_zero_stored_payloads). status
reads the catalog only (recent_sessions / status_text: counts + SUM(size_bytes) + last
errors, zero object opens, F5/R6); verify WRAPS store.verify_walk (no re-implemented
hashing, R9) and cross-checks the catalog against the objects in BOTH directions
(corrupted / orphan-never-deleted / missing), read-only (R4). status.py holds no write
handle and deletes nothing (fences green). A clean slice: Reviewer A found no findings.
Reviewer B + /code-review: operator triage, 2 CONFIRMED clusters fixed in 1 fixer round
(of 3):
- C-VERIFY-CRASH (F7/R5): verify crashed on a malformed/NULL catalog session.hash
  (non-hex -> ValueError, NULL -> TypeError in sorted()), suppressing every finding on
  exactly the suspect store it inspects; now it validates each hash (store.is_sha256_hex)
  before store.has, reports a malformed row, and keeps going (report-and-continue).
- C-UNREADABLE-LABEL (R8-spirit): an unreadable object is now labeled "unreadable"
  rather than a content-address mismatch.
Refuted: B3 (dedup "bytes stored" double-count -- session PK is the hash, one row per
object), B5 (nondeterministic output -- verify_walk yields sorted). Accepted: litter not
surfaced, the store-size logical-total label, the ext=".jsonl" missing-direction
asymmetry (a v1.1 follow-up when web_export lands).

Contract-derived regression tests (this ticket owns them by citation, HARNESS section
4 precedent): tests/test_status_verify_regressions.py (3 tests). Operator black-box
verified 7/7 via real ccw subprocesses (status + the four verify states + the
malformed-hash no-crash), and re-probed the crash fix. Gates: 6 oracle + 3 regression +
7 build + 6 fences green, pyright strict 0, ruff clean; full suite 24 failed / 149
passed, red for the right reason.
