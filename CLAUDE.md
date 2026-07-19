# cc-warehouse

Content-addressed, immutable warehouse for AI conversation sessions (Claude Code,
claude.ai exports, future sources), projected into uniform markdown/HTML files.
CLI: `ccw`. Successor to `claude-code-transcripts` (that repo is the frozen SPECIMEN;
read it, never modify it).

## Read these before working (they are the contract)

1. `docs/BRAINSTORM.md` - approved scope: version cuts, locked decisions, rejected items.
2. `docs/SPEC.md` - the specimen's real behavior with keep/change/drop verdicts.
3. `docs/FINDINGS.md` - failure classes (F1-F10) the design must make impossible.
4. `docs/DESIGN.md` - the architecture; section 14 rules R1-R14 are enforceable in review.
5. `docs/HARNESS.md` + `harness/prompts/` - HOW code gets built (roles, gates, loop).

Decisions locked in these documents are not relitigated in-session; propose contract
edits to the principal instead.

## Hard rules

- Python 3.12+, **stdlib-only runtime**. Tests may import pytest, nothing else
  third-party.
- **Oracle tests before implementation.** Never port tests from the specimen suite.
- `uv` for everything (`uv run pytest`, `uv run pyright`, `uv run ruff check`).
  pyright strict + ruff are merge gates from commit one. Strict mode is enforced via
  `typeCheckingMode = "strict"` in pyproject; the pyright CLI has no `--strict` flag,
  so where contract docs say "pyright --strict" read "pyright in strict mode".
- Every file write is tmp-file + `os.replace` (DESIGN R2). No deletes outside the
  projections/shares rebuild module (R4). Sources and stored objects are read-only.
- Session/transcript data is NEVER deleted or mutated by anything, ever.
- Public repo: commit as the GitHub noreply
  (`git -c user.name='CaptainCodeAU' -c user.email='69835039+CaptainCodeAU@users.noreply.github.com'`);
  never commit personal data (real username, machine names, personal paths); tests
  and docs use generic placeholders.
- No em-dashes in any authored text (docs, comments, commit messages). ASCII
  punctuation in code tokens.
- Never start a Bash command with `cd`; prefer `git -C` / absolute paths. Bash-tool
  `rm`/`cp`/`mv` bypass the shell safety wrappers; deletions are permanent, so get
  explicit confirmation first.

## Layout (grows during the build)

- `docs/` the five contract documents + `docs/diagrams/` | `harness/prompts/` role
  prompts | `harness/tickets/` slice tickets (filled in Phase 2) | `temp/` scratch
  (gitignored once git init lands). CLAUDE.md stays at repo root: Claude Code only
  auto-loads it from here.
- Warehouse DATA lives outside this repo (default `~/cc-warehouse-data`); code and
  data never share a directory.

## Current phase

Phase 1 (contract docs) complete 2026-07-17. Phase 2 complete 2026-07-18: bootstrap
(license PolyForm Noncommercial 1.0.0, gates wired), the oracle suite (red for the
right reason), and the 13 tickets in `harness/tickets/`. HARNESS trial run (ticket
01, store module) complete 2026-07-18 through the full loop; retro in HARNESS
section 8; slice 01 tests green, remaining suite red for the right reason. Main
build under way per DESIGN section 16. Slice 02 (catalog + registry) COMPLETE
2026-07-18: fixer round 1 (of 3) resolved 9 confirmed reviewer clusters,
operator-verified via black-box probes; retro in HARNESS section 8. Slice 03
(parser + conversation model) COMPLETE 2026-07-18: fixer round 1 (of 3) resolved
7 confirmed reviewer clusters (silent-loss / crash / overclaim), 6 contract-derived
regression tests added (HARNESS section 4) and operator black-box verified 12/12;
retro in HARNESS section 8. Slice 04 (capture hook + notify) COMPLETE 2026-07-18:
fixer round 1 (of 3) resolved 6 confirmed reviewer clusters (detached notify helper
off the hook critical path, best-effort sinks, the SPEC-3 _unresolved rung), 3
rejected; 3 contract-derived regression tests; operator black-box verified 21/21;
retro in HARNESS section 8. Slice 05 (sweep) COMPLETE 2026-07-18: fixer round 1
(of 3) resolved 3 confirmed reviewer clusters (unreadable-source-subdir named via
os.walk onerror, malformed --source refused conservatively, lock-held distinct
refusal), 4 rejected; 3 contract-derived regression tests
(tests/test_sweep_regressions.py); operator black-box verified 31/31; sweep reuses
capture.capture_transcript verbatim (R9/F8); retro in HARNESS section 8. Milestone
tags slice-01..05. Slice 06 (transcript.md emitters, full + compact) COMPLETE
2026-07-18: adds the normalized conversation model (turns/blocks) to parser.py and a
single-core markdown emitter to render.py; fixer round 1 (of 3) resolved 5 confirmed
reviewer clusters (turn-grouping demotion, fence corruption/injection, reminder
fail-open leak, commit tool_result text loss, R8 honesty) plus a tool-coverage add,
2 rejected; 10 contract-derived regression tests
(tests/test_render_md_regressions.py); operator black-box verified 18/18; retro in
HARNESS section 8. Milestone tags slice-01..06. Slice 07 (HTML emitters full +
compact, + manifest) COMPLETE 2026-07-19: an in-house stdlib markdown-to-HTML
renderer + HTML page emitter + build_manifest in render.py, reusing the slice-6
markdown fragments as the copy-as-md single source of truth (R9/F8); fixer round 1
(of 3) resolved 5 confirmed reviewer clusters (HTML passthrough injection, duplicate
sha256, multi-repo commit mislink, second CDN reference, R8 docstrings), 1 rejected,
visual chrome deferred; 6 contract-derived regression tests
(tests/test_render_html_regressions.py); operator black-box verified 10/10; retro in
HARNESS section 8. Milestone tags slice-01..07. Slice 08 (build/render orchestration;
un-stubs the render child) COMPLETE 2026-07-19: `ccw build` projects the catalog into
projections/<label>/<date>_<slug>_s-<hash12>/ (4 files + manifest), `ccw render`
(--session child + ad-hoc) and `ccw project rename` land, all writes via
store.atomic_write and the only sanctioned deletions in build.py; fixer round 1 (of 3)
resolved 6 confirmed reviewer clusters + the render-child error-notify (a permanent
prune-on-failure data-loss path, an unguarded prune crash, the missing locks/build
lock, the ad-hoc --out guard, silent rename-noid, head-only render), 1 rejected; 5
contract-derived regression tests (tests/test_build_regressions.py); operator black-box
verified; retro in HARNESS section 8. Milestone tags slice-01..08. Slice 09 (status + ccw verify CLI)
COMPLETE 2026-07-19: `ccw status` reads the catalog only (F5 zero object opens);
`ccw verify` wraps store.verify_walk and cross-checks the catalog against the objects
both directions (corrupted / orphan-never-deleted / missing), read-only (R4); fixer
round 1 (of 3) resolved 2 confirmed reviewer clusters (verify crashing on a
malformed/NULL catalog hash, an unreadable-object label), 2 refuted; 3 contract-derived
regression tests (tests/test_status_verify_regressions.py); operator black-box verified
7/7; retro in HARNESS section 8. Milestone tags slice-01..09. Slice 10 (migrate +
retire) COMPLETE 2026-07-19: `ccw migrate <old-root>` imports a legacy archive through
capture.capture_transcript verbatim (R9/F8, hash dedupe collapses duplicate copies F1),
records a per-file manifest to <root>/logs/migrate-manifest.json via store.atomic_write
(R2), under a locks/migrate O_EXCL lock (R14/DESIGN 13); `ccw migrate --retire` is a
separate consent-gated single rename only (D1, no import); fixer round 1 (of 3) resolved
3 confirmed reviewer clusters (non-regular *.jsonl named-not-dropped incl. the FIFO-hang
trap, retire refuses an existing target rather than clobber-an-empty-dir or crash,
missing locks/migrate lock), 0 rejected; 3 contract-derived regression tests
(tests/test_migrate_regressions.py); operator black-box verified 6/6; retro in HARNESS
section 8. Milestone tags slice-01..10. Slice 11 (share + redaction) COMPLETE 2026-07-19:
`ccw share s:<key> ... --out <dir>` builds a sanitized static site from COPIES (store +
projections keep full fidelity, R4); redaction runs on the json-DECODED payload before the
shared renderer (R9) so a \uXXXX-escaped / non-ASCII secret cannot leak through the HTML
base64 copy-src; secret-shaped strings abort the whole share unless --allow-findings ships
them verbatim; reuses build.projection_dir naming + stdlib html.escape (R9/F8). Reviewers
A/B ran in parallel (5 conformance + 9 adversary); operator verified each against the code
(Guardrail 9): fixer round 1 (of 3) resolved 10 confirmed clusters (B1 decoded-content
redaction, B5 timestamp path-traversal, A2/A5 reuse-not-duplicate, A3 error-vs-not-found,
B2/B4 hex-carveout + base64url, B7 zero-width-regex, B9 word-boundary builtins, A1/B6 --out
guard after refuting the "force prunes" premise), 3 rejected (A4 report schema frozen +
constant token required, B3 current-env builtins, B8 broad-detector tradeoff); 9
contract-derived regression tests (tests/test_share_regressions.py); operator black-box
verified 17/17 incl. base64 copy-src decode; retro in HARNESS section 8. Milestone tags
slice-01..11. Next: ticket 12 (relocate).
`/refresh` (in `.claude/commands/`) is the currency sweep.
Cross-project context lives in the claude-code-transcripts project memory
(`cc-warehouse-and-cc-vantage`); sibling project: `../cc-vantage`.
