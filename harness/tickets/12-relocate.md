# Ticket 12: relocate

Slice 12 of 13. Depends on: 02 (registry aliases), 04 (config subset).

NOTE (slice 02 fixer round 1, 2026-07-18): registry.move_project claims only the
raw cwd form of new_path today, not its ENCODED form (deferred until the cwd
encoder ships with slices 03/04). A relocate of a project first captured without
a cwd must re-claim the encoded form here, or it will resolve to a stale project
after the move.

THE RISKIEST V1 SURFACE (BRAINSTORM lock): this slice gets the heaviest
adversarial review. Both reviewers should budget double attention; FINDINGS
F2/F7/F9/F10 apply doubly here.

Tracer bullet: `ccw relocate <repo> --to <new>` repairs the external world
after a repo move in the specimen-taught order: PLAN -> show plan -> BACKUP ->
APPLY (contents before containers) -> VERIFY -> REPORT. Dry-run is the
default; --apply executes.

## Work order (template from harness/prompts/implementer.md)

- SLICE: relocate
- GOAL: make the slice-12 oracle tests pass without ever leaving the external
  world half-rewritten.
- ORACLE TESTS: tests/test_relocate.py (all).
- CONTRACT EXCERPTS: DESIGN section 11; SPEC section 10.2 (KEEP mechanics);
  DESIGN 14 rules R2, R5, R13; FINDINGS F2, F7, F9, F10.
- ADJACENT BEHAVIORS: registry.move_project (slice 2: the registry edit IS
  that function, not new SQL), store.atomic_write (every content rewrite),
  config relocate roots ([relocate] roots list, slice 4/13 loader).
- TOUCHES: src/cc_warehouse/relocate.py, src/cc_warehouse/cli.py (relocate
  verb + --to/--apply/--yes flags).

## Phase 2 decisions frozen in the tests

- Dry-run default prints the plan (including the target path) and changes
  NOTHING; --apply requires an interactive yes or --yes; non-TTY without
  --yes aborts untouched (R13/F10).
- Apply order: backups first (under <root>/backups/, originals preserved),
  memory file contents rewritten (markdown AND JSON-aware: rewritten JSON
  re-parses) BEFORE encoded dirs are renamed or the repo is moved.
- Encoded-dir matching is boundary-guarded: after the matched prefix the
  remainder must be empty or start with `-`; `...-widgetbar` never matches
  `...-widget`.
- Refuses a non-empty target with the Error: contract, exit 1, untouched.
- A content-rewrite failure names the item, exits non-zero, and halts the
  container renames and the repo move entirely (F7: conservative branch).
- The registry gains the new path as an alias claim.

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only. Consider the optional /code-review
third lens at slice close (HARNESS section 9); it feeds the same triage.
