# Ticket 46: cut the daily and weekly cost of an archive on a network share

Status: OPEN, scoped 2026-09-29 at the operator's request ("find any intelligent
or smart way to reduce the amount of time it will take every time or every
week"). Not started; the first measurement it needs (the catch-up sweep against
the share, started 2026-09-29 00:22) is appended below when it lands. Opened
2026-09-29.

## The cost, measured or bounded (ticket 44)

| Job | Local disk | On the share | Why |
|---|---|---|---|
| SessionEnd hook | median 69 ms | about 0.5 s | one JSONL write; fine |
| `ccw doctor` (every session start) | 8 s | 22 s measured after the switch | 25 folders verified over SMB; fine |
| `ccw archive --verify` | about 7 min | **3 h 10 min measured** (31,157 folders, 0.37 s each) | reads every manifest and JSONL through SMB |
| weekly `ccw archive --to` (Sunday 03:00) | about 7 min | estimated 1 to 3 h | same per-folder listing and manifest read |
| daily `ccw sweep` | 34 to 41 min (11 min on 2026-09-28) | estimated 2 to 2.5 h; measurement pending | the local half is unchanged; the post-sweep `build.build()` re-checks every head's folder on the share (`_head_is_current` -> `folder_is_current` -> `companion_records`, one listing and hash per companion file) |

The shape of the problem: the SOURCE side of every job is local and fast; the
ARCHIVE side is now slow per file, not per byte. Anything that decides "does this
folder need work" by touching the share pays 0.3 to 0.4 s per folder, 31k times.

## Options

| Option | What changes | Saves | Risk / cost |
|---|---|---|---|
| A. Decide from local evidence, touch the share only to write | the daily build treats a head as current when the CATALOG records that its folder was written for this (hash, renderer_version, companions digest); the companions digest is computed from the LOCAL source listing; the share is touched only for heads whose local evidence changed, plus doctor's 25-folder sample | the daily build drops from hours to minutes; the 25-folder sample and the weekly verify remain the honesty control | new catalog column(s); ticket 30 already wanted this ("incremental archive rebuild"); a folder damaged on the share is found weekly, not daily |
| B. Run the read-heavy pass WHERE THE DISK IS LOCAL | install `ccw` in the container (or on the host) and run `ccw archive --to <dataset path> --verify` there weekly over SSH, reading at NVMe speed; the Mac keeps writing over SMB | the weekly 3 h pass becomes minutes | needs the ccw package on the server (PyPI install, stdlib-only runtime makes that trivial), the same `archive_timezone` and marker, an SSH launchd job on the Mac or a cron on the host, and the report brought back to `~/.claude/logs` |
| C. Sampled or windowed verify | weekly verify checks only folders captured since the last full pass plus a random 5% | 20x fewer reads | a silent old corruption is found late; against the product's "the archive is the deliverable" stance |
| D. Cache the listing | keep a per-folder inventory (names, sizes, sha256) in the catalog and let `folder_is_current` trust it | like A but for the weekly job too | the catalog stops being disposable for that data |
| E. Change the mount | tune the SMB client (`nsmb.conf` dir cache, larger read size) or move to NFS from the container | maybe 2x | unmeasured; does not change the per-file shape |

## Recommendation

A plus B, in that order. A is the change that makes the DAILY job cheap and it is
the ticket 30 design this project already agreed it wanted; the daily job is the
one that runs while the operator works. B moves the WEEKLY full read next to the
disk instead of across the wire, which no client-side trick can match, and it
also gives the share its own independent integrity check (the copy-time proof
in ticket 44 phase 5 was done exactly this way, in 17 s for 227,812 files). C and
D are declined: both trade away the "every byte, every week" property. E is worth
one measurement day, not a design.

Before any of it: the catch-up sweep's measured duration, below, and one week of
the scheduled jobs' real numbers from `capture.jsonl` run summaries, so the
saving is measured against a real baseline rather than an estimate.

## Measurements appended as they land

- 2026-09-29 00:22 catch-up `ccw sweep` against the share: **4h29m55s** (00:22:41
  to 04:52:36, process exit seen by a `kill -0` watch). Run summary in
  `capture.jsonl`: `sweep: 29957 items, 7 stored, 13 with sidecars, 1 failed`
  (the one failure was a build item, `5f32eac9e690`, "no bytes ... in the vault
  (objects/ missing)"; not a share cost, filed separately). Against the 2 to
  2.5 h estimate above: about double. Phase timeline, all local time (AEST), each
  from the named instrument:
  - 00:22:41 start (`ps -o lstart` on pid 67450, hand-run, no `--quiet`).
  - 00:23 first payloads replaced in archive folders (JSONL mtimes on the share).
  - 01:53:35 `prompts.jsonl` split into folders (mtimes), 01:56 `pastes/` (mtime).
    `_process_history` runs after the per-item loop (`sweep.py`, code order), so
    the item loop plus per-item copies took about 1h31m; that split is inferred
    from code order, not timed directly.
  - 01:56 `locks/build` taken (lock file mtime): the post-sweep `build.build()`
    started. The lock was still present at 04:05 and gone at 04:33 (`ls
    locks/`); the last of three tracked folders re-rendered at 04:09 (manifest
    mtime). Build half: roughly 2h10m to 2h35m.
  - 04:33 to 04:52 `status.write_coverage` (code order; `coverage.json` mtime
    04:52): about 20 min for the corpus-wide coverage figures on the share.
  - Totals, approximate: item loop ~1h31m, build ~2h20m, coverage ~20m. CPU time
    at exit was about 16 min of the 4h30m (`ps -o time`, state `UN` throughout):
    the run is bound by waiting on the share, not by computation.
  - Side effect, fixed: while the build lock was held, `ccw doctor` FAILed its
    desync check on 5 folders the sweep had written but not yet re-rendered, and
    the SessionStart check reported capture broken 5 times in a row. Fixed in
    `a60d50d` (pending, not FAIL, under a live lock when the file is newer than
    its manifest); live once the frozen install is refreshed.
