# Ticket 45: prove a source is absorbed before it is deleted (`ccw absorbed`)

Status: OPEN, scoped 2026-09-29 from three read-only audits run 2026-09-28. Not
started. The operator chose this over "fix only the collision" and "by hand".
Opened 2026-09-29.

## The question that opened it

The operator asked, in his words: if he deletes session data from `~/.claude`
after it has been archived, will the archive ever follow that deletion? He wants
it ADDITIVE, never a MIRROR, so the source tree can be pruned and the disk
reclaimed. (The standing CLAUDE.md rule that AGENTS never delete from `~/.claude`
is unchanged by this ticket; the deletion here is his own hand, later.)

## What was measured (2026-09-28, session scratchpad `additive/`, all sandboxed)

**Additive: YES.** Three helpers, then the conductor re-checked the load-bearing
claims against the code and the real archive:

- Code audit: no code path deletes, renames, moves, hides or retires anything in
  the archive or the catalog because a source path vanished. Delete primitives
  exist only in `build._prune` (projections, off here), `share.py`'s own staging,
  `store.py` lock helpers, `relocate` (explicit verb) and `migrate --retire`
  (consent-gated). `hidden` is set once from payload content; `retired` only on
  project merge. Every reader (render child, repair, build, share, weekly
  `ccw archive --to`, reindex) reads the archive's own hash-checked JSONL, never
  `~/.claude`. Every doctor/status figure that reads the source DROPS when it is
  gone; no blocking check depends on a source existing.
- Sandbox: 12 deletion arms from one baseline (7 sessions, sub-agents,
  tool-results, file-history, todos, history.jsonl with an externalised paste, a
  hidden warmup, a two-version session), full verb set after each. Archive tree
  byte-identical every time; catalog identical except the routine
  `sweep-unchanged` event; the two-version head never moved; stranded siblings
  re-homed idempotently; weekly rebuild plus verify clean with every source gone.
- Red team: additive holds in the ordinary run and fails at FOUR EDGES, none of
  them the archive following a deletion. Fixtures under `additive/redteam/`.

## The four edges (what the archive may never have ABSORBED)

| # | Edge | Loud? | Real on this machine? |
|---|---|---|---|
| F3 | session continued after its last capture, source deleted before the next sweep: archive keeps the older prefix | SILENT: doctor, status, verify, dry-run all green | latent; the live form was seen the same night: one session re-captured at 21:49 while its share copy held the 20:31 prefix, caught only by a size compare (ticket 44 phase 6) |
| F2 | `file-history/<uuid>` and todos left behind for a uuid the archive already holds are never re-homed (`_archive_stranded_file_history` skips known uuids; `_archive_stranded` does not) | SILENT | yes by code shape |
| F4 | payloads with no `sessionId` all land at `<label>/undated_session/session.jsonl` because `capture._archive_source` calls `write_source` with the default stem; replace-if-larger means a later one overwrites an earlier one and, with `keep_objects=false`, the earlier bytes exist nowhere | SILENT (dry-run says would-skip, every build then fails on them) | YES: 2 `undated_session` folders, 14 `undated_*` folders, 15 catalog rows with `session_uuid IS NULL` (read-only count 2026-09-28). A live defect regardless of any deletion. |
| F5 | no instrument compares source BYTES to archive BYTES; `Uncaptured: 0`, `would-skip` and a catalog row all mean "hash seen" | the missing instrument | yes |

Loud but real: F7 (a transcript deleted while its session is live is captured
truncated and spoken once; reconcile then stays quiet because the uuid is
cataloged) and F6 (a `<uuid>.orphaned-*.jsonl` or name/payload mismatch is
archived correctly but reads OVERDUE forever; 0 such files on this machine today).

Also found by the sandbox, not about deletion, filed here so they are not lost:
with `keep_objects=false` a deleted ARCHIVE folder does not come back by itself
(sweep's pre-filter skips a cataloged hash; loud: build/repair/archive exit 1,
doctor RED; recovery `ccw reindex` then `ccw sweep`), and `ccw reindex` renumbers
project ids, which DESIGN 8's per-project config is keyed on.

## Scope

**45a `ccw absorbed [--source DIR] [--manifest OUT] [--json]`**, read-only by
construction like doctor. For every source transcript: locate the archive folder
by PAYLOAD uuid (never filename, F4/F6), compare bytes, and print one verdict per
source: `IDENTICAL`, `ARCHIVE-SUPERSET` (source is a byte prefix of the archive
JSONL), `SOURCE-NEWER` (archive is a prefix of the source), `DIFFERENT`, `ABSENT`.
Then, for the same uuid, every companion kind: `<uuid>/**` (tool-results,
workflows), `subagents/**`, `file-history/<uuid>/**`, `todos/<uuid>-agent-*.json`,
and the referenced paste-cache hashes: each file `HELD` (byte-equal in the folder)
or `UNHELD`. Exit 0 only when every candidate is IDENTICAL or ARCHIVE-SUPERSET
with zero UNHELD. It must NOT consult the catalog's hash set for the verdict (F5).
`--manifest` writes `<archive_root>/_not-sessions/deletions/<date>.json` (path,
sha256, archive folder, verdict) so "was X ever here" has an answer afterwards.
Reference prototype: `additive/redteam/absorbed.py` from the session scratchpad
(flagged all four sandbox edge cases where `sweep --dry-run` flagged none).

**45b the four fixes**, each small, each with an oracle test that fails first:
1. `capture._archive_source` passes `fallback_stem=f"session-{short}"` (or the
   payload sha) to `write_source` so it agrees with `_mirror`/`read_payload` and
   no two uuid-less payloads share a file (F4). FIRST inspect the two real
   `undated_session` folders and the 15 uuid-less rows: whether any earlier
   payload was overwritten is decidable from the catalog (rows whose hash no
   folder holds).
2. `sweep._archive_stranded_file_history` treats a KNOWN uuid the way
   `_archive_stranded` does: copy into that session's folder (F2); same for todos.
3. `cli._run_companions` logs a distinct line when `transcript_path` no longer
   exists, so "found nothing to copy" reads differently from "copied nothing".
4. `doctor._overdue`, `_dispatch_gap` and `status.uncaptured_gap` decide
   "archived?" by payload uuid or content hash rather than filename (F6).

**45c the procedure**, in `docs/operations.md`, nine steps, every one reading
zero or ok before the next: no live sessions (or exclude anything active in the
last 24 h); `ccw sweep` then `ccw repair` green; `ccw archive --verify` 0
problems; `ccw doctor` green with no stalled companions; `ccw absorbed` exit 0;
exclude by construction (no-uuid payloads, orphaned or mismatched names, `memory/`,
`history.jsonl`, `paste-cache/`, `MEMORY/`, and never a project DIRECTORY, only
proven files and dirs); a second copy proven (the share verify, ticket 44); write
the deletion manifest first; delete to the Trash in batches, re-checking doctor
and sweep after each, and empty the Trash only after the next scheduled sweep and
verify are green.

## Out of scope, recorded

- 44d (sub-agent index in the catalog) stays its own slice; 45a reads the tree.
- Making a deleted ARCHIVE folder self-heal from a still-present source (the
  sandbox's negative control) is a separate decision: it means the pre-filter
  keys on "folder present", not "hash cataloged", and costs one stat per
  candidate on the share.
- What the OPERATOR loses outside this product when he deletes sources, stated
  so nobody is surprised: `claude --resume` / `--continue` for those sessions,
  Claude Code's own file-history restore, dangling `history.jsonl` rows.

## Edge cases the build must cover

- A source whose payload uuid differs from its filename: verdict keyed on payload.
- A source with no `sessionId`: reported `NO-UUID`, never IDENTICAL.
- A session with two source files (a `.orphaned-` copy beside the live one).
- An archive folder holding a longer JSONL than the source (ARCHIVE-SUPERSET is
  safe to delete; SOURCE-NEWER is not).
- Companions present in the source but the folder's manifest lists none (UNHELD).
- `absorbed` must never create, rename or write anything under `archive_root`
  except the `--manifest` file, proven by `tree_snapshot` before and after.
