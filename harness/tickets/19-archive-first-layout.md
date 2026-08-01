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

## Open items, to rule on BEFORE implementation

(a) The `journal.jsonl` filter. 7 workflow journals were captured as sessions and
    are exactly the 7 rows with a NULL session_uuid. They are junk, not a naming
    edge case, so the fix is a capture-time filter. Confirm they should be
    excluded rather than named.
(b) What `ccw verify` becomes. Proposed: check each folder's JSONL against the
    `source_hash` already in its manifest, plus folder completeness and
    name-vs-payload agreement. That is a verifier for the thing actually shipped.
(c) Whether `ccw share` adopts the same layout, or keeps its own.

## Process

Standard loop (HARNESS section 2); oracle tests first. Ticket 18 (real-data
coverage) should land BEFORE this one: it hardens the parser against shapes this
migration will feed through 13,836 times, and a migration is the worst moment to
discover a twelfth unhandled entry type.
