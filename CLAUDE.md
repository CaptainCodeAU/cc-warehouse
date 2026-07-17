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
  pyright --strict + ruff are merge gates from commit one.
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

Phase 1 (contract docs) complete 2026-07-17. Next, when the principal asks: Phase 2
oracle tests + gates, then the HARNESS trial run on the store module, then the main
build per DESIGN section 16. Cross-project context lives in the claude-code-transcripts
project memory (`cc-warehouse-and-cc-vantage`); sibling project: `../cc-vantage`.
