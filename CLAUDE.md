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
- **DO NOT DELETE `~/CODE/my-claude-code-transcripts` (6.5 GB).** It looks like the
  retired exporter's leftovers and was called "dead weight" in-session on 2026-08-03.
  It is not. Measured that day: of its 7,698 session folders, **4,756 are in NEITHER
  `~/.claude/projects` NOR the archive**, 4,754 of them with a recoverable `.jsonl`
  (392.2 MiB), spanning 2026-02-14 to 2026-07-03, and **4,141 predate the warehouse's
  first capture (2026-05-01)**. Instrument: distinct UUID folder names minus both other
  sets, deduplicated (a `duplicates/` subtree inflates a naive walk from 4,756 to 9,541).
  Ticket 25.4/25.5 imports them; nothing may remove the tree before that lands and is
  verified. `~/CODE/claude-code-transcripts` (224 MB, the 16 legacy per-project hooks)
  was measured the same day and holds ZERO sessions absent from both, so it is genuinely
  redundant; the two names differ by one word, so check which one you are looking at.
- **`ccw` IS INSTALLED AS A FROZEN SNAPSHOT, so editing this repo does NOT change what
  the capture hook runs.** Reinstall after any change you want the hook to pick up:
  `uv tool install --force --reinstall --python 3.14 .` from the repo root. It was
  installed EDITABLE on 2026-08-03 and reinstalled non-editable the same day by principal
  ruling: an editable install makes `~/.local/bin/ccw` a live pointer at
  `src/`, so a half-finished edit or a branch switch becomes the system-wide capture path
  at every session end. Proved by execution: with `doctor.py` deliberately corrupted in
  the checkout, the installed `ccw doctor` still ran. NOTE the principal's own
  `uv_tool_install_current_project` / `uv_tool_reinstall_current_project` both hardcode
  `--editable`, so neither covers this case; use the raw command above.
- `~/cc-warehouse-journals/` holds the 7 workflow journals (409,059 bytes), the only
  vault objects with no byte-identical archive copy (they carry no `sessionId`, so
  ruling (a) excludes them). Copied there 2026-08-03 with every sha256 re-verified on
  arrival, originals untouched; see its `PROVENANCE.json`. Ticket 25.7 gives them a
  reserved home inside the archive, after which this folder is the principal's to remove.
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
  user-facing guides (TODAY: only `sharing-and-redaction.md`; install, quickstart and
  configuration guides are NAMED HERE BUT DO NOT EXIST, corrected 2026-08-02 after this
  line claimed four for weeks) | `harness/prompts/` role
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
(content), 14 tags in all. Gates green at that point (ruff, pyright strict, 403 tests
at v1 close; the live count moves with the suite and is not restated here) and
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

- **THE ACTIVE TRACK is tickets 22-27, defined 2026-08-03, in that order.** Capture has
  never run automatically and stopped even manually working on 2026-07-24; five sets of
  data exist in exactly one place. 22 protect the unprotected (DONE 2026-08-03) ->
  23 `ccw doctor` + sweep `--dry-run`/`--quiet` -> 24 make capture work -> 25 rescue the
  only copies -> 26 prove then back up -> 27 collapse to one folder. 28 is the backlog
  register (nothing dropped silently), including the go-public audit. Read the ticket
  files; they carry the measurements and the blast-radius checks behind each step.
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
- **Ticket 19 (archive-first layout): the EXPORT works; the archive is NOT LIVE.**
  Done 2026-08-02: 19a naming, 19b zone config, 19c folder writer, 19d migration, 19e
  integrity check, 19f project.json, 19h the `ccw archive` verb.
  **"6 of 7 slices" was a MISLEADING framing of mine, corrected 2026-08-02.** It was 6 of
  7 slices in MY CUT, and the cut covered BUILDING an archive, not LIVING in one.
  **CORRECTED AGAIN 2026-08-03 (ticket 22.4): the paragraph that stood here was STALE and
  would have had a future session re-implement shipped features.** It claimed "`capture.py`
  still calls `store.put`, so every new session lands in the old store and the archive
  drifts until someone re-runs the verb by hand". That was true before slice 19k. It is
  now FALSE: `capture.py:168-169` calls `_archive_source` and `_archive_subagents_of`
  UNCONDITIONALLY on the fresh-identity path, and `_archive_source` writes the archive
  folder synchronously inside the hook (its docstring explains why the detached render
  child must not be the thing that makes a session safe). `sweep.py` routes through
  `capture.capture_transcript` "exactly as the hook does", so a sweep populates both trees
  and files sub-agents under their parents. THREE things this list called missing are
  already built: dual-write, sub-agent capture (ticket 21), and the read half of an index
  rebuild (`archive.py:647` `read_projects`, which no verb calls; ticket 27.1 adds
  `ccw reindex`). Still genuinely open: 19g `share`, `status`/`relocate`/`project` on
  archive labels, retiring `objects/`, and reconciling `ccw verify` with ruling (b) which
  says it BECOMES archive integrity (today it is `ccw archive --verify` and plain `verify`
  still checks the vault).
  **THE REAL REASON NOTHING IS CAPTURED IS THAT NOTHING INVOKES CAPTURE.** `ccw hook` is
  absent from `~/.claude/settings.json` (0 references) and has never run; all 13,836
  stored sessions arrived via manual `ccw sweep`. Tickets 22-27 close this.
  **RUN AT SCALE:** `~/cc-warehouse-archive` holds 13,829 folders + 57 `project.json`,
  built in 6 minutes with 0 failures and verified with 0 problems, twice (the second run
  proved idempotence). **NOTHING HAS BEEN SWAPPED**: `~/cc-warehouse-data` is untouched
  and still the live warehouse; hook, sweep and build still write there. The swap is an
  open decision for the principal and should come last.
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
