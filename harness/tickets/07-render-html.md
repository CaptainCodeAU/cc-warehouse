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

## DONE 2026-07-19

Slice 07 COMPLETE through the full harness loop. Implementer diff green on first gate
pass (9 oracle tests); render.py only (no parser change needed). The HTML emitter
reuses the slice-6 markdown fragments as the copy-as-md single source of truth (base64
data-copy-src decodes to a byte-exact transcript.md fragment, R9/F8); an in-house
stdlib markdown-to-HTML renderer; content-hashed unique anchors (fixing the specimen
make_msg_id collision); commit-card links; and build_manifest wiring the
conversation-model counts + store.sha256_hex. render_markdown stayed byte-identical (18
slice-6 md tests green). Reviewers A/B + /code-review Standards+Spec; this slice had
REAL bugs and the lenses converged. Operator triage: 5 CONFIRMED clusters fixed in 1
fixer round (of 3):
- C-PASSTHROUGH (F6): _md_to_html passed <details>/<summary> through unescaped for USER
  text too (a "<details>" prompt broke the page; reachable since the slice-6 C-TURN fix
  made <-prefixed prompts real conversation); now provenance-based -- structural HTML
  passes only for emitter-authored fragments (header/reminder/continuation).
- C-SHA-DUP (R9): anchor hashing reuses store.sha256_hex, not a second hashlib site.
- C-COMMIT-REPO (F6): a multi-repo session mislinked a sha to the first repo; now the
  sha links to its own result's repo, the session repo as fallback.
- C-CDN-COUNT (DESIGN-6): dropped the second external cdnjs reference (theme CSS); the
  highlight.js script stays the one permitted external reference.
- C-R8-DOCSTRING (R8): docstrings now name their proving tests.
Deferred (principal): the exporter visual chrome (collapsible turns, sticky toolbar,
width/font toggles, research phases, Catppuccin palette) -- not oracle-required, later
polish. Accepted: the _turn_html/_render_turn walk duplication (fragments shared, no
markdown drift). Rejected: C-RENDER-LOSS (manifest loss is the frozen skipped_lines key).

Contract-derived regression tests (this ticket owns them by citation, HARNESS section
4 precedent): tests/test_render_html_regressions.py (6 tests). Operator black-box
verified 10/10 on the five clusters, independent of the fixer self-report; copy-as-md
byte equality reconfirmed (all 13 payloads are transcript.md substrings). Gates: 9
oracle + 6 regression + 43 other render/parser/fence tests green, pyright strict 0,
ruff clean; full suite 38 failed / 127 passed, red for the right reason.
