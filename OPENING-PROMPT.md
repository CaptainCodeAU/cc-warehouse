# Continuing ticket 31 — opening prompt for a fresh session

Read `CLAUDE.md` first, as always. This file is a pointer into where the
previous session left off, not a replacement for it.

## Where things stand (as of tag `slice-31.3`, 2026-08-20)

**31.1 (folded into 31.2) DONE, 31.2 DONE, 31.3 DONE.** Deployed and verified
live on this machine (2026-08-20): `ccw doctor` reports `frozen: running from
~/.local/share/uv/tools/cc-warehouse/...`, PEP 610 `direct_url.json` has no
`editable` flag. Tomorrow's 12:30 `com.captaincodeau.ccw-sweep` job runs this
code. **31.4 and 31.5 are the only sub-slices still open.**

Full evidence and reasoning, in order of how much detail each carries:
1. `harness/tickets/31-sweep-full-corpus-cost.md` — the work order, full
   31.1-31.3 account (31.1's retraction, 31.2's shipped design, 31.3's
   measurement-first correction).
2. `contract/DESIGN.md` section 15, entries "2026-08-20, ticket 31.2" and
   "2026-08-20, ticket 31.3" — the permanent record of both shipped decisions.
3. `contract/HARNESS.md` section 8, entry "2026-08-20: A TICKET'S OWN STATED
   PREMISE WAS NEVER MEASURED" — the process lesson from 31.3, worth reading
   before touching 31.4 or 31.5.
4. `Plans/read-opening-prompt-md-fully-and-composed-engelbart.md` — the
   approved 31.3 plan, including the in-place correction after Step 0's
   measurement contradicted the plan's own first draft.

Gates as of `slice-31.3`: `uv run pytest` full suite green (1105), `uv run
pyright` 0 errors, `uv run ruff check` clean, `tests/golden/matrix-anchor`
untouched.

**31.3 in one paragraph, because the shape matters for 31.4/31.5 too.** The
ticket's own premise (read+hash is what makes a `skipped_unchanged` item
expensive) was measured before any design was written and found FALSE:
read+hash costs ~0.4 ms/file, ~0.3% of the real cost. The actual cost was a
JSON parse plus a per-item lock file + fresh sqlite connection + `BEGIN
IMMEDIATE`/COMMIT, hidden because `capture.py`'s own `elapsed_ms` timer stops
one line before the expensive part. Fixed by moving `sweep.plan()`'s already-
shipped skip decision onto `sweep()`'s hot path (no new signal, no R1
exception). **What the fix does NOT explain**: every per-item mechanism
identified sums to ~72 s for the real corpus; the daily job that started this
investigation took 2,072.5 s (34.5 min). That ~91% gap was never explained by
anything in this codebase. A real (non-dry-run) `ccw sweep` run immediately
after deploying finished in **81.9 s** against the live 21,734-session corpus
— genuinely fast — but that was an interactive run under this session's own
load, not launchd's, so whether the DAILY job is now actually fast is
**still unverified**. Check it before assuming 31.3 solved the daily-cost
problem end to end.

## What to do next

**Operator instruction, 2026-08-20: this session does 31.4 AND 31.5, then
moves on to whatever else is pending (ticket 27 — see below).**

**First, cheaply**: read the daily sweep's actual wall-clock time since 31.3
deployed, from `~/cc-warehouse-data/catalog.sqlite`'s `capture_event` table
(the window between the first and last row of the run, same method the
original investigation used) or a launchd log if one exists. If it is still
close to 34.5 minutes, the ~91% gap this ticket never explained is confirmed
external to this code (leading candidate: this machine's own confirmed
resource contention under 4+ concurrent Claude sessions —
`python-process-resource-limits.md`, operator memory) — worth one line in
the record either way, but not a blocker for 31.4/31.5 below.

**31.4 (retry-on-lock-contention).** BE HONEST ABOUT WHAT ONE SESSION CAN
ACTUALLY FINISH HERE: the ticket's own instruction is "add debug logging,
then wait for a natural recurrence before writing the retry loop" — the
underlying mechanism (a `sqlite3.OperationalError` during
`_capture_locked`'s post-`write_source` steps) was never proven, only
suspected from one broken folder. What CAN ship in one session: the debug
logging itself (`capture.py` ~line 168 onward), and a decision, recorded,
on whether 31.3 removing ~16,400 of the ~17,000 daily write transactions
that were the suspected contention source makes this moot rather than fixed
- don't write a retry loop against an unconfirmed cause. If a natural
recurrence has already happened by the time this session runs (check
`ccw archive --verify` for a fresh desync, or the operator may simply know),
diagnose from the real exception instead of guessing.

**31.5 (doctor-level desync check).** Fully open, not started, no external
dependency - this one CAN close in one session. Scoping constraints from the
ticket: must stay SessionStart-cheap (no full `ccw archive --verify` over
21,000+ folders - that reintroduces the exact O(everything) cost this whole
ticket exists to remove), and `ccw doctor`'s TEXT OUTPUT is a public
compatibility surface (`ccw-watch` parses the `hook` line and the
`Uncaptured: N session(s)` figure by regex) - a new check must not change
that existing wording.

**Then, whatever else is pending: `harness/tickets/27-collapse-to-one-
folder.md`.** This is the project's actual active-track ticket per
`CLAUDE.md`'s OPEN/next section, opened before ticket 31 and still the
thing after it. CORRECTION to `CLAUDE.md`'s own line, found while writing
this handoff: it currently says ticket 27 is "NOT STARTED, 27.1-27.8" - that
is STALE. The ticket file itself shows **27.1 DONE 2026-08-05** (`ccw
reindex` shipped) and **27.2 DONE**, with a real-data comparison whose
verdict decides the rest of the ticket's order: the catalog is disposable
for sessions and labels, but NOT YET for aliases (114 of 4,913 recovered
after a rebuild, 2.3% - that gap is ticket 28.21). So the actual next open
step in ticket 27 is 27.3 onward, not the beginning. Update `CLAUDE.md`'s
stale line when picking this up.
**SAFETY, carried forward exactly as ticket 27 itself states it**: two
slices in this ticket (27.4, and the withdrawn-forever 27.9) are marked
DESTRUCTIVE and need the principal's explicit word at the moment of
running, not in advance, and not because a gate went green. 27.9 specifically
is WITHDRAWN and STAYS WITHDRAWN - a satisfied precondition is not consent
- see the ticket's own banner before touching any part of it.
