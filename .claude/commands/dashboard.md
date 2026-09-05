---
name: dashboard
description: Build and open the live interactive ccstats dashboard for this machine (tools/ccstats/dashboard.py -> ~/.cc-warehouse/stats/claude-code-dashboard-live.html). Always asks before refreshing the underlying session data. Reuses a saved private project-exclude list, asking once to create it if none exists yet. Serves the built file once over loopback HTTP (a plain file:// link is refused by the browser tool), hands over the exact link, then stops the server once the operator confirms they have opened it. Never commits or uploads anything; the output and the saved exclude list both hold real project names and stay outside this repo, under the tool's own private, gitignored output folder. Manual only.
argument-hint: "[ (blank = normal run) | refresh | no-refresh | edit-list ]"
disable-model-invocation: true
allowed-tools: Bash, Read, Write, Edit
---

# /dashboard - build and open the live ccstats dashboard

Builds `claude-code-dashboard-live.html` from `tools/ccstats/dashboard.py` and hands the operator
a working link to it. If this is the first time running this command in a session, skim
`tools/ccstats/README.md`'s "The live dashboard" and "Safety" sections first - they explain what
the flags actually do and why the output must never be committed or uploaded.

**A scheduled, agent-free path exists and this command does not replace it.**
`tools/ccstats/refresh.py` runs Steps 1 and 3 (collect, then build) with no questions and no
web server, and `com.captaincodeau.ccstats-dashboard` runs it daily at 13:00 (see
`docs/operations.md`). So the page is usually already fresh. What this command still adds:
choosing whether to refresh right now, showing and editing the saved project-exclude list, and
serving the file over loopback because the browser tool refuses `file://`. If all the operator
wants is a rebuild, `uv run python3 tools/ccstats/refresh.py` is the shorter answer.

**Mode = `$ARGUMENTS`** (default: full normal run):

- **blank** - full run: Steps 1-5 below, in order.
- **`refresh`** - skip Step 1's question; refresh the data unconditionally.
- **`no-refresh`** - skip Step 1's question; do not refresh.
- **`edit-list`** - run Step 2 only (show/edit the saved exclude list), then stop. No build, no
  serve.

## Step 0 - resolve the output root, once

Every path below means **`$OUT`**, resolved the same way `common.py`'s `resolve_out` resolves it
for every other ccstats command (see `tools/ccstats/README.md`, "Where it writes"): the
`CCSTATS_OUT` environment variable if it is set, otherwise `~/.cc-warehouse/stats`. Do not
hardcode `~/.cc-warehouse/stats` in any command below - read `$CCSTATS_OUT` first (e.g. with
`echo "${CCSTATS_OUT:-$HOME/.cc-warehouse/stats}"`) and use that resolved path everywhere,
including the Python one-liner in Step 2. This is what lets a test run point everything at a
scratch folder (`CCSTATS_OUT=/some/temp/dir`) without touching the real one - `dashboard.py` and
`collect.py` already honour that variable themselves; this command must agree with them rather
than hardcoding its own copy of the default.

## Step 1 - refresh the underlying data?

Check whether `$OUT/sessions.sqlite` exists and how old it is (on macOS:
`stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$OUT/sessions.sqlite"`).

- **Does not exist yet:** say so, explain that `collect.py` (read-only, scans every transcript,
  about 22 seconds) has to run once before a dashboard can be built, and run it. Not optional the
  first time - do not ask.
- **Exists:** tell the operator its age, then ask (yes/no, unless the mode already decided it)
  whether to refresh it now. Refreshing means, from the repo root:
  `uv run python3 tools/ccstats/collect.py`
  Read-only (see the README's Safety section), about 22 seconds. If they say no, use the existing
  file as-is.

## Step 2 - the project-exclude list

Saved at `$OUT/dashboard-defaults.json`, shape:
`{"exclude": ["substring", ...], "include": ["substring", ...]}`. This file holds real project
folder names. It already lives outside the repo and must never be committed or uploaded - same
rule as the dashboard output itself.

- **File exists:** read it, show the operator the current `exclude` (and `include`, if any) list,
  and ask whether to reuse it as-is or edit it (add/remove substrings, or replace the whole list).
  Matching is case-insensitive and matches anywhere inside `project_label` - a full project name
  is itself a valid substring.
- **File does not exist yet:** explain that this list only sets which projects START unticked when
  the page opens (the operator can always change it live in the browser afterward, nothing here is
  permanent), then print the live, current list of distinct `project_label` values so they can
  pick real names instead of guessing:
  ```
  uv run python3 -c "
  import os, sqlite3
  from pathlib import Path
  out = Path(os.environ.get('CCSTATS_OUT') or (Path.home() / '.cc-warehouse' / 'stats')).expanduser()
  conn = sqlite3.connect(out / 'sessions.sqlite')
  for (name,) in conn.execute('SELECT DISTINCT project_label FROM session ORDER BY 1'):
      print(name)
  conn.close()
  "
  ```
  Ask for the exclude list (and, only if wanted, an include allowlist). Write the JSON with this
  project's own write convention (R2): build the new content, write it to
  `dashboard-defaults.json.tmp` in `$OUT`, then replace the target with it atomically - never edit
  the live file in place.
- **Mode is `edit-list`:** stop here once saved. Do not build or serve.

## Step 3 - build

Read `dashboard-defaults.json` with the Read tool and turn its `exclude`/`include` arrays into
repeated `--exclude "..."` / `--include "..."` flags yourself (do not attempt a clever inline
shell one-liner to do this - build the flag list directly, then run the command). From the repo
root:
```
uv run python3 tools/ccstats/dashboard.py --exclude "..." --exclude "..." [--include "..."]
```
Do not pass `--since`/`--until` unless the operator has separately asked to shrink the embedded
range - the default (full range) is correct for normal use, since the page's own date pickers
already let the reader narrow what they see without a rebuild.

Report the exact line the script prints on success (output path, byte size, session count,
window).

## Step 4 - serve it once

The browser tool refuses `file://` URLs. Serve the output folder over loopback instead, with
`--directory` so no `cd` is needed (this project's Bash rule: never start a command with `cd`):
```
uv run python3 -m http.server 8721 --bind 127.0.0.1 --directory "$OUT"
```
Run this with `run_in_background: true`. If port 8721 is already taken, try 8722, then 8723.

Give the operator the exact link:
`http://127.0.0.1:<port>/claude-code-dashboard-live.html`

## Step 5 - stop the server

Ask the operator to confirm they have opened the page and are done with it for now (a quick
yes/no). The file is fully self-contained once loaded in a tab, so stopping the server afterward
does not break an already-open tab. Once confirmed, stop the background server process. If they
want to keep it open longer, wait and ask again rather than killing it under them.

## Never

- Never commit `~/.cc-warehouse/stats/` or anything inside it - not the dashboard HTML, not the
  CSVs, not `dashboard-defaults.json`, not `dashboard-data.json` or `stats-facts.json`. Real project data, stays outside this repo, per the
  README's own Safety section.
- Never upload the built HTML or the defaults JSON via the Artifact tool or any other external
  host.
- Never set `CCSTATS_OUT` (or otherwise resolve `$OUT`) to somewhere inside this repo, `~/.claude`,
  the archive, or the warehouse data root - `resolve_out` already refuses those; do not attempt to
  work around a refusal.
