# Continuing ticket 31 — opening prompt for a fresh session

Read `CLAUDE.md` first, as always. This file is a pointer into where the
previous session left off, not a replacement for it.

## Where things stand (as of tag `slice-31.2`, 2026-08-20)

The previous session investigated one broken archive folder the operator
handed over (`CaptainCodeAU-win_go_app_test/20260820-093714+1000_b087d6a2-
...`), traced it to the daily `ccw sweep` job's cost, and opened
**ticket 31** (`harness/tickets/31-sweep-full-corpus-cost.md`) with 5
sub-slices. **31.2 is DONE** (tag `slice-31.2`, commits `26c930e` feat +
`bc355c7` docs, both pushed to `origin/master`). **31.1, 31.3, 31.4, 31.5
are still open.**

Full evidence and reasoning, in order of how much detail each carries:
1. `contract/PROPOSALS/daily-sweep-full-corpus-cost.md` — the original
   investigation: real numbers, root cause, what was checked and ruled out.
2. `harness/tickets/31-sweep-full-corpus-cost.md` — the work order, 31.1
   through 31.5, including 31.1's retraction and 31.2's full account.
3. `contract/DESIGN.md` section 15, entry "2026-08-20, ticket 31.2" — the
   permanent record of the shipped decision.
4. `Plans/federated-sleeping-lark.md` — the approved implementation plan for
   31.2 (already executed; kept for reference, not a to-do list anymore).

Gates as of `slice-31.2`: `uv run pytest` full suite green (1094 + 18 new),
`uv run pyright` 0 errors, `uv run ruff check` clean, `tests/golden/matrix-
anchor` untouched.

**Notable process note from this session, worth carrying forward:** a first
design for 31.1 (guard `build.build()`'s call in `ccw sweep` on
`keep_projections`) looked safe and was nearly shipped, but would have broken
archive-page rendering for every session the daily safety net captures. It
was caught by reading `build._mirror()`'s actual code before writing the fix,
not by testing alone. The corrected design (31.2) went through two rounds of
adversarial subagent review before any line shipped. Worth the same care on
31.3-31.5 — this project's own daily sweep job has already burned one
almost-shipped mistake this week.

## What to do next: design decisions for 31.3

**This is the explicit next task, per the operator.** From
`harness/tickets/31-sweep-full-corpus-cost.md`, section "31.3":

> Give `sweep()`'s own walk a cheap pre-check before the read+hash. The
> biggest single win (34-44 minutes measured for the walk alone) and the one
> part of this ticket with no existing shipped pattern to copy directly -
> `sweep.py` `_walk_source()` + `capture.capture_transcript()` walk every
> `.jsonl` under `~/.claude/projects` and fully read+hash every one of them
> before any skip decision can be made.

Two honest options the proposal named, not a false choice — pick one, refine
one, or find something better, and say why:

1. A new side-table (source path, mtime, size, last-known hash) checked
   before the read. Fast, but mtime/size is a *proxy* for content, not
   content itself — this project's own R1 treats content-hash as the only
   real identity elsewhere, so this needs a deliberate, recorded exception
   or a better idea.
2. Reduce the cost *per skip* instead of avoiding the read: batch or drop
   per-item `capture_event` logging for `skipped_unchanged` outcomes, so the
   read+hash still happens but the ~17,000 individual `BEGIN IMMEDIATE`/
   `COMMIT` transactions collapse into far fewer. Simpler, smaller diff,
   does not fully solve the wall-clock cost but directly reduces the
   database write pressure implicated in 31.4.

Before designing: re-read `sweep.py` fresh (it may have drifted since the
proposal was written) and re-confirm the 17,079/16,382-skipped numbers are
still roughly representative — they were measured once, on 2026-08-20, not
guaranteed to still hold.

31.4 (retry-on-lock-contention) and 31.5 (a doctor-level desync check) are
also still open and lower-priority per the ticket's own ordering, but were
flagged as worth scoping together with 31.3 since one investigation found
both. 31.4 specifically has its own open question (the lock-contention
mechanism is not proven, no stack trace was recoverable) that should be
resolved with real evidence, not assumed, before writing a retry loop —
see the ticket's 31.4 section for exactly what to check first.
