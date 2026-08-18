# Incremental archive rebuild — proposal

**ACCEPTED 2026-08-18 as ticket 30 (`harness/tickets/30-incremental-archive-
rebuild.md`), DONE the same day.** Every evidence claim below was verified
against the running code and held (line numbers, the real-run numbers, the
manifest keys, the hidden-session short-circuit). The proposed check shipped
essentially as sketched, keyed on `source_hash` + `config`, PLUS two fields
this document did not name: `renderer_version` (a new top-level manifest key -
without it a `ccw` upgrade would leave every folder frozen at the old render
format forever) and the sub-agent list (without it a sub-agent captured after
its parent's last render would never get recorded). Both were found necessary
because skipping the RENDER, not just the write, is a strictly stronger claim
than this project's existing `ccw build` incrementality makes, and each closes
a way the archive could go stale silently otherwise. The open question below
(interrupted-run safety) was answered by reading the code rather than by
adding a new mechanism: `manifest.json` was already written last, and that
ordering is now a pinned oracle test rather than incidental. See the ticket for
the full account, including a third hazard this document did not anticipate
and that surfaced only by running the test suite. The rest of this document is
kept VERBATIM as filed, per this project's convention of not rewriting a
finding after the fact.

---

**Original status, as filed:** proposal, not a ticket. Written 2026-08-18 by an
assistant session working outside this repo (a dotfiles-project audit that
happened to trace through `ccw archive`). Not scoped or reviewed by this
project's own process. Whoever picks this up should verify every claim below
against the current code before trusting it — line numbers and behavior may
have drifted.

The point of this document is to hand over evidence, not a decision. Make
the judgment call yourself: whether this is worth doing, whether it becomes
a numbered ticket, and how to close the one open question below.

## The problem, with real numbers

A weekly `launchd` job runs `ccw archive --to ~/cc-warehouse-archive`. On a
real run against this machine's warehouse (2026-08-18):

```
20779 folders written (392 archived without projections), 7 not sessions,
45 refused as smaller, 0 failed, 0 project.json written
```

Measured wall-clock: ~40 minutes, ~90% CPU, the whole time (`ps -o
pid,etime,pcpu,stat`). That is a full pass over **every** session in the
warehouse, every single run — not just the ones that changed since last
time.

Root cause, in code:

- `_migrate_locked()` (`archive.py`) walks every row in the catalog every
  run. There is no incremental cursor — no "only rows touched since X".
- `write_session_folder()` (`archive.py`, ~line 433) already treats the raw
  `.jsonl` source efficiently: it only rewrites it if the new payload is
  strictly larger than what's on disk; equal-size is left alone (~line
  487-498, the "replace-if-larger" path, R14).
- But the four **generated** files (`transcript.md`,
  `transcript.compact.md`, `conversation.html`, `conversation.compact.html`,
  plus `manifest.json`) are written unconditionally, every run, for every
  session that isn't hidden — `for name, payload in
build.iter_projection_files(rendered, options): store.atomic_write(...)`
  (~line 523). No existing-content comparison gates that loop.

So the source data is already handled efficiently. Only the human-readable
pages built from it are rebuilt from scratch every week, whether or not
anything actually changed.

## What already exists that makes this cheap to build

`build_manifest()` (`render.py`, ~line 2237) writes two fields that are
described in its own docstring as **frozen keys, DESIGN section 6** — a
locked contract, not incidental:

- `source_hash` — the payload's own sha256. Always present whenever a
  manifest is written at all.
- `config` — `asdict(options)`, a full serialization of the `RenderOptions`
  used for that specific render.

Both already exist, per session, on disk, today. Nothing new needs to be
invented to detect "has the chat content changed" or "have the render
settings changed since this page was built" — the fingerprints for both
are already being computed and written; they're just not being read back
and compared before deciding to rebuild.

## Proposed check (sketch — not a final design)

Before doing the expensive part (`store.get()`, parse, render,
`atomic_write` ×5) for a given catalog row:

1. Does `<session-folder>/manifest.json` already exist?
2. If yes: does its `source_hash` match this row's current content hash,
   **and** does its `config` match `asdict(current_options)`?
3. If both match — skip entirely. No store read, no parse, no render, no
   write.
4. If either differs, or no manifest exists yet — fall through to exactly
   today's path, unchanged.

This only touches the _decision to skip_. Nothing about
`write_session_folder`'s own internals (the size-based refusal, the hidden
short-circuit, the atomic-write mechanics) needs to change.

Because `config` is already stored per-session rather than in one shared
location, there's no separate "did settings change globally" pass needed
either — a settings change simply makes every affected session's own
`config` field stop matching on the next run, and each one individually,
correctly, decides it needs rebuilding. No new storage, no cross-run marker
file, no risk of that marker getting out of sync with reality.

## A case already checked and ruled out — not a gap

"Hidden" sessions (bookkeeping entries with no manifest at all) already
skip rendering entirely via the existing `if hidden: return
FolderResult(...)` short-circuit in `write_session_folder` (~line 514-517).
They were never part of the 40-minute cost, so this feature doesn't need
to special-case them. Confirmed by reading the code, not assumed.

## Open question — needs real investigation, not a guess

`write_session_folder`'s own docstring says manifest.json is written
"last-ish" among the generated files. If a run gets interrupted mid-loop
(killed process, crash, laptop sleep at the wrong moment), could a folder
end up with a manifest that still says "I match" sitting next to a page
that's actually stale from an even older render — and would this skip-check
then trust that manifest and wrongly skip a folder that needs rebuilding?

Before implementing, whoever picks this up should:

- Confirm the actual current write order of
  `build.iter_projection_files()`'s yielded names.
- Decide whether `manifest.json` needs to become a strict "written
  absolutely last = this folder is complete and consistent" guarantee
  (it may already effectively be this — verify, don't assume).
- Write an oracle test for the interrupted-mid-write case either way, per
  this project's own stated methodology (oracle tests before
  implementation, not ported from anywhere).

## Not open — already agreed, carry forward as-is

Keep a full-rebuild escape hatch that ignores the skip-check entirely and
redoes everything, mirroring the existing `ccw build --rebuild` precedent
for projections. Whether that's a new flag on `ccw archive` or reuses
something existing is an implementation detail, not a design question.

## Deliberately left to you

- Whether this becomes a numbered ticket, or something lighter.
- Where new code and tests should live relative to the existing
  `archive.py` / `tests/test_archive_live.py` structure.
- Whether the skip-check should also short-circuit the `store.get()` read
  itself (more savings, slightly more surface area) or only skip the
  render + write step (simpler, smaller diff, most of the savings —
  `store.get()` is a local read, not the expensive part).

## Evidence trail, for verification

- `archive.py` — `_migrate_locked()`, `write_session_folder()`, the R14 lock
  comment describing the replace-if-larger rule
- `render.py` — `build_manifest()`, ~line 2237-2284
- `store.py` — `atomic_write()` (no content-comparison short circuit today;
  it always writes)
- A real run's log: `~/.claude/logs/ccw-archive.log`
- Measured via `ps -o pid,etime,pcpu,stat -p <pid>` during the run this
  document is based on

---

## Appendix: other changes made on this machine this session

**Unrelated to the proposal above** — do not fold these into the
incremental-rebuild design. This is deployment/integration context: facts
about how `ccw` is actually invoked and consumed on THIS machine that
changed today, from outside this repo. None of it shows up by reading this
repo alone, and none of it is reflected in `BRAINSTORM.md` / `DESIGN.md` /
`SPEC.md`, which describe the project's own design, not one machine's
deployment. If this project keeps any memory or notes about its own
real-world usage, fold these in — a stray assumption from before today
could otherwise overwrite or contradict what's true now.

1. **A new external consumer now depends on `ccw doctor`'s exact text
   output.** `~/.local/bin/ccw-watch` (source: a different repo,
   `fifty-shades-of-dotfiles`, at `home/.local/bin/ccw-watch`) runs `ccw
doctor` once at the start of every Claude Code session, on this whole
   machine — wired into `~/.claude/settings.json`, nothing inside this
   repo. It parses `doctor`'s text output: the `hook` line's wording, and
   the `Uncaptured: N session(s)` figure via a regex. A future change to
   `doctor`'s output format would silently break this consumer. This
   dependency is also the direct cause of the `_hook_commands`
   SessionEnd-scoping bug fixed today (`CHANGELOG.md` 0.1.2) —
   `ccw-watch`'s own command string is what triggered it, by containing the
   substring `ccw`.

2. **A new scheduled caller of `ccw archive` exists as of today, outside
   this repo.** `com.captaincodeau.ccw-archive`, a macOS `launchd` job at
   `~/Library/LaunchAgents/com.captaincodeau.ccw-archive.plist`, runs `ccw
archive --to ~/cc-warehouse-archive` weekly (Sunday 03:00). Before today,
   nothing on this machine called `ccw archive` on a schedule at all — only
   `ccw sweep` did, via the pre-existing daily `com.captaincodeau.ccw-sweep`
   job. This new job is also the exact thing the proposal above is about.

3. **A competing exporter that used to run alongside this project has been
   retired.** This machine used to also run `export_transcript.sh` →
   `claude-code-transcripts` (an unrelated tool, not part of this project)
   on every Claude Code SessionEnd, writing a second, separate copy of
   every session to `~/CODE/claude-code-transcripts/`. Confirmed duplicate
   capture of a live session by both systems at once before this was
   retired. That hook has been removed (`fifty-shades-of-dotfiles` repo,
   `.claude/settings.json`) as of today, after confirming nothing else
   depended on its output tree. `cc-warehouse` is now the only thing
   capturing Claude Code sessions on this machine.

4. **Nothing above changed this repo's own runtime behavior**, except the
   `doctor.py` fix already reflected in `CHANGELOG.md` (0.1.2) and this
   repo's own git history — that part IS visible from inside this repo.
   Items 1-3 live in a different repo and in `~/.claude/settings.json`;
   they're recorded here so this project doesn't have to independently
   rediscover them.
