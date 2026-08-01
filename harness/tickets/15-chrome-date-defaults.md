# Ticket 15: HTML chrome defaults + date-locale display

DONE 2026-08-01. Commits 51ed851 (chrome), e286a2b (dates), c09cb72 (review
fixes). Gates: ruff clean, pyright strict 0 errors, suite green. FINDINGS, each
re-derived by execution:

1. THE TICKET CONTRADICTED ITSELF and the fork was taken to the principal rather
   than resolved in passing, because it changes what every reader sees. Oracle
   test 1 asked for defaults byte-identical to post-slice-14 output; oracle test
   5 asked for the conversion JS present by default. With `html_dates` frozen at
   `local` those cannot both hold. RULED (option 1 of a presented table): keep
   the frozen default, move the baseline. DESIGN outranks the ticket, and shared
   rule (d) scopes rule (b)'s byte-identity promise to CONTENT toggles, which
   chrome is not.

2. The ticket's map of the code was wrong in two places. ADJACENT says "index
   page emission (timestamps there get the same JS treatment)" and TOUCHES lists
   build.py "(index pages only)". Executed: `ccw build` emits NO index page (a
   real build produced four projections plus manifest.json), and share's
   `_index_html` emits only `<li><a href>title</a></li>` with no timestamp of any
   kind. There was nothing to treat and nothing to touch; build.py is not in this
   slice's diff. A ticket's map is evidence, not a specification.

3. THE `<details open>` TRAP, caught before it shipped. `_MD_PASSTHROUGH_RE`
   whitelisted a BARE `<details>` only, so emitting the opened spelling without
   widening it would have put literal `&lt;details open&gt;` text on the page -
   visible, broken, and green under every other test. The regex and the seven
   emission sites moved in one commit for that reason.

4. TWO KEYS WERE INERT, found by a correctness census after the slice was
   pushed. `html_width` and `html_font` reached the JS fallback only; the <body>
   class was frozen at the v1 pair, so with JS unavailable the config was
   silently ignored and with JS available the page painted at the wrong size
   until the end-of-body script ran. The tell was the asymmetry: `html_turns`,
   the third key of the same block, was already implemented in markup. In-spec
   as the ticket worded it, and wrong anyway - block 2 says the four INITIAL
   STATES become config, and the body class is the initial state.

5. THE SPLIT CLOCK, the same defect class for the third time in this run. The
   date pass reached the per-turn stamps and not the header's own `Captured:`
   span, so under the default one page showed the turns in the reader's zone and
   the session's own span in UTC with nothing saying which was which. Fixed in
   `_header_html`, not in the markdown, so the .md files stay ISO; verified
   afterwards that all 21 data-copy-src payloads are byte-identical and the
   header payload still reproduces transcript.md verbatim.

6. The anchor moved TWICE, both recorded beside it with what was verified: once
   for the approved date script (+14 lines per HTML file), once to complete the
   same change (one line per file). Markdown goldens never moved.

7. Shares verified unaffected by personal chrome: `ccw share` builds a bare
   RenderOptions, so all five keys take defaults. Shared pages DO ship the date
   pass, which is the strongest case for the feature - a share is read by other
   people, in other timezones.

Slice 15 of 17 (v1.1 flag groups; DESIGN 15 entry 2026-08-01, blocks 2 and 4 +
shared rules). Depends on: slice 14 landing first (same files; sequential order
per the entry's build-order paragraph), slice 7 (HTML emitter).

Tracer bullet: five chrome-family keys (`html_width`, `html_font`, `html_turns`,
`details`, `html_dates`) and their `--<key> VALUE` flags reach the page skeleton
(fallback values, initial classes, `open` attributes) and a new JS pass shows
timestamps in the reader's local time while markup keeps raw ISO.

## Work order (template from harness/prompts/implementer.md)

- SLICE: chrome initial states + client-side date display
- GOAL: `html_width` / `html_font` (small|medium|large), `html_turns`
  (expanded|collapsed), `details` (closed|open), `html_dates` (local|iso, the
  whole date-locale group) as config keys with value flags; word values only.
- ORACLE TESTS (write first, in tests/test_chrome.py + additions to
  tests/test_config.py and tests/test_cli.py):
  - defaults unset: output byte-identical to post-slice-14 output (anchor
    reused);
  - `html_width = "medium"` changes the JS toggler fallback from "l" to "m";
    same shape for `html_font`;
  - `html_turns = "collapsed"`: every `section.turn` carries the collapsed
    class at render time;
  - `details = "open"`: `<details open>` appears in BOTH markdown and HTML
    variants (the one cross-format knob, named unprefixed for that reason);
  - `html_dates = "local"` (the default): timestamp spans keep the ISO stamp in
    markup and hover, and the conversion JS is present; `"iso"`: conversion JS
    absent; markdown files carry ISO under BOTH values;
  - invalid values (letters like "l", unknown words) are usage errors on flags
    and config-load errors on keys;
  - localStorage still wins after first paint (the JS reads saved || fallback -
    assert the emitted JS string preserves that order).
- CONTRACT EXCERPTS: DESIGN 15 entry blocks 2 and 4; DESIGN 8 key map; the
  incremental-build invariant (build.py: unchanged session re-projects to the
  same bytes) which the date mechanism exists to protect. Rules R9, R2.
- ADJACENT BEHAVIORS: the toggler() JS and `_hljs_block` emission in render.py;
  `_write_if_changed` byte-compare in build.py (do not break determinism: NO
  datetime.now(), NO machine tz anywhere in rendering); index page emission
  (timestamps there get the same JS treatment); REFUSED scope in the entry (no
  visibility knobs - do not add any).
- TOUCHES: src/cc_warehouse/render.py, src/cc_warehouse/config.py,
  src/cc_warehouse/cli.py, src/cc_warehouse/build.py (index pages only).

## Interview decisions frozen in the tests (register 7-8, 11, 16)

Four initial states only; honest-split naming (`details` unprefixed because it
reaches markdown); word values, never the DOM's s/m/l; client-side display with
ISO markup (reader-respect, determinism); `html_dates` default local; chrome
keys variant-agnostic (no `_full`/`_compact` forms).

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only.
