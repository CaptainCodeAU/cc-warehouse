# Daily sweep's full-corpus cost — proposal

**ACCEPTED 2026-08-20 as ticket 31 (`harness/tickets/31-sweep-full-corpus-
cost.md`), NOT STARTED.** The operator read this document and chose to open
it as a numbered ticket before any code changes, rather than jump straight to
a fix. See the ticket for the work-order breakdown; this document is kept
VERBATIM below as filed, per this project's convention of not rewriting a
finding after the fact.

---

**Original status, as filed:** proposal, not a ticket. Written 2026-08-20 by an
assistant session that started from one broken session folder
(`CaptainCodeAU-win_go_app_test/20260820-093714+1000_b087d6a2-...`, handed over
by the operator in `temp/`) and traced the investigation outward into why its
archive folder was internally inconsistent (JSONL newer than the four rendered
pages beside it). That trace led to the daily `ccw sweep` job itself. Not
scoped or reviewed by this project's own process. Whoever picks this up should
verify every claim below against the current code before trusting it — line
numbers and behavior may have drifted, and every number below is one machine's
measurement, not a general claim.

The point of this document is to hand over evidence, not a decision. Make the
judgment call yourself: whether this becomes one ticket or several, and how to
close the open questions below.

## The problem, with real numbers

A daily `launchd` job (`com.captaincodeau.ccw-sweep`, `StartCalendarInterval
{Hour: 12, Minute: 30}`, every day) runs `ccw sweep --quiet`. Measured against
this machine's real catalog (`~/cc-warehouse-data/catalog.sqlite`,
2026-08-20):

```
capture_event rows in today's sweep window (02:16:07-02:50:39 UTC):  17,079
  skipped_unchanged:      16,382  (96.0%)
  stored:                    541
  duplicate-invocation:      156
total sessions ever cataloged:                                       21,728
```

And it is growing, unbounded, every day — this is not a one-time spike:

```
2026-08-11:  15,584 capture_events
2026-08-15:  15,825
2026-08-18:  16,181
2026-08-20:  17,079   <- today
```

Root cause, in code — **two separate, stackable costs, both O(every session
ever), triggered by the same daily job:**

**Cost 1 — `sweep()`'s own walk never gates the expensive part on a cheap
check.** `sweep.py` `_walk_source()` (~line 46) walks the *entire*
`~/.claude/projects` tree every run — every `.jsonl` file that has ever
existed there, not just ones that changed since yesterday. `sweep()` (~line
307) hands every one of them to `capture._capture_item()` → `capture.
capture_transcript()` (`capture.py` ~line 312), which unconditionally does
`data = transcript_path.read_bytes()` (full file read) then `store.
sha256_hex(data)` (full hash) *before* it can even check whether this exact
content was already captured. For the 96% that are `skipped_unchanged`, this
is a full read + full hash + one `BEGIN IMMEDIATE`/`COMMIT` write transaction
(`catalog.record_event`, `_capture_locked` ~line 158) for a file that is
byte-identical to what's already known. No mtime/size/anything-cheap check
happens before that expensive path.

**Cost 2 — `ccw sweep` also unconditionally calls `ccw build`, whose own
cost is separately O(everything).** `cli.py` `_run_sweep()`, ~line 647:

```python
if stored:
    build_report = build.build(config)
```

`build.build()` (`build.py` ~line 473) is the exact defect this project's own
backlog already named: **`harness/tickets/28-backlog.md` item 28.20, "`ccw
build` is O(everything) even when nothing changed,"** measured 2026-08-04 on a
smaller corpus (14,246 sessions) at **5:55-6:04, unchanged whether anything
had actually changed.** Quoting that entry directly: *"every head is still
read from the store and fully re-rendered in order to compare."* 28.20 is
explicitly marked **STILL OPEN** and explicitly says the fix pattern already
exists elsewhere: **ticket 30 (`harness/tickets/30-incremental-archive-
rebuild.md`, DONE 2026-08-18)** built `archive.folder_is_current()` — a cheap
manifest-comparison check done *before* the store is even read — for the
*analogous* cost inside `ccw archive`'s weekly job. Ticket 30 never touched
`build.build()`, so this second cost is exactly where 28.20 left it.

**On this machine, right now, cost 2 produces zero benefit — it is pure
waste.** `~/.config/cc-warehouse/config.toml` sets `keep_projections =
false` (turned off 2026-08-03, when the archive-first folder tree replaced
the old `projections/` tree as the deliverable). `build.build()`'s write step
is correctly gated on `keep_projections` (`build.py` ~line 510, ~line 524) —
but the *read-every-payload-from-the-store, parse, fully re-render, and
compare* work above that gate is not. So every day sweep stores at least one
new session (541 today; this is not a rare case), the daily job pays the full
~6-9 minutes of `build.build`'s CPU (larger now than 28.20's 2026-08-04
measurement — corpus grew from 14,246 to 21,728 sessions since then) and
writes nothing, anywhere, ever, on this deployment.

**This is the third instance of the same shape in this project.** Ticket 30
fixed it for `ccw archive`. Ticket 28.20 named it for `ccw build` and marked
it open. This document is the third: `ccw sweep`'s own walk has never had a
cheap pre-check either, and it is the single most expensive of the three
(34-44 minutes measured wall-clock for the walk alone, before `build.build`
even starts).

## What already exists that makes this cheap to build

- `archive.folder_is_current()` (`archive.py`, ticket 30) is a proven,
  shipped, tested implementation of exactly this shape: read one small file,
  compare a few fields, skip the expensive path if they match. The same
  pattern generalizes to `build.build()` directly — nothing new needs
  inventing, only reuse.
- `catalog.session` already stores `hash` (sha256) per row — the content
  identity this project treats as ground truth (R1), not filesystem
  metadata. A cheap pre-check for `sweep()`'s walk needs *some* fast signal
  cheaper than a full read+hash, and the honest options are (a) a new small
  side-table keyed on source path + mtime + size, checked before the read, or
  (b) accept that R1 means only a hash can be authoritative and instead
  reduce the *cost per skip* (batch the `skipped_unchanged` DB writes, or
  drop per-item event logging for skips) rather than avoiding the read
  entirely. Both are legitimate; they trade off differently. Not decided
  here.

## Proposed checks (sketch — not a final design)

1. **Guard `build.build()`'s call from `_run_sweep()` on `config.
   keep_projections`.** One line, `cli.py` ~line 647-648. Zero risk, zero
   design work, and on this specific deployment eliminates 100% of cost 2
   immediately. Does **not** help an operator who has `keep_projections =
   true`, so it is a mitigation for this machine, not a general fix.
2. **Give `build.build()` the same cheap-check-before-expensive-work shape
   ticket 30 already proved for `archive.folder_is_current()`.** This is the
   real, general fix for cost 2 — needed by anyone who *does* keep
   `projections/` live.
3. **Give `sweep()`'s own walk a cheap pre-check before `capture_transcript`
   ever reads+hashes a file**, closing cost 1. This is the biggest single
   win (34-44 minutes → an `os.walk` plus a handful of real reads for
   whatever's actually new) and the part with no existing shipped pattern to
   copy — see the open question below.

## A second, related but distinct finding: the resilience gap this daily cost exposed

Not the same bug as above, but found by chasing why it mattered on a real
session, and worth handing over together since one investigation surfaced
both.

Session `b087d6a2-...` (project `win_go_app_test`) reached its real end —
its content includes a closing line, "Good session. Talk soon.," confirmed
present in the operator's own Claude Code export and absent from the stale
archive pages — sometime after the daily sweep had already caught an earlier,
shorter snapshot of the same session (12:37:19 local, 843 lines, the routine
safety-net case the sweep job exists for). The session's true end wrote the
full 1250-line content into the archive's raw `.jsonl`
(`archive.write_source()`, safe, confirmed present) at 13:24:14 local — but
**nothing else followed**: no new `session` row, no new `capture_event`, no
rebuilt `transcript.md`/`conversation.html`/manifest, and critically, no
voice notification and no Finder reveal, even though both are turned on for
this operator (`config.toml` `[notify] open_folder = true`; top-level
`voice_url`/`voice_id`) and both are gated on the interactive `ccw hook`
path's detached render child specifically — `sweep()`'s own comment says why
sweep-caught sessions never get either: *"One detached child per item is not
an option at this scale; this sweep would have spawned 2,064 processes."*
`~/.claude/logs/ccw-hook.log` — the interactive hook's own log — recorded
nothing at all after 02:50:39 UTC that day, which is the *exact* moment the
sweep window's last `capture_event` was also logged.

Not proven — no stack trace was recoverable — but the best-supported reading
of the evidence: `capture.py` `_capture_locked()` (~line 136-189) writes the
JSONL first (`_archive_source` → `archive.write_source`, ~line 168) and only
*afterward* opens/writes the catalog row (`catalog.add_session`, ~line 186).
An exception anywhere between those two lines — most plausibly a
`sqlite3.OperationalError` from lock contention against the sweep job's own
~17,000 write transactions running in the same window — produces exactly
this shape: raw text safely saved, everything downstream silently missing,
because nothing in the current code retries or reports a *partial* capture
distinctly from a full one. `catalog.py` already sets `PRAGMA busy_timeout =
5000` (~line 139), so this is a *bounded* wait today, not an infinite hang —
but 5 seconds can still be exceeded under sustained load, and nothing retries
after it is.

`ccw archive --verify` independently confirms this is rare, not systemic:
**1 folder out of 21,669 checked**, read-only, today. That rarity is itself
evidence for a timing-dependent cause (contention during a specific ~45
minute daily window) over a deterministic one.

Proposed, separately from the cost-1/cost-2 fix above:

- Retry-with-backoff around the catalog write path in `_capture_locked` /
  `capture_transcript` for a caught `sqlite3.OperationalError` ("database is
  locked"), rather than letting it propagate and abort the whole capture
  after the JSONL write already succeeded.
- Wire `ccw archive --verify`'s existing "JSONL does not match manifest
  source_hash" check (`archive.py` `verify_folder()`, ~line 925) — or an
  equivalent cheap check — into `ccw doctor`'s regular report, so this class
  of desync surfaces on its own instead of requiring an operator to notice a
  missing sound and go looking, as happened here.

## A few things checked and ruled out — not gaps

- **Duplicate hook registration.** An old `claude-transcript-exporter`
  plugin's cache directory (`~/.claude/plugins/cache/gz-claude-code-plugins/
  claude-transcript-exporter/`) still exists on disk and still contains a
  `hooks.json` registering the identical `SessionEnd → ccw-hook.py` hook as
  the current `cc-capture@cc-warehouse` plugin. Checked `~/.claude/plugins/
  installed_plugins.json` directly: only `cc-capture@cc-warehouse` is
  installed. The old plugin is not double-firing anything. (Worth a
  housekeeping note to the operator regardless — a stale, uninstalled
  plugin's files sitting in the cache is not itself a bug, just confusing to
  find mid-investigation.)
- **`ccw-watch` / `ccw doctor` at SessionStart**, which fires once per Claude
  Code session and this operator runs several concurrently. Confirmed
  read-only: `doctor.py` ~line 279 calls `sweep.source_transcripts()`, which
  is a plain `os.walk()` file listing, not `capture_transcript`. No read+hash
  per file, no DB write. Not a contributor to the contention above.
- **The weekly `ccw archive` job** (ticket 30) is a separate schedule
  (Sunday 03:00 only) and was already fixed 2026-08-18. It is not stacked
  with the daily cost described here on any normal day.

## Open questions — needs real investigation, not a guess

- **What's the cheapest correct pre-check for `sweep()`'s walk (cost 1)?**
  mtime+size is fast but is filesystem metadata, not the content-hash
  identity this project's R1 treats as ground truth elsewhere. Whoever
  implements this should decide, and say why, rather than defaulting to
  mtime+size out of convenience — ticket 30 deliberately chose a stronger
  signal (`source_hash`) for the analogous archive-side check.
- **Is the lock-contention theory in the resilience section actually the
  cause, or a plausible-but-wrong story?** No stack trace was captured live.
  Before writing a retry loop, it may be worth adding a debug log around
  `_capture_locked`'s post-`write_source` steps and simply waiting for the
  next natural occurrence, rather than designing a fix for an unconfirmed
  mechanism.

## Not open — already agreed, carry forward as-is

The general pattern — cheap check before expensive work, computed from data
already on disk, no new cross-run marker file — is already accepted
project-wide via ticket 30. This document is "apply the same accepted
pattern to two more call sites, plus a related resilience gap," not a new
architectural question.

## Deliberately left to you

- Whether guard 1 (the one-line `keep_projections` gate) ships alone,
  immediately, ahead of the general fixes 2 and 3 — it is safe and
  independent of everything else here.
- Whether the resilience section (retry + doctor check) becomes part of the
  same ticket as the two performance fixes, or its own — they address
  different failure shapes (wasted work vs. silent partial failure) even
  though one investigation found both.
- Whether `sweep()`'s pre-check needs new persistent state at all, or
  whether reducing the *cost per skip* (batched/aggregated event logging
  instead of one transaction per file) is an acceptable, simpler first step.

## Evidence trail, for verification

- `sweep.py` — `_walk_source()` ~line 46, `sweep()` ~line 307,
  `_capture_item()` ~line 186
- `capture.py` — `capture_transcript()` ~line 312, `_capture_locked()` ~line
  136, `_archive_source()` ~line 192
- `cli.py` — `_run_sweep()` ~line 591-658 (the `build.build()` call at ~647)
- `build.py` — `build()` ~line 473, `keep_projections` guards ~line 510 and
  ~line 524
- `archive.py` — `folder_is_current()` ~line 443 (ticket 30's proven
  pattern), `write_source()` ~line 377, `verify_folder()` ~line 925
- `catalog.py` — `open_catalog()` ~line 117, `PRAGMA busy_timeout = 5000`
  ~line 139
- `harness/tickets/28-backlog.md` item 28.20 (the `build.build` cost, named
  and left open 2026-08-04)
- `harness/tickets/30-incremental-archive-rebuild.md` (the proven fix
  pattern, DONE 2026-08-18)
- `~/.config/cc-warehouse/config.toml` (`keep_projections = false`,
  `[notify] open_folder = true`, `voice_url`/`voice_id`)
- `~/cc-warehouse-data/catalog.sqlite` — `capture_event`/`session` tables,
  queried read-only
- `~/.claude/logs/ccw-hook.log` — silent since 02:50:39 UTC, 2026-08-20
- `~/Library/LaunchAgents/com.captaincodeau.ccw-sweep.plist` (daily,
  12:30), `com.captaincodeau.ccw-archive.plist` (weekly, Sunday 03:00) — the
  only two scheduled callers found
- `~/.claude/plugins/installed_plugins.json` — confirms only one capture
  plugin is active
- Session compared throughout: `CaptainCodeAU-win_go_app_test/
  20260820-093714+1000_b087d6a2-b996-4e69-ac60-d0994a10eaf1`, plus its live
  source under `~/.claude/projects/<encoded-project-path>/
  b087d6a2-b996-4e69-ac60-d0994a10eaf1.jsonl` (Claude Code encodes the
  project's absolute path into that directory name, so it is not repeated
  here verbatim) and its operator-
  provided export
