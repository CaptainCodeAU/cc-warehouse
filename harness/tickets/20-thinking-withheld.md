# Ticket 20: thinking withheld upstream, surfaced and overridable

DONE 2026-08-02. Commits 2e25bcd (code) and 50f704c (contract). Gates: ruff clean,
pyright strict 0 errors, 688 tests. `tests/golden/matrix-anchor` UNTOUCHED. FINDINGS,
re-derived by execution:

1. THE SLICE WAS STOPPED BY A LOCKED FENCE, AND STOPPING WAS THE RIGHT OUTCOME.
   `test_no_thinking_key_exists_on_either_variant` banned any RenderOptions field whose
   NAME contained "thinking". `thinking_withheld` tripped it. The frozen decision behind
   it is that there is no toggle for whether thinking RENDERS; the test enforced the
   letter, not the decision. Three ways out were put to the principal and A was ruled:
   narrow the contract and the fence to the decision. RENAMING THE KEY TO DODGE THE
   SUBSTRING was offered and REJECTED, because it buys a five-minute ship at the price of
   a fence anyone can defeat with a synonym. The replacement fence is stronger than what
   it replaced: it bans the specific names that would BE a render toggle, then asserts the
   protected property directly, that thinking appears in full and never in compact at
   every position of the new key.

2. MY OWN PITCH WAS WRONG AND A TEST CAUGHT IT. Option 4 was sold to the principal as
   "zero new lines". True when the phase also renders something; false when a phase is
   ALL withheld thinking, because there is no header to join and one breadcrumb line
   appears. The test written to assert zero lines failed. It was NOT weakened: it was
   split into two tests pinning both cases, so the exception is contract rather than
   folklore.

3. THE TRUE COST, MEASURED over all 13,836 objects rather than estimated:

       withheld blocks .......................... 41,458   (matches the ticket 18 census)
       sessions affected ........................  1,573   of 13,836, i.e. 11.4%
       phases containing withheld thinking ...... 35,468
       phases that are WITHHELD-ONLY ............  8,709
       -----------------------------------------------------------------------
       lines the DEFAULT adds ...................  8,709   corpus-wide
       lines the REJECTED per-block option adds .  41,458
       reduction ................................  79%

   26,759 of the 35,468 affected phases carry the fact for FREE. Also worth recording
   because it was mis-stated to the principal during the option round: the blocks
   CONCENTRATE. "About 3 per session" was arithmetic over all sessions; the real shape is
   26 per affected session across 11.4% of them.

4. THE SIGNATURE IS NEVER READ, and that is a deliberate non-scope reversal. Splitting
   `narration` (1,397 blocks) from `thinking` was offered during the option round and
   withdrawn on reflection: reading the label means parsing a field Anthropic documents as
   opaque, and building visible behaviour on an undocumented encoding breaks silently the
   first time it changes. Offering it was the mistake; withdrawing it before implementation
   was the correction.

5. WORDING IS ENFORCED, NOT INTENDED. For 96% of the corpus nothing was lost at capture
   time, so a test asserts the rendered output never contains "lost", "dropped",
   "discarded" or "removed". A marker implying the text was ever available for an Opus
   session would be F6 pointed inward, and prose is the one layer with no gate but the
   one we write ourselves.

Carried out of ticket 18 and ruled on 2026-08-02 (principal, option 4 of four).
Not a slice of a planned version cut; like ticket 18 it exists because real data
said something the contract did not anticipate.

## Why this ticket exists

41,458 of 43,060 `thinking` content blocks in the 13,836-session corpus arrive
with `thinking: ""`. They render nothing and increment nothing, which is the
FINDINGS F6 class one level BELOW the dispatch ticket 18 fixed: a silent drop
inside a NAMED branch, invisible to a green suite because the fixtures carry the
shape we imagined.

The cause is upstream and is NOT a capture failure. `anthropics/claude-code`
issue 30958 (opened 2026-03-05, still open, no maintainer reply) names v2.1.69
as the release where thinking text stopped reaching the JSONL, v2.1.68 being the
last that wrote it; issue 32810 (2026-03-10, closed as not planned) reports the
same against v2.1.72. Both predate this warehouse's first capture on 2026-05-01.

MEASURED, and the reason the wording matters: this is a MODEL property, not a
date property. Zero of 25,470 `claude-opus-4-8` blocks carry text, in any month.
All 1,602 readable blocks come from `claude-haiku-4-5-20251001` (1,391) and
`claude-sonnet-4-6` (211). Haiku wrote text on every block up to 2026-07-01 under
CLI 2.1.197 and none from 2026-07-02 under 2.1.198 onward, 22 versions and 21,670
blocks with zero. Cause of that boundary is UNPROVEN: version and date are
confounded on an auto-updating machine.

CONSEQUENCE for wording: for 96% of this corpus nothing was lost at capture time,
something never arrived. A marker implying the text was ever available for an
Opus session would be false, and false in exactly the direction F6 bans.

## The ruling (principal, 2026-08-02)

OPTION 4 of four: fold the count into the phase caption the transcript already
prints, so ZERO new lines are added, plus a manifest counter so the question is
answerable across 13,836 sessions without opening a transcript. Rejected: a
marker per block (41,458 near-identical lines, clustered, fails the "well
structured" half of the principal's own stated requirement); a manifest counter
alone (invisible where it happened); and leaving it (a named F6 hole left open).

PLUS, requested in the same ruling: a CLI argument that lets the operator
OVERRULE the default and change what reaches the markdown and HTML files. That
makes the rejected options runtime positions rather than closed doors.

## Work order

- SLICE: thinking-withheld surfacing, with an operator override
- GOAL: an empty thinking block is never silent; its treatment in the projected
  files is a config key and a CLI flag with three positions; the manifest counts
  it regardless of display.
- KEY: `[render] thinking_withheld`, flag `--thinking-withheld` (the 2026-08-01
  bijection, shared rule c: flag = key with dashes, zero exceptions).
  - `caption` (DEFAULT) the existing phase caption gains `N thinking withheld`.
    No new lines in any file.
  - `marker` one `> [thinking withheld]` line per block. The rejected option 2,
    available on demand.
  - `off` nothing in the markdown or HTML. The manifest still counts.
- MANIFEST: new TOP-LEVEL `withheld` block, `{thinking_blocks: N}`. Not a `loss`
  key and not part of `unrecognised`: it was not lost by us and it is not an
  unknown type. Third top-level key, same reasoning as ticket 18's.
- ORACLE TESTS (write first, tests/test_thinking_withheld.py):
  1. an empty thinking block reaches the conversation model at all
  2. the DEFAULT adds no new lines, only a caption bit, in markdown
  3. the same bit appears in HTML, by construction not by duplication
  4. `marker` emits one line per block in both emitters
  5. `off` emits nothing in either emitter
  6. the manifest counts identically under all three positions
  7. the compact variants never show it, at any position
  8. an illegal flag value is refused as a usage error before work begins
  9. a text-bearing thinking block is unaffected at every position
- ADJACENT: parser._assistant_blocks (where the empty block is dropped today);
  render._phase_meta (owns the caption bits both emitters print); config
  CHROME_KEYS' validation pattern, which this reuses rather than copies.
- TOUCHES: parser.py, render.py, config.py, cli.py, build.py, tests/, docs/.

## Explicitly NOT in scope

SPLITTING `narration` FROM `thinking`. 1,397 of the blocks carry the literal
`narration` rather than `thinking` inside the base64 `signature` envelope, and
this was offered during the option round. It is withdrawn on reflection: reading
it means PARSING THE SIGNATURE, a field Anthropic's own documentation says is
opaque and must not be parsed. Building a visible product behaviour on an
undocumented internal encoding would break the first time it changed, silently,
and this project's whole thesis is not overclaiming. The observation is recorded
in DESIGN 15; the dependency is not built.

RECOVERING THE TEXT. The signature carries the reasoning encrypted at roughly
1.2x its plaintext size, measured across the 1,602 blocks that have both. Only
Anthropic holds the key. Nothing here attempts otherwise.

THE 218 MB QUESTION. The signature blobs total 218,406,832 characters, about 14%
of the 1.5 GB store, and under archive-first they ship inside every session
folder as unreadable payload. That is a ticket 19 storage decision and belongs to
its own round.
