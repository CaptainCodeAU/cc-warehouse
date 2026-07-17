# Ticket 07: HTML emitters + manifest

Slice 7 of 13. Depends on: 06 (copy-as-markdown payloads must equal the
slice-6 transcript.md fragments byte for byte).

Tracer bullet: render_html(data, options) returns the two single-page HTML
variants; build_manifest(data, options) answers "did we lose anything".

## Work order (template from harness/prompts/implementer.md)

- SLICE: HTML emitters + manifest
- GOAL: make the slice-7 oracle tests pass with self-authored stdlib HTML
  generation (the in-house markdown renderer lives in this slice's scope).
- ORACLE TESTS: tests/test_render_html.py (all).
- CONTRACT EXCERPTS: DESIGN section 6 (unique anchors, copy-as-md equality,
  manifest telemetry, highlight.js note in section 15 item 8), SPEC section 7
  KEEP semantics (tool-typed rendering, commit cards, md hardening, base64
  data-copy-src instrumentation); FINDINGS F6 (loss accounting).
- ADJACENT BEHAVIORS: render.render_markdown (slice 6: fragments are shared,
  not re-derived; one source of truth per block, R9), parser conversation
  model, parser.detect_commits / detect_github_repo.
- TOUCHES: src/cc_warehouse/render.py (and parser.py model-only additions).

## Phase 2 decisions frozen in the tests

- Anchors: unique across the page even for equal timestamps (turn ordinal +
  short content hash; fixes the specimen's make_msg_id collision).
- Every block carries base64 data-copy-src whose decoded bytes appear
  verbatim in transcript.md.
- Commit cards link github.com/<owner>/<repo>/commit/<sha> when a repo was
  detected.
- Markdown hardening: loose lists render as <li>; <pre> tags stay balanced
  when a message ends in a dangling fence.
- Manifest keys: source_hash (full sha256 of the payload), counts.prompts
  (continuations merged, stop-hook and task-notification prompts excluded),
  counts.tool_calls, loss.skipped_lines, config (dict of options used).

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only.
