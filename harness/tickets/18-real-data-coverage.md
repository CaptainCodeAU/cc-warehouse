# Ticket 18: real-data coverage (the shapes a written suite never invents)

DONE 2026-08-02. Gates: ruff clean, pyright strict 0 errors, 665 tests.
`tests/golden/matrix-anchor` UNTOUCHED, which is the proof the change is additive.
Principal ruled option 4 on the open question below: classified markers plus a new
TOP-LEVEL manifest key `unrecognised`, never a third `loss` amendment. FINDINGS, every
one re-derived by execution against all 13,836 stored objects, not recalled:

1. THE TICKET'S OWN RECOMMENDATION WAS WRONG, and only sampling showed it. The ticket
   proposed one-line machinery markers for everything unhandled. Sampling every type
   found that `result` carries a sub-agent's RETURNED WORK, mean 2,234 bytes and max
   6,908 across 173 entries. A blanket marker would have closed a silent-loss bug by
   opening a quieter one. Machinery gets a marker; content gets a block. Recorded because
   the ticket's own standing lesson says a finding list is evidence, not a specification,
   and this is the second consecutive ticket where that held.

2. THE SAME DEFECT CLASS LIVED ONE LEVEL BELOW THE DISPATCH, and the first implementation
   shipped it. `_agent_result_block` read only `result.summary`, which covers 12 of the
   173; the other 161 return a schema of their own (verdict/evidence 71, candidates 41,
   verdicts 45, plus files/decisions/notes/command). So 93% of the very content this
   ticket exists to preserve was being flattened to a machinery marker BY THE FIX. Caught
   only by running the new parser over the real corpus and reconciling the block counts:
   12 where 173 was expected. Fixed by carrying the structured payload in `Block.result`
   and fencing it as JSON. After the fix `agent_result` reads 173 and `machinery` falls by
   exactly 161, which is the arithmetic that proves it.

3. VERIFIED ON REAL DATA, read-only: 13,836 objects parsed, 0 failures, 0 unrecognised
   entries. The named registry covers today's corpus completely, so `unrecognised` is a
   tripwire rather than a live alarm.

4. `custom-title` CHANGES 26 SESSIONS, NOT 910. The census counts 910 custom-title
   ENTRIES, but a rename APPENDS an entry rather than replacing one, so they land in just
   26 sessions. The 910 figure reached two source comments before the corpus run corrected
   them. An entry count is not a session count, and saying "910 sessions" in a comment is
   F6 in miniature.

5. THE THREE DEGENERATE SHAPES ALREADY WORKED; nothing pinned them. A 100 MB payload, a
   session with no timestamp anywhere and a single JSONL line over 1 MB all rendered
   before this ticket. The value added is the pin, plus one measurement worth keeping: a
   104,868,489-byte payload peaks at 943,779,996 bytes of traced heap, a ratio of 9.00x.
   The test ceiling is 12x, a third above the observation.

6. MY OWN CENSUS INSTRUMENT WAS THE FIRST THING TO BE WRONG. An early pass reported 126
   unparseable lines and 10 timestamp-free payloads, contradicting the ticket. Both were
   `.DS_Store` swept up by `rglob`. The ticket's zero-unparseable and nine-timestamp-free
   figures hold exactly. A census is only as bounded as its enumeration.

CARRIED, NOT DONE (needs its own ruling, recorded in DESIGN 15): 41,458 of 43,060
`thinking` blocks arrive with `thinking: ""` and their content in an opaque `signature`
blob, encrypted extended thinking. They render nothing and count nothing, which is this
ticket's own F6 class inside a NAMED branch. Surfacing them is another 41,458 markers and
therefore a visible-output change the principal has not been asked about.

ALSO NOT DONE, and a deviation from the option comparison shown before the ruling: the
"Files touched" count still reads 0 for a session whose only file evidence is a
`file-history-delta`. The comparison sketched it as 1. `_file_targets` is the index of
files THE CONVERSATION edited, derived from Edit/Write tool calls; file-history entries
are Claude Code's own backup bookkeeping and fire for files merely tracked, so folding
them in would overstate the index rather than correct it.


Not a slice of a planned version cut. This ticket exists because the first
`ccw build` at scale (2026-08-01, 13,608 sessions) failed on 9 of them, and the
census that followed found more of the same class. Every item below is derived
from a MEASURED property of a real 13,836-session corpus, never from
brainstorming - brainstorming is what missed the lone surrogate.

## Why this ticket exists

The suite is written from the contract. The contract describes what the product
SHOULD do. Neither contains a payload with half an emoji in it, because nobody
invents one. Eleven real sessions had one. The standing lesson recorded in
CLAUDE.md and HARNESS section 8 is that A GREEN SUITE IS A STATEMENT ABOUT THE
INPUTS YOU IMAGINED; this ticket is the corrective.

## The measured findings (2026-08-01, all 13,836 stored objects)

ELEVEN entry / block types present in real data render NOTHING and increment NO
loss counter, which is silent loss by FINDINGS F6's own definition:

    permission-mode        26,154 entries     first seen 2026-05-01
    mode                   19,165             first seen 2026-05-26
    file-history-snapshot  14,315             first seen 2026-05-01
    file-history-delta      1,682             first seen 2026-07-14
    custom-title              910             first seen 2026-05-18
    started / result          346
    frame-link                  5             first seen 2026-07-03
    image  (content block)     87
    document / fallback         3
    ---------------------------------------------------------------
    ~62,600 entries dropped with `loss: 0` recorded beside them

DESIGN section 6's entry-type paragraph says the model "now surfaces the rest"
of the types, machinery ones as a one-line marker. These are therefore a GAP
against a ruling, not a ruling. `custom-title` is the sharpest: `ai-title`
already wins the title, and a title the OPERATOR set should presumably beat one
the model generated.

ROOT CAUSE, and the reason item 3 below matters more than items 1-2: the
entry-type census was performed once, on 2026-07-23. `frame-link` first appears
2026-07-03 and `file-history-delta` 2026-07-14. Claude Code's format keeps
moving, so A ONE-TIME CENSUS OF A LIVING FORMAT GOES STALE BY CONSTRUCTION.

Other measured properties with no test standing behind them:

    largest payload            114.2 MB  -> renders in 12s, emits a 6 MB HTML page
    single JSONL lines > 1 MB        36
    payloads with NO timestamp        9
    message.content as a bare str 27,913  (handled; nothing pins it)

CLEARED by the same census, and worth recording so nobody re-derives it: zero
non-utf8 payloads and zero unparseable lines across all 13,836 files. The
parser's robustness paths are real but have never met reality. All 449,212
timestamps are Z-suffixed, so slice 17's offset-parsing branch has never met a
real offset either.

## Work order

- SLICE: real-data coverage
- GOAL: no entry or block type present in a payload can be dropped without
  either rendering something or incrementing a loss counter; the scale and
  degenerate-shape cases have tests.
- ORACLE TESTS (write first, in tests/test_real_shapes.py):
  1. every entry `type` renders something OR increments loss (11 named types)
  2. every `message.content` block `type` likewise (image / document / fallback)
  3. A FENCE that FAILS when an unrecognised type appears at all - the durable
     fix, because items 1-2 are a snapshot and this is a tripwire. Model it on
     test_fences.py's existing AST fences: enumerate the types the parser names,
     and fail on a payload carrying one it does not.
  4. a 100 MB payload renders without exhausting memory (yours is 114 MB)
  5. a session with no timestamp anywhere renders (9 real cases)
  6. a single JSONL line over 1 MB renders (36 real cases)
  7. `message.content` as a bare string, not a list (27,913 real cases)
- CONTRACT EXCERPTS: DESIGN section 6 entry-type coverage paragraph (the "now
  surfaces the rest" sentence is the promise being checked); FINDINGS F6 (loss
  is never silent); DESIGN 6 manifest `loss` key set, amended twice on
  2026-08-01 and likely to need a third key here.
- ADJACENT: parser._extract_entries and the entry-type dispatch in
  build_conversation; render.build_manifest's loss block; the machinery-marker
  convention `attachment` already uses for its non-content kinds, which is the
  precedent for how an unhandled-but-recorded type should look.
- TOUCHES: src/cc_warehouse/parser.py, src/cc_warehouse/render.py, tests/.

## Open question for the principal, to settle BEFORE implementation

A new `loss` key would be the third amendment to a frozen key set in two days.
The alternative is that unhandled types render as one-line MACHINERY markers,
exactly as `attachment`'s machinery kinds already do, in which case nothing is
lost and no counter is needed. That is probably the better answer, but it makes
~62,600 markers appear in projections that do not have them today, which is a
visible output change and therefore a ruling.

## Process

Standard loop (HARNESS section 2); oracle tests first. Item 3 is the one that
must not be dropped for time: without it this ticket is a snapshot that expires
the next time Claude Code ships an entry type.
