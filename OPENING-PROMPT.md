# Ticket 29 mechanism 1 done, 27.4's code blocker is gone. The delete itself is still not run.

Read `CLAUDE.md` first, as always. This file is a pointer into where the
previous session left off, not a replacement for it.

## Where things stand, 2026-08-20

**27.1, 27.2, 27.3 are DONE.** `keep_objects = false` is live on the real
machine, verified with a real Claude Code session (via Herdr). Full account:
`contract/DESIGN.md` section 15, "2026-08-20, ticket 27.3".

**27.4's non-destructive half found a real bug, and the bug is now fixed.**
Renaming `objects/` aside and running `ccw build` against the real
21,460-session corpus failed 4 sessions with `FileNotFoundError`. Root
cause, after a first write-up that named the wrong mechanism and was
corrected in the same session (read the git history if you want that
detour - it is not load-bearing for what to do next): **ticket 29's
already-open "Mechanism 1"** - `build._heads`/`head_for_short` picked a
session's current version as "the row no other row supersedes" (the newest
INSERT), not "the row whose payload is actually the newest" - so an
out-of-order or truncated capture could become head over a fuller,
chronologically-later one whose bytes are what the shared archive folder
actually kept.

**Ticket 29 mechanism 1 is DONE, 2026-08-20**, scoped with the operator
first (both the ticket and `catalog._latest_version`'s own docstring
required that before touching `build._heads`/`head_for_short` - "the most
load-bearing pair of functions in the project"). Both functions now rank
each session_uuid's rows by `COALESCE(last_ts, captured_at)` - the same
ordering `catalog._latest_version` already used - via one shared query
fragment, `build._HEAD_RANK_CTE`. `catalog.add_session`'s own chain-building
is unchanged. Full account: `harness/tickets/29-which-copy-is-the-current-
one.md` and `contract/DESIGN.md` section 15, "2026-08-20, ticket 29
mechanism 1".

**Verified on the real machine, not just the test suite.** All 4 originally-
failing sessions now resolve, via the fixed query run directly against the
live catalog, to the exact hash sitting in their archive folder. The full
27.4 exercise (rename `objects/` aside, `status`/`verify`/`build`/`sweep
--quiet`/a real live Claude Code session end via Herdr) was re-run end to
end and passed clean: `ccw build` went from `4 failed` to `0 failed` against
the SAME unchanged corpus. `objects/` was restored afterward.

**What is NOT proven**: a clean re-run over today's corpus does not
guarantee no other session will hit this same class through a chain shape
the two oracle tests don't construct (three-plus versions, more complex tie
patterns). Read `tests/test_head_selection.py` to see exactly what is and
isn't covered before assuming the class is fully closed.

## What to do next

**The delete step in 27.4 was NOT run.** Fixing the code blocker is not the
principal's word at the moment of running - that is still owed separately,
per the ticket's own DESTRUCTIVE marking, and per this session's own
explicit scope (the go-ahead covered the fix and its verification, not the
delete).

If picking this up fresh: read `harness/tickets/27-collapse-to-one-
folder.md`'s 27.4 section in full (it now has both the original finding and
the fix account), confirm with the operator whether they want the delete
run now, and if so, run it exactly as the ticket specifies (delete
`objects/`, not `objects.27.4-renamed-aside` or any other stale rename - if
one is sitting around from a prior session's testing, that means testing
was interrupted; check what state the machine is actually in before
assuming). If not now, 27.5-27.8 are the next open slices in the ticket,
independent of 27.4's delete.

## Standing rule, unchanged

27.9 stays withdrawn regardless of what else in this project goes green.
