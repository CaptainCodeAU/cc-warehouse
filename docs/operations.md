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
| `com.captaincodeau.ccw-repair` | daily 12:45 | `ccw repair --quiet` | `~/.claude/logs/ccw-repair.log` |
| `com.captaincodeau.ccw-archive` | weekly, Sunday 03:00 | `ccw archive --to ~/cc-warehouse-archive` | `~/.claude/logs/ccw-archive.log` |
| `com.captaincodeau.ccstats-dashboard` | daily 13:00 | `.venv/bin/python3 tools/ccstats/refresh.py --quiet` | `~/.claude/logs/ccstats-dashboard.log` |

Notes:

- **`ccw-repair` runs 15 minutes after `ccw-sweep` on purpose**, so the two never contend
  for the same catalog lock (`locks/sweep` and `locks/build` are separate locks, but
  running them back to back rather than concurrently was the simpler choice made when
  `ccw-repair` was added).
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
  `dashboard-data.json` beside it, then `export.py` for `stats-facts.json` (both JSON files
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

No crontab entries exist for this user (`crontab -l` -> "no crontab").

## The two consumers of `ccw doctor`

`ccw doctor`'s TEXT OUTPUT and EXIT CODE are a public compatibility surface: two
independent scripts, neither owned by this repo's own test suite, parse them. Changing
doctor's wording or exit-code semantics without checking both can break either silently.

**`ccw-watch`** (external, `fifty-shades-of-dotfiles`). Runs `ccw doctor` at the start of
EVERY Claude Code session in EVERY project on this machine (not just this repo). On a
non-zero exit code it shows an escalating banner:
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
non-blocking). It escalates on a CONSECUTIVE-FAILURE STREAK across session starts and logs
every check (both pass and warn) as a durable JSON line in `~/.claude/logs/ccw-hook.log`
(`source: "ccw-freshness-check"`) - unlike `ccw-watch`, this one keeps real history, since
it's an append-only log rather than an overwritten snapshot. Its message text names the
raw uncaptured count in the wording (e.g. "capture check failed (246 uncaptured)"), which
can read as if THAT number is the problem even when the real failing check is something
else entirely (e.g. desync) - a real weakness in the message clarity, not the detection
logic, confirmed during a 2026-09-01 investigation (ticket 34's own account has the
detail).

## Real incident this session traced end to end (2026-09-01)

`ccw doctor`'s desync check flagged "110 problems in the 25 most recently captured
folders" this session. `ccw-watch` showed its RED banner (captured verbatim, with a
timestamp, inside the Claude Code session transcript that was running when it fired -
Claude Code saves every hook's stdout as part of that session's own JSONL, so the exact
banner text and firing time are recoverable after the fact by reading that session's
transcript directly, which is how this was confirmed). The root cause and the fix are
both ticket 34's account; this file exists so the NEXT investigation starts from a map
instead of rebuilding one.
