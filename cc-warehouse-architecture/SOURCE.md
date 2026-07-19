# cc-warehouse architecture-review board - canonical SOURCE

> **This file is the canonical record of cc-warehouse's code-architecture review board.**
> `index.html` is the VIEW rendered from this file by `/architecture` - edit THIS, then
> regenerate. Never hand-author findings into the HTML.
> **Scope guard:** the contract docs (`docs/BRAINSTORM.md`, `SPEC.md`, `DESIGN.md`,
> `FINDINGS.md`, `HARNESS.md`) are LOCKED. This board never edits them and never relitigates
> their decisions; a candidate that needs a contract change says so and waits for the
> principal's ruling (the card-8 pattern).
>
> **Snapshot:** review run 2026-07-19; the review walked the tree at master `a909cc0` and every
> citation was re-checked at master `56262f6` after the slice-12 split landed (only
> `src/cc_warehouse/store.py` changed between the two, +13 lines; its cited ranges verified to
> still hold). All file:line evidence pins to `56262f6`. Line refs decay as src moves; a fresh
> review re-verifies, the renderer only flags.
> **Method:** 3 background Explore lens scans (pipeline core / orchestration / testability)
> over the git hot-spot census (60 commits), every load-bearing claim re-verified first-hand
> before entering this board.
> **Vocabulary:** module, interface, implementation, depth (deep/shallow), seam, adapter,
> leverage, locality (the /codebase-design glossary).
>
> **States:** `PROPOSED` (awaiting the grilling conversation) / `GRILLING` (in conversation) /
> `TICKETED-<nn>` (owned by a harness ticket; the ticket is the claim) / `BUILT` (landed,
> verified) / `REJECTED` (recorded so reviews stop re-suggesting it).
> **Evidence tiers:** `VERIFIED` (first-hand at the snapshot commit) / `CONTRACT` (a DESIGN or
> ticket line is the claim) / `AGENT-REPORTED` (lens-scan context beyond the verified lines).

---

## The board (recommended order)

### 1st . C1 - Parse once: one parse product
`[PROPOSED]` . Strength: **Strong** . Tier: VERIFIED . in-process
- **Files:** `src/cc_warehouse/parser.py` . `render.py` . `build.py`
- **Problem:** parser sells two products over the same bytes (parse_session,
  build_conversation), each re-running `_extract_entries` (parser.py:158, :403). render's
  emitters take raw bytes, so build's one projection extracts the payload five times
  (render.py:375-377, 726-727, 740; build.py:84-86). DESIGN section 4 says parse ONCE; the
  interface defeats it.
- **Solution direction:** one parse entry extracts once and yields metadata plus conversation
  together; emitters accept the parsed model, bytes kept only at the edge. Interface shape =
  grilling-stage, not decided here.
- **Wins:** leverage (one parse, three emitters) . locality (extraction quirks in one
  function) . 5x parse cost gone before the ~7k-session migrate and v1.1 FTS5 . makes the
  DESIGN parse-ONCE sentence true (R8).
- **Contract ties:** R8, R9; DESIGN section 4.
- **Why 1st:** zero contract risk, no collision with the 12a/12b queue, and the modules are
  done and frozen by black-box output tests, so the refactor verifies itself. Feeds C5.

### 2nd . C2 - Deepen the batch-verb protocol
`[PROPOSED]` . Strength: **Strong** . Tier: VERIFIED . in-process
- **Files:** `reports.py` . `cli.py` . `sweep.py` . `build.py` . `migrate.py` . `relocate.py`
- **Problem:** the lock primitive is deep (store.py:192-271) but its ceremony is copied: the
  sentinel triple plus acquire-or-refuse plus finally-release appears in sweep.py:24-29/
  137-151, build.py:218-227/247-280, migrate.py:34-39/99-119, relocate.py:39-40/634-641;
  cli.py re-implements the lock-held detector, failure loop, count, summary, and exit policy
  five times (cli.py:187-195, 242-250, 491-502, 597-617, 684-698). reports.py is a 19-line
  pass-through that fails the deletion test.
- **Solution direction:** reports.py absorbs the protocol (run a batch body under
  locks/<op> or return the standard lock-held report; one console-plus-exit presenter). Verbs
  keep their bodies; the lock stays store's O_EXCL primitive.
- **Wins:** leverage (v1.1 `ccw import` inherits the protocol) . locality (R10/R14
  presentation in one module) . deletes four sentinel triples and five CLI blocks.
- **Contract ties:** R9, R10; R14 untouched. Timing: 12a, 12b, and 13 all touch cli.py.
- **Why 2nd:** best done before the cli.py queue lands and before a fifth copy appears.

### 3rd . C3 - Make the risky transforms public and I/O-free
`[PROPOSED]` . Strength: **Strong** . Tier: VERIFIED (call-pattern census AGENT-REPORTED,
spot-verified) . in-process
- **Files:** `share.py` . `relocate.py`
- **Problem:** the correctness-critical logic of the two riskiest verbs is pure
  transformation, yet private behind Config-plus-disk entry points: share's detectors
  `_scan_secrets` / `_is_generic_secret` / `_redact_tree` (share.py:117-278, only share()
  public) and relocate's JSON-aware rewriter `_form_patterns` / `_sub_text` / `_sub_tree` /
  `_rewrite_bytes` (relocate.py:114-184, only plan/apply public). Locality lost: a redaction
  miss lives in _scan_secrets but the catching test runs three process boundaries away
  (test_share_regressions.py:30-49). Share/relocate/sweep/migrate test files drive the CLI
  only; direct imports are zero.
- **Solution direction:** public, I/O-free interfaces: decoded text in, hits out; text or
  JSON node plus mapping in, rewritten result out. Verbs keep the I/O shell.
- **Wins:** the interface becomes the test surface for the riskiest logic . a new redaction
  rule is a one-line in-memory assertion . oracle tests stay locked, future tests get cheap.
- **Contract ties:** ticket 12b re-opens exactly the relocate rewriter surface (its
  carried-forward findings are rewriter-core defects); fold the rewriter seam into 12b's work
  order. The share half stands alone, not gated on 12b.
- **Why 3rd:** biggest testability payoff; the relocate half now has a natural home.

### 4th . C4 - Give the head concept one home: a catalog read seam
`[PROPOSED]` . Strength: **Strong** . Tier: VERIFIED . in-process
- **Files:** `catalog.py` . `build.py` . `share.py` . `cli.py`
- **Problem:** "a head is a row no other row supersedes" has no owner: the predicate SQL is
  typed verbatim twice (build.py:137, :167) while head_for_short's docstring claims "one
  owner, R9" (build.py:156), an overclaim (R8/F6); `_Head` is private so share re-declares
  the identical five-field shape as `_Resolved` (share.py:73-82) and copies field-by-field
  (:320-328); cli runs its own SELECTs (cli.py:300, :422); test helpers hardcode schema SQL
  (conftest.py:390-402).
- **Solution direction:** catalog.py owns the head predicate, a public head-record type, and
  the read queries; build, share, cli consume them. Reads stay catalog-only (R6 unchanged).
- **Wins:** locality (version-chain semantics beside the schema) . leverage (v1.1 search and
  v1.2 MCP read the same seam) . deletes the shape copy . makes the docstring true (R8).
- **Contract ties:** R6, R8, R9.
- **Why 4th:** smallest diff of the strong four; high leverage for v1.1/v1.2.

### 5th . C5 - One turn walker, two serializers
`[PROPOSED]` . Strength: Worth exploring . Tier: VERIFIED . in-process
- **Files:** `render.py`
- **Problem:** above the shared per-block fragment the traversal is written twice:
  `_render_turn` (render.py:314) and `_turn_html` (:675) carry the byte-identical
  synthetic-skip guard (:315, :678) and the same prompt/reminders/blocks order. A turn-policy
  change is two edits with nothing keeping them in lockstep; the doubling is why render.py is
  747 lines.
- **Solution direction:** hoist the traversal into one walker yielding typed units; markdown
  and HTML become thin serializers. Outputs frozen by black-box tests.
- **Wins:** locality (turn policy decided once) . one implementation of the walk (R9) . pairs
  with C1's single parse product.
- **Contract ties:** R9.

### 6th . C6 - cli.py: verbs hand back results, not cursors
`[PROPOSED]` . Strength: Worth exploring . Tier: VERIFIED . in-process
- **Files:** `cli.py` . `build.py` . `relocate.py`
- **Problem:** the dispatch is thin but the implementation carries verb logic: catalog opens
  and the no-row-vs-superseded policy (cli.py:297-310), the project-exists SELECT (:419-430),
  the F9 out-guard `_out_under_warehouse` (:340-356) which does not travel to non-CLI callers
  (v1.2 MCP), and halted-run recovery keyed on relocate's action strings (:608-614).
- **Solution direction:** verbs own their reads and guards, return result plus exit intent;
  cli keeps parsing, printing, exit codes. Scoped to EXCLUDE flag parsing and config layering
  (ticket 13 owns those).
- **Wins:** locality (one file per verb change) . the F9 guard travels with the operation .
  leverage (v1.2 MCP reuses whole verbs).
- **Contract ties:** F9; tickets 12a/12b/13 all touch cli.py; 12a's plan-advisory consent-gap
  finding overlaps the action-string coupling. Let 12a/12b land first.

### 7th . C7 - Type the Block discriminant
`[PROPOSED]` . Strength: Worth exploring . Tier: VERIFIED . in-process
- **Files:** `parser.py` . `render.py`
- **Problem:** Block.kind is a bare str spanning nine values; the taxonomy and field-validity
  rules live only in a docstring (parser.py:258-272); render re-derives the switch three ways
  (render.py:242, 262, 643/668). A missed or renamed kind silently drops content; pyright
  strict cannot see it (the F6 class).
- **Solution direction:** a typed discriminant (Literal or per-kind types, stdlib, R7-safe)
  so exhaustiveness is compile-checked.
- **Wins:** F6 silent loss becomes a type error . the interface carries the taxonomy.
- **Contract ties:** F6, R7.

### 8th . C8 - A page-chrome seam in render_html
`[PROPOSED]` . Strength: Worth exploring . Tier: VERIFIED + CONTRACT (DESIGN 15 item 8) .
in-process . **contract callout**
- **Files:** `render.py` . `share.py`
- **Problem:** render_html emits content and chrome as one indivisible page; the highlight.js
  script tag pointing at cdnjs.cloudflare.com is appended unconditionally (render.py:536-540,
  :710). share's only render path is build.write_projection (share.py:389), so every page of
  a published share pings the CDN per viewer. No adapter exists between conversation content
  and page chrome.
- **Solution direction:** a seam between content emission and chrome assembly; personal keeps
  the CDN plus fallback per DESIGN section 6, shares gain the ability to inline or omit.
- **Contract callout:** DESIGN section 15 item 8 explicitly holds shares-inline-vs-CDN OPEN,
  and the grill round locked shares to the personal renderer and theme. This card proposes
  only the seam that makes the open decision implementable; the share behavior itself is the
  principal's contract call.
- **Wins:** two adapters justify the seam (personal chrome, share chrome) . unblocks the item
  8 decision.

### 9th . C9 - One source walker, two policies
`[PROPOSED]` . Strength: Speculative . Tier: VERIFIED . in-process
- **Files:** `sweep.py` . `migrate.py`
- **Problem:** sweep._walk_source (sweep.py:44-76) and migrate._walk (migrate.py:42-82) copy
  the same ~30-line os.walk onerror/suffix/sort scaffold; only the per-file policy differs
  (sweep skips agent-*, migrate keeps them and names non-regular dirents).
- **Solution direction:** one enumerator taking a classify callback; each verb keeps its rule.
- **Deletion test:** concentrates, modestly.

### 10th . C10 - A catalog read-scope for relocate
`[TICKETED-12b]` . Strength: (was Speculative) . Tier: VERIFIED + CONTRACT (ticket 12b
carried-forward list)
- **Files:** `relocate.py` (ceremony also in status.py, share.py)
- **Problem:** relocate._catalog_conn opens and closes a fresh connection per helper call
  (relocate.py:335-359) and _cwds_for_encoded runs inside the per-candidate loop (:313); one
  plan churns connections.
- **State note:** superseded as a candidate on 2026-07-19: ticket 12b's carried-forward
  findings name this exact churn ("every candidate opens its own SQLite connection ... two
  full home reads before the first mutation", F5). Scheduled work owned by 12b; the analysis
  is kept for the record.

---

## Verified healthy (cleared this review - no candidate)

- `[CLEARED]` **The store foundation** - store.py hides O_EXCL takeover races and atomic
  writes behind put / get / acquire_lock / verify_walk. Deep by construction.
- `[CLEARED]` **The ingestion seam** - capture.capture_transcript is one deep leverage point
  with three adapters (hook, sweep, migrate); no caller re-implements dedupe or error paths.
- `[CLEARED]` **The render surface** - 747 lines behind three public functions (the depth
  exemplar; C5 concerns its internals, not its interface).
- `[CLEARED]` **The oracle suite discipline** - black-box only, the F5 zero-object-reads
  negative proven with an audit hook, atomic_write fault-injected cleanly (test_store.py).
- `[CLEARED . post-scan proof]` **atomic_write mode preservation (2026-07-19)** - relocate
  exposed a silent permission reset on every rewrite, present since slice 01; fixed once in
  the one primitive, every caller inherited it, pinned by tests/test_store_regressions.py.
  Locality doing exactly what this board keeps asking for.

## Not on the board (already owned elsewhere - reviews stop re-suggesting)

- The five hand-rolled flag scanners in cli.py - ticket 13 ("full flag layering lands in
  slice 13" annotations at cli.py:153, :258, :625).
- config.toml parsed in three modules (config._webhooks_from_root, share._custom_patterns,
  relocate._relocate_roots) while Config's redact_patterns / relocate_roots / voice_* /
  inbox fields sit unpopulated - ticket 13 ("COMPLETE it in place; a parallel loader is a
  rejection, R9").
- Relocate's catalog connection churn - ticket 12b (see C10 above).

## Provenance and change log

- **2026-07-19** - Board created from this session's review: 3 Explore lens scans (pipeline
  core / orchestration / testability) plus first-hand verification of every load-bearing
  claim at master `a909cc0`; citations re-checked at `56262f6` after the slice-12 split
  landed (contract rulings fcadd7e, ticket split 69f27e6, build order 56262f6). All
  candidates PROPOSED except C10 TICKETED-12b. Top recommendation: C1 (runner-up C2). The
  board supersedes the ephemeral scratchpad report this review first rendered to. Mermaid
  validation: mmdc unavailable on this machine; diagrams are browser-rendered only (the
  /architecture command validates with mmdc when it is available).
