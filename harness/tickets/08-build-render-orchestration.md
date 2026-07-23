# Ticket 08: build + render orchestration (un-stubs the render child)

EXIT-REVIEW ADDENDUM 2026-07-24 (principal ruled Option 2: build all four now). This
ticket wired `ccw project rename` and nothing else, and no ticket ever enumerated the
rest, so DESIGN section 7's `list / show / rename / move OLD NEW / merge A B` sat
1-of-5 implemented behind a green suite and a DONE annotation. The gap was invisible to
every slice-level check: the oracle suite was written from the tickets, the tickets from
the slice list, and the slice list never named the subcommands. A green suite proves the
code matches the tests, never that the tests cover the contract.
It was not cosmetic. DESIGN section 8 keys per-project config on
`[project.<registry-id>]` and names `ccw project show` as the way to obtain that id, so
the per-project override feature shipped in slice 13 had no documented way to be used.
Closed 2026-07-24; tests in tests/test_project_cli.py (21 cases, 13 red first). `list`
and `show` read the catalog only and open no stored payload (R6/F5, pinned). `move` and
`merge` route every edit through the registry module (R9) and inherit its validation, so
each refusal path is asserted to change nothing, and `merge` soft-retires (R4) rather
than removes. `list` shows a retired project marked rather than hiding it.

Slice 8 of 13. Depends on: 04 (capture), 06, 07 (emitters).

Tracer bullet: `ccw build` projects the catalog into
projections/<label>/<date>_<slug>_s-<hash12>/ dirs; `ccw render` becomes real
(both the --session form the hook's detached child invokes, and the ad-hoc
path form). This module owns the ONLY sanctioned deletions besides share
(inside projections/, DESIGN R4).

## Work order (template from harness/prompts/implementer.md)

- SLICE: build/render orchestration
- GOAL: make the slice-8 oracle tests pass; incremental by catalog diff,
  atomic per file, disposable by construction.
- ORACLE TESTS: tests/test_build.py (all except
  test_recent_listing_opens_zero_stored_payloads, which is slice 9),
  tests/test_cli.py::test_render_adhoc_writes_out_dir_and_never_touches_the_warehouse,
  tests/test_cli.py::test_render_adhoc_without_out_prints_a_temp_path.
- CONTRACT EXCERPTS: DESIGN sections 1 (layout + disposability), 4 (render
  child), 6 (supersession, label-rename relocation, hidden sessions), 7
  (render verb); DESIGN 14 rules R2, R3, R4, R6, R12; FINDINGS F2, F4, F5.
- ADJACENT BEHAVIORS: render.render_markdown / render_html / build_manifest
  (slices 6-7: the orchestrator writes what they return, nothing more),
  store.atomic_write + store.get, catalog reads (R6: no raw-payload scans to
  decide what to build), capture's spawn contract (slice 4 froze the child
  argv this slice now serves).
- TOUCHES: src/cc_warehouse/build.py, src/cc_warehouse/cli.py (build +
  render verbs).

## Phase 2 decisions frozen in the tests

- Dir naming exactly <label>/<YYYY-MM-DD>_<slug>_s-<hash12>/ with the date
  from first_ts (R12). Four files + manifest.json per dir.
- Incremental build leaves already-current files untouched (mtime-stable);
  --rebuild regenerates.
- A superseded version's dir is removed on incremental build (one canonical
  dir per session uuid); a label rename relocates dirs and removes the
  emptied old label dir. These are the sanctioned deletions.
- Hidden sessions render only under --include-hidden.
- Ad-hoc render: writes to --out (or a printed temp dir), never under
  projections/, never touches the catalog.

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only.

## DONE 2026-07-19

Slice 08 COMPLETE through the full harness loop. Implementer diff green on first gate
pass (6 in-scope build + 2 render-adhoc oracle tests; the 7th, test_recent_listing...,
is slice 9). One shared projection-writing routine + dir-path function serve build,
`ccw render --session`, and ad-hoc `ccw render <path>` (R9); catalog-driven selection
(R6); content-compare incremental (mtime-stable, F1); disposable-by-construction prune
(the sanctioned R4 deletion, build.py only); every write via store.atomic_write (R2
fence). `ccw project rename` wires the existing registry.rename_project (TOUCHES
expanded by the operator for the label-rename oracle test). Un-stubbing the render
child kept the slice-4 capture suite green. Reviewers A/B + /code-review Standards+Spec;
this slice had REAL bugs (a permanent data-loss path) and the lenses converged. Operator
triage: 6 CONFIRMED clusters + C-CHILD-NOTIFY fixed in 1 fixer round (of 3):
- C-PRUNE-LOSS (F7/F9): a build where the new head failed to render deleted the
  predecessor dir -> ZERO projections (verified); prune now runs only on a clean build.
- C-PRUNE-CRASH (R5): the unguarded prune crashed the build on a concurrent/FS error;
  now best-effort.
- C-BUILD-LOCK (R14/DESIGN-13): build now takes a locks/build O_EXCL lock; a live
  holder refuses.
- C-ADHOC-GUARD (F9): ad-hoc render --out under objects/ or projections/ is refused.
- C-RENAME-NOID (F7): project rename of an unknown id errors.
- C-RENDER-HEAD (R9): render --session projects only a current head (a superseded short
  is a no-op), via a shared head-by-short query.
- C-CHILD-NOTIFY (DESIGN-4): the detached child notifies error on failure + opt-in
  folder reveal.
Rejected: A1 rename-no-commit (refuted: rename_project commits via writing()). Accepted:
C-HIDDEN-CHURN (by design), the "N built" cosmetic miscount. Documented residual: the
build-vs-detached-child stale-snapshot race is regenerable (the next build reconciles).

Contract-derived regression tests (this ticket owns them by citation, HARNESS section
4 precedent): tests/test_build_regressions.py (5 tests). Operator black-box verified the
fixes in fresh temp dirs (25/27 subprocess checks; the 2 non-green were the async render
child racing the probe, re-verified CLEAN 6/6 on a catalog seed). Gates: 6 build + 5
regression + capture 19 + fences 6 green, pyright strict 0, ruff clean; full suite 30
failed / 140 passed, red for the right reason.
