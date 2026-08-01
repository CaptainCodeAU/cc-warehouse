# Ticket 18: real-data coverage (the shapes a written suite never invents)

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
