# CHEATSHEET - the daily dashboard job

Everything you need for `refresh.py` (sitting right beside this file) and the
`launchd` job that runs it. Written 2026-09-04 so the commands do not have to be
remembered. Deeper explanation lives in `README.md`, "Rebuilding it on a schedule";
the whole machine's job list lives in `../../docs/operations.md`.

Paths use `~`, so every command below can be pasted as it is. Every command here
was executed on 2026-09-04 before this file was committed, including the off/on
round trip, so none of them is copied from memory or a man page.

## What happens by itself

Every day at **13:00** the job scans your transcripts, rebuilds the dashboard
page, then shows a box on screen with three buttons.

| Piece | Where |
|---|---|
| The script | `~/CODE/CaptainCodeAU/cc-warehouse/tools/ccstats/refresh.py` |
| The job | `~/Library/LaunchAgents/com.captaincodeau.ccstats-dashboard.plist` |
| The log | `~/.claude/logs/ccstats-dashboard.log` |
| The page it builds | `~/.cc-warehouse/stats/claude-code-dashboard-live.html` |
| The data it exports | `~/.cc-warehouse/stats/dashboard-data.json` (the page's own payload, ~1.6 MB) |
| The facts card | `~/.cc-warehouse/stats/stats-facts.json` (top-line numbers, ~2 KB) |
| Job name (the "label") | `com.captaincodeau.ccstats-dashboard` |

## The box that appears

| Button | Does |
|---|---|
| `Open page` (the default) | Opens the dashboard in your browser |
| `Show page folder` | Opens Finder at the stats folder, page selected |
| `Show script` | Opens Finder at this folder, `refresh.py` selected |

Three buttons is Apple's hard limit for a dialog, which is why there is no
separate Dismiss: any button closes the box. Left alone it closes itself after
5 minutes. If the run failed there is no page to open, so the buttons become
`Show script` and `Dismiss`.

## Run it right now

Through the real job, exactly as 13:00 would (**this is the one to use**):

```
launchctl kickstart -p gui/$(id -u)/com.captaincodeau.ccstats-dashboard
```

Or by hand, from the repo root:

```
uv run python3 tools/ccstats/refresh.py
```

Two flags worth knowing:

```
uv run python3 tools/ccstats/refresh.py --skip-collect   # rebuild page only, ~3s not ~12s
uv run python3 tools/ccstats/refresh.py --no-notify      # no box
```

## Is it healthy?

```
launchctl list com.captaincodeau.ccstats-dashboard
cat ~/.claude/logs/ccstats-dashboard.log
```

Read it like this:

| You see | Means |
|---|---|
| `"LastExitStatus" = 0` and an **empty** log | Healthy. Empty is correct, not broken. |
| `"LastExitStatus" = 0` and log has text | It ran, but the box could not be shown. Read the text. |
| `"LastExitStatus" = 1` | The run failed. The log says why. |
| `"PID"` present | Still running. Usually the box is on screen waiting for you. |
| No such job / nothing listed | The job is not loaded. See "Turn it off / back on". |

An empty log is the healthy state on purpose, the same convention as the three
`ccw` jobs. That is also why a box that fails to appear is forced into the log:
otherwise "ran fine" and "never ran" would look identical.

## Open the page without waiting for the job

```
open ~/.cc-warehouse/stats/claude-code-dashboard-live.html
```

## Read the numbers without opening the page

The job writes two JSON files beside the page, for anything that is not a browser.

```
# the top-line numbers, ~2 KB, easy to read by eye or with jq
cat ~/.cc-warehouse/stats/stats-facts.json
jq '.facts.sessions_real, .facts.cost' ~/.cc-warehouse/stats/stats-facts.json

# the page's own payload, ~1.6 MB. `.cols` tells you what each array column means
jq 'keys' ~/.cc-warehouse/stats/dashboard-data.json
jq '.cols.S' ~/.cc-warehouse/stats/dashboard-data.json
```

Build them by hand, without waiting for 13:00:

```
cd ~/CODE/CaptainCodeAU/cc-warehouse
uv run python3 tools/ccstats/dashboard.py    # page + dashboard-data.json
uv run python3 tools/ccstats/export.py       # stats-facts.json only, under a second
```

**THE TWO FILES ARE NARROWED DIFFERENTLY, AND EACH SAYS SO.**

`dashboard-data.json` holds EVERY session, including projects that start unticked -
the page applies the tick list in your browser, so narrowing the data would break its
own controls.

`stats-facts.json` IS narrowed, to the saved start date and the saved project
selection, because whatever renders it has no controls. Check either file with:

```
jq '.scope' ~/.cc-warehouse/stats/stats-facts.json
```

## Change the start date, or which projects count

Both live in one file, `~/.cc-warehouse/stats/dashboard-defaults.json`:

```json
{
  "since": "2026-06-08",
  "exclude": ["3rdParty-", "Scaffoldings-"],
  "include": []
}
```

- `since` - the start date for `stats-facts.json`. Remove it for the full range.
  A value that is not `YYYY-MM-DD` is ignored, and you get a full-range card
  rather than a failed job.
- `exclude` / `include` - substring patterns, case-insensitive. `exclude` is a
  denylist, `include` an allowlist, and `exclude` narrows `include`. These set
  both which projects start unticked on the page AND which ones the facts card
  counts.

After editing, rebuild without waiting for 13:00:

```
cd ~/CODE/CaptainCodeAU/cc-warehouse
uv run python3 tools/ccstats/export.py
```

A pattern matching no project prints a warning naming it.

**One number in the card ignores all of this on purpose:** `dst_sessions_all`.
It counts sessions hit by a timezone bug that has been fixed, so it has to quote
the whole corpus. It is listed by name in the file, under
`scope.whole_corpus_facts`, with the reason.

## Change which projects start unticked

The list is saved outside this repo at
`~/.cc-warehouse/stats/dashboard-defaults.json`. Easiest way to change it:

```
/dashboard edit-list
```

`refresh.py` never passes its own filters, so whatever is saved there is what
both the scheduled page and a `/dashboard` page use. They cannot drift apart.

## Change the time it runs

Edit `Hour` and `Minute` in
`~/Library/LaunchAgents/com.captaincodeau.ccstats-dashboard.plist`, then reload:

```
launchctl bootout gui/$(id -u)/com.captaincodeau.ccstats-dashboard
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.captaincodeau.ccstats-dashboard.plist
```

Keep it clear of 12:30 (`ccw-sweep`) and 12:45 (`ccw-repair`).

## Turn it off / back on

```
launchctl bootout gui/$(id -u)/com.captaincodeau.ccstats-dashboard                                  # off
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.captaincodeau.ccstats-dashboard.plist   # on
```

To stop only the box but keep the rebuild, add `--no-notify` to the plist's
`ProgramArguments`, then reload with the two commands above.

## When something is wrong

| Symptom | Almost certainly |
|---|---|
| No box, log says `dialog not shown` | `osascript` was blocked. The log line says by what. |
| No box, log empty, exit 0 | The box appeared and closed itself, or you clicked it. |
| Job never fires | Not loaded. Run the `bootstrap` line above, then `launchctl list`. |
| Fails instantly, empty log | The interpreter path is gone. The job uses the repo's own `.venv/bin/python3`, so a deleted `.venv` stops it. Recreate it with `uv sync` in the repo. |
| Page exists but the numbers look old | Title said `STALE`: the scan failed and the old database was reused. The log says why. |

## The two rules that do not bend

- **Never commit `~/.cc-warehouse/stats/`** or anything in it. It holds real
  project names. That is why it lives outside this repo.
- **Never upload the built HTML** anywhere. Same reason.
