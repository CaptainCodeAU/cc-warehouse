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

## DONE 2026-07-19

Slice 11 (share + redaction) COMPLETE through the full loop. Implementer green on
the first gate pass (4 oracle tests). share() redacts the PARSED payload before the
shared renderer (R9), reads [share] redact_patterns share-locally from
<root>/config.toml (the config layering that folds it into load_config is slice 13),
detects secret-shaped strings broadly, aborts the whole batch on a finding unless
--allow-findings, skips-and-continues on a bad short (R10), and builds a self-contained
index via stdlib html.escape. Locked operator decisions taken before finalizing the
plan: explicit --out write-only (defer the warehouse shares/ default + build --rebuild
regeneration); skip-and-continue on a missing/superseded/hidden short; broad secret
heuristics; regex custom patterns.

Reviewers A/B in parallel (A 5 conformance, B 9 adversary). Operator verified every
finding against the code before triage (Guardrail 9): 10 CONFIRMED, 3 REJECTED. Rejected
with reasons recorded: A4 (the redaction report is already the contract-frozen
pattern/file/line/replacement schema; a constant [REDACTED] replacement is REQUIRED
because writing the removed value would leak it into the shipped report; file=short +
line=JSONL-line is the honest coordinate for a pre-render seam); B3 (builtins from the
current process env match the frozen decision and the oracle; per-session-origin identity
is a later enhancement); B8 (broad-detector false positives are the accepted consequence
of the operator's broad choice, with --allow-findings as the hatch).

Fixed in 1 fixer round (of 3). The load-bearing one, B1 (F6): redaction and secret
detection now run on the json-DECODED content of each JSONL line, so a \uXXXX-escaped or
non-ASCII secret/PII can no longer slip past raw-text matching and reappear decoded in the
share (including inside the HTML base64 data-copy-src). B5 (F9): a hostile payload
timestamp is neutralized by validating first_ts against a date shape and reusing
build.projection_dir, so a shared directory can never escape --out. A2/A5 (R9/F8): reuse
build.projection_dir for naming and stdlib html.escape for the index instead of
hand-rolled copies (pyright strict forbids importing the private render._escape /
build._component, so the canonical stdlib/public implementations are used). A3 (R5/F7): a
store read or a projection write failure is reported as an error, distinct from a benign
not-found. B2/B4: the pure-hex carve-out is narrowed to git/sha digest lengths (a 128-hex
secret_key_base is now flagged) and the generic detector covers base64url tokens. B7
(F7): a zero-width custom regex is inert (no content corruption); catastrophic-backtrack
ReDoS on a user-supplied pattern stays a documented risk (stdlib re has no timeout). B9:
username/hostname match at word boundaries so a short login is redacted without shredding
it out of unrelated words. A1/B6: the CLI refuses a populated --out that is not a prior
share; the reviewers' "force=True prunes" premise was REJECTED after verifying
write_projection never prunes (it overwrites only its own five filenames).

9 contract-derived regression tests (tests/test_share_regressions.py, cited on this
ticket). Operator black-box verified 17/17 in temp dirs independent of the fixer
self-report, including the check the oracle tests omit: no leak through the base64
data-copy-src after decoding, and a 40-hex git sha not false-aborting a clean share.
Round count 1 (target <= 2). Gates: 4 oracle + 9 regression green, pyright strict 0, ruff
clean; full suite 16 failed / 169 passed, red for the right reason (test_cli 4 +
test_config 9 are slice-13 CLI/config polish, test_relocate 3 is slice-12). Residual
notes carried forward: builtins are current-env identity (per-origin deferred); the broad
detector may false-positive on long paths / base64 blobs; ReDoS on user regex is
unbounded. Milestone tag slice-11 at completion. Next: ticket 12 (relocate).
