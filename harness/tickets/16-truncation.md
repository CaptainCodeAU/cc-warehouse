# Ticket 16: tool-output truncation

DONE 2026-08-01. Commit e541f3f. Gates: ruff clean, pyright strict 0 errors,
suite green. FINDINGS:

1. The renderer and the manifest counter must agree about WHICH strings the cap
   applies to, or the marker on the page and the number in the manifest would
   describe different things. Both go through one `_result_payloads` and one
   `_truncate`, so they cannot disagree by construction rather than by care.

2. Blocks are counted ONCE, not once per file. The cap is variant-agnostic, so a
   block cut in transcript.md is cut identically in the compact variant when
   slice 14's matrix opened tool output there; counting per variant would
   double-report a single loss.

3. The marker's second clause is load-bearing and is not decoration. "The stored
   session is complete; only this projection is capped" is what stops a reader
   inferring archive damage from a projection choice (F6). Both clauses have a
   test standing behind them, which is what R8 asks of a guarantee.

4. Projection-only is asserted, not assumed: a capped render leaves the source
   payload hash-identical.

Slice 16 of 17 (v1.1 flag groups; DESIGN 15 entry 2026-08-01, block 3 + shared
rules). Depends on: slice 14 (the cap applies wherever a tool-result block
renders, including compact when the matrix opened it). The manifest amendment
rides in this slice ALONE by design: the most safety-relevant change travels in
the least crowded vehicle.

Tracer bullet: `tool_output_max_chars` threads from config/flag through render
block emission; over-cap blocks are cut at a line boundary, marked in-page, and
counted in the manifest's `loss` block.

## Work order (template from harness/prompts/implementer.md)

- SLICE: opt-in per-block truncation of rendered tool results
- GOAL: `tool_output_max_chars` config key (absent or 0 = off, the default;
  positive int = per-block character cap) + `--tool-output-max-chars N` flag.
  Manifest `loss` grows to skipped_lines + truncated_blocks + truncated_chars.
- ORACLE TESTS (write first, in tests/test_truncation.py + additions to
  tests/test_config.py and tests/test_cli.py):
  - absent and 0: output byte-identical to post-slice-15 output (anchor
    reused); explicit 0 equals absent;
  - a block over the cap is cut at the LAST line boundary at or below the cap,
    never mid-line;
  - a single-line over-cap blob (the archetypal offender) is still cut;
  - the in-page marker appears in md AND html, states the omitted character
    count AND that the stored session is complete;
  - marker present if and only if truncation happened (loss is never silent,
    and no marker on untruncated output);
  - manifest counts are exact: truncated_blocks = number of cut blocks,
    truncated_chars = total characters omitted;
  - the STORED payload bytes are untouched (hash the source before and after a
    capped render);
  - the cap reaches a matrix-opened compact variant (`tool_output_compact =
    true` + cap: compact blocks are capped too);
  - negative values are usage errors on the flag and config-load errors on the
    key.
- CONTRACT EXCERPTS: DESIGN 15 entry block 3; DESIGN 6 (manifest: config used,
  counts, loss telemetry); FINDINGS F6 (the code overclaims its own
  guarantees - the marker text is a guarantee and its test is the citation);
  rules R2, R8, R9.
- ADJACENT BEHAVIORS: build_manifest's frozen key discipline (render.py:
  "Frozen keys (DESIGN section 6)" - extend the docstring with the new loss
  keys); the copy-as-markdown parity invariant (copy payloads must equal the
  TRUNCATED transcript fragments, staying self-consistent); `_Policy` /
  RenderOptions from slice 14.
- TOUCHES: src/cc_warehouse/render.py, src/cc_warehouse/config.py,
  src/cc_warehouse/cli.py.

## Interview decisions frozen in the tests (register 9-10, 16)

Opt-in, OFF by default (an audit-trail product does not change your files
because you upgraded); characters, in the key name (`_max_chars`), because the
renderer's unit is decoded str, a line cap misses the one-line blob, and a KB
cap means different amounts per alphabet; projection-only by construction.

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only.
