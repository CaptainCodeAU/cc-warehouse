# HARNESS - how cc-warehouse gets built (and how the process itself is judged)

**Status:** Phase 1 contract document, 2026-07-17. Learning this harness is an explicit
goal EQUAL to shipping the product (handoff lock). Method: the scaled-down Bun-rewrite
process (bun.com/blog/bun-in-rust): contract docs first, black-box oracle tests before
implementation, small loops of specialized roles, a trial run before scaling, and
fix-the-prompt-not-the-code. Role prompts live in `harness/prompts/` and are the ONLY
instructions the role agents receive beyond their inputs.

---

## 1. The roles (one loop = 4 agents)

| Role | Prompt file | Sees | Produces |
|---|---|---|---|
| Implementer | `harness/prompts/implementer.md` | the work order (one module/feature slice), SPEC/DESIGN/FINDINGS excerpts for it, the oracle tests for it, existing repo code | a diff that makes the oracle tests pass under the gates |
| Reviewer A (conformance) | `harness/prompts/reviewer-conformance.md` | the DIFF ONLY + the same excerpts; told to assume the code is wrong | a findings table: rule violations (DESIGN section 14 by number), spec mismatches, test gaps |
| Reviewer B (adversary) | `harness/prompts/reviewer-adversary.md` | the DIFF ONLY + FINDINGS.md; told to assume the code is wrong | a findings table: concrete failure scenarios (crash timing, concurrency, malformed input, filesystem errors) with reproduction sketches |
| Fixer | `harness/prompts/fixer.md` | the diff + BOTH findings tables + the excerpts | a revised diff addressing every CONFIRMED finding, or a written rejection per finding |

Diff-only context for reviewers is deliberate: they cannot rationalize code from its
surroundings, so they judge what changed on its own merits. Two reviewers with
DIFFERENT lenses (rules vs sabotage) catch different failure modes; identical reviewers
would just vote twice.

## 2. The loop

```
work order (one slice)
  -> Implementer produces diff
       (or a written OBJECTION to a test/contract line -> operator triage, below)
  -> GATES run mechanically: uv run pytest (oracle suite) + pyright --strict + ruff
       any gate red -> back to the diff's AUTHOR (implementer, or fixer in fix
       rounds; a gate-red fixer round counts toward the limit). No review of red code.
  -> Reviewers A and B run IN PARALLEL on the green diff
  -> Findings triage (the operator session): each finding CONFIRMED or REJECTED
       with a one-line reason; rejections are recorded, not silently dropped
  -> zero confirmed findings -> slice DONE, commit
  -> else Fixer produces revised diff -> back to GATES
       Fixer may return a written rejection of a confirmed finding; rejections go
       BACK TO OPERATOR TRIAGE: accepted rejection = finding closed; overruled =
       it returns to the fixer and the round counts.
  -> loop limit: 3 fix rounds per slice; hitting the limit = STOP, escalate (section 4)
```

The gates are not the review. Gates catch mechanical failure; reviewers catch wrongness
that type-checks. A slice is DONE when gates are green AND every reviewer finding is
either fixed or carries an operator-accepted rejection. Implementer objections and
fixer rejections both resolve at operator triage; nothing self-arbitrates.

## 3. Fix the prompt, not the code

When a role produces bad output (implementer ignores a rule, reviewer flags noise,
fixer papers over instead of fixing), the operator does NOT hand-edit the artifact.
The fix goes into the ROLE PROMPT (or the work order template), and the role reruns.
Hand-editing outputs destroys the harness's ability to improve: the same failure
returns on the next slice. Every prompt edit gets a dated line in the prompt file's
own changelog footer, so prompt evolution is visible history. The exception: trivial
mechanical slips (a typo in a comment) may be fixed by the Fixer role in the normal
loop; never by silent operator edits.

## 4. Escalation

- A slice that hits the 3-round loop limit stops the line. The operator re-reads the
  work order: 90% of stuck loops are a bad slice boundary or a contradictory contract
  line. Fix the order or the contract doc (with the principal if it changes a locked
  decision), then restart the slice fresh.
- Reviewers disagreeing with each other is NOT escalation; both tables go to triage.
- A confirmed finding that reveals a CONTRACT defect (SPEC/DESIGN/FINDINGS wrong or
  silent) always patches the contract doc in the same commit as the code fix, and
  adds an oracle test if the defect class is testable.

## 5. Oracle tests (Phase 2, before any implementation)

- Written from SPEC (KEEP behaviors), DESIGN (new behaviors + section 14 rules), and
  FINDINGS (impossibility proofs: each F-rule's verification line becomes at least one
  test). NEVER ported from the specimen suite (it enshrines F1 as expected).
- Black-box: tests invoke `ccw` verbs and the public module API, assert on files,
  catalog rows, exit codes, and output; they do not import private helpers.
- The FINDINGS tests are the crown jewels: same-size-different-content dedupe refusal
  (F1), kill-mid-write torn-file absence (F2), N concurrent captures one row (F3),
  display-name collision two projections (F4), zero-jsonl-opens listing (F5),
  stat-failure conservatism (F7), source-tree read-only proofs (F9/migrate).
- Gates config (pytest + pyright strict + ruff) lands in the SAME commit as the first
  test file. The suite must be red-for-the-right-reason before implementation starts
  (missing implementation, not broken tests).

## 6. Trial run (before scaling to the main build)

One slice through the FULL loop: the **store module** (`atomic_write`, object store
put/get/has, hashing, and the re-hash WALK PRIMITIVE that `ccw verify` will later wrap;
the verify CLI itself is slice 9). Chosen because it is small, is the foundation
everything else calls, and exercises F1/F2/F9 tests directly.

Judge the HARNESS on the trial, not just the code:

- Did the gates catch anything reviewers then did not have to? (gates earn their keep)
- Did each reviewer produce at least one finding the other did not? (lenses differ)
- Was any finding fixed by editing a prompt rather than the artifact? (the mechanism
  works; if no prompt needed editing, fine, but record that it was considered)
- Round count to done (target: <= 2 fix rounds), and operator wall-clock feel.
- Output quality: would we ship the store module as-is?

Record the answers in `HARNESS.md`'s changelog (section 8). Only after the trial-run
retro does the main build fan out, slice by slice, in DESIGN section 16 order.

## 7. Slicing the main build (initial cut, revisable at each retro)

1. store (trial run) -> 2. catalog + registry -> 3. parser + conversation model (the
hook's metadata extraction lives here) -> 4. capture hook + notify (the render child
is a STUB until slice 8; its oracle tests assert the spawn contract, not the output)
-> 5. sweep -> 6. transcript.md emitters (full+compact) -> 7. HTML emitters
(full+compact) + manifest -> 8. build/render orchestration (un-stubs the child) ->
9. status + `ccw verify` CLI (wraps the slice-1 walk, adds catalog cross-check) ->
10. migrate (+retire) -> 11. share + redaction -> 12. relocate (plan/backup/apply/
verify/report; double reviewer attention per BRAINSTORM) -> 13. config + env + CLI
polish. Each slice ships with its oracle tests already merged, and no slice's work
order may depend on a later slice's code.

## 8. Harness changelog

- 2026-07-17: v1 of this document + the four role prompts written (Phase 1).
- 2026-07-17: Phase 1 adversarial coherence review (23 findings, all confirmed)
  applied: loop states for fixer rejections and implementer objections; red gates
  return to the diff's author; slices reordered so no work order depends on later
  code (parser before hook, render child stubbed until slice 8); verify split into
  walk primitive (slice 1) + CLI (slice 9); prompts bumped to v1.1. The harness
  reviewed its own contract before its first run, which is exactly the point.
- 2026-07-18: Phase 2 complete: repo bootstrap (license PolyForm Noncommercial
  1.0.0 per the principal; gates wired from commit one), the oracle suite (136
  tests: 124 red for the right reason, 12 by-design pre-implementation greens:
  6 fences + 6 negative invariants), and the 13 ticket files per sections 7/9.
  Gate note: the pyright CLI has no --strict flag; the strict gate runs as
  `uv run pyright` with typeCheckingMode=strict in pyproject (where this doc
  says "pyright --strict", read "pyright in strict mode"). Trial run not started.
- 2026-07-18: Trial run (slice 01, store) COMPLETE through the full loop, commit
  75b9b68: implementer diff green on first gate pass; reviewers A/B in parallel
  (A 4 findings, B 9, overlap 2: both lenses earned their seat); triage confirmed
  T1-T8, rejected T9 (parent-dir fsync: beyond the stated crash model); 1 fixer
  round to done (limit 3). The T3 contract defect (delete fence vs the
  release-removes-the-file frozen decision) was patched in the same commit as the
  code fix per section 4: function-scoped fence carve-out for store.py's O_EXCL
  lock helpers (principal decision at triage). Retro: gates made no unique catch
  but kept reviewers on green code; fix-the-prompt applied once (implementer
  rule 9 now demands an objection on contract-vs-contract conflicts, v1.2);
  /tdd not literally invoked, red-green followed procedurally. Accepted residual
  (operator): a theoretical ABA window in stale-lock takeover requiring three-way
  microsecond interleaving; revisit at slice 5 if sweep raises the stakes. Ops
  lesson: one writer per TOUCHES; confirm a lost-looking role spawn is dead
  before issuing a replacement (a duplicate implementer converged on store.py;
  no corruption, the second wrote nothing). Main build fans out per section 7.

---

## 9. External tooling (decided 2026-07-17: compose, don't replace)

The mattpocock-skills flow composes into this harness at fixed altitudes; it never
replaces the loop:

- Each section 7 slice is written as a tracer-bullet TICKET file in `harness/tickets/` (one file per slice,
  blockers-first order matching the slice numbering) so a fresh session picks up one
  ticket cold; the ticket embeds the work-order template from harness/prompts/implementer.md.
- `/tdd` (red-green slices) is the engine INSIDE the Implementer role, driving against
  the already-merged oracle tests.
- `/code-review` may run as an OPTIONAL third lens at slice close, after reviewers A/B
  are clear; its findings enter the same operator triage. It never substitutes for
  either reviewer.
- The outer loop, roles, gates, and fix-the-prompt policy in sections 1-4 are the law
  regardless of tooling.

---

**Operator quick reference.** New slice: write the work order (template in
`harness/prompts/implementer.md` header) -> run loop per section 2 -> triage -> commit on
green+empty -> retro notes here if the harness itself misbehaved -> next slice.
