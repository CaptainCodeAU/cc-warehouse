# Opening prompt for a fresh session, 2026-08-24 (seventeenth handoff: ticket
# 28.9 Fix B is DONE - the whole ticket is now closed, both mechanisms fixed
# and both tested per the operator's real-browser bar. Full account: "FIX B
# DONE 2026-08-24" inside "ACTIVE TASK: ticket 28.9" below, and
# harness/tickets/28-backlog.md's 28.9 entry. **CORRECTED 2026-08-27: this
# line used to say "NOT YET COMMITTED" - false by the time an eighteenth-
# handoff session checked `git log` for an unrelated reason. It was already
# committed as `7842549` before that session even started.)

## Next task: **ticket 28.9 is now FULLY DONE (both Fix A and Fix B, each
## built and tested per the operator's real-browser bar) - it is no longer
## the next task.** The operator picked server-side reuse for Fix B (over
## client-side reconstruction) via a 2-option table; the change eliminates a
## real duplicate-computation bug (a block's markdown was independently
## re-derived up to five times across row/phase/turn/whole-transcript/header
## passes) with a plain id-keyed memoization cache, proved byte-identical
## before/after on a real 9.7 MB session and proved correct in a real Chrome
## tab (2,013 of 2,013 copy-payload DOM elements matched their transcript.md
## fragment). Read "ACTIVE TASK: ticket 28.9" below for the full account
## before assuming anything about `render.py`'s copy-payload machinery -
## `_render_block` is no longer the whole story, `_render_block_uncached` is.
## **The standing next candidates, none picked yet, are ticket 28's other
## backlog items (28.2, 28.10, 28.11, 28.12, 28.14) and `ccw share --open` as
## a possible fast follow-up to 28.1** - see "Also on record, not scheduled"
## near the end of this file. Ask the operator which to pick up, or whether
## something else has come up since. Nothing in items 1-7, ticket 28.22,
## ticket 30's flagged defect, ticket 28.13, ticket 24.7, ticket 28.19, ticket
## 28.1, or ticket 28.3 is open work either - see the eleventh through
## fourteenth handoff entries at the end of this file for those accounts.
## **The fifteenth, sixteenth and eighteenth handoffs' own accounts, at the
## very end of this file, are also worth reading** - the fifteenth fixed two
## real, live production bugs in `archive.py` and `sweep.py`; the sixteenth
## fixed four real data-correctness bugs in `tools/ccstats` (a sub-agent
## double count and three others) that made the live dashboard's numbers
## wrong by anywhere from 20% to 96x; the eighteenth (2026-08-27) split the
## live dashboard's sub-agent handling from one page-wide toggle into a
## per-panel rule (cost/token/tool panels always count sub-agent runs, hours/
## session panels never do) and fixed a layout gap + an always-visible note
## in the filter bar. Any future session touching capture, sweep, archive, or
## ccstats should know about all three before assuming those paths behave the
## way older parts of this file describe.

## ACTIVE TASK: ticket 28.9, cut `conversation.html`'s memory cost

**Where this stands, 2026-08-24 (updated)**: investigated end-to-end with real, reproduced
measurements (not guesses), then Fix A was BUILT and TESTED, in a fresh session, exactly as
planned - see "FIX A DONE 2026-08-24" below for the full account. **Fix B has NOT been built.**
The operator's original ask was two separate steps done one at a time, each tested for real in a
browser via `claude-in-chrome`, not just `pytest` - Fix A satisfied that bar; Fix B still needs
to. Read this whole section, including the Fix A account, before touching any code: Fix B's plan
(step 3 below) assumes the reader knows what Fix A already changed.

**The ticket**: `harness/tickets/28-backlog.md`'s "28.9" entry. Original note (undated
precisely, from the 2026-08-03/04 backlog investigation): "`render_html` costs 74x the payload
and emits about 6.3x its size (a 100 MB session projects to a 633 MB page, 7.26 GiB peak).
Latent: the largest real page is 17.7 MiB." **That 74x/633MB/7.26GiB figure was NEVER
independently re-verified at that scale this session** - only a smaller synthetic case (below)
was actually measured. Treat the 100 MB/7.26 GiB numbers as historical, not re-confirmed.

**What was actually measured, twice, independently, same result both times** (once by a forked
sub-agent, once by the primary session re-running the SAME script cold, matching to the KiB).
Synthetic payload: 40 turns, each with a Bash `tool_use` + a 20 KB `tool_result` (shape matches
`tests/conftest.py`'s `entry()`/`jsonl()` helpers), built and measured with `tracemalloc`:

| metric | value |
|---|---|
| input payload | 1,679,860 B (1.60 MiB) |
| `conversation.html` (full) output | 5,391,271 B (5.14 MiB) |
| `conversation.compact.html` output | 76,601 B (0.07 MiB) |
| wall time for `render_html()` | ~0.54 s |
| traced peak (tracemalloc) | 61.16 MiB |
| **peak / input ratio** | **38.18x** |

Stage-isolated peaks (same payload, each stage measured alone): `build_conversation` 6.62 MiB
(parser overhead, transient, not the problem); `_render` (plain markdown) peak 6.51 MiB for a
0.80 MiB output (~8x, same underlying cause as below); **`_render_page` FULL variant: peak
59.51 MiB to produce a 5.14 MiB string - effectively the entire run's peak**; `_render_page`
COMPACT variant: peak only 0.77 MiB (compact strips tool output by default, so it has far less
content to duplicate at each copy-button level - see below - which is itself confirming
evidence for the mechanism).

**Reproduction scripts are saved at `temp/ticket-28.9-render-perf/`** (this repo, gitignored,
NOT the session scratchpad, which does not survive into a new session): `profile_render.py`
(whole `render_html`, tracemalloc + timing, the numbers above), `profile_render_stages.py`
(isolates `build_conversation` / `_render` / `_render_page` full vs compact), `profile_render_dup.py`
(confirms the duplication mechanism with a base64 substring probe). Run with `uv run python3
temp/ticket-28.9-render-perf/profile_render.py` from the repo root; each edits `sys.path`
itself and needs no other setup.

**TWO DISTINCT, INDEPENDENT MECHANISMS were found, and the plan below treats them as two
separate fixes on purpose - they have very different risk profiles:**

**Mechanism 1 (Fix A target): an emoji forces the WHOLE final HTML string into 4-byte-per-char
storage.** Confirmed with a tiny, fully isolated repro (not part of the scratch scripts above,
run it fresh if you want to re-see it):

```
uv run python3 -c "
import sys
print(sys.getsizeof('x'*999999 + chr(0x1F50C)))   # one astral-plane char -> 4,000,060 bytes
print(sys.getsizeof('x'*1000000))                  # pure ASCII        -> 1,000,041 bytes
"
```

CPython's compact-string representation stores an ENTIRE string at 4 bytes per character the
moment it contains even ONE character outside the Basic Multilingual Plane (code point >
0xFFFF, e.g. most emoji). `src/cc_warehouse/render.py` uses 23 different `\N{...}` named-emoji
escapes as UI icons; **15 of them are astral-plane** (confirmed by looking each one up):
`BELL`, `BOOKMARK TABS`, `BUST IN SILHOUETTE`, `CLIPBOARD`, `ELECTRIC PLUG`, `GLOBE WITH
MERIDIANS`, `JIGSAW PUZZLE PIECE`, `LEFT-POINTING MAGNIFYING GLASS`, `LINK SYMBOL`,
`MICROSCOPE`, `OCTAGONAL SIGN`, `PAPERCLIP`, `ROBOT FACE`, `THOUGHT BALLOON`, `WRENCH`.
`WRENCH` (U+1F527) is `_row_icon`'s DEFAULT fallback for any unmapped tool-block kind (grep
`_ROW_ICONS.get(block.kind, "\N{WRENCH}")`), so almost every real page with any tool call
trips this. Measured effect on the 1.60 MiB payload above: the single largest retained
allocation in the whole run is `render.py:2184` (`"\n".join(parts) + "\n"`, confirm the exact
line by grepping - it may have moved), **20.6 MiB retained for what ends up as a 5.14 MiB
UTF-8-encoded string** - a ~4x inflation matching the astral-plane mechanism exactly. Fixing
just this (see Fix A below) should save roughly 15 MiB of the 59.5 MiB peak on this payload,
i.e. cut the peak/input ratio from ~38x toward roughly ~27x, PURELY from this one mechanism -
not the full win, but a real, well-understood, zero-risk chunk of it.

**Mechanism 2 (Fix B target): the page's per-block "copy as markdown" buttons pre-bake a
separate base64 copy at FOUR nested levels.** Confirmed by reading the code, not just
inferred: `render.py` computes and `base64.b64encode()`s a `fragment` string independently at
each of these sites (grep to confirm current line numbers, they will drift):
- row / block level, inside `_phase_html` (`payload = base64.b64encode(fragment...)`, the row's
  own block content)
- phase level, inside `_phase_html` (a SEPARATE `fragment` covering every row already counted
  above, base64'd again)
- turn/section level, inside `_section_html` (a SEPARATE `fragment` covering the whole turn -
  every phase and row inside it, counted twice already, base64'd a third time)
- whole-transcript level, inside `_render_page` (`whole = _render(...)`, the entire document,
  base64'd a fourth time, as one big blob rather than once per block)

Each level's `fragment` is a SUPERSET of the levels nested inside it, so real transcript
content that is N levels deep ends up base64-encoded roughly N+1 times, all held in the same
`parts` list simultaneously before the final join. This is BY DESIGN, not a bug: every copy
button, at every granularity, needs its own ready-to-click payload. **This is a genuinely
tested, locked contract guarantee, not just a convention**: `contract/DESIGN.md` section 6,
line ~158, "copy-as-markdown payloads equal the transcript.md fragments byte for byte", proven
by `tests/test_render_html.py::test_copy_as_markdown_payloads_equal_transcript_fragments`
(read it before touching this - it asserts every `data-copy-src` payload, base64-decoded, is a
substring of the FULL `transcript.md` text; loose enough that a correctly-reconstructed
fragment - built by concatenating the SAME already-existing smaller fragments in the SAME
order - should still satisfy it, but this needs PROVING against the real test, not assumed).

**THE OPERATOR-APPROVED PLAN, in this exact order, ALL of it in a fresh session:**

1. **Fix A**: stop the astral-plane emoji from inflating the WHOLE final HTML string. The
   clean shape (confirm by reading `build.py`'s `iter_projection_files` first): `render_html`
   and `render_markdown` currently return `str`, and BOTH of `build.py`'s call sites
   immediately do `.encode("utf-8")` on the result anyway. Building the `parts` list (and the
   equivalent in `_render`/`render_markdown`) as UTF-8 BYTES per-fragment and joining with
   `b"\n".join(...)` avoids ever materializing one giant wide-char Python `str` - each small
   fragment stays cheap even if it individually contains an emoji, because the 4x penalty only
   applies to the ONE STRING that touches the emoji, not to everything concatenated with it
   later once it's already bytes. This is very likely a real, if moderate-sized, refactor
   (dozens of `.append`/`.extend` call sites across a 2,296-line file), NOT a one-line patch -
   scope it properly before diving in. **Zero visible/functional change is the whole point**:
   same emoji, same HTML, same bytes on disk, same everything a reader sees or copies - only
   HOW the bytes get built changes. If `render_html`/`render_markdown`'s public return type
   changes from `str` to `bytes`, update every caller (`build.py`'s two `iter_projection_files`
   call sites, and any test that currently asserts against a `str` return - there are several,
   e.g. `tests/test_render_html.py`, `tests/test_render_markdown.py` if it exists, grep first).
2. **Test Fix A for real**, per the operator's explicit requirement:
   - `uv run pytest`, `uv run ruff check`, `uv run pyright` all green (the usual gates).
   - Re-run `temp/ticket-28.9-render-perf/profile_render.py` and confirm the peak actually
     dropped, roughly in line with the ~15 MiB / ~26% estimate above - if it did not move
     noticeably, the fix did not land where expected and needs re-diagnosis before moving on.
   - **`claude-in-chrome`, a REAL browser tab, on a REAL generated `conversation.html`.**
     `file://` URLs are refused by the navigate tool (see "Two environment facts" below in
     this file) - serve the directory locally first: `uv run python3 -m http.server <port>
     --bind 127.0.0.1` from the folder holding the generated HTML, then navigate to
     `http://127.0.0.1:<port>/conversation.html`. Check: the page loads with zero console
     errors (`read_console_messages`), looks visually identical to a pre-fix render (same
     icons, same layout - Fix A must not change a single visible pixel), and EVERY copy
     button (row, phase, turn, whole-transcript) still works and copies text. Kill the server
     after.
3. **Only after Fix A is confirmed working, move to Fix B**: reduce the actual N-level base64
   duplication from Mechanism 2. This is the RISKIER half - it touches the DESIGN section 6
   contract guarantee above. Two shapes exist, genuinely different risk (pick one and say why,
   or ask, per this project's own house style - do not default to whichever is less code):
   - **Server-side reuse**: build the phase/turn/whole-transcript `fragment` strings by
     concatenating the SAME already-built row-level fragment strings (in the same order
     `_phase_md`/the turn markdown builder already uses), instead of re-deriving them from a
     separate pass - saves the DUPLICATE COMPUTATION, and likely also memory since fewer
     distinct large strings exist, but the coarser levels are still pre-baked and shipped in
     the HTML (page weight is roughly unchanged, only the redundant intermediate work is cut).
   - **Client-side reconstruction**: ship ONLY the row-level (finest-grained) `data-copy-src`
     payloads server-side; have the phase/turn/whole-transcript copy buttons' JS handler
     (`_copy_script`, grep for it) walk the DOM at CLICK TIME and concatenate the child
     fragments it finds, instead of reading a pre-baked attribute. This is the bigger win on
     PAGE WEIGHT (not just build-time memory) but is the more invasive change and the one that
     most directly needs `test_copy_as_markdown_payloads_equal_transcript_fragments` to keep
     passing UNCHANGED (or, if the operator agrees the test's own wording should adjust, that
     is a contract edit and needs the operator's explicit word first, same as ticket 27.8's
     `keep_objects` decision did - never just relax a locked oracle test to make a perf fix
     pass, per this project's own "contract fences: narrow, never dodge" rule).
   Either shape: the output a reader sees and can copy must remain byte-identical to what it
   is today. That is the property to protect, not a specific implementation.
4. **Test Fix B for real**, same three-part bar as step 2 (gates green, re-profile, real
   Chrome tab) PLUS one more check that step 2 did not need: click every level of copy button
   in the real browser tab, read the clipboard content back (or read the DOM/console to confirm
   what was copied), and confirm it still matches the corresponding `transcript.md` fragment
   byte for byte - this is the step that actually proves the contract guarantee survived, not
   just that pytest still passes.

**Do not skip straight to Fix B, and do not consider either fix "done" on `pytest` alone** -
both of those were the operator's explicit instructions, given after they asked "what does the
fix change, does it change functionality" and were told Fix A is a pure invisible optimization
while Fix B is designed to look the same but touches a locked guarantee and needs real proof,
not just a green test suite.

**FIX A DONE 2026-08-24, FIX B NOT STARTED.** `_render`/`_render_page` in `render.py` now
encode each fragment to UTF-8 bytes before the final join instead of joining `str` first;
`render_markdown`/`render_html` return `tuple[bytes, bytes]` (were `tuple[str, str]`); `build.py`
simplified to match; ~40 test call sites across 10 files updated to decode at point of use, no
assertion logic changed. All three gates green (1,175 tests, ruff clean, pyright 0 errors).
Output proved byte-identical before/after on BOTH the synthetic repro and a real 8.3 MB session
from this machine (`cmp` via `git stash`). Peak memory on the synthetic repro: 61.16 MiB -> 28.00
MiB (38.18x -> 17.48x of input), beating the ~26 MiB estimate because the fix reached both
`_render` and `_render_page`. Real-browser check done (not skipped): the real session's
`conversation.html` served over loopback and opened in an actual Chrome tab via
`claude-in-chrome` - zero console errors, and all four copy-button levels (row/phase/turn/whole)
clicked with clipboard content read back programmatically: the whole-transcript copy is
character-identical to `transcript.md` (545,316 chars), the finer levels are each a substring of
it, matching the locked `test_copy_as_markdown_payloads_equal_transcript_fragments` guarantee.
Full account and exact numbers: `harness/tickets/28-backlog.md`'s 28.9 entry.

**FIX B DONE 2026-08-24.** The operator picked server-side reuse (over client-side
reconstruction) via a 2-option table when asked directly. Root cause turned out to be broader
than the ticket's own four-level framing: each level (row, phase, turn, whole-transcript) - plus
a FIFTH pass this investigation found, `_claude_turn_count` (the header's "N you / M Claude"
split, which called `_claude_md` per turn just to test truthiness) - independently re-derived
its own markdown fragment from scratch via a fresh call chain into `_render_block`, so a block
already rendered once at row level got rendered again up to four more times. Fix: a plain
`dict[(id(block), policy) -> list[str]]` cache (`_BlockCache`), created once per `_render_page`
call and threaded as a REQUIRED parameter (no default, so a missed call site is a pyright error,
not a silent loss of caching - this caught the fifth pass, `_claude_turn_count`, before it
shipped half-fixed) through 13 functions between it and `_render_block`. `_render_block` itself
is now a thin cache-check wrapper; the old body moved verbatim to `_render_block_uncached`, so
the rendering LOGIC is byte-for-byte unchanged, only WHEN it runs changed.

Verified, not assumed: full suite 1,198 passed (up from 1,197 on `master` at session start - the
"1,175" Fix A recorded is stale, 22 unrelated tests landed since, confirmed via `git stash`),
ruff clean, pyright 0 project errors. Output proved BYTE-IDENTICAL before/after on a real 9.7 MB
session (`cmp` on all four projection files, `git stash`/`stash pop`). Isolated to Fix B alone
(holding Fix A constant via `git stash`), wall time on the ticket's synthetic repro dropped ~31%
(0.511s -> 0.350s); peak memory stayed flat (28.00 -> 28.03 MiB, noise-level) - exactly as
predicted for this shape, since server-side reuse cuts redundant CPU/allocation work, not the
final page weight (only the unchosen client-side-reconstruction shape would have done that). A
new test, `test_render_block_is_memoized_across_copy_levels`
(`tests/test_render_html.py`), pins the cache's own invariant (no `(block, policy)` pair computed
twice) rather than only the byte-equality the existing locked test already covers; confirmed it
actually catches a regression by manually bypassing the cache in a throwaway script, which
reproduced up to 10 calls for a single block.

Real-browser check done per the operator's explicit requirement, and went further than Fix A's
own check: the real session's `conversation.html` served over loopback and opened in a real
Chrome tab via `claude-in-chrome` - zero console errors on load and after every interaction.
Reading the system clipboard triggered an OS permission prompt that froze one `javascript_tool`
call (worked around by not retrying it, per the dialog-avoidance rule in this file's own
system prompt); verification instead read the DOM directly, which the operator-approved plan's
own step 4 explicitly allows as an alternative to a literal clipboard read. EVERY
`[data-copy-src]` element on the real rendered page - 2,013 of them, covering all four levels
(1,477 row/block, 509 phase, 24 turn, 1 whole-transcript) plus the header meta and files index -
was base64-decoded and confirmed to be a substring of the real `transcript.md` fetched from the
same server: 2,013 of 2,013 passing, the same guarantee
`test_copy_as_markdown_payloads_equal_transcript_fragments` checks, now proven against a live
browser-rendered page. Real clicks on the whole-transcript, row-level and phase-level copy
buttons produced zero console errors.

**Not yet committed as of writing this paragraph** - `src/cc_warehouse/render.py`,
`tests/test_render_html.py`, `harness/tickets/28-backlog.md`, and this file are all modified in
the working tree. Full account and exact numbers: `harness/tickets/28-backlog.md`'s 28.9 entry.

### One loose end inside item 2, not urgent, not blocking

The prior session's second open thread (deterministic generation of
`dashboard_template.html`) WAS investigated this session, by a sub-agent, in
depth as asked. Measured, not guessed: the file is 1,118 lines / 59,228
bytes, ~55% mechanical (CSS palette, SVG/JS chart primitives, effects/
controls wiring - already factored into shared functions, called once each,
so there is little duplicated boilerplate left to extract) and ~45%
editorial (the 20 panel definitions, 469 lines, each mixing bespoke
aggregation logic with bespoke caption wording - inherently not scriptable).

The sub-agent's recommendation was NOT a codegen script. It was: write a
short "panel contract" doc so a future edit reads that doc plus one example
panel, instead of the whole 1,118-line file - the real cost driver is
context size, not duplicated code, and a small CSS-palette codegen would
save little (15 lines, rarely edited).

This was put to the operator as a 2-option decision (write the doc now /
skip). **The operator never picked either option** - the conversation moved
straight into giving the `--include`/`--exclude` list instead, and it was
never revisited across the rest of the session despite four more rounds of
dashboard work landing on the exact file this would apply to. Nothing was
written. Ask the operator before doing anything here; do not assume "yes"
just because the file has since had six more rounds of hand-edits that a
panel-rules doc would have made cheaper.

**RESOLVED 2026-08-23: the operator said "write it now."** Written as
`tools/ccstats/PANEL-CONTRACT.md` - the data model (`DATA`/`IDX`/`LK`/`FS`/
`state`), every chart/format helper, the `CHART-BRIEF.md` house rules
restated as a checklist, one fully annotated example panel (Daily), and a
one-line pointer added from `tools/ccstats/README.md`'s "The live dashboard"
section so it is actually findable. Nothing in `dashboard_template.html`
itself changed. This loose end is CLOSED; do not re-ask it.

---

## The order, with the reasoning

### 1. Protect `temp/ccstats/` and stop its disk leak - DONE 2026-08-21

**Correction, found while doing this**: the handover line above said "136 MB
left behind per run". It was not per run: `Path.replace()` overwrote the same
`.prev` every time, so exactly one stale copy existed at any moment (measured:
`sessions.sqlite` 143,695,872 bytes, `.prev` 143,646,720 bytes, one of each).
The defect was a permanent doubling of a 137 MB file, not a growing pile.

Two operator rulings taken this session:

- **Code -> `tools/ccstats/`.** Tracked, outside `src/`, no contract ruling
  needed. `src/cc_warehouse/` as a `ccw stats` verb is still open, blocked on
  the `contract/BRAINSTORM.md` warehouse-vs-`cc-vantage` line; NOT attempted.
- **Generated files -> `~/.cc-warehouse/stats/`**, outside the repo and
  untracked, overridable with a new `--out DIR` flag (or `CCSTATS_OUT` env).
  **`~/cc-warehouse-stats/` (the old location, 373 MB including the old
  `.prev`) was explicitly left alone during this work.** The operator then
  deleted it themselves later the same session, once `CHART-BRIEF.md` (the
  one file only that folder held that the new one did not) was moved across
  by hand. **`~/cc-warehouse-stats/` no longer exists; confirmed gone
  2026-08-21.** `~/.cc-warehouse/stats/` is now the only copy and holds all 20
  files, `CHART-BRIEF.md` included.

What changed: `temp/ccstats/` -> `tools/ccstats/`, committed. `common.py` gained
`resolve_out`/`Out`, replacing 5 copies of a hardcoded `OUT_DIR` with one
resolution, fenced against `~/.claude`, the archive, the warehouse data root
and this repo (refuses loudly, like `parse_since` does for a bad date).
`collect.py`'s `.prev` rename is gone, replaced by `tempfile.mkstemp` +
`os.replace` (DESIGN R2's own idiom): the live database is only ever replaced
by a complete build, a crash mid-build can no longer corrupt it, and a leftover
`*.building` file is reported (`collect-report.json` -> `stale_building_files`)
rather than auto-deleted. `pyproject.toml` and `tests/test_packaging.py` both
gained `tools` in their exclude/`FORBIDDEN_DIRS` lists, keeping the sdist clean
(verified by building a real sdist: `tools` absent from its 162 members).

Verified: all three gates green (ruff, pyright, 1,112-test oracle suite,
including `test_packaging.py`); the ccstats suite grew from 72 to 86 tests (one
per new behaviour) and passes; a full real-data run (`verify.py snapshot` ->
`collect.py` -> `build_workbook.py --since 2026-06-08` -> `make_docs.py` ->
`check_consistency.py` -> `verify.py compare`) landed in `~/.cc-warehouse/stats/`
with 0 problems, `check_consistency.py` reporting all 14 shared figures
consistent; a second `collect.py` run left exactly one `sessions.sqlite` and no
`.prev`/`.building` file, anywhere; `--out` writes to an arbitrary directory and
is refused for `~/.claude`.

### 2. Build an interactive stats dashboard - DONE, CLOSED 2026-08-22

**Both threads this file used to hand to "the next session" are now
resolved.** The `--include`/`--exclude` list was given and applied (see
below). The codegen investigation ran and its outcome is the loose-end note
at the very top of this file. Everything below this line, through "Fourth
round", is history kept intact rather than rewritten; skip to "Fourth round"
for what actually changed most recently.

The operator wants a browser dashboard, like the one already sitting at
`~/.cc-warehouse/stats/claude-code-dashboard.html`, but with two live controls:
a date range (start AND end) and a list of projects to EXCLUDE. "How you build
it is up to you" - the operator's own words - but being able to change the
range and the exclude-list themselves, without asking anyone to re-run
anything, is the actual ask, so treat "if possible" as "strongly preferred",
not as optional.

**What the existing dashboard actually is, measured, not guessed:**

- 270 KB, one file, no external assets. 19 `<svg>` charts, 1 `<table>`, and
  exactly one `<script>` block - and that block is ~250 bytes of scroll-reveal
  animation (`IntersectionObserver`), nothing to do with data.
- It carries **no embedded JSON, no chart library, no client-side filtering at
  all.** Every chart is a static SVG baked once, at generation time, for one
  fixed window (its `<title>` literally says "Claude Code usage - 2026-06-08
  to 2026-08-21").
- **Nothing in this repo built it.** It was built by Claude Chat for Web
  (claude.ai), reading three files by hand: `claude-code-stats.xlsx`,
  `DATA-GUIDE.md`, `sessions-real.csv`. `CHART-BRIEF.md` (moved into
  `~/.cc-warehouse/stats/` by the operator this session) is the actual brief
  that was used to build it - **READ IT FIRST.** It carries hard rules that
  must carry over to anything new: chart `engaged_hours` only, never
  `active_hours`; label the cost axis "API list-price equivalent, not billed
  spend"; print the timezone (`Australia/Melbourne`, from cc-warehouse's own
  config, not the machine clock) beside any hour-of-day chart; `project_label`
  (80 rows, what was actually worked in) vs `repo_root` (67 repos,
  subdirectories folded into their parent) are DIFFERENT keys and any panel
  must say which one it uses; both end months of a window are partial and must
  say so on the chart itself, not only in prose.
- That brief's own decision #1 says the current dashboard deliberately has NO
  client-side filtering, because the window was fixed before the data was
  handed over. That decision is exactly what the operator now wants reversed.

**The real gap, and why this is not a copy-paste job:**

A live date range needs BOTH ends. `common.Window` (`tools/ccstats/common.py`)
only has `since`. `--until` does not exist anywhere in `ccstats` yet - it was
already named as missing polish in item 7 below, written before this request
existed. Adding the `until` half to `Window` is very likely a PREREQUISITE
here, not extra scope layered on top.

Project EXCLUSION does not exist in any form. `Window` has never filtered on
`project_label`. This is new, not an extension of something that half-exists.

**The design call to make first, before writing any code:**

Two shapes, genuinely different amounts of work. The operator said "how you
want to do it is up to you" - so the next session should pick one and say why,
or ask, rather than default to whichever is fastest to type:

1. **Regenerate on demand.** A new script (maybe `tools/ccstats/dashboard.py`)
   takes `--since`, `--until`, `--exclude-project NAME` (repeatable) and bakes
   ONE static HTML, same editorial style as today's, for exactly that slice.
   Changing the range means re-running a command. Cheapest, and it is the same
   shape every other ccstats script already uses (`resolve_out`, `Window`, one
   pass over `sessions.sqlite`).
2. **Live in the browser.** Generate once, embed a small aggregate (most
   likely per `local_date` x `project_label`: hours, cost, sessions, tokens -
   NOT full per-session rows, which would run to tens of MB) as JSON in the
   page, and write vanilla JS (no CDN; this project is self-contained by
   habit) that recomputes totals and redraws the SVGs whenever the date
   pickers or the project checklist change. Matches "I want to be able to
   specify..." more literally - it reads as a live control, not a re-run trigger.
   More work: the SVG-drawing logic has to exist in JS too, not only Python.

Recommendation, not a decision made here: **(2).** The operator's own words
were about changing things themselves, which is what "specify" usually means
when someone says it about a UI, not about re-running a script. But this is a
real fork with a real cost difference, so confirm before committing to it.

**Where the data comes from:** `~/.cc-warehouse/stats/sessions.sqlite`, table
`session` (`local_date`, `project_label`, `repo_root`, `engaged_seconds`,
`cost_usd`, the token columns, `is_worktree`, `is_real`; open read-only via
`common.open_ro`, exactly like every other ccstats script). The pre-aggregated
CSVs (`daily.csv`, `projects.csv`, etc.) are already summed over the WHOLE
current window and cannot be re-sliced by excluding one project without
re-querying the database.

**Privacy, non-negotiable:** this file holds real project labels (folder
names) per session - the same thing the existing dashboard already ships, and
the operator already treats as fine to keep local. It must stay a LOCAL file
under `~/.cc-warehouse/stats/`, opened straight from disk in a browser, and
must NEVER be uploaded via the Artifact tool or any other external host: that
folder is explicitly gitignored and "must never be committed" per
`tools/ccstats/README.md`'s own Safety section, and an upload would publish
that same private data externally regardless of who is asked to view it.
**The dashboard's own on-page reminder of this ("this file is private, do not
upload it") was removed 2026-08-22 along with the Caveats panel it lived in -
see "Fourth round" below. The rule itself still applies in full; only the
on-page text is gone.**

**DONE 2026-08-21. Option 2 (live in the browser) was chosen, confirmed with
the operator first via a decision table + AskUserQuestion, per their standing
format preference.** The operator's own follow-up sharpened the ask further:
one filter bar at the TOP of the page, applying to every panel underneath -
explicitly not a per-section control. Built that way.

What shipped: `tools/ccstats/dashboard.py` (new) queries `sessions.sqlite`
directly - `session`, `turn`, `tool_call`, `attribution`, `overlap_day` - and
embeds a compact per-session dataset (row-major arrays against small
project/repo/model/tool lookup tables, never a repeated string per row) into
`tools/ccstats/dashboard_template.html` (new, the CSS/JS shell, reusing the
static dashboard's exact design tokens - paper/ink/signal-red palette, Arial
Narrow + Georgia + monospace, the hatch pattern for partial data) via a
`/*__CCSTATS_DATA_JSON__*/` marker substitution. Output:
`claude-code-dashboard-live.html`, one file, no external assets, no network
calls, no build step. `common.py` gained `--until` (`parse_until`,
`Window.until`, all five `Window` SQL-form properties extended) - the
prerequisite item 7 already flagged; closed here instead of twice.

19 panels, all reading `sessions.sqlite` directly rather than the
pre-aggregated CSVs (which are already summed over one fixed window and
cannot be resliced): Overview, Daily, Weekly, Monthly (partial-month
detection now keys off the READER's chosen range, not a fixed window),
Session sizes, Projects, Repositories, Project x month, Models, Model x
month, Tokens, Thinking, Hour heatmap, By weekday, Tools, Skills & agents,
Worktrees, Top sessions, CC versions, plus a static Caveats panel. CHART-BRIEF
rules carried over and checked by execution, not assumed: engaged_hours only
(never active_hours), the Melbourne timezone label, is_real=1 filtering, the
"cost is not a bill" disclaimer placed ON the four cost-primary charts
themselves (Projects/Repositories/Models/Model x month), not only in prose,
and the 2026-08-12 thinking-token recording-start date stated on that panel.
**CC versions and Caveats were both REMOVED 2026-08-22, see "Fourth round".**

**Scope trims, stated rather than hidden**: Concurrency reads whole-corpus
`overlap_day` (real interval-overlap math, not reconstructable from a
per-session duration) and narrows only by date, not by the project filter -
the panel says so. Worktrees reports counts only, no `worktree_name` list.
Top sessions shows 50, not 200. Every other panel is fully live on both
filters, wired to the one filter bar per the operator's requirement.
**Top sessions is now 25, not 50, and Concurrency's bars are now weekly, not
daily - see "Fourth round".**

**Verified, not just eyeballed**: no browser was available this session
(`mcp__claude-in-chrome` reported "Browser extension is not connected"), so
correctness was proved a different way. `uv run pytest tools/ccstats/tests -q`
- 99 tests (86 prior + 13 new for `--until`), ruff clean. The generated file's
actual `<script>` block was executed HEADLESS under Node (`vm.runInContext`
against a minimal `document` stub) three ways: (1) default full range, 0 of
19 panels threw, KPI totals (9,628 sessions, 1,509.5h, $78,051.13) matched an
independent recomputation done separately from the embedded JSON, not through
the dashboard's own code; (2) a real filtered scenario (July 2026, the
busiest project excluded) also matched an independent recomputation exactly
(1,989 sessions, 275.45h, $18,445.69 both ways); (3) a genuinely empty date
range (2020-01-01..02, 0 sessions) rendered 0 panel errors, the actual risk
case for divide-by-zero on an empty array. What was NOT verified: how it
actually looks and behaves in a real browser (mouse clicks on the project
checklist, the sticky bar's scroll behaviour, visual match to the static
dashboard's spacing) - Node proves the math and that nothing throws, not
pixel rendering. **A real browser WAS available 2026-08-22 and was used
extensively - see "Fourth round".**

Also fixed along the way: `tests/test_ccstats_fences.py::test_no_module_can_
delete_anything` caught a real defect before it shipped - the first draft of
`dashboard.py`'s atomic write called `.unlink()` on its own temp file when a
write failed. Rewritten to match `collect.py`'s own idiom exactly: build into
a `.building` file, one `os.replace`, and on failure leave it for the
operator rather than auto-deleting it. The fence did its job.

**Addendum, same session, two operator follow-ups after seeing the first cut:**

1. The Overview panel above shipped with only 5 KPI tiles. The operator
   attached a screenshot of the STATIC dashboard's Overview (15 tiles) and
   asked for the same depth. `facts.py` (the "numbers quoted in prose"
   module) turned out to be the wrong source for most of them - it was
   written for the .xlsx/DATA-GUIDE.md pair, not the HTML dashboard, which
   was built separately by a different process reading raw CSVs by hand and
   inventing its own KPI set (median/mean session, the missing-day callout).
   Matched anyway, mostly by inference from the screenshot's own wording plus
   `facts.py`'s confirmed formulas (`wall_h`, `active_h`, `elapsed_h` from
   `overlap_day`, `SUM(n_user_prompts)`/`SUM(n_tool_uses)`/
   `SUM(n_assistant_turns)` at the session-row level, never the child
   tables). `dashboard.py`'s `S` rows grew 5 columns (`wall_seconds`,
   `active_seconds`, `n_user_prompts`, `n_tool_uses`, `n_assistant_turns`) to
   support it. All 15 tiles are reactive to both filters except three
   explicitly marked otherwise (session-open hours and peak-concurrent stay
   whole-corpus, date-range only, same reason as the Concurrency panel; the
   two "full embedded range" comparison tiles deliberately read from the
   UNFILTERED `DATA.S`, on purpose, since that is the whole point of a
   concentration/drop-off figure).

   Verification here found and corrected ITS OWN false alarm, worth recording
   because it is the exact shape [[explain-only-what-you-measured]] warns
   about: a first check used `ntile(1000)` in SQL to estimate the median
   session length and got ~28.5s, versus the dashboard's computed 11.6s (0.2
   min), a 2.5x gap that looked like a real bug. It was the CHECK that was
   wrong, not the code: `ntile` distributes 9,628 rows into 1,000 buckets
   unevenly on a heavily right-skewed distribution, so "bucket 500" is not
   actually the 50th-percentile position. An exact `ROW_NUMBER()`-based
   median gave 11.634s, matching the dashboard exactly. Confirmed a second,
   independent way: narrowing the date picker to 2026-06-08 onward (close to
   the original screenshot's own window) reproduced the screenshot's "75
   days / 72 active / 3 missing" figure exactly, INCLUDING the same three
   missing dates (24 Jun, 27-28 Jul) and the same "1.1 min" median - strong
   evidence the formula, not just the arithmetic, matches what built the
   original.

2. The operator also asked, separately, whether a real charting LIBRARY
   could give the page more "effects" - it read as static next to the
   original. Answered by explaining the tradeoff rather than guessing what
   they meant: this project's own stated habit is "no CDN, self-contained by
   habit" (from this very item's investigation section above), and a real
   library like D3 would mean vendoring 100-250 KB inline or breaking the
   single-file/no-network guarantee the privacy section demands. Built the
   vanilla equivalent instead: a custom styled tooltip (`.cc-tooltip`,
   replacing the native SVG `<title>`, which is slow and unstyled - every
   chart's `<g><title>` wrapper became a `data-tip` attribute read by one
   delegated `mouseover`/`mousemove`/`mouseout` handler), a hover-brighten on
   every bar/cell (`rect.mark:hover`), an `IntersectionObserver` scroll-
   reveal fade-in on each panel (mirrors the ORIGINAL static dashboard's own
   ~250-byte technique, mentioned in this item's investigation section
   above), and a brief cross-fade on `#panels` when a filter changes. All
   respect `prefers-reduced-motion`. NOT built: animated bar-height
   transitions on filter change (would need persistent per-bar DOM nodes
   instead of the current full-innerHTML-replace redraw, a bigger structural
   change) - noted as a possible follow-up, not attempted.

   The three Node correctness harnesses (full range, a real filtered
   scenario, and the Overview cross-check) all needed their own DOM stubs
   extended (`document.createElement`, `document.body`, `querySelectorAll`)
   to keep running headless after the effects landed - none of that code
   path had existed before. Re-ran all three after both rounds: 0 panel
   errors, all totals still matched independent recomputations exactly, 99
   tests still green, ruff clean.

**Third round of follow-ups, same session, all DONE 2026-08-21**: the
Overview panel grew from 5 to 15 KPI tiles (matching a screenshot of the
static dashboard's own Overview, cross-checked against `facts.py` where a
definition existed there); dollar figures switched to `US$` everywhere;
default start date set to 2026-06-08 (was the earliest embedded date); a
`--exclude-project` flag was added, then GENERALIZED the same session into
`--include`/`--exclude` (both repeatable, substring match against
`project_label`, `--include` an allowlist and `--exclude` a denylist that
narrows it further) after the operator asked for partial-name matching
rather than exact project names; the two strikethrough "naive number"
comparisons became plain parenthetical text (operator: "the strikethrough is
absolutely hideous"); every "vs. the full embedded range" comparison was
removed from the 15 tiles at the operator's explicit request ("everything
else becomes noise") - two tiles (`time with a session open`,
`most sessions running at once`) are STILL whole-corpus under the hood
(real interval-overlap math can't be sliced by project with the data
embedded), the caveat text is just gone from the page now, flagged to the
operator in chat rather than on the page; the API-cost tile's model
breakdown was changed from per-version to per-FAMILY (opus/sonnet/haiku/fable,
version numbers summed together) using a simple leading-letters regex on the
model string; the project-filter popup was widened twice, finally to
`min(96vw,900px)` with per-item ellipsis truncation for the rare 100+
character auto-generated names (measured: 118 distinct labels, avg 49.8
chars, max 196 - only ~14 exceed 80 chars) plus a `title` attribute so a
truncated name is still readable on hover. Every change re-verified the same
way as the rounds before it: real database cross-checks (model-family
percentages, substring-match counts, allowlist+denylist composition all
independently confirmed against direct SQL/counts), 99 tests, ruff clean.

**Fourth round, 2026-08-22 session, item 2 fully CLOSED.** A real browser was
available this whole session (`mcp__claude-in-chrome`). One environment note
worth keeping: `file://` URLs are refused by the navigate tool ("Can't
interact with browser-internal or unparseable URLs") even with a fresh tab,
tried three times. Worked around by serving `~/.cc-warehouse/stats` with
`uv run python3 -m http.server 8721 --bind 127.0.0.1` (loopback only) each
time a visual check was needed, then killing it after. Reuse this pattern
rather than re-discovering it.

1. **The operator's real `--include`/`--exclude` list, given this session and
   applied.** Final exclude list (no include list given, so nothing is
   allowlisted - everything not excluded stays ticked): `private-`,
   `<local-username>-`, `Tools-google-auth-2fa-exporter`, `Tools-clawfidence`,
   `Scripts-littlesnitch_blocklist`, `Scripts-devtools-snippets`,
   `Scaffoldings-`, `Playground-skills_playground`, `Ideas-Whryte_app_clone`,
   `Ideas-GitFoot_FluidAudio_vanilla`, `Ideas-Browser_Automation_System`,
   `CaptainCodeAU-Tax_`, `CaptainCodeAU-claude-code-transcripts`,
   `CaptainCodeAU-EXTENSIONS-`, `CaptainCodeAU-Proxmox-`,
   `CaptainCodeAU-Plex_Server`, `CaptainCodeAU-SCAFFOLDINGS-`, `3rdParty-`,
   `CaptainCodeAU-tax`, `CaptainCodeAU-wisdom_grabber`, `Ideas-GitFoot`,
   `CaptainCodeAU-hermes`, `CaptainCodeAU-cc-print-shop`. Printed the live
   118-project list from `sessions.sqlite` first so the operator could
   copy/paste real names rather than guess them; two case-mismatch misses
   (`CaptainCodeAU-tax-data-sprint` vs `Tax_`, `CaptainCodeAU-SCRIPTS-` vs
   `Scripts-`) were caught and flagged before the operator asked for
   case-insensitive matching outright.

2. **Case-insensitive `--include`/`--exclude` matching.** `resolve_unticked()`
   in `dashboard.py` lower-cases both sides before the substring check (was
   exact-case `pattern in name`). Verified with a probe insert/compare, not
   just by re-running the build.

3. **Default end date now tracks the reader's real "today"**, not the day
   the file was built. `todayLocal()` (local, not UTC, calendar date) +
   `DEFAULT_TO = todayLocal() < DATA.max_date ? todayLocal() : DATA.max_date`
   added to `dashboard_template.html`; `DEFAULT_FROM`'s own 2026-06-08 default
   is untouched. Verified by running the generated file's own script headless
   under Node against the live embedded data: `todayLocal()` correctly
   returned the real machine date while `DEFAULT_TO` correctly clamped to the
   newest embedded day when today's data was not embedded yet.

4. **"Where the work moved, month by month" (the `proj-month` heatmap), TWO
   separate real bugs, both operator-reported, both fixed:**
   - Month column headers (e.g. "2026-06", "2026-07", "2026-08") were
     rendering stacked on top of each other, unreadable. Cause: `heatmap()`'s
     default `cellW` (26 SVG units) was sized for 1-2 char labels (used
     correctly by the OTHER heatmap call, weekday x hour, 24 short columns);
     a 7-char month key needed much more room. Fixed by passing `cellW: 60`
     for this call specifically.
   - Long project row labels were losing characters off the START (e.g.
     "CaptainCodeAU-COWORK..." rendered as "OWORK-Best-Practice-Docs..."),
     because row labels are right-anchored and grow LEFTWARD past x=0, which
     the SVG viewBox clips. Fixed generically inside `heatmap()`: labels now
     truncate with an ellipsis to what the label column can actually hold
     (~8px/char, tuned against the real rendered names after an initial
     6.5px/char estimate still clipped by ~3 characters), with the full name
     still reachable via the existing `data-tip` hover tooltip.
   - **A THIRD, worse bug in the same panel was found only after the operator
     reported "text very large, alignment issues" post-fix**: for a narrow
     date range (few month columns), the heatmap's own natural width (e.g.
     390 SVG units for 3 months) was far below the page's real rendered
     panel width (measured 1,170px via `getBoundingClientRect()`), so the
     browser stretched the whole viewBox - text included - by 3x to fill the
     container. `barChart()` already guards against exactly this
     (`Math.max(660, ...)`, matching the page's own `.chart-svg{min-width:
     660px}`); `heatmap()` had no equivalent floor. Fixed by growing `cellW`
     (not padding blank space) so the natural width always reaches 660,
     mirroring how `barChart()`'s own bars already expand to fill its floor.
     Verified by DOM measurement before and after: viewBox went from
     `0 0 390 260` rendered at 1170px (3.0x stretch) to `0 0 660 260` at
     1170px (1.77x), in the same range as the "Top 15 by cost" panel's own
     1.3x - no longer an outlier.

5. **"How much time overlapped, whole corpus" (Concurrency), operator-flagged
   as "tremendous number of bars".** These bars are per DAY, not per project
   (the panel has no project dimension at all, by design - it needs real
   interval-overlap math across every project). A ~75-day default range gave
   75 thin daily bars. Rolled up to one bar per ISO week (11 bars for the
   default range) inside the panel's own render function: `summedHours` and
   `elapsedHours` are safely additive across days (each day is a disjoint,
   non-overlapping clock-time slice), `concurrency` is RECOMPUTED from the
   weekly sums rather than averaged day-to-day, and `maxConcurrent` is the
   max of the days' own peaks (the true weekly peak occurs within some single
   day, and that day's own figure is already its true instantaneous max - no
   session-level reconstruction needed). Verified two ways: an independent
   Python rollup against the live database matched the panel's own 11 bars
   exactly (1,188.7h / 941.3h / 811.0h / ... down to 533.0h), and the same
   figures were then read directly off the rendered chart in the browser and
   matched again.

6. **Project-list "noise" consolidation, operator-flagged on "Top 15 by
   cost" and (by the operator's own words) likely elsewhere too.** Measured
   first, not assumed: only 2 panels actually GROUP by project at all -
   "Top 15 by cost" and the month-by-month heatmap (a separate "repos" panel
   already exists, keyed on `repo_root`, and already folds ordinary
   subdirectories and named worktrees into their parent - that panel was
   left untouched). The real noise turned out to be a narrower thing than
   "worktree labels" in general: Claude Code's own background-agent tooling
   creates a throwaway folder per agent run
   (`.claude/worktrees/agent-<random hex>`), and each one gets counted as
   its own `project_label` / `repo_root` because Git genuinely treats a
   linked worktree as its own toplevel. Measured: 15 such rows, 30 sessions
   total, 12 of them for `cc-warehouse` alone. Put to the operator as a
   2-option decision (fold only this auto-generated pattern / fold
   everything the same way `repo_root` already does); **the operator chose
   "fold only the junk"**. Implemented as `canonicalProjectName()` (a regex
   stripping the `-.claude-worktrees-agent-<hex>` suffix) applied only inside
   the two grouping panels via a shared `CANON_PROJECT` lookup array - real
   named worktrees (`-.worktree-web`) and genuinely separate sub-repos
   (`-DIB-governor`) are deliberately left alone, since those are real,
   distinct work. Verified: an independent Python rollup (fold logic +
   exclude list both applied) matched the live panel's "42 projects in
   range" figure and its top-15 dollar amounts exactly, including
   `cc-warehouse` at US$ 3,948.02 (base US$ 3,774.78 + the 12 folded-in
   agent-worktree sessions summing to US$ 173.24, cross-checked
   independently too).

7. **Title changed** from "Claude Code, your own slice" to
   ".cc-warehouse / stats" (the page's `<h1>`; the `<title>` tag itself,
   "Claude Code, live", was not part of the ask and is unchanged).

8. **"Models by cost in range" now groups by model FAMILY** (opus/sonnet/
   haiku/fable, version numbers summed together), not by exact model
   string, per the operator's explicit ask. The Overview KPI tile already
   did this with its own local `modelFamily()` function; hoisted that to a
   shared top-level function so both panels use identical logic instead of
   risking two copies drifting apart, and matched its existing
   `<synthetic>`-row exclusion (a $0 placeholder for an interrupted reply,
   not a real priced model). Verified against a direct SQL rollup (with the
   exclude list applied): opus US$ 38,138.38, fable US$ 9,424.43, sonnet
   US$ 6,167.83, haiku US$ 64.34 - matched the rendered US$ 38.1k / 9.4k /
   6.2k / 64 exactly.

9. **"Top 8 in each kind" alignment fix, operator-flagged.** Was a 2-column
   CSS grid (`.grid2`); since each kind (agent/mcp_server/mcp_tool/plugin/
   skill) has a different row count and label lengths, the two columns never
   lined up cleanly. Switched to a single stacked column (`.stack1`, a plain
   flex column with a 26px gap) per the operator's own suggestion. The now-
   fully-unused `.grid2` CSS rule and its media query were deleted rather
   than left dead.

10. **Sessions tables, operator-requested change plus a new addition.** "The
    50 most expensive sessions in range" is now "The 25 most expensive
    sessions in range" (`slice(0, 50)` -> `slice(0, 25)`). Added a new panel,
    "The 25 longest sessions in range" (`longest-sessions`), same columns,
    sorted by engaged hours descending instead of cost descending.

11. **"Claude Code builds in range" panel removed entirely**, per the
    operator's explicit "it's kind of useless, get rid of it." Only the
    display panel was removed - the underlying `ccVersion` data column and
    lookup table in the embedded payload are untouched, so nothing else in
    the file lost data it depends on.

12. **The Caveats section ("What would make these charts wrong") removed
    entirely**, per the operator's explicit "it comes across very negative."
    Removed the `CAVEATS` array, its rendering block and nav link inside
    `renderAll()`, and the now-dead `.panel.dark`/`.cav-grid`/`.cav`/
    `.cav-t`/`.cav-d` CSS rules. **Flagged to the operator in chat, not
    silently dropped**: this section was the ONLY place the page told a
    reader "this file is private, do not upload it." That specific reminder
    is now gone from the page itself; the underlying privacy rule (never
    upload this file, it embeds real folder names) still fully applies per
    this document's own Privacy paragraph above - it is just no longer
    printed on the page for a reader who has not seen this file or
    `tools/ccstats/README.md`.

13. **A space added after "US$" everywhere**, per the operator's explicit
    ask. Both dollar-formatting functions (`fmtUSD`, `fmtUSDFull` in
    `dashboard_template.html`) changed from `"US$" + ...` to `"US$ " + ...`;
    these are the only two places the string "US$" is built anywhere in the
    file, confirmed by grep before editing, so no dollar figure on the page
    was missed.

**Verification method for this whole round**: `ruff check` and the 99-test
`pytest` suite stayed green throughout and after every change (no NEW tests
were added this round - every change here is in `dashboard_template.html`'s
client-side JS, which the Python test suite does not and cannot exercise;
`dashboard.py`'s own case-insensitivity change likewise has no dedicated
pytest coverage, only the ad-hoc DB probe described above). Every numeric
claim above was independently cross-checked against `sessions.sqlite` with a
fresh Python query, separate from the dashboard's own code, THEN confirmed
a second time by opening the real rebuilt file in a live Chrome tab (via the
local http-server workaround) and reading the same numbers off the actual
rendered page - not assumed from the JS alone. Browser console was checked
for errors after every rebuild (`read_console_messages`, pattern
`error|Error|exception|NaN|undefined`); none were found at any point this
round. **What is still NOT covered by an automated test**: none of
`dashboard_template.html`'s JS is under `pytest` at all, by design (it is a
generated static asset, not a `ccw` module) - the only guard against a
future regression in any of these 13 fixes is a human, or a future session,
re-opening the file in a browser and looking. Worth remembering before
trusting a future "the tests still pass" as proof this page still renders
correctly.

### 2b. `/dashboard` Claude Code command - DONE, tested 2026-08-23

Not part of the original plan - the operator asked for it mid-session, after asking how the live
dashboard actually works under the hood. A project-local slash command,
`.claude/commands/dashboard.md` (only usable inside this repo, matching `/refresh` and
`/architecture`'s existing pattern). It wraps `tools/ccstats/dashboard.py`: asks whether to
refresh the underlying data (always asks - operator's explicit choice, not auto-decided), asks
for (or reuses a saved) project-exclude list, builds the dashboard, serves it once over loopback
(`file://` is refused by the browser tool - see "Two environment facts" below), hands over the
link, then stops the server once the operator confirms they're done looking. Documented in
`tools/ccstats/README.md` under "The live dashboard" (the top-level repo `README.md` never
mentions `ccstats` at all, confirmed by grep with a control - `tools/` is explicitly not part of
`ccw`, so this is the correct home, not the main README).

**A real design gap was found and fixed before testing, not after**: the first draft hardcoded
`~/.cc-warehouse/stats` everywhere instead of honouring `CCSTATS_OUT` the way `dashboard.py` and
`collect.py` already do. Fixed by resolving the output root once (Step 0 in the command file) and
using that everywhere instead. This is what let the test below use a scratch folder instead of
the operator's real one.

**Tested end to end, for real, not just read over**: the operator asked for this specifically -
"we can't test it in this session, it'll get polluted" - so a single forked agent spun up a
genuinely separate Claude Code session in a new Herdr pane (`herdr agent start`), drove it through
`/dashboard` with `CCSTATS_OUT` pointed at a scratch folder, then opened the real output file in a
real Chrome tab via claude-in-chrome. Result: **PASS**. First run correctly skipped the refresh
question (nothing to refresh yet) and ran `collect.py` unconditionally as designed; the
exclude-list question worked and saved correctly (tmp-file + rename, per R2); the build and serve
steps produced a working link; the page rendered with zero console errors, real numbers, and a
live filter toggle that visibly recomputed totals with no reload; the server was confirmed stopped
afterward (`lsof`); and three real production files (`sessions.sqlite`,
`claude-code-dashboard-live.html`, and the fact that `dashboard-defaults.json` still does not
exist for real) were all confirmed untouched by mtime/existence check. One non-defect finding
worth knowing for next time: driving a fresh Claude Code session's own numbered-choice UI by
sending a literal digit (e.g. `"2"`) through `herdr agent prompt` does NOT select that option -
Enter just confirms whatever option is already highlighted (the default). Send the option's actual
wording instead, or use `herdr agent send-keys` for arrow keys.

Three commits, all pushed: `ca83ce7` (the command itself), `72e0b82` (the `CCSTATS_OUT` fix +
README documentation). A memory was also saved this session: always give the operator a full path
or link for anything to open, never a bare filename.

### 3. Ticket 27.5-27.8, the last open track

**CORRECTED 2026-08-23: this section was stale.** It read as if all four sub-tickets were still
open. They are not - `CLAUDE.md`'s own OPEN/next section already recorded the real state as of
2026-08-22 and this file simply had not been reconciled to it until now. Real state:

- **27.5** (whether `root` moves into the archive) - **DONE.** Decided AGAINST by the principal,
  after 27.6's guard read showed merging would make every `ccw archive --to <archive_root>` call
  trip the existing "must not be the warehouse itself" refusal. No code changed.
- **27.6** (re-read the `ccw archive --to` guard) - **DONE.** This is the read that answered 27.5.
- **27.7** (reconcile `ccw verify` with ruling (b)) - **DONE.** It turned out to already be shipped
  and tested; only the ticket's own paperwork was stale, and that's fixed too.
- **27.8** (retire `store.py`) - **NOT DONE, and NOT just unstarted - actively blocked.** It was
  attempted this track (`keep_objects` default flipped to `False` in code, oracle-tests-first) and
  REVERTED: it broke 7 pre-existing tests, all genuine resilience tests (an unwritable archive, a
  deleted archive JSONL). Retiring `store.py` for real needs a bigger, still-undecided call:
  dropping `keep_objects` as a feature entirely and making `archive_root` mandatory for every
  install, not just this machine's config. That is the actual decision the next session needs from
  the principal before touching this ticket again - not a scoping or measurement task.

So **item 3's real remaining work is just 27.8**, and it starts with a decision, not code. See
`CLAUDE.md`'s OPEN/next section ("27.5-27.7 CLOSED 2026-08-22...") and
`harness/tickets/27-collapse-to-one-folder.md` for the full account - this file no longer
duplicates it now that it's been reconciled once.

**THAT DECISION WAS MADE 2026-08-23, SAME SESSION.** Explained to the operator in plain
language first (verified from source: `config.py:162`, `capture.py:189-261`, the 7 named
tests), then put as a straight fork: drop the vault and make `archive_root` mandatory
everywhere, or keep both as the status quo. **The operator chose to keep both.** 27.8
stays NOT DONE and `store.py` stays - this is the settled answer, not an open question,
recorded in `CLAUDE.md`, `harness/tickets/27-collapse-to-one-folder.md`, and
`contract/DESIGN.md` section 15 ("2026-08-23, ticket 27.8"). Item 3 has no remaining
work. Do not re-ask this.

**27.9 IS WITHDRAWN AND STAYS WITHDRAWN.** Nothing is ever deleted from
`~/.claude`. A satisfied gate is not consent.

### 4. Ticket 30's flagged-for-later: the equal-size payload defect

A real fidelity bug, in ticket 29's family. When a re-captured payload is the
SAME SIZE as the archived one but has different content, the JSONL is correctly
left alone, but `refused` stays False, so the folder's rendered markdown and
HTML describe the NEW payload while the JSONL beside them still holds the OLD
bytes. Mechanism 2 fixed the size-known-different case; this is the equal-size
case. Recorded at the end of `harness/tickets/30-incremental-archive-rebuild.md`.

Correctness of the deliverable beats everything below it.

**CLOSED 2026-08-23.** `write_session_folder` now reads and compares the actual
bytes when sizes match, instead of assuming equal size means equal content
(F1). A mismatch takes the same conservative branch as a smaller payload (R5) -
declined, recorded in the manifest with its own reason string, tracked in a new
`FolderResult.refused_equal_size` field kept separate from `refused_smaller` so
the two causes are never conflated. Scoped to `write_session_folder` only -
`write_source`/`write_subagent` share the same size-only pattern but never
render a second set of files that could disagree with the JSONL, so neither
reproduces the actual failure mode. Oracle tests (`tests/test_equal_size_
refusal.py`, 7 tests, plus one addition to the locked `test_archive_layout.py`)
were verified red-then-green with a real `git stash` of just the production
fix - every one failed against the pre-fix code, the end-to-end test with the
exact real-world "JSONL does not match manifest source_hash" symptom, before
passing once restored. Full account: `harness/tickets/30-incremental-archive-
rebuild.md`'s own closing note. Full suite: 1,122 passed, ruff clean, pyright
0 errors.

### 5. Ticket 28.22: fence `ccw doctor`'s text output

`~/.local/bin/ccw-watch` (a DIFFERENT repo, `fifty-shades-of-dotfiles`) runs at
every Claude Code SessionStart and parses `ccw doctor` with a regex: the `hook`
line's wording and the `Uncaptured: N session(s)` figure. **Nothing in this
repo's suite protects that shape**, so a reformat breaks an external consumer
with nothing here going red. Pin the exact substrings a known-external parser
depends on, not the whole output.

**CLOSED 2026-08-23, done FIRST (of items 4 and 5) since it was the quick
one.** Read ccw-watch's actual source rather than trust the "hook line's
wording" framing above, which turned out to be imprecise - ccw-watch never
matches on the word "hook" at all. The real, narrower contract: exit code,
the literal `"Uncaptured: <N> session"` substring (`status.py:152`, extracted
by ccw-watch's own `sed`), and a leading `"FAIL"` on a failed blocking check's
line (`doctor.py:440`, read by ccw-watch's own `grep`).
`tests/test_doctor_external_contract.py` pins both by running those EXACT
sed/grep commands against real `ccw doctor` output, and was proved to
actually catch a break (mutated the wording, watched it go red, reverted).
No production code changed - a protective test only. Full account:
`harness/tickets/28-backlog.md`'s 28.22 entry.

Cheap, and this session nearly tripped over `doctor`'s output twice.

### 6. Ticket 28.13: re-derive the architecture board

Now urgent in a way it was not before. **The board's every `file:line` was
derived at master `1517bba`, and that commit no longer exists** - nor
`18fa5be`. Both were lost when the repository was deleted and re-created on
2026-08-10 for the go-public audit (28.20). So the refs are anchored to
nothing and their decay cannot even be measured: `git rev-list 1517bba..HEAD`
does not run. A decay banner recording this now sits at the top of
`cc-warehouse-architecture/SOURCE.md`; the cards are untouched.

The card REASONING still stands. Only the line numbers are dead. The fix is a
fresh review at a live commit, via `/architecture`, never hand-patching refs.

### 7. ccstats polish, once item 1 has made it safe

In rough value order: ~~`--until` (only `--since` exists...)~~ **DONE, landed
as part of item 2 above (2026-08-21) - closed here instead of twice, as
already noted.** ~~Split the three long functions (`collect.scan_transcript`
330, `make_docs.main` 273, `facts.compute` 153)~~ **DONE 2026-08-23.** Each
split into named helpers grouped by what they actually compute; verified
byte-identical output against real data before/after (a frozen transcript set
for `scan_transcript`, the same real `sessions.sqlite` for `facts.compute`,
a real `DATA-GUIDE.md` regeneration for `make_docs.main` - the last one
caught and fixed one real transcription slip before it shipped). ~~Re-check
model prices (pinned at 2026-06-24, every dollar figure drifts)~~ **DONE
2026-08-23.** Checked against the live pricing page: everything still
matched except Claude Sonnet 5's active $2/$10 introductory rate (through
2026-08-31) - operator chose to keep the post-intro $3/$15 rate rather than
the temporary one, recorded in a comment so it does not read as a future
oversight. `PRICES_READ_ON` bumped to 2026-08-23. Full account: the commit
that landed all three (`dcac852`).

~~**Remaining, not started:** incremental collect (re-reads all 25k transcripts
every run, ~25 s).~~ **DONE 2026-08-23, item 7 now fully closed.**
`collect.py` gained `scan-cache.sqlite`, a sibling to `sessions.sqlite`
published the same way (temp file + `os.replace`, R2): each transcript's own
scan result is cached keyed by its path + size + mtime, so an unchanged file
is served from the cache instead of being re-read and re-parsed. It is pure
derived data, not a second copy of session content (R1) - deleting it, or
passing the new `--no-cache` flag, just falls back to a full scan (R5/R10).
Cache validity is auto-invalidated by a fingerprint (`CACHE_SCHEMA_VERSION` +
`PRICES_READ_ON` + the detected local timezone), because `cost_usd` and
`local_date`/`local_hour` are baked into every cached row and would otherwise
keep reporting numbers only true under the OLD prices/zone forever, since a
finished session's file never changes again. A `--limit` smoke-test run reads
the cache but never overwrites it, since it only ever sees a slice of the
corpus and writing that back would evict every other session's entry.

11 new tests in `tools/ccstats/tests/test_incremental_cache.py` (110 total,
up from 99), each verified red-then-green with a real `git stash` of just the
production changes - every one failed against the pre-cache code before
passing once restored. Measured on the real archive via `CCSTATS_OUT` pointed
at a scratch dir (never touching `~/.cc-warehouse/stats`): a cold run over
26,678 transcripts took 26.9s; a warm rerun with nothing changed took 7.5s
(26,675 cache hits, 3 rescanned - real live sessions that genuinely changed
between the two runs). A follow-up micro-optimisation (reusing a cache hit's
own raw JSON text instead of decoding then re-encoding it) was tried and
measured to make no real difference, so it was reverted in favour of the
simpler symmetric code - **explain only what you measured**, not what seems
like it should help. `README.md` documents the new file and flag.

---

## Also on record, not scheduled

- ~~**Ticket 24.7**, session-start capture freshness. Partly closed from
  outside this repo by `ccw-watch`.~~ **DONE 2026-08-23**, and now owned by
  this project's own plugin rather than borrowed - see the eleventh-handoff
  entry at the end of this file.
- **Ticket 28**, the backlog register. **28.1 (`--open`) and 28.3 (`--limit`
  on sweep) BOTH DONE 2026-08-24** (see the ticket's own DONE notes in
  `harness/tickets/28-backlog.md`; 28.1 scoped to `ccw render` only,
  `ccw share`'s multi-session `index.html` left for later). Still open in it:
  optional secret redaction on personal projections (28.2), `render_html`
  costing 74x the payload (28.9), test gaps (28.10), markdown/HTML for
  sub-agents (28.11), re-homing an orphaned sub-agent when its parent arrives
  (28.12), `prefers-color-scheme` for shared pages (28.14).
  **28.19 was ALREADY DONE (2026-08-10, `4b8dde4`) and this list was stale about
  it until 2026-08-23** - the plugin has lived in-repo at `plugins/cc-capture/`
  for two weeks, installed as `cc-capture@cc-warehouse`; the old
  `claude-transcript-exporter@gz-claude-code-plugins` is gone from
  `~/.claude/settings.json`'s `enabledPlugins` entirely, not merely disabled.
  Found the hard way: ticket 24.7's freshness signal was first built against
  the old, dead plugin before this was caught and the work redone in the
  right place - see the eleventh-handoff correction below.
- **Ticket 31's inherited open question:** the lock-contention mechanism is
  still UNPROVEN. Debug logging shipped; the retry loop was deliberately not
  written until the real exception is observed. Do not design a fix for an
  unconfirmed cause.
- **Version cuts not started:** v1.1 proper (FTS5 + `ccw search` + HTML archive
  search + `ccw import`/inbox), v1.2 (`ccw mcp`), ticket 19 leftovers (`share`
  19g, and `status`/`relocate`/`project` on archive labels), DESIGN 15 item 7
  (registry backup/export story).
- **`ccw-watch`'s "capture is NOT working" RED banner from 2026-08-22
  (`desync: 5 problem(s)... missing transcript.md`) was investigated
  2026-08-23 and is CLEARED, not a live bug.** Full account: `contract/
  DESIGN.md` section 15, "2026-08-23: THE `ccw-watch` RED FLAG...". Short
  version: one session got rendered ~16h late by the daily sweep backstop
  instead of the hook (now fixed on disk); a full 22,580-folder archive walk
  (not just the 25-folder sample `ccw doctor` checks) found 0 other real
  bugs - the other 505 "missing transcript.md" folders are hidden/warmup
  sessions withheld from rendering BY DESIGN. Worth remembering: a green
  `ccw doctor` re-run does not by itself prove an old desync is fixed, since
  its sample window is only the 25 most recent captures and simply moves
  forward - this session confirmed it the slow way instead of trusting the
  green sample alone.

## Two environment facts that will bite

- **`ccw doctor` run from inside this repo reports `editable`, and that is not
  a rule violation.** `.envrc` (tracked 2026-08-21) sources `.venv/bin/activate`,
  so `.venv/bin/ccw` shadows `~/.local/bin/ccw` on PATH and doctor truthfully
  describes the venv copy - not what the hook runs. The install IS frozen.
  Unambiguous check:
  `env -u VIRTUAL_ENV PATH="$HOME/.local/bin:/usr/bin:/bin" ~/.local/bin/ccw doctor`
- **The SSH key drops out of the agent** (ticket 28.15, seen again 2026-08-21).
  `ssh-add -l` reported "no identities" and `git push` failed on access rights.
  Commits `3b284e5` and `a366275` are LOCAL AND UNPUSHED. The operator must run
  `ssh-add` themselves; a session cannot.
- **NEW, 2026-08-22: `file://` navigation is refused by the Chrome browser
  tool** (`mcp__claude-in-chrome__navigate`), even to a brand-new tab -
  "Can't interact with browser-internal or unparseable URLs." To visually
  check any local HTML file (this dashboard included), serve its directory
  over loopback first: `uv run python3 -m http.server <port> --bind
  127.0.0.1` from that directory, navigate to `http://127.0.0.1:<port>/file`,
  then kill the server when done. Worked cleanly every time this session.
- **NEW, 2026-08-23: testing any ccstats script without touching real data** -
  set `CCSTATS_OUT=<scratch dir>` before running `collect.py`, `dashboard.py`,
  or `/dashboard` (its Step 0 honours the same variable, fixed this session).
  Everything lands in the scratch folder instead of `~/.cc-warehouse/stats`,
  and `resolve_out` still refuses the dangerous roots (this repo, `~/.claude`,
  the archive, the warehouse data root) even for the scratch value.
- **NEW, 2026-08-23: a fresh Claude Code session's numbered-choice UI, driven
  via Herdr's `herdr agent prompt`, does not respond to a literal digit** -
  sending `"2"` does not select option 2; Enter just confirms whichever option
  is already highlighted (the default). Send the option's actual wording as
  text instead, or use `herdr agent send-keys <name> <key>` for real arrow-key
  navigation. Caught before any real file was touched; see item 2b above.

## What the previous session did

**2026-08-23 session (the one that produced this seventh handoff).** Opened by reading this file
(the sixth handoff, above) and asking the operator, in plain language, what to do about the two
threads it left open: the item-3 decision (ticket 27.8) and the item-2 loose end (the panel-contract
doc). The operator first asked for a plain-language explanation of what `keep_objects`/`store.py`
(the vault) vs `archive_root` (the archive folder) actually do before deciding anything on 27.8 -
answered by a sub-agent verifying the real mechanism from source (`config.py:162`,
`capture.py:189-261`, and the 7 specific tests named in the 2026-08-22 ticket-27.8 entry), not from
memory or this file's own prior summary. Given that explanation, the operator chose to KEEP BOTH
(the vault stays as a safety net) - see the correction inside item 3 above. That decision is now
recorded in `CLAUDE.md`, `harness/tickets/27-collapse-to-one-folder.md`, and `contract/DESIGN.md`
section 15; **item 3 has no remaining work and should not be re-opened without a new, explicit
reason.**

Separately, the operator said "write it now" for the panel-contract doc. Read
`dashboard_template.html` and `dashboard.py` directly to write `tools/ccstats/PANEL-CONTRACT.md` -
the data model, every chart/format helper, the house rules from `CHART-BRIEF.md`, and one fully
annotated example panel (Daily) - plus a one-line pointer from `tools/ccstats/README.md`. See the
correction inside the "One loose end" section above; that loose end is CLOSED.

One stale line noticed but NOT fixed, flagged instead: `tools/ccstats/README.md`'s "Scope, stated
rather than hidden" paragraph still says "Top sessions shows the top 50... not 200," but this file's
own item-2 "Fourth round" notes say that panel is 25, not 50, as of 2026-08-22. Out of scope for
this session's actual task; worth a one-line fix next time that file is touched.

**What was NOT done, as of the seventh handoff:** nothing from items 1-3 remains open. The next
real work is whatever the operator picks from "Also on record, not scheduled" below or
`CLAUDE.md`'s OPEN/next section - ticket 30's equal-size payload defect, ticket 28.22, ticket
28.13, or ccstats polish (item 7) are the standing candidates, none started this session.

---

**Later the same day (eighth handoff).** Given the choice between ticket 30's equal-size defect
(item 4) and ticket 28.22 (item 5) and told to do both, picking which one to start with. Started
with 28.22 (the recommendation, since it was quick and closed a real risk): read `ccw-watch`'s
actual source in `fifty-shades-of-dotfiles` rather than trust this repo's own prior description of
what it depends on, found that description was imprecise (ccw-watch never matches on the word
"hook"), and wrote `tests/test_doctor_external_contract.py` pinning the real, narrower contract by
running ccw-watch's own sed/grep commands against real `ccw doctor` output - verified red-then-green
by mutating the wording it depends on and watching the test catch it. Then ticket 30's equal-size
defect: `write_session_folder` now compares actual bytes (not just size) when an offered payload
matches the archived one's length, taking the same conservative "refuse and record" branch as a
smaller payload when they differ. Verified the SAME way - a real `git stash` of just the production
fix showed every new/changed test fail against the pre-fix code, the end-to-end one with the exact
real-world "JSONL does not match manifest source_hash" symptom, before all passed once restored.

One incidental fix along the way: a doc edit for 28.22 named `fifty-shades-of-dotfiles`'s own
tracked copy of the script by its internal path, which uses that repo's OWN home-dir-mirroring
folder convention, not a real username - but the packaging gate's privacy-scan heuristic (`test_
packaging.py`) reads any slash-separated "home" segment followed by a word as a real user's home
directory, so it went red. Reworded the doc rather than touched the locked scan test.

Four commits, all pushed: `a197853` (PANEL-CONTRACT.md), `f60bc24` (ticket 27.8's decision record),
`32a31a3` (ticket 28.22's fence test), `f7f598c` + `962680a` (the packaging-gate reword and ticket
30's fix, split because the test file landed a commit early by an unintentional `git add` carry-over
- harmless, but worth knowing the history looks that way if anyone reads it later). Full suite
re-confirmed green after every change (1,122 tests, ruff clean, pyright 0 errors).

**What was NOT done:** nothing from items 1-5 remains open as of this eighth handoff. Ticket 28.13
(re-derive the architecture board) and ccstats polish (item 7) are the standing next candidates;
neither started this session.

---

**Later the same day (ninth handoff).** Given the two remaining candidates, ticket 28.13 (the
architecture board) and ccstats polish, and told to do both, one at a time.

**Ticket 28.13.** The named review skill was not enabled in this session, so 5 parallel read-only
agents substituted for it - the same lens split as the 2026-07-24 review, plus a new lens for
`archive.py`, a 900+ line module that postdates that review entirely and had never been looked at
by this board. Two of the agents' findings were consequential enough to verify first-hand rather
than trust: both turned out to be real, LIVE bugs, not just architecture debt, and were fixed the
same session with oracle tests written first, proved red-then-green against the pre-fix code -
`write_subagent` silently dropping a same-size, content-different re-capture with no record
anywhere (worse than the session-writer twin ticket 30 had just fixed, since sub-agents have no
manifest to record a refusal in), and `ccw share --out` having no guard against writing inside the
warehouse's own store (unlike its `ccw render --out` sibling). The whole board was then re-derived
and re-ranked at HEAD, with the new top recommendation (C12) being exactly the lesson those two
bugs taught: one shared "replace if larger" rule instead of three near-identical copies. Three
commits, all pushed: `d9a2227` (the write_subagent fix), `4824098` (the share guard fix), `e067c8c`
(the board itself).

**ccstats polish.** Split all three flagged long functions (`collect.scan_transcript`,
`facts.compute`, `make_docs.main`) into named helpers, verified byte-identical against real data
before and after every split via `git stash` - a frozen transcript set, the same real
`sessions.sqlite`, and a real `DATA-GUIDE.md` regeneration (which caught and let a real
transcription slip get fixed before it shipped, rather than after). Also re-checked the pinned
model prices against the live pricing page: everything matched except Claude Sonnet 5's active
introductory rate, which the operator chose not to adopt (kept the post-intro steady-state price
instead, recorded in a comment so a future session does not read it as a missed update). One
commit, pushed (`dcac852`). "Incremental collect" (the third flagged ccstats item, a real feature
rather than a cleanup) was left alone, as scoped from the start.

Four commits this half of the session, all pushed: `d9a2227`, `4824098`, `e067c8c`, `dcac852`.
Full suite re-confirmed green after every change (1,124 main-repo tests, 99 ccstats tests, ruff
clean, pyright 0 errors on `src`/`tests`).

**What was NOT done:** nothing from items 1-7, ticket 28.22, or ticket 30's flagged defect remains
open as of this ninth handoff. Standing candidates for a future session: ticket 24.7 (session-start
capture freshness - partly closed already from outside this repo), the remaining items in ticket
28's backlog register, and ccstats' "incremental collect" (item 7's one leftover, a real feature,
not a cleanup - re-reads all ~25k transcripts every run, roughly 25 seconds).

---

**Later the same day (tenth handoff).** Given a straight choice between "incremental collect" and
picking an item from ticket 28's backlog, the operator picked incremental collect. See the
correction inside item 7 above for the full technical account - short version: `collect.py` now
caches each transcript's own scan result in a sibling `scan-cache.sqlite`, keyed by path + size +
mtime, so an unchanged file (almost all of them, once a session ends) is reused instead of being
re-read and re-parsed. A price or timezone change auto-invalidates the whole cache, since both are
baked into every cached row (`cost_usd`, `local_date`/`local_hour`) and an old row would otherwise
keep reporting stale numbers forever. `--no-cache` and `--limit`'s "never overwrite the cache with
a partial slice" behaviour are both new flags/rules, documented in `README.md`.

11 new tests (110 total), each proved red-then-green against a real `git stash` of just the
production changes. Measured on the real archive via a `CCSTATS_OUT` scratch dir (never touching
`~/.cc-warehouse/stats`): 26.9s cold, 7.5s warm with nothing changed - roughly 3.6x. A follow-up
attempt to shave the warm run further (reusing a cache hit's own raw JSON text instead of decoding
then re-encoding it) was tried and measured to make no real difference, so it was reverted in favour
of the simpler, symmetric code rather than kept on the assumption it must help.

One commit, pushed. Full suite re-confirmed green (1,137 main-repo tests, 110 ccstats tests, ruff
clean on both).

**What was NOT done:** item 7 is now fully closed - nothing from items 1-7 remains open. Standing
candidates for a future session, unchanged from the ninth handoff: ticket 24.7 (session-start
capture freshness, partly closed already from outside this repo) and the remaining items in ticket
28's backlog register.

---

**Later the same day (eleventh handoff).** Given a straight choice between ticket 24.7
(session-start capture freshness) and a ticket 28.9 performance fix, the operator picked 24.7,
after first asking to confirm before the change touched a second, live repo (`gz-claude-code-plugins`)
whose `hooks.json` controls what runs at every real SessionStart on this machine - confirmed
before any edit there.

Two fixes landed, one per repo. In cc-warehouse: `_run_hook`'s `CCW_SKIP_HOOK=1` path used to
return 0 with zero record anywhere; it now reports `skipped_disabled` through the same
`notify.report` path `skipped_unchanged` already uses, proved red-then-green
(`tests/test_capture.py::test_kill_switch_reports_skipped_rather_than_silently`).

In the plugin repo: a new `SessionStart` hook, `ccw-freshness-check.py`, registered in
`hooks.json` beside the existing `SessionEnd` capture hook. **A real design correction was
found and fixed before shipping, not after**: the ticket's own wording ("reads ticket 23's gap
figure") reads as "alarm on the Uncaptured: N count", and the first draft did exactly that with
fixed numeric thresholds. Run against this machine's real data, it printed ALERT on a perfectly
healthy install, because that count sits at 250-350 here permanently (old sessions predating the
archive, hidden/warmup sessions) and `doctor.py` itself marks it "ok", never blocking. Rebuilt to
key the alarm on `ccw doctor`'s own PASS/FAIL exit code instead - the same signal `ccw-watch`
already relies on - escalating on consecutive broken session-starts in a row (a streak persisted
in `~/.claude/logs/ccw-freshness-state.json`), with the raw gap figure riding along as context
rather than as the trigger. Verified against real data three ways: the real 298-uncaptured healthy
machine now prints nothing; a simulated 6-session outage (`CCW_BIN` pointed at a fake failing
`ccw`) escalated mild -> WARNING (streak 2-4) -> ALERT (streak 5+); a simulated recovery went
silent and reset to streak 0 immediately.

The plugin repo had no test suite at all before this. Its first test file,
`tests/test_freshness_check.py` (stdlib `unittest`, no new dependency, 14 tests), covers the
escalation tiers, the streak persistence, the `uv tool run` fence (matched narrowly against the
argv-list shape so it does not flag the historical incident documentation already in `ccw-hook.py`'s
own docstring), and a hand-kept mirror of cc-warehouse's `CCW_*` env var list (necessarily
hand-kept, not a live cross-repo import - the two repos share no dependency). All 14 passed. Full
account, including why the fences do not live in cc-warehouse itself (hardcoding a sibling repo's
local path would violate this project's own "no personal machine paths" rule): the "24.7 DONE
2026-08-23" section of `harness/tickets/24-make-capture-work.md`.

Full cc-warehouse suite re-confirmed green after the fix: 1,138 tests, ruff clean, pyright 0
errors.

**CORRECTION, same handoff, found immediately after the operator read the summary above:** the
SessionStart hook had been built and pushed into the WRONG, DEAD plugin. `claude-transcript-
exporter@gz-claude-code-plugins` was already retired - ticket 28.19 had moved the plugin into this
very repo two weeks earlier (2026-08-10, `4b8dde4`, installed as `cc-capture@cc-warehouse`), and
this file's own "Also on record" list and CLAUDE.md's OPEN/next section were both stale about it,
still calling 28.19 open. Proof: `~/.claude/settings.json`'s `enabledPlugins` carries only
`"cc-capture@cc-warehouse": true` - the old slug is not merely `false`, it is absent entirely, and
the plugin cache for it is pinned to a commit from before this session even started.

Redone in the right place: `ccw-freshness-check.py` and the `SessionStart` hooks.json entry now
live in `plugins/cc-capture/hooks/` (this repo), identical logic to the discarded copy. This time
the oracle tests landed inside cc-warehouse's OWN gated suite
(`tests/test_cc_capture_freshness.py`, pytest, 14 tests) instead of a hand-rolled `unittest` file in
a separate repo - the original ticket's "the fences belong in this repo" is now literally true,
since the plugin genuinely is in this repo. One test could not exist in the discarded version at
all: a LIVE check that every `CCW_*` name the wrapper sets is a real name in
`cc_warehouse.config.ENV_VARS`, importing that module directly rather than hand-mirroring its
contents. Verified against real data again in the new location: the real machine (310 chronic
uncaptured, healthy doctor verdict) produces no output and one `"status": "ok"` log line.
**"Left in place rather than deleted" below is STALE as of the twelfth handoff - see that section**;
ticket 28.19's own entry in `harness/tickets/28-backlog.md` was corrected from open to
`DONE 2026-08-10`. Full account: `harness/tickets/24-make-capture-work.md`'s "24.7 DONE" section
and `harness/tickets/28-backlog.md`'s corrected 28.19 entry.

Full cc-warehouse suite re-confirmed green after the correction: 1,152 tests, ruff clean, pyright 0
errors.

**What was NOT done, as of the eleventh handoff:** nothing from items 1-7, or from tickets
24.7/28.13/28.22/30, remained open. Ticket 28.19 was not open either - it was already done, the
record was just wrong. **This was not actually the end of the day - see the twelfth handoff below
for real-data verification via Herdr, a second real defect found and fixed in `ccw doctor` itself,
and cleanup of the discarded repo.**

---

**Twelfth handoff, same day, same session, prompted by the operator's own tip ("you can always use
Herdr to launch a claude code session in a new pane... to do a fresh test without context
pollution") plus three follow-up questions.**

**Herdr verification, not just unit tests.** Split a sibling pane, started a fresh Claude Code
session (`herdr agent start`), ran `/plugin marketplace update cc-warehouse` in it (confirmed:
"Updated 1 marketplace, 1 plugin bumped", and the cache grew a new commit directory,
`~/.claude/plugins/cache/cc-warehouse/cc-capture/<new-hash>/`, already carrying the SessionStart
entry). Started a SECOND, genuinely fresh session and confirmed via the shared hook log
(`~/.claude/logs/ccw-hook.log`) that Claude Code's own SessionStart plumbing - not a manual script
invocation - actually fired `ccw-freshness-check.py` and logged a fresh, correct "ok" line. Closed
both test panes afterward.

**The operator then asked three questions, all answered by checking live state rather than
assuming:** (1) had the discarded `gz-claude-code-plugins` commit been reverted - no, not yet, but
confirmed harmless (`extraKnownMarketplaces` in `~/.claude/settings.json` has NO entry for that
marketplace at all - fully removed, not just disabled); (2) the full path to `cc-capture` and
whether it is the same one in this repo - yes, source at
`plugins/cc-capture/` here, running copy at
`~/.claude/plugins/cache/cc-warehouse/cc-capture/<commit-hash>/`; (3) what could prevent this exact
mistake from recurring, "not even accidentally".

**Answering (3) surfaced a SECOND real defect, this time in `ccw doctor` itself**, found while
designing the safeguard rather than assumed: `_hook_commands` globbed every plugin's cached
`hooks.json` with no regard for whether Claude Code still had that plugin enabled, so a retired
plugin's leftover cache directory (proven to exist on this exact machine -
`~/.claude/plugins/cache/gz-claude-code-plugins/claude-transcript-exporter/d8107737a5ee/`, and it
even carries Claude Code's OWN `.orphaned_at` marker, timestamp 2026-08-10T10:01:39Z, ~23 minutes
after the ticket 28.19 commit) could still be reported as a working capture hook. Fixed
oracle-tests-first (3 new tests in `tests/test_doctor.py`, proved red against the pre-fix code:
a plugin absent from `enabledPlugins`, one explicitly `false`, and the positive case of one that
really is `true`): `doctor.py` now reads `enabledPlugins` and only counts a plugin-sourced hook when
its exact `plugin@marketplace` key is `true` there, and the `hook` line now NAMES the serving
plugin (`found via cc-capture@cc-warehouse: ...`). Verified against real data via the editable dev
build (`uv run ccw doctor`): correctly ignores the real orphaned `gz-claude-code-plugins` cache and
correctly names `cc-capture@cc-warehouse`. One incidental fix along the way: a docstring using the
word "identical" tripped the R8/F6 guarantee-words fence
(`tests/test_fences.py::test_guarantee_words_cite_their_proving_test`) - reworded rather than
exempted, since the word was decorative prose, not an actual guarantee this function proves.

**A new hard rule went into `CLAUDE.md`** naming `cc-capture@cc-warehouse` as the only live capture
plugin and stating the exact check to run (`enabledPlugins`) before touching any hook file in any
repo. **Two memory files were also written/updated** (outside this repo, in the project's
Claude-memory directory): `ccw-deployment-on-this-machine.md` gained the plugin-migration facts and
the `.orphaned_at` timeline; a new `verify-live-state-before-editing-hooks.md` (type: feedback)
records the general lesson - check a tool's own live enabled-state before editing its
config, never infer it from a repo's docs - for reuse beyond this repo.

**The operator then chose, from a 3-option question, to "clean it up"**: in
`gz-claude-code-plugins`, `git revert --no-edit` undid the discarded commit (history preserved,
nothing force-pushed), and both that repo's top-level README and the plugin's own README gained a
prominent "RETIRED 2026-08-10" notice pointing at `cc-capture@cc-warehouse` in this repo. Both
commits pushed.

Five commits this handoff, all pushed to cc-warehouse: the `_run_hook` skip-reporting fix, the
freshness-check rebuild in the right plugin, the `doctor.py` `enabledPlugins` safeguard, and the
`CLAUDE.md` hard rule (four separate commits from earlier in the day, listed here for completeness)
plus none new to cc-warehouse in this specific handoff beyond what the "24.7 DONE" and
`enabledPlugins` sections above already cover. Two commits pushed to `gz-claude-code-plugins`: the
revert and the retirement-notice docs commit. Full cc-warehouse suite re-confirmed green after
every change this handoff: 1,155 tests, ruff clean, pyright 0 errors.

**What was NOT done:** nothing from items 1-7, or from tickets 24.7/28.13/28.19/28.22/30, remains
open as of this twelfth handoff. The `gz-claude-code-plugins` repo itself was NOT archived on
GitHub - the operator picked the middle option (revert + retirement notice), not the "archive the
whole repo too" option, so that remains available as a future ask if wanted but is not done. The
only standing candidate for a future session is ticket 28's backlog register (28.1, 28.2, 28.3,
28.9, 28.10, 28.11, 28.12, 28.14).

---

**Thirteenth handoff, 2026-08-24 (new session).** Opened by reading this file, then asked the
operator to pick a starting point from ticket 28's backlog via a 4-option question (`--open`
28.1 / `--limit` on sweep 28.3 / the `render_html` perf issue 28.9 / stop for now). Operator
picked `--open`.

**28.1 DONE, scoped to `ccw render` only.** `notify.open_folder` reveals the folder a capture
landed in; nothing opened the actual rendered page. Read the specimen's own four `--open` sites
(`claude_code_transcripts/cli.py`, stdlib `webbrowser.open`) for the shape, then built the
cc-warehouse equivalent rather than porting it: `notify._open_with_system_default` is now the one
shared platform-opener primitive (R9, the exact C12 pattern ticket 28.13's architecture review had
just recommended), with `open_folder` (existing, reveals a folder) and the new `open_page` (opens
one file) as thin named wrappers. `cli.py` gained `_open_rendered_page`, which picks the archive
folder's `conversation.html` when `archive_root` is configured (mirroring `_reveal_target`'s own
"the archive is the deliverable" precedent) or the personal `projections/` copy otherwise, wired
to a new `--open` flag on both the `--session s:<key>` and ad-hoc forms of `ccw render`.
Best-effort throughout (DESIGN 12): a broken opener can never fail a render.

`ccw share`'s multi-session `index.html` was deliberately left out of this pass to keep the change
small and testable in one sitting; flagged in the ticket's own DONE note as a fast follow-up if
wanted, not attempted here.

8 new oracle tests (`tests/test_render_open.py`), proved red-then-green with a real `git stash` of
just the production diff (7 of 8 failed pre-fix; the 8th, a pre-existing typo-guard regression
test, was correctly unaffected). One test written for a third scenario -
`keep_projections=false` with no `archive_root`, meant to prove `--open` is a silent no-op with
nothing to open - was dropped after measuring that `config.py`'s own `_keep_projections` refusal
makes that combination unreachable: it silently falls back to `keep_projections=True` rather than
ever leaving a session with nowhere to render. The no-op branch in `_open_rendered_page` stays as
defensive code, not something a real config can trigger. Full suite: 1,163 passed, ruff clean,
pyright 0 errors on `src`/`tests`.

Ticket 28's own entry (`harness/tickets/28-backlog.md`) and this file's "Also on record, not
scheduled" section above were both updated in place to mark 28.1 done, rather than left to drift
the way 28.19 did.

One commit, pushed (production + tests + doc updates together, since the change is small).

**What was NOT done:** nothing new opened this part of the handoff. See the continuation directly
below for 28.3, picked next in the same session.

---

**Same day, continuing the thirteenth handoff.** Asked the operator to pick again from the
remaining backlog via a 3-option question (`--limit` on sweep 28.3 / the `render_html` perf issue
28.9 / stop for now). Operator picked `--limit` on sweep.

**28.3 DONE.** `ccw sweep --limit N` (and `--limit=N`) caps `sweep._walk_source`'s transcript list
to the first N in sorted (path) order - useful for exercising a slice of a source tree that can run
to tens of thousands of files in a real deployment, without walking the whole thing. Applied
identically to a real sweep and to `--dry-run` (one walk implementation, one place the cap lives).
It bounds candidates WALKED, never sessions STORED: the existing already-known skip still applies
on top, and the orphan-object catch-up pass (reads `objects/`, not the source tree) is untouched.
A malformed value (missing, non-numeric, zero, or negative) is a usage error, exit 2, matching
`--source`'s own validation posture - a silent `--limit 0` would look identical to a fresh, empty
warehouse. Narrowing a run loses nothing: a later unlimited sweep still picks up whatever a limited
one left behind, the same property `--since`/`--until` already have.

12 new oracle tests (`tests/test_sweep_limit.py`), proved red-then-green with a real `git stash` of
just the production diff (8 of 12 failed pre-fix; the other 4, the usage-error tests, were already
satisfied by the pre-existing "unrecognised option" guard before `--limit` was a known flag -
correctly unaffected, not a gap). Full suite: 1,175 passed, ruff clean, pyright 0 errors.

One commit, pushed. Ticket 28's own entry and this file's backlog pointer were both updated in
place.

**What was NOT done:** nothing new opened this handoff. Standing candidates for a future session:
ticket 28's remaining backlog items (28.2, 28.9, 28.10, 28.11, 28.12, 28.14), and `ccw share --open`
as a possible fast follow-up to 28.1's work above.

---

**Fourteenth handoff, 2026-08-24 (new session).** Opened by reading this file (the thirteenth
handoff, above), which pointed straight at ticket 28.9's "ACTIVE TASK" section and its
operator-approved two-fix plan. Did Fix A only, exactly as that section specified: build it,
test it for real (gates + re-profile + a real Chrome tab), stop before Fix B.

**Fix A DONE.** `_render` and `_render_page` (`src/cc_warehouse/render.py`) now encode each
fragment to UTF-8 bytes and join with `b"\n".join(...)` instead of joining `str` and encoding
afterward - the fix scoped to exactly these two functions' final join, not the "dozens of call
sites" the ticket's own plan predicted might be needed, because encoding at that one boundary
per function was enough to stop the astral-plane 4x-inflation from reaching the whole document.
`render_markdown`/`render_html`'s PUBLIC return type changed from `tuple[str, str]` to
`tuple[bytes, bytes]` (both `build.py` call sites were encoding the result immediately anyway,
so `build.py` simplified rather than grew). That public-type change reached ~40 call sites
across 10 test files (`test_matrix.py`, `test_real_shapes.py`, `test_render_html.py`,
`test_render_html_regressions.py`, `test_render_md.py`, `test_render_md_regressions.py`,
`test_surrogates.py`, `test_thinking_withheld.py`, `test_truncation.py`, `test_chrome.py`) -
each fixed by decoding to `str` once at the point of use (a shared helper where one already
existed, e.g. `test_matrix.py`'s `_rendered`, otherwise a small local wrapper), with zero
assertion logic changed anywhere. `test_surrogates.py` needed one real adaptation, not just a
decode: two tests used to call `.encode("utf-8")` on the result to prove a lone surrogate didn't
break rendering; that encode now happens INSIDE `render_markdown`/`render_html`, so calling the
function at all (and it not raising) is now the assertion.

**Verified, not assumed, at every step**: full suite 1,175 passed, ruff clean, pyright 0 errors
(one pre-existing, unrelated pyright gap in `tests/test_render_open.py` was found and confirmed
via `git stash` to predate this session - not touched, out of scope for this ticket). Output
proved byte-identical before/after via `git stash`/`stash pop` around the production diff, on
TWO independent payloads: the ticket's own synthetic repro (1.60 MiB in, 40 turns) and a real
8.3 MB session pulled from this machine's own `~/.claude/projects` - all 5 projection files
(`transcript.md`, `transcript.compact.md`, `conversation.html`, `conversation.compact.html`,
`manifest.json`) matched with `cmp` both times. Peak memory on the synthetic repro dropped from
61.16 MiB to 28.00 MiB (peak/input ratio 38.18x -> 17.48x) - beating the ticket's own ~26 MiB /
~27x estimate, because the fix landed in both `_render` (markdown, called a second time inside
`_render_page` for the whole-transcript copy payload) and `_render_page` (HTML) rather than only
the HTML page's own join the estimate was based on.

**The real-browser check ran twice** - the Chrome extension was not connected on the first
attempt (a live occurrence of the same environment gap prior handoffs hit, not a new finding),
and the operator was asked to reconnect it rather than the session skipping the check or
declaring the fix done on `pytest` alone. On retry: the real 8.3 MB session's `conversation.html`
served over `127.0.0.1:8917` and opened in an actual Chrome tab via `claude-in-chrome`. Zero
console errors on load and after interaction. All four copy-button levels clicked with the
clipboard read back programmatically (`navigator.clipboard.readText()`, comparing against
`transcript.md` fetched from the same server): the whole-transcript button's output is
CHARACTER-IDENTICAL to `transcript.md` (545,316 chars, `===` true), and the row/phase/turn
buttons' output is each a substring of it - directly exercising
`test_copy_as_markdown_payloads_equal_transcript_fragments`'s own guarantee outside pytest, not
just trusting the test. Icons (including the astral-plane ones Fix A is about) rendered correctly
and round-tripped through copy intact, e.g. a row-level copy came back as
`"<details>\n<summary>🧩 session events</summary>..."` (a real 🧩 JIGSAW PUZZLE PIECE,
un-mangled).

One commit, pushed: `fb85934`, `fix: cut render_html/render_markdown peak memory 2x (ticket
28.9, Fix A)`. `harness/tickets/28-backlog.md`'s 28.9 entry and this file's "ACTIVE TASK" section
were both updated in place with the full account, matching every other closed step in this file.

**The operator then said: do Fix B in a new session, stop here now.** Fix B (the four-level
copy-as-markdown base64 duplication, Mechanism 2 in the ACTIVE TASK section above) was NOT
started - no code read or written toward it beyond what the investigation already covered before
this handoff. The two candidate shapes (server-side reuse vs. client-side reconstruction) are
still an open pick for whichever session does Fix B; see step 3 of the plan above. This file's
top "Next task" pointer and the ACTIVE TASK section's own status line were updated to send a
fresh session straight at Fix B rather than back through Fix A's now-closed investigation.

**What was NOT done:** Fix B, and everything downstream of it in the plan (step 4's browser
test). Nothing else was touched this handoff.

---

**Fifteenth handoff, 2026-08-24 (new session).** Opened by reading this file (the fourteenth
handoff, above), which pointed straight at ticket 28.9 Fix B. Before touching that, the
operator asked for the `claude-code-dashboard-live.html` file to be opened in a real browser
(served over loopback, per the "Two environment facts" section - the browser tool refuses
`file://`), which was done cleanly, then killed on request. The operator then set a standing
preference, now recorded in memory (`give-full-paths-and-links.md`): use `~/...` in any path
shown to them, never the literal `/Users/<name>/...` form (it leaks the machine's real
username into anything that records the text), and do not spin up a local server by default
for a plain file path - only when the browser tool itself needs one.

Asked how deterministic `dashboard.py` is and how long the pipeline takes, and told to go
measure it rather than guess. **A real mistake happened here**: checking `dashboard.py
--help` (which the script does not support) actually ran `collect.py` for real against the
LIVE `~/.cc-warehouse/stats/` data instead of a scratch copy - this session's own memory rule
about testing with `CCSTATS_OUT` was not applied. Disclosed immediately, confirmed harmless
(refreshed the real stats DB early, touched nothing session-related, no `.building` file left
behind), and the operator approved rebuilding the live dashboard page to match. Measured
result, real data: `dashboard.py` is deterministic except one timestamp field (byte-identical
output twice, confirmed with `cmp` after normalising that one field); the full pipeline
(`collect.py` + `dashboard.py`) takes under 10 seconds warm, ~30-45s cold (estimate from an
earlier session's own measurement on a then-smaller corpus).

**The operator then asked to check whether real sessions in `~/.claude` were going
uncaptured**, suspecting the SessionEnd hook itself might not be firing. It was firing fine
(307/307 real hook-log entries "ok", zero errors) - the real, live finding was a 37-session
backlog from the prior ~2 hours, which `ccw sweep` cleared. **The operator explicitly rejected
this as "just a temporary manual fix"** and asked for the actual mechanism and real, durable
fixes, presented as options first. That investigation surfaced two independent, previously
undiscovered real bugs, found by reading logs and code directly rather than guessing:

1. **The weekly `ccw archive --to` job had been silently failing for two weeks** (612 real
   items failing, 0 folders written on its last real run) - `archive.migrate`'s vault-gone
   fallback path (a stale/missing archive folder falls back to reading the OLD vault store)
   was never updated when `objects/` was retired (ticket 27.4, 2026-08-20), so it tried to
   read a directory that no longer exists. Fixed same-session, oracle-tests-first, verified
   on real production data (`ccw archive --to ~/cc-warehouse-archive`: 612 failed -> 8 failed
   after the first fix, then 8 -> 0 after a second fix for the genuinely-permanent case
   below). Commits `db03dd6` (the vault-fallback fix, landed BEFORE the plan-mode arc below)
   and `24c9ea6` (the permanent-non-session case).
2. **`sweep()` has no per-item exception boundary at all** (`capture_transcript`'s own
   docstring already said so: "any deeper failure propagates to the caller's never-raise
   boundary" - the HOOK path has one, `_run_hook`; sweep does not) - one contended catalog
   write can silently abort the ENTIRE daily sweep batch mid-run, with nothing printed or
   logged, and everything still queued in that run simply never attempted (picked up by the
   next sweep, not lost, but invisible in between). This exact gap was already flagged, not
   yet fixed, in `harness/tickets/31-sweep-full-corpus-cost.md` section 31.4 (2026-08-20,
   "logging only... the retry loop stays unshipped... blocked on a confirmed exception").

**Entered plan mode** (operator-approved, `Plans/majestic-floating-cray.md`) to design real
fixes rather than another catch-up, after two Explore-agent codebase surveys both failed
twice on a transient Anthropic API 529 (server overloaded) - rather than keep retrying, every
file was read directly instead (`capture.py`, `catalog.py`, `store.py`, `sweep.py`, `cli.py`,
`notify.py`, `doctor.py`, `contract/DESIGN.md`'s R14, the freshness-check plugin and its
tests). The operator's own explanation of `win_go_app_test`'s rapid-fire session bursts
(Herdr/subagent-driven automated testing, confirmed NORMAL, not a bug to chase) shaped the
final plan: the real fix is tolerating that load, not investigating that project further.

**Four pieces shipped, each oracle-tests-first (red confirmed against unfixed code, then
green), each committed and pushed separately:**

- **Retry-with-backoff on catalog writes** (`capture.py`, commit `5aef3d3`). The real answer
  to "run captures without stepping on each other": SQLite's own reserved lock (`BEGIN
  IMMEDIATE` + the existing 5s `busy_timeout`) already coordinates writers (R14) - the gap
  was giving up after exactly one wait. `_capture_locked`'s two catalog calls now retry up to
  3 times on `sqlite3.OperationalError` matching "locked"/"busy" only; any other exception
  still raises immediately, unchanged.
- **Sweep per-item safety net + a durable failure log** (`sweep.py`, commit `a19710a`),
  directly answering both "stop one bad session from killing the batch" and "log bad sessions
  for review". `_capture_item` now catches any exception (matching `_archive_subagent`'s own
  existing pattern a few lines above it in the same file), logs it to the same
  `logs/capture.jsonl` the hook path's stage-failure logging already uses, and lets the batch
  continue. `BatchReport`/`ItemOutcome`'s shape is unchanged.
- **Watch the 3 real launchd jobs for failures** (`plugins/cc-capture/hooks/ccw-freshness-
  check.py`, commit `8d88cea`), directly answering "watch the daily/weekly jobs" - `ccw
  doctor`'s own PASS/FAIL verdict never covered these at all, which is exactly why the
  archive-job incident above sat unnoticed for two weeks. Shells out to `launchctl print
  gui/<uid>/<label>` for `com.captaincodeau.ccw-sweep`/`-archive`/`-repair`, best-effort and
  guarded (never blocks session start; a missing `launchctl`, e.g. non-macOS, reads as
  unknown, not broken).
- **Backlog growth-rate context on an already-escalating alert** (same file, commit
  `e35b7b6`), answering "alarm on a fast-growing backlog, not just a broken job" - applying
  this file's own hard-learned lesson (ticket 24.7's first draft alarmed on the raw
  uncaptured count and fired every session on a healthy machine): the growth rate rides along
  as context on a message the doctor-streak signal ALREADY decided to show, never as an
  independent trigger, because this session's own real numbers (37 in ~2h from ordinary
  multi-session usage, ~18/hr) are not reliably distinguishable from a real problem by rate
  alone.

**Verified against real production state at every step, not just pytest**: full suite grew
from 1,175 to 1,197 passing tests across the arc; ruff and pyright stayed clean throughout
(one pre-existing, unrelated pyright gap in `tests/test_render_open.py` predates this
session, confirmed via `git stash`, not touched). The frozen `ccw` binary was reinstalled
(`uv_tool_reinstall_current_project --no-extras`) after the code changes - this session
independently re-discovered the "editing the repo does not change what runs" trap
`CLAUDE.md`'s own hard rule already documents, the first time by forgetting it (an accidental
real-data `collect.py` run, see above), the second time by verifying a fix against the OLD
binary and getting confused before catching it. The real weekly `ccw archive --to` job was
run for real (`517 folders written, 0 failed`, exit 0) and the real launchd job was
kickstarted end-to-end (`launchctl kickstart`), confirmed via a background wait to finish
with `last exit code = 0`, and the freshness-check script confirmed silent afterward. The
plugin cache (a SEPARATE deployment surface from the `ccw` binary - Claude Code reads
`~/.claude/plugins/cache/cc-warehouse/cc-capture/<commit-hash>/`, not this repo directly) was
stale until the operator ran `/plugin marketplace update cc-warehouse` and `/reload-plugins`
themselves at the end of the session; confirmed byte-identical to this repo's copy afterward
(`diff`, exit 0) against the new cache directory `e35b7b6bb2bc`, matching this session's own
final commit hash exactly.

**What was NOT done:** ticket 28.9 Fix B (see "Next task" at the top of this file - entirely
untouched this session, the redirect happened before it was ever started). No other open
item from this file's own tracking was touched.

---

**Sixteenth handoff, 2026-08-24 (new session).** Opened by reading this file (the fifteenth
handoff, above), which pointed straight at ticket 28.9 Fix B. Before touching it, the operator
asked to look at a specific number on the live dashboard - `~/.cc-warehouse/stats/claude-code-
dashboard-live.html`'s "1.2 min / typical session length" tile looked wrong - and asked for a
thorough, wide-blast-radius investigation into whether the dashboard's numbers were correct at
all: double-counted, missing, or stale values were all named as suspects. Fix B was NOT started
this session either.

**Investigation, not guesswork.** Three parallel Explore agents each read one full source file
(`dashboard.py`, `dashboard_template.html`, `collect.py`) and reported every SQL query, every
JS computation, and every column derivation verbatim with file:line refs. Every consequential
finding was then independently re-verified first-hand: real `sqlite3` queries against
`~/.cc-warehouse/stats/sessions.sqlite` (read-only), a real `find` census of both source trees'
sub-agent filenames, and a decode of the actual bytes in the shipped HTML file. Four real,
distinct defects were found and confirmed, none of them guesses:

1. **A sub-agent transcript existing in BOTH the archive and the live tree was stored TWICE.**
   `collect.py:1364-1367` keyed a scanned transcript by its raw filename stem; the archive names
   a sub-agent `<id>.jsonl`, the live tree keeps Claude Code's own `agent-<id>.jsonl` - different
   stems, different dedup keys, so the "duplicate payloads collapsed" pass never paired them.
   Measured: 1,908 pairs, all with IDENTICAL size/cost/engaged-time (1,908 of 1,908), inflating
   every summed figure corpus-wide by +US$5,750, +119 engaged hours, +69,518 turn rows.
2. **`is_real = 1` blended three unrelated populations into one "session" count**: the
   operator's own interactive sessions (`entrypoint` `cli`/`local-agent`/NULL, the last being
   138 real sessions that predate Claude Code recording the field at all, 2026-02-14..03-11),
   automated one-shot API calls (`entrypoint='sdk-cli'` - one prompt, a few seconds, zero tool
   calls: hooks, titling), and Task sub-agent runs (`is_subagent=1`). Measured: 46.5% of
   "sessions" in the default range were the latter two. This, not arithmetic, is why the tile
   read 1.2 min - the median was correct for the 6,443-row set the page was actually counting;
   that row set was never "your sessions".
3. **The tile itself measured `wall_seconds` (raw file span, includes idle), not
   `engaged_seconds`**, contradicting `PANEL-CONTRACT.md`'s own house rule and the tile's own
   label, with no disclosure either way.
4. **The shipped page carried NO project exclusions at all** (`default_unticked_projects: []`,
   verified by decoding the real HTML's embedded payload) even though
   `~/.cc-warehouse/stats/dashboard-defaults.json` listed six real patterns - `dashboard.py`
   never read that file, only `.claude/commands/dashboard.md`'s own flag-passing did, so a
   direct run (which is what built the page currently on disk) silently dropped them.

Full measured comparison (default range): page showed 6,443 "sessions" / 1.2 min typical /
US$65,310; the operator's true 666-673 interactive sessions measured 55-116 min typical (wall
vs. engaged) / US$54,229-54,524 - sessions +867%, tool calls +65%, replies +62%, cost +20%,
typical length 96x too low.

**Plan approved via ExitPlanMode, then a 2-option question on the one real design fork**: keep
all three populations but split them behind a toggle (recommended - sub-agent cost is real
money, hiding it is worse than blending it), vs. hard-filter to interactive sessions only and
drop the other two from the page entirely. **Operator chose the toggle**, with the exact default
tick-state specified in the question's own preview.

**Four fixes shipped, in dependency order, each proved red-then-green against a real `git
stash` of just its own production diff:**

1. **The double-count (D1)** - `collect.py:1364-1367` strips a leading `agent-` from a
   sub-agent's key before building its cache/dedupe identity; `CACHE_SCHEMA_VERSION` bumped
   1->2 so the one already-populated `scan-cache.sqlite` (97.9% of the corpus, all from a prior
   run) can't serve a stale per-tree row back out under the OLD key. Verified against real data:
   `is_real=1` row count dropped from 10,128 to 8,264 on rebuild, sub-agent files ~halved (3,821
   -> ~1,930), matching the measured 1,908-pair defect almost exactly (small residual is normal
   corpus growth between the two measurements, this machine captures continuously).
2. **The population split (D2)** - new `dashboard.py` classifier `session_kind()` (`is_subagent`
   wins first -> `subagent`; `entrypoint='sdk-cli'` -> `automated`; everything else, including
   the pre-field-recording NULL rows -> `mine`), a new `kind` column in the embedded payload
   (`lookups.kinds` + one int per `S` row, looked up by NAME client-side via `KIND_IDX`, never a
   hardcoded 0/1/2), and a new "Count as a session" control in the page's existing top filter
   bar - `[x] my sessions N  [ ] sub-agent runs N · US$c  [ ] automated one-shots N · US$c` -
   defaulting to `mine` only, each label live-updating via a new `kindCounts()` (date+project
   filtered, kind-toggle-independent on purpose, so a reader sees what TICKING a box would add
   rather than watching a number vanish the moment they tick it).
3. **The tile (D3)** - `dashboard_template.html`'s Overview panel now sorts/medians
   `IDX.S.engagedSec`, not `wallSec`; the note now says which column and which populations
   ("whichever kinds are ticked above").
4. **The exclusions (D4), two parts.** `dashboard.py` gained `load_default_filters()`, reading
   `<out_root>/dashboard-defaults.json` directly as a fallback when no `--include`/`--exclude`
   flag is given, so a direct run and a `/dashboard` run can no longer disagree. Separately, a
   real correctness bug found alongside it: `state.excluded` was keyed on the RAW project index
   while the Projects/Project-month panels grouped by the CANONICAL name (auto agent-worktree
   folders folded onto their parent, `CANON_PROJECT`) - un-ticking a parent left its worktree
   children ticked, and their hours reappeared folded under the very name just excluded. Fixed
   by keying BOTH sides on the canonical name (`CANON_LIST`, `defaultExcludedNames()`); the
   project checklist now also shows one row per real project instead of one per throwaway
   agent-worktree folder, a side benefit of the same fix.

**Step 5 of the approved plan (make the Concurrency panel and its two Overview tiles obey the
new project/kind filters too, via a client-side interval sweep over per-session start/end
timestamps) was explicitly named as the one deferrable piece in the plan itself, and was
deferred** - real timezone-aware calendar-day clipping (`build_overlap` in `collect.py`) is
genuinely complex to reimplement correctly client-side, the panel was never the operator's
actual complaint, and a wrong reimplementation would be worse than an honestly-labelled
limitation. Took the plan's own documented fallback instead: the D1 fix already cleans
`overlap_day`'s numbers (it's built from the same, now-deduplicated `session` table), and the
two Overview tiles' notes now say "whole corpus" on the tile itself, closing a real disclosure
gap `PANEL-CONTRACT.md` had claimed was already closed but wasn't.

**A new headless test harness, `tools/ccstats/tests/node/dashboard_probe.js`, is the other
lasting change.** Before this session `dashboard_template.html`'s client-side JS had ZERO test
coverage - nothing had ever executed it - which is how all four defects above shipped with a
fully green `pytest` suite. The harness runs the REAL generated `<script>` block (not a copy)
under Node's `vm` module against a minimal hand-built DOM stub (real enough for this page's
exact usage: id lookups, classList, dataset, one delegated `querySelectorAll` target; a broader
page rewrite would need it extended, which is intentional - it forces a human to look rather
than silently degrading). One non-obvious mechanic worth remembering: `vm.Script.runInContext`
does NOT attach top-level `let`/`const` bindings as properties of the context object (only `var`
would), so reading `context.FS` after the script runs returns `undefined` even though the
script ran fine - the fix is appending a small epilogue INSIDE the same script text
(`;globalThis.__probe = { state, ... };`) so it shares the real lexical scope, and using
closures/accessor functions (`getFS: () => FS`) for anything the page later REASSIGNS (`FS =
[]` inside `recomputeFilteredSessions`), since a captured snapshot goes stale the moment a
scenario re-triggers `renderAll()`. `test_dashboard_headless.py` (new) builds a tiny synthetic
`sessions.sqlite` with hand-computed expected numbers - 5 "mine" rows with engaged minutes
10/20/30/40/50 (median 30, cost $15.00 exactly), 2 sub-agent and 2 automated rows, one project
and its auto-worktree-suffixed child - and asserts the ACTUAL rendered tile text and `FS.length`
against those hand-computed numbers, never against `dashboard.py`'s own aggregation code, so a
bug in either the Python payload builder or the page's own JS is equally able to fail it. Also
confirms the canonical-exclusion fix directly: excluding the parent's name removes the worktree
child's session too.

**Verified for real, at every layer, matching this project's own "test the code, don't just
read the output" lesson**: 6 new headless tests + 7 new `session_kind()` tests + 8 new sub-agent
dedup tests, all proved red-then-green against real `git stash`ed production diffs; full
ccstats suite grew 110 -> 131 passing; main repo's 1,197-test oracle suite and pyright stayed
untouched and green (one pre-existing, unrelated pyright gap in `tests/test_render_open.py`,
confirmed via `git status` to predate this session, not touched); ruff clean repo-wide. A
scratch rebuild (`CCSTATS_OUT` pointed at a session-scratchpad dir, never
`~/.cc-warehouse/stats`) was run through the real `collect.py` + `dashboard.py` pipeline on this
machine's REAL corpus and opened in an actual Chrome tab via `claude-in-chrome` (loopback-served
on `127.0.0.1:8931`, `file://` is refused by the browser tool - see "Two environment facts"
below): zero console errors on load and after interaction; the default view read exactly "668
sessions with a reply" / "55.6 min typical session length" / "US$ 54,506 API cost", matching the
headless probe's own numbers to the byte; ticking "sub-agent runs" live-recomputed every tile
with no reload (668 -> 2,184 sessions, "typical session length" 55.6 -> 4.6 min - directly
demonstrating the exact mechanism that produced the original 1.2 min bug - and API cost US$
54,506 -> 60,053, matching 54,506+5,547 exactly); the project checklist showed one row per real
project, named worktrees (e.g. `-.worktrees-ui-first`) correctly left un-folded per the existing
rule. Server killed and tab closed afterward.

Two commits, both pushed: `cf71d3c` (the collect.py dedup fix + its tests) and `4898c5f` (the
dashboard classifier, toggle, tile fix, exclusion fixes, the new Node harness, and their tests).
Every fix was verified against a session-scratchpad copy FIRST, before touching real data.

**The real `~/.cc-warehouse/stats` was then rebuilt for real, with the operator's explicit
go-ahead (asked via a 2-option question).** `collect.py`: `real_sessions` 10,128 -> 8,265 (the
D1 dedup fix landing on the real corpus, matching the scratch-run's proportional drop almost
exactly). `dashboard.py`: the real, already-existing `dashboard-defaults.json` (32 raw project
names, six patterns, saved by a prior session's `/dashboard` run) was picked up automatically
via `load_default_filters()` with NO flags passed - confirmed by decoding the rebuilt page's own
embedded payload (`default_unticked_projects`: 32 entries, was `[]`) - proving the D4 fix on the
real file it was written to fix, not just the synthetic one. Opened in a real Chrome tab
(loopback, `127.0.0.1:8932`): default view **488 sessions, 53.2 min typical session length**
(was 1.2 min), "Projects: 20 excluded" (32 raw names folded to 20 canonical, the D4b fix),
zero console errors. Both temporary HTTP servers (scratch on 8931, real on 8932) were killed and
both tabs closed afterward; nothing was left running.

**Three more operator follow-ups, same session, after seeing the toggle live, all DONE:**

1. **"sub-agent runs" now defaults ON too** (`DEFAULT_KINDS` -> `{mine, subagent}`), only
   "automated one-shots" still defaults off - a sub-agent is real work done on the operator's
   behalf, same as watching a Task call run. `test_dashboard_headless.py`'s default-view test
   rewritten for the new 7-row default population (was 5); a new test covers explicitly
   dropping to mine-only, since that is now the thing a reader has to opt INTO, not the default.
2. **The filterbar and panel-nav layout were tightened.** The filterbar wrapped onto three
   lines once the toggle row landed, with the summary line stranded alone on its own row -
   restructured into two explicit rows instead of one unconstrained wrapping flex row.
   Fixing this surfaced a real, separate bug: the sticky panel-nav bar below it was pinned at
   `top: 49px`, a hardcoded guess matching the OLD single-row filterbar height, already stale
   the moment the toggle row was added - replaced with `setNavTop()`, which measures the
   filterbar's real rendered height (re-measured on resize) instead of guessing. The panel-nav
   links themselves were also restyled from plain inline text (read as one continuous run) into
   bordered chips, with a permanent edge-fade (`mask-image`) on the scrolling strip as a visual
   "there's more this way" cue. `dashboard_probe.js`'s DOM stub gained `document.querySelector`,
   `document.documentElement`, and real `style.setProperty`/`getBoundingClientRect` stubs,
   needed by the above - the harness needing extension for a UI-only change is by design (its
   own header comment says so), not a gap.
3. **The real, saved `~/.cc-warehouse/stats/dashboard-defaults.json` held the WRONG exclude
   list**, discovered when the operator looked at the live "Projects" dropdown and it didn't
   match what they remembered dictating. Confirmed by direct comparison: the file on disk (6
   generic patterns - `.claude-worktrees-agent-`, `.worktree`, `private-tmp-`,
   `private-var-folders-`, `scratchpad`, `orchestration-drill`, mtime 2026-08-24T01:25, before
   this session started) does not match `CLAUDE.md`'s own "Fourth round" record of the
   operator's real 23-pattern list from 2026-08-22. **This was not introduced by this
   session** - the file was never written by anything in this session, only read, and its
   mtime predates this session's start. Something earlier today (not identified, not this
   session) replaced the operator's real list with a generic scratch/noise filter. Restored the
   real 23-pattern list from `CLAUDE.md` verbatim (tmp-file + `os.replace`, R2's idiom, even
   though this file lives outside the repo entirely). One value needed reconstruction:
   `CLAUDE.md` redacts the operator's real local username as `<local-username>-` (this repo's
   own privacy rule for anything git-tracked); the real machine account is `fonzarelli` -
   confirmed, not assumed, by checking that real `project_label` values starting with
   `fonzarelli-` actually exist in the corpus (`fonzarelli-.claude`, `fonzarelli-Temp`, etc. -
   Claude config/library folders outside `~/CODE`, exactly what that pattern exists to catch)
   before writing it. Dashboard rebuilt with the restored list: 58 raw names -> 57 canonical
   exclusions (was 32 -> 20 under the stale list), "my sessions" 564 (was 668). Verified in a
   real Chrome tab, zero console errors. **This file lives outside the repo
   (`~/.cc-warehouse/stats/`, not tracked in git at all per this project's own DATA-vs-CODE
   separation) - nothing to commit for this fix, it is a local-data correction only.**

One commit, pushed (`c10c851`, items 1-2; item 3 has no git artifact by design - see above).
132 ccstats tests passing, ruff clean.

**What was NOT done:** ticket 28.9 Fix B, again untouched - this is now the SECOND handoff in a
row where an operator-initiated redirect landed before Fix B was ever started (see "Next task"
at the top of this file). Step 5 of the dashboard plan (client-side concurrency reimplementation)
was explicitly deferred, not forgotten - see above. **Also unresolved and worth a future
session's attention, not chased down here**: WHAT overwrote the real `dashboard-defaults.json`
with a generic list sometime before 2026-08-24T01:25 - no session's own account in this file
claims to have done it, and the mechanism is unknown.

---

**Eighteenth handoff, 2026-08-27 (new session).** Opened by reading this file, then the operator
ran `/dashboard` directly (a fresh build + real-Chrome look, nothing else) rather than picking up
ticket 28.9's own backlog candidates (28.2/28.10/28.11/28.12/28.14, `ccw share --open` - none of
these were chosen or touched this session). Two follow-up asks landed after that, both about the
live dashboard's UI, not its data pipeline.

**1. Sub-agent population split.** The operator's own framing: sub-agent runs get counted as "a
session" today, which is right for some stats and wrong for others - asked for the two groups
worked out with reasoning, not guessed. The mechanism: every `session` row already carried a
`kind` (`mine`/`subagent`/`automated`, from the sixteenth handoff's own `session_kind()`), but
ONE page-wide toggle applied that classification to every panel identically - `inRange()` fed a
single `FS` array to all 20 panels. Split into two populations instead: `FS` ("my own work" -
sub-agent NEVER counted, because a sub-agent's engaged time sits INSIDE its parent session's own
clock time, so counting it again double-counts minutes) and `FSW` ("real work done" - sub-agent
ALWAYS counted, because its cost/tokens/tool-calls are genuine extra spend, not nested time).
`inRangeInteractive`/`inRangeWorkload` replace the old single `inRange`; `DEFAULT_KINDS` dropped
to `{mine}` alone (was `{mine, subagent}`); the "sub-agent runs" checkbox was removed from the
filter bar entirely (`.claude` reader can no longer toggle it - the rule is now fixed per panel,
by design, since a single toggle literally cannot serve two contradictory questions at once).
9 of 20 panels (Projects, Repositories, Project x month, Models, Model x month, Tokens, Thinking,
Tools, Skills & agents) now read `FSW`; the rest (Daily/Weekly/Monthly, Session sizes, Hour
heatmap, By weekday, Worktrees, Top/Longest sessions, and most of Overview's 15 KPI tiles) stayed
on `FS`. Two genuine judgment calls were put to the operator as a 2-option `AskUserQuestion`
rather than decided alone: **Tools panel now counts sub-agent tool calls** (real work, delegated
or not); **the "25 most expensive sessions" leaderboard excludes sub-agent runs** (it is a
leaderboard of the operator's OWN sessions, not a cost bucket). Overview's KPI accumulation loop
was split into two passes (one over `FS`, one over `FSW`) since it mixes both kinds of tile in one
panel - `session_kind()`'s own Python-side docstring in `dashboard.py` was updated to match, since
it used to claim sub-agent was "reachable via a toggle", which is no longer true.

Verified: `tools/ccstats/tests/test_dashboard_headless.py`'s three toggle-behaviour tests were
REWRITTEN, not just made pass again - they tested the OLD one-toggle behaviour on purpose, so a
green run against the new code would have meant the fix was reverted, not confirmed. The rewrite
adds an explicit regression guard that a scenario still naming `"subagent"` in `kinds` (mimicking
the removed checkbox) has ZERO effect on either population. Full suite: 132 passed (was 129
before this session even started, unrelated to this change), ruff clean, pyright unchanged (82
pre-existing errors, all in `tools/` which is outside strict `src/` by design, confirmed via
`git stash` that the count is identical before/after). The REAL `~/.cc-warehouse/stats` dashboard
was rebuilt from live data and headless-probed against the actual generated HTML (not a test
fixture): `fsLength` 661, `fswLength` 1950, "API cost" tile `US$ 53,747` - all three independently
cross-checked against a fresh direct SQL query (`is_real=1`, the same date window, the operator's
real 23-pattern exclude list applied) and matched exactly. Opened in a real Chrome tab over
loopback: 0 console errors, "sessions with a reply" 661 / "typical session length" 45.8 min (both
`FS`-driven, sub-agent excluded) alongside "API cost" `US$ 53,747` / "tool calls" 119,546 (both
`FSW`-driven, sub-agent included) rendered correctly side by side on the same page. Commit
`ee5d65a`, pushed.

**2. Layout gap + always-visible note, both operator-reported after looking at the rebuilt
page.** The note ("Sub-agent runs are handled automatically per chart...") read as too prominent
sitting permanently in the filter bar. Converted to a small `data-tip`-driven hover icon (an "i"
in a circle, reusing the page's own existing chart-tooltip mechanism, `.cc-tooltip` /
`document.addEventListener("mouseover", ...)` - no new JS infrastructure needed). The same
mechanism was used to answer the operator's own on-the-spot question ("what is this
`2,414 · US$ 66`?" - the live count/cost of "automated one-shots", off by default) by attaching a
second tooltip directly to that checkbox, so the answer now lives on the page itself, not just in
chat. Separately, a real ~100px dead gap above the date filters: `<header class="mast">` was
wrapped in the generic `.wrap` class, whose `padding: 0 28px 96px` exists for the PANELS wrap at
the very bottom of the page - reused on the header, its 96px bottom padding just opened a gap
nothing needed. Split into a new `.mast-wrap` (same max-width/centering/side-padding, zero bottom
padding of its own) confirmed via `grep` to be the only two places `.wrap` was used before
touching either.

Verified: 132 tests still green (no test covers pixel layout or tooltip visibility - this was a
real-browser-only check, matching this project's own "the only guard against a UI regression here
is a human looking" note from the sixteenth handoff). Rebuilt the real dashboard again, opened in
a real Chrome tab: 0 console errors before and after the change; a before/after screenshot pair
confirmed the gap closed and the filter bar visibly tightened; hovering the new "i" icon and the
"automated one-shots" label both showed their correct tooltip text and stayed hidden otherwise.
Commit `8f3b4ab`, pushed.

**The operator asked whether `.claude/commands/dashboard.md` also needed updating. Checked, not
guessed: it does not.** Read the whole command file - every step (resolve `$OUT`, refresh
`sessions.sqlite`, read/write `dashboard-defaults.json`, the `--exclude`/`--include` build flags,
serve over loopback, stop the server) is about the BUILD/SERVE workflow, none of which changed
this session. Nothing in the command's own text describes the generated page's internal filter-
bar wording, tooltip behaviour, or layout, so nothing in it went stale. Confirmed to the operator
rather than editing on a guess.

**What was NOT done:** ticket 28.9 remains closed and untouched (unrelated to this session's
work). None of the standing backlog candidates (28.2/28.10/28.11/28.12/28.14, `ccw share --open`)
were picked - still open, still the operator's to choose. Step 5 of the sixteenth handoff's own
dashboard plan (client-side concurrency reimplementation) remains deferred, not touched here
either. The unresolved `dashboard-defaults.json` overwrite mystery from the sixteenth handoff is
still unresolved - not chased down this session.
