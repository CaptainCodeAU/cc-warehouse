# Ticket 30: incremental archive rebuild

Opened 2026-08-18, from `contract/PROPOSALS/incremental-archive-rebuild.md` - a
proposal filed by an assistant session working outside this repo that evening,
who found the defect by reading a real `ccw archive` run's timing and CPU use on
this machine and traced it into the code.

**DONE 2026-08-18.**

## The problem, with real numbers

A weekly `launchd` job (`com.captaincodeau.ccw-archive`, new the same evening)
runs `ccw archive --to ~/cc-warehouse-archive`. Measured on a real run before this
ticket: **20779 folders written, ~40 minutes, ~90% CPU, the whole time.** That is
a full pass over every session in the warehouse, every single week, even though
almost nothing had changed since the previous run.

Root cause: `_migrate_locked` walked every catalog row and called
`write_session_folder` unconditionally. The JSONL itself was already handled
efficiently (replace-if-larger, R14); the four generated documents plus the
manifest were rebuilt from scratch regardless.

## What shipped

One shared predicate, `archive.folder_is_current(directory, source_hash,
options)`, used at two call sites so there is exactly one implementation of this
truth (R9/F8):

1. **`_migrate_locked`** - the big win. Widened `_session_rows` to also select
   `first_ts`/`session_uuid` (columns `build._heads` already reads, for the same
   reason), names the folder from the catalog row alone via `build.archive_dir`,
   and checks it **before `store.get()` is ever called**. An unchanged session
   now costs one small file read instead of a store read, a parse and a
   five-file render.
2. **`write_session_folder`** - the same check as a guard, right before the
   render loop, covering `capture._mirror_to_archive` and `build._mirror` too
   for free.

`ccw archive --rebuild` is the escape hatch, mirroring `ccw build --rebuild`;
threaded through `migrate(..., rebuild=False)` exactly as `force` is threaded
through `build.write_projection`.

`MigrationReport` gained `skipped_current`, reported in `summary()` as its own
"N unchanged" segment (R10: never silently do less and say nothing about it).

## Two hazards the proposal named as open, closed here

Both would have been invisible to a byte-compare-after-render approach (what
`ccw build`'s existing incrementality does) because skipping the RENDER, not
just the write, is a strictly stronger claim.

**H1 - the renderer itself can change.** Without a way to detect that, an
upgrade that changes rendered output (tickets 18/20, slices 14-17 all did) would
leave every existing folder frozen at the old format forever, with nothing on
disk saying so. Fixed by adding `renderer_version` (`cc_warehouse.__version__`)
as a new top-level manifest key (DESIGN section 6), included in the skip check.
Chosen over a hand-maintained format counter because a stamp nobody has to
remember to bump cannot be forgotten; it costs one full rebuild per release,
which is the run an operator would want anyway.

**H2 - sub-agent lists go stale.** `write_subagent` never touches its parent's
manifest; only a full render of the parent refreshes the `subagents` list. The
weekly full rebuild was quietly doing that repair every run; removing it would
have removed the repair too. Measured across the whole real archive (20,740
folders, 300 with sub-agents) before this ticket: 0 stale, entirely because of
that repair. Fixed by including `subagent_records(directory)` in the skip check.

## A third hazard, found by running the test suite rather than by reasoning

Neither of the above is what the first real regression was. `folder_is_current`
originally trusted `manifest.json` alone. `tests/test_keep_projections.py::
test_build_still_refreshes_the_archive_when_projections_are_off` deletes
`transcript.md` from an archive folder and expects `ccw build --rebuild` to
restore it - and with the skip-check as first written, it silently stopped
doing that, because the manifest (one of the five files, and the only one that
was NOT deleted) still looked current. Fixed by requiring all five
`GENERATED_NAMES` files to exist on disk before even opening the manifest.
Recorded per this project's own standing lesson ("a green suite is a statement
about the inputs you imagined"): this was not anticipated by the design, it was
caught by running the actual test suite the first time, in the same session.

## The interrupted-run question, closed by evidence rather than by a new mechanism

The proposal's one open question: could an interrupted run leave a manifest
that says "I match" beside stale pages? Verified in the code:
`build.iter_projection_files` yields `manifest.json` LAST, and
`write_session_folder` writes in yield order, so a kill mid-loop can only leave
*fresh pages beside an OLD manifest* - which fails the `source_hash` check and
forces a rebuild. The dangerous ordering is unreachable under the current write
order. No marker file was added; instead the ordering itself is now pinned by
`test_manifest_is_yielded_last` and by a comment naming what depends on it, so a
future reordering breaks a test at the reorder site instead of breaking safety
silently.

## Oracle tests

`tests/test_archive_incremental.py`, 20 tests, written before the fix for H3
above was known to be needed (it surfaced from running them). Covers: the
predicate in isolation (missing manifest, corrupt manifest, hash/config/
renderer-version/subagent mismatches, a missing generated file); end-to-end
`write_session_folder` behaviour (skip, rebuild, `--rebuild`-forces, a refusal
is never skipped even though the surviving payload's hash still matches, a
sub-agent forces a rebuild and gets listed, a deleted file gets restored); the
manifest-last write-order invariant; a simulated interrupted run; and, at the
`ccw archive` CLI level, that a second run reports everything unchanged, never
touches the stored payload for unchanged sessions, is a true no-op on the tree,
and `--rebuild` forces every folder through the full path regardless.

## Verification

`uv run pytest` (1077 passed, plus this ticket's 20), `uv run pyright`
(0 errors), `uv run ruff check` (all checks passed). `tests/golden/matrix-anchor`
untouched - this change moves no projected byte, only which bytes get
(re)written when.

## Not done here, flagged for later

`archive.py`: when a re-captured payload is the same size as what's archived but
has different content, the JSONL is correctly left alone but `refused` stays
False, so the folder's rendered pages describe the NEW payload while the JSONL
beside them still holds the OLD bytes. Pre-existing, in ticket 29's family
(mechanism 2 fixed the size-known-different case; this is the equal-size case),
unrelated to and unchanged by this ticket. Recorded rather than folded into an
unrelated fix.
