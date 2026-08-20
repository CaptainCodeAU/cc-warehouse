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

**Immediate, low-effort, and answers the open question above**: read
tomorrow's (or the next) daily sweep's actual wall-clock time, from either
`~/cc-warehouse-data/catalog.sqlite`'s `capture_event` table (the window
between the first and last row of the run, same method the original
investigation used) or a launchd log if one exists. If it is still close to
34.5 minutes, the ~91% gap is confirmed to be external to this code (the
leading candidate is this machine's own confirmed resource contention under
4+ concurrent Claude sessions — `python-process-resource-limits.md`,
operator memory) and 31.4/31.5 should be scoped with that assumption made
explicit rather than left implicit. If it dropped substantially, that is
itself worth recording — it would mean the per-item DB/lock pressure this
session removed was contending with something else running at the same
time, not just costing time on its own account.

**31.4 (retry-on-lock-contention)**: the ticket's own open question — the
lock-contention mechanism was never proven, no stack trace was recoverable —
is now MORE likely to be moot rather than less: 31.3 removed ~16,400 of the
~17,000 daily write transactions that were the suspected contention source.
Before writing a retry loop, add debug logging around `_capture_locked`'s
post-`write_source` steps (`capture.py` ~line 168 onward) and wait for a
natural recurrence, per the ticket's own instruction — do not assume it is
already fixed by 31.3, and do not assume it still needs a retry loop either.

**31.5 (doctor-level desync check)**: still fully open, not started. See the
ticket's own section for the scoping constraint (must stay SessionStart-cheap,
must not reintroduce the O(everything) cost this whole ticket exists to
remove) and `contract/DESIGN.md`'s 31.3 entry for why `ccw doctor`'s TEXT
OUTPUT is a public compatibility surface (`ccw-watch` parses it) that 31.5
must not change the wording of.
