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
- **NOTHING IS EVER DELETED FROM `~/.claude` (principal, verbatim, 2026-08-04:
  "I do NOT want you to delete anything from `~/.claude`. You do not have my
  permission to delete anything from `~/.claude`.").** Not deleted, moved,
  emptied, pruned, rotated or "cleaned up", by this project or by anything an
  agent runs on its behalf. Ticket 27.9 used to say "clear `~/.claude`" and is
  WITHDRAWN; every gate it was waiting on went green on 2026-08-04, so a future
  session will find the preconditions satisfied and MUST NOT read that as
  permission. Older notes in this repo say `~/.claude` "is scheduled to be
  wiped" and use it to justify urgency; that is SUPERSEDED. The archive being a
  proven second copy is the win, and a second copy is added, never traded.
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
  **THE GATE THIS RULE WAS WAITING ON IS NOW SATISFIED, MEASURED 2026-08-21.** Ticket
  25.4/25.5 landed 2026-08-04 and the tree was re-swept end to end. Today it measures
  **3.38 GiB, 6,462 sessions**, not 6.5 GB / 7,698; `du` and the apparent byte sum agree,
  so nothing is hidden by compression. `ccw import --from ~/CODE/my-claude-code-transcripts
  --dry-run` reports **6,462 items, 0 would be stored, 0 written** (6,461 would-skip plus
  1 would-keep-not-a-session). Cataloged is not recoverable, so every payload was ALSO
  byte-compared against the archive folders directly: **6,460 exact sha256 matches, 2 where
  the archive holds a strict superset (the tree copy is a byte prefix), 0 genuinely absent.**
  Seven first read as absent and were the F4 path-as-identity census bug again, keyed on the
  DIRECTORY NAME; re-resolved by content hash across all 23,731 archive jsonl, 6 are filed
  under the payload's own `sessionId` and 1 under `_not-sessions/imported/`. The tree is also
  STATIC: newest session content is 2026-07-24, the only newer files are two `.DS_Store`, and
  a controlled sweep of 55,329 script/config files found NOTHING that writes to it (the 16
  `export_transcript.sh` hooks all target `~/CODE/claude-code-transcripts`, the other name).
  Unresolved and stated as unresolved: the drop from the recorded 7,698 folders to 6,462.
  No session folder left any project dir after 2026-07-24 (all 54 project mtimes are
  <= that date), and the root mtime of 2026-08-14 is indistinguishable from a Finder
  `.DS_Store` rewrite. It does not move the verdict, because the rescue import ran
  2026-08-04, before that date. **A SATISFIED GATE IS NOT CONSENT.** This bullet no longer
  blocks a delete on missing data, but the delete itself still needs the principal's
  explicit word at the moment of running, same as ticket 27.4.
- **`ccw` IS INSTALLED AS A FROZEN SNAPSHOT, so editing this repo does NOT change what
  the capture hook runs.** After any change you want the hook to pick up, from the repo
  root with the venv active: **`uv_tool_reinstall_current_project --no-extras`**.
  No mode flag is needed, and naming one yourself is worse: `pyproject.toml` carries
  `[tool.uv-tool] install-mode = "frozen"`, the function reads it and prints
  `pyproject.toml pins this project to frozen installs`, so the command cannot drift from
  what the project requires.
  WHY FROZEN (principal ruling 2026-08-03): an editable install makes `~/.local/bin/ccw` a
  live view of `src/`, so a half-finished edit or a branch switch becomes the system-wide
  capture path at every session end. Proved by execution: with `doctor.py` deliberately
  corrupted in the checkout, the installed `ccw doctor` still ran.
  THE PIN IS ADVISORY, so VERIFY rather than trust it. uv itself ignores `[tool.uv-tool]`;
  only the principal's shell functions honour it (`--frozen` and the pin were added there
  2026-08-04 by a separate session); it is inert on any other machine; and an explicit
  `--editable` overrides it. Two instruments that cannot both miss:
  - `ccw doctor` prints an `install` line with the mode AND the directory it is running
    from. This reads `cc_warehouse.__file__`, which is where the code actually loaded.
    **RUN IT FROM OUTSIDE THE REPO, or it answers about the wrong binary.** This
    repo's `.envrc` (tracked 2026-08-21) sources `.venv/bin/activate`, so any shell
    that has `cd`-ed here puts `.venv/bin/ccw` ahead of `~/.local/bin/ccw` on PATH
    and `ccw doctor` then truthfully reports **`editable`** - about the venv copy,
    which is NOT what the hook runs. Seen and misread as a rule violation on
    2026-08-21. The unambiguous form:
    `env -u VIRTUAL_ENV PATH="$HOME/.local/bin:/usr/bin:/bin" ~/.local/bin/ccw doctor`,
    which reports `frozen`, agreeing with `direct_url.json`.
  - PEP 610 records what uv did:
    `find ~/.local/share/uv/tools/cc-warehouse -name direct_url.json -exec cat {} \;`
    -> `"dir_info":{}` frozen, `"dir_info":{"editable":true}` not. Use `find`, NOT a glob:
    the file sits four levels down under a version-stamped `.dist-info`, and a glob that
    misses prints NOTHING, which reads as "no editable flag" and therefore as frozen. That
    is the dangerous wrong answer, silently. I shipped exactly that bug here on 2026-08-03.
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
  (gitignored once git init lands) | `tools/` tracked scratch tooling that is
  NOT part of `ccw`: outside `src/`, so not subject to pyright strict, the oracle
  suite or the packaging test (both `pyproject.toml`'s sdist `exclude` and
  `tests/test_packaging.py`'s `FORBIDDEN_DIRS` name it explicitly). Added
  2026-08-21 for `tools/ccstats/`, a read-only session-statistics collector
  that used to live in `temp/` and was one `rm -rf temp/` from being lost with
  no history; see `tools/ccstats/README.md`. | `cc-warehouse-architecture/` the
  code-architecture review board (SOURCE.md is canonical, index.html is
  rendered from it by `/architecture`; owned by that command, outside
  `/refresh`'s sweep scope).
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

- **THE ACTIVE TRACK is tickets 22-27, defined 2026-08-03, in that order. 22 through 26
  are CLOSED; 27 is the only one left and it is UNBLOCKED.** 22 protect the unprotected
  (DONE 2026-08-03) -> 23 `ccw doctor` + sweep `--dry-run`/`--quiet` (DONE 2026-08-03) ->
  24 make capture work (DONE 2026-08-04; 24.7 DONE 2026-08-23, see below) -> 25 rescue the only
  copies (DONE 2026-08-04) -> 26 prove then back up (DONE 2026-08-04, including 26.4) ->
  27 collapse to one folder (CORRECTED 2026-08-20, was stale here: **27.1 DONE
  2026-08-05** (`ccw reindex` shipped) and **27.2 DONE**, verdict "catalog is
  disposable for sessions and labels, NOT YET for aliases" - see the ticket file
  for the real-data comparison. **27.3 DONE 2026-08-20**: `keep_objects = false`
  is live in `~/.config/cc-warehouse/config.toml` (operator's explicit go-ahead
  at the time, per this ticket's own requirement), verified with a real Claude
  Code session that the vault stopped growing while the archive kept working -
  see `contract/DESIGN.md` section 15, "2026-08-20, ticket 27.3". **27.4's
  non-destructive half (rename `objects/` aside, exercise) was RUN 2026-08-20
  and FOUND A REAL BLOCKER, then the blocker was FIXED the same session:**
  `ccw build` failed 4 of 21,460 sessions with `objects/` renamed away,
  root-caused (after a first, corrected misdiagnosis) to ticket 29's
  ALREADY-OPEN "Mechanism 1" - head selection could promote a catalog row
  whose payload the archive folder does not actually hold, because it picked
  "the newest INSERT" instead of "the newest PAYLOAD". **Ticket 29 mechanism
  1 is now DONE**: `build._heads`/`head_for_short` rank by payload recency
  (`COALESCE(last_ts, captured_at)`) instead of insertion order - see
  `contract/DESIGN.md` section 15, "2026-08-20, ticket 29 mechanism 1". The
  full 27.4 exercise was re-run after the fix and passed clean end to end
  (`ccw build`: 4 failed -> 0 failed against the same real corpus); `objects/`
  was restored afterward. **27.4 IS DONE. THE DELETE HAS BEEN RUN, and this
  paragraph said the opposite until 2026-08-21.** It read "the DELETE ITSELF
  was still not run and still needs the principal's explicit word", which by
  then was false, and a stale pending-destructive note is the exact shape that
  gets a destructive step done twice. Re-verified first-hand on 2026-08-21,
  four ways: `~/cc-warehouse-data/` now holds only `catalog.sqlite`, `locks`
  and `logs` (52 MB) with NO `objects/` and no renamed-aside copy anywhere
  under `$HOME` at depth 2; `ccw doctor` reports `keep_objects=False`, "capture
  is working" and "0 problems in the 25 most recently captured folder(s)"; the
  archive holds 22,130 session folders and 22,137 payload `.jsonl` (9.3 GB);
  and 40 catalog sessions sampled at random resolved to a real archive payload
  40 times out of 40. `OPENING-PROMPT.md` (written 2026-08-21) already recorded
  it as closed, so the drift was between documents, not about the fact.
  **27.5-27.7 CLOSED 2026-08-22. 27.8 was attempted, measured, and reverted -
  it is NOT done.** 27.5 (whether `root` moves into the archive): decided
  AGAINST by the principal, after 27.6's guard read found that merging would
  make every `ccw archive --to <archive_root>` call trip the existing
  "must not be the warehouse itself" refusal; no code changed. 27.7 (`ccw
  verify` becomes archive integrity) turned out to already be shipped and
  tested; only the ticket's paperwork was stale. **27.8 (retire `store.py`)
  is blocked on a real finding, not an oversight**: `keep_objects: bool =
  True` is still the tool's shipped default project-wide (only this
  machine's config overrides it), so the vault code is not dead in general.
  Flipping that CODE default (tried on the principal's word, oracle-tests-
  first) broke 7 pre-existing tests, all genuine resilience tests (an
  unwritable archive, a deleted archive JSONL) - it would have removed a
  safety net from every install that sets `archive_root` without explicitly
  opting into `keep_objects = false`, inverting R5 (today's default IS the
  conservative branch). Reverted cleanly; full suite re-confirmed green.
  Retiring `store.py` for real needed a bigger call: dropping `keep_objects` as
  a feature and making `archive_root` mandatory. **THAT CALL WAS MADE
  2026-08-23: the principal chose to keep both** (the vault stays as a
  write-time safety net for any install that has not explicitly turned it
  off). **27.8 stays NOT DONE, `store.py` stays, and this is not open for
  re-litigation without a new explicit reason.** See
  `harness/tickets/27-collapse-to-one-folder.md` and `contract/DESIGN.md`
  section 15 ("2026-08-22, ticket 27.5/27.6" and "...27.8") for the full
  account, and `harness/tickets/29-which-copy-is-the-current-one.md` for the
  unrelated ticket 29 material this section also used to point to.
  **THE RULE 27.4 WAS UNDER STILL STANDS FOR EVERY FUTURE DESTRUCTIVE STEP:
  a green gate is not consent, and the principal's word is needed at the moment
  of running.** 27.9 WITHDRAWN AND STAYS WITHDRAWN).
  28 is the backlog register (nothing dropped silently), including the go-public audit.
  Read the ticket files; they carry the measurements and the blast-radius checks behind
  each step.
- **TICKET 26 IS COMPLETE (2026-08-04) AND THAT IS WHAT UNBLOCKS 27, so read this before
  touching 27.** 26.1-26.3 closed the integrity and containment gates; **26.4 put the
  archive on the external drive and VERIFIED it independently of the copy tool**, hashing
  both sides in full: 116,433 of 116,433 files, both manifests digesting to
  `ee1996858860...`. The archive exists in two places for the first time, which is the
  property every destructive step in 27 was waiting on. **A SATISFIED GATE IS NOT CONSENT**
  (the whole reason 27.9 exists as a withdrawn ticket): 27's two DESTRUCTIVE slices need
  the principal's word at the moment of running, and 27.9 is not to be done at all.
  Still owed on 26 and it is the principal's to do by hand: a `BACKUP-PROVENANCE.json`
  beside the copy, since this machine's sessions cannot write to that volume (macOS TCC
  refuses even `ls`, re-tested 2026-08-05).
- **CAPTURE IS LIVE. This list said "capture has never run automatically" and that is now
  FALSE (corrected 2026-08-05).** The plugin wrapper is repointed at `ccw hook` through an
  explicit resolved path (never `uv tool run`, which is what broke it), the operator's
  `/plugin` update has landed, and the evidence is first-hand: `~/.claude/logs/ccw-hook.log`
  holds successful captures, `ccw doctor` reports "capture is working", and
  `ccw archive --verify` grew from 19,224 to 19,230 folders with 0 problems, matching the
  hook's own success count exactly. `com.captaincodeau.ccw-sweep.plist` covers the sessions
  a hook cannot see (24.5). **STILL OPEN inside 24: 24.7**, the session-start capture
  freshness signal. There are 0 `ccw` references in `~/.claude/settings.json` and none of
  the 7 SessionStart commands is a ccw check, so a capture that silently stops would still
  not announce itself at session start; the CI watch is the shape to copy.
  **THE "0 `ccw` references" CLAIM ABOVE IS STALE, corrected 2026-08-18 from outside this
  repo.** `~/.local/bin/ccw-watch` (a different repo, `fifty-shades-of-dotfiles`) now runs
  at SessionStart on this machine and its own settings.json command string contains the
  substring `ccw`, so 24.7's stated freshness gap is at least partly closed by something
  this repo does not own or control.
  **24.7 IS NOW FULLY DONE, 2026-08-23, owned by this project rather than borrowed from
  `ccw-watch`.** A new `SessionStart` hook, `ccw-freshness-check.py`, ships in
  `plugins/cc-capture/hooks/` (THIS repo, registered in that plugin's own `hooks.json`
  beside the existing `SessionEnd` capture hook) and reads `ccw doctor`'s own PASS/FAIL
  verdict, escalating on how many consecutive session-starts in a row it has been broken,
  clearing the moment it is fixed. **It was FIRST built in the wrong place** -
  `gz-claude-code-plugins`, home of `claude-transcript-exporter`, a plugin already retired
  since ticket 28.19 moved cc-warehouse's real plugin into this repo on 2026-08-10
  (`4b8dde4`, installed as `cc-capture@cc-warehouse`; `~/.claude/settings.json`'s
  `enabledPlugins` has no entry at all for the old slug) - and redone here once that was
  found. Also corrected from the ticket's own literal wording after running the first draft
  against real data: it does NOT alarm on the raw `Uncaptured: N session(s)` figure, which
  sits at 250-350 on this machine permanently and which `doctor.py` itself treats as
  non-blocking - a threshold on that number alone printed ALERT every session on a
  perfectly healthy install. Ticket 28.19's own entry in `harness/tickets/28-backlog.md` was
  itself stale (recorded open when it had shipped two weeks earlier) and is corrected too.
  Full account: `harness/tickets/24-make-capture-work.md`'s "24.7 DONE 2026-08-23" section.
  **`ccw doctor`'s TEXT OUTPUT IS THEREFORE A PUBLIC
  COMPATIBILITY SURFACE, not an internal detail**: `ccw-watch` parses the `hook` line's
  wording and the `Uncaptured: N session(s)` figure with a regex. Changing that wording or
  dropping that figure breaks an external consumer silently. This dependency is also the
  direct cause of the `_hook_commands` SessionEnd-scoping bug fixed the same day
  (`CHANGELOG.md` 0.1.2): `ccw-watch`'s own command string is what tripped it, by
  containing the substring `ccw`. Separately, a weekly `launchd` job,
  `com.captaincodeau.ccw-archive`, now runs `ccw archive --to ~/cc-warehouse-archive`
  (Sunday 03:00) beside the pre-existing daily `com.captaincodeau.ccw-sweep`; see ticket 30
  for the incremental-rebuild work that job's cost motivated. And the competing exporter
  this repo used to run alongside (`export_transcript.sh` -> a separate, unrelated
  `claude-code-transcripts` tool, writing a second copy of every session) is retired as of
  the same day, confirmed by enumerating all hooks in `~/.claude/settings.json`: `cc-warehouse`
  is now the only thing capturing Claude Code sessions on this machine.
  **THAT LAST CLAIM IS FALSE AND THE INSTRUMENT BEHIND IT WAS TOO NARROW, corrected
  2026-08-21.** Enumerating `~/.claude/settings.json` cannot see a hook registered in a
  PROJECT-LOCAL `.claude/settings.json`, and 17 of them still register a `SessionEnd` hook
  running `export_transcript.sh`. Population: 135 `settings*.json` under `~/CODE`
  (explicit walk, maxdepth 7); control token `export_transcript` hit 17, so the count is
  from a proven instrument. 16 such scripts exist and every destination string in them
  resolves to `~/CODE/claude-code-transcripts` (14 tilde form, 1 absolute, 1 stale pointing
  at a different home dir). A prior session recorded this as 12; that undercount came from
  a shallower walk that missed two `.worktrees/` copies and a duplicated project dir.
  `cc-warehouse` is the only thing capturing INTO THE WAREHOUSE, which is the property that
  matters here; it is NOT the only exporter still armed on this machine.
  **THOSE 17 WERE THEN INVESTIGATED IN FULL AND THE OPERATOR RULED "LEAVE THEM"
  (2026-08-21). The count is 16, not 17, and my own 17 was the overclaim this time.**
  The 17th is `~/CODE/Scaffoldings/fifty-shades-of-dotfiles/.claude/settings.minimal.json`,
  a filename Claude Code never reads, whose referenced script does not exist either. Inert
  twice over. Of the 16 armed, 15 target this machine's home. All 17 registrations are on
  `SessionEnd` with matcher `prompt_input_exit|logout|other`, so `/clear` does not fire them.
  **The scripts write nothing themselves.** They shell out to
  `claude-code-transcripts json <path> -o ~/CODE/claude-code-transcripts -a --json`, so the
  behaviour is the CLI's, not the hook's. Read that CLI's 26 source files with a proven
  control: **ZERO destructive calls** (no `rmtree`, `os.remove`, `.unlink(`, `shutil.move`,
  `os.rmdir`), so it cannot destroy anything; it only READS `~/.claude` on this path; and it
  cannot reach `~/cc-warehouse-data` or `~/cc-warehouse-archive` at all. It DOES
  `mkdir(parents=True)`, so it recreates `~/CODE/claude-code-transcripts` on first fire, FLAT
  as `<uuid>/`, not `Project/uuid/` (that shape came from the plugin's `hook` subcommand).
  **They also barely ever fire.** Measured two ways with control-proven instruments
  (`~/.claude/projects` and the archive): 12 of the 16 projects have never had a session at
  all, 3 more have a project dir holding zero sessions, and the only one with sessions
  (`~/CODE/CaptainCodeAU/SCRIPTS/devtools-snippets`) last had one 2026-07-10. Cost per fire,
  measured by running the exact command into a scratchpad on a 976,062-byte transcript:
  **0.30s wall, 7 files, 1,992 KiB**, no browser, no network, no log. On that evidence the
  operator chose to leave all 16 in place; fixing them is per-project hook config in 16
  unrelated repos and is not this repo's code to change.
  **UNRESOLVED, recorded not explained away:** a prior session's note says this hook was
  "CONFIRMED FIRING as recently as 2026-08-18". That could not be reproduced. No hooked
  project had a session near that date in either instrument, and the folder that would have
  held the evidence was deleted before the check.
  **WORTH KNOWING, and it is this repo's own documented hazard on someone else's tool:**
  `claude-code-transcripts` is installed **EDITABLE** (`"dir_info":{"editable":true}`)
  against `~/CODE/CaptainCodeAU/claude-code-transcripts`, the frozen SPECIMEN repo. The live
  binary those 16 hooks invoke is therefore a live view of that repo's `src/`. That is
  exactly the failure mode the frozen-install rule above exists to prevent for `ccw`, and it
  is one more reason not to edit the specimen.
- **TICKET 25 IS COMPLETE (2026-08-04). The only-copies are rescued.** `ccw import
  --from DIR` shipped, and the live run imported **4,756 payloads with 0 failures** in
  10m22s: the archive went 14,472 -> 19,226 folders and `ccw archive --verify` reports
  **19,224 folders, 0 problems**. The 7 workflow journals are in at
  `<archive>/_not-sessions/journals/`, hash-verified, originals untouched. The legacy
  tree has 0 files modified (F9). Ticket 26.2's gate reads **0 payloads whose content is
  not in the archive**; the 7 remaining hash misses are all strict PREFIXES of copies the
  archive holds in full, which is why that gate had to be reformulated (a hash miss is
  not a content miss, and as written it could never have reached 0).
  **The acceptance census reads 8, and all 8 are IN the archive** (6 under their
  payload's `sessionId` rather than their legacy folder name, 2 under `_not-sessions/`).
  Genuinely absent: 0. The census keyed on the directory name, which is path-as-identity;
  F4 is why the product does not. Fix the census, never the import.
- **Ticket 29 opened and half closed the same day.** Mechanism 2 is DONE (`86394d3`):
  `archive.write_session_folder` used to refuse a smaller payload's JSONL and then render
  that same refused payload over the folder's markdown, HTML and manifest. Found by
  VERIFYING a throwaway import that had reported 7,671 stored / 0 failed / exit 0.
  **Mechanism 1 is OPEN and unscoped, and now PROVED rather than suspected (2026-08-05).**
  A probe inserted a NEWER copy then an OLDER copy of one `session_uuid`: `build._heads`
  returned the OLDER as the single head. `catalog._latest_version` picks the right
  supersedes TARGET, but a head is "a row no other row supersedes", so the newest INSERT
  is the head whatever the payload says. Harmless for the archive folder now; still wrong
  for `ccw status`, `ccw render --session` and any future search. Do not touch
  `catalog.add_session` or `build._heads` without scoping it with the principal first.
  **The docstring beside it USED TO CLAIM THE OPPOSITE** ("a late-imported old export
  therefore never displaces the newer copy"), which would have told the next reader this
  was closed; corrected in `8435aeb`, docstring bytes only.
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
  **THE REASON NOTHING WAS CAPTURED WAS THAT NOTHING INVOKED CAPTURE, and ticket 24 FIXED
  IT (corrected 2026-08-05; this paragraph used to be in the present tense).** `ccw hook`
  is still absent from `~/.claude/settings.json`, and that is CORRECT rather than a gap:
  it is registered by the `claude-transcript-exporter` plugin's `hooks.json`, so grepping
  settings.json alone reports a false 0. The plugin wrapper is the instrument to read.
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
- **Ticket 28.13 DONE 2026-08-23.** The architecture review held 2026-07-24 at `1517bba`
  was found 2026-08-21 to be anchored to a commit that no longer existed (the repository
  was deleted and re-created on 2026-08-10 for the go-public audit, ticket 28.20, which
  rewrote history). A fresh review re-derived every card at HEAD `4824098` (257 commits),
  using 5 parallel Explore agents in place of the named review skill
  (`/mattpocock-skills:improve-codebase-architecture`, not enabled in this session), plus
  a new lens for `archive.py` - a 900+ line module the archive-first rewrite (tickets
  19-30) added entirely after the last review, never looked at by this board before.
  Two agent-reported findings were independently re-verified from source and turned out
  to be LIVE BUGS rather than architecture debt, and were fixed the same session:
  `write_subagent` silently dropping a same-size, content-different re-capture with no
  record anywhere (sub-agents have no manifest.json, so this was worse than the
  session-writer twin ticket 30 had just fixed - genuinely invisible, F6), and
  `ccw share --out` having no guard against writing inside the warehouse's own
  `objects/`/`projections/` trees, unlike its `ccw render --out` sibling (F9; both
  `share.py` write sites use `force=True`, so this was a real overwrite path). The
  board's new top recommendation, C12, is exactly this: one shared replace-if-larger
  primitive instead of three copies that can (and did) drift independently. Full account:
  `cc-warehouse-architecture/SOURCE.md`'s "2026-08-23 - FRESH REVIEW" change-log entry.
- **Ticket 32 DONE 2026-08-23**: the detached render child (SPEC section 2.5/5) can fail
  with ZERO trace - real live incident the same day, found via `ccw doctor`'s desync
  check, fixed by hand (`ccw render --session s:<key>`), then closed for good. Shipped
  (1) `__main__.py`, used only by the two detached children, now logs any otherwise-
  uncaught exception to `logs/capture.jsonl` before re-raising, WITHOUT touching SPEC
  section 5's locked "all stdio to DEVNULL" line (a first instinct that would have);
  (2) a new verb `ccw repair`, deliberately NOT a flag on `ccw doctor` (which stays
  read-only by construction and is `ccw-watch`'s external compatibility surface),
  that shares doctor's own bounded recency scan (`doctor.desync_detail`, promoted
  public) and re-renders whatever it flags. Verified on real data (0 problems, wrote
  nothing). NOT wired into any scheduled job yet - a system-level change outside this
  repo, left for the principal. Full account:
  `harness/tickets/32-detached-render-child-visibility.md`.

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
board and is outside `/refresh`'s scope; `/dashboard` builds and opens the live ccstats
dashboard (`tools/ccstats/dashboard.py`), project-scoped, not part of either sweep. Cross-project
context lives in the claude-code-transcripts project memory (`cc-warehouse-and-cc-vantage`);
sibling project: `../cc-vantage`.
