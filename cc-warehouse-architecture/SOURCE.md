# cc-warehouse architecture-review board - canonical SOURCE

> **This file is the canonical record of cc-warehouse's code-architecture review board.**
> `index.html` is the VIEW rendered from this file by `/architecture` - edit THIS, then
> regenerate. Never hand-author findings into the HTML.
> **Scope guard:** the contract docs (`contract/BRAINSTORM.md`, `SPEC.md`, `DESIGN.md`,
> `FINDINGS.md`, `HARNESS.md`) are LOCKED. This board never edits them and never relitigates
> their decisions; a candidate that needs a contract change says so and waits for the
> principal's ruling (the card-8 pattern).
>
> ## ⛔ DECAY BANNER, added 2026-08-21: THIS BOARD'S ANCHOR NO LONGER EXISTS
>
> **Every `file:line` on this board was derived at master `1517bba`, and that commit
> is NOT in this repository.** Checked with `git cat-file -t`: both `1517bba` and the
> `18fa5be` that `CLAUDE.md` names beside it are MISSING. They were lost when the
> repository was deleted and re-created on 2026-08-10 (ticket 28.20, the go-public
> audit), which rewrote history; the board was not re-anchored afterward.
>
> **What this means, precisely.** No line reference below can be verified against the
> commit it was taken from, and none can be checked for decay either, because there is
> nothing to diff against. `git rev-list 1517bba..HEAD` does not run. The repository is
> now at 236 commits with HEAD at `3b284e5`.
>
> **What is still usable:** the REASONING on each card, and its verdict. Those were
> verified first-hand at the time and do not depend on a line number.
> **What is not:** every `file:line`, every "N commits stale" claim, and the retired
> decay banner quoted in the snapshot note below, which is retired against a commit
> that cannot be consulted.
>
> **Do not patch the line numbers by hand.** The board is owned by `/architecture` and
> re-derived, never edited in place. The fix is a fresh review at a live commit, which
> is ticket 28.13's job. This banner exists so nobody reads a stale ref as a current one
> in the meantime.

> **Snapshot: FRESH REVIEW 2026-07-24, master `1517bba`.** This supersedes the 2026-07-19
> review at `56262f6`, whose line refs had decayed across 20 commits and +4,036 src lines.
> Every file:line below was RE-DERIVED at `1517bba` and re-verified first-hand; the decay
> banner the previous snapshot carried is retired because the refs are current again.
> **Method:** 3 background Explore lens scans (pipeline core / orchestration / testability)
> over the git hot-spot census (cli.py 16 commits, relocate.py 13, render.py 8), then
> first-hand verification of every load-bearing claim by the operator before it entered this
> board - a lens report is EVIDENCE to reconcile, never a settled finding.
> **Vocabulary:** module, interface, implementation, depth (deep/shallow), seam, adapter,
> leverage, locality (the /codebase-design glossary).
>
> **States:** `PROPOSED` (awaiting the grilling conversation) / `GRILLING` (in conversation) /
> `TICKETED-<nn>` (owned by a harness ticket; the ticket is the claim) / `BUILT` (landed,
> verified) / `REJECTED` (recorded so reviews stop re-suggesting it).
> **Evidence tiers:** `VERIFIED` (first-hand at the snapshot commit) / `CONTRACT` (a DESIGN or
> ticket line is the claim) / `AGENT-REPORTED` (lens-scan context beyond the verified lines).
>
> **Build state:** v1 is CLOSED. All DESIGN section 16 slices landed and tagged (14 tags,
> slice-01..13 incl. 12a/12b); the exit review was held; `--hljs`/`--theme` ruled; C8 BUILT.

---

## The board (recommended order - RE-RANKED at the 2026-07-24 review)

### 1st . C3 - Make the risky transforms public and I/O-free
`[PROPOSED]` . Strength: **Strong** . Tier: VERIFIED at 1517bba . in-process
- **Files:** `share.py` . `relocate.py`
- **Problem:** the correctness-critical logic of the two riskiest verbs is pure, deterministic
  string transformation, yet sealed behind underscore-private helpers with only I/O-bound
  entry points public. share's detectors and redactors: `_custom_patterns` (share.py:85),
  `_redaction_patterns` (:133), `_redact_value` (:142), `_redact_tree` (:176),
  `_is_generic_secret` (:235), `_scan_secrets` (:253) - only `share()` (:331) is public and it
  does store reads, render, and disk writes. relocate's JSON-aware rewriter: `_form_patterns`
  (relocate.py:169), `_sub_text` (:198), `_sub_tree` (:204), `_tree_matches` (:228),
  `_references` (:242), `_rewrite_bytes` (:263) - only `plan_relocate` (:617) and
  `apply_relocate` (:962) are public, and both walk the filesystem.
- **Cost, MEASURED not inferred (the testability lens):** every test of this logic stands up a
  temp warehouse and crosses a process boundary (`run_ccw` in conftest.py:88 is a real
  subprocess). tests/test_relocate_json_matrix.py drives its 29-shape census
  (~120 assertions across CASE_IDS) through ONE `ccw relocate --apply` subprocess because
  `_rewrite_bytes` is not callable; tests/test_share_regressions.py runs ~27 subprocess
  invocations plus a fresh temp warehouse per test to assert facts about `_redact_value`,
  `_is_generic_secret` and `_scan_secrets`. Zero in-memory private-helper calls exist across
  tests/. render.py and parser.py are the counter-example: their pure transforms
  (`render_markdown`, `parse_session`, `build_conversation`) are public and tested in-memory.
- **The surface is actively WIDENING:** `_tree_matches` and `_references` were added in commit
  7a3b4b5 (ticket 12b finding 2), later than the original slice-12 43432e4. 12b's headline
  defect - an escaped path form invisible to the scan, so a file was never a candidate and
  verify confirmed success over it - is exactly this card's predicted failure class, and its
  new decode-fallback depth landed with no seam.
- **Solution direction:** promote thin public transform seams - e.g.
  `redact_payload(text, patterns) -> (str, hits)` and `scan_secrets(text) -> findings` over
  share; `rewrite_bytes(path, text, patterns)` and `references(path, text, patterns)` over
  relocate - so the shape census asserts against the transform directly and the subprocess
  covers only the real I/O.
- **Wins:** the interface becomes the test surface for the riskiest logic . a new redaction
  rule or path shape is a one-line in-memory assertion instead of a subprocess . oracle tests
  stay locked, future tests get cheap.
- **Why 1st (re-ranked from 3rd, 2026-07-24):** highest correctness stakes in the codebase,
  the cost is measured rather than argued, the gap is widening, and its designated home
  (ticket 12b) closed WITHOUT folding in the seam. The 12a/12b timing objection that placed
  it 3rd is spent. This is the review's top recommendation, replacing C1.

### 2nd . C2 - Deepen the batch-verb protocol
`[PROPOSED]` . Strength: **Strong** . Tier: VERIFIED at 1517bba . in-process
- **Files:** `reports.py` . `cli.py` . `sweep.py` . `build.py` . `migrate.py` . `relocate.py`
- **Problem:** `store.acquire_lock`/`release_lock` (store.py:192-270) is a deep O_EXCL primitive
  behind a two-function bool interface, but four verbs each re-wrap it with an identical shell,
  and cli.py mirrors the report/tally half four more times. Module copies (sentinel-triple +
  acquire-or-refuse + finally-release): sweep.py (constants :20/:24/:29, body :137-151),
  migrate.py (:30/:34/:39, :99-119), build.py (:224/:228/:233, :253-286), relocate.py
  (:37/:38/:39, :972-979). CLI mirrors (lock-held detect + failure loop + count + exit):
  `_run_sweep` (:310-318), `_run_build` (:375-383), `_run_migrate` (:757-768), `_run_relocate`
  (:882-908). reports.py is a 19-line shell owning only the `.failures` error filter; every
  verb re-derives `stored`/`built` counts and the exit policy locally, and relocate keeps its
  own `CHANGE_ACTIONS`/`applied_changes` notion of "what counts" (relocate.py:68/:76-78).
- **Solution direction:** deepen the seam - a `with_lock(root, name) -> BatchReport` runner plus
  a shared `render_batch(report) -> exit_code` in reports.py owning the sentinel-triple, the
  finally-release, the per-action counts and the exit policy, so each verb hands in only its
  body.
- **Wins:** leverage (v1.1 `ccw import` inherits the protocol) . locality (R10/R14 presentation
  in one module) . deletes four sentinel triples and four CLI mirrors.
- **Contract ties:** R9, R10; R14 untouched.
- **Note 2026-07-24:** this grew since the last snapshot. The 2026-07-19 board recorded 5 CLI
  blocks; the migrate / project / `--EXPOSED` work added copies, so it is now 4 module + 4 CLI.
  Best done before v1.1 `ccw import` adds a fifth.

### 3rd . C1 - Parse once: one parse product
`[PROPOSED]` . Strength: **Strong** . Tier: VERIFIED at 1517bba . in-process
- **Files:** `render.py` . `build.py` . `parser.py`
- **Problem, RE-LOCATED by the review:** parse-once is honored INSIDE parser.py -
  `parse_session` (parser.py:161) and `build_conversation` (:597) both route through the single
  `_extract_entries` (:122, called at :167 and :614), so the "both re-extract" hypothesis is
  refuted. The real violation is one level up, at the orchestration seam: the three emitter
  entry points each take raw `data: bytes` and privately re-derive the model.
  `render_markdown` calls `build_conversation` (render.py:892) + `parse_session` (:893);
  `render_html` calls both (:1813/:1814); `build_manifest` calls `build_conversation` (:1829).
  `build._projection_files` (build.py:87-100) invokes all three (:90-92), so ONE projection
  write decodes the bytes and re-walks the entry list build_conversation x3 + parse_session x2.
  `sha256_hex(data)` is likewise recomputed at render.py:894, :1816, :1831.
- **Solution direction:** hoist parsing to the orchestrator - build `(Conversation,
  ParsedSession)` once in `_projection_files` and pass the models into the three emitters,
  keeping a thin bytes-taking wrapper for the black-box tests.
- **Wins:** leverage (one parse, three emitters) . locality (extraction quirks in one place) .
  5x parse cost gone before the large migrate and v1.1 FTS5 . makes the DESIGN parse-ONCE
  sentence true (R8).
- **Contract ties:** R8, R9; DESIGN section 4.
- **Why 3rd (was 1st):** still Strong and still zero contract risk, but the review re-ranked C3
  above it: C3's stakes are higher and its cost is measured. C1 stays a clean, self-verifying
  refactor (the emitters are frozen by black-box output tests).

### 4th . C4 - Give the head concept one home: a catalog read seam
`[PROPOSED]` . Strength: **Strong** . Tier: VERIFIED at 1517bba . in-process
- **Files:** `build.py` . `share.py` . `cli.py` . `catalog.py`
- **Problem:** "a head is a row no other row supersedes" is copied. The predicate
  `s.hash NOT IN (SELECT supersedes FROM session WHERE supersedes IS NOT NULL)` is typed
  verbatim in `_heads` (build.py:143) and `head_for_short` (:173), and the whole SELECT+JOIN
  column list is duplicated too (build.py:141-142 vs :170-171) - while head_for_short's own
  docstring (:167) claims "Shares _heads' join and head predicate (one owner, R9)", an R8/F6
  overclaim. `_Resolved` re-declares the head shape in share.py:75; cli.py runs its own
  session/project SELECTs (see C6).
- **Solution direction:** catalog.py (or build.py) owns one `_HEAD_SELECT` / `_HEAD_WHERE`
  fragment and a public head-record type both callers compose; reads stay catalog-only (R6).
- **Wins:** locality (version-chain semantics beside the schema) . leverage (v1.1 search and
  v1.2 MCP read the same seam) . makes the docstring true (R8).
- **Contract ties:** R6, R8, R9.

### 5th . C6 - cli.py: verbs hand back results, not cursors
`[PROPOSED]` . Strength: **Strong** . Tier: VERIFIED at 1517bba . in-process
- **Files:** `cli.py` . `build.py` . `registry.py` . `relocate.py`
- **Problem:** verb logic lives in cli.py that should live in the verb's module.
  (a) The render no-row-vs-superseded policy is stranded in `_render_session` (cli.py:431-444):
  a raw `SELECT 1 FROM session WHERE short = ?` (:434) plus the three-way "absent -> exit 1,
  superseded/hidden -> clean no-op" policy (:439-444), while build.head_for_short owns only the
  head selection, so a non-CLI caller cannot tell absent from superseded.
  (b) project-exists SELECTs are inline in `_run_project` (list :585-587, show :606-626, rename
  existence :643-646, merge label map :679-682) even though registry.py owns the edits.
  (c) `_out_under_warehouse` (cli.py:475-491) guards `build.write_projection` (build.py:119)
  but is a CLI-only wrapper, so the two non-CLI callers of write_projection lose the guard.
  (d) halted-run recovery string-matches relocate action detail (cli.py:886, :894-905), the
  exact fragility the typed `skipped` flag and `REFORMAT_NOTE` were introduced to avoid.
- **Solution direction:** verbs own their reads and guards and return a typed result plus exit
  intent; registry.py gains the project read side; the write-guard moves into write_projection;
  relocate exposes typed accessors (`reformatted()`, `halted_changes()`) so cli never
  string-matches. cli keeps parsing, printing, exit codes.
- **Wins:** locality (one file per verb change) . the F9 guard travels with the write .
  leverage (v1.2 MCP reuses whole verbs).
- **Contract ties:** F9. Overlaps C2 (both concern cli.py's batch/verb shell) and C4 (both
  concern the head read).

### 6th . C9 - One source walker, two policies
`[PROPOSED]` . Strength: **Strong** (was Speculative) . Tier: VERIFIED at 1517bba . in-process
- **Files:** `sweep.py` . `migrate.py`
- **Problem:** `sweep._walk_source` (sweep.py:44-76) and `migrate._walk` (migrate.py:42-82) are
  the same scaffold verbatim: the `if not root.is_dir(): return [], []` guard, the inner
  `_on_error` appending an "unreadable source directory" ItemOutcome, `os.walk(onerror=...)`,
  the `.jsonl` suffix filter, and `return sorted(found), sorted(errors, ...)`. Even the
  `_JSONL_SUFFIX = ".jsonl"` constant is declared twice (sweep.py:36, migrate.py:21). The only
  real divergence is the per-file policy: sweep skips `agent-*` and drops a non-regular jsonl
  silently; migrate keeps `agent-*` and names a non-regular one as an error (the slice-10
  FIFO-hang lesson).
- **Solution direction:** one `walk_transcripts(root, *, classify)` owning the scaffold, with
  each verb supplying only its filename policy.
- **Why bumped to Strong:** the review found the duplication is total (scaffold + onerror body +
  constant), not partial, and the F7 under-capture lesson it encodes now has two homes that can
  drift.

### 7th . C5 - One turn walker, two serializers
`[PROPOSED]` . Strength: **Worth exploring** . Tier: VERIFIED at 1517bba . in-process
- **Files:** `render.py`
- **Problem:** the turn/segment traversal is written twice. Markdown: `_turn_body`
  (render.py:730-746) walks `group_segments(turn)` with an `is_phase` branch; `_render_turn`
  (:789-805) does the synthetic / user-half / claude-half shape. HTML: `_claude_inner`
  (:1617-1630) repeats the same walk; `_turn_html` (:1633-1697) repeats the same shape. A
  turn-structure change is two edits kept in agreement only by hand. Deliberately partial: leaf
  block-to-markdown IS single-owner via `_render_block` (:356) - only the WALK is doubled.
- **Solution direction:** one turn-walk yielding typed events (Phase / Reply / UserHalf), each
  emitter supplying only leaf rendering.
- **Contract ties:** R9. Pairs with C1's single parse product.

### 8th . C7 - Type the Block discriminant
`[PROPOSED]` . Strength: **Worth exploring** . Tier: VERIFIED at 1517bba . in-process
- **Files:** `parser.py` . `render.py`
- **Problem:** `Block.kind` (parser.py:291) is a bare str whose legal set is enumerated only in
  a docstring (:287-289), switched on at ~7 sites: `_segment_category` (parser.py:356-369),
  `group_segments` (:394), and across render.py `_render_block` (:356-384), the `_ROW_ICONS`
  map (:1479-1492), `_row_label` (:1497-1528), `_row_icon` (:1531-1537). A new kind added in the
  parser compiles clean while several render switches silently fall through; pyright strict
  cannot see it (the F6 class).
- **Solution direction:** a typed discriminant (Literal or enum, stdlib, R7-safe) driving the
  render dispatch through mappings, so a missing arm is a type error.
- **Related (Speculative):** `RenderOptions.reminders_full/reminders_compact/hljs` and
  `_segment_category`'s category strings are the same shallow-discriminant pattern at lower
  stakes (read at one or two sites; several already "fail closed on unknown", the tell).
- **Contract ties:** F6, R7.

### 9th . C11 - Split the short-key band math from its query (NEW 2026-07-24)
`[PROPOSED]` . Strength: **Worth exploring** . Tier: VERIFIED at 1517bba . in-process
- **Files:** `catalog.py`
- **Problem:** `_short_key` (catalog.py:131-148) decides whether a 12-hex citation key must
  extend and to what length - pure string math (the prefix band `low = candidate + "0"*(...)`,
  `high = candidate + "f"*(...)`, lines :137-140) - but it is welded to `conn.execute` at
  :142-145, so the only seam to test the extension rule is standing up a database with a
  colliding row. Surfaced by the pipeline lens, verified first-hand.
- **Solution direction:** split the pure "given existing prefixes, choose a length" function
  from the `conn.execute` collision lookup, exposing the arithmetic at a direct seam. Small,
  and it is the same public-pure-transform shape as C3 in a lower-risk module.
- **Contract ties:** F5 (the band query rides the PK index deliberately; keep that).

### 10th . C10 - A catalog read-scope for relocate
`[TICKETED-12b]` . Strength: (was Speculative) . Tier: VERIFIED + CONTRACT (ticket 12b list)
- **Files:** `relocate.py`
- **Problem, as filed:** `relocate._catalog_conn` opened a fresh connection per helper call and
  the per-candidate lookup ran inside the candidate loop; one plan churned connections.
- **PARTIALLY CLOSED 2026-07-24 (commit 8738423), re-verified this review.** The O(N)-per-
  candidate churn F5 named is GONE: `_encoded_moves` threads the single shared connection into
  its candidate loop (`registry.cwds_for_encoded_dir(conn, ...)` at relocate.py:497, using the
  `conn` opened once in `_compute` at :560), documented at :495-496. What remains is O(1)
  per-apply churn: `_project_for_cwd` (relocate.py:527-534) and `_encoded_owner` (:751-758) each
  open their own connection, both called from `_preflight` (once per apply, not per candidate).
  Constant per apply, not a scaling bug.
- **Solution direction:** have `_preflight` accept the live conn (as `_encoded_moves` already
  does) and inline `project_for_path(conn, ...)`, retiring the two helper opens. This is the
  same "finish the one-connection-per-computation intent" the code already argues for at :559.
- **Why not BUILT:** the F5 defect is closed but the ceremony remains; overlaps C2/C6.

---

## Verified healthy (cleared - no candidate)

- `[CLEARED]` **The store foundation** - store.py hides O_EXCL takeover races and atomic writes
  behind put / get / acquire_lock / verify_walk. Deep by construction.
- `[CLEARED]` **The ingestion seam** - capture.capture_transcript is one deep leverage point
  with three adapters (hook, sweep, migrate); no caller re-implements dedupe or error paths.
- `[CLEARED]` **The parser and render public seam** - `parse_session`, `build_conversation`,
  `render_markdown`, `render_html`, `build_manifest` are public and tested in-memory. This is
  the positive model C3 asks the two risky verbs to match; the markdown-hardening pure
  transforms (`_fence`, `_harden`, `_md_to_html`) sit at clean direct string seams too.
- `[CLEARED]` **The oracle suite discipline** - black-box only, the F5 zero-object-reads
  negative proven with an audit hook, atomic_write fault-injected cleanly.
- `[CLEARED . post-scan proof]` **atomic_write mode preservation (2026-07-19)** - relocate
  exposed a silent permission reset present since slice 01; fixed once in the one primitive,
  every caller inherited it. Locality doing exactly what this board keeps asking for.
- `[CLEARED . 2026-07-24]` **C8 page-chrome seam - BUILT.** The `RenderOptions.hljs` mode plus
  `render._hljs_block`, with share setting `inline` at both call sites (commit 0cd4146),
  implemented DESIGN 15 item 8. Two real adapters (personal CDN chrome, shared inline chrome)
  justify the seam. Moved off the active board into the healthy panel as the built exemplar.

## Not on the board (owned elsewhere - reviews stop re-suggesting)

- The remaining hand-rolled flag scanners in cli.py (`_sweep_source`, `_render_flags`): ticket
  13 closed WITHOUT removing them; two survive deliberately and now document why (sweep takes
  one option; the content flags reach build/render through `load_config(flags=...)`). Whether
  the survivors are a candidate is a fresh-review question; no ticket owns them now.
- config.toml parsed in three modules: RESOLVED 2026-07-24. config.py is now the only module in
  src/ importing tomllib (relocate's reader went in 03ca402, share's in f9b7bbd). It was
  understated as R9 duplication: in share it was a publish-path leak (an XDG-tier
  `redact_patterns` rule ignored, its content published).
- Relocate's catalog connection churn: card C10 above (partially closed).

## Provenance and change log

- **2026-07-24 - FRESH REVIEW, snapshot moved 56262f6 -> 1517bba.** Ran
  `/mattpocock-skills:improve-codebase-architecture`: 3 Explore lens scans (pipeline core /
  orchestration / testability) over the git hot-spot census, then first-hand operator
  verification of every load-bearing line ref before folding (the lens reports agreed with the
  independent verification where they overlapped, which raised confidence; the three NEW
  pipeline claims - `_short_key` band math, the duplicated head column list, the 3x sha256
  recompute - were each spot-verified). Outcome: every file:line re-derived at 1517bba, so the
  decay banner is retired. RE-RANKED: C3 -> 1st (strongest, cost MEASURED, surface widening,
  its 12b home closed without it), C1 -> 3rd (re-located: parse-once holds inside parser.py,
  the real violation is the emitter orchestration seam, 5 extractions per projection), C2 -> 2nd
  (grew: 4 module + 4 CLI copies), C6 -> 5th and expanded (Strong), C9 -> Strong (was
  Speculative; duplication is total), C8 -> BUILT and moved to the healthy panel. NEW card C11
  (short-key band math behind a connection). C10 re-confirmed partial. Top recommendation: C3.
  Mermaid validation: mmdc unavailable on this machine; the single diagram is browser-rendered
  only (recorded, not claimed as validated).
- **2026-07-24 - state fold** (superseded by the fresh review above): C8 BUILT, C10 partial, C3
  home closed without it, config-parser resolved; folded without re-verifying refs.
- **2026-07-19 - Board created** from a review at master `a909cc0`, citations re-checked at
  `56262f6`. All candidates PROPOSED except C10. Superseded by the 2026-07-24 fresh review.
