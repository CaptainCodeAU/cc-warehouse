# FINDINGS - verified failure classes of the specimen, as binding constraints

**Status:** Phase 1 contract document, 2026-07-17. Companions: `SPEC.md` (what the old
tool does), `DESIGN.md` (how the new one works), `HARNESS.md` (how it gets built),
`BRAINSTORM.md` (approved scope).

**How to read this document.** Every finding below was verified against the specimen's
actual source (`~/CODE/CaptainCodeAU/claude-code-transcripts`, master at `2c8fea7`) on
2026-07-17, not taken from its docs or from prior review prose. Each finding is stated
four ways: the **evidence** (where it lives), the **class** (the general mistake, which
is what we actually ban), the **rule** (the design property that makes the class
impossible in cc-warehouse, not merely fixed), and the **verification** (how the rule is
enforced: an oracle test, a reviewer checklist line, or a static gate). Line numbers are
frozen to the commit above; they date, the classes do not.

The one-sentence summary of the whole document: **the specimen achieves correctness by
coincidence of the data (sizes, paths, timestamps, single-writer luck); cc-warehouse must
achieve it by construction (hashes, IDs, atomic writes, idempotent operations).**

---

## F1. Size-equality treated as content identity

- **Evidence:** `scripts/reconcile_sessions.py:366-409` (`compare_session_copies`):
  equal `st_size` returns "identical" with no byte comparison, feeding both the orphan
  duplicate path (`_handle_duplicate`, line 439) and drift dedupe (`classify_drift`,
  line 1407). Same proxy in `src/claude_code_transcripts/core/idempotency.py:12-21`
  (`should_skip`): equal size of source and archived JSONL means "already exported".
  The prior review called this H-1; confirmed.
- **Class:** using a cheap attribute (size) as an identity proxy for content.
- **Rule:** identity in cc-warehouse is sha256 of content, everywhere, with no
  size-based shortcut anywhere in any code path. Two payloads are "the same" if and
  only if their hashes are equal. Size and timestamps may be stored as metadata,
  never consulted for equality (the specimen's no-JSONL branch even falls back to
  mtime-as-identity with a 60s band, reconcile_sessions.py:393-409; same ban).
- **Verification:** oracle test: two same-size, different-content JSONLs must be stored
  as two distinct sessions and never deduped; grep gate: no comparison of `st_size` or
  `st_mtime` values appears outside pure display code; reviewer checklist line.

## F2. No atomic writes anywhere

- **Evidence:** `cli.py:586-589` (`shutil.copy` of the transcript straight to its final
  path); `render/html.py:204,294` and `render/indexes.py:35,74` (`write_text` direct to
  final path); `notify.py:110` (append is fine, but the pattern is absent everywhere
  else). No `os.replace`, no tmp files, in the entire pipeline.
- **Class:** torn writes: a crash or concurrent reader mid-write observes a partial
  file that downstream logic then treats as real (and F1's size proxy misjudges).
- **Rule:** every write of every file in cc-warehouse (store objects, catalog side
  files, projections, manifests, shares) is tmp-file-in-same-directory + `os.replace`.
  This is a locked architecture decision from the handoff; it is global, not hot-path
  only.
- **Verification:** oracle test: kill the writer mid-render and re-run; no partial file
  is ever visible at a final path. Static gate: reviewer checklist forbids `write_text`
  / `open(path, "w")` on final paths; a helper (`atomic_write`) is the only sanctioned
  write primitive.

## F3. Unlocked concurrent capture

- **Evidence:** `cli.py:538-605` (`hook_cmd`): no lock, no pidfile. Two SessionEnd
  invocations for the same session both pass `should_skip`, both copy, both spawn
  detached render children (`spawn.py`) that write the same `index.html` concurrently
  via non-atomic writes (F2). The prior review called this RC-1; confirmed. Same class
  in drift mode: `classify_drift` (reconcile_sessions.py:1397) checks the target
  collision at PLAN time but `execute_drift_plan` (1443) moves later with no re-check,
  a plan/apply TOCTOU window.
- **Class:** multi-writer race on shared output with no coordination.
- **Rule:** capture is idempotent by identity, not by luck: storing an object whose
  hash already exists is a no-op; catalog inserts are transactional (SQLite); the
  render child writes projections atomically (F2) so the worst case of a duplicate
  render is wasted work, never corruption. Where exclusion is still needed (sweep vs
  hook), a lock file with `O_EXCL` semantics, never assumption.
- **Verification:** oracle test: fire the same capture payload N times concurrently;
  exactly one catalog row, valid projections, no torn files.

## F4. Paths used as identity

- **Evidence:** the whole naming pipeline: `core/naming.py` (lossy display-name
  derivation with `skip_dirs`), `core/resolve.py:17` (cwd encoding collapses `/`, `_`,
  `.` to `-`), archive layout keyed by display name, and `render/html.py:66` +
  `core/archive.py:37-45` where two encoded folders sharing a display name silently
  share an output dir and `_generate_project_index` (`indexes.py:34`) lets the last
  writer win (prior review RC-2; confirmed). Corollary: repo moves orphan memory and
  history (the principal's rename fear; `migrate_project.py` patches one narrow case).
- **Class:** deriving identity from a mutable, lossy attribute (a path or a name
  computed from it).
- **Rule:** sessions are identified by content hash; projects are identified by stable
  registry IDs with time-stamped path aliases. Display names are labels resolved
  through the registry; every projection groups by project ID, never by raw path or
  derived name. Collisions become alias rows, not overwrites.
- **Verification:** oracle test: two projects whose paths derive to the same display
  name must produce two registry entries and two complete projections; oracle test: a
  registry `move` relinks history with zero file rewrites.

## F5. Full-corpus scans to answer small questions

- **Evidence:** `core/summary.py:84-106` (`find_local_sessions`): globs `**/*.jsonl`
  and summary-parses every file (each opened up to twice) to display 10 picker rows
  (prior review P-1; confirmed, with the nuance that the source is the live
  `~/.claude/projects`, not the archive). `core/archive.py` re-parses everything on
  every `all` run; no incremental anything.
- **Class:** no index; every read re-derives global state from raw data.
- **Rule:** the catalog is the read path. Listings, filters, and search hit SQLite;
  raw JSONL is read once at capture (plus explicit rebuilds). Projection rebuilds are
  incremental by catalog diff unless `--rebuild` is asked for.
- **Verification:** oracle test: listing recent sessions from a 10k-session store
  opens zero JSONL files (observable via a file-open counter in tests).

## F6. The code overclaims its own guarantees

- **Evidence:** `reconcile_sessions.py:9,98,1313,1412,1510`: docstrings and user-facing
  strings say "byte-equal" while the implementation compares sizes (F1). The public
  docs repeated it until corrected (specimen commit `2c8fea7`). The old test suite
  encodes the size-only behavior as EXPECTED (`tests/test_reconcile.py`,
  `TestCompareSessionCopies`), so the tests enshrine the bug.
- **Class:** guarantee drift: prose (comments, docs, tests names) promising a stronger
  property than the code enforces; tests locking in the weaker property.
- **Rule:** cc-warehouse oracle tests are written from SPEC/DESIGN/FINDINGS before
  implementation and never ported from the specimen suite. Any user-facing string or
  docstring naming a guarantee ("atomic", "identical", "byte-equal", "never deletes")
  must have a test that proves that exact word.
- **Verification:** HARNESS reviewer checklist line: for every guarantee word in
  strings/docs, cite the test that enforces it or reject the diff.

## F7. Errors fail toward the destructive branch

- **Evidence:** `reconcile_sessions.py:374-375,402-403`: a stat `OSError` returns
  ("identical", "stat failed"), which routes the copy to `_DELETE/` (soft-delete) in
  both consumer paths. An I/O failure is interpreted as "safe to remove".
- **Class:** exception handling that defaults into the action requiring the MOST
  confidence.
- **Rule:** in cc-warehouse, any error on the evidence path aborts the action for that
  item and reports it; unknowns are never classified as duplicates, never skipped as
  already-captured, never drained. The conservative branch is the default branch.
- **Verification:** oracle test: make stat/read fail for one item mid-batch; that item
  is reported and untouched, the batch completes for the rest.

## F8. Duplicated logic drifts

- **Evidence:** structural, and live in-tree TODAY: `generate_html` and
  `generate_html_from_session_data` are ~170-line near-verbatim duplicates in one
  file (render/html.py:122-297 vs 300-469); the `web` command renders through the
  second copy, so every rendering semantic exists twice. Historically the same class
  misrouted real sessions: the plugin's stdlib-only copy of
  `get_project_display_name` stayed buggy after the CLI copy was fixed (specimen
  commit `6e43c04`; plugin activation later deleted the duplicate; archived
  `docs/private/ARCHITECTURE_LEGACY.md` documents it).
- **Class:** two copies of one truth with no import linkage.
- **Rule:** cc-warehouse is a single package; the capture hook, CLI, and any wrapper
  invoke the same installed code path. Wrappers may set environment only; they carry
  zero business logic. The exporter userscript is the one sanctioned sibling
  implementation, and the bundle manifest (not shared code) is its contract.
- **Verification:** reviewer checklist: any diff introducing a second implementation of
  an existing function is rejected; wrapper files are grep-audited for logic.

## F9. Destructive interpretation of "cleanup"

- **Evidence:** the specimen already honors soft-delete (`move_to_delete_folder`,
  `reconcile_sessions.py:1185-1201`, with collision suffixes) and the no-delete rule is
  principal-locked. But the pattern relies on every future code path remembering it;
  nothing structural prevents a `shutil.rmtree`.
- **Class:** safety by convention instead of by construction.
- **Rule:** cc-warehouse has no delete primitive at all in its store layer: objects are
  immutable, catalog rows are never hard-deleted (soft flags only), and the only file
  removal in the entire codebase is projection rebuild (delete + regenerate inside the
  projections directory, which is disposable by definition) plus the O_EXCL lock
  helpers removing their own lock files (DESIGN section 13 closed list). `rm`-class
  calls against the store or source transcripts are forbidden tokens.
- **Verification:** static gate: `shutil.rmtree` / `os.remove` / `unlink` allowed ONLY
  under the projections module and the store module's O_EXCL lock helpers (DESIGN
  section 13 closed list; function-scoped carve-out decided at slice-01 triage,
  2026-07-18), enforced by a fence test like the specimen's zero-dep fence; oracle
  test: migrate and import never modify or remove their sources.

## F10. Non-interactive input is treated as consent

- **Evidence:** `reconcile_sessions.py:1256-1264` (`confirm`) and
  `migrate_project.py:247-250` (`confirm`) + `260-278` (`prompt_3rdparty`): when stdin
  is not a TTY, every confirmation returns the proceed path. Piping input or running
  from cron auto-approves every destructive group without `--yes` ever being passed.
- **Class:** consent defaulted in the absence of a human.
- **Rule:** in cc-warehouse, apply-class steps proceed only on an interactive yes or an
  explicit `--yes`; a non-TTY stdin without `--yes` aborts with a clear message. The
  absence of a human is the conservative branch, exactly like the presence of an error
  (F7).
- **Verification:** oracle test: run an apply-capable command with stdin from
  /dev/null and no `--yes`; it must exit non-zero having changed nothing.

---

## Carried context

- The specimen's own remaining overclaim (F6 strings) is deliberately NOT fixed there:
  the repo is feature-frozen as this project's specimen (its BACKLOG ID 27).
- F1/F2/F3/F4 correspond to the prior review's H-1, RC-1, RC-2 and the torn-write and
  should_skip extensions verified this session; P-1 is F5.
- Every rule above must appear in `DESIGN.md` as an enforceable design rule and in
  `harness/prompts/` as reviewer checklist material. If a rule is missing from either place,
  that is a Phase 1 defect.
