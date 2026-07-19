# Ticket 12a: relocate, containers and registry

Split from ticket 12 at the 2026-07-19 section-4 escalation (see 12-relocate.md for the
loop record and the diagnosis). Slice 12a of 13. Depends on: 02 (registry aliases),
04 (config subset), 10 (migrate.retire is the refuse-existing-target template).

Tracer bullet: `ccw relocate <repo> --to <new>` MOVES the repo and renames the
`~/.claude/projects` encoded dirs that are proven to belong to it, then records the move
in the registry. Dry-run is the default; `--apply` executes behind an explicit yes.
This slice does NOT rewrite the contents of any file (that is 12b).

Why the split: the escalated loop did not converge because one slice carried two
operations with different risk profiles and different contracts. Container work is a
small number of irreversible `os.rename` calls over paths the catalog can reason about.
Content work is an unbounded scan over arbitrary user-configured roots. Their pre-flight
checks, failure modes, and proofs of correctness have almost nothing in common, and
mixing them meant every fix to one surfaced a new hole in the other.

## Work order (template from harness/prompts/implementer.md)

- SLICE: relocate containers + registry
- GOAL: move the repo and rename only the encoded dirs PROVEN to belong to it, or refuse
  having changed nothing. Never rename a directory that might belong to another project.
- ORACLE TESTS: tests/test_relocate.py, the container and refusal cases
  (test_dry_run_is_the_default_and_changes_nothing,
  test_apply_refuses_a_non_empty_target,
  test_apply_without_yes_on_non_tty_aborts_untouched, and the container half of
  test_apply_moves_repairs_and_backs_up); plus the container cases in
  tests/test_relocate_regressions.py.
- CONTRACT EXCERPTS: DESIGN section 11 (including the 2026-07-19 boundary-rule
  CORRECTION and the scan-exclusion paragraph); DESIGN 14 rules R2, R4, R5, R10, R13,
  R14; FINDINGS F2, F4, F7, F9, F10; SPEC 10.2 with its 2026-07-19 correction note.
- ADJACENT BEHAVIORS: registry.move_project / project_for_path / cwds_for_encoded_dir /
  encode_cwd (the registry edit IS those functions, not new SQL), store.acquire_lock and
  release_lock, migrate.retire as the refuse-existing-target pattern, cli._consented.
- TOUCHES: src/cc_warehouse/relocate.py, src/cc_warehouse/cli.py, src/cc_warehouse/
  registry.py (TOUCHES expansion ruled by the principal 2026-07-19).

## Frozen decisions (principal, 2026-07-19; DESIGN section 15 records them)

- Cross-device is REFUSED outright: os.rename cannot cross filesystems and R4 sanctions
  no copy+delete, so there is no cross-device move to implement.
- The boundary rule is a filter, not a proof. A hyphen-remainder candidate is renamed
  only when the catalog attributes it to a cwd at or under the repo, or exactly one real
  directory encodes to that name and it lies under the repo. Unproven candidates are
  skipped and NAMED; `--claim-ambiguous` is the only way to take one, and it never takes
  a dir the catalog attributes to another project.
- Attribution reads EVERY cwd claim: claims are append-only, so a relocated project keeps
  its previous cwd row and a single row may be stale.
- The rename TOCTOU residual is accepted (stdlib has no RENAME_NOREPLACE); mitigation is
  a re-check at the point of action plus the locks/relocate O_EXCL lock.
- No automatic undo or resume. The journal and manifest are an operator record; pre-flight
  recognises an interrupted previous run and points at the backup dir.
- Order within apply: repo rename first, then encoded dirs, then the registry claim last
  (the one reversible, transactional step).

## Carried-forward findings this slice must close

From the ticket-12 escalation, still open in code:

- The warehouse and source-transcript exclusions compare UNRESOLVED paths, so a symlinked
  root or a symlinked CCW_ROOT defeats them. Resolve before comparing.
- HOME unset (cron, launchd) makes the source-transcript guard inert and the encoded-dir
  scan resolve to a relative path. Refuse rather than proceed blind.
- A `--to` whose parent is a regular file or a dangling symlink passes pre-flight and
  fails only at the rename. Pre-flight must prove the parent is, or can become, a dir.
- The plan is advisory: apply recomputes instead of consuming plan.edits, so consent is
  collected against a set that may differ from the one applied (R13/R14 plan-apply gap).
- The dry-run line counts SKIPPED entries as edits, and the success line counts them as
  changes.

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get diff +
excerpts + the ADJACENT list only. This slice inherits ticket 12's escalation lesson:
operator black-box verification runs BEFORE triage and is not a formality, and every
contract-derived regression test must be confirmed to FAIL against the pre-fix code.
