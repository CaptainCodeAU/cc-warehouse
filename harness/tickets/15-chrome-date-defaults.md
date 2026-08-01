# Ticket 15: HTML chrome defaults + date-locale display

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
