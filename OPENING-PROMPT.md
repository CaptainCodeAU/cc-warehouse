# Ticket 27.3 done, 27.4 blocked on a real finding. Opening prompt for a fresh session

Read `CLAUDE.md` first, as always. This file is a pointer into where the
previous session left off, not a replacement for it.

## Where things stand, 2026-08-20

**Ticket 31 (sweep full-corpus cost) is FULLY CLOSED** - see the previous
version of this file in git history, or `harness/tickets/31-sweep-full-
corpus-cost.md`, if you need that account. This handoff is about ticket 27.

**27.1 and 27.2 were already DONE before this session.** This session did
**27.3 (DONE) and started 27.4 (BLOCKED on a real finding, not yet safe to
retry the destructive half)**.

### 27.3: DONE, verified live

`keep_objects = false` is live in `~/.config/cc-warehouse/config.toml`, with
the operator's explicit go-ahead at the moment of the change. Verified with
a REAL Claude Code session (via Herdr, not a test fixture): opened a
session, closed it, confirmed the old `objects/` vault got zero new files
while the new archive kept working normally, and `ccw doctor` stayed green.
Full account: `contract/DESIGN.md` section 15, "2026-08-20, ticket 27.3".

### 27.4: attempted, BLOCKED - read this before touching it again

The ticket's own instruction is: rename `objects/` aside (not delete), run
`capture`/`sweep`/`build`/`verify`/`status`/a real session end, and only
when ALL of those pass does the delete happen - and the PRINCIPAL runs that
delete, not a session. This session did the non-destructive half, with the
operator's go-ahead for exactly that half.

`objects/` (2.6 GB, 22,030 files) was renamed aside on the real machine.
`ccw status` and `ccw verify` passed clean (`verify` already redirects to
archive integrity under `keep_objects = false`, confirmed by reading the
code first - it never touches `objects/` at all). **`ccw build` did NOT
pass: 4 of 21,460 sessions failed with `FileNotFoundError` reading
`objects/<hash>.jsonl`**, even though all 4 already have a complete archive
folder sitting right there (JSONL plus all five generated files - checked
directly, not assumed). One of the 4 is the session ticket 31 opens with
(`b087d6a2-...`, the already-known desync); the other 3
(`80721130-...`, `17e372b3-...`, `c85f1e1b-...`, all captured within the
same minute on 2026-08-04) are new information nothing had flagged before.

**The mechanism**: whatever makes `build._head_is_current` decide these 4
specific heads need a full rebuild, `build._read` then reads `objects/`
UNCONDITIONALLY - no fallback to the archive JSONL that is already there.
That is backwards for a deployment that stopped writing to `objects/` this
same session (27.3) - the archive is supposed to be sufficient now, and for
these 4 heads it demonstrably is not treated that way by the rebuild path.

**`objects/` was restored immediately** (not left broken overnight) - a
second `ccw build` came back `4 built, 0 failed`, confirming the diagnosis
and that nothing was lost or corrupted. The live machine is back to normal,
fully green on `ccw doctor`.

**What the next session must do before re-attempting 27.4:**

1. Read `build._read` and `build._head_is_current` (`src/cc_warehouse/
   build.py`) to understand exactly why these 4 heads are flagged
   not-current, and why only these 4 out of 21,460.
2. Decide whether `build._read` should fall back to an archive folder's own
   JSONL when `objects/` doesn't have the payload (or `objects/` doesn't
   exist at all) - this is the real question 27.4's delete step depends on,
   not a one-off patch for 4 named sessions.
3. Ship that fix with oracle tests first, same discipline as every other
   slice in this project (`CLAUDE.md`'s hard rules).
4. Re-run the SAME exercise this session ran (rename `objects/` aside,
   `status`/`verify`/`build`/`sweep`/a real session end) before considering
   the delete safe. A clean run on 21,460 sessions today does not prove the
   next 21,460 won't hit the same gap through a different path - `build`
   found this by accident (a routine `ccw build` run, not a targeted probe),
   so don't assume 4 was the whole population.
5. **The delete itself still needs the principal's explicit word at the
   moment of running, same as it always did.** A clean re-run of step 4 is
   not consent by itself.

Full account, most detail first: `harness/tickets/27-collapse-to-one-
folder.md` (27.4 section) -> `contract/DESIGN.md` section 15, "2026-08-20,
ticket 27.4" -> `CLAUDE.md`'s own ticket-27 status line.

## Standing rule, unchanged

27.9 stays withdrawn regardless of what else in this project goes green.
