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

- **v1.1 flag groups: COMPLETE 2026-08-01.** All four slices landed the day they were
  defined: 14 per-variant matrix, 15 chrome + date-locale, 16 truncation, 17 the
  `--since`/`--until` window. Tags slice-14..slice-17. The regression anchor at
  `tests/golden/matrix-anchor` outlives the run and future slices reuse it: it pins
  the four projected files, so a slice that moves DEFAULT output breaks it ON PURPOSE.
  Never regenerate it to make a change pass. It moved twice, both times by a recorded
  principal ruling with the delta measured first; the two rulings are written beside
  the anchor in `tests/test_matrix.py`.
- **ARCHIVE-FIRST LAYOUT decided 2026-08-02** (DESIGN 15 entry; R1 and R4 amended in
  section 14). The product is a READABLE archive: the folder tree is the deliverable,
  each session folder holds its own JSONL beside the projections, `objects/` retires,
  and the catalog becomes a disposable index. Tickets 18 (real-data coverage) then 19
  (the layout itself), in that order - a migration is the worst moment to meet a new
  entry type. This is closer to a version cut than a slice.
- **Ticket 18 (real-data coverage): DONE 2026-08-02.** Every entry and content-block type
  a payload carries now renders something; anything the parser does not name renders a
  marker AND increments the manifest's new top-level `unrecognised` key (principal ruling,
  option 4: NOT a third `loss` amendment, because a rendered entry is not a lost one).
  Verified read-only over all 13,836 objects: 0 unrecognised, 0 parse failures, anchor
  untouched. **Ticket 19 is NEXT and is not started; it needs scoping with the principal.**
- **Ticket 20 (thinking withheld): DONE 2026-08-02.** Closed the open ruling ticket 18
  carried. The 41,458 empty `thinking` blocks now fold their count into the phase caption
  (8,709 added lines corpus-wide, not the 41,458 a per-block marker would cost), the
  manifest gains a top-level `withheld` block, and `--thinking-withheld
  {caption|marker|off}` lets the operator overrule the default. The text was never
  delivered to this machine: Claude Code stopped writing it at v2.1.69 (2026-03-05), and
  it is a MODEL property, zero of 25,470 opus-4-8 blocks ever carried text.
- **CONTRACT NARROWED 2026-08-02 (principal ruling, DESIGN 15 block 1 non-scope).** The
  frozen "no thinking key" decision protects the absence of a toggle for whether thinking
  RENDERS, not the absence of the word in a key name. The oracle fence enforcing it was
  narrowed to the decision and now asserts the protected property directly instead of
  matching a substring. Renaming the key to dodge the check was offered and rejected.
- **NEXT after those: v1.1 proper**: FTS5 + `ccw search` (session AND message hits) + HTML archive
  search + `ccw import`/inbox; **then v1.2**: `ccw mcp`. `ccw import` adopts slice 17's
  window definition when it lands.
- **Pre-release, not pre-v1**: DESIGN 15 item 6 (PyPI name re-check before the repo goes
  public) and item 7 (registry backup/export story).
- **Named v1.1 candidate, recorded not dropped**: honouring the reader's OS setting via
  `prefers-color-scheme` for SHARED pages. Same reader-respect argument that decided
  `--hljs`; needs a light palette designed and the highlight.js token colours re-checked
  for contrast.
- **Non-blocking**: the architecture review was HELD 2026-07-24 at `1517bba` (commit
  18fa5be) and its decay banner is retired; this line previously said a review was still
  due, which was stale. Since that snapshot `src/` has moved again (slices 14-17), so the
  board's line refs will have drifted and a re-derive is worth doing before its cards are
  acted on. `cc-warehouse-architecture/SOURCE.md` is canonical.

## Standing lessons (full form in HARNESS section 8)

- **Slice completeness is not contract completeness.** The oracle suite was written from the
  tickets, the tickets from the slice list. A green suite proves the code matches the TESTS;
  only reading the CONTRACT against the CODE proves the tests cover the contract.
- **A ticket's finding list is evidence, not a specification.** Across 12a and 12b, four of
  ten carried findings were mis-stated: two understated, one mis-classified, one whose
  mechanism was the reverse of the assumption. Re-derive every finding by execution first.
- **The same defect class recurs across modules.** Fixing one instance of the private-config-
  reader bug would have left a live redaction leak in `ccw share`. Census the class.
  Sharpened 2026-08-01 (slice 14): a census performed on ONE file is still an instance fix.
  The F6 overclaim in the compact note was fixed and written up as a class fix, citing this
  very lesson, while its twin sat live in the HTML emitter of the same module - green,
  because the oracle test called one emitter and not the other. Knowing the lesson does not
  apply it. Test shared behaviour across BOTH emitters by construction.
- **Non-destructiveness is a precondition, not an intention.** Prove a backup before touching
  its original, so the worst outcome of a future defect is a refusal rather than a loss.
- **A green suite is a statement about the inputs you imagined.** 639 tests and three
  gates did not contain a payload with a lone surrogate, because nobody invents one; 11 of
  13,836 real sessions had one, and the first `ccw build` at scale failed on 9 (2026-08-01).
  Run the product on real data before believing it works. R10 is why it was diagnosable:
  the batch named each failed item and carried on instead of aborting on the first.
- **A read-only-looking command must be proved read-only.** `ccw sweep -h` printed no help
  and imported 13,836 sessions into a real warehouse (2026-08-01): eight of ten verbs never
  checked for the flag. Exit 0 plus output is NOT evidence nothing happened; the test that
  catches it asks whether the world changed. Fixed at the dispatcher, because per-verb
  guards are only as complete as whoever remembered to add them.

`/refresh` (in `.claude/commands/`) is the currency sweep; `/architecture` owns the review
board and is outside `/refresh`'s scope. Cross-project context lives in the
claude-code-transcripts project memory (`cc-warehouse-and-cc-vantage`); sibling project:
`../cc-vantage`.
