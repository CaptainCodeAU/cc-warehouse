# Ticket 37: the sweep rewrites every sub-agent `meta.json` daily, and a hook killed mid-run leaves no trace

Opened 2026-09-06. **Part A DONE and Part B row 1 DONE the same day** (see the bottom of this file). Part B rows 2, 3 and 5 and the pre-filter follow-up are OPEN. **2026-09-09: Part B's underlying mechanism confirmed CHRONIC and size-correlated, still unfixed - see that dated section near the bottom.** Two findings from one session's timeline
(chorustic session `78bb0bd1-06cf-44b6-b5ec-6e7a01b0df92`), traced because
the operator asked why the rendered files landed nine minutes after the
JSONL and why the `subagents/` folders carried a date between the two.
Part A is the defect. Part B is the logging gap that made part A take
seven tool calls to reconstruct instead of one `grep`.

(There is no ticket 36 file; CLAUDE.md cites "ticket 36" for the
`docs/operations.md` correction of 2026-09-01, which was recorded there and
in `harness/HANDOFFS.md` rather than as a ticket file. 37 is the next free
number.)

## The timeline that surfaced both (all times local, +10:00)

| Time | What | Instrument |
|---|---|---|
| 12:28:21 | Session ended. Last transcript line is a `queue-operation` dequeue at 02:28:21.113Z. | source `.jsonl` |
| 12:28:22 | SessionEnd hook wrote the raw JSONL into the archive folder. | archive `.jsonl` mtime (`ls -lT`) |
| 12:28:23 | Hook wrote the sub-agent JSONLs into `subagents/<stamp>_<id>/`. | `ad9b32df62d234670.jsonl` mtime |
| 12:28:2x | Hook died. No `ok`/`error` line in `~/.claude/logs/ccw-hook.log`, no row in `capture_event`, no line in `logs/capture.jsonl`. All three stop at 02:25:54Z (a different session). | the three logs |
| 12:30:00 | `com.captaincodeau.ccw-sweep` fired (`ccw sweep --quiet`). | plist StartCalendarInterval 12:30 |
| 12:30:40 | Sweep hashed this session, found no catalog row, took the fresh path. `_archive_source` and `_archive_subagents_of` were byte-identical no-ops. `stored`, elapsed 4,737 ms (largest item of the batch; the next largest was 56 ms). | `capture_event` id near 279,5xx |
| 12:31:45 | Last `stored` of the batch. Sweep continues hashing the remaining source files. | `capture_event` |
| 12:34:47 to 12:35:01 | Sweep pass two (`sweep.sweep`, the `deferred` loop) called `archive.write_subagent` for every sub-agent file in `~/.claude/projects`. Each call rewrote `meta.json`. 26 folders in this session bumped to 12:34:47-12:34:52. | `meta.json` mtime 12:34:47 beside a `.jsonl` at 12:28:23 |
| 12:37:21 | Sweep logged `sweep-unchanged`, 23,954 unchanged, 6,838 ms of hashing. | `capture_event` |
| 12:37:39 to 12:37:41 | `cli._run_sweep` called `build.build()` once for the batch; transcript.md, both HTML, manifest.json written. | file mtimes, `cli.py:706` |

The nine-minute capture-to-render gap is ticket 34's known shape (it
measured 7m14s) and is not a defect. Part A and part B are.

## Part A: `write_subagent` rewrites `meta.json` unconditionally

### The mechanism (read from source, then measured)

`archive.write_subagent` (`src/cc_warehouse/archive.py`, the block after the
replace-if-larger branch) does:

```python
if meta is not None:
    store.atomic_write(directory / _META, meta)
```

with no comparison against the file already there. The JSONL beside it has
the full replace-if-larger / refuse-equal-size treatment; `meta.json` gets
none. `store.atomic_write` is tmp-file + `os.replace` (R2), so every call
is a real write plus a directory entry replacement, which bumps the
folder's mtime.

Two callers hit it:

1. `capture._archive_subagents_of` on the hook's fresh path. Runs once per
   captured session. Fine.
2. `sweep.sweep`'s second pass. Sub-agent files have NO catalog row (ticket
   21a: they are part of a session, not one of their own), so the ticket
   31.3 hash pre-filter (`already_known = _cataloged_hashes(...)`) can never
   match one. Every sub-agent file in the source tree is therefore `deferred`
   and handed to `_archive_subagent` -> `write_subagent` on EVERY sweep. The
   JSONL is refused as equal size (correct, silent); the `meta.json` is
   rewritten (wrong, silent).

### Measured 2026-09-06

```
find ~/.claude/projects -path "*/subagents/agent-*.jsonl" | wc -l   -> 2,305
find ~/cc-warehouse-archive -name meta.json | wc -l                 -> 2,505
find ~/cc-warehouse-archive -name meta.json \
     -newer ~/cc-warehouse-data/logs/capture.jsonl | wc -l          -> 2,501
```

`logs/capture.jsonl` was last written 12:25:54, before the sweep. 2,501 of
2,505 archive `meta.json` files are newer than that: the daily sweep
rewrote essentially every one. The 4 that were not are presumably under
sessions whose source folder no longer exists in `~/.claude/projects`
(2,505 archived vs 2,305 in source), which is consistent with the
mechanism: only files the sweep can still SEE get rewritten.

### Cost and harm

- Writes: ~2,500 tmp-file + rename pairs per day, growing with the archive.
  Small in bytes (each meta is ~135 bytes) but it is the exact write pattern
  the weekly `ccw-archive` rsync-style copy has to re-examine, and ticket 30
  exists because that job's cost matters.
- Truth: a sub-agent folder's mtime no longer says when its content
  arrived. This session's folders read 12:34 while the transcript inside
  them arrived 12:28. Finder, `ls -lt`, `find -newer` and any "what changed
  since" instrument now lie for sub-agents. That is the F6 class (a state
  the tool cannot report on) in a small form: the archive's own timestamps
  stopped being evidence.
- Not harmful to content: the bytes written are the same bytes. Nothing is
  lost. This is a correctness-of-record and cost defect, not a data one.

### What to do (proposed, not yet ruled on)

Compare before writing, same shape as the JSONL branch one screen up:

```python
if meta is not None:
    meta_path = directory / _META
    if not meta_path.exists() or meta_path.read_bytes() != meta:
        store.atomic_write(meta_path, meta)
```

Plus, so that the next reader can SEE it did nothing: extend
`SubagentResult` with `meta_written: bool` (or `meta_unchanged`), and have
`sweep._archive_subagent` report `skipped_unchanged` rather than a bare
success when neither the JSONL nor the meta changed. Today the sweep's
BatchReport cannot distinguish "wrote a sub-agent" from "touched one and
did nothing", which is the same blindness ticket 30 closed for sessions.

Oracle test first (`tests/test_archive.py` or wherever `write_subagent` is
covered): write a sub-agent twice with identical meta, assert the second
call leaves `meta.json`'s inode/mtime alone AND reports it as unchanged.
Then a sweep-level test: two sweeps over the same source, the second one
reports every sub-agent as unchanged and writes nothing under `subagents/`
(assert on mtimes across the whole tree, not on one folder: the standing
lesson is that a census on one file is still an instance fix).

Also worth deciding while here: whether sub-agent files should enter the
ticket 31.3 pre-filter at all. A cheap way is to key the snapshot on
content hash of every archived sub-agent JSONL (a walk of the archive's
`subagents/` dirs, or a small side table). That would skip the read+parse
too, not just the write, and is the same cost argument ticket 31 already
made for sessions. Bigger change; the compare-before-write above is the
one-line fix and should land first.

## Part B: a hook killed between "wrote the archive" and "wrote the row" leaves nothing

### What the logs held for this session

Nothing. The wrapper `plugins/cc-capture/hooks/ccw-hook.py` writes ONE line
to `~/.claude/logs/ccw-hook.log`, after `subprocess.run([ccw, "hook"])`
returns. `ccw hook` itself writes to `logs/capture.jsonl` (via
`notify.append_log`) and inserts into `capture_event` at the END of
`_capture_locked`, after `_archive_source` and `_archive_subagents_of`. So
the sequence for this session was:

1. archive JSONL written (durable, 12:28:22)
2. 26 sub-agent folders written (durable, 12:28:23 onward)
3. process gone before the catalog insert, the `capture.jsonl` line, and
   the wrapper's `ok` line

and the three instruments all say "no such capture", while the disk says
"captured". The sweep recovered it two minutes later, correctly and with
no help, which is what the sweep is for. But the operator asking "why" had
to be answered by cross-referencing file mtimes against the catalog's event
table by hand. Ticket 35's stated purpose was exactly the opposite: "if
these different types of situations or edge cases emerge, then everything
gets logged in some file with relevant information".

### Why the hook died is NOT recoverable, and that is the finding

Candidates, none provable from what exists:

- Claude Code's own hook timeout is 45 s (`hooks.json`); the wrapper's
  inner `subprocess.run` timeout is 40 s. The sweep did the same work in
  4.7 s, so a timeout needs the machine to have been ~10x slower at 12:28
  than at 12:30. Not impossible (4+ concurrent sessions is normal here) but
  unlikely.
- Claude Code exiting (window closed, `kill`, crash) and taking the hook
  process tree with it via SIGHUP/SIGTERM. Most likely. The wrapper has no
  signal handler, so a SIGTERM ends it with no line written.
- The `TimeoutExpired` path IS covered: it is a `SubprocessError`, caught,
  reported as `did not run: TimeoutExpired`. The absence of that line rules
  out the wrapper's own 40 s timeout, and leaves Claude Code's 45 s kill or
  an exit-driven signal.

### Edge cases the logs do not cover today

Each row: the shape, what is written today, what would have answered the
operator's question in one line.

| Edge case | Today | Proposed |
|---|---|---|
| Wrapper starts, is killed before `ccw hook` returns | nothing | A `started` line at the top of `main()` with session id and transcript path. A `started` with no matching `ok`/`error` is then a one-grep diagnosis. Keeps the log append-only and the freshness check's parser unaffected (it reads `status`, and a new status value `started` is ignorable). |
| Wrapper receives SIGTERM/SIGHUP | nothing | Best-effort `signal.signal` handler that writes `{"status":"killed","signal":N}` then re-raises the default. Cannot catch SIGKILL; does catch the common exit path. |
| `ccw hook` wrote the archive folder but died before the catalog row | nothing; the next sweep silently takes the fresh path and its archive writes no-op | In `capture._capture_locked`'s fresh path: when `_archive_source` reports the folder ALREADY EXISTED with identical bytes, put that in the `capture_event.detail` (`archive folder pre-existed, bytes identical`) so the row itself records the recovery. Today `detail` is empty for `stored`. Zero-cost: `write_session_folder` already computes this. |
| Sweep pass two writes/no-ops a sub-agent | `ItemOutcome` says success either way | Part A's `skipped_unchanged` for sub-agents, so a sweep BatchReport is honest about what it touched. |
| Sweep-recovered session's render happens minutes later, in `build.build()` after the walk | `_run_sweep` logs build failures since ticket 35; a SUCCESSFUL late render leaves no line saying "this session was captured by the sweep, not the hook, and rendered at T" | Log one line per sweep-`stored` session in `capture.jsonl` with `source: sweep` (the hook's lines already exist for hook captures). Then "who captured this and when" is one grep on the session id, which is the question this ticket started from and which took seven tool calls. |

### Not proposed

- Changing `ccw doctor`'s text output. It is `ccw-watch`'s and the
  freshness check's parsed surface (CLAUDE.md hard rule).
- Any change to SPEC section 5's "all stdio to DEVNULL" for the detached
  render child (ticket 32 already threaded that needle; nothing here
  touches the child).
- Making the hook write the catalog row BEFORE the archive. The order is
  load-bearing (a row must never name a payload nothing holds, capture.py's
  own comment) and the sweep's recovery proves the current order fails
  safe.

## Acceptance

Part A:
- Oracle test: identical meta twice, second call does not rewrite, result
  says so.
- Sweep-level test: second sweep over an unchanged source tree writes zero
  files under any `subagents/` directory.
- Real-data check: run `ccw sweep` by hand after the fix, then repeat the
  three `find` counts above; the `-newer` count must be ~0, not ~2,500.

Part B:
- After the change, kill a hook by hand mid-run (a `sleep` shim on
  `CCW_BIN`, then SIGTERM the wrapper) and show the `started` + `killed`
  pair in `ccw-hook.log`.
- Reproduce this session's shape (archive folder present, no catalog row,
  then sweep) and show the `capture_event.detail` names the pre-existing
  folder.


## DONE 2026-09-06: Part A, and Part B row 1 (commits `81784d3`, `52319d7`)

**Part A.** `store.write_if_changed(path, data) -> bool` is now the one
compare-before-write primitive (the C12 shape). `build._write_if_changed`,
`archive.write_project_sidecar` and `archive.write_subagent` (meta.json AND
the orphan note, which sat two lines below with the same defect and which the
first cut of this fix missed until the review caught it) all call it.
`SubagentResult` gained `wrote`, `refused` and `unchanged`; `sweep.
_archive_subagent` reports `skipped_unchanged` for a no-op and
`refused-subagent` for a smaller or same-size-different payload, instead of a
plain `archived-subagent` for all three. Oracle tests first, over the whole
`subagents/` tree, not one folder.

Real-data acceptance, exactly the three counts from Part A above:

```
touch marker; ccw sweep            -> sweep: 26708 items, 13 stored, 0 failed (2m20s)
find archive -name meta.json -newer marker | wc -l          -> 0
find archive -path "*/subagents/*" -newer marker | wc -l    -> 0
```

Against 2,501 of 2,505 rewritten by the 12:30 run the same morning.

**Part B row 1.** `ccw-hook.py` writes a `started` line before it runs
anything, and EVERY line it writes now carries `"source": "ccw-hook"` and
`"session": <id>` (the review pointed out that a `started`-only session id
forces pairing by position, which is wrong when concurrent session ends
interleave). `grep <session-id> ~/.claude/logs/ccw-hook.log` is the whole
run; a `started` with nothing after it is a hook that died. Five oracle
tests including the killed-mid-run shape.

**Not live until the plugin is updated.** The frozen `ccw` was reinstalled
and carries the archive change; the hook wrapper is loaded by Claude Code from
`~/.claude/plugins/cache/cc-warehouse/cc-capture/<sha>/`, which still holds
the old script until the operator runs `/plugin` and updates
`cc-capture@cc-warehouse`. Verified 2026-09-06: 0 of the cached copies
contain `_started`.

**Still open, in priority order** (from the four-angle review of `81784d3`):

1. Part B row 2, the SIGTERM/SIGHUP `killed` line. Small; the wrapper has no
   signal handler at all today.
2. Part B row 3, `capture_event.detail` naming a pre-existing archive folder
   on the fresh path.
3. The read side. On the unchanged path each sub-agent source file is read 3
   times and JSON-parsed 4 times per sweep (`_content_hash`,
   `_is_subagent_file`, `_archive_subagent`, then `write_subagent`), the
   archived JSONL is read in full for a size compare, `catalog.open_catalog`
   runs once per sub-agent for a label lookup, and `_parent_folder` lists the
   project directory once per sub-agent. About 80 MB of reads and 2,300 sqlite
   opens per day to conclude "unchanged". The fix is the pre-filter: record
   the digest `sweep.sweep` already computes at line ~459 (a small
   `subagent_seen` table, or a second SELECT folded into `_cataloged_hashes`),
   keyed on JSONL+meta together so a changed meta with an unchanged JSONL is
   not skipped. Catalog schema change: its own ticket.
4. Part B row 5, a `source: sweep` line per sweep-stored session.
5. A shared `SubagentResult.action` enum so `capture._archive_subagents_of`
   (which currently discards the result) and the sweep share one vocabulary.

## 2026-09-09: Part B's mechanism is chronic, and it tracks payload size

Found while working ticket 42 item #1 (real notification on the freshness
check). `ccw doctor` reported `capture is NOT working` (`FAIL desync`, 11
problems in 3 folders). All three problem folders are sessions whose
`~/.claude/logs/ccw-hook.log` entry that day shows a `started` line with NO
matching `ok` or `error` - the Part B row 1 line doing exactly the job it was
built for: this took one `tail`, not the seven tool calls the original
2026-09-06 incident needed.

**What's new since the original instance (which was one session, cause
undetermined):**

- **It is chronic, not a one-off.** The daily `ccw repair` job
  (`com.captaincodeau.ccw-repair`, 12:45 local) wrote 23 `repair: fixed`
  lines into `capture.jsonl` at 02:45 UTC the same day, for 23 different
  sessions from the day before. Repair has been silently absorbing this
  every day; nobody had looked at whether it should have to.
- **It tracks payload size.** The two folders with NO catalog row at all
  (`85da9fee-24bb-4285-a6d6-9f88df63a3eb`, `c8f9cc69-fe9d-45d1-9a63-6285c638a7ea`)
  were the two LARGEST sessions of the day: 3.06 MB / 25 sub-agent dirs and
  3.35 MB / 21 sub-agent dirs. Every smaller session captured that day
  rendered fine (checked all 25 most recently captured folders via
  `doctor.desync_detail`). Their raw `.jsonl` and `subagents/` are safely on
  disk - only the derived transcript.md/HTML/manifest never got written, and
  no catalog row exists for either session at all (confirmed by querying
  `catalog.sqlite`'s `session` table directly by `session_uuid`: zero rows).
  This is exactly the Part A/Part B row 3 shape this ticket already names -
  the hook died after writing the archive but before the catalog insert -
  just not previously known to correlate with size.
- **A THIRD, distinct failure showed up in the same batch, worth recording
  separately**: session `abaece35-4037-4f28-8286-bbd612ff38f9` DOES have a
  catalog row, but `ccw doctor` flagged `JSONL does not match manifest
  source_hash`, and `ccw repair` could not fix it (`render failed: exit 1`,
  no stderr). Traced (read-only, one scoped `ccw render --session
  s:5f98fd710bd5`, nothing else touched): the catalog's row was snapshotted
  at `2026-09-09T02:31:07Z` against hash `5f98fd710bd5...`, but the archive
  mirror's `.jsonl` kept growing after that (the session was still active)
  to a different hash, `5482b4c6...`. `archive.read_payload` correctly
  refuses to serve a mismatched file and falls through to `store.get`, which
  unconditionally does `object_path(...).read_bytes()` - but this machine
  runs `keep_objects=false` (ticket 27.3), so `objects/` does not exist, and
  the fallback raises a bare `FileNotFoundError` with no `.filename` context
  (swallowed via `repr(exc)` in `notify.report`, which drops the path
  entirely - `str(exc)` would have kept it). This is a DIFFERENT bug from
  Part B's hook-death shape: no hook died here, a session was captured
  mid-growth and never re-captured once it stabilized, and the render-time
  fallback to a vault that no longer exists on `keep_objects=false`
  installs produces an unhelpful crash instead of a clear "no bytes
  anywhere for this hash" message. Worth its own ticket line if it recurs;
  not fixed here.

**The unresolved timing question from Part B's own "why the hook died is not
recoverable" section, re-measured and STILL unresolved:** the outer
SessionEnd kill is 45s (`hooks.json`) and `ccw-hook.py`'s own inner
`subprocess.run(..., timeout=40)` is 40s. The inner budget is BELOW the outer
kill, so a `TimeoutExpired` should fire first and get logged via the existing
`except (OSError, subprocess.SubprocessError)` branch (`ccw-hook.py:213-215`).
It did not, for either of the two catalog-less sessions. So either Claude
Code kills the SessionEnd hook's process tree before its declared 45s
elapses, or an exit-driven signal (window close, `kill`) takes the whole tree
down regardless of either budget - the same two candidates Part B's original
"why the hook died" section already named, still unprovable from what exists,
now with two more data points that both point the same way (both failures
were large payloads, which is the kind of session most likely to still be
running long enough into shutdown to get caught either way).

**Confirmed, not just suspected:** `cli._run_hook` (`cli.py:549-582`) always
returns 0 on every path, including an in-process exception - so
`ccw-hook.py`'s `result.returncode != 0` branch (`ccw-hook.py:217`) can never
fire in practice. Every real capture failure that does not crash the wrapper
itself lands on `report("ok", ...)`. This is ticket 42 Finding A, and it is
exactly why `ccw-hook.log` showed nothing for these three sessions instead of
a wrong-but-visible "ok": the wrapper's subprocess call itself never
returned, so it never reached line 217 OR line 226.

**The candidate fix, from ticket 42's unranked design-tradeoff list, not
scoped here and needs an operator ruling first:** move the hook's synchronous
sidecar/external-file copying (`capture.py:440-547`,
`_archive_sidecars_of`/`_archive_external_of`) off the SessionEnd timing
budget entirely - detach it (`nohup ... & disown; exit 0`-shaped), at the
cost of losing that piece's ability to report a failure back synchronously
(which ticket 42 proposal #5's `capture.jsonl` reconciliation check would
need to cover instead). Until that lands, `ccw repair`'s daily 12:45 run is
the only thing closing this gap, which means a session captured after 12:45
stays unrendered for roughly 24 hours - a mitigation, not a fix.

Ticket 42 item #1 (real desktop/voice notification on the freshness check)
shipped the same session this was found, deliberately gating the new alert
on `_tier()` rather than the raw streak so a single ordinary blip does not
start popping up notifications - see that file's own change for detail. That
alert will now surface this exact chronic condition instead of only ever
printing to a SessionStart a human might not read.
