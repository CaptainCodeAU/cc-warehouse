# Ticket 12b: relocate, content rewriting

Split from ticket 12 at the 2026-07-19 section-4 escalation (see 12-relocate.md for the
loop record and the diagnosis). Slice 12b of 13. Depends on: 12a (containers must be
decided before content, because content rewriting must track exactly the dirs 12a
renames), 04 (config subset).

Tracer bullet: after 12a knows which repo path and which encoded dirs move, `ccw relocate`
rewrites the path references inside the memory and inventory files under the
config-driven `[relocate] roots`, in markdown AND JSON, backing up each file's exact
pre-image first. Contents are rewritten BEFORE any container moves; a content failure
halts the container phase entirely.

Why this is its own slice: the scan is unbounded over arbitrary user-configured roots,
so its failure modes are about SCOPE (what must never be touched) and MATCHING (what
counts as a reference), neither of which the container work shares. In the escalated
loop these two problem shapes kept masking each other.

## Work order (template from harness/prompts/implementer.md)

- SLICE: relocate content rewriting + backup
- GOAL: repair every path reference inside the configured roots, touch nothing outside
  them, and never leave a file half-repaired or silently unrepaired.
- ORACLE TESTS: tests/test_relocate.py, the content cases (the memory/JSON half of
  test_apply_moves_repairs_and_backs_up and
  test_content_rewrite_failure_halts_container_renames); plus the content cases in
  tests/test_relocate_regressions.py.
- CONTRACT EXCERPTS: DESIGN section 11, especially the 2026-07-19 paragraphs on
  JSON-aware editing with KEYS INCLUDED, encoded-name reference tracking, and the
  warehouse / `~/.claude/projects` scan exclusions; DESIGN 14 rules R2, R4, R5, R10;
  FINDINGS F2, F4, F6, F7, F9; SPEC 10.2 (contents before containers).
- ADJACENT BEHAVIORS: store.atomic_write (every rewrite and every backup; it now
  PRESERVES an existing target's mode, decided 2026-07-19), config._webhooks_from_root as
  the share-local config.toml reader pattern, registry.encode_cwd.
- ALSO CITED: tests/test_store_regressions.py pins the atomic_write mode guarantee this
  slice depends on. The defect was surfaced by relocate (it rewrites arbitrary user files,
  so a silent 0600 was visible) but the primitive is shared by every slice, which is why
  the tests live in their own file and are owned here rather than by ticket 01.
- TOUCHES: src/cc_warehouse/relocate.py, src/cc_warehouse/cli.py.

## Frozen decisions (principal, 2026-07-19; DESIGN section 15 records them)

- Content atomicity is pre-flight validation (every target dir writable) followed by
  per-file `store.atomic_write`. NOT two-phase staging: R2 keeps one write primitive.
- A content failure halts ALL container renames (contents before containers).
- Backup covers the files whose contents are rewritten, and reads each file ONCE so the
  stored pre-image is exactly the bytes the rewrite transformed.
- JSON-aware editing rewrites every string in the decoded document, KEYS INCLUDED.
- Rewriting never descends into the warehouse root (a stored object rewritten in place
  stops hashing to its address) nor into `~/.claude/projects` (captured transcripts are
  sources, read-only forever).
- Encoded-name references are rewritten with one literal old->new pair per dir the run
  actually renames, so a reference changes when and only when its directory moved.

## Carried-forward findings this slice must close

From the ticket-12 escalation, still open in code:

- `Path.read_text()` is locale-dependent, so a non-UTF-8 locale writes mojibake over the
  user's file AND stores the same mojibake as the backup, leaving no recoverable
  pre-image. Decode explicitly, and treat an undecodable file as a named skip.
- JSON rewriting re-serializes the whole document, destroying hand-maintained layout of
  a file whose plan line promised only "rewrite path refs". Decide and record whether
  layout preservation is required, or whether the plan must say what it will do.
  RULED + CLOSED 2026-07-23 (principal), commit 7a3b4b5. Layout IS preserved: rewrite as
  text, then decode the result and check no old reference survives; if one does, redo that
  file structurally and NAME it on stderr as reformatted. Decided by enumerating 29 JSON
  shapes and running both candidate implementations over every one, not from an example.
  That matrix found a defect in the obvious fix AND a live defect in the shipped code:
  an escaped path form (`\/x\/y`, `/x`) is legal JSON that decodes to the real path
  and is invisible to raw-text matching, so the SCAN never selected such a file, the
  rewrite never ran, and `_verify` (also raw text) confirmed success over a file still
  pointing at the old location. Fixed in three places (scan / rewrite / verify) via a
  shared `_references` predicate. The matrix is permanent:
  tests/test_relocate_json_matrix.py (119 assertions, one real `ccw relocate --apply`),
  confirmed red against pre-fix code. It also pins what must NOT change, which the old
  code silently normalised: duplicate keys, number formats, big integers, unicode escapes,
  raw non-ASCII, layout.
  NOTE for the rest of this slice: the plan LINE still reads "rewrite path refs", which is
  now accurate for the common case; a file needing the decode fallback is named at apply
  time rather than at plan time, because the scan does not retain file contents. Revisit
  when the scan is restructured (finding 3/4 below).
- Files under a symlinked directory inside a root are never enumerated, and `.git` and
  the excluded trees are dropped with no mention, contradicting the "never silently
  drops a file" claim. Either report them or drop the claim.
- The roots are fully scanned twice per apply (once for the plan, once inside the lock)
  and every candidate opens its own SQLite connection. With `roots = ["~"]` this is two
  full home reads before the first mutation (F5).
  NOTE 2026-07-23: 12a's finding-4 fix (1da004b) made apply recompute through the shared
  `_compute` and compare against the plan, so the CLI now performs plan + apply scans that
  are BOTH required (the second is the point-of-action re-check the frozen decision
  mandates). The duplication is therefore intentional now; what remains for this slice is
  making each scan cheap, not removing one of them.

Added 2026-07-23 while closing 12a (found by probe, on no ticket before now):

- relocate.py carries its own `[relocate].roots` TOML reader (`_relocate_roots`) whose
  docstring still says "the full config layering that folds this into load_config lands in
  slice 13". Slice 13 landed and gave `Config` a `relocate_roots` field, but relocate.py
  was never switched over, so there are two implementations of one behaviour (R9/F8). This
  is drift created by slice 13 building out of DESIGN-16 order. Fold the reader into
  `load_config` and consume `config.relocate_roots`; the `config._webhooks_from_root`
  pattern already named in ADJACENT BEHAVIORS is the shape to follow.
- 12a's exclusion fix resolves EVERY candidate path (one realpath per entry) inside the
  `rglob` walk. That is correct but pays a syscall per file on an unbounded home walk. The
  `rglob` -> `os.walk(onerror=...)` restructure this slice owns should prune at DIRECTORY
  level instead, which fixes the cost and the silent-drop reporting above in one shape
  (the slice-05 `os.walk(onerror)` precedent).

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get diff +
excerpts + the ADJACENT list only. Same inherited lesson as 12a: operator black-box
verification runs BEFORE triage, and every contract-derived regression test is confirmed
to FAIL against the pre-fix code before it is trusted.
