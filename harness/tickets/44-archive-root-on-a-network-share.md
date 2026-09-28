# Ticket 44: `archive_root` on a network share (`/Volumes/mac`)

Status: OPEN, scoped 2026-09-28. Phases 1 and 2 (this ticket, the three code
fixes) authorised by the principal the same day. Phases 3 to 7 each wait for his
word at the moment of running. Opened 2026-09-28.

## Why

The laptop has 11 GB free and `~/cc-warehouse-archive` is 18 GB. The principal
wants the archive to live on the SMB share mounted at `/Volumes/mac` (server on the home LAN,
a container on the Proxmox host, share path `/srv/fileshare/mac`
inside the container, owner the share user; exact host, container id and user names live in the Network_Plan repo, not here). `~/cc-warehouse-data` (catalog, locks,
logs) STAYS on the laptop. Rulings taken 2026-09-28:

- move the archive, not the catalog;
- the SanDisk stick is not to be touched;
- server-side backup is parked (Network_Plan ruled it out of scope 2026-09-17);
- the copy runs server-side (tar over SSH), not file-by-file over SMB;
- the daily sweep's slower run on the share is accepted and measured, not
  pre-optimised; an incremental-sweep ticket opens only if the measured cost
  hurts;
- the old local tree stays in place, frozen, until the principal deletes it
  himself. Until then it is the second copy.

## What was measured before scoping (2026-09-28, four audit helpers, every
load-bearing claim re-checked by the conductor)

Share behaviour, probed live with local APFS controls:

| Property | Share | Consequence |
|---|---|---|
| Case | insensitive, preserving, same as APFS | none: 0 case-only collisions in 229k names |
| Unicode | stored NFD, NFC lookup works | none: every archive name is ASCII |
| Name length | 255 bytes max | none: longest name 196 bytes, longest path 360 |
| Hard links | `os.link` fails errno 45, 200 of 200 | `store.acquire_lock` (`store.py:300`) cannot work there, which is why `root` stays local |
| `os.replace` | same as local; EXDEV across the mount | fine: every writer makes its tmp file in the target dir |
| SQLite | locks correctly, WAL refused silently, 0.26 s per commit | catalog stays local |
| Small-file create | about 70 to 114 ms | one real-shape session folder 4.06 s vs 0.012 s local |
| Throughput | about 10 MB/s uncached | 18 GB copy over SMB about 7 h; per-file cost dominates |
| mtime | 100 ns kept, server clock +25 to +32 ms | fine |
| Unmounted | path missing; `/Volumes` is root-owned 755 | a user process cannot recreate the mount point |

Code behaviour on a missing or slow archive root (verified in source):

- Clean unmount: `capture._archive_source` re-raises because `keep_objects` is
  false (`capture.py:305-308`), no catalog row is written, the failure is spoken
  and logged, the next sweep recovers the transcript. Loud and safe.
- Leftover EMPTY mount directory (not observed, not ruled out): `archive.write_source`
  does `mkdir(parents=True)` (`archive.py:821`), the hook succeeds onto the boot
  disk, the catalog records it, and once the share re-mounts at `/Volumes/mac-1`
  the archive is silently forked. There is NO mount-point check, sentinel or
  "root must already hold the tree" guard anywhere in `src/`.
- `ccw doctor` walks the whole archive twice per run (`doctor.py:617` in
  `_dispatch_gap`, `:735` in `_overdue`) and `_recent_archive_folders`
  (`doctor.py:404`) walks it a third time through `archive.walk_folders`. About
  292k filesystem calls, 8.4 s local today, an estimated 15 to 40 min on the share
  against the SessionStart freshness hook's 55 s budget. Every session start would
  block and report `unreachable`.
- `doctor._desync`'s 120 s pending grace is measured from the session START in
  the folder name (`doctor.py:700-703`), not from capture time.
- The daily sweep's post-capture `build.build()` re-lists and re-hashes every
  companion file of every head. Local 34 to 41 min; estimated 2 to 2.5 h on the
  share. The 12:45 repair job already runs INSIDE the sweep's window today (sweep
  ends 13:00 to 13:11, measured from `capture.jsonl`), so its "15 minutes after"
  premise is false regardless of the share.
- Hook: the only synchronous share write is the JSONL. Median capture 69 ms local;
  about 0.5 s typical on the share. Only a payload above about 90 MB would hit the
  40 s wrapper kill; exactly one archived session (114 MB) does, and that case is
  re-swept, not lost.

## The three fixes (phase 2)

### 44a. Archive root marker

A marker file at the top of the archive tree, proposed name `_archive-root.json`
(underscore prefix, beside `_not-sessions/`, so `build.RESERVED_LABELS` and every
label walker already skip it: VERIFY that they do, and add the name to the reserved
set if not). Contents: `{"cc_warehouse": "archive_root", "archive_timezone":
"<zone>", "created": "<iso>"}`.

Rules:
- Every WRITER that targets `archive_root` refuses when the marker is absent:
  `capture._archive_source`, `sweep` (top of the run, before any write),
  `build`'s mirror, `ccw archive --to`, `ccw import`, `ccw repair`. One shared
  check in `archive.py` (for example `require_root(archive_root, zone) ->
  Path`), raising one named exception, called at the verb or hook ENTRY, not at
  every `mkdir` site. A refusal is named and exits non-zero (R10, R14).
- The marker's `archive_timezone` must equal the configured one, or the writer
  refuses. Changing the zone renames the whole tree (config.toml already says
  so); this makes the mismatch a refusal instead of a fork.
- `ccw archive --to X --init` writes the marker into X, whether X is empty or an
  existing tree without one. It refuses when X already holds a marker with a
  different zone. Without `--init`, an X with session folders but no marker is
  refused (this is the stale-directory guard).
- `ccw doctor` gains a BLOCKING line `archive root: marker present ... / MISSING
  at <path>`. It must not raise when the path does not exist.
- Read-only verbs (`status`, `render`, `share`, `verify`, `reindex --dry-run`)
  are unchanged.
- `_archive_source` still only re-raises when `keep_objects` is false; with the
  vault on, the vault write remains the safety net and the refusal is logged.

Oracle tests first, each with a negative arm that fails on master's code: writer
refuses on a missing marker; writer refuses on a zone mismatch; `--init` creates
the marker; `--init` refuses a different-zone marker; a non-empty root without a
marker is refused without `--init`; doctor's line goes FAIL and does not raise on
a nonexistent root; `walk_folders` and `read_projects` never treat the marker as
a label.

### 44b. Doctor stops walking the archive

`_dispatch_gap` and `_overdue` take the archived uuid set from the CATALOG
(`session` rows with a `session_uuid`), and `_overdue`'s `newest_archived` anchor
from the catalog's payload timestamps, keeping R12 (payload time, never mtime).
`_recent_archive_folders` picks the newest `_DESYNC_SAMPLE` folders from the
catalog too and stats only those, so the recency scan touches 25 folders instead
of 31k. The 25-folder verify that already exists is the honesty control on the
catalog: a catalog row whose folder is missing is a FAIL, as today.

Bound it by construction: a test counts archive filesystem calls (monkeypatch
`Path.iterdir`/`os.scandir` under the archive root) and asserts the count is
independent of how many label directories and session folders exist (build a
fixture with 3 labels and with 30, same count). `status.archived_session_uuids`
and `sweep._archived_session_folders` are OUT of scope: the sweep is a batch job
that may pay one walk.

### 44c. Slow-path tolerance

- `_desync`'s grace is measured from the folder's `captured_at` in the catalog,
  falling back to the folder-name moment when the row is missing.
- `docs/operations.md`: record the hook's synchronous write and the 40 s wrapper
  budget; correct the stale line that says `ccw-watch` runs doctor (it stopped on
  2026-09-07); document that the repair job runs inside the sweep window today.
- OUTSIDE the repo, the principal's go-ahead at the moment of running: move
  `com.captaincodeau.ccw-repair` past the sweep's real end (proposed 15:30).

Nothing in 44c changes the hook's timeout or the sweep's algorithm.

## Phases 3 to 7 (each waits for the principal's word)

3. Frozen reinstall: `uv_tool_reinstall_current_project --no-extras`, then
   `env -u VIRTUAL_ENV PATH="$HOME/.local/bin:/usr/bin:/bin" ~/.local/bin/ccw doctor`
   from outside the repo reports the new version and `frozen`.
4. Mark the local tree: `ccw archive --to ~/cc-warehouse-archive --init`.
   Copy server-side, excluding `.DS_Store`:
   `tar -C ~ -cf - --exclude .DS_Store cc-warehouse-archive | ssh <proxmox-host> 'pct exec <ct-id> -- tar -xf - -C /srv/fileshare/mac'`
   then `ssh <proxmox-host> 'pct exec <ct-id> -- chown -R <share-user>:<share-user> /srv/fileshare/mac/cc-warehouse-archive'`.
   The chown is REQUIRED: files unpacked as root inside the container are not
   writable by the share user, which is who `ccw` is over SMB, and the next
   `renderer_version` bump rewrites every manifest.
5. Verify: a sha256 manifest of both trees compared file by file (the ticket 26.4
   method), then `ccw archive --to /Volumes/mac/cc-warehouse-archive --verify`.
   Both must report 0 differences and 0 problems.
6. Switch: `archive_root` in `~/.config/cc-warehouse/config.toml`; the `--to`
   path in `com.captaincodeau.ccw-archive.plist`; the hard-coded path in
   `tools/ccstats/common.py`; `tools/recover_hidden_sessions.py`'s default.
   Then one `ccw sweep` (catches sessions that ended during the copy), `ccw
   doctor` from outside the repo, and a real session end as the positive case
   landing on the share. Watch the freshness hook and `ccw-watch` for a day.
7. The old local tree stays frozen until the principal deletes it by hand.
   Nothing in this ticket deletes anything.

## Out of scope, recorded not dropped

- Incremental sweep (only if the measured daily cost hurts).
- Server-side backup of the share (parked, Network_Plan).
- SanDisk refresh (not to be touched).
- A `.sparsebundle` on the share instead of a bare tree (offered, not chosen).
- The 114 MB single session exceeding the hook budget (re-swept, accepted).

## Edge cases the build must cover

- Marker present but unreadable or malformed JSON: refuse, name the file.
- Marker present, zone key missing (an older marker): treat as mismatch, refuse.
- `archive_root` configured but path absent entirely: doctor FAIL line, writers
  refuse, no directory is created anywhere.
- Catalog has a row whose folder is missing on the share (after a partial copy):
  doctor's 25-folder verify must FAIL on it, not skip it.
- Catalog empty (fresh install) with a marked, empty archive: doctor and sweep run
  clean, no exception.
- A label directory whose name starts with `_` that is NOT the marker must still be
  skipped exactly as before.

## Rulings taken during the build, 2026-09-28 (44b widened by measurement)

The audit's "two walks" undercounted. Measured on the real archive with a
call-attributing instrument (`count_doctor_walks.py`, session scratchpad): one
`ccw doctor` run makes 292,286 archive filesystem calls in 33.7 s local:
`_dispatch_gap` and `_overdue` 64k stats, the desync recency sample 32k via
`walk_folders`, `status.uncaptured_gap` 67k (sessions AND their `subagents/`
dirs), and `status.sidecar_gap` plus `status.paste_gap` 62k file OPENS (one
`sidecars.json` or `manifest.json` per folder) on top of 64k stats. So 44b has
to cover all six walkers, and two of them sit on earlier rulings:

- **Sub-agents are not in the catalog.** Principal ruled: doctor's `Uncaptured:`
  line reports the SESSION figure from the catalog (the literal `Uncaptured: N
  session` is what `ccw-freshness-check.py` parses and stays) and points to
  `ccw status` for sub-agents, which keeps walking. A new slice **44d** (not
  started) adds a sub-agent table to the catalog, written at capture and sweep
  and rebuilt by `ccw reindex`, so the exact figure returns to doctor.
- **The two corpus-wide coverage lines (`sidecars`, `prompts`, ticket 38 ruling
  (e)) keep their corpus-wide meaning by moving the WORK to the daily sweep.**
  The sweep already walks every folder; it writes the two figures to
  `<root>/logs/coverage.json` (tmp + `os.replace`) and doctor prints them with
  the sweep's timestamp ("as of <when>"). No file under the archive is opened
  by doctor for these lines. `ccw status` computes them live as before.
- Also corrected: `CLAUDE.md` says `ccw-watch` parses doctor's text; it stopped
  on 2026-09-07 (its own header says so). The freshness hook is the only
  consumer, and it reads the exit code plus the `Uncaptured: N session` figure.
