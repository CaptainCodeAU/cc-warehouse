# Ticket 10: migrate + retire

Slice 10 of 13. Depends on: 04 (reuses capture_transcript), 05 (batch shape).

Tracer bullet: `ccw migrate <old-root>` imports the ~7.3k-session legacy
archive through the standard store routine; `ccw migrate --retire <old-root>`
performs the single sanctioned old-world rename afterward.

## Work order (template from harness/prompts/implementer.md)

- SLICE: migrate + retire
- GOAL: make the slice-10 oracle tests pass; the source tree stays
  byte-identical (except the explicit retire rename).
- ORACLE TESTS: tests/test_migrate.py (all).
- CONTRACT EXCERPTS: DESIGN section 10; DESIGN 14 rules R1, R4, R5, R10,
  R13; FINDINGS F1, F7, F9, F10; SPEC section 9 (batch posture).
- ADJACENT BEHAVIORS: capture.capture_transcript (slice 4: migrate carries
  ZERO capture logic, R9/F8), store hash dedupe (duplicate archive copies
  collapse for free), reports.BatchReport.
- TOUCHES: src/cc_warehouse/migrate.py, src/cc_warehouse/cli.py (migrate
  verb + --retire and --yes flags).

## Phase 2 decisions frozen in the tests

- Manifest at <root>/logs/migrate-manifest.json (latest run, written via
  atomic_write): one entry per source file with source, hash, outcome; every
  file accounted for (stored / duplicate* / error).
- Idempotent: a second migrate adds no rows.
- Unreadable item: named in the report, left untouched, batch continues,
  exit non-zero.
- Retire: renames the root to _RETIRED_<YYYY-MM>_<name> (contents
  untouched); requires an interactive yes or --yes; non-TTY stdin without
  --yes exits non-zero having changed nothing (R13).

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only.

## DONE 2026-07-19

COMPLETE through the full loop. Implementer green on first gate pass (6 oracle
tests). Reviewers A/B in parallel (A 3 conformance, B 2 adversary; overlap 1 -
the non-regular-file silent drop, found by both lenses). Operator triage: 3
clusters, all 3 CONFIRMED and probe-verified, 0 rejected, fixed in 1 fixer round
(of 3): C1 (F7/R10) a non-regular *.jsonl (dangling/looping symlink, FIFO, socket)
is now a named error item in both the BatchReport and the manifest rather than
silently dropped, never handed to capture (a FIFO read would block migrate); C2
(R4/F9) retire refuses a pre-existing target rather than let os.rename silently
remove an existing empty _RETIRED_ dir (a delete outside R4's closed list) or
crash on a non-empty one, the CLI catches OSError for a clean message; A1
(R14/DESIGN 13) migrate now takes a locks/migrate O_EXCL lock (DESIGN 13 names
migrate a lock-taker) mirroring sweep, refusing a live holder with a distinct
non-counted refusal. Locked decision D1: --retire = consent + single rename only,
no import (DESIGN 10 "separate explicit step"). migrate reuses
capture.capture_transcript verbatim (R9/F8), store.atomic_write for the manifest
(R2), reports.BatchReport/ItemOutcome. 3 contract-derived regression tests
(tests/test_migrate_regressions.py). Operator black-box verified 6/6 independent
of the fixer self-report (dangling symlink, FIFO no-hang, empty+non-empty retire
target, happy retire, lock-held). Gates: 6 oracle + 3 regression green, pyright
strict 0, ruff clean; full suite 20 failed / 156 passed, red for the right reason.
Retro in HARNESS section 8. Milestone tag slice-10.
