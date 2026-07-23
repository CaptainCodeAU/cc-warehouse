# cc-warehouse

Content-addressed, immutable warehouse for AI conversation sessions (Claude Code,
claude.ai exports, future sources), projected into uniform markdown/HTML files.
CLI: `ccw`. Successor to `claude-code-transcripts` (that repo is the frozen SPECIMEN;
read it, never modify it).

## Read these before working (they are the contract)

1. `contract/BRAINSTORM.md` - approved scope: version cuts, locked decisions, rejected items.
2. `contract/SPEC.md` - the specimen's real behavior with keep/change/drop verdicts.
3. `contract/FINDINGS.md` - failure classes (F1-F10) the design must make impossible.
4. `contract/DESIGN.md` - the architecture; section 14 rules R1-R14 are enforceable in review.
5. `contract/HARNESS.md` + `harness/prompts/` - HOW code gets built (roles, gates, loop).

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

- `contract/` the five LOCKED contract documents + `contract/diagrams/` | `docs/`
  user-facing guides (install, quickstart, configuration, sharing) | `harness/prompts/` role
  prompts | `harness/tickets/` slice tickets (filled in Phase 2) | `temp/` scratch
  (gitignored once git init lands) | `cc-warehouse-architecture/` the code-architecture
  review board (SOURCE.md is canonical, index.html is rendered from it by
  `/architecture`; owned by that command, outside `/refresh`'s sweep scope).
  CLAUDE.md stays at repo root: Claude Code only auto-loads it from here.
- Warehouse DATA lives outside this repo (default `~/cc-warehouse-data`); code and
  data never share a directory.

## Current phase

**v1 is CLOSED (2026-07-24).** Every slice in the DESIGN section 16 build order landed and
carries its milestone tag: slice-01..13, with slice 12 split into 12a (containers) and 12b
(content), 14 tags in all. Gates green (ruff, pyright strict, 403 tests, zero stubs) and
zero forward-looking "lands in slice N" promises left in `src/`.

The DESIGN section 16 **v1 exit review was held and closed** the same day. It found two
contract-vs-code gaps that no DONE annotation, milestone tag or green test could surface,
and the principal ruled on both: `ccw project` was implemented 1-of-5 against the section 7
table (which silently broke the per-project config feature, since DESIGN 8 names
`ccw project show` as the way to get the registry id it is keyed by), and the dispatcher
accepted an undocumented internal `notify` verb. Both closed. The two rulings the review
left open, `--hljs` and `--theme`, were also taken and closed that day.

**This section is a STATUS POINTER, not a changelog.** It was compacted on 2026-07-24 from
158 lines after a census showed its per-slice narrative was a LOSSY duplicate of records
that own those facts more completely (one slice-03 finding was in HARNESS and the ticket
but had never made it here at all). Nothing was lost; the detail lives at:

- **per-slice records, retros, process lessons** -> `contract/HARNESS.md` section 8 (append-only)
- **what each slice did, its findings and their outcomes** -> `harness/tickets/<nn>-*.md`
  (each carries a dated DONE annotation; findings keep their original wording with the
  verified outcome appended)
- **decisions and the reasoning behind them** -> `contract/DESIGN.md` section 15 (append-only)
- **architecture candidates and their states** -> `cc-warehouse-architecture/SOURCE.md`

## OPEN / next (no silent omissions)

- **v1.1 flag groups**: per-file matrix, HTML chrome defaults, truncation, `--since`/`--until`.
- **then v1.1 proper**: FTS5 + `ccw search` + `ccw import`; **then v1.2**: `ccw mcp`.
- **Pre-release, not pre-v1**: DESIGN 15 item 6 (PyPI name re-check before the repo goes
  public) and item 7 (registry backup/export story).
- **Named v1.1 candidate, recorded not dropped**: honouring the reader's OS setting via
  `prefers-color-scheme` for SHARED pages. Same reader-respect argument that decided
  `--hljs`; needs a light palette designed and the highlight.js token colours re-checked
  for contrast.
- **Non-blocking**: a fresh architecture review is due. The board's line refs have decayed
  across 20 commits and +4,036 lines of `src/`; `cc-warehouse-architecture/SOURCE.md`
  carries the measured per-file table and flags every affected card.

## Standing lessons (full form in HARNESS section 8)

- **Slice completeness is not contract completeness.** The oracle suite was written from the
  tickets, the tickets from the slice list. A green suite proves the code matches the TESTS;
  only reading the CONTRACT against the CODE proves the tests cover the contract.
- **A ticket's finding list is evidence, not a specification.** Across 12a and 12b, four of
  ten carried findings were mis-stated: two understated, one mis-classified, one whose
  mechanism was the reverse of the assumption. Re-derive every finding by execution first.
- **The same defect class recurs across modules.** Fixing one instance of the private-config-
  reader bug would have left a live redaction leak in `ccw share`. Census the class.
- **Non-destructiveness is a precondition, not an intention.** Prove a backup before touching
  its original, so the worst outcome of a future defect is a refusal rather than a loss.

`/refresh` (in `.claude/commands/`) is the currency sweep; `/architecture` owns the review
board and is outside `/refresh`'s scope. Cross-project context lives in the
claude-code-transcripts project memory (`cc-warehouse-and-cc-vantage`); sibling project:
`../cc-vantage`.
