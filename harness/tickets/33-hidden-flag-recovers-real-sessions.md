# Ticket 33: the `hidden` flag was silently hiding real work, not just junk

Opened and CLOSED 2026-09-01, from a red-team audit launched to investigate a
same-day capture-health false alarm (unrelated: see the freshness-check
timing investigation logged the same day). One of four parallel audits was
told to adversarially re-check an earlier claim in the same session ("583 of
588 folders missing render files are harmless hidden sessions") rather than
trust it, and found the claim was wrong in a way that mattered.

## Why this ticket exists

`parser._summary_candidate` answers one question: does this session have a
good display title (first `type:summary` line, else the first non-meta user
message whose text doesn't start with `<`). SPEC 8's KEEP verdict reused that
exact signal to also decide `hidden` (skip rendering entirely) whenever no
candidate exists. Those are different questions. A session started by a slash
command (`<command-name>...`, deliberately excluded from title candidates
since it's machine text, never a summary) and then run autonomously with no
further typed user text has NO summary candidate even when the assistant did
substantial real work afterward -- so it was hidden too, with zero warning.

Measured on the live archive (`~/cc-warehouse-data/catalog.sqlite`, `~/cc-warehouse-archive`):
597 sessions carried `hidden=1`. Sampling by size found the smallest genuinely
trivial (a bare `/exit`, 8 lines, zero assistant entries) but the largest real,
substantial work, permanently unrendered:

- `6bcf9aab-4eaf-4bac-8ca6-6851b3a45763` (chorustic) -- 1,010 lines, 1.57MB,
  216 assistant turns, 126 tool calls, kicked off via `/cc-skills:tdd`.
- Three more over 500KB with dozens of real assistant/tool turns each.

~101 of the 597 hidden rows exceed 20KB, a rough lower bound on how many are
real sessions rather than noise.

## What shipped

### 33.1 Decouple "good title" from "worth rendering"

`contract/SPEC.md` section 8 amended (principal ruling) and `contract/DESIGN.md`
section 15 carries the dated decision. The summary/title rule and its KEEP
verdict are UNCHANGED -- still `(no summary)` display text when there's no
candidate. Only the no-candidate branch's `hidden` computation is narrowed:
`parser._has_substantial_engagement(entries)` now decides it, true once the
assistant has produced real content (non-blank text or a tool call) in at
least two separate turns. Two, not one: a single canned reply still reads as
a stub, matching the shape of the pre-existing `(no summary)` oracle fixture
(which needed no change as a result). The `warmup` branch is untouched.

**Oracle tests** (`tests/test_parser.py`, 3 new): a slash-command-only session
with no follow-up stays hidden (mirrors the real `/exit` example); a
slash-command session with 2+ real assistant/tool turns is not hidden (mirrors
the real `6bcf9aab` example); a single bare assistant reply alone still is
(the amendment's explicit lower bound). RED confirmed before the parser change
(1 of the 3 failed, the other 2 already passed against the old code), GREEN
after. Full suite: 1201 passed, `uv run ruff check` clean, `uv run pyright`
0 new errors (15 pre-existing, unrelated, in `test_render_open.py`, confirmed
present on a clean `git stash` baseline too).

### 33.2 Recovery backfill against the live warehouse

One-off script, `tools/recover_hidden_sessions.py` (tracked scratch tooling,
outside `src/`, same convention as `tools/ccstats/` -- not a permanent `ccw`
verb). Reads every `hidden=1` catalog row, re-parses that session's JSONL from
the ARCHIVE (read-only) with the fixed classifier, flips the catalog `hidden`
column to 0 for anything that now computes visible, and renders it.

Recovery run against the live warehouse (`~/cc-warehouse-data/catalog.sqlite`,
`~/cc-warehouse-archive`): 597 hidden rows examined, **13 flipped hidden ->
visible**, all 13 rendered successfully (0 failures), 574 correctly stayed
hidden, 10 had no matching archive folder (untouched, not counted). All four
of the originally-sampled examples (`6bcf9aab`, `e003ffff`, `11ec555a`,
`00767c0a`) are among the 13 and were spot-checked directly: catalog `hidden`
now 0, archive folders now hold all five files at real sizes (e.g. `6bcf9aab`'s
`conversation.html` is 2.3MB, not an empty stub). The pre-fix ~101-over-20KB
estimate was a rough size proxy, not a prediction of the exact rule; the true
count under "2+ substantive assistant turns" is smaller because many large
hidden sessions are dominated by thinking-only assistant entries (empty
`thinking` blocks carry no text and are not a tool call) with fewer than two
turns of real text/tool-call content.

## What was deliberately NOT done

- Not touched: any row whose re-derived `hidden` status is still `True`. Those
  stay exactly as before (archived JSONL, no markdown/HTML), which is correct
  -- SPEC 8's underlying intent (hide genuinely trivial sessions) is preserved,
  only narrowed.
- Not revisited: the unrelated same-day finding that today's "110 problems in
  25 folders" capture-health alarm was itself a false alarm (a daily sweep
  burst still mid-render when doctor sampled it) -- that is a separate,
  already-reported finding, not this ticket's concern.
- Not addressed: the also-confirmed-separately latent bug where a real render
  failure in `build._mirror`/`cli._mirror_to_archive` gets swallowed with zero
  log (a different red-team finding from the same audit). Left for a future
  ticket.

## Gates

Full suite: 1201 passed, `uv run ruff check` clean, `uv run pyright` 0 new
errors. `tests/golden/matrix-anchor` untouched -- this change only affects the
`hidden` classification of sessions that previously had `hidden=True` and no
default-output-shape byte moved for anything already rendered.
