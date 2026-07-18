# Ticket 01: store module (THE TRIAL RUN)

**DONE 2026-07-18** through the full harness loop (1 fixer round; commit
75b9b68; retro recorded in HARNESS section 8).

Slice 1 of 13. Depends on: nothing. This slice runs the FULL harness loop as
the trial run (HARNESS section 6); judge the harness on it, record the retro
in HARNESS.md's changelog before fanning out.

Tracer bullet: the foundation everything else calls: hashing, the one write
primitive, object put/get/has, the re-hash walk primitive (wrapped by the
slice 9 verify CLI), and the O_EXCL lock helpers.

## Work order (template from harness/prompts/implementer.md)

- SLICE: store module
- GOAL: make the slice-1 oracle tests pass with a stdlib-only object store
  whose identity is sha256 and whose only write path is tmp + os.replace.
- ORACLE TESTS: tests/test_store.py (all), tests/test_fences.py (stay green).
- CONTRACT EXCERPTS: DESIGN sections 1, 2, 13; DESIGN 14 rules R1, R2, R4,
  R14; FINDINGS F1, F2, F3, F9.
- ADJACENT BEHAVIORS: none yet (first slice). The write-primitive fence
  (tests/test_fences.py) already confines write handles to store.py and
  notify.py; every later slice calls store.atomic_write instead of opening
  files.
- TOUCHES: src/cc_warehouse/store.py only.

## Phase 2 decisions frozen in the tests

- objects/<hh>/<sha256>.jsonl sharding; put of an existing hash is a no-op
  with created=False.
- atomic_write: tmp file in the TARGET directory, exactly one os.replace,
  no litter on success, no final-path file on failure, old content intact on
  failed overwrite.
- Locks: locks/<name> created with O_EXCL, containing the holder's ASCII PID;
  acquire returns False while the recorded PID is alive, takes over when it
  is dead; release removes the file (sanctioned, DESIGN R4 closed list).
- get() of an unknown hash raises FileNotFoundError.

## Process

Loop per HARNESS section 2: implementer diff -> gates (uv run pytest,
uv run pyright, uv run ruff check) -> reviewers A+B in parallel on the green
diff -> operator triage -> fixer if needed (3-round limit). /tdd drives the
implementer against the already-merged oracle tests. Reviewers see the diff
plus the excerpts above only.
