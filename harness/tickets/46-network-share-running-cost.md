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
- 2026-09-29 12:30 scheduled sweep: SKIPPED on the principal's word (job booted out
  12:12, re-bootstrapped 12:40, did not run; `launchctl print` state "not running",
  runs 0). No measurement.
- 2026-09-29 ~13:50, the likely main cause, VERIFIED read-only: all three launchd jobs
  (ccw-sweep, ccw-archive, ccw-repair) carried `LowPriorityIO=true` and
  `ProcessType=Background`. Reading `manifest.json` files on the share took 38 to 55 ms
  each at normal priority and 1,176 to 1,250 ms under `taskpolicy -d throttle` (two
  runs each, different files, so not a cache effect), about 25x slower. A reviewer
  measured that 16 to 32 parallel readers help only 1.2 to 1.6x at low priority against
  about 4x at normal (agent-reported). The principal ruled "turn it off" (~14:05): both
  keys removed from all three plists (backups `*.bak-20260929-pre-priority` beside
  them), each reloaded without running. Tomorrow's 12:30 sweep is the first at normal
  priority; record its wall time here. Trade-off accepted: while a job runs it competes
  with interactive use for disk and network.

- 2026-09-29 13:06 to 14:27, option A step 1 (thread pool, W-20260929-A91), branch
  `fix-parallel-reads`. READ-ONLY harness calling the parallelised read functions on
  the real share (catalog opened `?mode=ro`; no `ccw` verb run). Each configuration
  drew its own random, disjoint sample of heads, so every run started cold. Wi-Fi was
  noisy: the same configuration varied up to 2x between rounds, so ranges are given.
  Per item, milliseconds:

  | Check | Priority | Serial | 8 workers | 16 workers | 32 workers |
  |---|---|---|---|---|---|
  | build `_head_is_current` (150 heads per run, two rounds) | normal | 245, 592 | 89, 130 | 46, 86 | 87, 98 |
  | same (24 then 64 heads) | `taskpolicy -d throttle` | 5,212 | | 972, 1,275 | 646, 1,031 |
  | coverage (notice + manifest, 200 folders) | normal | 74 | 17 | 13.5 | 8.9 |
  | same (40 then 120 folders) | throttled | 594 | | 257, 297 | 252, 248 |
  | full `verify_folder` (60 folders) | normal | 339 | | 169 | 201 |
  | same (16 folders) | throttled | 1,635 | | 360 | |
  | sweep sub-agent read-back, warm then re-read (150) | normal | 3,914 | | 4,265 | 2,897 |
  | sweep sidecar read-back, warm then re-read (100 of 1,681 candidates) | normal | 4,164 | | 4,724 | 4,082 |

  - The sweep read-ahead does NOT pay. Split on 20 sub-agents: finding the parent
    folder (`archive._parent_folder`, a full listing of the label dir plus a stat per
    entry) took a median 2.0 s, max 16.2 s, cold; everything else, file reads included,
    0.14 s. Filed as W-20260929-A115.
  - SMB client cache, measured: a file read seconds ago re-reads in about 0 ms; after
    20 s the median is 3.8 ms, after 60 s 20 ms (cold 15 to 50 ms). Listings behave
    the same. Under throttle a 64-head warm repeat took 61 to 71 s against 66 to 82 s
    cold: at that speed the chunk outlives the cache.
  - Memory, full verify of the 8 largest heads (13 to 114 MB): serial peak 1.70 GB, 16
    workers uncapped 2.45 GB, 16 workers with the 256 MiB byte cap 1.98 GB.
  - Estimate, ASSUMED from the ratios above applied to the measured 4h30m run (a hand
    run at normal priority): build ~2h20m to about 15 to 45 min; coverage ~20 min to
    about 4 to 7 min; item loop unchanged at ~1h30m (the lookup cost above). Whole
    sweep about 2 to 2.5 h at normal priority. Under the scheduled jobs' IO throttle
    the serial build check alone extrapolates to about 44 h for 30k heads and the
    pooled one to 8 to 11 h: the throttle, not the thread count, decides the
    scheduled job's time.
  - Outcome, 2026-09-29: the sweep read-ahead warmers were dropped from the branch
    before merge (conductor ruling, option A); the pool stays for the build check,
    coverage, the desync scan and `ccw archive --verify`. The sweep's per-item cost is
    W-20260929-A115's to fix.
  - MEASURED 2026-09-30, the first scheduled sweep after the IO throttle was removed
    (LowPriorityIO and ProcessType dropped from the plists 2026-09-29): launchd started
    it 12:30:06 AEST (`launchctl print`, pid 60309) and its run summary landed 15:15:24
    AEST, so 2 h 45 min wall time, against the 2 to 2.5 h estimate above. Summary:
    `sweep: 30244 items, 51 stored, 113 with sidecars, 8 failed`, exit 1; the 8 failures
    are W-20260930-A59 (stream-json files in a project's memory/ folder cataloged with no
    session uuid), not a cost finding. The sweep moved to 02:00 the same day (operator,
    no scheduled wake), so later runs start at the first wake after 02:00.
