# Panel contract for `dashboard_template.html`

Read this file plus ONE example panel before editing or adding a panel. You should not
need to read the rest of `dashboard_template.html`'s 1,170 lines to do either.

This file documents the ~55% of `dashboard_template.html` that is shared machinery
(palette, SVG chart primitives, filter wiring). That part is already factored into
functions called once each - there is little to extract further. The ~45% that is
NOT covered here is the panel bodies themselves (20 of them, ~470 lines): each mixes
bespoke aggregation logic with bespoke caption wording, and is inherently one-off. This
doc will not make that part shorter; it exists so you can find the shared pieces fast
instead of re-reading them each time.

## What a panel is

Every panel is one call to `panel(id, title, opt, renderFn)`, made at the top level of
the `<script>` block (search for `panel("`). Calling `panel(...)` pushes `{id, title,
opt, render}` onto the module-level `PANELS` array as a side effect - there is no
separate registration step. **Panels render top to bottom in the order they are
called in the file.** To add a panel, add a new `panel(...)` call near the others; to
reorder panels, move the call.

`renderFn` takes no arguments and must return `{ eyebrow, body }`:

- `eyebrow`: a short HTML string shown above the title (usually a count, e.g.
  `` `<span class="num">${n}</span> active days` ``).
- `body`: the panel's HTML content, usually `` `<figure class="chart">${chartHtml}</figure>` ``
  from one of the chart helpers below, or a `table(...)` call, or `emptyNote()`.

`renderAll()` (the only caller of `renderFn`) wraps each call in try/catch - a thrown
error becomes a red "This panel failed to draw" note in place of that one panel, and
does not break the rest of the page. Still guard against empty input yourself (see the
`if (!dates.length) return { eyebrow: "0 days", body: emptyNote() };` pattern in every
panel below) - an uncaught exception is caught, but an empty chart with a divide-by-zero
NaN in it is not, and will render silently wrong instead of failing loud.

## The data you have inside `renderFn`

- **`DATA`**: the whole embedded payload (see `dashboard.py`'s `build_payload()` for
  the Python side). Built once at file-generation time; never mutated in the browser.
- **`FS`**: the CURRENTLY FILTERED session rows (an array of `DATA.S` rows), recomputed
  by `recomputeFilteredSessions()` every time the date range or project checklist
  changes. **Use `FS`, not `DATA.S`, unless your panel is deliberately whole-corpus**
  (see "Whole-corpus panels" below) - reading `DATA.S` directly silently ignores both
  filters.
- **`IDX.<table>.<column>`**: numeric column index for a named field, e.g.
  `IDX.S.date`, `IDX.S.engagedSec`, `IDX.S.project`. Rows are plain arrays (not
  objects) for embed-size reasons, so every field read goes through `IDX`, never a
  hardcoded number.
- **`LK`**: lookup tables (`LK.projects`, `LK.repos`, `LK.models`, `LK.ccversions`,
  `LK.tools`, `LK.attrKinds`) - a session row stores an INDEX into these, e.g.
  `LK.projects[row[IDX.S.project]]` gives the real `project_label` string.
- **`state`**: `{ from, to, excluded }` - the reader's current filter bar values. You
  should not normally read this directly; `FS` already reflects it.

### `S` row columns (one row per session), in order

```
date, hour, weekday, project, repo, worktree, engagedSec, cost, tokIn, tokOut,
tokCacheWrite, tokCacheRead, tokThinking, ccVersion, model, wallSec, activeSec,
prompts, toolUses, turns
```

Other tables, keyed the same way (`IDX.M`, `IDX.T`, `IDX.A`, `IDX.O`):

- **`M`** (per session-model breakdown): `session, model, cost, tokIn, tokOut, tokCacheWrite, tokCacheRead, tokThinking`
- **`T`** (per session-tool breakdown): `session, tool, count, errors`
- **`A`** (per session skill/agent/mcp attribution): `session, kind, name, count`
- **`O`** (`overlap_day`, whole-corpus concurrency, one row per calendar day):
  `date, sessionsActive, sessionsStarted, summedHours, elapsedHours, concurrency, maxConcurrent`

The source of truth for this list is `dashboard.py`'s `payload["cols"]` - if the two
ever disagree, `dashboard.py` is right and this doc is stale.

## Drawing helpers (call, don't reimplement)

- `barChart(items, opt)` - vertical bars, one value per category. `items`:
  `{label, value, sub?, flag?, color?, title?, hatch?}`. Used by Daily/Weekly/Sizes/Tokens.
- `hbarChart(items, opt)` - horizontal ranked bars (label left, bar+value right). Used
  by Projects/Repositories/Models/Tools/Skills. `opt.log: true` for a log scale.
- `heatmap(rowLabels, colLabels, matrix, opt)` - grid, cell shade = value. Used by the
  hour-of-day and project-by-month panels. Pass `opt.cellW` explicitly if your column
  labels are wider than ~2 characters (see the comment at its call site for why - a
  narrow natural width gets stretched by the browser and blows up your font sizes too).
- `stackedBar(xLabels, series, opt)` - stacked bars, `series`: `{label, color, values[]}`.
  Used only by Model x month today.
- `table(columns, rows)` - plain HTML table. `columns`: `{label, num?}`.
- `legend(series)`, `emptyNote()` - self-explanatory from call sites.
- Every chart mark carries a `data-tip` attribute (not a native SVG `<title>`, which
  is slow and unstyled) - build a real string for it, don't skip it.

## Formatting helpers

`fmtHours`, `fmtUSD` (compact, `k` suffix over 1000), `fmtUSDFull` (Overview tiles
only - full thousands separators, no suffix), `fmtInt`, `fmtTok` (token counts, `k`/`M`/`B`),
`fmtHoursPrecise` (Overview tiles only). Always `esc()` any string built from real data
(project names, tool names) before it goes into HTML - these come straight from the
warehouse and are not sanitized upstream.

## House rules (from `CHART-BRIEF.md`, apply to every panel you touch)

1. **`engaged_hours`, not `active_hours`**, unless the panel is explicitly labelled
   otherwise (the Overview KPI tiles show both, clearly distinguished).
2. **Timezone**: any hour-of-day panel must print the timezone
   (`` `${esc(DATA.timezone)}` ``, Melbourne, from cc-warehouse's own config) next to
   the chart, not just in this doc.
3. **`project_label` vs `repo_root` are different keys** - a panel using one must say
   which, since they group differently (repo_root folds subdirectories into a parent;
   project_label does not).
4. **Partial ranges/months must say so on the chart itself** (a flag, hatch, or
   caption), not only in prose here.
5. **Cost is not a bill.** Any cost-primary panel needs that disclaimer visible on the
   panel, not just in the README.
6. **`US$ ` with a trailing space**, everywhere a dollar figure is formatted (both
   `fmt*` functions already do this - don't hand-build a dollar string elsewhere).
7. Fold `.claude/worktrees/agent-<hex>` throwaway folders into their parent project
   with `canonicalProjectName()` in any panel that GROUPS by project (only "Projects"
   and "Where the work moved" do this today) - real named worktrees and genuine
   sub-repos are left alone. Group by model FAMILY with `modelFamily()`, not exact
   model string, in any panel that groups by model.

## Whole-corpus panels (deliberately ignore one or both filters)

A few panels can't be sliced by the project checklist and say so on the panel:
Concurrency (`O` table, real interval-overlap math, date-range only) and two Overview
tiles (`time with a session open`, `most sessions running at once` - same reason). If
you add a panel with the same constraint, read `FS` for the date range but `DATA.S` (or
`DATA.O`) for anything the project filter can't narrow, and say so in the panel's `lede`
or body text, the way those do.

## Annotated example: the "Daily" panel

```js
/* ---- 02 Daily ---- */
panel("daily", "Engaged hours per day", {
  lede: "One bar per active day in your range. Sessions run in parallel on this "
      + "machine, so daily hours can exceed 24 -- that is correct, not a bug."
}, () => {
  const byDate = new Map();
  FS.forEach(r => {                                    // FS: respects both filters
    const d = r[IDX.S.date];
    const e = byDate.get(d) || { hours: 0, sessions: 0 };
    e.hours += r[IDX.S.engagedSec] / 3600; e.sessions += 1;  // engaged_hours, house rule 1
    byDate.set(d, e);
  });
  const dates = [...byDate.keys()].sort();
  if (!dates.length) return { eyebrow: "0 days", body: emptyNote() };  // guard empty input
  const items = dates.map(d => ({
    label: d.slice(5), value: byDate.get(d).hours, sub: byDate.get(d).sessions + " sess",
    title: `${d} · ${byDate.get(d).hours.toFixed(1)}h engaged · ${byDate.get(d).sessions} sessions`,
  }));
  const html = barChart(items, { valueFmt: fmtHours, barGap: 40, height: 340 });
  return { eyebrow: `<span class="num">${dates.length}</span> active days`,
    body: `<figure class="chart">${html}</figure>` };
});
```

This is the whole shape: filter with `FS`, aggregate with a `Map`, guard the empty
case, build `items`/rows for a helper, return `{eyebrow, body}`. Most panels in the
file are this pattern with different aggregation logic in the middle.

## What this doc deliberately does not cover

The 20 panels' individual aggregation logic and caption wording - that's the editorial
45% mentioned at the top, and it's genuinely one-off per panel. Read the panel itself
for that, using this doc to skip everything around it.
