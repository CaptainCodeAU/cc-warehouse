# Ticket 41: capture-alert incident, 2026-09-09 - findings and open gaps

Opened 2026-09-09. NOT started. A live incident investigation (a peer Claude
Code session relayed a `ccw-freshness-check` ALERT: "16 session-starts in a
row, 56 uncaptured, growing ~23/hr"), followed by a RedTeam skill review (7
adversarial agents) of the investigating session's own conclusions, direct
forensic verification, then a RootCauseAnalysis skill pass (3 more parallel
forensic agents) at the operator's explicit request to find the actual root
cause rather than stop at "safely recovered." This ticket is the write-up:
what was found, what's confirmed, what's still open, and scoped proposed
fixes. **Full raw evidence (fault tree, per-UUID log correlation, raw log
lines) lives in the companion file
`harness/tickets/41-addendum-rca-evidence-2026-09-09.md` - read it before
re-running any of this investigation's fact-finding.** No code changed yet -
filed for review before anything touches the live hook.

## What actually happened (now confirmed with hard evidence)

Timeline, all times UTC (local Melbourne = UTC+10):
- 00:02-02:28: `ccw-freshness-check` (SessionStart hook, ticket 24.7) logged
  an escalating ALERT streak, `~/.claude/logs/ccw-hook.log`, peaking at
  "16 session-starts in a row (56 uncaptured)" at 02:28:09.
- 02:38:14: the next freshness-check log line reports `status: "ok"`,
  `"uncaptured=3"` - but written under a DIFFERENT Python interpreter
  (`.../cc-warehouse/.venv/bin/python3` 3.12.12, the DEV checkout) than every
  other entry that day (`/opt/homebrew/.../python3.14` 3.14.7, the real
  installed copy). Root cause, confirmed: a new Claude Code session started
  inside THIS repo at that moment (this investigation's own session), and its
  SessionStart hook ran under the repo's `.venv` because `direnv`/`.envrc`
  puts it ahead of `~/.local/bin/ccw` on PATH - the exact "wrong binary from
  inside the repo" trap CLAUDE.md already documents for interactive use,
  triggering for the first time (that we've found) inside an AUTOMATED HOOK.
- 02:45:08-02:45:37: `~/cc-warehouse-data/logs/capture.jsonl` (the durable
  log ticket 35 added) shows 23 `"repair: fixed"` records - `ccw repair`
  (the daily 12:45-local launchd job) re-rendering 23 already-catalogued but
  incomplete archive folders. This is what a `find -newermt` sweep over the
  archive tree also caught (17 of the 23 - the other 6 didn't bump their
  parent folder's mtime, consistent with a repair that only rewrites files
  already present).
- No `capture.jsonl` entries exist anywhere for a `ccw sweep` run that day -
  not because sweep didn't run, but because (see Finding 2) a fully
  successful sweep run has NO durable log record at all, success or
  otherwise. `ccw sweep`'s own launchd-redirected stdout log
  (`~/.claude/logs/ccw-sweep.log`) is 0 bytes, dated 4 Aug, because
  `--quiet` suppresses stdout and nothing else writes there.
- Direct verification (not inference): diffed every current source session
  UUID against every current archive folder UUID by name. Exactly 10
  sessions currently lack a folder - 9 are brand-new/still-open sessions
  from the last 90 minutes (baseline noise), 1 is an unrelated
  `.orphaned-*` file from 2026-07-09. **None of the 56 sessions from the
  alert window are missing right now.**

**Verdict, REVISED by the RCA pass below: the 56-session backlog itself was
recovered safely (confirmed) - but 3 specific sessions hit by a different,
distinct bug (Finding 5) currently have NO trace anywhere on this machine.
"Nothing was lost" was correct for the backlog as a whole and wrong as a
universal claim. See Finding 5 for what's actually still missing and why
the earlier by-name diff couldn't have caught it.** The backlog recovery
mechanism itself is now understood: `ccw sweep`'s normal daily run created
the missing folders (its own scan doesn't depend on the hook having fired
at all - confirmed in the addendum), with `ccw repair` 15 minutes later
finishing incomplete renders - the sweep half of that story still has no
durable log evidence of its own, which is Finding 2 below.

## Finding 1 (HIGH): a live hook can silently run the dev checkout instead of production

CLAUDE.md already documents this trap for INTERACTIVE `ccw doctor` runs from
inside this repo. This incident shows it also fires for the `ccw-freshness-check.py`
SessionStart hook itself, automatically, any time a Claude Code session
starts with this repo as its cwd (or a `.envrc`-activated shell inherits
into the hook's environment). A freshness-check reading taken this way may
not reflect the real installed system - which is exactly what made this
incident's recovery signal look suspicious to every one of 7 independent
red-team reviewers before direct forensics cleared it. Confirmed with three
independent, converging pieces of hard evidence (not inference): the
mismatched line's Python version exactly matches this repo's `.venv`; a
Claude Code session (`bdf71b7d-a66a-4a96-899f-5c5de376faa7`) started with
this repo as cwd 2.7 seconds after the log line's timestamp; and `direnv
status` shows this repo's `.envrc` has been in the `allowed` state since
2026-08-20, three weeks before the incident, not a one-off.

**Proposed fix:** have the plugin's hook wrapper (or `ccw-freshness-check.py`
itself) resolve and invoke the installed binary by an explicit path
(`~/.local/bin/ccw`, or equivalent env-var override), never a bare `ccw`
that PATH/venv activation can redirect. Scope: `plugins/cc-capture/hooks/`.

## Finding 2 (MEDIUM): `ccw sweep` has no durable log record on success

Ticket 35 (2026-09-01) added durable logging for `ccw build`/`ccw sweep`'s
per-item FAILURES and for every `ccw repair` outcome (success and failure,
regardless of `--quiet`). It did not add a per-run SUMMARY record for `ccw
sweep` itself. A sweep run that captures 50+ previously-uncaptured sessions
with zero failures - exactly what this incident's recovery needed - leaves
no trace in `capture.jsonl`, and the launchd stdout redirect
(`ccw-sweep.log`) is empty by design (`--quiet`). The only way to confirm
sweep ran today was to reconstruct it from indirect signals (the
`uncaptured` count dropping, folder mtimes, `ccw repair`'s log). `launchctl
print` only gives a lifetime run count with no per-run timestamp.

**Proposed fix:** one durable `capture.jsonl` record per `ccw sweep`
invocation summarizing the run (items seen, stored, sidecars, failed),
mirroring what `_log_repair_outcome` already does for repair - same file,
same schema, called regardless of `--quiet`. Scope: `cli.py::_run_sweep`.

## Finding 3 (LOW): ALERT wording doesn't distinguish "queued" from "actually broken"

Already a documented, known weakness (`docs/operations.md`, ticket 34's own
account): the freshness-check ALERT text names the raw uncaptured count but
not which underlying `ccw doctor` check is actually failing, so a reader
(human or peer agent) can't tell "the daily net will clear this shortly"
from "the hook itself is broken." This incident is a real example: the peer
session that relayed the alert reasonably read it as live, ongoing data
loss. Not new, just newly confirmed as a real source of confusion in
practice, not just a theoretical one.

**Proposed fix:** out of scope to design here (needs the same care ticket
34/38's non-blocking-line design got) - flagging for a future ticket rather
than proposing wording now.

## Finding 4 (RESOLVED root cause, HIGH): the "~50 uncaptured" figure was mostly a pre-existing backlog, and the live hook was never invoked for most of what did happen

The RCA pass corrected the framing itself first: only 14 sessions actually
ended during the 2.5h incident window (checked directly against every
transcript's last message timestamp), not ~50. The freshness-check's first
reading of the day already showed 39 uncaptured at 00:02Z - most of the "56"
predates the window.

Of those 14 real session-ends, **12 have zero entries anywhere in
`ccw-hook.log`'s entire history - the SessionEnd hook was never invoked for
them at all**, spanning 4 different project directories (ruling out one
project's config). This is a Claude Code-side dispatch gap, not a `ccw`
crash or timeout - `ccw-hook.log` only records what happens AFTER Claude
Code invokes the wrapper, so this project's own logs cannot see WHY the
dispatch didn't happen. All 12 were independently recovered by `ccw sweep`'s
normal scheduled scan regardless (sweep does not depend on the hook ever
having fired), so no data loss resulted from this specific mechanism.

Two of the 14 show a genuine `ccw`-side signal: 1 got a `started` line with
total silence after (SIGKILL-mid-run signature, matching a documented
2026-09-06 precedent in `ccw-hook.py`'s own docstring), 1 captured normally
(proving capture wasn't universally broken). A source-level fault tree
(addendum) ranks the SIGKILL mechanism, compounded by new synchronous I/O a
same-day-prior release (0.1.4, installed ~17.5h before the incident) added
inside the hook's 40-45s timing budget, as the most plausible explanation
for cases where the hook DOES fire but doesn't finish - a separate,
narrower failure mode from the 12 no-fire cases.

**Proposed fix:** none proposed for the Claude-Code-side dispatch gap itself
(outside this repo's code - see "Genuinely open" below). For the
compounding I/O-budget risk, consider moving `_archive_sidecars_of`/
`_archive_external_of` (capture.py:440-547) off the hook's synchronous
critical path, matching how render is already detached (cli.py:448-456) -
flagged, not scoped as a concrete diff here.

## Finding 5 (CRITICAL, genuinely unresolved): 3 specific sessions have no trace anywhere on this machine

Distinct from Finding 4. Three sessions (`5604f5fd-8fab-40bf-8ca9-69e5b1a93c47`,
`bf09caea-0fb3-4305-a0a7-0ad06137e541`, `313b7e02-3fff-4ae4-8122-44c013a0fe70`)
show the hook logging `started`->`ok` (success) while `capture.jsonl`
simultaneously logged `error: unreadable transcript ... No such file or
directory` for the exact same path, same second. Direct checks (not
inference): their source `.jsonl` files do not exist anywhere under
`~/.claude/projects` (checked by UUID glob, at any depth, under any name,
including the `.orphaned-*` rename pattern ticket 38 documents - not
found), and no archive folder exists for any of the three either.

**This is why the earlier "nothing was lost" verdict in this same ticket was
wrong as a universal claim**: that check diffed CURRENT source files against
CURRENT archive folders, which structurally cannot see a session whose
source file is already gone from both sides.

Root code path identified (see addendum for the full trace):
`capture.capture_transcript` (capture.py:694-713) correctly returns an
`error` result rather than raising on an unreadable transcript (documented,
deliberate - R5/R10), and `cli._run_hook` (cli.py:549-582) is documented to
"always exit 0" regardless (deliberate - F7, a hook must never crash Claude
Code's own hook runner). **Both of those are correct, intentional design.
The actual gap: nothing consumes the `error` records `capture.jsonl`
correctly writes to trigger a retry, and `status.uncaptured_gap`
(status.py:84-107) only diffs files CURRENTLY present in the source tree -
so a session whose source file disappears before capture succeeds is
invisible to every existing `ccw doctor` check, permanently, with no alarm
ever firing.** That blind spot is real regardless of how these specific 3
files vanished.

WHY the 3 source files vanished is NOT determined. Best working hypothesis
(NOT confirmed): `started`->`ok` logged in the same second for all three
suggests a very short-lived, effectively-empty session that Claude Code
itself may never have durably written - but this is inference, not a
verified fact.

**Proposed fix (two parts):** (a) close the observability blind spot -
doctor/status should be able to flag "a source file this project once knew
about (via `ccw-hook.log`'s own `started` entries) is now gone and was never
captured," which needs a source distinct from directory-listing alone,
likely `ccw-hook.log`/`capture.jsonl` itself as the source of truth for
"once existed." (b) determine whether these 3 sessions ever held real
content - needs the operator's own memory of that time window (01:56-02:18Z
= 11:56am-12:18pm local, projects Network-Plan and fifty-shades-of-dotfiles)
or access to Claude Code's own session records, neither of which this
investigation could reach.

## Finding 6 (formerly Finding 3, renumbered, LOW): ALERT wording doesn't distinguish "queued" from "actually broken"

Already a documented, known weakness (`docs/operations.md`, ticket 34's own
account): the freshness-check ALERT text names the raw uncaptured count but
not which underlying `ccw doctor` check is actually failing, so a reader
(human or peer agent) can't tell "the daily net will clear this shortly"
from "the hook itself is broken." This incident is a real example: the peer
session that relayed the alert reasonably read it as live, ongoing data
loss. Not new, just newly confirmed as a real source of confusion in
practice, not just a theoretical one.

**Proposed fix:** out of scope to design here (needs the same care ticket
34/38's non-blocking-line design got) - flagging for a future ticket rather
than proposing wording now.

## Genuinely open, not resolved by this ticket

- **Why Claude Code's own hook dispatch didn't invoke the SessionEnd hook
  for 12 of 14 sessions (Finding 4).** Outside this repo's code and logs -
  `ccw-hook.log` only sees what happens after invocation. Would need
  Claude Code's own session/hook-dispatch internals, which this
  investigation could not reach.
- **Whether the 3 sessions in Finding 5 ever held real content, and whether
  they're recoverable.** The single highest-priority open item from this
  whole incident - needs the operator's input or a source this
  investigation doesn't have access to.

## Provenance

Surfaced during an interactive investigation this session, escalated twice
at the operator's explicit request rather than accepted at face value: first
a 7-agent RedTeam skill review (EN-2, EN-3, EN-6, AR-6, PT-2, PT-7, IN-3) of
the "resolved, nothing lost" conclusion, which unanimously flagged the
causal story as under-evidenced; then, once the backlog-recovery question
was settled by direct forensics (the `capture.jsonl` grep, the by-name UUID
diff), a RootCauseAnalysis skill pass (3 parallel agents -
`q1-source-faulttree`, `q1-log-timeline`, `q1-system-schedule` - findings 4
and the seed of finding 5) to answer the harder "why did this happen at
all" question the first pass had explicitly left open. Finding 5's full
scope (the 3 sessions being genuinely untraceable, not just flagged as a
log contradiction) was established by the lead session's own direct
follow-up checks after the RCA agents reported back. Full raw evidence for
all of the above: `harness/tickets/41-addendum-rca-evidence-2026-09-09.md`.
