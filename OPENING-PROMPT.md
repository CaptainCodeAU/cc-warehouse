# Opening prompt for a fresh session, 2026-08-21

Read `CLAUDE.md` first, as always. This file is a pointer into where the
previous session left off, not a replacement for it.

## Next task: ask the operator. Nothing is queued.

The folder-sweep track has no obvious next target. Both named candidates are
now resolved (see below). Do NOT invent one. Ask.

The open work that IS on record, in case the operator wants a pointer:

- **Ticket 27.5-27.8** in `harness/tickets/27-collapse-to-one-folder.md`.
  27.1-27.4 are all closed, including the `objects/` delete.
- **Ticket 24.7**, the session-start capture freshness signal, partly closed
  from outside this repo by `ccw-watch`. See `CLAUDE.md`.
- **Ticket 28**, the backlog register, including the go-public audit.
- **Ticket 30**, incremental rebuild, motivated by the weekly archive job's cost.

## What this session did

Ran the five-step folder sweep on `~/CODE/my-claude-code-transcripts`, at the
operator's pick. Investigation only. Nothing imported, nothing deleted.

**Verdict: the tree is fully absorbed, static, and nothing refills it.**

- 3.38 GiB, 6,462 sessions, 22,364 files, 0 symlinks, exactly 3 levels deep.
- Full file census closes with no remainder: 9,355 `page-NNN.html` + 6,496
  `index.html` (1 root, 33 project, 6,462 session) + 6,462 `UUID.jsonl` + 51
  `.DS_Store` = 22,364.
- Newest session CONTENT is 2026-07-24. The only newer files are two
  `.DS_Store`. The tree is STATIC.
- `ccw import --from ... --dry-run` (using `~/.local/bin/ccw`, 0.1.2): **6,462
  items, 0 would be stored, 0 written.**
- Byte-compared every payload against the archive folders, not just the
  catalog: **6,460 exact sha256 matches, 2 where the archive holds a strict
  superset, 0 genuinely absent.**
- Controlled sweep of 55,329 script/config files found nothing that writes to
  the tree.

`CLAUDE.md`'s "DO NOT DELETE" bullet for this tree has been amended with the
measurement. Its gate is satisfied. **The delete itself was NOT run and still
needs the operator's explicit word at the moment of running.** A satisfied gate
is not consent.

## Two corrections this session made to the record

1. **`CLAUDE.md` said `cc-warehouse` is "the only thing capturing Claude Code
   sessions on this machine".** False, and the instrument behind it was too
   narrow: it only enumerated `~/.claude/settings.json`. Project-local
   `settings*.json` under `~/CODE` still register a `SessionEnd` hook running
   `export_transcript.sh`. The prior session's figure of 12 was an undercount
   from a shallower walk that missed two `.worktrees/` copies and a duplicated
   project dir. **CLOSED 2026-08-21, see the next section: 16 armed, not 17,
   and the operator ruled "leave them".**
2. **`CLAUDE.md` recorded this tree as 6.5 GB / 7,698 sessions.** It measures
   3.38 GiB / 6,462. The drop is stated as UNRESOLVED, not explained away: no
   session folder left any project dir after 2026-07-24, and the root mtime of
   2026-08-14 cannot be told apart from a Finder `.DS_Store` rewrite.

## The export_transcript.sh hooks: investigated and CLOSED 2026-08-21

The operator asked for a thorough investigation of my "17 hooks still rebuild
it" claim, then ruled **leave them in place**. Do not reopen this without being
asked. Full account is in `CLAUDE.md` beside the capture section; the short form:

- **16 armed, not 17.** The 17th registers in `settings.minimal.json`, which
  Claude Code never reads, and its script is missing too.
- **The scripts write nothing.** They shell out to `claude-code-transcripts json
  <path> -o ~/CODE/claude-code-transcripts -a --json`.
- **That CLI has ZERO destructive calls** across its 26 source files, checked
  with a proven control. It cannot delete. It only READS `~/.claude` on this
  path. It cannot reach the warehouse or the archive.
- **They are dormant.** 12 of the 16 projects have never had a session; 3 more
  have zero; the one that has any last saw one 2026-07-10.
- **Cost per fire, measured:** 0.30s, 7 files, 1,992 KiB.
- **Unresolved:** an earlier note claimed the hook fired 2026-08-18. Could not
  be reproduced, and the evidence folder was deleted before the check.
- **Hazard worth remembering:** `claude-code-transcripts` is installed EDITABLE
  against the frozen SPECIMEN repo, so its live binary is a view of that repo's
  `src/`. One more reason never to edit the specimen.

## The method, if another folder ever needs sweeping

1. Survey: `ls -la`, `du -sh`, depth histogram, symlink count.
2. **Do not trust a "retired" or "static" claim. Check real mtimes across the
   WHOLE tree**, and separate CONTENT files from metadata like `.DS_Store`.
   Two `.DS_Store` files were the entire reason this tree's top-level mtime
   looked three weeks fresher than its newest real session.
3. If it is still growing, find WHY. Search the global settings, the plugin
   caches, AND every PROJECT-LOCAL `.claude/settings*.json` under `~/CODE`.
   Use maxdepth 7, not 5: worktrees and duplicated project dirs live deeper.
   The destination folder name usually is NOT in settings.json, it is inside
   the hook SCRIPT, so search for the script name.
4. **Every count must carry a control token known to be present, in the same
   breath.** This session's first writer hunt used a control that hit 0 of 90
   files and would have reported a confident false "nothing found".
5. Cross-reference with `ccw import --from DIR --dry-run` using
   `~/.local/bin/ccw`, never the repo `.venv` copy. PROVE it is read-only:
   snapshot the archive folder count and the catalog sha before and after, and
   expect drift from the LIVE capture hook. Attribute any change before
   blaming the dry-run. The instrument that settles it is
   `~/.claude/logs/ccw-hook.log`, which timestamps every capture to the second.
6. **`would-skip` proves CATALOGED, not RECOVERABLE.** With `objects/` retired,
   the payload lives in the archive session folder. Byte-compare.
7. **When a payload looks absent, suspect the census before the archive.**
   Keying on the DIRECTORY NAME is path-as-identity and F4 is why the product
   does not do it. Re-resolve by content hash and by the payload's own
   `sessionId`. This session had 7 false absences from exactly that bug.

## Standing rule, unchanged

27.9 stays withdrawn regardless of what else in this project goes green.
Nothing is ever deleted from `~/.claude`.
