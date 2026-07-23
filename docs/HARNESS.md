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
10. migrate (+retire) -> 11. share + redaction -> 12a. relocate containers (repo move,
proven encoded-dir renames, registry claims) -> 12b. relocate content (memory and
inventory rewrites, backup, scan scope) -> 13. config + env + CLI polish. Each slice
ships with its oracle tests already merged, and no slice's work order may depend on a
later slice's code.

Slice 12 was ONE slice until the 2026-07-19 section-4 escalation split it (principal
ruling; tickets 12a and 12b, record on ticket 12). It carried two operations with
different risk profiles and different contracts: a small number of irreversible renames
over paths the catalog can reason about, and an unbounded content scan over arbitrary
user-configured roots. Every fix to one surfaced a hole in the other, so findings did not
converge across two review rounds. The double reviewer attention BRAINSTORM mandates for
relocate applies to BOTH halves. The split is also the standing worked example of the
section-4 diagnosis: when a loop will not converge, suspect the slice boundary first.

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
- 2026-07-18: /refresh hardened post-slice-01 (operator sweep of the command
  itself): red-reason classifier width-proofed (pytest truncates its short
  summary to the terminal width; the old probe binned unusable fragments),
  phase-note probe widened to the full section, a DONE-annotation probe added,
  and slice completion defined as a three-way agreement (dated ticket DONE
  line, zero stubs, green ticket tests) in Phase 3 and the deviation guard.
  README status prose moved off pre-implementation in the same sweep.
- 2026-07-18: Slice 02 (catalog + registry) COMPLETE through the full loop.
  Implementer diff green on first gate pass; reviewers A/B in parallel (A 6
  conformance findings, B 11 adversary) triaged into 9 clusters, all confirmed
  and fixed in 1 fixer round (limit 3). Fixes: one BEGIN IMMEDIATE / busy_timeout
  transaction discipline for every read-decide-write, add_session idempotent by
  content hash (U1); merge repoints alias claims onto keep, not just sessions, so
  a future capture at a merged path never resolves back to the retired row (U2);
  move_project raises instead of silent no-op on a claimed new_path or non-owned
  old_path (U3); version recency from payload last_ts, not warehouse capture
  order (U4); blank/whitespace cwd treated as absent, no catch-all label-'' bucket
  (U6); session/project/alias indexes plus a sargable short-key prefix range (U7);
  a single store.is_sha256_hex validator that catalog.add_session and
  store.object_path both call (U8, R9/F8); merge_projects id validation (U9).
  Split rulings: U3's encoded-form new_path claim DEFERRED to the cwd encoder
  (noted on tickets 04/12); B10 (captured_at format attack) REJECTED because our
  own capture generates captured_at, pinned at slice 4; U5 scoped to a docstring
  fix with the encoded_dir best-effort behavior kept (SPEC section 3, deliberate
  loss for lossy input). Operator verified all nine dispositions with black-box
  temp-dir probes (9/9), independent of the fixer self-report. Gates: 34 slice
  tests, pyright strict 0, ruff clean; full suite 96 red for the right reason.
- 2026-07-18: Slice 03 (parser + conversation model) COMPLETE through the full
  loop. Implementer diff green on first gate pass (13 oracle tests). Reviewers A/B
  in parallel (A 4 conformance, B 6 adversary; overlap 2, A1==B4 and A2==B3, so
  both lenses earned their seats: A uniquely caught the whitespace-summary hiding
  gap and the docstring overclaim, B uniquely caught the RecursionError crash, the
  BOM misroute, the isMeta type-truthiness, and the timestamp-order question).
  Operator triage: 8 clusters, 7 CONFIRMED, 1 REJECTED (C8 first/last-ts as
  file-order not chronological min/max: rejected because append-only JSONL makes
  file order chronological and the oracle test pins it; min/max would mask
  corruption and add scope). Principal confirmed the clusters and chose to add
  contract-derived regression coverage. Six operator-written oracle tests (from
  SPEC 6 / FINDINGS F6, not the code) pinned the silent-loss and crash classes red,
  then 1 fixer round (of 3) turned them green: a present-but-non-list loglines value
  counted not zeroed (C1); a valid-JSON non-object line counted skipped consistently
  across the JSONL and loglines paths, blanks still uncounted (C2); a whitespace-only
  summary falls to (no summary)/hidden (C3); RecursionError caught alongside
  JSONDecodeError at both parse sites so deep nesting never crashes (C4); a leading
  UTF-8 BOM stripped before routing via utf-8-sig (C5); the parse_session docstring
  softened off an unprovable "never misrouted" guarantee (C6, R8); isMeta honored
  only as boolean True (C7). Operator black-box verified 12/12 with fresh inputs in
  a temp dir, independent of the fixer self-report. The C2 accounting clarification
  landed on ticket 03 in the same commit as the code (HARNESS section 4). Fix the
  prompt: not needed this slice (implementer and fixer both honored their rules; no
  role misbehavior, so no prompt edit, recorded here as considered). Round count 1
  (target <= 2). Gates: 19 slice tests, pyright strict 0, ruff clean; full suite 83
  red for the right reason.
- 2026-07-18: Slice 04 (capture hook + notify) COMPLETE through the full loop.
  Implementer diff green on first gate pass (19 oracle tests: 14 capture + 5
  notify). Reviewers A/B in parallel (A 5 conformance, B 7 adversary) plus the
  sanctioned /code-review third lens (Standards + Spec). Operator triage: 12 raw
  findings clustered, each re-verified against the slice-1/2/3 code the diff-only
  reviewers could not see. 6 CONFIRMED and fixed in 1 fixer round (of 3): C1
  webhook POSTs moved OFF the hook critical path into a detached notify-only helper
  (DESIGN 12; a 3s sink no longer stalls the hook), C2 every sink best-effort with
  the render child spawned INDEPENDENT of notify (a log failure never suppresses
  rendering), C3 looped os.write against a partial-write torn log + honest R8
  docstring, C4 render-spawn best-effort (a Popen failure never emits a
  contradictory second error for a stored capture), C5 the SPEC-3 _unresolved rung
  stores a keyless capture rather than error-dropping it, C6 trimmed an unemitted
  action label. Two principal decisions at triage: C1 fixed now (not deferred to
  slice 8), C5 implemented now. 3 REJECTED, each refuted by adjacent code the
  reviewers were blind to: concurrent different-session project split (catalog
  BEGIN IMMEDIATE + busy_timeout serializes resolve_project), stale-lock poisoning
  (store.acquire_lock reaps dead-PID locks and capture self-completes), supersedes
  never built (add_session derives it; test_grown_transcript proves the link). 2
  accepted residuals: the add_session/record_event crash window (row + object
  survive so build renders from the catalog) and a missing-CCW_ROOT silent no-op
  (nowhere to log without a root; the slice-13 default root moots it). Operator
  black-box verified 21/21 in temp dirs independent of the fixer self-report,
  including the C1 off-path proof (hook returns 0.06s under a 3s sink; the POST
  still lands at +3.09s via the helper). Deferred to follow-ups: contract-derived
  regression tests for C1/C5/C2 (slice-03 precedent), the encoded-alias +
  registry.move_project claim (D1), desktop/voice sinks and full config layering
  (slice 13). Fix the prompt: not needed (implementer and both reviewers honored
  their rules; recorded as considered). Round count 1 (target <= 2). Gates: 19
  slice tests, pyright strict 0, ruff clean; full suite 60 red for the right
  reason. Post-slice hardening (principal chose to add): 3 contract-derived
  regression tests (tests/test_capture_regressions.py: C1 off-path via a blocking
  sink, C5 _unresolved stored-not-dropped, C2 best-effort broken log), full suite
  now 85 passed. Deferred to follow-ups: the encoded-alias + registry.move_project
  claim (D1), desktop/voice sinks and full config layering (slice 13). The absent
  slice-01 milestone tag (the tag-parity drift the /refresh self-improving guard
  anticipated) was backfilled at 75b9b68; tags now slice-01..04.

- 2026-07-18: Slice 05 (sweep) COMPLETE through the full loop. Implementer diff
  green on first gate pass (7 oracle tests); sweep reuses capture.capture_transcript
  verbatim per file (R9/F8), store.acquire_lock/release_lock for a locks/sweep lock
  (R14), and reports.BatchReport/ItemOutcome (the shared batch shape migrate slice 10
  reuses). Reviewers A/B in parallel (A 2 conformance, B 4 adversary) plus the
  /code-review Standards+Spec third lens. Operator verified every finding
  (Guardrail 9) with empirical probes for the two load-bearing ones: rglob silently
  drops an unreadable subdirectory (proven), and the store's dot-prefixed
  atomic-write tmp is not orphan-adoptable (proven, refuting a torn-write finding).
  Triage: 7 clusters, 3 CONFIRMED + fixed in 1 fixer round (of 3), 4 REJECTED. C1
  (R5/F7): os.walk(onerror) replaces rglob so an unreadable source subdirectory is a
  named failure with a non-zero exit, never a silent under-capture. C2 (R5): a
  malformed --source fails conservatively instead of sweeping the default tree; the
  =form is supported. C3 (R8-spirit): lock-held is a distinct refusal action, not a
  phantom batch item. Rejections (recorded): C4 orphan filename-vs-content = ccw
  verify's domain (slice 9); C5 cwd=None attribution refuted (capture resolves from
  the source path); C6 in-progress two-rows = intended supersedes
  (test_grown_transcript); C7 swept-no-render = batch tool, render is build's
  incremental job. D1 (forward cwd encoder + registry.move_project claim) confirmed
  as a follow-up, does not ride slice 5 (principal). 3 contract-derived regression
  tests added (tests/test_sweep_regressions.py, cited on ticket 05). Operator
  black-box verified 31/31 in temp dirs independent of the fixer self-report. Fix
  the prompt: not needed (implementer, both reviewers, and fixer honored their
  rules; recorded as considered). Round count 1 (target <= 2). Gates: 11
  slice+regression tests green, pyright strict 0, ruff clean; full suite 55 failed /
  94 passed, red for the right reason. Ops note: the Engineer implementer/fixer ran
  in a git worktree; the deliverable was replayed onto the main tree and the
  ephemeral worktrees removed before commit. Milestone tag slice-05 at completion.

- 2026-07-18: Slice 06 (transcript.md emitters, full + compact) COMPLETE through the
  full loop. Implementer green on first gate pass (8 oracle tests); adds the normalized
  conversation model (turns/typed blocks, reminder split) to parser.py plus a single
  policy-parameterized markdown emitter to render.py (full and compact from one _render
  core + _Policy, no F8), reusing extract_text/detect_commits/detect_github_repo and a
  new shared _extract_entries routing (parse_session refactored, 19 parser tests still
  green). Reviewers A/B in parallel plus /code-review Standards+Spec; unlike slices
  01-05 this slice had REAL bugs and the two lenses converged hard. Operator verified
  every finding with a white-box probe. Triage: after principal confirmation, 5
  CONFIRMED clusters + a tool-coverage add fixed in 1 fixer round (of 3): C-TURN (the
  SPEC-8 <-prefix + a substring task-notification search had leaked into SPEC-6
  turn-starting, demoting real prompts to machinery; both removed, only a whole-message
  task-notification/stop-hook/isMeta/empty is machinery), C-FENCE (fence-aware
  orphan-strip + a safe-fence helper so arbitrary tool/thinking/reminder content
  containing a code fence cannot break out, and a balanced nested fence is never
  corrupted), C-REMINDER-LEAK (an unknown reminders_* value fell open and leaked the
  reminder; now fails closed, F7), C-TOOLRESULT-LOSS (a commit tool_result dropped its
  other text; now keeps both, F6), C-R8 (honest docstrings + proving tests for
  determinism and pre-first-prompt preservation), C-TOOLCOVERAGE (Write/TodoWrite/Edit
  replace_all specialized per SPEC 7, which slice-7 copy-as-md depends on). Rejected: A5
  (refuted: ParsedSession.session_uuid + the (no summary) sentinel verified present), B8
  (resolved by C-TURN). Accepted edges (documented): C-USERLIST, promptless-session
  compact. 10 contract-derived regression tests added (tests/test_render_md_regressions.py,
  cited on ticket 06). Operator black-box verified 18/18 on the six clusters independent
  of the fixer self-report. Ops note: the Engineer implementer/fixer ran in auto-created
  worktrees; the deliverable was landed on the main tree and the worktrees removed before
  commit (the slice-05 lesson, instructed up front this time). Fix the prompt: not needed
  (roles honored their rules; recorded as considered). Round count 1 (target <= 2). Gates:
  37 slice+regression+parser tests green, pyright strict 0, ruff clean; full suite 47
  failed / 112 passed, red for the right reason. Milestone tag slice-06 at completion.
  Next: ticket 07 (HTML emitters + manifest).

- 2026-07-19: Slice 07 (HTML emitters full + compact, + manifest) COMPLETE through the
  full loop. Implementer green on first gate pass (9 oracle tests); render.py only. The
  HTML reuses the slice-6 markdown fragments as the copy-as-md single source of truth
  (base64 data-copy-src == a byte-exact transcript.md fragment, R9/F8), adds an in-house
  stdlib markdown-to-HTML renderer, content-hashed unique anchors (fixing the specimen
  make_msg_id collision), commit-card links, and a manifest wiring the conversation-model
  counts + store.sha256_hex; render_markdown stayed byte-identical (18 slice-6 md tests
  green). Reviewers A/B in parallel plus /code-review Standards+Spec; like slice 06 this
  slice had REAL bugs and the lenses converged. Operator verified the load-bearing
  findings with white-box probes. Triage: after principal confirmation, 5 CONFIRMED
  clusters fixed in 1 fixer round (of 3): C-PASSTHROUGH (the md-to-HTML passed
  <details>/<summary> through unescaped for USER text -- a "<details>" prompt broke the
  page, reachable since the slice-6 C-TURN fix made <-prefixed prompts real conversation;
  fix is provenance-based, structural HTML only for emitter-authored fragments, F6),
  C-SHA-DUP (anchor hashing now reuses store.sha256_hex, R9), C-COMMIT-REPO (a multi-repo
  session mislinked a sha to the first repo; now links to its own result's repo, F6),
  C-CDN-COUNT (dropped the second external cdnjs reference, the theme CSS, to honor
  DESIGN-6's ONE permitted external reference), C-R8-DOCSTRING (docstrings name their
  proving tests). Deferred (principal): the exporter visual chrome (collapsible turns,
  sticky toolbar, width/font toggles, research phases, Catppuccin palette) -- not
  oracle-required, later polish. Accepted: the _turn_html/_render_turn walk duplication
  (fragments shared, no markdown drift). Rejected: C-RENDER-LOSS (manifest loss = the
  frozen skipped_lines key). 6 contract-derived regression tests added
  (tests/test_render_html_regressions.py, cited on ticket 07). Operator black-box
  verified 10/10 on the five clusters independent of the fixer self-report; copy-as-md
  byte equality reconfirmed (13 payloads). Ops note: the Engineer implementer/fixer ran
  in auto-created worktrees; the deliverable landed on the main tree (the fixer via a
  controlled exact-match apply script) and the worktrees were removed before commit; the
  operator regression file was ruff-clean before the fixer round (the slice-06 lesson).
  Fix the prompt: not needed. Round count 1 (target <= 2). Gates: 58 render/parser/fence
  tests green, pyright strict 0, ruff clean; full suite 38 failed / 127 passed, red for
  the right reason. Milestone tag slice-07 at completion. Next: ticket 08 (build/render
  orchestration).

- 2026-07-19: Slice 08 (build/render orchestration; un-stubs the render child) COMPLETE
  through the full loop. Implementer green on first gate pass (6 in-scope build + 2
  render-adhoc oracle tests). One shared projection-writing routine + dir-path function
  serve build, `ccw render --session`, and ad-hoc `ccw render <path>` (R9); catalog-driven
  selection (R6); content-compare incremental (F1-safe); disposable-by-construction prune
  (the sanctioned R4 deletion in build.py); every write via store.atomic_write (R2 fence);
  `ccw project rename` wires the existing registry.rename_project (operator expanded
  TOUCHES for the label-rename test). Un-stubbing the render child kept the slice-4
  capture suite green. Reviewers A/B in parallel plus /code-review Standards+Spec; this
  slice had REAL bugs and the lenses converged, headlined by a PERMANENT data-loss path.
  Operator verified the load-bearing findings with white-box probes (B1: a failed head's
  build pruned the last-good dir to zero -> verified). Triage: after principal confirmation,
  6 CONFIRMED clusters + C-CHILD-NOTIFY fixed in 1 fixer round (of 3): C-PRUNE-LOSS (prune
  only on a clean build, F7/F9), C-PRUNE-CRASH (best-effort prune, R5), C-BUILD-LOCK
  (locks/build O_EXCL, R14/DESIGN-13), C-ADHOC-GUARD (--out under objects/projections
  refused, F9), C-RENAME-NOID (unknown id errors, F7), C-RENDER-HEAD (render --session
  projects only a head via a shared query, R9), C-CHILD-NOTIFY (the child notifies error
  + opt-in folder reveal, DESIGN-4). Rejected: A1 rename-no-commit (refuted -- rename_project
  commits via writing(); the oracle test passes). Accepted: C-HIDDEN-CHURN (by design),
  the "N built" cosmetic miscount. Documented residual: the build-vs-detached-child
  stale-snapshot race is regenerable (the next build reconciles). 5 contract-derived
  regression tests added (tests/test_build_regressions.py, cited on ticket 08). Operator
  black-box: 25/27 real-subprocess checks + a CLEAN 6/6 catalog-seed re-verify (the 2
  non-green were the async render child racing the probe, not code bugs). Ops note: the
  Engineer implementer/fixer ran in auto-created worktrees; the deliverable landed on the
  main tree and the worktrees were removed before commit; the operator regression file
  was ruff-clean before the fixer round. Fix the prompt: not needed. Round count 1
  (target <= 2). Gates: 6 build + 5 regression + capture + fences green, pyright strict 0,
  ruff clean; full suite 30 failed / 140 passed, red for the right reason. Milestone tag
  slice-08 at completion. Next: ticket 09 (status + ccw verify).

- 2026-07-19: Slice 09 (status + ccw verify CLI) COMPLETE through the full loop.
  Implementer green on first gate pass (6 status_verify + the F5
  test_recent_listing_opens_zero_stored_payloads, the one build test slice 8 left red).
  status reads the catalog only (F5/R6: counts + SUM(size_bytes) + last errors, zero
  object opens); verify WRAPS store.verify_walk (R9, no re-implemented hashing) and
  cross-checks the catalog against the objects in BOTH directions -- corrupted,
  orphan-reported-never-deleted, and the missing-object direction the walk cannot see (a
  catalog hash with no object) -- read-only (R4). status.py stays out of the write/delete
  fence sets. A CLEAN slice: Reviewer A found no findings; the two-lens value came from
  Reviewer B + /code-review. Operator verified the one real edge with a probe. Triage: 2
  CONFIRMED clusters fixed in 1 fixer round (of 3): C-VERIFY-CRASH (verify crashed on a
  malformed/NULL catalog session.hash -- non-hex ValueError, NULL TypeError in sorted() --
  suppressing every finding on exactly the suspect store it inspects; now validates each
  hash before store.has and reports a malformed row, report-and-continue, F7/R5),
  C-UNREADABLE-LABEL (an unreadable object is now labeled "unreadable", not a content
  mismatch, R8-spirit). Refuted: B3 (the "bytes stored" dedup double-count -- session PK
  is the hash, one row per object, SUM accurate), B5 (nondeterministic order --
  verify_walk yields in sorted path order). Accepted: litter not surfaced (out of scope),
  the logical store-size label, and the ext=".jsonl" missing-direction asymmetry (a v1.1
  follow-up for web_export). 3 contract-derived regression tests added
  (tests/test_status_verify_regressions.py, cited on ticket 09). Operator black-box
  verified 7/7 via real ccw subprocesses + a re-probe of the crash fix. Ops note: the
  Engineer implementer/fixer ran in auto-created worktrees; the deliverable landed on the
  main tree and the worktrees were removed before commit; the operator regression file
  was ruff-clean before the fixer round. Fix the prompt: not needed. Round count 1
  (target <= 2). Gates: 6 oracle + 3 regression + 7 build + 6 fences green, pyright strict
  0, ruff clean; full suite 24 failed / 149 passed, red for the right reason. Milestone
  tag slice-09 at completion. Next: ticket 10 (migrate + retire).

- 2026-07-19: Slice 10 (migrate + retire) COMPLETE through the full loop.
  Implementer green on first gate pass (6 oracle tests); migrate reuses
  capture.capture_transcript verbatim per file (R9/F8, zero capture logic), hash
  dedupe collapses duplicate archive copies for free (F1), reports.BatchReport, and
  store.atomic_write for the <root>/logs/migrate-manifest.json per-file manifest (R2).
  Reviewers A/B in parallel (A 3 conformance, B 2 adversary; overlap 1: both lenses
  caught the non-regular-file silent drop, A via R5/R10 and B via F7/F6, so both
  earned their seats). Operator verified every finding with a fresh black-box probe
  (Guardrail 9) BEFORE triage: the os.rename empty-target clobber and the DESIGN-13
  migrate-lock requirement were the two load-bearing ones. Triage: 3 clusters, all 3
  CONFIRMED, 0 rejected, fixed in 1 fixer round (of 3): C1 (F7/R10) a *.jsonl dirent
  that is not a regular file (dangling/looping symlink, FIFO, socket, device) is now a
  NAMED error item in both the BatchReport and the manifest instead of a silent
  is_file() drop, and is never handed to capture (reading a FIFO named *.jsonl would
  block migrate forever - the fixer was warned of the trap up front); C2 (R4/F9)
  retire refuses a pre-existing target (new_path.exists() or is_symlink()) rather than
  let os.rename SILENTLY remove an existing empty _RETIRED_ dir (a delete outside R4's
  closed list, probe-confirmed) or raise an uncaught OSError on a non-empty one, with
  the CLI catching OSError for a clean report-not-crash message (R5); A1 (R14/DESIGN
  13) migrate now holds a locks/migrate O_EXCL lock mirroring sweep - DESIGN 13 line
  305 names migrate a lock-taker, so two concurrent runs can no longer race the shared
  manifest (last-writer-wins); a live holder is a distinct non-counted refusal.
  Locked principal decision D1 (asked before planning): `migrate --retire` = consent +
  the single rename ONLY, no import (DESIGN 10 "a separate explicit step"); plain
  migrate imports only. 3 contract-derived regression tests added
  (tests/test_migrate_regressions.py, cited on ticket 10). Operator black-box verified
  6/6 in temp dirs independent of the fixer self-report (dangling symlink reported +
  sibling still imports, FIFO no-hang under a 10s timeout, empty + non-empty retire
  target both refused-and-preserved, happy retire renames, lock-held refuses with no
  manifest/import). Ops note: both the Engineer implementer and fixer ran in
  auto-created worktrees; the deliverable was landed on the main tree via a controlled
  exact-match Write and the worktrees + branches removed before commit (the slice-05
  lesson); the operator regression file was ruff-clean before the fixer round. Fix the
  prompt: not needed (implementer, both reviewers, and fixer honored their rules;
  recorded as considered). Round count 1 (target <= 2). Gates: 6 oracle + 3 regression
  green, pyright strict 0, ruff clean; full suite 20 failed / 156 passed, red for the
  right reason. Milestone tag slice-10 at completion. Next: ticket 11 (share +
  redaction).
- 2026-07-19: Slice 11 (share + redaction) COMPLETE through the full loop. Implementer
  green on first gate pass (4 oracle tests). The load-bearing design choice, verified
  against render.py before coding: redaction runs on the payload BEFORE the shared
  renderer, because the HTML emitter base64-embeds each block's raw markdown in a
  data-copy-src, so post-render text redaction would pass the oracle yet leak every
  secret through the copy path. Reviewers A/B in parallel (A 5 conformance, B 9
  adversary). Operator verified every finding against the code before triage (Guardrail
  9): 10 CONFIRMED, 3 REJECTED. Two reviewer findings shared a false premise worth
  recording: both A1 and B6 asserted `write_projection(force=True)` invokes build's
  prune and could delete files under --out; a direct read of build.write_projection
  (mkdir + _write_if_changed only; _prune is a separate function it never calls) refuted
  the deletion claim, so the "prune" framing was rejected while the real residual (an
  export overwriting files in an unrecognized populated --out) was fixed with a CLI
  refusal guard. The confirmed cluster, fixed in 1 fixer round (of 3): B1 (F6) the leak
  core - redaction and secret detection moved to the json-DECODED content so a
  \uXXXX-escaped or non-ASCII secret/PII cannot slip past raw-text matching and reappear
  decoded in the share (incl. the base64 copy-src, the exact vector the oracle grep does
  not decode); B5 (F9) a hostile payload timestamp cannot escape --out (validate first_ts
  + reuse build.projection_dir); A2/A5 (R9/F8) reuse build.projection_dir + stdlib
  html.escape rather than hand-rolled copies (pyright strict reportPrivateUsage forbids
  importing render._escape / build._component, and the codebase never crosses that
  boundary, so the canonical stdlib/public forms are used); A3 (R5/F7) an I/O read/write
  failure is a named error, not a benign not-found; B2/B4 the pure-hex secret carve-out
  narrowed to git/sha digest lengths and the generic detector extended to base64url; B7
  (F7) a zero-width custom regex is inert (no corruption; ReDoS on user regex stays a
  documented unbounded risk, stdlib re has no timeout); B9 word-boundary username/hostname
  redaction. Rejected with reasons: A4 (report is the frozen pattern/file/line/replacement
  schema and a constant [REDACTED] is REQUIRED - writing the removed value would leak it),
  B3 (current-env builtins match the frozen decision + oracle; per-origin identity is a
  later slice), B8 (broad-detector false positives are the accepted cost of the operator's
  broad choice, --allow-findings is the hatch). Locked operator decisions taken before
  the plan was finalized: explicit --out write-only (defer warehouse shares/ + rebuild),
  skip-and-continue on a bad short, broad secret heuristics, regex custom patterns. 9
  contract-derived regression tests (tests/test_share_regressions.py, cited on ticket 11).
  Operator black-box verified 17/17 in temp dirs independent of the fixer self-report,
  including base64 copy-src decode (no leak) and git-sha no-false-abort. Fix the prompt:
  not needed (all four roles honored their rules; recorded as considered). Round count 1
  (target <= 2). Gates: 4 oracle + 9 regression green, pyright strict 0, ruff clean; full
  suite 16 failed / 169 passed, red for the right reason (test_cli 4 + test_config 9 are
  slice-13, test_relocate 3 is slice-12). Milestone tag slice-11 at completion. Next:
  ticket 12 (relocate).

- 2026-07-19: Slice 12 (relocate) ESCALATED under section 4, NOT done, no milestone tag;
  full record on ticket 12. The first non-converging loop of the build: round 1 produced
  27 findings (22 clusters confirmed, 1 rejected), round 2 produced 21 MORE, five of them
  defects the round-1 fixes had introduced or missed. The operator escalated after fixer
  round 2 rather than spend the third round, on the grounds that the trend (22 then 21)
  was the signal the limit exists to detect. Three process lessons worth carrying:
  (a) OPERATOR VERIFICATION EARNS ITS SEAT INDEPENDENTLY OF THE REVIEWERS. The black-box
  probe caught a locked-rule violation both reviewers missed and the round-1 fix itself
  had introduced (relocate was content-rewriting captured transcripts, against BRAINSTORM's
  "source transcripts are never modified by anything, ever" and SPEC 10.2). A green diff
  plus two clean-ish reviewer tables is not evidence; running the thing is.
  (b) A REGRESSION TEST THAT PASSES BEFORE THE FIX PINS NOTHING. All five tier-1 pins were
  run against the pre-fix code and required to FAIL first; one of them passed both ways,
  proving it did not exercise the bug at all, and was replaced with one that does. Adopt
  this as standing practice for contract-derived regression tests.
  (c) THE OPERATOR'S OWN RECOMMENDATION NEEDS THE SAME SCRUTINY AS A REVIEWER'S. The
  round-1 encoded-dir fix was recommended over the principal's stated preference on the
  reasoning that forward encoding is exact; round 2 proved `<repo>/two` and `<repo>-two`
  encode identically, so the proof proved the wrong proposition. Verify what you advocate,
  not only what you are shown.
  Section 4 diagnosis: bad slice boundary AND contract silence. Relocate bundles content
  rewriting across arbitrary user roots with container renaming, and DESIGN section 11 is
  silent on several rules the implementation must invent (JSON key handling, the encoded-
  form content rule, file-mode preservation, scan scope). Recommended restart: split the
  two operations and land the contract clarifications first.
- 2026-07-19: Architecture-review board added at cc-warehouse-architecture/ (SOURCE.md
  canonical, index.html rendered by the new .claude/commands/architecture.md; adapted from
  a sibling project's pattern the principal shared read-only, commit 17ef206). Process
  relevance: reviews feed the board, the board proposes deepening candidates, grilling and
  tickets decide; the contract stays with the principal, and the board never edits docs/.
  The folder is outside /refresh's sweep scope by single ownership (/refresh's file map
  updated to record that this run). Same-day /refresh sweep: gates ruff green, pyright
  strict clean, suite 13 failed / 195 passed all slice-13 (7x CCW_ROOT ValueError from the
  partial loader naming its pending slice, stub-CLI usage/exit assertions), red for the
  right reason; zero stubs; DONE 01-11 with tag parity; ticket-11's completion tail gained
  a dated superseded-note pointing at 12a (the split postdates that annotation).
- 2026-07-23: Direct-build era (principal chose Option 1 over the harness loop for
  interactive render work), all verified against ONE operator-scoped read-only session.
  Two process lessons worth carrying. (a) AUDIT BY STRUCTURE, NOT SUBSTRING. The exporter-
  chrome / entry-type render work shipped a 94-check "audit" that only tested string
  PRESENCE; it passed while the HTML had NO Claude sections and Claude's tool phases were
  nested inside the user block. A parsing audit (nesting invariants, role-section counts
  against the model, payload-in-md checks) replaced it and caught three real defects the
  presence audit could not see. The operator caught the original miss. (b) CENSUS THE DATA,
  NOT JUST THE LAYOUT. Round after round of "looks right vs the exporter" kept missing
  gaps because nothing censused the SOURCE format; a 400-session field census (615 keys,
  13 entry types) showed the render consumed only 2 of 13 types, including dropping the
  session's own ai-title. Both are the same failure the verification-discipline memory
  names: confidence must not exceed verification coverage, and a lower-bound instrument
  (grep / presence) must not be reported as a census. Slice 13 (config + CLI + flags +
  --EXPOSED) then built directly, oracle suite green, 7 contract-derived regression tests,
  each flag proven through the real CLI against the scoped session; v1 exit review with the
  principal followed, and the contract docs were reconciled to the approved decisions in the
  same review (this doc sync).
- 2026-07-23: Slice 12a (relocate containers + registry) COMPLETE by direct build, the
  first half of the escalated slice to converge. Five carried-forward findings closed, one
  commit each (2ead0f6, f1e3866, 6f227be, 1da004b, 2f7a4ae), 8 contract-derived regression
  tests; gates ruff clean / pyright strict 0 / suite 223 passed / 0 failed; zero stubs; all
  five ticket-12a oracle tests green; independently black-box re-probed outside the suite.
  Four process lessons, all sharpening rules this document already carries:
  (a) A TICKET'S OWN FINDING LIST IS EVIDENCE, NOT A CENSUS. Every finding was re-derived by
  EXECUTION against a synthetic probe world before being fixed. Two of the five were
  materially understated (HOME-unset produces no relative path but a silently half-guarded
  run; a bad `--to` parent does not merely fail at the rename, it rewrites contents first
  and leaves them pointing at a path that can never exist), and a SIXTH finding existed on
  no ticket at all. Had the fixes been written from the ticket text, two would have been
  aimed at the wrong mechanism.
  (b) THE MECHANISM CAN BE THE OPPOSITE OF THE ASSUMED ONE. The symlink findings were
  assumed to be about traversal following links. `Path.rglob` does NOT descend symlinked
  directories on Python 3.14, so the walk reaches the real path while the exclusion holds
  the link: a COMPARISON bug. A traversal-shaped fix would have shipped green tests over a
  live R4/F9 violation, which is the slice-12 lesson (c) in a new costume.
  (c) THE RED CHECK MUST BE PERFORMED, NOT REASONED ABOUT. Two assertions were verified red
  by temporarily removing the specific guard and re-running, not by arguing they must fail.
  One of them was an R8 overclaim the operator had introduced in the PREVIOUS commit of this
  same slice (a docstring promising the module API could not bypass the HOME guard, while
  `plan_relocate` could), caught only because the independent probe disagreed with the
  pytest suite. Two instruments beat one.
  (d) WHEN A TEST AND THE CODE DISAGREE, THE TEST CAN BE THE WRONG ONE. A first-draft
  assertion cross-compared the plan count against the apply count; the code was right and
  the test was wrong, because DESIGN 11 enumerates external-world REPAIRS, so the repo move
  is the header line and not a plan edit. Recorded because the reflex under time pressure is
  to "fix" the code.
  Scope discipline held: the `rglob` -> `os.walk` restructure, the silent-drop reporting and
  the parallel config loader were all left to 12b rather than merged back into 12a, since
  re-merging the two halves is precisely what the section-4 escalation split apart.

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
