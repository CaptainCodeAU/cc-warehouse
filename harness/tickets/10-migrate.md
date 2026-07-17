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
