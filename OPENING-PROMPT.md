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
folder sitting right there.

**THE MECHANISM, diagnosed the same session (an earlier write-up here was
wrong and has been corrected - do not trust anything about this that predates
this file's own git history entry):** `archive.read_payload` already prefers
the archive folder over `objects/`, VERIFIED by re-hashing the folder's
JSONL against the catalog's recorded hash before trusting it - confirmed by
reading the code, not assumed. Computing `shasum -a 256` on all 4 archive
JSONLs directly showed all 4 MISMATCH their catalog row's hash - that
mismatch is what triggers the fallback to `objects/`, which then wasn't
there. **This is ticket 29's already-open "Mechanism 1"**
(`harness/tickets/29-which-copy-is-the-current-one.md`): `build._heads`
picks a session's head as "the row no other row supersedes" (the newest
INSERT), regardless of whether that row's payload is the one that actually
survived in the shared archive folder - `write_source`'s "larger payload
wins" rule can leave an OLDER, larger capture's bytes on disk when a
newer-but-smaller recapture arrives. **3 of the 4 failing sessions
(`80721130-...`, `17e372b3-...`, `c85f1e1b-...`) are the EXACT three uuids
ticket 29's own "blast radius" section already named** on 2026-08-04/05 -
not new, re-found through a harder failure mode now that `objects/` was
briefly gone. **The 4th (`b087d6a2-...`, the session ticket 31 opens with)
is NEW**: a fresh, same-day three-version chain hitting the identical class,
proving the mechanism is still live and adding new affected sessions, not a
closed historical case.

**`objects/` was restored immediately** (not left broken overnight) - a
second `ccw build` came back `4 built, 0 failed`, confirming both the
symptom and this corrected diagnosis without losing or risking anything.
The live machine is back to normal, fully green on `ccw doctor`.

**What the next session must do before re-attempting 27.4:**

1. Read `harness/tickets/29-which-copy-is-the-current-one.md` in full - it
   already scopes Mechanism 1's fix shape and names the locked oracle test
   it must not break (`test_a_smaller_payload_is_refused_and_the_refusal_is_
   recorded`). Do not re-derive the mechanism from scratch; this session
   already did that and the ticket file has the fuller account.
2. Ship Mechanism 1's fix with oracle tests first, same discipline as every
   other slice (`CLAUDE.md`'s hard rules). This is the actual blocker for
   27.4's delete step, not a change to `build.py`'s read path (that already
   works correctly, verified).
3. Re-run the SAME exercise this session ran (rename `objects/` aside,
   `status`/`verify`/`build`/`sweep`/a real session end) before considering
   the delete safe. `ccw build` found this by accident (a routine run, not a
   targeted probe) - don't assume these 4 were the whole population; name
   what a re-run actually checked, same as this handoff does.
4. **The delete itself still needs the principal's explicit word at the
   moment of running, same as it always did.** A clean re-run of step 3 is
   not consent by itself.

Full account, most detail first: `harness/tickets/27-collapse-to-one-
folder.md` (27.4 section) -> `contract/DESIGN.md` section 15, "2026-08-20,
ticket 27.4" -> `CLAUDE.md`'s own ticket-27 status line.

## Standing rule, unchanged

27.9 stays withdrawn regardless of what else in this project goes green.
