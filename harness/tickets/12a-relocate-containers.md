# Ticket 12a: relocate, containers and registry

DONE 2026-07-23 (direct build, not the harness loop; principal chose Option 1). All five
carried-forward findings closed, one commit each, each with a contract-derived regression
test confirmed to FAIL against the pre-fix code first. Every finding was re-verified by
EXECUTION before being fixed, not taken from this ticket's description: two turned out to
be worse than written (see below), and a sixth was found that is on no ticket and has been
recorded on 12b. Commits 2ead0f6, f1e3866, 6f227be, 1da004b, 2f7a4ae. Gates: ruff clean,
pyright strict 0 errors, full suite 223 passed / 0 failed (was 215 before this slice; +8
regression tests). Zero stubs. All five oracle tests named below green. Independently
black-box re-probed outside the pytest suite: all five findings refuted.

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

From the ticket-12 escalation. ALL CLOSED 2026-07-23; each entry keeps its original
wording with the verified outcome appended, per the append-don't-rewrite record rule.

- The warehouse and source-transcript exclusions compare UNRESOLVED paths, so a symlinked
  root or a symlinked CCW_ROOT defeats them. Resolve before comparing.
  CLOSED 2ead0f6. Verified by execution first: with a symlinked CCW_ROOT a stored object
  became a rewrite target and its sha256 changed; with a symlinked `~/.claude` the run
  printed `rewritten: .../projects/<encoded>/capture.jsonl`, a live recurrence of the
  locked rule the escalation caught. Mechanism note for the record: `Path.rglob` does NOT
  descend symlinked dirs on Python 3.14, so the vector is the COMPARISON, not traversal -
  the walk holds the real path while the exclusion holds the link.
- HOME unset (cron, launchd) makes the source-transcript guard inert and the encoded-dir
  scan resolve to a relative path. Refuse rather than proceed blind.
  CLOSED f1e3866. UNDERSTATED as written: there is no relative path. `expanduser` still
  finds the home via `pwd`, so the scan rewrites real files while `_claude_projects`
  returns None, leaving zero encoded-dir candidates and no transcript guard. The dry-run
  printed "2 edits planned". Now refused at the CLI (before planning), in `_preflight`,
  and surfaced as a plan entry so the module API cannot slip past either.
- A `--to` whose parent is a regular file or a dangling symlink passes pre-flight and
  fails only at the rename. Pre-flight must prove the parent is, or can become, a dir.
  CLOSED 6f227be. UNDERSTATED as written: it does not merely fail at the rename. Contents
  are rewritten FIRST, so the run leaves memory files pointing at a path that can never
  exist. Both shapes reproduced (1 file rewritten each) before the fix.
- The plan is advisory: apply recomputes instead of consuming plan.edits, so consent is
  collected against a set that may differ from the one applied (R13/R14 plan-apply gap).
  CLOSED 1da004b. Reproduced: a file created after planning was rewritten unconsented.
  Fixed by making plan and apply share ONE enumeration (`_compute`, R9) and by requiring
  the point-of-action recompute to MATCH the plan, refusing on divergence rather than
  merging. The apply path now also PRINTS the plan before asking.
- The dry-run line counts SKIPPED entries as edits, and the success line counts them as
  changes.
  CLOSED 2f7a4ae. `RelocateEdit.skipped` is now typed, and `planned_changes` /
  `applied_changes` are the single source for both totals. Incidentally fixed: the
  halted-run report omitted `alias` from its change list.

## Findings found during 12a that do NOT belong to it

- relocate.py carries its own `[relocate].roots` TOML reader (`_relocate_roots`) while
  slice 13 gave `Config` a `relocate_roots` field: two implementations of one behaviour
  (R9/F8), drift created by slice 13 landing out of DESIGN-16 order. Confirmed by probe.
  It is a CONTENT-SCAN configuration concern, so it is recorded on ticket 12b rather than
  fixed here (principal ruling 2026-07-23, keeping the container/content split the
  section-4 escalation created).

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get diff +
excerpts + the ADJACENT list only. This slice inherits ticket 12's escalation lesson:
operator black-box verification runs BEFORE triage and is not a formality, and every
contract-derived regression test must be confirmed to FAIL against the pre-fix code.
