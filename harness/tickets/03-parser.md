# Ticket 03: parser + conversation model

STATUS: DONE 2026-07-18 (full harness loop; 1 fixer round of 3; 7 confirmed
reviewer clusters resolved, 1 rejected; 6 contract-derived regression tests;
operator black-box verified 12/12; retro in HARNESS section 8).

Slice 3 of 13. Depends on: nothing at runtime (pure functions); ordered here
so slice 4 can call it (the hook's metadata extraction lives in this slice).

Tracer bullet: one parse of a raw payload produces everything the catalog
needs (metadata, summary, counts) plus the normalized conversation model the
slice 6/7 emitters will consume. The model's internal shape is NOT frozen by
tests; its observable semantics are pinned via the emitters later.

## Work order (template from harness/prompts/implementer.md)

- SLICE: parser + conversation model
- GOAL: make the slice-3 oracle tests pass with a stdlib parser that never
  loses data silently.
- ORACLE TESTS: tests/test_parser.py (all).
- CONTRACT EXCERPTS: SPEC section 6 (all KEEP/CHANGE verdicts), SPEC section
  8 (summary + hiding), DESIGN section 4 (parse ONCE), DESIGN 14 rules R5,
  R8; FINDINGS F6 (malformed lines counted, never silent).
- ADJACENT BEHAVIORS: catalog.SessionMeta (slice 2) is the destination shape
  for parsed metadata; do not invent a second metadata container.
- TOUCHES: src/cc_warehouse/parser.py only.

## Phase 2 decisions frozen in the tests

- line_count = total raw lines; skipped_lines = unparseable lines only
  (a parseable summary-type line is filtered, not skipped).
- Slice-03 reviewer round (2026-07-18) refines the bullet above: skipped_lines
  counts every non-blank line/item that yields no usable entry dict, which
  includes a valid-JSON-but-non-object line (consistent across the JSONL and
  loglines paths); a genuinely blank line stays uncounted. A `loglines` value
  present but not a list is a malformed payload (counted, never zeroed); a
  leading UTF-8 BOM is stripped before routing; deeply nested input is counted
  as skipped, never allowed to crash. Six regression tests in
  tests/test_parser.py pin these (added per HARNESS section 4).
- JSON files with a `loglines` key parse like JSONL (SPEC KEEP).
- Summary priority: first summary-type line, else first user text not
  starting with `<` (task notifications and command output are machine text),
  200-char cap; `warmup` and no-summary sessions are hidden=True with the
  `(no summary)` placeholder for the latter.
- Commit regex keeps the specimen's load-bearing `(?:\n|$)` terminator;
  repo detection reads github.com/<owner>/<repo>/pull/new/ URLs.

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only.
