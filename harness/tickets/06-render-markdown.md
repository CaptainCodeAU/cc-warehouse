# Ticket 06: transcript.md emitters (full + compact)

Slice 6 of 13. Depends on: 03 (consumes the conversation model).

Tracer bullet: render_markdown(data, options) returns the two markdown
variants of the 4-file projection: exporter-style full transcript and the
conversation-only compact.

## Work order (template from harness/prompts/implementer.md)

- SLICE: transcript.md emitters
- GOAL: make the slice-6 oracle tests pass; the transcript.md fragments
  produced here become the byte-exact copy-as-markdown payloads of slice 7.
- ORACLE TESTS: tests/test_render_md.py (all).
- CONTRACT EXCERPTS: DESIGN section 6 (file table + fixed policies), SPEC
  sections 6-7 KEEP semantics (grouping, continuations, task notifications,
  Stop-hook exclusion, md hardening); BRAINSTORM render lock (exporter
  v8.10.1 reference).
- ADJACENT BEHAVIORS: parser.parse_session and its conversation model
  (slice 3: extend the model there if a semantic is missing; do not re-parse
  raw JSON here), parser.detect_commits / detect_github_repo.
- TOUCHES: src/cc_warehouse/render.py, plus model-only additions to
  src/cc_warehouse/parser.py.

## Phase 2 decisions frozen in the tests

- Full: `***` separators (Quick-Look-safe), thinking inside ```md fences,
  tool calls present, system reminders present but collapsed in <details>.
- Compact: conversation only (no thinking, no tools, no reminders, no task
  notifications), carries a variant note mentioning "compact".
- reminders_full / reminders_compact options override the policy for
  PERSONAL renders only (share ignores them, slice 11).
- breadcrumbs option changes compact output; default off.

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only.
