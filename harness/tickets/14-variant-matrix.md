# Ticket 14: per-variant content matrix

DONE 2026-08-01 (direct build; oracle tests first, then implementation, then a
four-angle quality review). Commits fa79b80 (oracle tests + the anchor), f0c6970
(render), 7674a81 (config + build), 9a64deb (cli), 6044b41 and c9c1d86 (review
fixes). Gates: ruff clean, pyright strict 0 errors, full suite 473 passed (403
before this slice + exactly 70 new: 61 in tests/test_matrix.py, 7 in
tests/test_config.py, 2 in tests/test_cli.py). Zero stubs in `src/`. All seven
oracle tests the work order named are green, and the `/refresh` config-vs-contract
drift probe reports no drift (DESIGN 8 already names all five keys).

The regression anchor was generated from the slice-13 tree at c075c5d with
`git status --porcelain src/` verified EMPTY, so `tests/golden/matrix-anchor` holds
pre-slice bytes by construction rather than by claim. It is never regenerated to
make a change pass; slices 15-17 reuse it as-is.

FINDINGS, each re-derived by EXECUTION before being acted on:

1. A mechanical key-to-field bijection would have shipped `tool_output_compact`
   as a DEAD key. Executed: with `include_tools=False`, `_render_block` returns
   `[]` for a `tool_result` before `toolresult_diff` is ever read, so binding the
   compact key to `toolresult_diff` alone (the field its unsuffixed sibling
   drives) could not change one byte. Compact hard-codes BOTH gates; the full
   variant hard-codes `include_tools=True` and exposes only the diff one, so the
   two variants do not have a symmetric field to bind to. RESOLVED FROM THE
   CONTRACT, not adapted: DESIGN 15 block 3 says the truncation cap applies
   "wherever a tool-result block renders (full by default; compact if the matrix
   opened it)", which only holds if the matrix can open it. `tool_output_compact`
   therefore lifts both gates. No frozen ruling was contradicted.

2. The five content classes do NOT mean the same thing, and the ticket's phrasing
   ("same per key for the other four classes") reads as though they do. Executed:
   four classes gate whether their block renders at all, but the unsuffixed
   `tool_output` key in the FULL variant only chooses between the structured
   stdout/stderr rendering and the raw result fence - `**Result:**` is present
   either way. The first draft of the unsuffixed-key oracle test asserted the
   marker DISAPPEARS from the full variant and was wrong for this class; it now
   asserts the full variant CHANGED, which is what the v1 meaning actually
   promises. Recorded because it is the exact shape of the standing lesson that a
   ticket's finding list is evidence, not a specification.

3. Naming asymmetry, recorded and deliberately NOT fixed: the `tool_output`
   config key has driven a RenderOptions field called `toolresult_diff` since
   slice 6, so key-to-field is not uniform. Left alone because `build_manifest`
   publishes those field names verbatim through `asdict(options)` into the
   manifest `config` block, which is frozen v1 surface, and renaming would move
   every session's manifest bytes for an internal tidiness with no ruling behind
   it. The five NEW fields match their keys exactly, so the bijection holds
   wherever this slice creates it.

4. F6 OVERCLAIM FOUND AND CLOSED, and it predates this slice. The compact
   variant note was the fixed string "conversation only, no thinking, tools, or
   reminders". Opening tools in compact would have made it deny the file it
   heads. Executed against the PRE-slice code at c075c5d: with
   `reminders_compact = "show"` that same sentence was already printed above a
   file containing the reminder text, so the defect existed before slice 14 and
   this slice would merely have widened it. The note's list is now derived from
   the policy. The DEFAULT wording is unchanged, which the anchor proves rather
   than asserts.

4b. THE SAME DEFECT HAD A TWIN, AND MY FIRST CENSUS MISSED IT. Finding 4 fixed
   the MARKDOWN note and I recorded it as a class fix. It was an instance fix.
   The compact variant describes itself in TWO places: the header note, and a
   second sentence in the HTML meta strip ("compact variant, thinking and tool
   detail omitted"), which stayed fixed. A quality review flagged it and
   execution confirmed it: with `tool_output_compact = true`,
   `conversation.compact.html` rendered tool blocks while telling the reader tool
   detail was omitted - the identical overclaim, in the emitter nobody looked at,
   passing a green suite because the oracle test called only `render_markdown`.
   Fixed in 6044b41; the HTML sentence now derives from the POLICY (it runs at
   emission time, where the policy is the only thing that knows what the page
   actually contains), and the test covers both emitters. Recorded in full rather
   than folded into finding 4, because the interesting fact is not that the
   second site existed but that I had already written "census the class" in this
   ticket while doing exactly the instance fix that lesson warns against.

5. Pre-existing exception to the bijection, recorded not fixed: `--reminders`
   maps to the config key `reminders_full`, so it is not "key with dashes".
   DESIGN section 7 names that spelling explicitly, so shared rule (c) inherited
   the exception rather than creating it. The new `--reminders-compact` does
   match its key.

6. No fixture in the suite could exercise the matrix. `rich_session` covers
   thinking, tools, commits and reminders but emits no sub-agent, attachment,
   command or extra block, so four of the five classes had never been rendered by
   any test. `conftest.matrix_session` was added for this and is what slices
   15-17 will reuse. A guard test asserts every class is present in the full
   variant and absent from compact at defaults, so a green matrix cell cannot be
   vacuously green.

7. The R8 guarantee-word fence fired on this slice's own code and was satisfied
   the way R8 specifies: `test_guarantee_words_cite_their_proving_test` rejected
   a new docstring saying "byte-identical" until `GUARANTEE_PROOFS` cited the
   anchor test. The citation was added; the claim was not softened.

8. The content help group heading was already inaccurate before this slice. It
   read "content (default on; --no-X drops it)", which was false for
   `--breadcrumbs` (defaults off) and would have been false for all five new
   flags. Now split into a full-variants group and a compact group, which shared
   rule (c) permits explicitly ("help text may group flags for readability, never
   respell them"); every stem printed comes straight out of the parser's own
   tables, so a flag the parser accepts cannot go unlisted.

8b. The first attempt at that split derived the group by testing the stem for a
   `-compact` SUFFIX, and made the heading WORSE rather than better:
   `--breadcrumbs` is compact-only without carrying the suffix, so it printed
   under "content, full variants" - a heading that states the opposite of the
   truth, where the old vague one had merely been unhelpful. Two of the four
   review angles found it independently. The variant is now a FIELD on the row.
   The same edit moved each value flag's value list onto its own row: one shared
   `{collapse|strip|show}` constant was correct only by coincidence, and slice 15
   adds four value flags with four different lists, so it would have printed the
   wrong values beside every one of them. Fixed in c9c1d86.

9. Non-leak verified rather than assumed: `ccw share` output is byte-identical
   with all five personal compact keys ON plus `reminders_compact = "show"`
   (5 files hashed off a real share build). DESIGN 9's "share builds IGNORE any
   personal render overrides" holds because `share.py` constructs a bare
   `RenderOptions(hljs="inline")`. This was checked because the same
   private-config-reader class already produced one live redaction leak in this
   codebase; the class was censused, not spot-checked.

10. Incremental behaviour verified: a compact key takes effect on the next
    `ccw build` WITHOUT `--rebuild` (the incremental check is a byte compare, not
    a source-hash compare), while a no-op build still leaves projections
    mtime-stable. Without this the keys would have looked inert to an operator
    until a full rebuild.

RAISED BY REVIEW AND DELIBERATELY NOT ACTED ON, so the next reader inherits the
reasoning rather than the finding:

- Extract a shared `_valued_flag(args, stem)` in cli.py. Real duplication - the
  `--x VALUE` / `--x=VALUE` scan exists five times in that file - but four of the
  five sites are outside this slice's diff, and one of them (`_sweep_source`)
  already behaves differently by rejecting a flag-shaped value. Consolidating
  means picking which behaviour wins, which is a decision for whoever owns that
  surface, not a cleanup to smuggle into slice 14.
- Rebuild `conftest.matrix_session`'s two sidechain records through the existing
  `entry()` helper. The reviewer judged the golden anchor unaffected because the
  parser does not read keys positionally. That reasoning is WRONG and the
  suggestion was rejected on execution, not on taste: the rendered header carries
  `sha256` of the payload BYTES, so any change to the fixture's JSON layout moves
  all four goldens. The anchor is the one thing in this slice that must not be
  regenerated. Kept as a reminder that a sub-agent report is evidence, not a
  result.
- Give `_Policy` an explicit `compact: bool` instead of using the truthiness of
  `variant_note` as the compact sentinel at three sites. Fair observation, but
  `_compact_note` cannot return an empty string (the list always contains at
  least "thinking"), so the fragility is theoretical today. Recorded for whoever
  next touches `_Policy`.
- Rename `_Policy.toolresult_diff` to something ending in `_style`, since it is
  the only content field that names a rendering STYLE rather than a gate. Same
  reason as finding 3: the name is published into the manifest.
- Cache the default-render baseline and the no-flag `ccw render` subprocess
  across parametrized cases (measured at roughly 450ms of the suite's 23s).
  Rejected in favour of test isolation: the sharing scheme needs its own HOME
  because a neighbouring test writes a config file into `ccw_env`, and an
  interdependent suite costs more than half a second.

Slice 14 of 17 (v1.1 flag groups; DESIGN 15 entry 2026-08-01, block 1 + shared
rules). Depends on: slice 13 (config layering, Group-A flags), slices 6/7 (the
render emitters and `_Policy`).

Tracer bullet: the five `_compact` keys and their flag pairs thread from CLI and
config through `RenderOptions` into `_compact_policy`, so compact's hard-coded
drops become defaults. An empty config renders byte-identical output to v1.

## Work order (template from harness/prompts/implementer.md)

- SLICE: per-variant content matrix
- GOAL: `subagents_compact`, `attachments_compact`, `commands_compact`,
  `extras_compact`, `tool_output_compact` (config keys, all default OFF) and
  their bijection-derived flag pairs (`--subagents-compact` /
  `--no-subagents-compact`, ..., plus `--reminders-compact VALUE`) reach the
  compact variants of all four files. Unsuffixed keys and flags keep their v1
  meaning (full variants only).
- ORACLE TESTS (write first, in tests/test_matrix.py + additions to
  tests/test_config.py and tests/test_cli.py):
  - empty config and no flags: all four files byte-identical to pre-slice output
    (the regression anchor for the whole flag-group run);
  - `subagents_compact = true` renders sub-agent turns in transcript.compact.md
    AND conversation.compact.html; same per key for the other four classes;
  - each `--x-compact` flag beats its config key (DESIGN 8 precedence);
  - unsuffixed `--no-subagents` still strips full variants and leaves compact
    unchanged;
  - flag spelling is the mechanical bijection (no `--compact-x` spellings parse);
  - `--reminders-compact show|collapse|strip` maps to `reminders_compact`;
  - the manifest `config` block records the new RenderOptions fields.
- CONTRACT EXCERPTS: DESIGN 15 entry 2026-08-01 (shared rules a-d, block 1);
  DESIGN 8 key map (the eleven v1.1 keys and the defaults sentence); DESIGN 7
  flag paragraph. Rules R9 (extend `_compact_policy` in place; a parallel policy
  builder is a rejection), R2 (writes), R8 (guarantee words cite tests).
- ADJACENT BEHAVIORS: render.RenderOptions and `_compact_policy` (complete in
  place); config.load_config's `[render]` section and Config fields;
  cli._CONTENT_BOOL_FLAGS / _content_flags and the verb help text; the
  NON-SCOPE line in the entry (no thinking key on either variant - do not add
  one).
- TOUCHES: src/cc_warehouse/render.py, src/cc_warehouse/config.py,
  src/cc_warehouse/cli.py.

## Interview decisions frozen in the tests (register 3-6, 16)

Matrix = variant x toggle; suffixed FLAT keys (no sub-tables; the one-level
merge is a constraint, not a bug); unsuffixed = full; compact defaults = its v1
drops; full CLI parity (principal's call over config-only); flag = key with
dashes, zero exceptions.

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only. First slice of the v1.1 run: the
byte-identical regression anchor lands here and slices 15-16 reuse it.
