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
tags slice-01..05. Next: ticket 06 (transcript.md emitters).
`/refresh` (in `.claude/commands/`) is the currency sweep.
Cross-project context lives in the claude-code-transcripts project memory
(`cc-warehouse-and-cc-vantage`); sibling project: `../cc-vantage`.
