# Ticket 37: the sweep rewrites every sub-agent `meta.json` daily, and a hook killed mid-run leaves no trace

Opened 2026-09-06. **Part A DONE and Part B row 1 DONE the same day** (see the bottom of this file). Part B rows 2, 3 and 5 and the pre-filter follow-up are OPEN. Two findings from one session's timeline
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
