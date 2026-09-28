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

## 44b and 44c DONE 2026-09-28 (conductor, on master)

**What shipped.** `ccw doctor` no longer walks the archive. A new read-only
`doctor._catalog_index` answers the three questions the walks used to answer:
the archived uuid set (`_dispatch_gap`, `_overdue`), the newest payload start
(`_overdue`'s R12 anchor) and the `_DESYNC_SAMPLE` most recently STARTED heads
with their computed folder paths (`_desync_scan`, through `build.archive_dir`,
the one naming function). `status.uncaptured_gap` takes the session figure from
a new `status.cataloged_session_uuids` in both `status` and `doctor`; the
sub-agent figure is computed only for `status` (`subagents=True`) and doctor's
line now reads `Uncaptured: N session(s) in <src> with no catalog row
(sub-agents: ccw status)`. The two corpus-wide coverage lines are measured by
`ccw sweep` after its post-sweep build (`status.write_coverage`, tmp + replace
into `<root>/logs/coverage.json`) and doctor prints them from
`status.read_coverage` with `(as of <iso>)`; before the first sweep after
upgrading it prints `not measured yet: the next ccw sweep writes
logs/coverage.json` and stays ok. `_desync`'s pending grace is measured from the
catalog's `captured_at`, falling back to the folder-name moment (44c).
`build._HEAD_RANK_CTE` gained `s.captured_at` (additive; both consumers select
by name). `docs/operations.md` and `CLAUDE.md` corrected (ccw-watch stopped
calling doctor 2026-09-07; the repair job runs inside the sweep window; the hook
budget recorded). `pyproject.toml`'s sdist exclude gained `.worktree` after the
packaging test shipped a worker's whole checkout (217 members).

**Measured, real data, read-only.** `ccw doctor` archive filesystem calls
292,286 -> 1,080 (all inside the 25 sampled folders); wall 33.7 s -> 6.4 s, the
remainder being the local source-tree walk. Catalog uuid set == archive walk set:
31,112 = 31,112, 0 either way. Old frozen `ccw status` and new code agree on
`Uncaptured: 37 session(s), 25 sub-agent(s)`.

**Tests.** New `tests/test_doctor_catalog_index.py`, 14 arms; 10 failed on
master's code, 4 are semantic controls that pass on both. Three existing tests
re-anchored from "old session" to "old CAPTURE" by aging `captured_at` in the
scratch catalog (`test_doctor.py` x2, `test_repair.py` x1); six
`test_sidecar_signal.py` tests now sweep after planting an anomaly, because the
figure is the sweep's; the whole-line `Uncaptured` pin updated to the new tail.
`tests/test_doctor_external_contract.py` (the real sed) untouched and green.
Suite before 1,633 pass + 10 fail (the 10 above), after: see the merge commit.
pyright strict 0 errors, ruff check clean.

**Chosen on my own, recorded:** `write_coverage` lives in `cli._run_sweep`
after `build.build`, not inside `sweep.sweep()`, because the manifests it
counts are rendered by that build (a first cut inside `sweep()` measured 0/0
on a fresh sweep). A coverage-write failure is one `ItemOutcome` error and a
stderr line, never a failed sweep. `sweep.sweep()` called in-process writes
no coverage file; only the CLI verb does.

**Not done here:** the repair plist reschedule (outside the repo, the
operator's go-ahead); 44d (sub-agent index); the reinstall and every later phase.
||||||| 9475d88


## 44a DONE 2026-09-28 (branch `t44a-marker`, not merged)

**What shipped.** `archive.ROOT_MARKER` (`_archive-root.json`, holding
`cc_warehouse`, `archive_timezone`, `created`), one read-only diagnosis
`archive.root_problem(root, zone) -> str | None` that never raises and never
creates anything, `archive.require_root` raising the one named exception
`archive.ArchiveRootRefused`, `archive.init_root`, and `archive.root_refusal`
(the batch-report form sweep, build and import return). Entry checks, each
before the first write: `capture._archive_source`, `capture.archive_companions`
(the detached companions child's whole body), `sweep.sweep`, `build.build`,
`ccw render --session` (the hook's detached render child), `ccw archive --to`,
`import_tree.import_tree`, `ccw repair`. `ccw archive --to X --init` writes the
marker. `ccw doctor` gains a BLOCKING `archive root` line (new
`doctor._archive_root_check`, one appended `Check`; `_dispatch_gap`, `_overdue`,
`_recent_archive_folders` and `_desync` untouched). The marker name joined
`build.RESERVED_LABELS`, and `archive.read_projects` now skips reserved names
the way `walk_folders` already did (it only skipped non-directories before).
`docs/agent-setup-contract.md` and `docs/reference-config.toml` say to run
`--init` once.

**Tests.** Before: 1629 passed. After: 1675 passed, 1 xfailed. New file
`tests/test_archive_root_marker.py`, 47 arms: 40 failed on master's code
(committed red first, `43bf074`), 6 pass on both (positive controls: hook,
sweep and `ccw archive` writing into a MARKED root; regression pins:
`--verify` on an unmarked tree, a marker file beside labels, `_`-prefixed labels
that are not the marker), 1 strict xfail (below). The 40 failed on: missing
`archive.require_root`/`ROOT_MARKER`/`ArchiveRootRefused` (unit arms); `--init`
being an unknown flag; every writer writing into or creating the unmarked
root (hook, sweep, build, render, import, capture with and without the vault,
the companions child); repair exiting 0; doctor having no `archive root` line;
and `read_projects` yielding a DIRECTORY named `_archive-root.json` as a label.

**The six ticket edge cases,** each a test: malformed marker (bad JSON, not an
object, wrong kind, empty file) refuses and names the file; a marker with no
zone refuses; an absent path makes doctor FAIL without raising, every writer
refuse, and nothing created (hook arm and `require_root` arm); catalog empty
with a marked empty archive runs doctor and sweep clean; `_not-sessions`
still skipped and `_unlabeled` still walked. The fifth, a catalog row whose
folder is missing, is `xfail(strict=True)` because it needs 44b's catalog-driven
recency sample; strict means it turns red the moment 44b makes it pass, so the
mark cannot outlive the fix. Brief extras also covered: `created` is never
compared; `--init` on a same-zone marker exits 0 and rewrites nothing (bytes,
inode and mtime_ns unchanged); `_archive_source` with the vault on stores the
session and logs one `error` line naming the marker, with it off re-raises.

**Existing tests touched (251 went red, all fixed).** Every per-file config
helper that sets `archive_root` now calls the new `conftest.mark_archive`,
which uses the product's own `init_root`; tests that build with `ccw archive
--to` run `--init` first. Four dry-run tests asserted `not archive_root.exists()`;
the root now exists up front, so they assert the tree snapshot is unchanged
instead (same property). Six tests made the archive unwritable by nesting it
under a FILE, which is now a marker refusal before any write; they use a marked
root with mode 0o555 instead, so they still exercise a write failure after the
check. That arm assumes tests do not run as root.

**Chosen on my own.**
- `--init` marks and STOPS; it never builds. The same-zone no-op requirement
  ruled out a build in the same run, and marking an 18 GB tree should never
  turn into a rebuild by accident.
- `--init` creates X but never X's parents (a missing parent is what an
  unmounted share looks like). It refuses any existing marker it cannot prove
  (other zone, no zone, malformed) rather than replacing it, and `--init
  --verify` together is a usage error (exit 2).
- `ccw archive --to X` without a marker is refused even when X is empty or
  absent, not only when it holds session folders: the ticket's first rule
  ("every writer refuses when the marker is absent") is the stricter reading.
- `build.build` refuses the whole build, projections included, rather than
  failing each head; `ccw render --session` refuses before writing the
  projection too.
- The refusal log line on the vault-on capture path is its own function
  (`capture._log_root_refusal`), because `_log_stage_failure`'s wording says the
  archive write already succeeded.
- `archive_companions` returns silently on an unproven root; the parent's
  refusal was already logged or raised for the same session.
- The doctor check is named `archive root` as the ticket words it; at 12
  characters it pushes its detail one column right of the others. No existing
  line changed.

**Left undone.**
- `ccw sweep --dry-run` (`sweep.plan`) still predicts a normal run against an
  unmarked root; the real run then refuses. Read-only verbs were ruled
  unchanged, so it was left alone.
- `ruff format --check` fails repo-wide on master (117 files) and still does;
  this branch adds no new formatting diffs (per-file diff sizes compared
  against master, the only change being fewer in `build.py`).
- DEPLOY ORDER MATTERS: the moment the frozen reinstall (phase 3) lands, the
  live archive has no marker, so every writer refuses it, the hook re-raises
  (the live config has `keep_objects = false`) and doctor goes FAIL. Phase 4's
  `ccw archive --to ~/cc-warehouse-archive --init` must run immediately after
  phase 3, before the next session ends.
