# Ticket 37: the sweep rewrites every sub-agent `meta.json` daily, and a hook killed mid-run leaves no trace

Opened 2026-09-06. **Part A DONE and Part B row 1 DONE the same day** (see the bottom of this file). Part B rows 2, 3 and 5 and the pre-filter follow-up are OPEN. **2026-09-09: Part B's underlying mechanism confirmed CHRONIC and size-correlated; the day's 3 stuck sessions were recovered via `ccw sweep`, but the mechanism itself is still unfixed - operator ruled on the fix's shape (detach + log-file reporting), not yet built - see that dated section near the bottom.** Two findings from one session's timeline
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

**All 3 sessions recovered the same day, by the operator's explicit go-ahead
to run `ccw sweep` early rather than wait for the 12:30 scheduled job.**
`sweep: 28059 items, 31 stored, 12 with sidecars, 0 failed`. Verified two
ways: `ccw doctor` went from `FAIL desync` (11 problems, 3 folders, exit 1)
to `ok desync` (0 problems, exit 0), and all three archive folders were
checked directly on disk - `transcript.md`, both HTML variants, and
`manifest.json` now present in each, including the third (`abaece35-...`),
whose stale-catalog-row shape `ccw repair` could not fix on its own but a
fresh sweep re-captured cleanly since the source session had since ended and
stabilized. This confirms the sweep-as-safety-net property Part B's own
"Not proposed" section already argues for; it does not confirm anything about
whether the underlying hook-death mechanism itself is fixed.

**Operator ruling on the candidate fix, 2026-09-09: detach the hook's
synchronous sidecar/external-file copying, and report a failure in that
detached work via a log file a daily job reads** - the same shape this repo
already uses for `sidecars`/`history`/`prompts` (a non-blocking `ccw doctor`
line reading a durable log, per ticket 38 ruling (e)), rather than trying to
report synchronously from work that is deliberately no longer on the
SessionEnd critical path. **Not built this session** - scoping the actual
diff (where the detached child writes its log, which existing daily job
reads it or whether it needs a new one, what the new `ccw doctor` line looks
like, and whether it reuses `notify.alert` or needs its own path given this
file's "must not import `cc_warehouse`" constraint) is real design work on
its own and was deliberately left for a dedicated session rather than rushed
in under this one's original scope.

## Part B DONE, 2026-09-09 (same-day follow-on session): the detached companions child

Scoped and built the diff the previous section deliberately left open. **Widened
the scope of what detaches, past the operator's original ruling, on measured
evidence rather than guessing**: `_archive_subagents_of` alone is 14-18 MB /
30-90 files on a big session, ~90% of the hook's total elapsed time (the
sidecar/external work the ruling named is the other ~10%), and the slowest
real `stored` capture in the two days measured (4,331 ms) was nowhere near the
40s/45s timeout budgets - independent confirmation that a hook lost mid-run is
being killed by a signal, not a timeout, so shortening the window is what
actually lowers the odds of getting caught in it. Detaching only sidecars/
external would have moved ~10% of the exposure and left this ticket
effectively open; the operator confirmed detaching all four calls before this
was built.

**What shipped:**
- `capture.py`: the four companion functions widened to take `session_uuid:
  str | None` instead of a full `parser.ParsedSession` (same reason
  `log_sidecar_trouble` was widened in 39e - a caller that only knows a
  catalog `short` should not have to re-parse a multi-megabyte transcript for
  a 36-character string), lifted into one new public `archive_companions()`.
  `capture_transcript()` gained `defer_companions: bool = False`; default
  false keeps `ccw sweep`/`ccw import`/`ccw migrate` byte-for-byte unchanged
  (not on a timing budget, and one detached child per sweep item is the wrong
  shape at scale, per DESIGN 15's own ticket-31 cost argument).
- `cli.py`: new hidden verb `ccw companions --session s:<key> --transcript
  PATH` (the `notify`/`render` precedent for a machine-invoked verb absent
  from `_VERB_OPTIONS`), `_spawn_companions` (same `start_new_session=True`,
  all-DEVNULL Popen shape SPEC 2.5/5 locks, spawned beside `_spawn_render`),
  `_run_companions` (re-derives `project_id`/`session_uuid` from the catalog
  by `short`, calls the SAME `archive_companions` the inline path calls so
  the two can never drift), `_log_companions` (writes `companions-started`/
  `companions-done`/`error` into the EXISTING `logs/capture.jsonl`, six-field
  schema unchanged, every message prefixed `"companions: "` so a later reader
  can tell this child's `error` lines apart from unrelated ones sharing the
  same `session` value). `_run_hook` now passes `defer_companions=True`.
- `doctor.py`: `_companions_stalled` (modelled on `_history_staleness`, not on
  a `status.py` gap/line pair - a machine-level log is that function's shape).
  Pairs `companions-started` against `companions-done`/a `companions: `-
  prefixed `error` by `session`, within a 7-day window, `_COMPANIONS_GRACE_
  SECONDS = 300` before a started-with-no-finish counts as stalled rather
  than merely running. Registered NON-BLOCKING (ticket 38 ruling (e) posture)
  after `prompts` in `diagnose`; `report_text`/the exit-code rule are
  untouched, so `ccw-watch`'s `grep -E '^\s*FAIL'` and `ccw-freshness-
  check.py`'s exit-code read are both unaffected by construction (proved by a
  real `grep` subprocess, not just an assertion on the Python object).
- `store.py`: `get()` now raises an `OSError` (constructed from the original's
  own `errno`, so `isinstance` and the concrete subclass are unchanged) whose
  message names the hash and the vault root. Fixes a REAL, separate incident
  this same session found live on the operator's machine (see "A second,
  distinct bug" below): the bare form's `repr()` drops the filename entirely
  (confirmed by inspection: `FileNotFoundError(2, 'No such file or
  directory')`), and `notify.report`'s error path formats with `repr()`, so a
  `keep_objects=false` install with no `objects/` crashed with a message
  carrying no path and no hash at all.
- New `tests/test_companions_detach.py` (9 oracle tests: the defer flag,
  `archive_companions` producing the same tree as the inline path, the verb's
  catalog lookup and logging, and every state of the new doctor check) plus
  two new `test_store.py` tests for the `get()` message. `tests/conftest.py`
  gained `settle_companions` (the companions-child twin of the existing
  `settle_render`), and the pre-existing hook-fire-then-assert-on-companion-
  content tests across `test_external_capture.py`, `test_sidecar_capture.py`,
  `test_subagent_capture.py`, `test_sidecar_boundaries.py` were updated to
  wait on it - those tests were racing a background process that did not
  exist before this ticket.

**A genuinely new race this ticket's own change caused, found and fixed, not
just inherited**: adding a SECOND detached child per hook fire (companions,
alongside the pre-existing render child) measurably raised the odds of a
PRE-EXISTING, previously-rare race in `test_sidecar_sweep.py`'s
`test_a_sweep_that_only_archived_sidecars_still_rebuilds_the_manifest` - the
hook's own render child (built before this ticket, unrelated to it) can write
a STALE `manifest.json` (built before a later-arriving sidecar file existed)
AFTER a subsequent sweep's build already wrote the correct one, if the render
child is still in flight. Proven, not assumed: 8/8 clean runs on the
pre-change commit (`git stash`), 1/5 failing with the change applied, 12/12
clean again once the test was given a `settle_render` wait it always should
have had. Fixed with a one-line wait in the test, not a change to the render
child or the new companions child - the mechanism was already there; this
ticket only made it more visible.

**A second, distinct bug found and root-caused, but NOT force-fixed**: this
ticket's own plan guessed slice 4b's fix was "`build._heads` renders from a
stale head instead of the one matching the bytes on disk" (a ticket-29-shaped
ranking bug). **Reproduced end to end in a scratch archive_root and the guess
was wrong.** The real mechanism: a capture's archive write (`_archive_source`,
durable, always first by design) succeeds, and then its OWN catalog-row
insert (`catalog.add_session`) fails - the exact, already-documented ticket
31.4 sqlite-contention shape, reproduced here with a monkeypatched
`add_session` raising after a real archive write - so the archive folder ends
up holding bytes at a hash NO catalog row for that `session_uuid` names.
`ccw repair` can never fix this by construction: it only ever re-renders from
a catalog row, and there is no row matching what the archive actually holds,
so it fails with `render failed: exit 1` and empty stderr - exactly the shape
this ticket's own 2026-09-09 addendum first saw on `abaece35`. The machine's
own PROVEN recovery is `ccw sweep` re-capturing the still-present source
transcript once it stabilizes (recorded lower on this page: "all 3 sessions
recovered... via ccw sweep"), not a change to repair's rendering logic. Slice
4a (the `store.get` message fix above) already turns this incident's
operator-facing symptom from a contextless crash into a message naming the
hash and the vault root; no further code was shipped for this half of 4b,
per this ticket's own instruction to write up a wrong guess rather than force
it through. Left as an open question for the operator: whether `_run_repair`
should also read `capture.jsonl`'s own error line to enrich its "still
broken" report (small, safe, deferred rather than freelanced), or whether
this is adequately covered by the next day's scheduled sweep.

**Real-data acceptance, run 3x for confidence**: `uv run pytest tests/ -q` -
1542 passed, zero failures, three consecutive clean runs (no flakes). Full-repo
`ruff check .` and `pyright` both clean. **Not yet done, needs the operator's
go-ahead at the moment of running**: `uv_tool_reinstall_current_project`, the
`/plugin` update, and the real-session acceptance checks this ticket's own
Verification section calls for - none of that was run this session.
