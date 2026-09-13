# Ticket 43: a SessionEnd hook that dies before it can log

Status: OPEN, scoped, not started. Opened 2026-09-13.

## The incident

Session `5c652174-0f67-46ba-a010-84bdd51f83c6` (cwd `~/.claude`,
2026-09-12T09:09:22Z to 14:54:50Z, 351 lines, 1,188,678 bytes) ended cleanly via
`/exit` and was never captured. It reached neither the catalog nor the archive.
`ccw-hook.log` holds ZERO lines for it, while a control id `dd70c134` holds 2.

This is NOT a lost session. The daily `ccw sweep` covers it. The defect is that
the failure left no trace anywhere, so it cannot be explained.

## What is measured

SessionEnd DID fire. `SessionCleanup.hook.ts` wrote a work-event for that
session id at 14:54:50.997Z, 181 ms after the Goodbye line, into
`~/.claude/LIFEOS/MEMORY/STATE/work-events.jsonl`. Six of the seven registered
SessionEnd hooks are settings.json hooks and at least one completed. Only the
cc-capture plugin hook produced nothing.

All seven dispatch in PARALLEL, not serially. Verbatim from a `claude --debug`
run (session `1051ac9b`), completion timestamps, whole window ~700 ms, ccw-hook
completing 233 ms in. So "starved behind a slow sibling hook" is not the shape.

`/exit` produces reason `prompt_input_exit`. `hooks.json` registers SessionEnd
with no matcher, so every reason already matches. Nothing to change there.

Ruled out by measurement, each one separately: launcher (three controlled
`lifeos`-launched sessions with cwd `~/.claude` all archived cleanly:
`c93d9c11`, `513b0720`, `1051ac9b`); cwd being the config dir (no
`settings.local.json`, no managed settings, `~/.claude/.claude/` empty);
resume (both archived controls also begin `{"type":"last-prompt"}`); plugin
registration (5c652174's own transcript contains the SessionStart freshness
banner); python resolution (`the homebrew python3` symlink unchanged since
18 Aug, log shows 3.14.7 throughout, the interactive `use uv run` override is a
zsh function and never reaches a hook subprocess); plugin-file churn (nothing
under `~/.claude/plugins` modified in the session window bar `.in_use` markers);
size and duration (a 10 MB Goodbye-ended session `ea9988cf` archived fine; this
one is ~2 MB, and of 21 ended sessions since 2026-09-08 it is the only one with
zero hook lines).

## The blind window

`main()` reads stdin, THEN calls `_started`:

    payload = sys.stdin.read()   # blocks until Claude Code closes the pipe
    _started(payload)            # first thing that touches the log

Nothing is written before that. So a kill anywhere in these three steps is
invisible by construction:

1. process spawn + interpreter startup
2. module-scope imports
3. `sys.stdin.read()`, blocking, unbounded

Steps 1 and 2 are BOUNDED and small. Measured on this machine, three runs,
`the machine's python3 (3.14.7)`:

    full module-scope import set   20 ms  (19.9, 20.5, 19.9)
    bare interpreter startup       10 ms
    total spawn to ready           30 ms

Step 3 has no ceiling: it waits on teardown closing the pipe. That asymmetry is
the finding. The uninstrumented window is dominated by the one step whose length
nobody controls.

`_started`'s own design is already correct and its ticket-37 docstring says why.
The write is `with LOG.open("a")`, which flushes on close, so buffering is not
the hole.

## The second instance

`34054751-aad4-494f-adb6-5052ac69fbea`, 2026-09-09, is the near-miss version and
the reason this is a class rather than a one-off. `ccw-hook` logged `started` at
08:16:35Z and then NOTHING: no `ok`, no error. The session is in the archive
anyway, catalogued at 08:38:51Z, 22 minutes later by another route. The only
thing that noticed anything wrong that day was the freshness check ALERTing on
aggregate breakage; nothing flagged that one session's hook had died.

A `started` with no `ok` is ALREADY a defined defect signal, written down in
`_started`'s own ticket-37 docstring. Nothing reads it.

## Decided (2026-09-13, jointly with the session investigating from ~/.claude)

ORDER: the alarm ships FIRST, then the dispatch line. Amendment accepted
2026-09-13. The alarm covers BOTH incidents; the dispatch line covers only the
5c652174 shape, and adds exactly nothing for 34054751, which did reach `started`.
Cheapest and broadest goes first. If only one of the two ever ships, it is the
alarm.

DO: a pre-python dispatch line. Change the `hooks.json` command to a shell
wrapper that appends a timestamped `{"source":"ccw-hook","status":"dispatched"}`
line and then `exec`s python. Shell startup is a couple of ms. It cannot know
the session id (that is on stdin, and reading it would consume the payload), and
it does not need to: the open question is "never dispatched" vs "dispatched and
killed", and a bare timestamp answers it. Pair by proximity to the SessionEnd
event, not by id.

DO: a `started`-without-`ok` alarm. Covers the 34054751 shape. Must be
non-blocking on the `ccw doctor` exit code, per ticket 38 ruling (e) and the
24.7 lesson: `ccw-watch` greps `^\s*FAIL` and `ccw-freshness-check.py` reads the
exit code, so a new informational line must never move either.

DO NOT: defer the heavy imports into their functions. Proposed and declined on
measurement. It saves at most ~15 ms of a 30 ms bounded window, against a 700 ms
dispatch window, and costs an edit to a file whose current shape is load-bearing.
It improves odds on the step that was never the likely killer.

Both sessions measured this independently and got different absolutes: 20 ms
here, 39-41 ms from the ~/.claude session, a gap attributed to method (that
timing wrapped shell plus spawn). Recorded because it is unresolved. It does not
move the decision: the SAVING measured ~15 ms here and ~17 ms there, and the
saving is the only number the decision turns on. The argument that settled it
was the asymmetry, not the size: optimising the bounded half of a window whose
unbounded half is the likely killer is the wrong move.

## Deliberately NOT bundled, flagged not dropped

Reading stdin with a timeout instead of blocking to EOF. That is prevention
rather than detection and is probably the real fix, but it changes behaviour on
a path that must never lose a payload. Own design pass, own ruling.

## Rollout, so "done" is not overclaimed

Editing `plugins/cc-capture/hooks/ccw-hook.py` in this repo does NOT change what
runs. Claude Code executes the plugin from
`~/.claude/plugins/cache/cc-warehouse/cc-capture/7ab4793b3a97/`, independently
confirmed by both sessions (`installed_plugins.json` records that versioned path
as the install), so any change
here is inert until a `/plugin` update lands it. That is the operator's action at
his own terminal. Same shape as this repo's frozen-install rule for `ccw`. After
building, the honest state is "written and tested, NOT live".

## DONE 2026-09-13 (repo half). NOT LIVE.

Two corrections to the plan above, both found by checking the code before
building it, and both recorded because the plan as agreed was wrong.

**THE ALARM WAS ALREADY BUILT. It was not built again.** `doctor._dispatch_gap`
(ticket 41 Finding 4 / ticket 42 #6) already asks exactly the 5c652174 question:
which not-yet-archived sessions have no `started` line in `ccw-hook.log`. It
prints as doctor's `dispatch` line, non-blocking by the ticket 38 (e) posture.
The 34054751 shape is instrumented too, verified rather than assumed: its
`capture.jsonl` line reads `repair: no catalog row for 34054751-...` at
2026-09-09T08:38:04Z. So the "nothing reads the started-without-ok signal" claim
in this ticket's own body was WRONG, and would have shipped a duplicate check.

**THE DISPATCH LINE SHIPPED IN-PROCESS, not as the agreed shell wrapper.**
`report("dispatched", "")` is now the first statement of `main()`, ahead of
`sys.stdin.read()`. That closes the UNBOUNDED step, which is the whole point,
and leaves only bare interpreter startup (~10 ms, bounded) uninstrumented. A
shell wrapper would close that last 10 ms as well, at the cost of a new file and
a new moving part in `hooks.json`. Judged not worth it until evidence says
otherwise; the reasoning is in the code comment beside the call.

Also corrected: `_dispatch_gap`'s docstring asserted that a missing `started`
line "means Claude Code never invoked the hook for it at all". It does not, and
could not have: `started` sits behind the read. The docstring now says the hook
never reached its first log write, and says the two cases are indistinguishable
until enough log history carries a `dispatched` line.

Shipped: `report()`'s quiet set gains `dispatched` (a line written on EVERY
session end must never reach the voice server; pinned by a test with a control
that proves the spy is reachable). Three new oracle tests, written red first.
Five existing exact-sequence assertions updated to `["dispatched", "started",
...]`, still pinned exactly rather than loosened.

Gates: ruff clean, pyright strict clean, 1,627 tests pass. `test_packaging.py`
caught a real leak in this file's first draft (a personal home path in a public
repo) and it was scrubbed.

**STATE: written and tested, NOT LIVE.** Claude Code runs the plugin from
`~/.claude/plugins/cache/cc-warehouse/cc-capture/7ab4793b3a97/`, confirmed
independently by both sessions via `installed_plugins.json`. Nothing here takes
effect until the operator runs `/plugin update` at his own terminal. Doctor's
docstring change additionally needs the frozen reinstall
(`uv_tool_reinstall_current_project --no-extras`), also the operator's call.

Postscript: `5c652174` reached the archive at
`fonzarelli-.claude/20260912-190922+1000_5c652174-...` when the 12:30 sweep ran
on 2026-09-13. The net held, as designed.

## Rollout addendum, 2026-09-13: "live" means NEW sessions only

A session resolves its plugin path at START, so a session already open when the
update lands keeps running the OLD cache dir until it is closed. Measured in the
real `ccw-hook.log` in the first 90 seconds after install, three genuine session
ends:

    03:06:33  started 30f48a8c -> ok                       2 lines, OLD hook
    03:07:26  dispatched -> started c68469f6 -> ok         3 lines, NEW hook
    03:07:44  started 12ffa665 -> ok                       2 lines, OLD hook

Two of three still uninstrumented. Corroborated from the other session's own
`PATH`, which carries `.../cc-capture/7ab4793b3a97/bin`, the pre-update version,
because that session started before the push. Old sessions drain naturally as
they are closed; nothing to do, but "live" is not "live everywhere" on the day of
an update, and a silent hook death in an already-open session is still possible
until the last one closes.

## Correction to the residual figure

The ~10 ms of bare interpreter startup quoted above is THIS session's
measurement. The other session measured 20-21 ms warm over three runs, same
method gap as the earlier import disagreement (that timing wraps shell plus
spawn). So the residual blind window may be double what is written above. Both
figures are bounded and small, neither changes the decision to skip the shell
wrapper, and 10 ms should not harden into a fact without this caveat.
