# Ticket 08: build + render orchestration (un-stubs the render child)

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
