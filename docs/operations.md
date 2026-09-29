# Operations

What actually runs, on a schedule or at every Claude Code session, on the machine this
warehouse lives on. Written 2026-09-01 (ticket 36) after a session had to rediscover all
of this from scratch by reading launchd plists and hook scripts one at a time. Every fact
below was verified directly (read the plist, read the script, ran `launchctl list`) on
2026-09-01, not inferred from a docstring.

## Scheduled jobs (launchd)

Four jobs, all under `~/Library/LaunchAgents/`, all currently loaded
(`launchctl list | grep captaincode`). A fifth entry there,
`com.captaincodeau.hermes-o-backup-pull`, is unrelated to this project.

| Job | Schedule | Command | Log |
|---|---|---|---|
| `com.captaincodeau.ccw-sweep` | daily 12:30 | `ccw sweep --quiet` | `~/.claude/logs/ccw-sweep.log` |
| `com.captaincodeau.ccw-repair` | daily 15:30 (was 12:45 until 2026-09-29, ticket 44) | `ccw repair --quiet` | `~/.claude/logs/ccw-repair.log` |
| `com.captaincodeau.ccw-archive` | weekly, Sunday 03:00 | `ccw archive --to /Volumes/mac/cc-warehouse-archive` (was `~/cc-warehouse-archive` until 2026-09-29, ticket 44) | `~/.claude/logs/ccw-archive.log` |
| `com.captaincodeau.ccstats-dashboard` | daily 13:00 | `.venv/bin/python3 tools/ccstats/refresh.py --quiet` | `~/.claude/logs/ccstats-dashboard.log` |

Notes:

- **`ccw-repair` runs 15 minutes after `ccw-sweep` on purpose**, so the two never contend
  for the same catalog lock (`locks/sweep` and `locks/build` are separate locks, but
  running them back to back rather than concurrently was the simpler choice made when
  `ccw-repair` was added).
  **THAT PREMISE IS FALSE BY MEASUREMENT (ticket 44, 2026-09-28).** From
  `~/cc-warehouse-data/logs/capture.jsonl`, the daily sweep runs 34 to 41 minutes on local
  disk and ends between 13:00 and 13:11, so the 12:45 repair fires INSIDE the sweep's
  window every day, and so does the 13:00 dashboard. The folders repair "fixes" are most
  likely ones the sweep stored minutes earlier and had not yet rendered. On the network
  share the sweep is expected to take 2 to 2.5 hours (ticket 44, accepted and to be
  measured). Moving the repair job past the sweep's real end is a plist edit outside this
  repo; MOVED to 15:30 on 2026-09-29 with the operator's word (dated `.bak` beside the plist).
- **`ccw-repair` is the only DAILY sha256 integrity check, since 2026-09-29
  (W-20260929-A74).** `ccw doctor` at SessionStart now checks presence and size only
  (see "What doctor's `desync` line checks" below); repair's scan of the same 25 folders
  still reads and hashes every recorded file. Measured 2026-09-29 on the share: 7 s with
  a warm cache; the same scan cold measured 16 to 44 s when doctor still ran it. launchd
  sets no timeout on this job, so that fits its slot. What repair does with a hash
  mismatch it finds (re-renders over it) is an open problem; see "What doctor's
  `desync` line checks" below.
- All four use `--quiet` (sweep, repair, ccstats-dashboard) or rely on `ccw archive`'s own default output;
  `--quiet` means **no stdout on success, failures still print**, so an empty log file is
  the expected healthy state, not evidence the job never ran. Check `launchctl list` for
  a job's last exit status (the number after the PID column; `0` is success) rather than
  trusting an empty log alone.
- `ccw-archive` has **no `--verify` flag** in its scheduled invocation. It rebuilds the
  archive tree incrementally; it does not re-check existing folders for integrity. The
  only full-tree integrity check (`ccw archive --to <dir> --verify`, which writes
  nothing) is currently run BY HAND. As of 2026-09-01 this had apparently not been run in
  an unknown amount of time before that day.
- **`ccstats-dashboard` is not part of `ccw` and does not touch the warehouse.** Its
  day to day commands are collected in `tools/ccstats/CHEATSHEET.md`, beside the script. It runs
  `tools/ccstats/refresh.py` (added 2026-09-04), which calls `collect.py`, then
  `dashboard.py` to rebuild `~/.cc-warehouse/stats/claude-code-dashboard-live.html` and
  `dashboard-data.json` beside it, then `export.py` for `stats-facts.json`, then
  `review.py --new` (advisory: it cannot fail the run, and is deliberately never given
  `--record`, so an unwatched dialog cannot acknowledge a warning on the operator's
  behalf). (Both JSON files
  added 2026-09-05, so a program other than a browser can render the same run's numbers; the
  payload file is the page's OWN embedded string, so the two cannot disagree). The payload
  is whole, because the page's own date pickers and tick boxes need it to be; the facts card
  is narrowed to the `since` and project lists saved in `dashboard-defaults.json`, because
  whatever renders it has no controls. Both carry a machine-comparable `scope` object saying
  which they are. All three
  children only READ `~/.claude/projects` and `~/cc-warehouse-archive`; every write lands
  under `~/.cc-warehouse/stats`, and `common.resolve_out` refuses an output root inside the
  repo, `~/.claude`, the archive or the warehouse data root. It passes no project
  include/exclude flags on purpose - `dashboard.py` reads the saved
  `dashboard-defaults.json` itself, so the scheduled page and a `/dashboard` page cannot
  drift apart. Scheduled at 13:00, after `ccw-repair` (12:45), so a sweep's fresh captures
  are already rendered before the stats scan reads them. **It is the only one of these jobs
  that announces itself**: every completion opens a macOS dialog box naming the program
  that ran and the full path of the page it wrote, because a `launchd` job leaves no trace
  on screen and this one's healthy log is deliberately empty, so the box is the only way to
  tell "ran fine" from "never fired". It carries three buttons (AppleScript's ceiling):
  `Show script`, `Show page folder`, `Open page`; a run that wrote no page drops the two
  page buttons and offers `Dismiss` instead. A box rather than a notification banner was
  the operator's explicit call on 2026-09-04, and the cost is real: a dialog is modal and
  transient, so a run nobody is in front of goes unseen where a banner would have waited in
  Notification Centre. It closes itself after 300 seconds so an unattended run never parks
  a process waiting for a click, and a dialog that cannot appear only writes a line to the
  log rather than failing the job. `--no-notify` suppresses it for a hand run. Measured runtime 2026-09-04 on a
  10,148 session corpus: 12 seconds. The interactive `/dashboard` command still exists for
  editing the exclude list and for serving the page over loopback; the scheduled job
  replaces only the rebuild half of it.
- To run any of these manually right now: `launchctl kickstart -p gui/$(id -u)/<label>`.
  To see a job's own header comment (why it exists, what it assumes): `cat
  ~/Library/LaunchAgents/<label>.plist` - all four carry a substantial comment block at
  the top explaining their own reasoning.
- `ccw sweep`, when it captures anything, also calls `build.build()` at the end of its own
  run (see `cli.py::_run_sweep`) - this is what actually renders a session that only
  `ccw sweep` (not the live SessionEnd hook) captured. `ccw-sweep.log` therefore reports
  BOTH capture failures and render (build) failures under one job.

## Hooks that fire on every Claude Code session

Two independent mechanisms, registered in two different places, both on this machine
specifically (not something `cc-warehouse` the package controls):

**Global, every project** - `~/.claude/settings.json`'s own `SessionStart` array includes:
```
test -x "$HOME/.local/bin/ccw-watch" && "$HOME/.local/bin/ccw-watch" || true

Also at SessionStart, since 2026-09-28 and outside this repo: this repository is on the
machine's `ci-watch` watchlist (the operator ran `ci-watch --add .` by hand), so the start
card shows the last CI result for `cc-warehouse master`. `ci-watch` lives in the dotfiles
repo; nothing here configures it.
```
`ccw-watch` is NOT part of this repo. It is a bash script in a different repo entirely,
`fifty-shades-of-dotfiles`, tracked under that repo's own `home` subtree (which mirrors a
home directory layout for symlinking) at `.local/bin/ccw-watch`, and symlinked into place at
`~/.local/bin/ccw-watch`. See "The two consumers of `ccw doctor`" below for what it does.

**This repo's own plugin** - `plugins/cc-capture/hooks/hooks.json` (installed as the
`cc-capture@cc-warehouse` plugin, confirmed enabled in `~/.claude/settings.json`'s
`enabledPlugins`) registers:
- `SessionEnd` -> `ccw-hook.py` (the actual capture: writes the session's JSONL
  synchronously, then spawns the detached render child - SPEC section 2.5/5).
- `SessionStart` -> `ccw-freshness-check.py` (ticket 24.7). See below.

Neither hook is visible by grepping `~/.claude/settings.json` alone for `ccw` - the
SessionEnd/SessionStart wiring for THIS repo's own hooks lives in the plugin's own
`hooks.json`, not in `settings.json`. `settings.json` is where `ccw-watch` (an unrelated,
externally-owned script) happens to be wired instead. Checking only one of these two
files gives an incomplete picture either way.

### Picking up a change to the plugin's hooks

The hooks run from a CACHED COPY, not from this checkout:
`~/.claude/plugins/installed_plugins.json` points `cc-capture@cc-warehouse` at
`~/.claude/plugins/cache/cc-warehouse/cc-capture/<gitsha>/`, built from a clone of the GitHub
remote (the marketplace source in `~/.claude/plugins/known_marketplaces.json`). The version
string IS the commit hash. So neither a local commit nor `uv_tool_reinstall_current_project`
changes what runs; and `claude plugin update` reports "already at the latest version",
truthfully and uselessly, until the commit is on GitHub (harness/HANDOFFS.md records the
first time that caught a session). In order, from any directory:

1. Merge to `master` and push it to GitHub.
2. Refresh the marketplace clone:
   ```
   claude plugin marketplace update cc-warehouse
   ```
3. Update the plugin. Read what it shows before accepting; do not add `-y`, which accepts
   whatever install command the marketplace declares (docs/agent-setup-contract.md, step 3):
   ```
   claude plugin update cc-capture@cc-warehouse
   ```
4. Verify by what EXECUTES, not by what was pushed: the registry must name the new hash, and
   the cached file must carry the change. For the 2026-09-29 background check, for example:
   ```
   grep -c '"async": true' ~/.claude/plugins/cache/cc-warehouse/cc-capture/*/hooks/hooks.json
   ```
   The newest `<gitsha>` directory must print 1 (an older one printing 0 is the control).
5. Start a NEW session. A session resolves its plugin path at start, so sessions already
   running keep the old hooks until they end.

`ccw` itself is a separate frozen install (CLAUDE.md, "`ccw` IS INSTALLED AS A FROZEN
SNAPSHOT"). A change under `src/` needs that reinstall; a change under `plugins/` needs the
steps above; a change to both needs both, and ccw-hook.py's "DEPLOY-ORDER SAFETY" note says
which goes first.

No crontab entries exist for this user (`crontab -l` -> "no crontab").

## The two consumers of `ccw doctor`

`ccw doctor`'s TEXT OUTPUT and EXIT CODE are a public compatibility surface: two
independent scripts, neither owned by this repo's own test suite, parse them. Changing
doctor's wording or exit-code semantics without checking both can break either silently.

**`ccw-watch`** (external, `fifty-shades-of-dotfiles`). **STALE BELOW THIS LINE, corrected
2026-09-28 (ticket 44): `ccw-watch` STOPPED calling `ccw doctor` on 2026-09-07.** Its own
header says so ("NARROWED 2026-09-07. IT NO LONGER ASKS `ccw doctor` ANYTHING"): it now
checks only that the capture plugin is installed and reports `capture installed -- ccw
<version>, plugin <hash>` at SessionStart. So `ccw-freshness-check.py` below is the ONLY
consumer of doctor's text and exit code, and the only doctor wording it depends on is the
literal `Uncaptured: <N> session` prefix (regex `Uncaptured:\s*(\d+)\s*session`) plus
the exit code. The account that follows is kept as the record of what `ccw-watch` did
until 2026-09-07. Ran `ccw doctor` at the start of
EVERY Claude Code session in EVERY project on this machine (not just this repo). On a
non-zero exit code it showed an escalating banner:
- day 0-2: a plain red line, `RED capture is NOT working -- <N>d`, plus the FAILING
  check's own detail text verbatim (doctor already names what's wrong and by how much;
  `ccw-watch` does not re-word it).
- day 3-6: a louder boxed banner plus a spoken voice alert.
- day 7+: the loudest banner, spoken every session.

Only clears when `ccw doctor` reports healthy again, or a deliberate
`ccw-watch --snooze <days>`. State (whether currently broken, and since when) lives in
`~/.local/state/ccw-watch/capture.state` - **a single snapshot file, overwritten on every
check**. It records "broken since" as an epoch timestamp while broken, but the moment
doctor reports healthy again that timestamp is gone - there is no history of past broken
periods anywhere, only the live/current state.

**`ccw-freshness-check.py`** (this repo, `plugins/cc-capture/hooks/`, ticket 24.7). Runs at
SessionStart too, but only via the `cc-capture@cc-warehouse` plugin's own hook wiring, and
its trigger is `ccw doctor`'s EXIT CODE specifically (not the raw `Uncaptured: N` figure,
which sits at 200-350 permanently on this machine by design and is explicitly
non-blocking). **Since 2026-09-29 (W-20260929-A93, rulings: Gavin) it escalates on how LONG
capture has been continuously broken, not on a count of session starts, and it runs in the
background.** The first failed check stamps `broken_since` in
`~/.claude/logs/ccw-freshness-state.json`; the first healthy check clears it. Broken under 30
minutes: logged as `info` and handed to the session only. 30 minutes: a desktop
notification (`warn`). 2 hours: desktop plus the spoken alert (`alert`). A doctor that could
not be asked (timeout, crash) runs the same clock with "could not check capture" wording. The
clock is wall time and includes sleep. A state file that exists but cannot be read, or cannot
be written, warns at once rather than restarting the clock. `hooks.json` marks the entry
`"async": true`, so a session start never waits on doctor; Claude Code then drops the hook's
plain stdout and delivers its JSON `additionalContext` to the MODEL on the next turn, never to
the screen, and enforces no timeout (code.claude.com/docs/en/hooks, checked against the
installed 2.1.284 binary). So the desktop and voice channels are the only ones that reach a
human, and the script bounds itself (`_DOCTOR_TIMEOUT`, 45 s). A kernel `flock` on
`~/.claude/logs/ccw-freshness.lock`, which the doctor child inherits, means panes starting
together run ONE doctor; the others log `reused` and hand on the last verdict. A lock held more
than 5 minutes is a hung check and is reported as an unanswered one, timed from when it
began. The scheduled-job check runs only in the lock holder. Pinned by
`tests/test_cc_capture_freshness_timing.py`. It logs
every check (both pass and warn) as a durable JSON line in `~/.claude/logs/ccw-hook.log`
(`source: "ccw-freshness-check"`) - unlike `ccw-watch`, this one keeps real history, since
it's an append-only log rather than an overwritten snapshot. Its message text names the
raw uncaptured count in the wording (e.g. "capture check failed (246 uncaptured)"), which
can read as if THAT number is the problem even when the real failing check is something
else entirely (e.g. desync) - a real weakness in the message clarity, not the detection
logic, confirmed during a 2026-09-01 investigation (ticket 34's own account has the
detail).

**What doctor's `desync` line checks at SessionStart, since 2026-09-29 (W-20260929-A74;
ruling: Gavin, option 1).** It is a QUICK check over the 25 most recently started
archive folders: every file each folder's manifest lists (the payload, sub-agents,
tool results, file-history, pastes, `prompts.jsonl`, `custom-title.json`) must be
PRESENT and the RIGHT SIZE, compared by `stat` against sizes already recorded (each
manifest record's `bytes`, and the catalog's `size_bytes` for the payload). It opens
`manifest.json` and nothing else, hashes nothing and parses no JSONL; the hidden flag
and the folder name come from the catalog row. The line says so: `(quick check:
present and right size; ccw repair checks hashes)`. Why: the full sha256 check over
those 25 folders read 118 MB in 557 opens over the network share and took 17 to 44 s,
against the freshness hook's 45 s, and a timeout counts as a failure. Measured after
the change on the same machine: whole `ccw doctor` 7 to 10 s (was 14 to 45 s), the
desync step alone 3.5 s cold and 0.2 s warm.
**What it cannot see, accepted:** a file whose bytes changed but whose length did
not. The FULL check still runs daily in `ccw repair` (same 25 folders, every file
sha256-hashed and the payload parsed) and weekly-or-by-hand in `ccw archive --verify`,
so such a change is DETECTED within a day. A manifest record written before records
carried `bytes` is hashed instead of skipped. Pinned by
`tests/test_doctor_quick_desync.py`.
**DETECTED IS NOT ALARMED, and this is open (found 2026-09-29, pre-existing).** When
`ccw repair` finds a hash mismatch it does what it does for a missing render: it
re-renders the folder, and the re-render records the CHANGED bytes' hashes in the
manifest. Repair then logs "1 fixed", exits 0, and every later check (repair, doctor,
`ccw archive --verify`) reads the folder as clean. Verified in a test sandbox for all
five recorded kinds (payload, sub-agent, tool result, `prompts.jsonl`,
`custom-title.json`). Before this change doctor at SessionStart would FAIL on such a
folder until that day's repair ran; now nothing shows it except repair's own log line.

## The `sidecars` line, and the alert that is not a banner (ticket 38, 2026-09-08)

`ccw doctor` gained a THIRD kind of line in 0.1.3, and its whole design is about not
becoming a fourth thing that shouts:

```
  ok   sidecars    0 folder(s) with unarchived siblings; 39 sidecar dir(s) without a transcript
       sidecars    3 folder(s) with unarchived siblings, e.g. widget/2026...: zzz-probe; 39 sidecar dir(s) without a transcript
```

**It is NEVER blocking.** It does not move `ccw doctor`'s exit code, so neither
consumer above ever sees it: `ccw-watch` branched on the exit code and grepped for
`^\s*FAIL` (until 2026-09-07, see above), and `ccw-freshness-check.py` escalates on the exit code.

**SINCE TICKET 44b (2026-09-28) THE FIGURE IS MEASURED BY `ccw sweep`, NOT BY DOCTOR.**
This line and the `prompts` line are still corpus-wide, but reading one file in every
one of 31k archive folders at every SessionStart was 62k file opens, and with
`archive_root` on a network share that alone is minutes against a 55 s hook budget. The
daily sweep, which lists every folder anyway, now writes both figures to
`~/cc-warehouse-data/logs/coverage.json` after its post-sweep build, and doctor prints
them with the sweep's timestamp: `... (as of 2026-09-28T02:31:07+00:00)`. Before the
first sweep after upgrading, doctor prints `not measured yet: the next ccw sweep writes
logs/coverage.json` and stays `ok`. `ccw status`, which is run by hand, still walks and
reports live figures. The same ticket moved doctor's other tree walks to the catalog:
one `ccw doctor` used to make 292,286 filesystem calls under `archive_root` (measured
2026-09-28); it now touches only the 25 most recently captured folders.

**The SessionEnd hook's budget, recorded here because ticket 44 moves the archive onto a
slower disk.** `plugins/cc-capture/hooks/hooks.json` gives `ccw-hook.py` 45 s and the
wrapper kills the `ccw hook` child at 40 s. The ONLY synchronous write to `archive_root`
inside that budget is the session's JSONL (`capture._archive_source`); rendering and the
companion copies run in detached children afterwards. Measured locally the capture
median is 69 ms, p95 0.5 s; on the share about 0.5 s typical and 2 s at p99. A payload
above roughly 90 MB would not finish in 40 s at the share's 2.4 MB/s; exactly one
archived session (114 MB) is that large, and a killed hook is not a lost session: the
next `ccw sweep` captures it. Both are pinned
by tests that run their REAL sed and grep commands against a report carrying an
anomaly. This is deliberate, and it is the ticket 24.7 lesson: the `Uncaptured: N`
figure on this machine sits between 200 and 350 permanently on a healthy install, and
a threshold on a figure like that printed ALERT at every session start until it was
corrected. A chronic red banner is one nobody reads.

**The attention comes from a macOS notification instead.** `notify.alert` fires only
when a session's `sidecars.json` CHANGES to a non-empty set, so a permanent anomaly is
announced on the run that finds it and never again. It is a detached `osascript`
child, so it cannot block the capture hook, and it is a no-op off macOS. The same
sentence also goes to the voice sink this machine already has configured. Turn it off
with `[notify] desktop_alerts = false`.

**Two figures, not one.** `N folder(s) with unarchived siblings` is a job for whoever
adds a copier to `src/cc_warehouse/sidecars.py`. `M sidecar dir(s) without a
transcript` is a property of `~/.claude`'s own layout and is expected to sit at a
small non-zero number forever (39 here); the daily sweep copies them under
`<archive>/_not-sessions/stranded-sidecars/`, so the figure being non-zero is not a
backlog.

**Cost.** The check is corpus-wide (every archive folder, not the 25-folder recency
sample the desync check uses), because the failure it exists to catch was four months
old before anyone saw it. It can afford that because it opens `sidecars.json` and
nothing else: no payload is read and nothing is hashed, pinned by a test that
monkeypatches `store.sha256_hex` to raise.

**What the daily sweep now does extra.** A third pass over every session path,
including the ones reported `skipped_unchanged`, mirroring `tool-results/` and
`workflows/` into their session folders. It reads about 135 MB and writes nothing on a
steady-state run; the archive grew about 135 MB once, on the back-fill.

## Real incident this session traced end to end (2026-09-01)

`ccw doctor`'s desync check flagged "110 problems in the 25 most recently captured
folders" this session. `ccw-watch` showed its RED banner (captured verbatim, with a
timestamp, inside the Claude Code session transcript that was running when it fired -
Claude Code saves every hook's stdout as part of that session's own JSONL, so the exact
banner text and firing time are recoverable after the fact by reading that session's
transcript directly, which is how this was confirmed). The root cause and the fix are
both ticket 34's account; this file exists so the NEXT investigation starts from a map
instead of rebuilding one.
