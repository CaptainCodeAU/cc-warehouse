# Ticket 19: archive-first layout

NOT a slice of v1.1. This restructures what the product IS: the projected folder
tree becomes the deliverable, and the content-addressed store retires. It
touches two of the fourteen enforceable rules and three contract sections, so it
is closer to a version cut than to a slice. Decisions are frozen in DESIGN
section 15, entry 2026-08-02 ("ARCHIVE-FIRST LAYOUT"), with R1 and R4 amended in
section 14. Read those first; nothing here relitigates them.

## The one-sentence reason

The product is a READABLE archive, not a forensic one. The tree gets backed up,
outlives `~/.claude`, and different consumers take the markdown, the HTML or the
raw JSONL from it.

## Before / after

    BEFORE
      <root>/objects/<hh>/<sha256>.jsonl            the vault
      <root>/projections/<label>/<date>_<slug>_s-<short>/
                                 transcript.md, transcript.compact.md,
                                 conversation.html, conversation.compact.html,
                                 manifest.json

    AFTER
      <root>/<label>/<YYYYMMDD-HHMMSS><offset>_<uuid>/
                                 <uuid>.jsonl        <- the source, a REAL file
                                 transcript.md, transcript.compact.md,
                                 conversation.html, conversation.compact.html,
                                 manifest.json
      <root>/<label>/project.json                    label + known paths
      <root>/catalog.sqlite                          disposable index

## Work order

- SLICE: archive-first layout
- GOAL: one self-contained folder per session, named by pinned-zone local start
  time plus session UUID, containing the original JSONL beside its projections.
  `objects/` retired. The tree is complete enough that deleting the catalog
  loses nothing but speed.
- ORACLE TESTS (write first, in tests/test_archive_layout.py):
  - folder name is exactly `<YYYYMMDD-HHMMSS><offset>_<uuid>` and sorts
    chronologically by plain string sort;
  - the zone comes from CONFIG, not the machine: the same payload yields the
    same folder name under TZ=UTC and TZ=America/New_York (this is the
    determinism property the whole scheme rests on);
  - an AEDT session and an AEST session get +1100 and +1000 respectively (the
    offset is real, not a constant);
  - the folder holds the session JSONL byte-identical to the source;
  - re-capturing a LARGER payload replaces the folder's contents in place, and
    the folder NAME does not change (start-keyed);
  - re-capturing a SMALLER payload does NOT replace, and the refusal is recorded
    in manifest.json (never silent, F6);
  - re-capturing an IDENTICAL payload is a no-op and leaves every file
    mtime-stable (idempotence);
  - R4 AMENDMENT, the load-bearing test: a rebuild that deletes generated files
    NEVER deletes the session JSONL, and never removes a folder containing one;
  - a session with no UUID keeps its original filename stem (see open item a);
  - project.json round-trips: delete catalog.sqlite, rescan, and the labels and
    aliases come back;
  - `locks` / `catalog.sqlite` are refused as project labels (flattened-root
    collision).
- CONTRACT EXCERPTS: DESIGN 15 entry 2026-08-02 in full; section 14 R1 and R4 as
  amended; R2 (writes), R9, R12 (payload-internal timestamps), F1 (the identity
  rule R1's amendment carves around), F6, F9.
- ADJACENT: store.py (its object_path/put/get become dead once migration lands -
  do NOT delete the module until the migration has run and been verified);
  build.projection_dir and _prune (the R4 amendment lives here); catalog.py and
  registry.py (project_alias is what project.json must carry);
  share.py (its site layout mirrors projection_dir).
- TOUCHES: src/cc_warehouse/build.py, capture.py, catalog.py, config.py,
  registry.py, share.py, store.py, cli.py.

## Migration, and the one order that must not be reversed

Read from `objects/`, NOT from `~/.claude/projects`. Measured 2026-08-01: 4
stored objects have no surviving source, so migrating from the live sources
loses them permanently. Process `objects/` first, then sweep the live sources as
a second additive pass; both are idempotent because the folder name is a pure
function of the payload's own contents.

Build the new tree BESIDE the old one and verify before swapping. Never rename
in place: the existing 13,608 folders are the operator's live archive.

## Rulings that were open and are now closed (2026-08-02)

(a) A file is a SESSION if any entry carries a `sessionId`. Measured over all 14,066
    non-agent source files, that skips exactly the 7 workflow journals. Emptiness is a
    SEPARATE question: the 139 UUID-named sessions carrying only machinery entries are
    archived (JSONL kept) but get no markdown or HTML, which is today's hidden
    behaviour. Do NOT collapse these into one rule - the single "no conversation" test
    was measured and would have discarded all 139.
(b) `ccw verify` = archive integrity: JSONL vs the manifest's `source_hash`, all five
    files present, folder name agrees with the payload's UUID and start time.
(c) `ccw share` keeps the same layout via the one shared naming function (R9).

Extra oracle tests these imply:
  - a payload with no `sessionId` anywhere is refused at capture and REPORTED by name;
  - a payload WITH a sessionId but no user/assistant entry is captured, its JSONL is
    written, and NO markdown or HTML is generated for it;
  - verify fails a folder whose JSONL no longer matches its manifest source_hash;
  - verify fails a folder missing any of its five files;
  - verify fails a folder whose name disagrees with the UUID or start time inside it.

## Slice cut (2026-08-02), and the disk measurement that forced it

Ticket 19 is eight modules and a migration of 13,836 real sessions, so it runs as
SLICES rather than as one change. Cut so that everything before 19d is pure and
additive, and nothing touches the live archive until the strategy is locked.

    19a  archive folder name + reserved labels        DONE 2026-08-02 (035d2f6)
    19b  `archive_timezone` config key                DONE 2026-08-02 (ab39ed9)
    19c  write one archive folder (JSONL + 5 files)   DONE 2026-08-02 (ab39ed9)
    19d  the migration itself, objects/ -> archive    DONE 2026-08-02, RUN AT SCALE
    19e  archive integrity check (library level)      DONE 2026-08-02 (ab39ed9)
    19f  project.json + catalog-as-disposable-index   not started
    19g  `ccw share` onto the shared naming function  not started
    19h  CLI verbs for archive + verify               not started, see below

19x RESOLVED 2026-08-02: the principal chose BIG-BANG ("just do all of them
together"), having freed disk first. Re-measured at 8.68 GiB free against 5.08
needed. It ran in 6.0 minutes, which retires the resumability argument for
per-project: a 6-minute operation does not need to be resumable.

## THE MIGRATION HAS RUN AT SCALE (2026-08-02), and NOT been swapped

    source  ~/cc-warehouse-data        READ ONLY, verified untouched afterwards
    target  ~/cc-warehouse-archive     NEW root, 5.1 GiB, 13,829 folders
    zone    Australia/Melbourne
    time    6.0 minutes

    13,829 folders written   221 archived without projections
         7 not sessions      0 refused as smaller      0 FAILED

RECONCILIATIONS, all exact, none approximate:

  13,829 + 7 = 13,836, the whole vault, nothing unaccounted for.

  The 7 skipped are EXACTLY the workflow journals DESIGN predicted from the
  sessionId test. Prediction made 2026-08-02 from a census, confirmed the same
  day against a real migration.

  Withheld thinking: 41,408 counted in manifests + 50 inside the 221
  conversation-free folders (which get no manifest by design) + 0 in the 7
  journals = 41,458, exactly ticket 18's census. The 50-block gap was chased
  rather than rounded off.

  The 2 `undated_` folders and the 9 timestamp-free payloads from ticket 18's
  census are the same finding seen twice: 7 of those 9 ARE the workflow
  journals, so exactly 2 real sessions carry no timestamp anywhere.

VERIFY over all 13,829 folders: 0 problems. Every JSONL matches its manifest
source_hash, every folder has its five generated files, every folder name agrees
with the payload's own uuid and start time.

TELEMETRY AT SCALE, which is ticket 18 and 20 being proved on real data rather
than on fixtures: 0 unrecognised entries across the entire archive, so the named
type registry covers the corpus completely; 11 sessions carry any recorded loss
at all, which are the lone-surrogate cases from 2026-08-01.

NOT DONE, deliberately: nothing has been swapped. `~/cc-warehouse-data` is
untouched and still the live warehouse. The hook, sweep and build verbs still
write to it. Swapping is a separate decision.

19a is done: a pure function, no filesystem contact, no dependency on how the
migration runs, so it was safe to land before the strategy question closed.

DISK, measured 2026-08-02 before any of this: the frozen instruction is "build
the new tree BESIDE the old one and verify before swapping". The new tree needs
5.08 GiB (objects 1.50 + projections 3.63). Free space was 5.47 GiB on a volume
at 98%, a 7% margin on a long operation across 13,608 folders. Surfaced to the
principal, who freed space; re-measured at 8.68 GiB free, a 3.60 GiB margin, so
build-beside is now viable.

19x, STILL OPEN and blocking 19d: whether the migration runs BIG-BANG (build the
whole tree beside, verify, swap) or PER-PROJECT (one of the 57 labels at a time,
verify it, reclaim that label's old projections, move on). Per-project peaks at
about 1.2 GiB rather than 5.08 and is resumable after an interruption, and its
advantages were never only about disk. The principal freed space, which unblocks
big-bang without selecting it. Largest label is 0.84 GiB of 3.63 (23%).

`objects/` is not touched by any slice above. It stays the source of truth for
the whole migration, so the worst outcome of a failure at any point is a
partly-built new tree beside a completely intact old one.

## Process

Standard loop (HARNESS section 2); oracle tests first. Ticket 18 (real-data
coverage) should land BEFORE this one: it hardens the parser against shapes this
migration will feed through 13,836 times, and a migration is the worst moment to
discover a twelfth unhandled entry type.
