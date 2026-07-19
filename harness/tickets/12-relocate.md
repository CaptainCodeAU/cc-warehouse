# Ticket 12: relocate (SUPERSEDED 2026-07-19 by 12a + 12b)

RE-SCOPED. This ticket is kept for its loop record and its escalation diagnosis; the
work itself is now split into `12a-relocate-containers.md` (repo move, encoded-dir
renames, registry claims) and `12b-relocate-content.md` (memory and inventory content
rewriting, backup, scan scope). The split IS the section-4 remedy: the loop did not
converge because one slice carried two operations with different risk profiles and
different contracts, so every fix to one surfaced a hole in the other.

The landed implementation (43432e4, edb5268, 4241c45) and its 20 regression tests stay
on master as a working checkpoint. They are not DONE and carry no milestone tag; 12a and
12b each list the findings still open in that code as work they must close.



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

## IN PROGRESS 2026-07-19 - ESCALATED (HARNESS section 4)

NOT done. Gates are green and the implementation is landed and pushed (43432e4,
edb5268, 4241c45), but the review loop did not converge and the operator escalated
early rather than spend the third round. No milestone tag.

Loop record. Round 1: 27 findings (12 conformance + 15 adversary), 22 clusters
confirmed, 1 rejected (encode_cwd R9: verified no earlier encoder exists, capture
reads transcript_path.parent.name and never encodes). Fixer round 1 landed all 22.
Operator verification then caught a defect BOTH reviewers missed and the round-1 fix
had introduced: relocate was content-rewriting captured transcripts, violating the
locked "source transcripts are never modified by anything, ever" and SPEC 10.2
("nothing outside the memory roots is ever string-edited; dirs are renamed instead").
The F1 static fence separately caught a stat().st_size comparison; the CODE changed
to a bounded read, never the test. Round 2: 21 findings, FIVE of them defects the
round-1 fixes introduced or missed. Fixer round 2 landed only those five (tier 1),
each pinned by a regression test confirmed to FAIL against the pre-fix code:
contested-sibling encoded proof, every-cwd-claim attribution, JSON path KEYS,
verify-follows-moved-targets, and content refs to dirs the run itself renames.

Diagnosis per section 4 (bad slice boundary or contradictory contract line): BOTH.
The slice bundles two operations with different risk profiles and different contracts
- rewriting content across arbitrary user-configured roots, and renaming containers -
and DESIGN section 11 is silent on several decisions the implementation is forced to
make. Findings did not converge (22 then 21) because each fix had to invent an
unstated rule. A re-scope that splits container renaming from content rewriting, plus
the contract clarifications below, is the recommended restart.

Operator decisions taken during the loop (do not relitigate): TOUCHES expanded to
registry.py; cross-device refused; content atomicity = pre-flight then per-file
atomic_write; TOCTOU residual accepted (stdlib has no RENAME_NOREPLACE); no automatic
undo or resume, the journal and manifest are an operator record; backup narrowed to
destructively-rewritten files; encoded-dir policy is prove-then-rename with
--claim-ambiguous as the opt-in.

OUTSTANDING for the principal, not addressed in code (tier 2, real and verified):
- store.atomic_write is mkstemp + os.replace and does NOT preserve the target's mode,
  so every rewritten memory file comes back 0600 and an executable loses +x. Fixing it
  means changing store.py, used by every slice; needs a principal decision.
- The warehouse and source exclusions compare UNRESOLVED paths, so a symlinked root or
  CCW_ROOT defeats them and stored objects become rewrite targets again.
- HOME unset (cron/launchd) makes the source-transcript exclusion inert.
- Path.read_text() is locale-dependent, so a non-UTF-8 locale writes mojibake AND backs
  up the same mojibake, leaving no recoverable pre-image.
- A --to whose parent is a regular file or dangling symlink passes pre-flight, then
  fails after every content file has been rewritten.
Tier 3 (reporting and design): the plan is advisory because apply recomputes rather
than consuming plan.edits, so consent is collected against a set that may differ; the
dry-run and success lines count SKIPPED entries as edits/changes; JSON rewriting
reformats the whole file, destroying hand-maintained layout; roots are fully scanned
twice per apply.
