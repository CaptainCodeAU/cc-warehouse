---
name: daywall
description: Build and open the live 3D ccstats companion page for this machine (tools/ccstats/daywall.py -> ~/.cc-warehouse/stats/claude-code-daywall.html). One box per session, positioned by day and hour, WebGL2, no library. Shares the same private project-exclude list /dashboard uses - never asks to edit it, only offers to run /dashboard first if it does not exist yet. Serves the built file once over loopback HTTP (a plain file:// link is refused by the browser tool), hands over the exact link, then stops the server once the operator confirms they have opened it. Never commits or uploads anything. Manual only.
argument-hint: "[ (blank = normal run) | refresh | no-refresh ]"
disable-model-invocation: true
allowed-tools: Bash, Read
---

# /daywall - build and open the 3D ccstats companion page

Builds `claude-code-daywall.html` from `tools/ccstats/daywall.py` and hands the operator a
working link to it. If this is the first time running this command in a session, skim
`tools/ccstats/README.md`'s "Safety" section first - the same rules apply here (never commit,
never upload, output stays outside this repo).

This page is a **companion** to `/dashboard`'s `claude-code-dashboard-live.html`, not a
replacement - point the operator at `/dashboard` for the 20-panel view; this one is for seeing
session-level overlap and daily rhythm directly.

**Mode = `$ARGUMENTS`** (default: full normal run):

- **blank** - full run: Steps 1-4 below, in order.
- **`refresh`** - skip Step 1's question; refresh the data unconditionally.
- **`no-refresh`** - skip Step 1's question; do not refresh.

## Step 0 - resolve the output root, once

Every path below means **`$OUT`**, resolved exactly the way `/dashboard` resolves it (see that
command's own Step 0): the `CCSTATS_OUT` environment variable if set, otherwise
`~/.cc-warehouse/stats`. Read `$CCSTATS_OUT` first
(`echo "${CCSTATS_OUT:-$HOME/.cc-warehouse/stats}"`) and use that resolved path everywhere - this
is what lets a test run point at a scratch folder without touching the real one.

## Step 1 - refresh the underlying data?

Identical to `/dashboard`'s Step 1 - both pages read the SAME `$OUT/sessions.sqlite`, so if that
command was just run this session there is nothing to refresh again. Check whether
`$OUT/sessions.sqlite` exists and how old it is
(`stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$OUT/sessions.sqlite"` on macOS).

- **Does not exist yet:** explain that `collect.py` (read-only, scans every transcript, about
  22 seconds) has to run once first, and run it. Not optional the first time - do not ask.
- **Exists:** tell the operator its age, then ask (yes/no, unless the mode already decided it)
  whether to refresh it now: `uv run python3 tools/ccstats/collect.py`. If they say no, use the
  existing file as-is.

## Step 2 - the project-exclude list (shared with /dashboard, read-only here)

`daywall.py` reads the SAME `$OUT/dashboard-defaults.json` `/dashboard` writes (one saved list,
one source of truth for "which projects start unticked" on both pages) - `daywall.build_daywall_
payload` falls back to it automatically whenever no `--include`/`--exclude` flag is given, the
identical mechanism `dashboard.py` uses.

- **File exists:** nothing to do here - it will be picked up automatically in Step 3. Mention its
  current `exclude` count to the operator in passing if you already know it, but do not re-ask.
- **File does not exist yet:** this command does NOT create or edit it (that stays `/dashboard`'s
  job, so there is exactly one place that prompt lives). Say so, and offer to run `/dashboard`
  first if the operator wants a curated starting list - otherwise every project simply starts
  ticked, which is a fine default for this page.

## Step 3 - build

From the repo root, no flags needed (the saved defaults, if any, are picked up automatically):
```
uv run python3 tools/ccstats/daywall.py
```
Do not pass `--since`/`--until` unless the operator has separately asked to shrink the embedded
range - the page's own date pickers already narrow what's shown without a rebuild.

Report the exact line the script prints on success (output path, byte size, session count,
window). If it is meaningfully larger than the last time this ran, say so - nothing here should
grow silently.

## Step 4 - serve it once

Same reasoning as `/dashboard`'s Step 4 (the browser tool refuses `file://`); use a DIFFERENT
port so the two pages can be served side by side if both are open:
```
uv run python3 -m http.server 8741 --bind 127.0.0.1 --directory "$OUT"
```
Run this with `run_in_background: true`. If port 8741 is already taken, try 8742, then 8743.

Give the operator the exact link: `http://127.0.0.1:<port>/claude-code-daywall.html`

Mention once, briefly, that a browser without WebGL2 gets a plain-text fallback naming
`claude-code-dashboard-live.html` as the 2D alternative - not a blank page.

## Step 5 - stop the server

Identical to `/dashboard`'s Step 5: ask the operator to confirm they have opened the page and are
done with it for now, then stop the background server process. The file is fully self-contained
once loaded, so this never breaks an already-open tab. Wait and ask again rather than killing it
under them if they want it open longer.

## Never

- Never commit `~/.cc-warehouse/stats/` or anything inside it - not the daywall HTML, not the
  shared `dashboard-defaults.json`.
- Never upload the built HTML via the Artifact tool or any other external host.
- Never set `CCSTATS_OUT` (or otherwise resolve `$OUT`) to somewhere inside this repo, `~/.claude`,
  the archive, or the warehouse data root - `resolve_out` already refuses those; do not attempt to
  work around a refusal.
- Never write to `dashboard-defaults.json` from this command - that file is `/dashboard`'s to own.
