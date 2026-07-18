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

## DONE 2026-07-18

Slice 06 COMPLETE through the full harness loop. Implementer diff green on first gate
pass (8 oracle tests); adds a normalized conversation model (build_conversation,
Block/Turn/Conversation, split_reminder) to parser.py and a single policy-parameterized
markdown emitter (_render + _Policy, no F8) to render.py, reusing extract_text /
detect_commits / detect_github_repo verbatim plus a shared _extract_entries routing
(parse_session refactored, 19 parser tests still green). Reviewers A/B + /code-review
Standards+Spec. Unlike slices 01-05 this slice had REAL bugs; the lenses converged.
Operator triage: after principal confirmation, 5 CONFIRMED clusters + a tool-coverage
add fixed in 1 fixer round (of 3):
- C-TURN (SPEC-6/F6): turn-grouping no longer demotes a `<`-prefixed prompt or a prompt
  merely mentioning <task-notification>; only a whole-message task-notification /
  stop-hook / isMeta / empty-visible is machinery.
- C-FENCE (F6): fence-aware trailing-orphan strip (never deletes a balanced nested
  fence) + a safe-fence helper (a fence longer than any backtick run) wherever arbitrary
  content is wrapped, so tool/thinking/reminder content containing ``` cannot break out.
- C-REMINDER-LEAK (F7): an unknown reminders_* value fails closed (strip), never leaks.
- C-TOOLRESULT-LOSS (F6): a commit-bearing tool_result keeps its other text too.
- C-R8: honest docstrings + proving regression tests (determinism, pre-first-prompt).
- C-TOOLCOVERAGE (SPEC-7): Write (path+content), TodoWrite (task list), Edit replace_all.
Rejected: A5 (refuted), B8 (resolved by C-TURN). Accepted edges (documented):
C-USERLIST (user-list text), promptless-session compact.

Contract-derived regression tests (this ticket owns them by citation, HARNESS section
4 precedent): tests/test_render_md_regressions.py (10 tests). Operator black-box
verified 18/18 on the six clusters, independent of the fixer self-report. Gates: 8
oracle + 10 regression + 19 parser green, pyright strict 0, ruff clean; full suite 47
failed / 112 passed, red for the right reason.
