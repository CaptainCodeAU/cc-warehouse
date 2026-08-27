# Ticket 28: backlog, recorded so nothing is silently dropped

Not a slice. A register of everything named during the 2026-08-03 investigation
that is real but not on the ticket 22-27 critical path. Items graduate out of
here into their own ticket when they are taken up.

## Worth doing, small

- **28.1  `--open`. DONE 2026-08-24, scoped to `ccw render`.** Open the
  generated HTML in a browser. `notify.py:132` `open_folder` reveals the
  FOLDER; there was no equivalent for the page. The specimen had `--open` on
  four verbs (`local`/`json`/`web`/`all`, via stdlib `webbrowser.open`); this
  cut ships it on the one verb that is the direct match for "hand them their
  transcript" - a single session, `--session s:<key>` or ad-hoc - and leaves
  `ccw share`'s multi-session `index.html` for a later pass if wanted.

  Implementation reuses the SAME platform-opener mechanism `open_folder`
  already had (R9): `notify._open_with_system_default` is now the one shared
  primitive, with `open_folder` (reveals a folder, the `config.open_folder`
  opt-in) and the new `open_page` (opens one file, the `--open` CLI flag) as
  thin named wrappers - exactly the C12 pattern ticket 28.13's architecture
  review had just recommended. `_open_rendered_page` in `cli.py` picks the
  right file: the archive folder's `conversation.html` when `archive_root` is
  configured (mirroring `_reveal_target`'s own "the archive is the
  deliverable" precedent), else the personal `projections/` copy; best-effort
  and never fails the render (DESIGN 12), matching `open_folder`'s own
  contract.

  8 oracle tests in `tests/test_render_open.py`, proved red against a real
  `git stash` of just the production diff (7 of 8 failed pre-fix, the 8th -
  the pre-existing typo-guard regression test - correctly unaffected) before
  passing once restored. One test originally written for a third scenario
  ("keep_projections=false AND no archive_root -> nothing to open") was
  dropped after `config.py`'s own `_keep_projections` refusal proved that
  combination unreachable: it silently falls back to `keep_projections=True`
  rather than ever leaving a session with nowhere to render, so the
  no-op branch in `_open_rendered_page` is defensive rather than a state a
  real config can reach. Full suite: 1,163 passed, ruff clean, pyright 0
  errors.

- **28.2  Optional secret redaction on personal projections.** `ccw` redaction
  lives only in `share.py`; `build.py`, `render.py` and `capture.py` contain
  none, so personal projections are written unscrubbed. The retired
  `export_transcript.sh:18-19` scrubbed `github_pat_` and `gh[posru]_` from
  every file it generated. Defensible either way; currently inherited rather
  than decided.

- **28.3  `--limit` on sweep. DONE 2026-08-24.** Useful for exercising a slice
  of a large import. `--limit N` (and `--limit=N`) caps `sweep._walk_source`'s
  transcript list to the first N in sorted (path) order, applied identically
  to a real run and to `--dry-run` (R9: one walk, one place the cap lives).
  It bounds candidates WALKED, not sessions stored - the existing
  already-known skip still applies on top of whatever the cap lets through -
  and the orphan-object catch-up pass is untouched, since it reads `objects/`,
  not the source tree the flag exists to bound.

  A malformed value (missing, non-numeric, zero, or negative) is a usage
  error, exit 2, same posture as `--source`'s own validation (R5): a silent
  `--limit 0` would look identical to a fresh, empty warehouse, so it refuses
  loudly instead. Narrowing a run loses nothing, same property `--since`/
  `--until` already have: a later unlimited sweep still picks up whatever a
  limited one left behind.

  12 oracle tests in `tests/test_sweep_limit.py`, proved red against a real
  `git stash` of just the production diff (8 of 12 failed pre-fix; the other
  4 are the usage-error tests, which the pre-existing "unrecognised option"
  guard already satisfied before `--limit` was a known flag - correctly
  unaffected, not a gap in the tests). Full suite: 1,175 passed, ruff clean,
  pyright 0 errors.

- **28.22  Fence `ccw doctor`'s text output. DONE 2026-08-23.** Recorded
  2026-08-18 (ticket 30's Appendix, deployment facts from outside this repo).
  `~/.local/bin/ccw-watch` (a different repo, `fifty-shades-of-dotfiles`) runs
  `ccw doctor` at every Claude Code SessionStart on this machine and parses it
  with shell regex. Read `ccw-watch`'s actual source in the `fifty-shades-of-
  dotfiles` repo (its tracked copy of the installed script, confirmed
  byte-identical to the real `~/.local/bin/ccw-watch`) rather than trust
  the earlier "hook line's wording" description above, which turned out to be
  imprecise: ccw-watch never greps for the word "hook" at all. What it
  actually depends on is narrower - `status -eq 0` (doctor's exit code) plus,
  on the healthy path, `sed -n 's/.*Uncaptured: \([0-9]*\) session.*/\1/p'`
  (needs `status.py:152`'s literal `"Uncaptured: <digits> session"`), and on
  the broken path, `grep -E '^\s*FAIL'` (needs `doctor.py:440`'s literal
  `"FAIL"` prefix on a failed blocking check's line).
  `tests/test_doctor_external_contract.py` pins both by running those EXACT
  sed/grep commands (not a Python re-implementation that could drift from
  real shell regex semantics) against real `ccw doctor` output, healthy and
  broken. Verified the fence actually fences: mutated `status.py`'s literal
  string (`"Uncaptured:"` -> `"Not captured:"`), watched the sed-based test go
  RED with the exact real-world symptom, reverted, watched it go green again.
  Full suite re-confirmed green afterward (1,114 passed, ruff clean, pyright
  0 errors). No production code changed - this is a protective test only.

## Recorded, low value, not planned

- **28.4  `--repo` override.** `parser.detect_github_repo` auto-detects and has
  not failed. The specimen exposed a manual override.
- **28.5  Interactive session picker (`local`).** `ccw status` lists and
  `ccw render --session` renders; nothing joins them.
- **28.6  URL as input.** `ccw render <path>` takes a local path only. Low value
  while `web` is deferred.
- **28.7  `--gist`.** Deliberately NOT wanted: `ccw share` is the better
  replacement, with redaction and a self-contained page. Recorded only because
  it was in the specimen. (A 2026-08-03 report that `ccw` might already have
  gist support was wrong: the grep was matching re-GIST-ry.)
- **28.8  `web` / claude.ai import.** Excluded from this cut by the principal.
  DESIGN names claude.ai exports as a source, so this is deferred, not dropped.

## Known defects and debts

- **28.21  DONE 2026-08-05. The sidecar is now written by whatever CREATES the
  folder, so 27.4's prerequisite is met.** `capture._archive_project_file`
  refreshes the one project's `project.json` after its session lands, which
  covers the hook, `ccw sweep` and `ccw import` in one place because all three
  route through `capture.capture_transcript` (verified by running each, not
  assumed). `archive.write_project_files` keeps its behaviour and now LOOPS over
  the same single-project writer, so there is one sidecar renderer rather than
  two (R9/F8).

  THE SKIP IS LOAD BEARING, NOT TIDINESS. An unchanged sidecar is not rewritten,
  compared on CONTENT and never on existence, or a 4,756-payload import would
  rewrite one project's sidecar thousands of times. Cost measured on the real
  catalog rather than asserted, against the worst case (1,449 aliases, a 137 KB
  sidecar): `project_record` 0.89 ms, `write_project_file` no-op 0.70 ms, so
  about **1.6 ms added to a capture** whose hook timeout is 40 s.

  A SIDECAR FAILURE NEVER COSTS A CAPTURE, and that is the opposite of the
  payload write beside it. `_archive_source` raises when `keep_objects` is false
  because then nothing else holds the session; a sidecar is an index aid, so it
  gets its own try and is never re-raised (DESIGN 12). There is a test that
  makes the write fail and asserts the session still lands.

  THE PROOF IS THE ROUND TRIP THAT COULD NOT PASS BEFORE: capture only, `ccw
  archive` never run, delete the catalog, `ccw reindex`, and both labels and
  aliases come back. The fixture asserts it stored aliases FIRST, because a
  round trip over an empty set passes for the wrong reason (19f's lesson).

  A THIRD FENCE FIRED. R8's `test_guarantee_words_cite_their_proving_test`
  caught "byte-identical" in the new docstring. The word is load bearing (it is
  what the skip rests on) and it IS proven, so the proof registry gained an
  entry naming the test rather than the docstring being reworded to dodge the
  check. The registry's own comment says it "grows when a guarantee is added".

  **THE LIVE ARCHIVE WAS BROUGHT UP TO DATE THE SAME DAY** (principal's word),
  by calling `write_project_files` directly rather than re-running the bulk verb.
  57 sidecars became 90; exactly 45 files were written and 0 non-sidecar files
  were touched; `ccw archive --verify` reads 19,235 folders, 0 problems. The
  rebuild now recovers **4,906 of 4,913 aliases, 99.9%, up from 2.3%**, and the
  7 that do not come back are the 7 workflow journals, which have no project
  folder because they are not sessions. Full figures on ticket 27 beside the
  27.2 proof they update.

  The original finding, kept for the record:

- **28.21 (as first written)  `project.json` is written by ONE verb, so the
  disposable-index guarantee has silently lapsed for 33 of 90 projects.**
  Measured 2026-08-05
  against the real archive, through the product's own reader rather than a
  filesystem guess:

        label dirs on disk ............ 90
        read_projects recovers ........  57      <- unchanged since 2026-08-02
        aliases recovered ............. 114      <- unchanged since 2026-08-02
        INVISIBLE to a rebuild ........  33

  MECHANISM, found in code rather than inferred: `archive.write_project_files`
  has exactly ONE caller, `cli.py` in the `ccw archive` verb. The capture path
  (`_archive_source`) and `ccw import` both create label folders and neither
  writes a sidecar, and `archive.read_projects` SKIPS a folder that has none
  (`archive.py`, "A folder with no sidecar ... is SKIPPED rather than fatal").
  So every project folder born since the last bulk `ccw archive` run is invisible
  to a catalog rebuild. The 57 and the 114 are exactly the figures ticket 19f
  recorded at migration, which is the tell: nothing has been added since.

  WHY IT MATTERS AND WHY IT IS NOT URGENT. `write_project_files`' own docstring
  says the sidecar is "what makes the catalog a DISPOSABLE INDEX rather than a
  load-bearing database", and that until it exists the rebuild claim is "a claim
  the product cannot honour, and an unhonoured guarantee is the F6 class this
  project exists to ban". That is exactly the state 33 projects are in. But NO
  DATA IS AT RISK: the sessions, their JSONL and their projections are all on
  disk, and the LABEL survives because the label is the folder name. What would
  be lost on a rebuild is `project_alias`, so a renamed project would split in
  two on the next capture.

  THE CHEAP FIX IS NOT THE RIGHT FIX. Re-running `ccw archive --to` regenerates
  all 90 sidecars and is proven idempotent, but it also re-renders 19k folders
  and leaves the hole open for the next import. The fix is to write the sidecar
  on the path that creates the folder. Ties 28.10, which already lists
  "rename-then-rebuild for `project.json`" as a test gap.

  FOUND BY AUDIT, NOT BY A FAILURE, which is the argument for auditing: every
  gate was green, `ccw archive --verify` reported 0 problems over the whole tree,
  and the verify does not ask this question.

  **UPGRADED 2026-08-05 FROM BACKLOG ITEM TO PREREQUISITE OF 27.4, and the
  number is far worse than "33 of 90 projects".** Ticket 27.2's rebuild of the
  real archive recovered **114 of 4,913 aliases, 2.3%**. The project COUNT
  understated it badly: the 33 sidecar-less folders are not 33/90 of the aliases,
  because almost every alias learned since the 2026-08-02 bulk run lives only in
  the database. Sessions and labels round trip perfectly (19,233 of 19,233
  hashes, 90 of 90 labels); aliases do not. 27.4 deletes `objects/` on the
  argument that the archive is a complete substitute, and on aliases it is not.
  The measurement is in ticket 27 beside the rest of the 27.2 proof.

- **28.20  `ccw build` is O(everything) even when nothing changed.** Measured
  2026-08-04 on the real corpus: 14,246 sessions, 0 failed, **5:55 the first
  time and 6:04 the second**, back to back with nothing changed in between. Its
  docstring promises incremental ("a session whose files already hold the
  current bytes is left mtime-stable"), and that holds for the WRITE, but every
  head is still read from the store and fully re-rendered in order to compare.
  Since ticket 25 wired `build` into the end of `ccw sweep`, this is now the
  cost of every sweep that captures anything: about six minutes of CPU on the
  daily job. Tolerable at Background/LowPriorityIO, wasteful, and it will only
  grow with the corpus. A cheap skip (source hash plus render-options hash
  recorded in the manifest) would turn it into a stat walk.

  I ESTIMATED THIS WRONG TWICE, which is why it is written down with numbers:
  first "considerably slower", then "roughly a doubling, about 50 seconds". The
  real figure is a full re-render per build, unchanged on repeat.

  **STILL OPEN, but the pattern it proposed now exists elsewhere: see ticket 30
  (2026-08-18).** `archive.folder_is_current` is exactly the "source hash plus
  render-options hash recorded in the manifest" skip suggested here, built for
  the ANALOGOUS but distinct cost on `ccw archive`'s tree (measured there:
  20779 folders, ~40 minutes, every run). It also had to check a renderer
  fingerprint and the sub-agent list, not just source hash and config - see
  that ticket if this one is picked up, both for the predicate shape and for a
  regression it found live: a naive "manifest still matches" check alone let a
  DELETED sibling file (e.g. `transcript.md`) go unrestored, which is directly
  relevant here since `build()`'s OWN per-head loop (`_read` then
  `write_projection`) is what THIS item is about and is UNCHANGED by ticket 30 -
  it still reads and fully re-renders every head, every run. `_mirror`'s call
  into `archive.write_session_folder` is now cheap when `archive_root` is
  configured; the `projections/` half this item describes is not.

- **28.9  `render_html` costs 74x the payload** and emits about 6.3x its size
  (a 100 MB session projects to a 633 MB page, 7.26 GiB peak). Latent: the
  largest real page is 17.7 MiB. Measured per stage; the earlier attribution to
  a dict holding five payloads was wrong, streaming recovered 0.4 GB of 8.2.
  Documented today only in a test comment. Needs its own ticket.

  **INVESTIGATED 2026-08-24, then fully implemented across two sessions the
  same week (see "Fix A DONE" and "Fix B DONE" below - both mechanisms are
  now fixed and tested).** The 100 MB/7.26 GiB historical figures were NOT
  re-verified at that scale; a smaller synthetic case (1.60 MiB in, 40 turns)
  WAS measured twice independently and reproduced 38.18x peak/input (61.16
  MiB peak):

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
  0.80 MiB output (~8x, same underlying cause as below); `_render_page` FULL variant: peak
  59.51 MiB to produce a 5.14 MiB string - effectively the entire run's peak; `_render_page`
  COMPACT variant: peak only 0.77 MiB (compact strips tool output by default, so it has far less
  content to duplicate at each copy-button level - itself confirming evidence for the mechanism).

  Two distinct, independent mechanisms found, to be fixed and
  TESTED (pytest + `claude-in-chrome` in a real browser) SEPARATELY, in a
  fresh session, per the operator's explicit instruction:
  - Mechanism 1 (Fix A, low risk, zero visible/functional change): 15 of the
    23 emoji icons `render.py` uses are outside the Unicode Basic
    Multilingual Plane (confirmed by lookup: BELL, BOOKMARK TABS, BUST IN
    SILHOUETTE, CLIPBOARD, ELECTRIC PLUG, GLOBE WITH MERIDIANS, JIGSAW
    PUZZLE PIECE, LEFT-POINTING MAGNIFYING GLASS, LINK SYMBOL, MICROSCOPE,
    OCTAGONAL SIGN, PAPERCLIP, ROBOT FACE, THOUGHT BALLOON, WRENCH - the
    last being `_row_icon`'s own default fallback). CPython stores an
    ENTIRE string at 4 bytes/char the moment it contains even one such
    character, confirmed with an isolated repro
    (`sys.getsizeof('x'*999999 + chr(0x1F50C))` = 4,000,060 vs 1,000,041 for
    pure ASCII). The single largest retained allocation in the measured run
    is the final `"\n".join(parts)` string: 20.6 MiB retained for a 5.14 MiB
    UTF-8-encoded page, a ~4x inflation matching exactly. Fix: build/join as
    UTF-8 bytes instead of `str` (both `build.py` call sites already
    `.encode("utf-8")` the result immediately, so this is a natural fit, not
    a new requirement).
  - Mechanism 2 (Fix B, higher risk, touches a locked contract guarantee):
    the page's copy-as-markdown buttons pre-bake an independent base64 copy
    at FOUR nested levels (row, phase, turn, whole-transcript), each a
    superset of the one below, all held at once before the final join. By
    design, not a bug - but `contract/DESIGN.md` section 6 locks "copy-as-
    markdown payloads equal the transcript.md fragments byte for byte",
    proven by `tests/test_render_html.py::
    test_copy_as_markdown_payloads_equal_transcript_fragments`. A fix here
    must keep that guarantee intact and PROVE it in a real browser (click
    every copy-button level, check the copied text), not just keep pytest
    green.
  Reproduction scripts saved at `temp/ticket-28.9-render-perf/` (this repo, gitignored,
  reusable across sessions): `profile_render.py` (whole `render_html`, tracemalloc + timing, the
  numbers above), `profile_render_stages.py` (isolates `build_conversation` / `_render` /
  `_render_page` full vs compact), `profile_render_dup.py` (confirms the duplication mechanism
  with a base64 substring probe). Run with `uv run python3
  temp/ticket-28.9-render-perf/profile_render.py` from the repo root; each edits `sys.path`
  itself and needs no other setup.

  **The operator-approved plan that was followed, in this exact order, across two sessions:**

  1. **Fix A**: stop the astral-plane emoji from inflating the WHOLE final HTML string. The
     clean shape: `render_html` and `render_markdown` returned `str`, and BOTH of `build.py`'s
     call sites immediately did `.encode("utf-8")` on the result anyway. Building the `parts`
     list (and the equivalent in `_render`/`render_markdown`) as UTF-8 BYTES per-fragment and
     joining with `b"\n".join(...)` avoids ever materializing one giant wide-char Python `str`
     - each small fragment stays cheap even if it individually contains an emoji, because the 4x
     penalty only applies to the ONE STRING that touches the emoji, not to everything
     concatenated with it later once it's already bytes. Zero visible/functional change was the
     whole point: same emoji, same HTML, same bytes on disk - only HOW the bytes get built
     changes.
  2. **Test Fix A for real**: `pytest`/`ruff`/`pyright` green, re-run
     `temp/ticket-28.9-render-perf/profile_render.py` and confirm the peak actually dropped, AND
     a REAL browser tab (`claude-in-chrome`) on a REAL generated `conversation.html` - `file://`
     is refused by the navigate tool, so served over loopback first. Check: zero console errors,
     visually identical to a pre-fix render, every copy button still works.
  3. **Only after Fix A is confirmed working, move to Fix B**: reduce the actual N-level base64
     duplication from Mechanism 2 - the riskier half, since it touches the DESIGN section 6
     contract guarantee. Two shapes existed, genuinely different risk: **server-side reuse**
     (build the phase/turn/whole-transcript fragments by concatenating the SAME already-built
     row-level fragments instead of re-deriving them - cuts duplicate computation, page weight
     roughly unchanged) vs. **client-side reconstruction** (ship only row-level payloads
     server-side, have the copy buttons' JS walk the DOM at click time - bigger win on page
     weight, more invasive, needs the locked byte-equality test to keep passing unchanged).
     Either shape: the output a reader sees and can copy must remain byte-identical to today.
  4. **Test Fix B for real**, same three-part bar as step 2, PLUS: click every level of copy
     button in the real browser tab and confirm the copied content still matches the
     corresponding `transcript.md` fragment byte for byte - the step that actually proves the
     contract guarantee survived, not just that pytest still passes.

  **Do not skip straight to Fix B, and do not consider either fix "done" on `pytest` alone** -
  both were the operator's explicit instructions, given after asking "what does the fix change,
  does it change functionality" and being told Fix A is a pure invisible optimization while Fix B
  touches a locked guarantee and needs real proof.

  **Fix A DONE 2026-08-24 (Fix B not started, separate, riskier).** `_render`
  and `_render_page` (`render.py`) now encode each fragment to UTF-8 bytes
  before the final join (`b"\n".join(...)`) instead of joining `str` and
  encoding afterward; `render_markdown`/`render_html`'s PUBLIC return type
  changed from `tuple[str, str]` to `tuple[bytes, bytes]`, since every real
  caller (`build.py`'s two `iter_projection_files` sites) was encoding the
  result immediately anyway. `build.py` simplified to match (no more
  encode-then-`del` dance). ~40 call sites across 10 test files updated to
  decode at the point of use; none of their assertions changed.

  Verified, not assumed: full suite 1,175 passed, ruff clean, pyright 0
  errors. Output proved BYTE-IDENTICAL before/after on two independent
  payloads - the synthetic 1.60 MiB repro and a real 8.3 MB session from
  this machine's own transcripts (`cmp` on all 5 projection files each way,
  via `git stash`/`stash pop` around the production diff). Peak memory on
  the synthetic repro dropped from 61.16 MiB to 28.00 MiB (peak/input ratio
  38.18x -> 17.48x) - better than the ~26 MiB / ~27x this ticket's own plan
  estimated, because the fix reached BOTH `_render` and `_render_page`, not
  only the HTML page's own join.

  Real-browser check done per the operator's explicit requirement (not
  pytest alone): the real 8.3 MB session's `conversation.html` served over
  `127.0.0.1` and opened in an actual Chrome tab via `claude-in-chrome`.
  Zero console errors on load and after interaction. All four copy-button
  levels (row, phase, turn, whole-transcript) clicked and their clipboard
  content read back programmatically: the whole-transcript button's output
  is CHARACTER-IDENTICAL to `transcript.md` (545,316 chars, `===` true) and
  the row/phase/turn buttons' output is each a substring of it, matching
  `test_copy_as_markdown_payloads_equal_transcript_fragments`'s own
  guarantee. Icons (astral-plane emoji included) render correctly and
  round-trip through copy intact.

  Fix B (the four-level base64 duplication, Mechanism 2) is NOT started -
  it is the riskier half, touches the locked DESIGN section 6 guarantee
  directly, and per the operator-approved plan needs its own build-then-test
  pass, not bundled into this one.

  **Fix B DONE 2026-08-24. Shape chosen: server-side reuse (operator's
  explicit pick over client-side reconstruction, given a 2-option table -
  lower risk, smaller diff, no JS change).** Root cause was not the four
  base64 encode CALLS themselves but that each level (row, phase, turn,
  whole-transcript) independently re-DERIVED its own markdown fragment from
  the underlying blocks via a fresh pass over `_render_block`/`_phase_md`/
  `_turn_body` - so a block already rendered once at row level got rendered
  again, from scratch, up to three more times as its content was folded into
  each larger fragment (a FIFTH redundant pass, not previously counted, was
  found the same way: `_claude_turn_count` - used by the header's "N you / M
  Claude" split - called `_claude_md` per turn just to test truthiness).

  Fix: a plain `dict[(id(block), policy) -> list[str]]` cache (`_BlockCache`,
  `render.py`), created once per `_render_page`/one per `render_markdown`
  call and threaded as a REQUIRED parameter (no default) through every
  function between it and `_render_block` - 13 call sites in
  `_claude_turn_count`/`_lean_rows`/`_detail_rows`/`_header`/`_header_html`/
  `_phase_md`/`_turn_body`/`_claude_md`/`_synthetic_md`/`_render_turn`/
  `_render`/`_block_html`/`_phase_html`/`_claude_inner`/`_turn_html`/
  `_render_page`. `_render_block` itself becomes a thin cache-check wrapper;
  the old body moved verbatim to `_render_block_uncached`, so the actual
  rendering logic is byte-for-byte unchanged - only WHEN it runs changed.
  Required (not optional/defaulted) on purpose: a missed call site is then a
  pyright error, not a silent loss of the caching (and a real one WAS
  caught this way, `_claude_turn_count`, before it could ship half-fixed).
  `render_markdown`'s own two calls (`_render` for full/compact) pass a
  cache too even though a single `_render()` pass has no internal
  redundancy to remove (each block is only ever visited once inside it) -
  kept for signature uniformity, not because it does anything there.

  Verified, not assumed: full suite is 1,198 passed, up from 1,197 on
  `master` at the start of this session (the 1,175 Fix A recorded above is
  stale - 22 tests landed from unrelated work, mostly ccstats, between Fix
  A and this session; confirmed by collecting tests on `master` via `git
  stash` before touching anything). This session's own diff adds exactly
  ONE new test. ruff clean, pyright 0 project errors (the pre-existing 15
  in `test_render_open.py` are unrelated and were confirmed to already
  exist on `master` before this change, via the same `git stash` check).
  Output proved BYTE-IDENTICAL before/after on a
  real 9.7 MB session from this machine (`cmp` on all four projection
  files - `conversation.html`, `conversation.compact.html`, `transcript.md`,
  `transcript.compact.md` - each way, via `git stash`/`stash pop`).
  Wall time on the ticket's own synthetic repro dropped ~31%, isolated to
  Fix B alone (0.511s on `master` with Fix A only, via `git stash`, vs.
  0.350s on this session's tree with Fix A + Fix B, same script, same
  payload); PEAK MEMORY stayed flat (28.00 -> 28.03 MiB, noise-level),
  exactly as the operator-approved plan
  predicted for this shape ("page weight is roughly unchanged, only the
  redundant intermediate work is cut") - server-side reuse trades CPU/
  allocation churn for correctness-safety, not page weight; only
  client-side reconstruction (the unchosen, riskier option) would have cut
  the page itself.

  A NEW test, `test_render_block_is_memoized_across_copy_levels`
  (`tests/test_render_html.py`), pins the cache's own invariant rather than
  only the byte-equality the existing locked test already covers: it
  monkeypatches `_render_block_uncached` with a counting wrapper (reached
  via `getattr`/`setattr`, not attribute access, since the function is
  module-private - `# noqa: B009` on the deliberate `getattr`) and asserts
  no `(block, policy)` pair is ever computed twice. Confirmed the test
  actually catches a regression, not just documents intent: manually
  bypassing the cache in a throwaway script reproduced up to 10 calls for a
  single block (row + phase + turn + whole + the `_claude_turn_count`
  header pass, across both policy variants) - the same test would have
  failed loudly against that state.

  Real-browser check done per the operator's explicit requirement (not
  pytest alone, and stronger than Fix A's own check): the real 9.7 MB
  session's `conversation.html` served over `127.0.0.1` and opened in a
  real Chrome tab via `claude-in-chrome`. Zero console errors on load and
  after every interaction. Rather than reading the system clipboard (which
  triggered an OS permission prompt that froze one `javascript_tool` call -
  worked around by not retrying it, per this project's dialog-avoidance
  rule), verification read the DOM directly: EVERY `[data-copy-src]`
  element on the real rendered page - 2,013 of them, covering all four
  levels (1,477 row/block, 509 phase, 24 turn, 1 whole-transcript) plus the
  header meta and files index (1 each) - was base64-decoded and confirmed to be a
  substring of the real `transcript.md` fetched from the same server, 2,013
  of 2,013 passing. This is the same guarantee
  `test_copy_as_markdown_payloads_equal_transcript_fragments` checks, now
  proven against a live browser-rendered page rather than only the pytest
  process. Real clicks on the whole-transcript, row-level and phase-level
  copy buttons produced zero console errors.

  28.9 is now fully DONE - both mechanisms fixed, both tested per the
  operator's real-browser bar, nothing left open on this ticket.

- **28.10  Test gaps still open:** symlinked archive root; folder-name
  collision; ENOSPC mid-write; cross-tree reconciliation as a TEST rather than
  a hand-check; rename-then-rebuild for `project.json`.

- **28.11  Markdown and HTML for sub-agents.** Purely additive now that each
  sub-agent has its own folder: a config key, a flag, and the files appear
  beside the JSONL.

- **28.12  Re-homing an orphaned sub-agent when its parent arrives.**
  Unreachable today (0 orphans) and it collides with R4 as amended: moving a
  JSONL means deleting one. It would have to join R4's closed list.

- **28.13  Architecture board 41+ commits stale**, pinned at `1517bba`. `src/`
  has gained a module since, so its line refs have drifted. `/architecture`
  owns it.

  **DONE 2026-08-23.** By the time this ran, `1517bba` was not just stale, it
  no longer existed (destroyed by the 2026-08-10 repository rebuild, ticket
  28.20). Re-derived the whole board at HEAD `4824098` (257 commits) using 5
  parallel Explore agents in place of the named review skill
  (`/mattpocock-skills:improve-codebase-architecture`, not enabled in this
  session), plus a new lens for `archive.py` - a 900+ line module, unreviewed
  until now, that came from the archive-first rewrite (tickets 19-30) which
  landed entirely after the last review. Two agent-reported findings were
  independently re-verified from source and turned out to be live bugs, not
  architecture debt, and were fixed the same session rather than left as
  board-only entries: `write_subagent` silently dropping a same-size,
  content-different re-capture (no manifest to record it in, so genuinely
  invisible - F6), and `ccw share --out` having no guard against writing
  inside the warehouse store, unlike its `ccw render --out` sibling (F9). Full
  board: `cc-warehouse-architecture/SOURCE.md`, rendered to `index.html`. See
  its own "2026-08-23 - FRESH REVIEW" change-log entry for the full account.

- **28.14  `prefers-color-scheme` for shared pages.** Named v1.1 candidate
  (DESIGN 15, 2026-07-24). Needs a light palette designed and the highlight.js
  token colours re-checked for contrast.

- **28.15  SSH key drops out of the agent repeatedly** (twice on 2026-08-03).
  Worth making survive a lock.

## If the repository goes public

**RESOLVED 2026-08-10. The repository IS public.** 28.16, 28.17 and 28.18 are
closed; what follows records how, and one residual the principal accepted with
its measurement, so nobody re-discovers it as a surprise.

- **28.16 CLOSED.** `git filter-repo --mailmap` rewrote the root commit's author
  and committer to the noreply identity. All 209 commits, all messages and all
  32 annotated tags survived; the HEAD tree hash was byte-identical before and
  after, which is the proof no file content moved.
- **28.17 CLOSED, then reopened by design, then closed properly.** The trailers
  were stripped, and then REGREW, because the harness stamps them on every commit
  made from a session. Proved twice by execution within minutes. The durable fix
  is not a repeated rewrite: it is `git config trailers.disable true` in this
  clone, a knob the dotfiles owner added on request, which also strips the
  appended `Claude-Session:` line. Machine-local config, so a fresh clone
  re-enables stamping and must set it again.
- **28.18 CLOSED.** `cc-warehouse` 0.1.0 published 2026-08-09, 0.1.1 on 08-10.
  The squat named below is closed: the name now serves this code.

- **28.20  RESOLVED 2026-08-10 by deleting and re-creating the repository.** The
  entry below is kept as written, because the reasoning that led to accepting the
  residual is worth reading even though the decision was reversed. WHAT CHANGED:
  the accept was taken on figures this entry gave as "one session UUID and one
  URL". Measured properly afterwards, an anonymous fetch of a single old SHA
  pulled the whole ancestry, **1804 objects**, recovering 19 distinct session
  UUIDs, 19 session URLs, the personal email 8 times, the drive name 13 times and
  the real session UUID 14 times. Both prior history rewrites had bought nothing
  against anyone holding a SHA. The "not enumerable" claim was false too: of 76
  candidate SHAs quoted in the public tree, one resolved, and it was the one this
  very entry had published.

  The repository was deleted and re-created, which destroys the server-side
  object store. Verified afterwards with the same three-way control: the current
  HEAD and its parent fetch, a bogus SHA does not, and the root commit,
  pre-rewrite-1 HEAD, pre-strip HEAD and session-start HEAD are all **gone**.
  The re-created repository reports **1474 objects, reachable == total**, so it
  holds no unreachable objects at all. One old SHA still fetches, `ad71fd4`, and
  that is correct: it is an ancestor of HEAD, whose SHA survived the trailer
  rewrite because it carried no trailer and its parents were unchanged.

  **THE DURABLE LESSON, which outlives this ticket.** A force-push does not
  delete objects; only destroying the object store does. Every verification that
  used a CLONE was true and irrelevant, because a clone fetches reachable objects
  and the problem was in the unreachable ones. The instrument could not see the
  place the problem was. Check reachability with `git fetch origin <sha>` and a
  bogus-SHA control, never with a clone.

  --- the original entry, superseded, kept for its reasoning ---

  **ACCEPTED RESIDUAL: pre-rewrite commits survive on GitHub.**
  A force-push does NOT delete the old objects. Measured 2026-08-10 with a
  three-way probe (`git fetch origin <sha>` into a scratch bare repo): the
  current HEAD fetched, a bogus SHA was refused, and the pre-strip commit
  FETCHED. The two controls disagreed, so the probe distinguishes present from
  absent; without them it proves nothing, and two earlier attempts at this
  measurement were broken instruments that looked conclusive.

  **THE PRE-STRIP SHA IS NOT WRITTEN HERE, and the first version of this entry
  got that wrong.** It quoted the full 40 characters two lines above the sentence
  arguing the risk is bounded BECAUSE an attacker would have to know them, which
  published the key beside the lock. Caught by scanning the public clone for the
  SHA and finding one hit: this file. Anyone who needs the value has the backup
  bundles, where `git bundle list-heads` prints it; it does not need to be in a
  public document to be recoverable by the person entitled to it.

  Removing it here does not remove it from this repository's history, because the
  commit that introduced it is already public. That is accepted rather than
  chased: a rewrite to erase it would leave its own unreachable-but-fetchable
  object, which is the very condition this entry documents, so the fix would
  recreate the problem one level down. What the removal does buy is that the
  current tree no longer hands the pointer to a casual reader.

  A fresh clone cannot see these, because a clone fetches only REACHABLE objects.
  That is why the "209 commits, 0 trailers" verification is true and beside the
  point, and it is the same shape of blind spot as a `git log --pretty=%(trailers:only)`
  check that reads ordinary prose as a trailer.

  **WHAT IS EXPOSED:** one session UUID and one `claude.ai/code/session_…` URL,
  in `C-Sess-Id` / `C-Web-Id` trailers across 7 pre-strip commits and one
  superseded tag object. Not credentials. Nothing to rotate. The URL requires the
  owner's login to follow. Reachable only by someone who already knows the
  40-character SHA, so not enumerable.

  **THE FIX THAT WAS AVAILABLE AND DECLINED:** delete and re-create the GitHub
  repository, which gives a new server-side object store and keeps the same URL.
  All four preconditions held at the time (private, not a fork, 0 forks, no pull
  requests, 1 collaborator) and a verified bundle of the clean history existed.
  Principal ruling 2026-08-10: accept the exposure and flip. Recorded rather than
  left unwritten, because a residual nobody wrote down becomes a surprise.

  **IF THIS IS EVER REVISITED**, deleting and re-creating still works and is
  still about two minutes, but only while the four preconditions hold. A fork or
  a pull request referencing an old SHA makes it much harder, and neither is
  under this project's control once the repository is public.

Prior audit, superseded and kept for its baseline: run 2026-08-03, the working
tree was clean (0 hits for the username, no personal paths, no emails, no
secret-shaped strings, no data files tracked, 127 files).

- **28.16  The root commit carries a personal email.** `063a499` "Initial
  Commit", a personal address rather than the GitHub noreply, in BOTH the author
  and committer fields, an ancestor of master; every other commit uses the
  noreply identity. THE ADDRESS IS NOT REPEATED HERE ON PURPOSE (redacted
  2026-08-09): this file is tracked, so writing it out published to the tree the
  exact string the ticket exists to keep out of it. Read it off the commit with
  `git log --format='%ae' 063a499` when the fix is run. A 2026-07-20 principal
  ruling left it, reasoning that "the address is already public in the remote's records so a
  rewrite cannot un-publish it". THAT PREMISE IS NOW FALSE: the repo returns
  HTTP 404 unauthenticated, so it is not public and going public would expose
  the address for the first time. The ruling deserves re-taking on the corrected
  fact. Not re-proposing the rewrite; reporting that its basis changed.

- **28.17  Session trailers become public.** 156 commits carry `C-Sess-Id` and
  `C-Web-Id`: 15 distinct session UUIDs and 16 distinct `claude.ai/code/session_…`
  URLs. The URLs need the owner's login, so this is not a data leak, but it does
  publish a map from commits to private sessions. `C-Wt-Path` uses the tilde
  form and leaks no username.

- **28.18  Claim the PyPI name.** `cc-warehouse` returns HTTP 404 on PyPI, so it
  is unclaimed. Claiming it also closes the squatting risk behind ticket 24.2:
  today a hook written `uv tool run cc-warehouse` would fail loudly, but if
  someone registers the name it would silently run their code with the session
  payload on stdin. This is the exact failure that hit the old plugin, where the
  colliding package happened to be harmless.

- **28.19  Move the plugin into this repo. DONE 2026-08-10 (`4b8dde4`).**
  `plugins/<name>/` plus a root `.claude-plugin/marketplace.json`. Documented
  and normal: Anthropic's own `anthropics/claude-code` carries a marketplace
  manifest at its root while being a software project. Removes the cross-repo
  drift that caused the ten-day outage. Note the plugin name is an immutable
  slug once published, so the final name must be chosen before the first
  publish, and PolyForm Noncommercial may sit awkwardly with a
  community-marketplace submission.

  Installed as `cc-capture@cc-warehouse`, a deliberately different slug from
  the old `claude-transcript-exporter@gz-claude-code-plugins` so both could be
  installed and verified side by side during the migration. **Verified
  2026-08-23** (found while working ticket 24.7 in the wrong place first):
  `~/.claude/settings.json`'s `enabledPlugins` carries `"cc-capture@cc-warehouse":
  true` and no entry at all for the old slug - it is not merely disabled, it is
  gone from the enabled set. This ticket's own CLOSING note, and CLAUDE.md's
  OPEN/next list, had both gone stale by still calling this open; corrected the
  same day ticket 24.7's freshness signal was added to the now-current
  `plugins/cc-capture/` in-repo plugin. `plugins/` and `.claude-plugin/` are
  excluded from ruff, pyright, and the sdist (pyproject.toml), but ARE covered
  by this repo's own oracle suite as of ticket 24.7 (`tests/test_cc_capture_
  freshness.py`), which is the whole point this ticket's own text predicted:
  "removes the cross-repo drift."
