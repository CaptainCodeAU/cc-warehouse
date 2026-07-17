# Ticket 11: share + redaction

Slice 11 of 13. Depends on: 06, 07, 08 (one renderer for personal and shared
output; decided 2026-07-17).

Tracer bullet: `ccw share s:<key> ... --out <dir>` builds a sanitized static
site from COPIES; the raw store and personal projections keep full fidelity.
With build.py, this is the only module sanctioned to delete files, and only
inside the shares output space (R4).

## Work order (template from harness/prompts/implementer.md)

- SLICE: share + redaction
- GOAL: make the slice-11 oracle tests pass; sanitization happens at share
  time, is fully reported, and never silently mangles content.
- ORACLE TESTS: tests/test_share.py (all).
- CONTRACT EXCERPTS: DESIGN section 9; DESIGN 14 rules R4, R5, R13 (where
  apply-class), R8; FINDINGS F6 (report what happened), F9.
- ADJACENT BEHAVIORS: render.render_markdown / render_html / build_manifest
  (slices 6-7: the SAME renderer renders shares; a second rendering path is
  a rejection, R9), build's projection naming (slice 8), config redaction
  rules (slice 4 subset / slice 13 full).
- TOUCHES: src/cc_warehouse/share.py, src/cc_warehouse/cli.py (share verb).

## Phase 2 decisions frozen in the tests

- Redaction built-ins: home dir, username, email (hostname per DESIGN);
  plus [share] redact_patterns from config. Applied to copies only.
- Report: <out>/redaction-report.json listing every hit with pattern, file,
  line, replacement.
- Secret-shaped strings (API-key/token patterns): detected -> the share
  ABORTS non-zero with findings and writes no pages; --allow-findings ships
  the content VERBATIM (never auto-redacted).
- Personal render overrides are ignored: shared compact variants are always
  reminder-free, shared full variants always collapse reminders.
- Multi-session share writes one index.html.

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only.
