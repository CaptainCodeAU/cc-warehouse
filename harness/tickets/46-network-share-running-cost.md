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

- 2026-09-29 00:22 catch-up `ccw sweep` against the share: (pending)
