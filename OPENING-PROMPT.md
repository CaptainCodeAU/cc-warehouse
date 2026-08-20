# Opening prompt for a fresh session, 2026-08-21

Read `CLAUDE.md` first, as always. This file is a pointer into where the
previous session left off, not a replacement for it.

## Next task: repeat the "folder sweep" investigation on another folder

The operator wants to run the SAME investigation this session ran on
`~/CODE/claude-code-transcripts` (below) against a DIFFERENT folder next.
**Which folder was not named yet - ask the operator before starting**, do
not assume `~/CODE/my-claude-code-transcripts` or any other candidate.

**The method, as it was actually run (investigation only - do not run a real
`ccw import` or delete anything without being separately asked, same rule
this session followed):**

1. Survey the target folder: `ls -la`, `du -sh`, top-level structure. Note
   whether it looks like a Claude Code session tree (uuid-named dirs/files)
   or something else.
2. **Do not trust a claim that a folder is "retired" or "static" - check
   real file mtimes across the WHOLE tree, not just the top level.** This
   session's big finding came from exactly this: the top folder's own mtime
   looked old, but individual session files inside it were 3 days old,
   which contradicted a two-week-old CLAUDE.md claim that nothing writes
   there anymore.
3. If the tree turns out to be genuinely still growing, find WHY before
   doing anything else: `grep -rl` the suspect script/tool name across
   `~/.claude/settings.json`, `~/.claude/settings.local.json`, plugin
   caches, AND - this is the part that is easy to skip and was the actual
   gap - every PROJECT-LOCAL `.claude/settings.json`/`settings.local.json`
   under `~/CODE` (`find ~/CODE -maxdepth 5 -iname "settings*.json" | xargs
   grep -l <name>`). A hook registered in one project's local settings is
   invisible to any check that only enumerates the global file.
4. Cross-reference every session against the archive with `ccw import
   --from <DIR> --dry-run` (`~/.local/bin/ccw`, the real installed one, not
   the repo's `.venv` copy - see CLAUDE.md's frozen-install section for why
   that distinction matters). This is genuinely read-only (`import_tree.
   plan` takes no lock, opens the catalog read-only) - PROVE that rather
   than trust it, by snapshotting a cheap fact (e.g. `find ~/cc-warehouse-
   archive -mindepth 2 -maxdepth 2 -type d | wc -l`) before and after and
   confirming it is unchanged. `would-skip` on every item means the exact
   content is already cataloged; `would-store` means something is either
   missing or is a different version (see the note on ticket 29 mechanism 1
   below for why a smaller/older version being imported is safe now).
5. Full file-type census of the WHOLE tree before declaring anything safe
   to delete: `find <dir> -type f | sed 's/.../pattern/' | sort | uniq -c`
   to make sure nothing besides the obvious session files is in there
   (attachments, sub-agent files, symlinks, config). This session found the
   claude-code-transcripts tree was exactly 75 session jsonl + 75 index.html
   + 350 page-NNN.html + 1 `.DS_Store`, nothing else - checked, not assumed.

## What this session found (record, for context - not open work)

**`~/CODE/claude-code-transcripts` (the one with NO "my-" prefix, 267 MB,
75 sessions): investigated, confirmed fully absorbed, THEN DELETED by the
operator.** Verified on disk as of this session's end: the folder no
longer exists (`ls` returns "No such file or directory"), `ccw doctor`
stays fully green. All 75 sessions matched `would-skip` on `ccw import
--from ... --dry-run` (exact content hash already cataloged) before the
delete happened, and the full file census (see method step 5) found nothing
else in the tree worth keeping.

**Found in the process, NOT YET ACTED ON - a real gap in a standing
CLAUDE.md claim.** CLAUDE.md says "`cc-warehouse` is now the only thing
capturing Claude Code sessions on this machine... confirmed by enumerating
all hooks in `~/.claude/settings.json`". That enumeration only ever checked
the GLOBAL settings file. **12 separate project-local `.claude/
settings.json` files still register a `SessionEnd` hook running the OLD,
supposedly-retired `.claude/hooks/export_transcript.sh`**, and it was
CONFIRMED FIRING as recently as 2026-08-18 (payload content, not just file
mtime) - three days before this session, and likely still firing today
since nothing has been changed:

- `PRD_Storage/where_the_link_goes`
- `Tools/google-auth-2fa-exporter`
- `Tools/clawfidence`
- `Playground/skills_playground`
- `Ideas/GitFoot_FluidAudio_vanilla`
- `Ideas/GitFoot_DetailedSpec_GSD`
- `Ideas/my_claude_code_scaffolding`
- `Ideas/Whryte_app_clone`
- `Ideas/Browser_Automation_System`
- `CaptainCodeAU/Tax_Pipeline_1`
- `CaptainCodeAU/SCRIPTS/devtools-snippets`
- `CaptainCodeAU/EXTENSIONS/where_goes_the_link`

Every SessionEnd in these 12 projects writes a duplicate copy into (what
was) `~/CODE/claude-code-transcripts` - which no longer exists, so the next
session end in any of these 12 will likely just recreate it from scratch.
**This is genuinely a separate cleanup from the folder investigation itself
- deleting the folder does not remove the leftover hook that refills it.**
Not fixed. Not this repo's code to fix (it's per-project hook config, not
`cc-warehouse`), so probably a job for a different tool/session than this
one, but flagging it here so it is not lost. CLAUDE.md's "only thing
capturing sessions" line is stale and should be corrected when someone next
touches that section - not done yet, out of this session's explicit scope
(the operator asked for investigation, not fixes).

**Two other folders were characterized this session, informationally, not
acted on:**
- `~/cc-warehouse-journals` (420 KB, 7 files) - confirmed byte-identical to
  its home inside the archive (`_not-sessions/journals/`). CLAUDE.md already
  says this is "the principal's to remove" once that copy exists, and it
  does. Not deleted.
- `~/cc-warehouse-prepublish-backup` (4.4 MB, git bundles dated 2026-08-09/
  10) - nothing in this project's own docs or code mentions it. From the
  filenames alone (`pre-rewrite`, `pre-strip`, `POST-strip-clean`,
  `FINAL-clean`, `replacements.txt`) it looks like a safety net from
  scrubbing personal info out of the git history before this repo went
  public - INFERRED from evidence, not confirmed from any record. Not
  evaluated further.

## Ticket 27/29 status: FULLY CLOSED, including the delete

**Ticket 29 mechanism 1 (head selection ranks by payload recency, not
insertion order) and ticket 27.4 (retiring `objects/`) are BOTH fully done
as of this session.** The code fix, its oracle tests, and a full live
re-verification (rename-aside exercise, real Herdr session, real sweep) all
happened in the prior session - see `contract/DESIGN.md` section 15,
"2026-08-20, ticket 29 mechanism 1" and `harness/tickets/27-collapse-to-
one-folder.md` for that account, not repeated here.

**What's NEW this session: the operator ran the actual delete.**
`~/cc-warehouse-data/objects` no longer exists on disk (verified), and `ccw
doctor` stays fully green afterward. Ticket 27's remaining slices (27.5-27.8)
are the only open work left in that ticket, and are independent of anything
above - pick them up from `harness/tickets/27-collapse-to-one-folder.md` if
that's ever the next task, but it is NOT what this handoff is asking for
next (see the top of this file).

## Standing rule, unchanged

27.9 stays withdrawn regardless of what else in this project goes green.
