# cc-warehouse architecture-review board - canonical SOURCE

> **This file is the canonical record of cc-warehouse's code-architecture review board.**
> `index.html` is the VIEW rendered from this file by `/architecture` - edit THIS, then
> regenerate. Never hand-author findings into the HTML.
> **Scope guard:** the contract docs (`contract/BRAINSTORM.md`, `SPEC.md`, `DESIGN.md`,
> `FINDINGS.md`, `HARNESS.md`) are LOCKED. This board never edits them and never relitigates
> their decisions; a candidate that needs a contract change says so and waits for the
> principal's ruling (the card-8 pattern).

> **Snapshot: FRESH REVIEW 2026-08-23, master `4824098`.** This supersedes the 2026-07-24
> review at `1517bba`, which was NOT decayed but DESTROYED: the repository was deleted and
> re-created on 2026-08-10 (ticket 28.20, the go-public audit), which rewrote history, so
> `1517bba` no longer exists anywhere and could not be diffed against. Every `file:line`
> below was RE-DERIVED at `4824098` (257 commits) and re-verified first-hand; the decay
> banner this file carried since 2026-08-21 is retired.
>
> **Method, ticket 28.13.** The named review skill (`/mattpocock-skills:improve-codebase-
> architecture`) is not enabled in this session's plugin config, so this review substituted
> 5 parallel read-only Explore agents covering the same lens split as before (pipeline core,
> orchestration, the risky-transform verbs, the catalog/head seam) plus a new lens for
> `archive.py` - a 900+ line module that did not exist at the 2026-07-24 review and now owns
> most of what the tool does. Every agent's claims were re-derived at HEAD, not carried
> over, and the two claims consequential enough to change a user-facing decision were
> independently re-verified by reading the cited source directly, not trusted from the
> agent report alone (the standing rule: a lens report is evidence to reconcile, never a
> settled finding).
>
> **Two claims turned out to be live, current bugs, not architecture debt, and were fixed
> the same session rather than left as PROPOSED-only findings** - see C12 and C6 below for
> which parts of each are BUILT and which parts (the actual deepening) are still open.
>
> **Vocabulary:** module, interface, implementation, depth (deep/shallow), seam, adapter,
> leverage, locality (the /codebase-design glossary).
>
> **States:** `PROPOSED` (awaiting the grilling conversation) / `GRILLING` (in conversation) /
> `TICKETED-<nn>` (owned by a harness ticket; the ticket is the claim) / `BUILT` (landed,
> verified) / `REJECTED` (recorded so reviews stop re-suggesting it).
> **Evidence tiers:** `VERIFIED` (first-hand at the snapshot commit, by the operator or this
> session directly reading the source) / `AGENT-REPORTED` (re-derived at HEAD by one of the
> 5 lens agents, spot-checked where consequential but not independently re-read line by
> line) / `CONTRACT` (a DESIGN or ticket line is the claim).
>
> **Build state:** v1 is CLOSED. Since the 2026-07-24 review, a major "archive-first layout"
> rewrite landed (tickets 19, 21, 25, 27, 29, 30) that this board had never looked at until
> now - `archive.py` is now the real write path for both sessions and sub-agents, and three
> of this review's new findings come from it.

---

## The board (recommended order - RE-RANKED at the 2026-08-23 review)

### 1st . C12 (NEW) - One replace-if-larger primitive, not three copies
`[PROPOSED]` . Strength: **Strong** . Tier: VERIFIED at 4824098 . in-process
- **Files:** `archive.py`
- **Problem, and it is not hypothetical - it already happened twice in one day.**
  `write_session_folder`, `write_source`, and `write_subagent` each carry their own
  inline copy of "a larger payload replaces the JSONL, a smaller one is refused, equal
  size means equal content." Ticket 30 (2026-08-23, earlier this session) found and fixed
  a real defect in this rule as written in `write_session_folder`: equal SIZE was being
  read as proof of equal CONTENT, in violation of R1/F1 (size only ever answers "which of
  two payloads KNOWN to differ is larger," never "are these the same bytes"), so a
  same-length re-capture with different bytes silently rendered the wrong pages over a
  correctly-untouched JSONL. That fix was applied to ONE of the three copies. The
  2026-08-23 architecture re-review then found the SAME unfixed defect, independently,
  in `write_subagent` - there it was worse, because a sub-agent has no manifest.json to
  even record a refusal in, so the loss was not just mis-rendered, it was completely
  invisible (F6). **Both of those specific bugs are now fixed** (same session, see
  below) - the candidate itself, the fact that the rule lives in three places that have
  to be kept in agreement by hand, is not.
- **Current state of the three copies:** `write_session_folder` (archive.py, the
  session writer) and `write_subagent` (archive.py, the sub-agent writer) BOTH now
  correctly compare bytes at equal size, each with its own `refused_equal_size` field
  (`FolderResult`/`SubagentResult`) and its own near-identical block of logic.
  `write_source` (archive.py, the hook's synchronous durability write) still only
  compares size - deliberately left alone, because it is always followed by
  `write_session_folder` running on the same bytes, which is what actually decides
  what renders; `write_source`'s own comment used to claim it followed
  `write_session_folder`'s rule "exactly," which stopped being true the moment that
  rule got finer, and was corrected in the same session rather than left stale.
- **Solution direction:** one shared function - e.g. `_replace_if_larger(path, data) ->
  ReplaceOutcome` (`REPLACED` / `REFUSED_SMALLER` / `REFUSED_EQUAL_MISMATCH` / `NOOP`) -
  that all three callers use, so a future fourth defect in this rule needs fixing once,
  not remembered and reapplied three times under time pressure, which is exactly what
  happened here.
- **Wins:** correctness (one rule, one place it can be wrong) . the F6 "never silent"
  property becomes provable once instead of audited three times . leverage (a future
  writer - the review's C13/C14 candidates both touch archive.py - inherits the correct
  rule for free).
- **Contract ties:** R1 (as amended), R5, F1, F6.
- **Why 1st:** the only candidate on this board with a PROVEN, not argued, recurrence -
  the same defect class was independently found live twice in one session, and the
  duplication is what let the second instance survive a fix aimed at the first.

### 2nd . C6 - cli.py: verbs hand back results, not cursors
`[PROPOSED, one sub-finding BUILT 2026-08-23]` . Strength: **Strong** . Tier: VERIFIED at 4824098 . in-process
- **Files:** `cli.py` . `build.py` . `registry.py` . `relocate.py` . `share.py`
- **Problem, four parts, three still open, re-verified at current line numbers:**
  - (a) still valid, unchanged: the render no-row-vs-superseded policy is stranded in
    `_render_session` (`cli.py:863-920`), including a raw `SELECT 1 FROM session WHERE
    short = ?` (:878-881), while `build.head_for_short` owns only the head selection.
  - (b) still valid, unchanged: project-exists SELECTs are inline in `_run_project`
    (`cli.py:1036-1097`) even though the actual mutations route through `registry.py`.
  - (c) still valid, and **its live consequence was found and fixed this session.**
    `_out_under_warehouse` (`cli.py:933-949`) guards `build.write_projection` at exactly
    one of its five call sites (`_render_adhoc`, `cli.py:964`). The two `share.py` call
    sites (`share.py:464`, `:528`, both with `force=True`) had NO such guard, so
    `ccw share --out <path inside the warehouse>` could write straight into
    `objects/`/`projections/` - an F9 violation, not a style issue. **BUILT 2026-08-23**:
    `_run_share` (`cli.py`) now calls the SAME `_out_under_warehouse` guard before
    writing, reusing rather than duplicating it. The underlying structural problem this
    card names - the guard lives at the CLI layer instead of inside `write_projection`
    itself, so a future sixth call site can reintroduce the same gap - is NOT fixed;
    only this session's live instance of it is.
  - (d) still valid, unchanged: halted-run recovery already uses a typed accessor
    (`relocate.applied_changes`, `relocate.py:76-78`) rather than string-matching -
    this part of the original claim turned out to already be fixed by an earlier,
    unrelated change, confirmed by reading the current code, not carried over as
    still-broken.
- **Solution direction:** verbs own their reads and guards and return a typed result;
  registry.py gains the project read side; **the write-guard moves INTO
  `write_projection` itself** (not just reused at one more call site, which is what the
  2026-08-23 fix does) so every caller, present or future, gets it automatically.
- **Wins:** locality (one file per verb change) . the F9 guard travels with the write,
  permanently, instead of needing to be remembered at each new call site . leverage
  (v1.2 MCP reuses whole verbs).
- **Contract ties:** F9. Overlaps C2 (both concern cli.py's batch/verb shell) and C4/C12.
- **Why 2nd:** (c) just demonstrated, concretely, what this card has been warning about -
  a safety guard that lives at the call site instead of the primitive gets missed at a
  new call site. Ranked above C1/C2 because it already had one confirmed live
  consequence; below C12 because C12's recurrence was proven twice, this only once.

### 3rd . C3 - Make the risky transforms public and I/O-free
`[PROPOSED]` . Strength: **Strong** . Tier: VERIFIED at 4824098 . in-process
- **Files:** `share.py` . `relocate.py`
- **Problem, re-verified, still holds in full.** `share.py`'s redaction/scan logic
  (`_custom_patterns` :91, `_builtin_patterns` :120, `_redaction_patterns` :159,
  `_redact_value` :168, `_redact_tree` :202, `_redact` :223, `_is_generic_secret` :261,
  `_scan_secrets` :279) and `relocate.py`'s path-rewrite logic (`_form_patterns` :169,
  `_sub_text` :198, `_sub_tree` :204, `_tree_matches` :228, `_references` :242,
  `_rewrite_bytes` :263) are all still underscore-private, unchanged in kind since the
  last review.
- **The public surface widened FURTHER than previously described:** `share.py` now has
  4 public entry points (`share` :384, `prepare_comparison` :542, `commit_comparison`
  :597, `discard_comparison` :612 - the last three added for the `--EXPOSED` gate), all
  still I/O orchestrators delegating to the same private helpers, so the core claim is
  unaffected; the old "only `share()` is public" framing is simply out of date.
- **Test-seam cost CONFIRMED, and now spans MORE files.** A census of every test file
  found zero in-process calls into either module's private logic; the only in-process
  imports (in `test_relocate_regressions.py`/`test_share_regressions.py`) read source
  text for a meta-assertion, never call a function. Eight test files now exercise this
  logic exclusively through `run_ccw` subprocess invocations (five for relocate, three
  for share), including the newer `--EXPOSED` path.
- **Solution direction:** promote thin public transforms - `redact_payload(text,
  patterns) -> (str, hits)`, `scan_secrets(text) -> findings`, `rewrite_bytes(path, text,
  patterns)`, `references(path, text, patterns)` - so the shape census asserts against
  the transform directly and the subprocess covers only real I/O.
- **Wins:** the interface becomes the test surface for the riskiest logic . a new
  redaction rule or path shape is a one-line in-memory assertion . render.py and
  parser.py already prove the pattern.
- **Why 3rd (was 1st):** the reasoning is unchanged and still Strong, but C12 and C6 both
  now have a PROVEN live consequence this session; C3's cost is real and measured but
  has not (yet) produced a caught defect the way the other two just did.

### 4th . C1 - Parse once: one parse product
`[PROPOSED]` . Strength: **Strong, WORSE than described** . Tier: VERIFIED at 4824098 . in-process
- **Files:** `render.py` . `build.py` . `archive.py`
- **Problem, confirmed and grown.** Per session, `render_markdown` (`render.py:1185-
  1199`) calls `build_conversation` + `parse_session` + `sha256_hex`; `render_html`
  (`:2187-2204`) calls all three again; `build_manifest` (`:2238-2295`) calls
  `build_conversation` + `sha256_hex`. That is `build_conversation` x3, `parse_session`
  x2, `sha256_hex` x3 per projection write, orchestrated by `build.iter_projection_files`
  (`build.py:230-277`) - unchanged from the original finding.
- **What is NEW since the last review: `archive.py` duplicates on top of this rather
  than replacing it.** `write_session_folder` (the real entry point since the
  archive-first rewrite, used by both `build._mirror` and `ccw archive --to`) calls
  `parse_session` again for directory naming (`archive.py:603`), again conditionally on
  a refusal (`:652`), and `sha256_hex` again to check currency (`:663`) - THEN calls
  `iter_projection_files`, which fires the whole render.py-side redundancy again inside
  that. Worse: `build.build()` (`build.py:585-655`) can call BOTH `write_projection`
  (:636, when `keep_projections` is set) AND `_mirror` -> `write_session_folder` (:640)
  for the SAME payload unconditionally when both trees are configured, so today's worst
  case per session head is `build_conversation` up to x6, `parse_session` up to x5,
  `sha256_hex` up to x7 - a multiplicative-per-configured-tree cost, not the
  additive-per-file one the last review measured.
- **Solution direction:** hoist parsing to the orchestrator - build the models once and
  pass them into every emitter and into archive.py's own decision points, keeping a
  thin bytes-taking wrapper for the black-box tests.
- **Wins:** leverage (one parse, N emitters) . locality . a real, now-larger, measurable
  cost removed before v1.1's FTS5 work adds another reader.
- **Contract ties:** R8, R9; DESIGN section 4.
- **Why 4th (was 3rd):** still Strong, and the stakes GREW (multiplicative, not
  additive), but C12/C6/C3 all rank above it on correctness or proven-recurrence
  grounds; this remains a pure performance/redundancy argument, not a caught defect.

### 5th . C2 - Deepen the batch-verb protocol
`[PROPOSED]` . Strength: **Strong, WORSE than described** . Tier: VERIFIED at 4824098 . in-process
- **Files:** `reports.py` . `cli.py` . `sweep.py` . `build.py` . `migrate.py` .
  `relocate.py` . `import_tree.py` . `archive.py`
- **Problem, confirmed and grown from 4 to 6 copies.** The lock-acquire-or-refuse plus
  `try/finally`-release shell is now duplicated in SIX modules, not four: `sweep.py`
  (:381, :421-422), `migrate.py` (:114, :133-134), `build.py` (:612, :654-655),
  `relocate.py` (:972, :978-979), and two that postdate the last review -
  `import_tree.py` (ticket 25.4; :196, :219-220, a near line-for-line copy of
  migrate.py's shell) and `archive.py` (ticket 19/30; :749, :756-757, whose refusal is
  reported through a bespoke `MigrationReport.lock_held` field instead of the other
  five modules' shared `ItemOutcome` shape - the duplication is now wider AND less
  uniform). `reports.py` is unchanged at 19 lines, still owning only the failure filter;
  every verb still hand-rolls its own counts and exit policy.
- **cli.py's report/tally half also grew, from 4 to 6 current instances**
  (`_run_sweep` :591-658, `_run_build` :746-790, `_run_migrate` :1174-1219, `_run_import`
  :1222-1310, `_run_relocate` :1530-1624, `_run_archive` :1374-1438 - the last with its
  own third variant of the lock-held check), plus a 7th partial instance in
  `_run_reindex` (:1467-1520, the tally half with no lock to acquire).
- **Solution direction:** unchanged - a `with_lock(root, name) -> BatchReport` runner
  plus a shared `render_batch(report) -> exit_code` in reports.py, so each verb hands in
  only its body.
- **Wins:** leverage (a future verb, e.g. v1.1 `ccw import`'s successor, inherits the
  protocol for free) . locality . deletes six sentinel triples and six-plus CLI mirrors
  instead of four of each.
- **Contract ties:** R9, R10; R14 untouched.
- **Why 5th (was 2nd):** the duplication measurably grew, which argues for MORE urgency,
  but C12/C6/C3/C1 all have either a proven live defect or a larger measured cost;
  ranked by what a fix actually buys, this is real but has not yet bitten anyone.

### 6th . C7 - Type the Block discriminant
`[PROPOSED]` . Strength: **Worth exploring, WORSE fan-out, concrete drift proof found** . Tier: VERIFIED at 4824098 . in-process
- **Files:** `parser.py` . `render.py`
- **Problem, confirmed, with new evidence it is not hypothetical.** `Block.kind`
  (`parser.py:438-458`, the `kind: str` field at :448) is still a bare str, its legal set
  enumerated only in a docstring. **The docstring is already wrong**: `thinking_withheld`
  is constructed as a real kind (`parser.py:641`, ticket 20) and switched on correctly in
  render.py (:576), but was never added to the docstring's enumeration - exactly the
  failure this card warns about, caught in the act rather than argued for.
- **Fan-out is larger than previously described:** beyond the originally-named switch
  sites (`_PHASE_CATEGORY` parser.py:525, `_segment_category` :536-541, `_render_block`
  render.py:551-599, `_ROW_ICONS` :1840, `_row_label` :1859-1891, `_row_icon` :1894-1900),
  a census found kind comparisons clustered in `_phase_meta` (render.py:694-761, at
  least 7 separate comparisons) plus more across `_block_html`/`_section_html` and
  parser.py's own entry-classification code - roughly 15+ sites total, not ~7.
- **Solution direction:** a typed discriminant (`Literal` or enum, stdlib, R7-safe)
  driving render dispatch through mappings, so a missing arm is a type error and a
  future `thinking_withheld`-shaped addition cannot silently drift the docs again.
- **Contract ties:** F6, R7.
- **Why 6th:** Worth-exploring stakes (nothing is silently WRONG today, just
  under-typed), but the docstring drift is concrete proof the risk is real, not
  speculative - kept above the two brand-new "Worth exploring" cards below on that basis.

### 7th . C13 (NEW) - `folder_is_current`: pure decision logic welded to the filesystem
`[PROPOSED]` . Strength: **Worth exploring** . Tier: AGENT-REPORTED at 4824098 . in-process
- **Files:** `archive.py`
- **Problem.** `_current_manifest` (`archive.py:454-499`) fuses a file-existence check
  and a `manifest.json` read with three PURE dict comparisons (`source_hash`, `config`,
  `renderer_version`, :493-498) that actually decide "is this folder current." Its
  callers `pages_are_current` (:502-520) and `folder_is_current` (:523-544) inherit the
  coupling. There is no way to unit-test "a renderer_version mismatch is detected"
  without writing five real files to a real directory plus a real manifest.json first -
  the same class of problem C11 already names for `catalog._short_key`, in a module
  every incremental build/migrate call goes through.
- **Solution direction:** a pure `_manifest_matches(manifest: dict, source_hash, options)
  -> bool` taking an already-loaded dict, so each of the four independent conditions
  (files-present, hash, config, renderer_version) can be a plain dict-literal test.
- **Contract ties:** none new; same shape as C11.
- **Why NEW:** `archive.py` postdates the last review entirely; this is the first time
  it has been looked at by this board.

### 8th . C4 - Give the head concept one home: a catalog read seam
`[PROPOSED, MOSTLY RESOLVED]` . Strength: **downgraded from Strong** . Tier: VERIFIED at 4824098 . in-process
- **Files:** `build.py` . `catalog.py` . `share.py`
- **The headline finding is CLOSED, not just decayed.** Ticket 29 mechanism 1
  (2026-08-20 - between the two reviews, not caused by either) consolidated the head
  predicate, join, and recency ranking into one shared SQL fragment, `_HEAD_RANK_CTE`
  (`build.py:323-334`), used by both `_heads()` (:337-364) and `head_for_short()`
  (:379-403). `head_for_short`'s docstring, which the last review flagged as a false
  "shares the join" claim, is now TRUE - fixed as part of the same rewrite, not a
  separate docstring patch. `share._Resolved` (`share.py:79-89`) still exists as a
  second dataclass, but only copies fields sourced from `build.heads_for_window`/
  `head_for_short`; it does not re-derive the head SQL. cli.py's head resolution also
  routes through `build.head_for_short` (`cli.py:882`) - the old claim that it ran its
  own separate SELECTs no longer holds.
- **What remains** is a much smaller, cosmetic duplication: `_heads()` and
  `head_for_short()` each still do their own final column SELECT and tuple-to-`_Head`
  unpacking (~15-20 near-identical lines apiece).
- **New, unrelated duplication found in the same area:** `archive._session_rows`
  (`archive.py:835-861`) runs its own JOIN over every session (not just heads,
  deliberately, for migration purposes) that overlaps `_HEAD_RANK_CTE` on two columns -
  its own docstring already self-flags this ("`build._heads` already selects the same
  two columns for exactly this reason"), acknowledged but not deduplicated.
- **Solution direction, narrowed:** if pursued at all, a shared row-unpacking helper
  for `_heads`/`head_for_short`'s final SELECT - a small cleanup, not the structural fix
  the last review called for, since the dangerous part (the predicate that could
  silently diverge) is already fixed.
- **Contract ties:** R6, R8, R9 (R8/F6 overclaim risk is now resolved, not just noted).
- **Why 8th (was 4th):** the correctness-critical half of this candidate is BUILT, by a
  ticket that did not know it was closing an open board item. Left on the board rather
  than cleared, because a real (if now much smaller) duplication remains.

### 9th . C5 - One turn walker, two serializers
`[PROPOSED]` . Strength: **Worth exploring** . Tier: AGENT-REPORTED at 4824098 . in-process
- **Files:** `render.py`
- **Problem, confirmed, one naming correction.** The turn/segment walk is still written
  twice: markdown via `_turn_body` (`render.py:999-1015`, looping `group_segments(turn)`
  and branching on `segment.is_phase`) plus `_user_md` (:1018-1036); HTML via
  `_claude_inner` (:1984-1997, the same loop-and-branch shape) plus `_turn_html`
  (:2000-2072). Leaf rendering is confirmed still single-owner via `_render_block`
  (:551-599, called from `_block_html` :1816-1833) - only the walk itself is doubled, as
  originally described. **Correction:** the function the last review cited as
  `_render_turn` no longer exists under that name; the markdown-side equivalent is now
  split across `_turn_body`/`_user_md`.
- **Solution direction:** unchanged - one turn-walk yielding typed events (Phase / Reply
  / UserHalf), each emitter supplying only leaf rendering.
- **Contract ties:** R9. Pairs with C1.

### 10th . C9 - One source walker, two policies
`[PROPOSED]` . Strength: **Strong** . Tier: AGENT-REPORTED at 4824098 . in-process
- **Files:** `sweep.py` . `migrate.py` . `relocate.py`
- **Problem, confirmed, with a real fix already found alongside it.** `sweep._walk_source`
  (`sweep.py:48-82`) is unchanged in shape. `migrate._walk` no longer exists under that
  name: it was made PUBLIC as `migrate.walk_jsonl` (`migrate.py:42-97`) specifically so
  `ccw import` (ticket 25.4) could reuse it rather than adding a third copy - confirmed
  by reading `import_tree.py`, which calls `migrate.walk_jsonl` directly and defines no
  `os.walk` of its own. **The "does a new module add a third copy" risk this review was
  asked to check did NOT materialize** - the codebase already closed that gap by
  sharing rather than copying.
- **The underlying sweep/migrate duplication itself is unchanged and still near-verbatim**
  (same `os.walk(onerror=...)` shape, same error-message construction, same sorted-return
  convention); the `_JSONL_SUFFIX` constant is now independently defined in FOUR files
  (`sweep.py:40`, `migrate.py:21`, plus `archive.py:37` and `status.py:64` - the latter
  two are filename-string convenience, not walker scaffolding, and should not be folded
  into this card's framing).
- **New adjacent finding:** `relocate._scan_content` (`relocate.py:298-413`) has its own
  THIRD `os.walk(root, onerror=...)` (:360) with the same "turn an OSError into a named
  skip item" shape, serving a different job (content scanning, not JSONL harvesting) -
  worth folding in if this card is ever rewritten, since "two policies" now undercounts
  by one occurrence of the general shape.
- **Solution direction:** unchanged - one `walk_transcripts(root, *, classify)` owning
  the scaffold.

### 11th . C14 (NEW) - No owned 3-way session/subagent/not-a-session discriminant
`[PROPOSED]` . Strength: **Worth exploring** . Tier: AGENT-REPORTED at 4824098 . in-process
- **Files:** `archive.py` . `import_tree.py`
- **Problem.** `archive.py` exposes only two independent booleans, `is_subagent`
  (:163-165) and `is_session` (:168-184), plus `write_not_a_session` (:428-451) for the
  third case, but no function returning the combined 3-way classification. The one
  caller that needs all three, `import_tree._kind` (:84-101), reinvents the combination
  itself with a plain `-> str` return type, checked by string-literal equality
  (`import_tree.py:97-99,114,123`) rather than a typed discriminant - the same C7 shape
  (a typo would not be caught by pyright strict), at lower stakes since only one caller
  exists today. A near-miss already exists: `migrate`'s own loop (`archive.py:810`) uses
  only `is_session`, collapsing subagent and not-a-session into one bucket.
- **Solution direction:** a small combinator, e.g. `classify(data) -> Literal["session",
  "subagent", "not-a-session"]`, that `import_tree._kind` and any future second caller
  can share instead of reinventing.
- **Contract ties:** none new; same shape as C7, lower stakes (one caller today).
- **Why NEW:** surfaced by the same `archive.py` sweep that found C12 and C13.

### 12th . C10 - A catalog read-scope for relocate
`[TICKETED-12b]` . Strength: (was Speculative) . Tier: VERIFIED + CONTRACT (ticket 12b list)
- **Files:** `relocate.py`
- **Problem, as filed, re-verified - unchanged.** `_project_for_cwd` (`relocate.py:527-
  534`) and `_encoded_owner` (:751-758) each still open their own catalog connection per
  apply (called once, from `_preflight` at :721/:726, itself called once per apply from
  `_apply_locked` at :833). Confirmed the O(N)-per-candidate churn C10 originally named
  is still gone (`_encoded_moves`, :464-517, threads the one shared connection opened in
  `_compute` at :560, which is explicitly closed before `_preflight` ever runs at
  :574-575 - so there is no live connection available to hand `_preflight` even if
  someone wanted to). What remains is O(1) per-apply churn, unchanged from the last
  review's verdict: cosmetic ceremony, not a scaling bug.
- **Solution direction:** unchanged - have `_preflight` accept the live conn and inline
  `project_for_path`, retiring the two helper opens. Overlaps C2/C6.
- **Why not BUILT:** the scaling defect is closed; the ceremony remains.

### 13th . C11 - Split the short-key band math from its query
`[PROPOSED]` . Strength: **Worth exploring** . Tier: VERIFIED at 4824098 . in-process
- **Files:** `catalog.py`
- **Problem, re-verified, unchanged in shape.** `_short_key` (`catalog.py:146-163`,
  called from `add_session` at :223) still computes the pure prefix-band math (`low`/
  `high`, :151/:155-156) inside the same loop iteration as the `conn.execute` collision
  query (:157-160), so testing "given existing prefixes, what length gets chosen" still
  requires a real sqlite connection with colliding rows. No pure extraction has
  happened.
- **Solution direction:** unchanged - split the pure "choose a length" function from the
  collision lookup. Same shape as the new C13.
- **Contract ties:** F5 (keep the PK-index band query).

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
  justify the seam.
- `[CLEARED . 2026-08-20, found by ticket 29, not by this board]` **The head predicate's
  duplication and its false docstring** - see C4 above for what remains.

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

- **2026-08-23 - FRESH REVIEW, snapshot moved 1517bba -> 4824098** (not a normal re-anchor:
  the previous commit was destroyed by a 2026-08-10 repository rebuild, so this could not be
  a diff against it). 5 parallel Explore agents (the mattpocock-skills review skill is not
  enabled in this session), covering pipeline/render, cli.py orchestration, the risky
  transforms plus relocate/sweep walkers, the catalog/head seam, and a new lens for
  `archive.py` (never reviewed before - it postdates the last review entirely). Two
  agent-reported findings (a live silent-loss bug in `write_subagent`; an unguarded `ccw
  share --out` write path into the warehouse store) were independently re-verified by
  reading the cited source directly, confirmed real, and FIXED the same session with
  oracle tests written first - see C12 and C6 for exactly what is fixed vs. still open.
  RE-RANKED: NEW C12 -> 1st (a proven-recurring defect class, not argued), C6 -> 2nd
  (one of its four sub-findings had a confirmed live consequence, now fixed), C3 -> 3rd
  (unchanged reasoning, still real, no proven live defect of its own), C1 -> 4th (worse:
  duplication spans archive.py too, multiplicative not additive when both trees are
  configured), C2 -> 5th (worse: 4 copies -> 6, plus a 7th partial), C7 -> 6th (worse
  fan-out, ~15 sites not ~7, PLUS concrete proof of drift already having happened -
  `thinking_withheld` missing from the Block docstring), NEW C13 -> 7th (archive.py's
  `folder_is_current`, same shape as C11), C4 -> 8th and DOWNGRADED (ticket 29 mechanism 1,
  2026-08-20, already fixed the dangerous half - the false docstring and the duplicated
  predicate - independent of this review; only a small cosmetic duplication remains), C5 ->
  9th (unchanged, one function-name correction), C9 -> 10th (unchanged; confirmed the
  worried-about "third copy" did NOT happen - ticket 25.4's `import_tree.py` reuses
  `migrate.walk_jsonl` instead of copying it; one new adjacent finding in
  `relocate._scan_content`), NEW C14 -> 11th (archive.py's session/subagent/not-a-session
  discriminant, same shape as C7, lower stakes), C10 -> 12th (unchanged verdict, still
  TICKETED-12b, still not BUILT), C11 -> 13th (unchanged). Top recommendation: C12.
  Mermaid validation: see the render step's own note below.
- **2026-08-21 - DECAY BANNER ADDED** (superseded by the fresh review above): recorded that
  the 2026-07-24 snapshot's anchor commit no longer existed after the 2026-08-10 repository
  rebuild, and that this was ticket 28.13's job to fix. That fix is this entry.
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
