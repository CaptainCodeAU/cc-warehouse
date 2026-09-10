# Session handoff log

Dated, chronological account of what each past session on this repo actually did - one
entry per handoff, **newest first**. Split out of `OPENING-PROMPT.md` on 2026-08-27,
where this ran 844 lines (94% of that file's total) as an undifferentiated block with no
headers, just bold paragraphs, making it easy to read start to finish but hard to jump
into. Each entry below now has a real `###` heading so it is greppable and linkable.

Two things to know before reading:

- **Entry text is otherwise unmodified from the original**, including its own internal
  references to "above"/"below" other handoffs - those are relative to the ORIGINAL
  oldest-first reading order the prose was written in, not this file's newest-first
  layout. If an entry says "see the twelfth handoff below", look for it further DOWN
  this file's chronological numbering, not necessarily below on the page.
- **The seventeenth handoff never had its own dated entry until this split.** It existed
  only as a condensed status block inside `OPENING-PROMPT.md`'s old "ACTIVE TASK: ticket
  28.9" section. It is reconstructed here in its rightful place in the sequence.

For live "what to do next" state, read `OPENING-PROMPT.md`, not this file. For
recurring environment gotchas, read `harness/GOTCHAS.md`. For a closed ticket's full
technical account, read its file in `harness/tickets/`.

### Forty-ninth handoff, 2026-09-10 (ccw repair could pop a Finder window open on an unattended scheduled run)

The operator asked directly: does anything scheduled ever launch Finder, when that should
only happen for a human ending a real session in real time? Checked against the actual
code rather than assuming. `open_folder` (`[notify] open_folder = true` in this machine's
config.toml) is one shared switch. Two places read it: the live hook's own detached render
child (`cli._spawn_render`, correct - a human just ended a real session) and `ccw repair`'s
render subprocess (`cli._run_repair`, wrong - a daily 12:45 scheduled job with nobody at
the machine). `ccw sweep` and `ccw archive` were checked too and confirmed clean: neither
shells out to `ccw render --session` at all, so neither can reach this switch.

The bug had never fired live on this machine (`ccw doctor`'s desync check has stayed green,
so repair has never yet had anything to fix), but it is not hypothetical: writing a real
oracle test for it (`tests/test_repair.py::test_repair_never_opens_finder_even_when_open_
folder_is_configured_on`) genuinely popped a real Finder window on this machine the first
time it ran, before the fix, because nothing stopped the real render subprocess from
running for real. Fixed by forcing `CCW_OPEN_FOLDER=0` into that child's environment
explicitly in `_run_repair`, regardless of what config.toml says - repair keeps its own
rule instead of inheriting the hook's. Full suite 1626 passed (was 1625), ruff and pyright
strict both clean, all independently re-run.

### Forty-eighth handoff, 2026-09-10 (custom-title.json: new Claude Code sidecar was firing false alarms and going unbacked-up)

Two real desktop notifications from this machine's own `cc-warehouse` alerts prompted this:
an "unarchived sibling(s) beside dc7a3c48: custom-title.json" alert (the ticket 38
mechanism doing its job - a genuinely new sibling name), and a "1 session is permanently
unrecoverable" alert that turned out to be a false alarm from a `"session_uuid":
"probe-only"` synthetic test record left in the live `~/cc-warehouse-data/logs/capture.jsonl`
from testing ticket 42's alerting two nights earlier. The 2 fake lines were removed from
that log (backed up first) and confirmed gone.

`custom-title.json` (`{"customTitle": "..."}`, holding a session's renamed title) is real:
Claude Code started writing it beside a transcript's `<uuid>/` dir at some point after the
2026-09-06 sidecar census, confirmed on two separate real sessions on this machine. Unlike
`tool-results/`/`workflows/`, it is a single FILE, not a directory, so it got the
SUBAGENTS_DIR treatment instead of `copy_companion_dir`: added to `sidecars.SESSION_SIDECARS`,
its own `archive.write_custom_title`/`custom_title_record`/`_with_custom_title`/
`_custom_title_problems` (mirroring `write_prompts`'s shape exactly, including
`store.write_if_changed` rather than `write_if_absent` - a session's title can legitimately
change on a later rename, so refuse-on-conflict would have frozen the archive at the first
title forever), wired into `folder_is_current`, `verify_folder`, and both `capture.py`'s hook
path and `sweep.py`'s sweep/stranded-dir/dry-run paths. 24 new tests in `tests/test_custom_title.py`
plus additions to the three existing sidecar test files. Verified two ways beyond the oracle
suite: the REAL session that fired the original alert (`dc7a3c48-ecb2-4547-89e2-c3a312d3d2da`)
now scans as fully known with no anomaly, and a synthetic genuinely-unknown sidecar file was
confirmed to still trip the detector - the fix closes the real gap without blinding it.
Full suite 1625 passed (was 1607), ruff and pyright strict both clean, all independently
re-run rather than taken on the implementing agent's word.

No `pyproject.toml` version bump: `folder_is_current`'s own existing None-vs-`{"present":
False}` mismatch already forces exactly one rebuild per folder to backfill the new
`custom_title` manifest key, the same mechanism ticket 38's `COMPANION_MANIFEST_KEYS` loop
already relies on - a renderer_version bump was not needed for this to self-heal.

### Forty-seventh handoff, 2026-09-10 (ticket 41 Finding 5: narrowed the 3 untraceable sessions further, still not closed)

The operator asked to chase ticket 41 Finding 5's still-open CRITICAL item: whether the
3 sessions with no trace anywhere (`5604f5fd`, `bf09caea`, `313b7e02`) ever held real
content. Checked three more session-keyed stores beyond what the original investigation
covered - `~/.claude/file-history/`, `~/.claude/todos/`, and `~/.claude/history.jsonl` -
each with a known-good control session checked first so a zero would mean "absent," not
"the search is broken." All three came back empty for all three sessions. Went one step
further: this repo already keeps whole-file `history.jsonl` snapshots (ticket 39c), so
checked the earliest one taken AFTER all three sessions ended (40-60 minutes later) -
still empty. `tmutil listlocalsnapshots /` found no local Time Machine backup to check
as a last resort. Also noticed two of the three sessions were the same project, `started`
timestamps 2 minutes apart, with no other session in that project nearby - a
back-to-back near-instant pattern, not part of a normal busy run.

None of this proves nothing was typed - a prompt that failed before it reached
`history.jsonl` would look identical - but every store that would show real work is
empty, which fits the existing "near-empty session" hypothesis better than "real work
lost." Wrote the evidence into
`harness/tickets/41-capture-alert-incident-2026-09-09.md` (Finding 5) and corrected
`OPENING-PROMPT.md`'s ticket 41 bullet, which had said "NOT started" for a while after
findings 1-6 and their fixes had already landed. **This is still not closed**: the one
thing that can actually close it is the operator's own memory of that time window
(2026-09-09, roughly 11:56am-12:18pm local, in `Network-Plan` and
`fifty-shades-of-dotfiles`) - asked directly, not yet answered as of this handoff.

### Forty-sixth handoff, 2026-09-10 (correcting stale status: ticket 42 #6 was already reinstalled and live)

The operator asked to reinstall `ccw` so ticket 42 #6 (the hook-dispatch-gap detector)
would go live, per `OPENING-PROMPT.md`'s queue, which said it was "coded, tested and
verified... but NOT yet reinstalled into the frozen `ccw` - needs the operator's
go-ahead first." Before running the reinstall, checked the live state first (per this
repo's own standing lesson that a read-only-looking check must still be proved, not
assumed) and found it was **already done**: the forty-fourth or forty-fifth handoff's
session (or a later one) must have run the reinstall without updating this file to say
so. Verified three ways, none of them just "it looks fine": the installed
`doctor.py` is byte-identical to the repo's `src/cc_warehouse/doctor.py`
(`diff -q`); its file timestamp (`2026-09-09T23:22:16`) postdates commit `788cac9`,
which is the commit that added the check; and a live `env -u VIRTUAL_ENV ...
~/.local/bin/ccw doctor` run already prints the new `dispatch` line
("6 session(s) never reached ccw-hook.log, e.g. ..."). No reinstall was run this
session - there was nothing left to do. Corrected the stale paragraph in both
`OPENING-PROMPT.md` and `harness/tickets/42-capture-logging-and-alerting-gaps.md`
so the next session doesn't re-ask the operator for a go-ahead that was already
given and acted on. Pushed the doc fix (`c26be5a`) with the operator's go-ahead.

Then scoped ticket 42's last open item - "register capture logic in `settings.json`
directly" as a hedge against Claude Code's open plugin-loading bug (#16288). Presented
the operator three real options rather than picking one: (A) build a real second hook
registration (safe to double-fire, since capture is content-addressed, but creates a
second config to keep in sync with the plugin's forever - the exact "which one is
actually live" confusion class this repo's own CLAUDE.md hard rule exists to prevent),
(B) rely on the backstop that already exists (daily `ccw sweep` + #6's now-live doctor
check, both already built, catch a miss on the next run rather than instantly), or (C)
drop the idea. **Operator picked (B).** No code written. Recorded the decision and its
reasoning in `contract/DESIGN.md` section 15 ("2026-09-10, ticket 42's last unranked
item") and closed the ticket file. **Ticket 42 is now fully closed - every item done or
explicitly declined.**

Asked "what's next", swept the remaining queue for anything else genuinely ready to act
on, and found a third stale note of the same shape: `OPENING-PROMPT.md` said ticket
28.11 (sub-agent markdown/HTML rendering) was "coded and committed locally, NOT yet
pushed or reinstalled - pending review." Checked directly: `git log
origin/master..HEAD` showed nothing ahead (already pushed) and the installed
`render.py` is byte-identical to the repo copy (already reinstalled). Corrected the
paragraph. Also checked ticket 31.4's revisit condition (not ready - only ~1 day of
real signal since the fix that would settle it) and the session's flagged Critical risk
register item (already mid-mitigation, review booked 2026-09-23, nothing due now) -
both left as-is, nothing to fix there. Everything above needed the operator's own call
at each step; nothing was pushed without asking first.

### Forty-fifth handoff, 2026-09-09 (ticket 28.11: markdown and HTML for sub-agents; and two calls made without asking)

Continuation of the same session as the forty-fourth handoff. After ticket
42 #6 shipped, pushed, and was reinstalled live (operator go-ahead given),
the operator said "you pick" for what to do next. Two judgment calls were
made and documented rather than asked about, per that instruction:

1. Ticket 42's last open item (registering capture logic directly in
   `settings.json` as a hedge against Claude Code issue #16288) was reviewed
   and DEFERRED, not built. The addendum's own research found #16288 is not
   confirmed to be what caused this incident (that was a different bug,
   already fixed by ticket 37 Part B); doubling every session's hook
   overhead forever to hedge an unconfirmed risk was judged not worth it.
2. Ticket 28.2 (secret redaction on personal projections) was scoped and
   also set aside: closer reading of `share.py` showed its redaction is
   scan-and-abort, not scan-and-scrub, and the actual risk for LOCAL-only
   projections is low (the same secret already sits in `~/.claude/projects`
   before this project ever touches it). Genuinely "defensible either way,"
   as the ticket already said, so it stays undecided rather than picked
   without a real reason to prefer one side.

Picked ticket 28.11 instead: sub-agent transcripts get archived but never
rendered, so reading one meant reading raw JSONL by hand. Scoped by reading
`archive.write_subagent`'s own docstring (which literally said "sub-agents
are archived, not rendered... a flag for it recorded as future work") and
`write_session_folder`'s streamed-rendering machinery, then built the
smallest version that delivers the real value: a new `[render]
subagent_projections` config key (default OFF), and `write_subagent`
optionally rendering the same four files a session gets via
`store.write_if_changed` - no new manifest, no new incremental-skip system,
reusing `GENERATED_NAMES` (R9) and the "render the payload that survived"
lesson ticket 29 already paid for once.

7 new oracle tests, confirmed red against a `git stash` of just the
production diff before being confirmed green. Full suite 1607 passed (was
1604), ruff and pyright strict clean. Verified against real data: a real,
limited `ccw sweep --limit 200` into a scratch archive (never the real one)
rendered an actual sub-agent transcript correctly and a second sweep proved
idempotence; scratch directory deleted afterward. Default stays OFF, so
nothing changes for any existing install unless an operator opts in - not
pushed or reinstalled as of this handoff, pending the operator's review.
Full account: `harness/tickets/28-backlog.md`'s 28.11 DONE block.

### Forty-fourth handoff, 2026-09-09 (ticket 42 #6: the hook-dispatch-gap detector)

Picked up from the OPENING-PROMPT.md priority queue after the operator chose
it over the other two remaining options (settings.json capture registration,
chasing ticket 41's 3 unresolved lost sessions). The one item left in ticket
42's ranked list: build a `ccw doctor` check that answers "did Claude Code
even try to invoke our hook," distinct from every other check in the module,
which all ask "is it captured yet."

Shipped exactly to the ticket's own sketch: new `doctor._dispatch_gap(config,
walk_root, home)`, wired into `diagnose()` as a new non-blocking `dispatch`
line placed right after `overdue`. Reads `ccw-hook.log`'s `started` lines
(keyed on the full `session_id`, not the short hash `capture.jsonl` uses) into
a set, bounded to `_DISPATCH_WINDOW` (7 days, matching `_COMPANIONS_WINDOW`'s
posture); walks only unarchived source transcripts via
`sweep.source_transcripts`; flags any whose last activity (R12) is older than
`_DISPATCH_GRACE_SECONDS` (15 minutes) but still inside the window, and absent
from the started-set. Three "cannot answer" states read `ok=True` with an
explanatory detail rather than an alarm, matching `sidecars`/`history`/
`prompts`/`companions`/`reconcile`'s existing posture: no `ccw-hook.log` file
yet, a session that IS archived (sweep worked without the hook ever firing,
which is fine, not a gap), and a gap older than the window (`ccw reconcile`
already keeps the permanent record for that).

Deliberately did NOT touch `_overdue`'s own separate, longer-standing
archived-id-collection code, even though it duplicates a small amount of
logic with the new check's own archived-set read: refactoring a shared helper
would have meant re-verifying an existing, well-tested function's behaviour
for no functional gain, against a task that did not ask for it.

Oracle-tests-first, per this repo's own house rule: wrote 7 new tests in
`tests/test_doctor.py` against the not-yet-existing check, confirmed all 7
failed for the expected reason (`StopIteration` on a "dispatch" check that
didn't exist), then implemented, then confirmed all 7 passed. Two of the
tests needed a second pass after their first run exposed real test-design
gaps, not implementation bugs: one asserted a dispatch gap using a
completely-missing `ccw-hook.log` file, which the check correctly reads as
"cannot answer yet" rather than "gap" (fixed by giving the log an unrelated
entry so it exists but doesn't mention the session under test - the real
shape of ticket 41's actual incident); the other needed the same "isolate an
otherwise-healthy warehouse first" pattern the existing `history` non-blocking
test already uses, so only the check under test could move `report.ok`.

Full suite 1604 passed (was 1593), ruff and pyright strict clean
project-wide. Verified against real data, read-only, no reinstall needed
(doctor runs as ordinary dev-checkout code): `uv run ccw doctor` on this
machine found a genuine dispatch gap - 4 real sessions with zero
`ccw-hook.log` entries - and doctor's overall exit code stayed 0, confirming
the non-blocking posture holds outside the test suite too, not just inside
it. **Not yet deployed to the frozen `ccw` install** - that step needs the
operator's explicit go-ahead first, matching every other live-path change in
this ticket's own history. Full account:
`harness/tickets/42-capture-logging-and-alerting-gaps.md`'s #6 DONE block.

### Forty-third handoff, 2026-09-09 (real desktop notifications leaking from the test suite)

Triggered by the operator: two REAL macOS notifications appeared naming
`d3111111` and `zzz-probe`, right after the forty-second handoff's own test
runs. Both are hardcoded fixture constants (`PARENT`/`STDOUT_NAME`/probe dir
names reused across several sidecar test files), not real data - confirmed
by grepping the whole repo for both strings and reading the exact code
(`capture.announce_sidecar_anomaly`) that builds both message texts,
matching word for word.

Root cause: `notify.alert` fires a real `osascript` call whenever
`config.desktop_alerts` is true (the default, correct for real users - ticket
38 ruling (e)) and `sys.platform == "darwin"` (genuinely true here, no mock
involved). `tests/test_sidecar_capture.py` and `tests/test_sidecar_sweep.py`
both exercise the exact anomaly this alert exists for, via a REAL `run_ccw`
subprocess call, and neither mocks the sink.

Two fix shapes tried and rejected before the right one, both disproven by
direct evidence rather than assumed: a per-test `monkeypatch.setattr(notify,
"alert", ...)` only protects IN-PROCESS (`run_cli`) tests - `run_ccw` spawns
a real subprocess a same-process monkeypatch cannot reach, proven by finding
a THIRD live leak inside `test_sidecar_signal.py` ITSELF, a file that already
mocks `alert` carefully for its own dedup tests but has one unrelated
`run_ccw`-based test with no such protection. Pre-seeding the sandbox's own
`config.toml` with `desktop_alerts = false` was rejected too: several tests'
own `configure()` helpers later write a COMPLETE `config.toml` of their own,
overwriting any pre-seeded default.

Shipped: a new `CCW_DESKTOP_ALERTS` env var (`config.py`, mirroring
`CCW_OPEN_FOLDER`'s exact pattern), set to `"0"` for every test by
`tests/conftest.py`'s `ccw_env` fixture. Env beats file per this project's
own documented config precedence, so it survives regardless of what any
test's own config.toml says - real users are unaffected, since nothing sets
this variable outside a test sandbox. Four new oracle tests, one of them
spying on the real `subprocess.Popen` call with the machine's REAL
`sys.platform` left untouched (not monkeypatched away, so a false pass from
mocking the wrong thing is not possible), confirming zero calls while the
anomaly itself is still correctly recorded. Full suite 1597 passed (up from
1593), ruff and pyright strict clean.

Committed and pushed. No plugin/reinstall step needed - this only changes
test-time behaviour and `config.py`'s honored env-var list, neither of which
the hook wrapper reads. Full account: `contract/DESIGN.md` section 15,
"2026-09-09: the test suite could pop REAL desktop notifications" entry.

### Forty-second handoff, 2026-09-09 (ticket 42 #2/#3/#7: the logs stop lying, ccw archive stays out of scope)

Picked up `OPENING-PROMPT.md`'s priority-order item 5 (ticket 42's remaining
ranked list) right after the forty-first handoff closed item 4. Confirmed
priority-order item 3 (ticket 31.4's retry loop) is still genuinely blocked
before starting: all 784 lines of the real `capture.jsonl` hold zero
lock-contention or stage-error records, so the exception 31.4 needs has not
happened yet.

Two Explore agents mapped the logging/doctor/hook code in parallel before any
design decision; direct reads of the real machine's logs followed
(`~/.claude/logs/ccw-hook.log`: 1,238 rows, `ccw-hook` source is 70 `started`
+ 61 `ok` + ZERO `error`, confirming Finding A on real data rather than
argument alone). Presented a scoped decision brief and got two operator
rulings via AskUserQuestion before writing any code: build #2+#3+#7 together
(not #6, not archive-consistency-for-its-own-sake), and the hook wrapper logs
truthfully without adding a second spoken alert (`ccw hook` already speaks a
graceful failure itself). A third question (skip the version bump, since
`renderer_version` is `__version__` and a bump would re-render 29,700+
folders for zero rendering change) was also confirmed before building.

**#3** (`sweep.py`): `_log_item_failure` widened from an `Exception` param to
a `detail: str`, so `_capture_item` calls the same writer on
`capture_transcript`'s graceful `error` result, not just a raised exception.
**#2** (`cli.py`): new `_log_run_summary` helper, wired into `_run_sweep` and
`_run_build` (including their lock-refusal paths) exactly as scoped. **#7**
(`cli.py` + `ccw-hook.py`): `_run_hook` prints its real outcome to stdout
before returning 0; the wrapper reads it and logs a new `capture-error`
status kept out of its own voice gate.

**One real design conflict found by execution, not anticipated in the plan**:
wiring #2 into `ccw archive` too (the ticket's own "for consistency" line)
broke a real, load-bearing contract on the first attempt -
`test_archive_cli.py::test_archive_leaves_the_source_warehouse_byte_identical`
- because `ccw archive --to DIR` is deliberately BUILD-BESIDE, and a
`capture.jsonl` write is a warehouse write. Reverted the archive call sites
rather than patch the test, left a scope note in `cli.py`, and added a
positive oracle test proving a real archive run leaves the warehouse's log
untouched. This is recorded as a decision, not a shortfall: ticket 41 Finding
2's actual incident was about `ccw sweep`, and archive's own scheduled job
already gets a durable record from its stdout redirect.

Also found and fixed two existing tests that assumed a build failure's error
record would be the LAST error record in `capture.jsonl`
(`test_batch_failure_logging.py`) - true before #2, false after, since a
failed run now also writes a per-run summary (also `status="error"`) after
the per-item one. Widened both assertions to search rather than assume
order, rather than reordering the writes to preserve a test's incidental
assumption.

New test files: `tests/test_sweep_graceful_error_logging.py`,
`tests/test_run_summary_logging.py`, `tests/test_hook_prints_outcome.py`;
four new tests added to `tests/test_cc_capture_hook_started.py`; one existing
test widened in `tests/test_reconcile.py`. Full suite 1593 passed, ruff and
pyright strict clean, project-wide - verified twice, once right after the
archive revert and once after fixing two pyright strict findings (a
`reportPrivateUsage` on `sweep._log_item_failure` used from a test, silenced
the same way `test_companions_detach.py`/`test_doctor.py` already do; a
`lambda` monkeypatch pyright's strict mode could not fully type, replaced
with a named function matching this file's own existing style).

Corrected a stale note in the ticket file while here: its "also worth
weighing" section still said the hook's synchronous companion-copying was an
open design tradeoff, but ticket 37 Part B (`cd84020`) had already closed it
earlier the same day, wider than that bullet's own two named functions.

**NOT done, and named rather than silently dropped**: ticket 42 #6 (the
hook-dispatch-gap detector) and the remaining unranked item (registering
capture logic in `settings.json` directly, as a redundancy hedge). Neither
was in the approved scope for this session.

**DEPLOYED AND VERIFIED LIVE, same day, operator go-ahead given for both
gates at once.** `uv_tool_reinstall_current_project --no-extras` (run via
`zsh -ic`, since the Bash tool's own shell snapshot was missing a helper
function the real interactive shell has), confirmed frozen via `ccw doctor`
run from outside the repo. Pushed (`81d75cf`), `claude plugin marketplace
update cc-warehouse` then `claude plugin update cc-capture@cc-warehouse`
(digest `5078316cc35b` -> `81d75cf8a55b`, matching the pushed commit).
Verified against real data, not just exit codes: a real `ccw sweep` wrote
`"sweep: 28128 items, 15 stored, 12 with sidecars, 0 failed"` to
`capture.jsonl`; `ccw archive --to ~/cc-warehouse-archive --verify` reported
0 problems across 29721 folders and left the warehouse's own log line count
unchanged (792 before and after, proving the archive-logging revert holds on
the real machine too); a direct `ccw hook` probe against a missing
transcript printed `"error: unreadable transcript ..."` and still exited 0;
grepped the actual plugin cache digest folder AND the installed package for
the new `capture-error` code, found in both.

Full account: `contract/DESIGN.md` section 15's "2026-09-09, ticket 42
#2/#3/#7" entry; `harness/tickets/42-*.md`'s items #2/#3/#7 DONE blocks.

### Forty-first handoff, 2026-09-09 (ticket 42 #5: reconciliation check, real number is 21 not 3)

Picked up priority-order item 4 from `OPENING-PROMPT.md` right after item 2 (the
fortieth handoff) landed. Dispatched the design/scoping to a Plan agent on the
`opus` model tier per the session's model-rung reminder (MAX-class judgment work,
this session itself was running one rung down); the agent measured the real
`capture.jsonl` first rather than trusting the ticket's own text, and found the
true figure was **21 permanently unrecoverable sessions, not the 3 ticket 41
named**, running at roughly 1-2 a week since 2026-08-08. Presented the agent's
options (A narrow / B recommended / C broad / D backfill add-on) to the operator;
picked B+D.

Built `src/cc_warehouse/reconcile.py`: `find_unrecoverable` is the expensive
source-tree + archive + catalog cross-check (all three must miss, the
conservative direction); `known_unrecoverable_count`/`known_unrecoverable_uuids`
are a cheap read of the dedup ledger `ccw repair` writes back into
capture.jsonl. **Deliberately split from the agent's plan on one point**: the
agent's design had `ccw doctor`'s line do the same cross-check as `ccw repair`,
just over the whole log instead of a window; this session judged that unsafe on
its own (not something the agent's report weighed) - `ccw doctor` runs on every
SessionStart via `ccw-freshness-check.py`, and ticket 41 Finding 1 already caused
a real SessionStart timeout once from an unrelated bug, so doctor's line reads
ONLY the already-cheap dedup ledger and never walks the archive itself. Proven
with a test that monkeypatches the expensive cross-check to explode and confirms
doctor never reaches for it.

Also added: the `session_uuid` structured field (threaded through the 3 call
sites that can supply one - `cli._report_capture`/`_run_hook`'s error path,
`sweep._log_item_failure` - with the prose-regex fallback kept permanently for
every record written before this field existed); a new read-only `ccw reconcile`
verb (prints the full unbounded history); `ccw repair` now runs reconciliation
BEFORE its desync early-return (the trap: that return fires on the normal
healthy-machine day, exactly when this needs to run) and announces new losses
once per run via desktop + voice, deduped by writing its own record back into
the same log (no new state file, matching the pattern `capture._note_unknown_
siblings` already uses for a different anomaly).

22 new oracle tests (`tests/test_reconcile.py`, `tests/test_doctor.py`). Full
suite 1574 passed, ruff and pyright strict both clean, project-wide. Reinstalled
the frozen `ccw` and ran the real, read-only `ccw reconcile` against the actual
warehouse: it found the same 21 sessions, by UUID, including the exact 3
(5604f5fd/bf09caea/313b7e02) ticket 41 had already flagged as an unresolved
critical unknown - independent confirmation of that finding. Committed `2d58f73`,
not pushed. **`ccw repair`'s live run was then triggered with the operator's
explicit go-ahead**: announced 15 newly-confirmed unrecoverable sessions (14-day
alert window; 6 of the 21 fall outside it and only show in `ccw reconcile`'s
unbounded view), wrote one dedup record per session, fired one real desktop +
voice alert for the whole batch. `ccw doctor`'s new `reconcile` line read back
"15 session(s) on record as unrecoverable" afterward, and a second `ccw repair`
run correctly printed nothing new - the dedup path is proven live, not just in
the test suite.

### Fortieth handoff, 2026-09-09 (ticket 42 #4: fixed `ccw status`'s "Recent errors")

Picked up priority-order item 2 from `OPENING-PROMPT.md`. Ticket 42 Finding B: the
"Recent errors" section reads the catalog's `capture_event` table for `action =
'error'` rows, but `catalog.record_event` is never called with `action="error"`
anywhere in the codebase (verified independently: capture.py:225, capture.py:264,
sweep.py:162, none of the three call sites pass it) - the section was permanently
empty by construction. The ticket offered two fixes (wire errors into the catalog,
or relabel/remove the section); presented both plus a third option found while
reading the code - point the section at `logs/capture.jsonl` instead, which every
real error source (unreadable transcript, lock unavailable, post-archive-write
stage failures, build/repair failures) already writes to via `notify.append_log`'s
shared six-field schema. The operator picked the third option. It also turned out
to be what DESIGN section 7's own `ccw status` contract already specified ("reads
catalog + log"): the catalog-only implementation was itself the drift from spec.

Shipped: `status._recent_errors` reads `logs/capture.jsonl`, reusing the same
JSON-lines parsing pattern `doctor._companions_stalled` already uses for a
different check (missing file or malformed line reads as no errors, never a
crash, matching R5). `status_text` no longer queries `capture_event` for errors;
its docstring and the module docstring are corrected to say catalog session
table + log, not catalog-only. 6 new oracle tests in `tests/test_status_verify.py`
cover: a real error surfaces, `(none)` with no log, non-error records excluded,
newest-first ordering, capped at `_ERROR_LIMIT` (5), and a malformed line does
not crash the read. Full suite: 1547 passed (6 of them the new ones above), ruff
and pyright strict both clean, project-wide. Not yet committed or pushed - left
for the operator's go-ahead. `OPENING-PROMPT.md`'s priority list item 2 marked DONE.

### Thirty-ninth handoff, 2026-09-09 (ticket 37 Part B: the detached companions child, shipped and verified)

Picked up the priority-order item 1 that the thirty-eighth handoff's session left
scoped-but-not-built: detach the hook's synchronous sidecar/external-file
copying into its own child, matching the render child's shape. Measured first,
which changed the scope twice before any code was written. Measured cost per
companion type on the real machine: sub-agents are 14-18 MB / 30-90 files on a
big session, ~90% of the hook's total elapsed time; the slowest real `stored`
capture in two days (4,331 ms) was nowhere near the 40s/45s timeout budgets,
independently confirming a hook lost mid-run is being killed by a signal, not a
timeout. On that evidence, and with the operator's confirmation, ALL FOUR
companion calls detach, not only the two the prior session's ruling named -
detaching just sidecars/external would have moved ~10% of the exposure and left
the ticket effectively open.

Shipped: `capture.py`'s four companion functions widened to take `session_uuid:
str | None` (not a full `ParsedSession`) and lifted into one public
`archive_companions()`; `capture_transcript(defer_companions=False)` (default
unchanged behaviour for sweep/import/migrate); `cli.py`'s new hidden verb `ccw
companions --session s:<key> --transcript PATH`, `_spawn_companions` (same
`start_new_session=True`, all-DEVNULL Popen shape SPEC locks), `_run_companions`,
`_log_companions` (writes `companions-started`/`companions-done`/`error` into
the EXISTING `logs/capture.jsonl`, six-field schema unchanged, every message
prefixed `"companions: "` so a later reader can tell this child's lines apart
from unrelated `error` records sharing the same `session` value); `doctor.py`'s
new non-blocking `companions` check (`_companions_stalled`, modelled on
`_history_staleness`, pairs started/done within a 7-day window with a 300s
grace period) - proved non-blocking with a real `grep -E '^\s*FAIL'`
subprocess, not just an assertion on the Python object.

**A live, distinct incident found and fixed on the way, unplanned:**
`store.get()`'s bare `read_bytes()` failure formats fine via `str()` but its
`repr()` - what `notify.report`'s error path actually uses - drops the
filename entirely (`FileNotFoundError(2, 'No such file or directory')`, no
path, no hash). Confirmed this was live on the operator's machine: `ccw
doctor` was FAILing on exactly one folder (`9bde8f85`, go_research) with this
shape, the SECOND occurrence of a bug the prior ticket-37 session had already
seen once (`abaece35`) and flagged as "worth its own ticket line if it
recurs." It had recurred. `store.get()` now raises an OSError (same concrete
subclass via the original's own errno, so the one existing `except OSError`
caller elsewhere is unaffected) whose message names the hash and the vault
root.

**Reproduced that second bug's real mechanism end to end, in a scratch
archive_root, and found the ORIGINAL PLAN'S OWN GUESS WAS WRONG.** The plan
assumed a `build._heads` ranking bug (ticket 29's shape). Reproducing it
(a monkeypatched `catalog.add_session` failing right after a real archive
write) showed instead: the archive write succeeds and is durable, but that
SAME capture's own catalog-row insert then fails (ticket 31.4's own
already-documented sqlite-contention shape) - so the archive holds bytes at a
hash no catalog row names, and `ccw repair` can never fix this by
construction (it only ever re-renders from an existing row). Per the plan's
own instruction ("if the reproduction shows a different cause, write up what
it actually is rather than shipping the guessed fix"), no repair-logic change
was forced through; the already-working recovery is the next `ccw sweep`
picking the source transcript back up once it stabilizes.

**A second, genuinely new race, found by running the suite repeatedly rather
than trusting one green run**: adding a SECOND detached child per hook fire
raised the odds of hitting a PRE-EXISTING (not new) race in
`test_sidecar_sweep.py`'s manifest-rebuild test - proven with a `git stash`
comparison (8/8 clean on the base commit, 1/5 failing with the change
applied, 12/12 clean once the test got the `settle_render` wait it always
needed). One line fixed the test; nothing in the render or companions child
changed.

Test work: one general-purpose sub-agent, dispatched in parallel with this
session's own work, fixed the pre-existing `test_external_capture.py`/
`test_sidecar_capture.py`/`test_subagent_capture.py`/`test_sidecar_boundaries.py`
hook-then-assert races by adding a new `settle_companions` wait to
`tests/conftest.py` (the companions-child twin of the existing `settle_render`).
New oracle file `tests/test_companions_detach.py` (9 tests). Verified, not
assumed: `uv run pytest tests/ -q` run three times in a row, 1542 passed, zero
failures, zero flakes each time; full-repo `ruff check .` and `pyright` both
clean.

**Deployed and verified live, same session, operator go-ahead given.**
Committed (`cd84020`), pushed, frozen `ccw` reinstalled, plugin updated and
digest-verified against the checkout. A real peer session ending naturally
went through the new path unprompted and logged the correct
`companions-started`/`companions-done` pair 46ms apart; a manually-fired
uncaptured transcript did the same in 2ms. Caught one archive folder live,
mid-flight, from the exact ticket-37 mechanism this fix closes (started
moments before the fix landed, never finished) - `ccw repair` correctly could
not fix it and said why; a full `ccw sweep` (0 failed) closed it and the
already-known `9bde8f85` stale-manifest incident together. Final state: `ccw
doctor` reports "capture is working" and `ccw archive --verify` reports
29705 folders, 0 problems. **Left open for the operator**: whether `ccw
repair` should read `capture.jsonl`'s own error line to enrich its "still
broken" report for the stale-manifest bug (small, safe, deliberately not
freelanced - the operator chose to leave it as documented for now). Full
account: `harness/tickets/37-*.md`'s "Part B DONE, 2026-09-09" section;
`contract/DESIGN.md` section 15's matching dated entry.

### Thirty-eighth handoff, 2026-09-09 (ticket 41 Finding 1 shipped and verified live)

Picked up out of the stated queue order (item #6, moved ahead of #2/#4) after the
principal asked to investigate a live SessionStart hook warning ("could not check
capture, 4 session-starts in a row") rather than proceed straight to ticket 42 #4. Root
cause, confirmed not inferred: `find_ccw()` in both `plugins/cc-capture/hooks/ccw-hook.py`
and `ccw-freshness-check.py` resolves `ccw` via `shutil.which("ccw")`, and this repo's
own `.envrc` puts `.venv/bin` ahead of `~/.local/bin` on PATH for any process whose cwd
is under the repo - so a hook fired from a cc-warehouse session silently ran the editable
dev checkout instead of the frozen install. Direct evidence: session
`4c934843-9283-459a-be57-7224d9c8ea58`'s `ccw-hook.log` "started" line names
`.../cc-warehouse/.venv/bin/python3` as its interpreter (a 4th same-day instance of the
already-tracked ticket 37 Part B "started with no ok/error" pattern - it got captured
anyway, later, by a sweep, not by the hook completing), and `~/.claude/logs/ccw-freshness-
state.json` showed `consecutive_broken` climbing to 5 while the timeouts happened - all
against that same dev copy (`_DOCTOR_TIMEOUT=45`). Manually running the frozen install
correctly (`env -u VIRTUAL_ENV PATH=... ~/.local/bin/ccw doctor`) answered in a few
seconds both times, ruling out doctor itself being slow.

Fix: both `find_ccw()` copies now skip a `shutil.which()` hit under `/.venv/` and fall
through to the frozen `~/.local/bin/ccw` shim; the explicit `CCW_BIN` override is
untouched. Oracle tests first (`tests/test_find_ccw_skips_dev_checkout.py`, 6 cases across
both modules): confirmed red before the fix, green after. Full suite 1531 passed, ruff and
pyright both clean. One thing the new test file itself violated on the first pass and had
to be corrected before commit: it hardcoded the real machine's home-directory path,
tripping `test_packaging.py::test_no_forbidden_content_in_the_artifact` - replaced with
`tmp_path`-relative and generic system paths per this repo's own "never commit personal
data" rule.

**SHIPPED AND VERIFIED LIVE, not just committed.** Pushed `971bbc4`, then
`claude plugin marketplace update cc-warehouse` followed by
`claude plugin update cc-capture@cc-warehouse` (`a7815557d7b2` -> `971bbc4e43de`,
"restart required to apply"), then verified by grepping the actual plugin cache copy at
`~/.claude/plugins/cache/cc-warehouse/cc-capture/971bbc4e43de/hooks/{ccw-hook,ccw-
freshness-check}.py` for the new `"/.venv/" not in found` line directly - present in both.
Not yet re-measured post-restart whether the 45s timeout itself stops recurring (the disk-
at-95%-full angle raised during investigation is a real but unproven contributing factor,
separate from this fix); a future session should check `~/.claude/logs/ccw-freshness-
state.json`'s `consecutive_broken` after a few more session-starts. Ticket 41's own file
should have Finding 1 marked closed with this account; `OPENING-PROMPT.md`'s priority
list item #6 updated to point here instead of restating it.

### Thirty-seventh handoff, 2026-09-09 (ticket 42 #1 shipped; ticket 37 Part B found chronic)

Ticket 42 item #1 (real desktop/voice notification on `ccw-freshness-check.py`'s
WARN/ALERT tiers, top of `OPENING-PROMPT.md`'s priority order) is DONE:
`_desktop_alert` (ported by hand from `notify.py`'s `alert()`, since this file must
never import `cc_warehouse`) fires from the WARN tier (streak 2+) onward, voice from
ALERT (streak 5+) onward, fire-and-forget via `subprocess.Popen` so no new timeout was
added to the budget `test_the_freshness_hook_budgets_fit_inside_its_own_outer_kill`
already pins. The unlabelled tier-0 first miss (streak 1) got its own new log status,
`"info"`, deliberately kept off both notification channels - collapsing it into "warn"
(the pre-fix shape) would have raised a desktop toast on the very first failed check,
every time, the exact chronic-banner trap ticket 24.7 exists to avoid. 8 new oracle
tests in `tests/test_cc_capture_freshness.py`, all previously-uncovered branches (the
escalating half of `main()` had zero test coverage before this). Negative control run
by hand: reverting the notification call sent 3 of the new tests red, confirmed, then
restored. Full suite 1525 passed, ruff and pyright both clean. **NOT LIVE**: the plugin
cache (`~/.claude/plugins/cache/cc-warehouse/cc-capture/68d5fa775651/...`) still holds
the pre-fix script; needs an operator-run `/plugin` update.

While verifying the fix (`ccw doctor` before touching anything), found capture
genuinely broken: `FAIL desync`, 3 sessions that day with a `started` hook-log line and
no matching `ok`/`error`. This is ticket 37 Part B's exact mechanism (opened
2026-09-06, previously one instance, cause undetermined), now shown to be CHRONIC (the
daily `ccw repair` job silently fixed 23 of these the day before) and correlated with
payload size (the two fully-broken sessions were the day's two largest, 3+ MB / 20+
sub-agent dirs each; every smaller session that day rendered fine). A third session in
the same batch had a different, newly-found failure: a stale catalog row from mid-growth
capture, and `ccw repair`'s attempted fix crashed on a `store.get` fallback to a
`objects/` vault this machine no longer has (`keep_objects=false` since ticket 27.3),
raising a bare `FileNotFoundError` that `notify.report`'s `repr(exc)` swallows without
the path. Full evidence, including the still-unresolved 40s-inner-vs-45s-outer timeout
arithmetic, appended to `harness/tickets/37-*.md`'s dated 2026-09-09 section.

**Same day, follow-up: the alert deployment was verified live end to end** (git push
was NOT yet done when the fix landed - traced why `/plugin` reported "already latest"
by matching the reported hash to the pre-fix commit, pushed `a781555`, then re-verified
the full chain: marketplace checkout commit -> new plugin cache folder ->
`_desktop_alert` actually present in the loaded file). **The operator then approved
`ccw sweep` to recover the 3 stuck sessions** (`31 stored, 0 failed`) - all three
confirmed rendered on disk, `ccw doctor` back to `ok desync` / exit 0. **Operator also
ruled on ticket 37 Part B's root-cause fix**: detach the hook's synchronous copying,
report failures via a log file a daily job reads (the same shape this repo already
uses for `sidecars`/`history`/`prompts`). Recorded in the ticket; the actual diff is
NOT scoped or built - genuine design work left for a dedicated session rather than
rushed under this one's original scope.

### Thirty-sixth handoff, 2026-09-08 (ticket 39: shipped and live - the reinstall and back-fill)

Continuation of the same day's session that built 39b-39g. With the operator's explicit
go-ahead (asked separately from every build slice, via a structured decision brief - a
green test suite is not consent to touch live infrastructure, the standing rule this
repo has applied at every prior destructive/production-affecting juncture), the two
remaining steps were run for real:

`uv_tool_reinstall_current_project --no-extras` reinstalled the frozen `ccw` at `0.1.4`.
The wrapper's first invocation failed with `command not found: _uv_tool_parse_flags` -
that helper is only defined via the interactive zsh's autoloaded functions, which this
session's non-interactive Bash tool does not source; re-running through `zsh -i -c '...'`
picked it up and the reinstall succeeded. Verified two independent ways, both agreeing:
`ccw doctor`'s `install` line (`frozen: running from .../cc_warehouse`) and PEP 610's
`direct_url.json` (`"dir_info":{}`, no `editable` key).

`ccw sweep` against the real `~/.claude/projects`, via the newly-frozen binary: real
output `31031 items, 16 stored, 3344 with sidecars, 0 failed`. The nonzero sidecar count
triggered the existing post-sweep `build.build()` call, which re-rendered every one of
the ~29,580 existing archive folders once (the version bump is what makes
`folder_is_current` see each one's manifest as stale) - zero render failures.

`ccw archive --to ~/cc-warehouse-archive --verify` (the first attempt, without `--to`,
failed with a usage error, not a data problem - `--to` is required even in `--verify`
mode): `29593 folders checked, 0 problems`. Post-run `ccw doctor`:
`Prompts: 1489/28940 session(s) have prompts.jsonl, 649 reference paste-cache files` -
spot-checked directly on disk, not just trusted from the report text.

Ticket 39 is closed. Full account: the ticket file's own "TICKET 39 IS SHIPPED AND
LIVE" block.

### Thirty-fifth handoff, 2026-09-08 (ticket 39: slice 39g, repo-only release paperwork)

**Version bump only, no code behaviour changed. Full suite, pyright strict and ruff
all still clean.** This slice was deliberately scoped to the safe, reversible,
in-repo part of "make ticket 39 a real release": `pyproject.toml`'s `version` moved
`0.1.3` -> `0.1.4`, `uv.lock` was re-synced with `uv lock` (its own `cc-warehouse`
entry now reads `0.1.4` too), and a new `0.1.4` entry was added to `CHANGELOG.md`
above the `0.1.3` entry, summarizing 39b-39f's real shipped scope (file-history/todos
mirror, the `history.jsonl` whole-file snapshot, the per-session `prompts.jsonl`
split, the paste-cache gather, and the cross-cutting refusal-visibility fix), in the
same voice and with the same "first build/sweep after upgrading re-renders the whole
tree once" upgrading note 0.1.3's own entry carries - the mechanism is identical,
since bumping `__version__` is what makes `folder_is_current` treat every existing
archive folder as stale.

**The frozen reinstall and the live back-fill were NOT run, on purpose.** Bumping
the version in the repo is a different event from installing it system-wide, which
is a different event again from running it against the real 28,924-session archive.
Both of those steps are exactly the kind of production-affecting, hard-to-reverse
action this repo's own `CLAUDE.md` requires the operator's explicit word for at the
moment of running, not a background session's call - and they were asked about
separately from this slice, not delegated to it. Nothing under `~/cc-warehouse-data`
or `~/cc-warehouse-archive` was touched at any point.

Docs updated to match: `harness/tickets/39-archive-what-a-session-points-at.md`
gained a closing "FUNCTIONALLY DONE, NOT YET RELEASED" block at the bottom stating
this plainly; `OPENING-PROMPT.md`'s "Next task" section now leads with the same
state instead of pointing at 39g as still-open work; `CLAUDE.md`'s ticket 39
paragraph got one closing sentence recording the same thing.

### Thirty-fourth handoff, 2026-09-08 (ticket 39: slice 39f, config gate and corpus-wide visibility)

**Test count 1,507 -> 1,518 (11 new). Ruff and pyright strict clean; full suite
green.** Slice 39f's real remaining scope turned out smaller than the plan's
original text once the code was actually read: `archive_file_history` already
existed (39b), and `_process_history`/`_plan_history` already ran as their own
catalog-driven pass over `~/.claude/history.jsonl` (39c/39d) rather than
extending `_walk_source`. What was actually missing was one config key and one
new corpus-wide check.

**Config: `archive_history_prompts: bool = True`** in `config.py`, read with the
exact same `_bool(merged.get(...), True)` shape `archive_subagents`/
`archive_tool_results`/`archive_file_history` already use. Wired with a single
added condition to each of `_process_history`'s and `_plan_history`'s existing
early-return chains in `sweep.py`, so the snapshot, the prompts split AND the
paste-cache gather all turn off together with the one switch (they already came
from the same read, so there was never a reason to gate them separately).

**Naming note, recorded rather than resolved:** the key is named for the plan's
original scope ("prompts"), even though the pass it now gates also does 39c's
whole-file snapshot and 39e's paste-cache gather. Kept as-is rather than
renamed, since the name is a locked planning artifact from an operator-approved
document, not something this slice had authority to change unilaterally.

**Doctor/status: `status.PasteGap`/`paste_gap`/`paste_line`, new in `status.py`,
mirroring `SidecarGap`/`sidecar_gap`/`sidecar_line` exactly.** Walks
`archive.walk_folders` once, reads each session's `manifest.json`, and reports
two corpus-wide figures: how many archived sessions have `prompts.jsonl`
present, and how many reference at least one paste. Never hashes, never opens a
transcript payload (F5/R6) - one small JSON read per session folder. Wired into
`ccw status` (one more line) and `ccw doctor` (one more non-blocking `Check`,
same posture as `sidecars`/`history`).

**Deliberately deferred, not built:** a persistent per-session notice file plus
a desktop alert for paste-cache anomalies, mirroring what `sidecars.json`/
`notify.alert` already do for tool-results/workflows/file-history. That
mechanism is keyed on `_archive_sidecars`'s per-transcript loop; `_process_history`
is a structurally separate whole-file pass with no access to it. Unifying the
two passes is a bigger architecture change than this slice's scope; the
transient per-run sweep-report visibility (`"pastes-refused"`/`"pastes-missing"`
outcomes, added the same day as 39e) is real visibility in the meantime.

**Verified against the real archive, read-only.** Ran the new functions directly
against the real 28,924-session `~/cc-warehouse-archive`: `paste_gap` reports
0/28924 sessions have `prompts.jsonl` yet, and the doctor check reports the same
figure with `blocking=False`. Zero is the correct answer, not a bug - the live
back-fill (39g) has not run yet, and the installed frozen `ccw` (0.1.3) predates
39c-39e entirely.

Full account: `harness/tickets/39-archive-what-a-session-points-at.md`'s `39f
DONE` block. Next: 39g, the final slice (version bump, frozen reinstall, one
live back-fill, CHANGELOG, real-data acceptance script).

### Thirty-third handoff, 2026-09-08 (ticket 39: refusal-visibility gap across 39b and 39e)

**Test count 1,506 -> 1,508. Ruff and pyright strict clean; full suite green.** Two
independent red-team reviews of 39b/39e (commits `abba0b5`..`f771874`) converged on the
same real gap: a "refused" write (R5's same-name-different-bytes collision) inside
`sweep._gather_external` (file-history/todos, 39b) and `sweep._gather_pastes` (pastes,
39e) reached `logs/capture.jsonl` via `capture.log_sidecar_trouble` and then went
nowhere else - never an `ItemOutcome` in the sweep report, and for `_gather_external`
specifically never the persistent per-session `sidecars.json` notice a `tool-results`/
`workflows` refusal already reaches. Pre-existing in 39b, inherited by 39e, not a new
defect either slice introduced. One reviewer planted a real collision and watched a
sweep produce zero visible outcome for it while the audit log quietly recorded a
"refused" line.

**Fixed both halves without merging the two sweep passes.** `_gather_external`
(per-transcript) and `_gather_pastes` (whole-`history.jsonl`, once per sweep) run on
different keys, and merging them would have been a much bigger restructure than this
gap warrants. `_gather_external` now returns `(written, refused: list[str])` instead of
a bare `int`, prefixed like `_archive_sidecars`'s own companion-dir refusals
(`"file-history/<name>"`, `"todos/<name>"`); its one caller folds that list into the
SAME `refused` list that already feeds the `"refused-sidecar"` outcome and
`write_sidecar_notice`. `_gather_pastes` now returns `(written, missing, refused: int)`;
`_process_history` appends a separate `"pastes-refused"` outcome (`"N paste(s)
refused"`) whenever `refused > 0`, in addition to whatever `"archived-pastes"`/
`"pastes-missing"` outcome the same session's written/missing counts already produce -
not added to `SIDECAR_ARCHIVED_ACTIONS` and not counted as a batch failure, matching
`"refused-sidecar"`'s existing non-fatal posture.

**Added the missing test coverage the reviews flagged**: nothing in the suite had ever
triggered `_gather_pastes`'s refusal branch, so a paste-collision test went into
`tests/test_history_sweep.py`, plus a file-history refusal-visibility test in
`tests/test_external_capture.py`. Both assert the archived copy keeps its original
bytes (R5), the new outcome appears, and a `"refused"` line lands in
`logs/capture.jsonl`.

**Also corrected, doc-only:** the `0dac5b7` commit message said "six existing call
sites" updated for `log_sidecar_trouble`'s widened signature; the diff actually touched
eight. No code change for that - just a one-line correction in
`harness/tickets/39-archive-what-a-session-points-at.md`'s 39e section, since this
repo's convention is a new commit rather than amending a pushed one.

Full account: that ticket file's "39e refusal-visibility follow-up, same round" block.

### Thirty-second handoff, 2026-09-08 (ticket 39 slice 39e: the paste-cache gather)

**Test count 1,469 -> 1,506 (37 new tests). Ruff and pyright strict clean; full suite
green.** Slice 39e: copy each session's referenced `paste-cache/<hash>.txt` files into
its own `pastes/` folder.

**Reused the companion machinery wholesale rather than inventing a fifth mechanism.**
Unlike 39d's `prompts.jsonl` (exactly one file per session, needed its own manifest
shape), `pastes/` holds zero or more files - exactly what `tool-results/`,
`workflows/`, `file-history/` and `todos/` already are. Adding `PASTES_DIR` to
`COMPANION_MANIFEST_KEYS` and `_COMPANION_NOUNS` was the whole change on that side:
`folder_is_current`, `_with_companions`, `_companion_problems`, `verify_folder` and
`companion_records` all already iterate those two dicts generically, so none of them
needed touching. Confirmed by reading each one before writing anything, per the
assigning session's own explicit instruction not to duplicate what they already do.

**`archive.paste_hashes_by_session` is a deliberate SECOND pass over `history.jsonl`,
not a widening of `split_history_by_session`.** That function shipped in 39d and was
independently red-teamed by four reviewers the same day; reopening its return shape to
also carry paste-hash groupings would have cost some of that verification for a saving
real measurement shows is negligible (the whole 6.6 MB file parses in well under a
second either way). Only the EXTERNALISED `pastedContents` shape
(`{"id":..,"type":"text","contentHash": <hash>}`) contributes a hash; the INLINED shape
already has its text in `history.jsonl`, so it needs no lookup at all. A hash two
different sessions both referenced lands under BOTH their `pastes/` folders - the
ticket's own explicit requirement, tested directly.

**`capture.log_sidecar_trouble` was narrowed from a full `parser.ParsedSession`
parameter to the bare `session_uuid: str | None` it actually used.** The new
paste-gather loop inside `_process_history` only ever has a bare uuid from a
`history.jsonl` row, never a parsed transcript - there is nothing to construct a real
`ParsedSession` from. Six existing call sites (`capture.py`, `sweep.py`) were updated
to pass `parsed.session_uuid` instead of `parsed`; behavior is unchanged since the
function only ever read that one field.

**Verified against the real machine, real `~/.claude` untouched throughout, writes
confined to a scratch `archive_root` removed afterward:**

```
history.jsonl:                        18,381 lines, 6,609,695 bytes
sessions with >=1 referenced hash:    742
distinct referenced content hashes:   2,186
present in paste-cache:               1,914
missing from paste-cache:             272
```

These numbers match the ticket's own original census exactly. Built one real session
folder in the scratch archive, called `sweep._gather_pastes` with one real present hash
and one real missing hash: wrote exactly the present one (byte-identical, sha256
matched the source), counted the missing one without raising, and re-reading the real
paste-cache source afterward confirmed nothing under `~/.claude` moved.

**The honest limit: a paste-cache source already missing is unrecoverable, and this
slice does not pretend otherwise.** 272 of 2,186 referenced hashes were already gone
before this code ran - not even the 39c whole-file snapshot ever held the actual pasted
text, only the reference to it. `"pastes-missing"` makes that loss visible and counted;
it cannot undo it.

Full account: `harness/tickets/39-archive-what-a-session-points-at.md`'s `39e DONE`
block. Next: 39f (doctor/status/alert wiring, config keys).

### Thirty-first handoff, 2026-09-08 (ticket 39 slice 39d: the per-session prompts split)

**One commit, oracle tests red before green.** Slice 39d: `history.jsonl`'s rows split
per session into each archived folder's own `prompts.jsonl`. Test count 1,437 -> 1,465;
ruff and pyright strict clean.

**The real change is a consolidation, not just a new file.** 39e (paste-cache) needs the
same parsed rows 39d groups, and re-parsing an 18k-line file a second time per sweep
would defeat the "scan once, join second" principle this whole ticket leans on. So 39c's
`sweep._snapshot_history`/`_plan_history_snapshot` were RENAMED to `_process_history`/
`_plan_history` and now do both jobs - the whole-file snapshot and the per-session split
- from one read. `archive.write_history_snapshot`/`history_snapshot_path` themselves are
untouched.

**New in `archive.py`:** `split_history_by_session` (raw-line grouping by `sessionId`,
never re-serialized), `write_prompts` (fixed-name `prompts.jsonl`, `write_if_changed`
since a later extraction fix must be allowed to rewrite it - unlike the content-addressed
snapshot, which never is), and `prompts_record` (a NEW manifest shape,
`{present, sha256, bytes, lines}`, because a single per-session file cannot reuse
`COMPANION_MANIFEST_KEYS`'s list-of-records shape built for directories). Wired into
`_with_prompts` (manifest write), `folder_is_current` (a `prompts.jsonl` arriving OR
disappearing after the last render both force a rebuild), and `_prompts_problems`
(verify - same "never start a problem string with `missing `" rule the sidecar checks
already follow, for the same `doctor._desync` pending-render carve-out).

**`SIDECAR_ARCHIVED_ACTIONS` gained `"archived-prompts"`, proved load-bearing by
deliberately breaking it**: removed the entry, watched
`test_a_sweep_added_prompts_file_is_reflected_in_the_manifest_the_same_run` go red
(the manifest stayed at `{"present": false}` after a sweep that DID write the file),
put it back, watched it go green again. Without it, a session already rendered before
its `prompts.jsonl` arrives would need a SECOND sweep to pick it up.
`"archived-history-snapshot"` stays out of that set, unchanged from 39c - it never
touches a session folder, so there is nothing for the post-sweep build to catch up on.

**No stranded-prompts bucket, on purpose.** A `sessionId` in `history.jsonl` with no
matching archived folder (~14% by the ticket's own measurement) is silently skipped.
39c's whole-file snapshot is the backstop for exactly that case; splitting is allowed
to be wrong or incomplete because the snapshot beside it never is.

**Verified against the real source tree, nothing live touched.** Called
`split_history_by_session` directly on the real `~/.claude/history.jsonl`
(6,602,393 bytes, 18,358 lines): **1,649 distinct sessionIds, 18,358 lines grouped, 0
skipped** - every line found a home. Spot-checked one real session's grouped lines
against the source and confirmed each is an exact substring, not a re-encoding. Built
one real session folder in a scratch `archive_root` (removed afterward) with that
session's real grouped bytes and walked the whole chain by hand:
`write_prompts` -> `prompts_record` -> `folder_is_current` (False before a rebuild,
True after) -> `verify_folder` (0 problems). The real `history.jsonl`'s line and byte
counts were unchanged afterward; the live archive was never opened for writing at any
point in this verification.

Full account: `harness/tickets/39-archive-what-a-session-points-at.md`'s `39d DONE`
block. Next: 39e (paste-cache), which the ticket file itself now notes will still need
to parse each grouped line once for its `pastedContents` field - the reuse 39d buys is
the single read-and-group pass, not a pre-parsed row structure.

### Thirtieth handoff, 2026-09-08 (ticket 39 slice 39c: the `history.jsonl` snapshot)

**One commit, oracle tests first.** Slice 39c: a whole-file, content-addressed snapshot
of `~/.claude/history.jsonl` plus a non-blocking `ccw doctor` line saying whether the
live file is currently protected. Test count 1,418 -> 1,437; ruff and pyright strict
clean.

**Why ONE pass rather than per-session, unlike 39b.** `file-history/` and `todos/` (39b)
are keyed by session id, so the hook and the sweep both gather them per transcript.
`history.jsonl` is a single file shared by every session on the machine - there is
nothing to key a per-item pass on, so this ships as one whole-machine pass inside
`ccw sweep` (`sweep._snapshot_history`), not a hook change at all. New:
`archive.write_history_snapshot`/`archive.history_snapshot_path` (mirrors
`write_not_a_session`'s exists()-only shape, since the filename IS the hash),
`sweep._snapshot_history`/`_plan_history_snapshot`, and `doctor._history_staleness`
wired as a `"history"` Check right after the existing `"sidecars"` one, same
never-blocking posture (ticket 38 ruling (e)) so it cannot move the exit code
`ccw-freshness-check.py` escalates on.

**Verified against the real machine, live archive untouched.** Read the real
`~/.claude/history.jsonl` (6,599,428 bytes) and wrote its snapshot into a scratch
`archive_root` under the session scratchpad, deleted afterward: the snapshot is
byte-identical (sha256 `85a9077daf32...` both sides), a second write touches nothing
(same mtime), and the doctor line correctly flips from "not yet snapshotted" to
"snapshot up to date" once the write happens. The real `history.jsonl` was
byte-count-verified untouched afterward.

**Scope held to 39c only.** No `CHANGELOG.md`, no version bump, no `renderer_version`
bump - this slice writes nothing inside a session folder or its manifest, so none of the
39b version-mixing concerns apply here. 39d (the per-session `prompts.jsonl` split) is
next.

### Twenty-ninth handoff, 2026-09-08 (ticket 38 built end to end and released as 0.1.3, then ticket 39 slice 39b)

**One session, six slices, six commits, all pushed on green.** `2a041f4` (38a) ->
`cdda77a` (38b) -> `a7779e1` (38c) -> `f159de8` (38d) -> `b6439cb` (38e) -> `36940f0`
(38f). Oracle tests first in every slice, shown red for the right reason before the code
existed. Test count 1,269 -> 1,364; ruff and pyright strict clean at every commit; the
golden matrix anchor never moved.

**What the ticket was actually about, and it is not "tool-results was not archived".**
That is the symptom. The defect is that nothing in the product ever ENUMERATED what sits
beside a transcript: `capture.py` asked for `subagents/` BY NAME and ignored the rest of
the directory, so Claude Code could start writing a new sibling and the archive would
quietly stop being complete. It did, on 2026-05-08, and it took four months to notice.
`src/cc_warehouse/sidecars.py` is the fix: one leaf module holding the list of known
names, with `archive.COPIERS` fenced by two tests - a name without a copier fails the
suite, and so does a copier naming a function that does not exist.

**The sharpened lesson, written into `contract/HARNESS.md` section 8.** The standing
lesson says the same defect recurs across modules, so census the class. That could not
have caught this one: there was no wrong answer to census, because nothing had ever been
written about these folders at all. The general form is stronger. **When code consumes a
directory it does not own, enumerate what may be in it and fail on the rest, rather than
naming the one thing you want.** A grep finds code that exists; a fence finds code that
should.

**Three sub-agent bugs found while doing something else, all real, all fixed.** None
were in the ticket's title:
- `capture.py` located the sub-agent directory from the transcript's FILE STEM, so a
  `<uuid>.orphaned-<n>-<hash>.jsonl` transcript (one exists live) found none of its
  sidecars. Ruling (c) settles it: content uuid first, stem second.
- the hook's sub-agent glob was not recursive, so Workflow-tool sub-agents at
  `subagents/workflows/wf_<id>/agent-*.jsonl` (432 files, 33 MB, 211 transcripts) were
  reached only by the daily sweep's `os.walk`. A working net, but a net is not a plan.
- `sweep._archive_subagent` computed the project dir as a fixed three levels up, which is
  right for `subagents/agent-*.jsonl` and wrong for the nested ones, so 211 transcripts
  had a label derived from `wf_<id>`. The catalog lookup usually rescued it.

**Two bugs the oracle tests found in code that read as correct.** Worth recording
because in both cases the code looked obviously right:
- the sweep's third pass returned early when there was nothing to copy and no anomaly,
  which is exactly the state a session is in once its anomaly has been REMOVED - so
  `sidecars.json` went on claiming it forever. An early return that is right for the
  normal case and wrong for the recovery case.
- a refusal test on the hook path could not fire at all: capture is idempotent by hash
  (R14), so a second fire on unchanged bytes short-circuits before any archive write.
  The test was wrong, not the code, but only running it said so.

**The plan was followed, with three deviations and one correction, all recorded in the
ticket's DONE block rather than left to be rediscovered.** The correction is the one that
matters: ruling (d) treated every `<uuid>/` dir with no transcript beside it as homeless,
but "no transcript BESIDE this dir" is not "no transcript ANYWHERE" - four of the 39 real
ones have a session folder in the archive already, and filing those under `_not-sessions/`
would put a known session's data in the drawer for unknowns. The sweep builds a
`uuid -> folder` map now and files them where they belong.

**Ruling (e) in practice: the doctor line reports, the notification interrupts.** The new
`sidecars` line is non-blocking by design, so neither `ccw-watch` (greps `^\s*FAIL`) nor
`ccw-freshness-check.py` (reads the exit code) can ever see it. Both are pinned by tests
that run those tools' REAL sed and grep commands against a report carrying an anomaly.
The attention comes from `notify.alert`, fired only when a session's notice CHANGES to
non-empty, so a permanent anomaly is announced once and never again. This is the ticket
24.7 lesson being obeyed rather than re-learned.

**The release caught something the whole build had not, and it was not about
sidecars.** `v0.1.3` failed its first run on two tests that pass on macOS. Measured
before changing anything, because the obvious reading was that ticket 38 had broken
the archive verb: it had not. The capture hook renders in a DETACHED child, so
`ccw hook` returns before any projection exists (probed: 0 files the instant it
returned, 7 files five seconds later), and both tests snapshot immediately after
capturing. A pre-existing race that a fast laptop always wins, exposed because
capture got slightly slower. `conftest.settle_render` polls for the finished state
instead of sleeping.

**THE REAL FINDING IS THE GAP THAT LET IT REACH A RELEASE.** Until today the only
workflow in this repo fired on a `v*` tag, so the FIRST Linux run of any change was
its release run - the most expensive place to learn anything, because the version
number is chosen and the tag is pushed first. `.github/workflows/gates.yml` now
runs the same three gates on every push to master and every PR. It went green on
the runner BEFORE the tag was moved, which is what made moving it a decision rather
than a hope. The tag move itself was put to the operator, since that is the one git
operation this project gates; the failed run had published nothing, so no v0.1.3
artifact existed to supersede. PyPI now serves 0.1.3.

**THEN TICKET 39 SLICE 39b, in the same session.** `external.py` plus the gather for
`~/.claude/file-history/` and `todos/`, wired into the hook and the sweep. 929,845,225
bytes that exist nowhere else are now gatherable; the live back-fill is NOT run and
must wait for the release, because the installed frozen `ccw` is 0.1.3 and does not
write the two new manifest keys, so two versions would churn every folder's manifest.

**Measuring before building corrected the plan twice**, which is the standing lesson
"a ticket's finding list is evidence, not a specification" earning its keep again. The
plan expected about 5% of `file-history/` directories not to be bare session uuids;
today none of the 1,056 are. And it required catalog-driven discovery, which cannot
see either of the two cases its own risk table demands be reported (a non-uuid
directory, and 42 dirs whose session the archive never got) - iterating the catalog
only ever finds what it already knows about. The code scans and joins instead, which
keeps the F4 guarantee identically and is 30x cheaper. Recorded in DESIGN 15 rather
than left as a silent deviation.

**Watching for a second refusal found a defect in what had just shipped instead.**
There was no second refusal, but checking properly - with a control, 670 `ok` lines
matched and `refused` matched none - showed the SWEEP path wrote no audit-log line for
a refusal at all, while the hook path did. The ticket's own acceptance text had
claimed otherwise; it is corrected in place with the measurement. The notice says what
is true now for one session, the log says what happened and when across all of them,
and only the log can be counted afterwards.

**Ticket 39's remaining slices (39c-39g)** are the `history.jsonl` and `paste-cache/`
work, which 39b deliberately does not touch. `store.write_if_absent`,
`archive.copy_companion_dir`, `archive.write_sidecar_notice`, the doctor line and
`notify.alert` are all built for them to reuse.

### Twenty-eighth handoff, 2026-09-07 (a false green in doctor, a hook that was never 3.9-safe, and ticket 39 planned)

Same day as the twenty-seventh, continuing from it. Five things shipped and one plan
landed.

**`ccw doctor` reported a hook ok for a plugin root that does not exist (`03f7921`).**
Found by the `fifty-shades-of-dotfiles` session red-teaming its OWN watcher and handing
the observation over; proved here by execution before being accepted. `_mentions_ccw`
had two paths and only the second touched the filesystem: the first returned True as soon
as the command STRING contained "ccw", and our own registration is
`python3 ${CLAUDE_PLUGIN_ROOT}/hooks/ccw-hook.py`, where "ccw" is in the FILENAME. So the
string path fired and returned before the `is_file()` check was ever reached, and the
`hook` line stayed green for a deleted plugin cache. The fix is narrow on purpose: a
command that NAMES a script must have that script present, checked before the string
match, which leaves a bare `ccw hook` (no path, resolved from PATH) still accepted. That
legitimate case is pinned by its own control test, because requiring a file
unconditionally was the first instinct and would have broken it.

**`ccw-hook.py` was never 3.9-safe, and `83b7e73` had claimed both hooks were
(`68d5fa7`).** That commit tested `ccw-freshness-check.py`, which uses `timezone.utc`,
and generalised to `ccw-hook.py`, which imported `UTC` from datetime. That name is 3.11+
and an ordinary import of a too-new NAME is not deferred by a `from __future__ import
annotations` line, so the CAPTURE hook still died at import under 3.9 while passing every
static fence in the suite. Generalising a shape from one sample is already a standing
lesson in this file's own section 8, and it still happened one commit after a related one
was written. The test that catches it now EXECUTES both hooks under the oldest python3 on
the box rather than reasoning about which syntax is safe; it skips where no old
interpreter exists, so it is a net and not a proof, and the static fences stay.

**Both hooks now record which interpreter ran them**, in their own log record
(`"python": "3.14.7 /opt/homebrew/opt/python@3.14/bin/python3.14"`). Suggested by the
same peer session on the argument that removing a failure class and leaving no trace of
what happened are two separate decisions and only the first had been made. Adding it is
what exposed that the class was not actually removed. Measured while doing it: `zsh -lc`
on this machine already resolves `/usr/bin/python3` 3.9.6, which is what a launchd job
gets, and uv ships only version-suffixed shims with no bare `python3`, so the
deliberately chosen interpreter is the one the name cannot reach.

**The `my-claude-code-transcripts` DO-NOT-DELETE rule is discharged (`4f8c528`).** The
principal deleted the tree and confirmed it directly. The bullet stood as a live
prohibition for a path that no longer exists, which is the exact shape that misleads the
next session. Rewritten as a CLOSED record with the whole measurement history kept, plus
a WHAT WAS NEVER MEASURED paragraph (the sweep predates the deletion, so it proves
absorption as of 2026-08-21, not that nothing arrived after) and the bounding evidence
for that gap. "A satisfied gate is not consent" was kept and strengthened rather than
retired with the gate.

**Path-as-identity named as a lesson about the analyst (`7d2e348`, `89626e1`).** Third
occurrence; the first two were recorded as instances and neither prevented the third.
Today's was a script written to answer whether it is safe to DELETE 23,844 sessions,
which matched by FILENAME and reported 2,228 with no archive copy; re-resolved by sha256,
all 2,228 were present under other names and genuinely absent was 0. The general form is
now written down, along with the half that makes it fire in this repo: A GREEN CONTROL
DOES NOT VALIDATE THE KEY. `census` proves the instrument fired and the population was
non-empty; it says nothing about whether the thing it fired on was keyed correctly.

**Ticket 39 planned and approved, not started.** See
`harness/tickets/39-archive-what-a-session-points-at.md`. The archive keeps what a session
SAID and not what it POINTED AT. Blocked on ticket 38. Two operator rulings recorded in
the ticket. Three of the planning session's own findings were grep artifacts and are
corrected in the ticket rather than quietly dropped: repo hits for `file-history` are the
inline block type in `parser.py`, hits for `todos` are `render.py::_render_todos`, and
transcript hits for `paste-cache` are prose in sessions that were investigating
`.claude`. The directories are genuinely unhandled; the reasoning for saying so was wrong
each time, and a red-team agent caught the third one.

**Still open and untouched:** the external archive backup is roughly 62,000 files behind
(116,433 verified 2026-08-04 against 178,160 today), and no drive carrying it was mounted
for most of this session. That is unchanged from the twenty-seventh handoff and is the
only item here with a real downside if left.

---

### Twenty-seventh handoff, 2026-09-07 (a spoken false alarm traced to the watcher, not to ccw)

**The report.** The operator heard an error spoken at session start saying cc-warehouse capture had
failed, and asked what the logs said. They were right to doubt it: capture was working perfectly the
whole time.

**What the logs actually said.** `~/.claude/logs/ccw-hook.log` held exactly two error lines, at
02:55:10Z and 02:56:35Z, both `TimeoutExpired` after 15 seconds. Every `ccw-hook` line around them
said `ok`, the most recent capture having taken 24ms. Run by hand, `ccw doctor` returned all 8
checks green in 2.75s (frozen install) and 1.92s (venv copy), 3.39s each under 4x concurrency. No
lock was held, no ccw process was running, and all three launchd jobs reported `last exit code = 0`.

**Why it was slow, measured rather than assumed.** `ccw doctor` walks `~/.claude/projects` to count
uncaptured sessions: 27,277 files, 4.2 GB. Between 12:30 and 12:45 local, `ccw-sweep` wrote 486
archive folders clearing an overnight backlog that had reached 453 uncaptured sessions, and 30
session transcripts were being appended between 12:45 and 13:00. Doctor lost that race twice. NOT
measured and stated as such: the exact CPU/IO state at 02:55:10, which macOS does not retain.

**The real defect, and it was in the alarm.** `ccw-freshness-check.py` had two failure paths treated
oppositely. A doctor that RAN and said FAIL incremented a streak and escalated politely, clearing
when fixed. A doctor that could not be ASKED hit an `except` branch that called `report("error")`
immediately, which is the only status `report()` says out loud, with the raw Python exception text,
on the FIRST occurrence. It also never touched the streak counter, so a permanently unreachable
doctor could never have escalated past that one flat line, and it `return 0`-ed early, silently
skipping `broken_jobs()`, so the launchd job watch stopped running at exactly the moment
things looked worst.
Three defects, one branch. The file argued against itself: `broken_jobs()`'s own docstring, three
functions further down, says "absence of evidence is not evidence of failure here".

**Fixed, oracle tests first.** A `TimeoutExpired`/`OSError` now sets an `unreachable` string and
falls through to the same streak path a failed verdict uses, with its own wording that says the
check got no answer rather than claiming capture failed. Full detail is still logged, at a status
`report()` does not speak. `_DOCTOR_TIMEOUT = 45` replaces the inline 15.

**A review of that fix found a worse bug in it, and this is the part worth reading.** The four
`/simplify` agents were pointed at the diff; the altitude agent found that `hooks/hooks.json`
declares `"timeout": 20` for SessionStart, so Claude Code kills the whole hook process at 20s. An
inner budget of 45s could therefore never fire on its own terms: the hard kill lands first, skipping
the graceful except branch, the log line, the streak write and `broken_jobs()`. That is the same
silent-early-exit shape the fix existed to close, reintroduced one layer up, and it was a regression
against the old 15s, which used to fire cleanly with 5s of slack. The sibling hook in the same
plugin already had this right (SessionEnd outer 45, `ccw-hook.py` inner 40). Verified from source
before accepting it. Closed by raising the outer budget to 55, naming `_JOB_TIMEOUT = 2` (all three
`launchctl print` calls together measure 0.03s, so 5s each was 166x the cost and now stacks on the
doctor budget), and pinning the relationship with
`test_the_freshness_hook_budgets_fit_inside_its_own_outer_kill`: 45 + 3*2 = 51s under a 55s kill,
4s margin. The two files cannot see each other, so only a test can hold them together.

**Also from that review:** the copy-pasted `_WARN_AT`/`_ALERT_AT` ladder in `freshness_message` was
collapsed into one `_tier()` helper, and the identical urlopen stub that had grown independently in
both hook test files was hoisted to `conftest.py` as `UrlopenStub`.

**Gates:** ruff clean, pyright 0 errors (strict), 1,234 tests pass. Live: the real hook against the
real `ccw doctor` exits 0 in 1.89s logging `status: ok`, silent; a sandboxed-HOME run with an
unreadable binary proves the new path end to end (status `unreachable` logged with full detail,
status `warn` with the plain-English message, `consecutive_broken` reaching 1, nothing spoken).

**Two things found and NOT fixed, both reported to the operator rather than acted on.**
(1) `/usr/bin/python3` on this Mac is 3.9.6 and this hook has needed 3.10+ since long before today.
Verified by running the COMMITTED copy from HEAD under it: identical `TypeError` on PEP 604 syntax.
Pre-existing, out of this session's scope, and harmless in practice only because Claude Code's hook
environment resolves a newer python3.
(2) `ccw-watch` (the sticky RED banner, in `fifty-shades-of-dotfiles`, not this repo) has its own
20s budget, and it reads `CCW_WATCH_DOCTOR_TIMEOUT` from the environment, so it can be given the
same headroom without editing that repo at all. Not set; the operator's call.

**What is NOT done:** the fix is in this repo but NOT yet in what runs. The live plugin is a cached
copy at `~/.claude/plugins/cache/cc-warehouse/cc-capture/<sha>`, built from a git clone of the
GitHub remote. The operator must run a `/plugin` update after this is pushed, exactly as the
twenty-second handoff's "hook started line waits on /plugin update" note records for the same
reason.

---

### Twenty-fifth handoff, 2026-09-06 (cross-machine audit; ccw provisioning design with fifty-shades-of-dotfiles; agent-setup-contract.md added)

Ran concurrently with the twenty-fourth handoff's session, same day, different track: this
one started from the operator asking to understand `ccstats`/`cc-capture` at a high level,
then to audit this Mac's hook/launchd wiring plus a second machine reachable over SSH
(`mlbox-ubuntu`, alias for a WSL Ubuntu box, hostname `MLBox`).

**This Mac: clean.** Hooks correctly wired (`cc-capture@cc-warehouse` enabled, plugin
files byte-identical to the repo), all four `launchd` jobs loaded with last exit status 0,
`ccw doctor` fully green.

**MLBox: a genuine second, independent `ccw` install, not a backup of this Mac's
archive** - real data (one project, 14 objects). Found stale three ways (`ccw` 0.1.1 vs
0.1.2 here, no config file at all so no `archive_root` ever configured, plugin clone
pinned a month back at the original 2026-08-10 install commit). Full detail, kept as
personal-path memory rather than in this public file:
`[[ccw-deployment-on-mlbox]]` (project memory). Everything found came from read-only SSH
commands; nothing on MLBox was changed.

**A peer Claude session in `fifty-shades-of-dotfiles` reached out unprompted** once this
account was relayed to it, and the two sessions traded several rounds of messages the same
day - each side re-verified the other's claims rather than trusting them (its
`claude plugin update` discovery and this session's MLBox settings.json read both got
independently confirmed, and one MLBox prediction from the other side turned out wrong and
was retracted on direct evidence). Outcome, operator-ruled on both sides and confirmed
matching: the dotfiles installer owns every deterministic step of `ccw`'s lifecycle
(install if missing, keep current, register a fresh plugin, scaffold a baseline config,
triggered by whether a config file exists at all - not `ccw doctor`'s exit code, since
doctor correctly treats a missing `archive_root` as healthy by design, which is exactly
why MLBox went a month unnoticed). A new file, `docs/agent-setup-contract.md`, written FOR
an AI agent to read cold, covers only what the installer can't safely automate: where
`archive_root` should point, approving a plugin update's `-y` flag (it accepts whatever
command the marketplace declares AT UPDATE TIME, not just "yes" to the update itself), and
Linux/systemd scheduled jobs (untested by this project - macOS `launchd` only). Also filed:
`contract/PROPOSALS/doctor-json-config-fields.md`, a forward-looking requirement that a
future `ccw doctor --json` expose config-presence and archive_root-set as their own
fields rather than folded into one verdict.

**OPEN, not resolved this session:** the dotfiles session flagged, after the doc was
already written and pushed, that its wording ("upgrade to the latest PyPI release on every
run") conflicts with a policy it says the operator ruled directly to it - pin + floor +
notify instead, to stop a bad release reaching every machine silently. Surfaced to the
operator; not yet corrected in the doc. See `[[cross-project-ccw-provisioning-with-dotfiles]]`
(project memory) for the full account.

**Resolved same session, minutes later:** operator confirmed directly - the real policy is
pin + floor + notify, not "upgrade to latest on every run." `docs/agent-setup-contract.md`
corrected to say the installer enforces a pinned floor and reports (never auto-installs)
when PyPI has something newer. Both sides now consistent.

**Also this session: `/wrap-up` itself reviewed and fixed, from having just run it.** Three
real gaps, all hit live rather than hypothesized. (1) Step 7's secrets scan checked only the
staged diff - but this repo's own standing cadence rule (`commit-push-tag-workflow` memory)
is commit-and-push-immediately, so staging is almost always empty by the time the step runs;
the scan was silently checking nothing and still reporting clean. Now scans this session's
own commits (diffed against a captured starting commit) as well as anything still staged.
(2) Step 1's touched-set relied on `@{u}..HEAD`, which reads empty the moment a concurrent
session (this machine runs several against the same checkout - exactly what happened this
session, see above) pushes first; now anchors on a captured `SESSION_START_REF` instead.
(3) Step 4 assumed every decision fits a ticket or `contract/DESIGN.md`; the cross-project
governance decision above fit neither, so the step now says explicitly that `HANDOFFS.md` is
a legitimate home too. Fixed in `4ef843a`'s follow-up commits; the operator separately asked
this session to check its own MEMORY for related keywords, which surfaced that
`commit-push-tag-workflow.md` already documented both halves of the tension (commit-
constantly, and no-personal-data) without ever connecting them - a dated note was added
there generalizing the lesson beyond just `/wrap-up`.

**Corrected minutes later again: the hand-rolled grep itself was the wrong fix.** The
operator asked whether `git-leak-scan --since <ref>` should be used instead. It should -
this machine already has a real leak scanner (`~/.local/bin/git-leak-scan`, personal
tooling, not part of this repo) built for exactly this case (its own header calls out
"end-of-stage audit" by name, because the same staging-is-always-empty problem was already
solved there), already wired into every commit here via the pre-commit hook
(`~/.config/git/hooks/_audit-chain`), and covering far more than username/path: GitHub/
Slack/AWS/OpenAI-shaped tokens, PEM private keys, phone numbers. Verified live: `git-leak-scan
--since 2f374c2` (this session's actual starting commit) ran clean over the whole session.
`/wrap-up`'s Step 7 now calls it directly, falling back to the narrower grep only if the tool
is absent. Memory corrected to match rather than left pointing at the weaker fix.

**Further round, same day: a sibling project measured three real blind spots in ANY
diff-based leak scan, plus a session-anchor reliability question.** Independently
re-verified all three in a throwaway repo with real tokens before acting (one further
claim, a BLOCK exit-code discrepancy, could not be cleanly reproduced and was dropped -
the test repo's own history showed the triggering commit never actually existed, meaning
the test harness was broken, not the tool). Confirmed: commit/tag messages never appear
in any `git diff` (a real token in a commit message scanned exit 0; the same token in file
content correctly blocked); binary file content is invisible the same way; a value added
in one commit and removed in a later commit within the SAME range is invisible to a
two-dot diff even though `git log -p` shows it sitting in history already pushed - a real
risk given this project's own push-immediately habit, not theoretical. `/wrap-up` now runs
a supplementary `git log --format=%B <range> | gitleaks detect --pipe` pass for the first
gap, documents the other two as accepted limitations (a true full-history audit is
`/refresh`'s scope, not a per-session one), and treats a lost `SESSION_START_REF` as a
refuse condition rather than a silent best-guess fallback. The sibling project's own
session-anchor critique (a commit-trailer-based anchor going blind exactly when hooks are
skipped) does not directly apply here - this repo's anchor was already a captured starting
`HEAD` with no trailer dependency - but the underlying principle (refuse rather than guess)
was worth applying anyway. Full account, consolidated out of `commit-push-tag-workflow`
memory into its own file since it had grown too large embedded there:
`[[git-leak-scan-known-limits]]` (project memory).

**Final round, same evening: git-leak-scan fixed the add-then-remove gap upstream, and a
real overdue delivery surfaced.** The sibling project shipped a per-commit (`git log -p`)
audit mode closing limit 3 above for the common case (both commits inside one range) -
re-verified live with the same failing reproduction, now correctly blocks. Their message
also revealed this project had been sitting on a promise: `docs/reference-config.toml`
(every config key, commented with its default) was recommended weeks earlier as this
project's value-add for cross-machine provisioning and never actually built - the sibling
project was genuinely blocked on it. Built and shipped same session (`ad2375d`);
`agent-setup-contract.md` now points at it instead of expecting an AI agent to reconstruct
the config schema from memory each time. `git-leak-scan-known-limits.md` also gained the
tool's current authoritative state (commit `26c3551`, six changes, `--control` mode for
proving the scanner itself hasn't silently regressed) and two standing verification rules
worth carrying beyond this one tool.

No ticket file touched, no `pyproject.toml` version bump (docs-only this track) - this
session's own `/wrap-up` run found the guards already green (1222 passed, 0 ruff/pyright
issues) and the release tag already correctly pushed by the concurrent twenty-fourth
handoff session.

### Twenty-sixth handoff, 2026-09-06 (/refresh run, full sweep - a real privacy leak found and fixed)

Ran the full `/refresh` sweep (not a scoped mode) at the operator's request, prompted by a
housekeeping task relayed from a sibling project ("audit CLAUDE.md for stale rulings").
Recognized that request maps directly onto this repo's own existing `/refresh` command
rather than doing a lighter, duplicate ad-hoc audit.

**Real finding, fixed same session: the actual local username had leaked into two tracked,
public files** - `harness/HANDOFFS.md` (twice) and `tools/ccstats/review.py` (once) - a
hard-rule violation caught by `/refresh`'s own personal-data probe. Redacted using this
project's existing `<local-username>` convention, narrative content preserved.

Other real fixes: one dangling memory wiki-link (`[[opening-prompt-restructure-2026-08-27]]`,
never existed under that name - repointed to the real file,
`[[opening-prompt-is-an-index-not-a-log]]`, which covers the same event); README's Commands
table was missing `ccw repair` (a real, working verb since ticket 32) - added. `mcp`/`search`
were checked and are already correctly marked planned elsewhere in README, not a table
drift.

**Flagged, not auto-fixed (genuine judgment calls, per Guardrail 7):**
- Tag parity: 15 DONE-annotated items (slice-18 through slice-31, slice-37) carry no
  milestone tag. Expected under the documented DIRECT-BUILD era exception (post-v1 tickets
  don't necessarily follow the old slice-tag pattern) - report-tier, not a defect.
- Ticket-to-test wiring: 6 tickets cite test files that don't exist under those names
  (likely renamed when an implementation split into multiple files, e.g. ticket 19's
  original `tests/test_archive.py` citation vs the real `test_archive_*.py` files that
  exist); 25 real test files are cited by no ticket at all. Real drift, but sizable enough
  (31 items) that fixing it needs the operator's own triage, not a same-session guess.
- CHANGELOG's milestone table is missing 17 more recent tags (27.1-27.7, 29-mechanism-1,
  31.2-31.5, several `ticket-NN` tags). Possibly intentional given the table's own framing
  favors early illustrative tags over an exhaustive ledger - flagged rather than assumed.
- `contract/PROPOSALS/*.md`'s em-dashes: both files are explicitly preserved "as filed"
  per this project's own convention (one says so outright) - left untouched per Guardrail
  3, reported rather than silently cleaned.

**Verified false positives, not fixed:** CLAUDE.md's "STILL OPEN inside 24: 24.7" line
(dated historical narration immediately followed by its own correction two sentences
later - the probe can't see the correction, a human/careful read can); a `.claude/`
hygiene grep hit on `wrap-up.md` (`sk-` matched inside "ta**sk-**independent", not a key).

Gates re-verified unchanged after all edits (1222 passed, ruff/pyright clean). Three
commits, all pushed (`5656d80`, `3a27235`, plus the memory-only dangling-link fix which
lives outside the repo per this project's own memory/repo separation).

**Same evening, second relay: audit all five slash commands for the same shape of
staleness.** Checked all five (`architecture`, `dashboard`, `daywall`, `refresh`,
`wrap-up`) against five failure shapes a sibling project found in its own audit
(destroying a recovery path before confirmation, recommending a deprecated tool, a step
gone stale within the same session, an untracked command invisible to `git log`, and
dated stamps vs drifting counts) - verified by grep, not assumed. Four of five shapes
didn't apply anywhere in this repo's commands. The fifth did, in `/wrap-up` itself:
`git-leak-scan` grew a `--control` self-test (proves the scanner still detects real
patterns today, independent of whether this session's own range is clean) after Step 7
was last edited earlier the same day. `/wrap-up` now runs `--control` immediately before
the real scan and requires both results quoted verbatim in the report - the same
"prove the instrument, not just the reading" principle this whole session kept
rediscovering, now written into the command itself rather than left as something to
remember each time.

### Twenty-fourth handoff, 2026-09-06 (0.1.2 shipped; a real cross-platform test bug found and fixed; /wrap-up added)

Started from an operator question - "can PyPI auto-update from GitHub?" - answered by reading
`.github/workflows/release.yml`: the automation already existed (tag-triggered, PyPI Trusted
Publishing, no stored token) but had never fired since 0.1.1 (2026-08-09), because nobody had
pushed a `v0.1.2` tag despite `pyproject.toml` already reading 0.1.2 and `CHANGELOG.md` already
carrying that version's entry. Pushed it - which surfaced three real, previously-invisible
problems, each fixed the same session.

**1. 15 pyright-strict errors in `tests/test_render_open.py`.** `monkeypatch.setattr(notify,
"open_page", lambda path: ...)` - pyright can't propagate `open_page`'s `path: str` annotation
through a bare lambda passed to `setattr`. Fixed by replacing each lambda with a small named
function carrying the annotation directly; behaviour unchanged, 8 tests still pass.

**2. 22 tests failed ONLY on GitHub's `ubuntu-latest` runner**, never on macOS or in a locally
built Linux container (root, non-root+git, both tried and both green). Root-caused by reproducing
the exact CI condition locally rather than guessing: `config.py`'s `load_config()` checks
`XDG_CONFIG_HOME` before falling back to `$HOME/.config`. 23 test files write a sandboxed
`config.toml` under `$HOME/.config` and set `env["XDG_CONFIG_HOME"]` to match it - but only on a
plain dict used for `run_ccw`'s subprocess calls, never via `monkeypatch.setenv` on the real
process environment `run_cli`'s in-process calls actually read. On any machine where
`XDG_CONFIG_HOME` happens to already be unset (every machine tried until GitHub's runner), the
code's own fallback silently produces the same path anyway, hiding the bug for weeks - this
repo's tests hadn't run on GitHub since 2026-08-10 (see finding 3), so nobody had seen it fail.
One line in `tests/conftest.py`'s shared `ccw_env` fixture (`monkeypatch.delenv("XDG_CONFIG_HOME",
raising=False)`) fixes all 23 files at once, since every one of them computes the exact same
`$HOME/.config` value the fallback already produces. Verified by reproducing the CI condition
locally (`XDG_CONFIG_HOME=/tmp/x uv run pytest`): fails the same way without the fix, all 1222
pass with it.

**3. PyPI's GitHub Trusted Publisher link was broken since 2026-08-10**, the day the repo was
deleted and recreated for the go-public audit (ticket 28.20) - PyPI ties the link to GitHub's
internal repo ID, not the repo name, so the recreation silently orphaned it. Publish failed with
`invalid-publisher`. By the time it was checked, PyPI showed "No publishers are currently
configured" (not a stale entry - genuinely gone). Fixed by hand on pypi.org (walked the operator
through it live): re-added Owner `CaptainCodeAU`, Repository `cc-warehouse`, Workflow
`release.yml`, Environment `pypi`. `v0.1.2` published successfully afterward - confirmed against
PyPI's own JSON API, not just the green Actions checkmark.

**Standing rule added**: `commit-push-tag-workflow` memory now says push a matching `vX.Y.Z` tag
automatically whenever `pyproject.toml`'s version bumps, no asking each time (operator's explicit
authorization, given specifically because of finding 3's silent multi-week gap). A new memory,
`pypi-trusted-publisher-recovery`, records the fix for if a GitHub repo delete/recreate ever
breaks this link again.

**`/wrap-up` added** (`.claude/commands/wrap-up.md`), adapted from a much larger VM-infrastructure
version in a different project - kept the shape (derive the touched set from git alone, run the
guards fresh, three-state report vocabulary) and replaced the box/host-specific steps with this
project's own real gap: a version bump with no pushed release tag, which is exactly how finding 3
sat invisible for three weeks. First real run of it is this same session.

### Twenty-third handoff, 2026-09-06 (planning session, no code)

Started from two screenshots and two questions: why the archive folder for chorustic session
`78bb0bd1` has no `tool-results/` when the source folder does, and why only some sessions
have a `<uuid>/` folder at all. Answers: the product has never referenced `tool-results`
(census over 26 `src/` files, control hit, 0 matches), and Claude Code creates `<uuid>/` only
when it has a sidecar to put there (sub-agents, or a tool output too big to inline).

**Measured before designing.** 1,196 real sidecar dirs; child names are exactly
`tool-results/` (1,067), `subagents/` (481), `workflows/` (9), `.DS_Store`. `tool-results/`
holds 2,084 files, 135.7 MB; a byte check against every JSONL shows **65.4 MB exists in no
JSONL** (every hook-stdout file, half the overflow files, all pdf pages), because
`toolUseResult.stdout` is itself capped. First appeared 2026-05-08. Also found: the hook's
non-recursive glob misses `subagents/workflows/wf_*/agent-*.jsonl` (432 files, 33 MB; the
sweep's recursive walk has all 211 transcripts in the archive), 20 forked-skill files inside
`subagents/` copied by nothing, `<uuid>/workflows/` copied by nothing, and 35 sidecar dirs with
no transcript anywhere. Session id inside the transcript matched the dir name 450 of 450.

**Plan written, red-teamed, approved:** saved as
`harness/tickets/38-sidecars-tool-results-and-unknown-siblings.md` (`Plans/` is gitignored). Two Plan
agents (mechanism; red-team plus anomaly signal) and three Explore agents; every load-bearing
claim re-checked in source, two corrected (the layout tests will NOT break because the
session writer never creates sidecar dirs; the anomaly record must be a notice file, not a
manifest key, because the manifest is re-rendered later by a process that cannot see the
source dir and ~617 hidden sessions have none). Operator rulings taken in-session: copy the
stranded dirs under `_not-sessions/stranded-sidecars/`; doctor line informational plus a
desktop/voice alert fired once per new anomaly; all three sidecars in ticket 38. Ruling (c)
(sidecar identity from the transcript beside it) still needs its DESIGN 15 entry.

**Also closed:** the ticket 37 Part B row 1 check from handoff 22. The plugin update landed;
the newest cache copy contains `_started` and `ccw-hook.log` shows `started` lines.

Nothing in `src/`, `tests/` or `contract/` was changed. Next session: build 38a-38f.

### Twenty-second handoff, 2026-09-06 (new session)

Started from a plain question: why did one chorustic session's rendered files land nine
minutes after its JSONL, and why did its `subagents/` folders carry a date in between.
Traced through file mtimes, `capture_event`, the hook log and source. Answer: the SessionEnd
hook wrote the raw JSONL and sub-agent files, then died before the catalog row and every log;
the 12:30 daily sweep recovered it two minutes later and rendered after its full walk (ticket
34's known shape). The in-between date was the sweep rewriting every sub-agent `meta.json`.

**Ticket 37 opened and Part A closed the same day** (`harness/tickets/37-*.md`, commits
`fb08ea0`, `81784d3`, `52319d7`, `9d70689`, tag `ticket-37-part-a`). Measured: one daily
sweep rewrote 2,501 of 2,505 archive `meta.json` files because `write_subagent` wrote the
meta unconditionally and sub-agents never enter the hash pre-filter. Fixed with
`store.write_if_changed`, now the one shared compare-before-write primitive (the projection
writer, the project sidecar, the meta and the orphan note all use it); the sweep reports
`skipped_unchanged` and `refused-subagent` instead of a blanket success. Real-data
acceptance: a full `ccw sweep` over 26,708 items wrote 0 files under any `subagents/`.
Frozen `ccw` reinstalled and verified with `ccw doctor` from outside the repo.

**Part B row 1 shipped but is NOT LIVE.** `ccw-hook.py` writes a `started` line and puts
`source` and `session` on every log line. Claude Code runs the copy in
`~/.claude/plugins/cache/cc-warehouse/cc-capture/<sha>/`, which still has the old script
until the operator runs `/plugin` and updates `cc-capture@cc-warehouse`. Verified: 0 cached
copies contain `_started`. **First thing next session: check whether that update happened**
(`grep -c _started ~/.claude/plugins/cache/cc-warehouse/cc-capture/*/hooks/ccw-hook.py`).

A `/simplify` four-angle review of the first commit found four real things, all fixed in
`52319d7`: a hand-rolled compare where `build.py` already had one, the orphan note two lines
below carrying the identical bug (the standing "census the class" lesson, missed again in the
first cut), refusals reported as successes, and a session id that only worked if log lines
never interleaved. Left as ordered follow-ups in the ticket: the `killed` signal line, the
`capture_event.detail` pre-existing-folder note, and the read-side cost (each sub-agent read
3x and parsed 4x per sweep, sqlite opened per file; fix is a sub-agent hash pre-filter, a
catalog schema change that wants its own ticket).

Also committed: the `tools/ccstats` review-report work found uncommitted at session start
(`5f75844`, 320 tests green), under the operator's reaffirmed rule "always make frequent
commits and pushes". Operator also ruled: ignore `cc-warehouse-architecture/` unless it
bears on the CLI (it does not; nothing in `src/`, `plugins/` or `pyproject.toml` references it).

**What was NOT done:** ticket 37 Part B rows 2, 3, 5 and the pre-filter follow-up. Nothing
else opened.

### Twenty-first handoff, 2026-09-04 (new session)

Short session, no ticket picked up. Opened by reading `OPENING-PROMPT.md`, offered the
standing backlog candidates, and the operator instead ran `/dashboard`. Refreshed
`sessions.sqlite` (20.67s, 30,714 files parsed, 0 unreadable, 27,015 from cache) and
rebuilt the live dashboard, then answered two follow-up questions and made one small
committed change.

**"Does the HTML work offline?" - yes, and it was measured rather than asserted.** The
built page registers ZERO font faces (`document.fonts.size === 0` in a real browser), has
no `<link>`, no `@import`, no `@font-face`, no `fetch`/XHR/WebSocket, no external script
src, and exactly one absolute URL in the whole 1.7 MB file: the SVG XML namespace
`http://www.w3.org/2000/svg`, which is an identifier and is never fetched. Doctype and
`<meta charset>` are both inside the file, so nothing depends on the server's headers.

**"The fonts differ between the served page and the double-clicked file" - the stated
cause was disproved, and a different one was found but NOT confirmed.** Nothing can fail
to load, per the above, and the bytes are identical either way, so origin cannot change
font resolution. What was measured instead: this machine's default handler for BOTH
`public.html` and `http`/`https` is **Brave**, while the browser-automation tool only
drives **Chrome**, so the two pages being compared were probably in two different
browsers. Brave's own `Preferences` holds a `braveShieldsMetadata` entry for
`http://127.0.0.1` carrying a `farbling_token`, meaning Brave's fingerprinting protection
(which restricts which local fonts a page may use) has run on that origin; Shields do not
apply to `file://` URLs. That points the difference at the SERVED page, the opposite of
the initial guess. Left unconfirmed: only one browser is connected to the extension, so
Brave could not be inspected directly. Also ruled out by measurement, not by argument:
per-origin zoom (no saved zoom for `127.0.0.1` or for files), a stale/different file, and
missing fonts (`SF Mono`, `Menlo`, `Georgia`, `Arial Narrow`, `Helvetica Neue` are all
installed; only the later fallbacks `Consolas`, `DejaVu Sans Mono`, `Iowan Old Style` are
not, and they never get reached).

**Shipped: the project checklist is ordered most recently worked on first (`ca80ce7`).**
It was alphabetical, which on the real corpus means 123 rows where the two or three
projects the reader is here for sit wherever the alphabet puts them. Each canonical
project now carries its newest session date; the list sorts by that descending with the
old alphabetical order as the tiebreak, and the date renders on the right of each row
using the `.proj-item .n` style that already existed in the template but had never been
emitted. "Recent" is measured across the WHOLE embedded corpus, not the current date
range, so nudging a date picker cannot reshuffle the list under the reader's cursor.
Two new tests in `test_dashboard_headless.py`, with `dashboard_probe.js` extended to
expose `CANON_LIST`, `PROJECT_LAST_DATE` and the rendered row order. **The tests were
proved to bite**: the sort was temporarily reverted to alphabetical, they failed on the
first row, and the template was restored from a backup verified by sha256. 163 tests
green, ruff clean, verified afterwards in a real Chrome tab on the real corpus (123 rows,
every row an ISO date, monotonically descending, zero violations).

**A gotcha this session hit, worth knowing:** `cp` is interactive in this shell, so a
`cp` that overwrites an existing file BLOCKS on a `(y/n [n])` prompt instead of finishing.
It hung a 600s Bash call and, worse, left the deliberately-corrupted template in place
until the restore was redone in Python. Use a Python `write` + `os.replace` for
restore-from-backup steps, never `cp`.

**Reviewed but NOT changed: the project hide-list.** The operator asked whether any hidden
project resembled the kept ones. Measured across all 30,714 session rows with the page's
own canonicalisation and the 23 saved rules: 140 canonical projects, 71 shown, 69 hidden.
Four real candidates were surfaced - `Scaffoldings-fifty-shades-of-dotfiles` (4,005
sessions, 178.8 h, $7,170, active that day), `CaptainCodeAU-cc-print-shop` (the only `cc-`
project hidden while `cc-warehouse`, `cc-vantage` and `cc-context-forge` are all shown),
`CaptainCodeAU-EXTENSIONS-important-soonish-links` (531 sessions, active the day before),
and `CaptainCodeAU-claude-code-transcripts` - plus the tax family (~5,700 sessions, 288 h)
flagged separately as probably deliberate. **The operator chose none of them**;
`dashboard-defaults.json` is unchanged. Recorded here so a future session does not
re-derive the same list and read silence as an oversight.

### Twentieth handoff, 2026-08-28 (new session)

Opened by reading `OPENING-PROMPT.md`, then asked the operator which standing candidate to
pick up. Chose the 3D/WebGL ccstats companion page (raised 2026-08-27, explicitly not
started - the operator wanted it PLANNED first). Entered Plan Mode rather than starting
straight into code, per that instruction.

**Research before designing.** Two Explore agents in parallel read `collect.py`,
`dashboard.py`, `common.py` for the exact schema and reusable machinery; measured the
REAL corpus read-only (`~/.cc-warehouse/stats/sessions.sqlite`) rather than trusting the
README's prose: 26,403 sessions (4,042 mine / 20,353 automated / 2,008 sub-agent), 163
days, peak 28 concurrent sessions, longest session 33.5 days. Read the "Estate Orbit"
artifact the operator named as inspiration (a governance-graph 3D page using the bundled
`ForceGraph3D` library, TrackballControls, WASD/space-pan camera conventions) for its
INTERACTION quality, explicitly not its node/link data model - confirmed via
`parent_session_uuid` that ccstats has exactly one real session-to-session edge (396
parents, 2,008 sub-agent children) and is otherwise a time-interval population, not a
graph. Put two forks to the operator with an ASCII preview each (shape: Day Wall vs.
Project City vs. Swarm; renderer: hand-rolled WebGL2 vs. vendoring three.js) - Day Wall +
hand-rolled won both, matching the 2D page's own no-chart-library rule.

**Plan written to `Plans/spicy-spinning-pancake.md`** (gitignored, per this repo's own
`.gitignore` for `Plans/`), approved, then built test-first: `tests/test_daywall.py` (19
oracle tests) written BEFORE `daywall.py` existed, per this project's own rule. While
designing the payload found and fixed a real bug before it shipped: a `Lookup` over
`local_date` in first-seen order would silently SKIP a calendar day with zero sessions,
which would misalign every later day of a multi-day session once the browser-side
`dayIdx + 1` arithmetic crossed the gap - `days[]` is now a full contiguous date range,
not just the populated ones, with its own oracle test.

**Built:** `tools/ccstats/daywall.py` (its own slim 8-column payload, not an extension of
`dashboard.build_payload`; the `session_uuid` join is scoped to `is_subagent = 0` on the
parent side, since a sub-agent row carries its PARENT's uuid, not its own - the naive
join was measured to produce 35,471 spurious pairs), `daywall_template.html` (one box per
session on a WebGL2 canvas, positioned by day/hour, stacked into concurrency lanes
re-packed fresh on every filter change, hand-rolled camera + offscreen-framebuffer
picking, no library), `tests/node/daywall_probe.js` + `tests/test_daywall_headless.py` (9
tests exercising the page's real generated `<script>` block's pure-data half under Node,
mirroring `dashboard_probe.js`'s existing pattern), and `.claude/commands/daywall.md`
(mirrors `/dashboard`'s shape, shares its `dashboard-defaults.json` read-only rather than
duplicating the edit flow).

**Verified against the real corpus in a real Chrome tab**, not just `pytest` (this
project's own bar, ticket 28.9): built to a scratch `CCSTATS_OUT` first, served over
loopback, and found ONE real bug that no test had caught - `#wall{position:fixed;inset:0}`
does NOT stretch a `<canvas>` (a replaced element) the way it stretches a `<div>`; the
canvas stayed at its intrinsic 300x150 default and every box rendered off in the
literally-zero-sized viewport. Diagnosed via `getBoundingClientRect()` and
`getComputedStyle()` through `javascript_tool`, fixed with an explicit `width:100vw;
height:100vh`. After the fix: rotate/pan/zoom, click-to-spotlight (populated a real
session's project/kind/timestamps/cost/model correctly), every kind/project filter
checkbox, Reset, and Escape all confirmed working against all 8,682 real sessions, zero
console errors throughout. The scratch corpus copy (141 MB, real private data) was
deleted afterward; the real `~/.cc-warehouse/stats/` was never touched.

Committed and pushed (`0d41d3d`) after a targeted personal-data check on the 7 new/changed
files (clean). Full suite re-confirmed green after (161 ccstats tests, repo-wide ruff, the
1,198-test repo oracle suite). `OPENING-PROMPT.md`'s "Next task" section updated to close
this out and point at `/daywall`.

### Nineteenth handoff, 2026-08-27 (new session)

Opened by reading this file (the eighteenth handoff, below), then asked the operator
which of the standing backlog candidates to pick up. The operator instead asked to check
the previous session's last few messages for context - a 3D/WebGL ccstats dashboard idea,
raised but not started (see "Next task" in `OPENING-PROMPT.md`). Retrieved it by reading
the previous session's own transcript directly (`~/.claude/projects/.../*.jsonl`), not
guessed. Having seen that, the operator immediately flagged a more pressing problem:
`OPENING-PROMPT.md` itself had grown to 1,930 lines, mixing a chronological log of past
sessions with what a fresh session actually needs, and asked for a restructure plan
before any of it ran.

**This whole file is the result.** Mapped the original file's structure with a forked
sub-agent first (found 94% of it was closed-ticket writeups and past-session narrative,
only ~6% live/actionable). Two design forks were put to the operator directly: handoff-log
order (newest-first, chosen) and where to put the closed ccstats/dashboard writeups that
had no ticket file to live in (a new file next to the code, `tools/ccstats/HISTORY.md`,
chosen). The full plan was then confirmed with the operator before any file changed.

Shipped, verified line-for-line against the original before anything was deleted:
- **`harness/HANDOFFS.md`** (this file) - the session log, newest first, with real `###`
  headers. Also reconstructed the "seventeenth handoff", which had never had a dated
  entry of its own - it only existed as a status block inside the old ACTIVE TASK section.
- **`harness/GOTCHAS.md`** - the 5 recurring environment gotchas (was mislabeled "two
  environment facts" while actually holding five).
- **`tools/ccstats/HISTORY.md`** - the closed ccstats/dashboard build history.
- **`harness/tickets/28-backlog.md`**'s 28.9 entry gained the unique investigation detail
  that only lived in `OPENING-PROMPT.md` (the measurement table, stage-isolated peaks,
  the three repro-script names, the operator-approved 4-step test plan) and had a real
  self-contradiction fixed - the entry said "NOT YET IMPLEMENTED" a few paragraphs above
  its own "fully DONE" closing line.
- **`tests/test_doctor_external_contract.py`**'s docstring, which cited an
  `OPENING-PROMPT.md` section number that was about to move, repointed at the ticket file.
- **`OPENING-PROMPT.md`** itself cut from 1,930 to about 100 lines, keeping only current
  status, the open backlog, and a "Where else to look" index. A "Keep it this way" section
  was added specifically because explaining what moved isn't enough on its own - without
  an explicit instruction, the natural next move is writing a new narrative paragraph
  straight back into it, recreating the exact bloat this session fixed.

Verified, not assumed: every extracted block was diffed byte-for-byte against the
original `OPENING-PROMPT.md` content before it was deleted from there (all matched except
two intentional pointer-text edits, both fixing dangling references to the old "Two
environment facts" section name). Full suite green after every change (1,197 main-repo
tests + 132 ccstats tests passed, ruff clean); a repo-wide census (not grep - the
project's own `census.py`, control-verified) confirmed only 3 harmless historical
mentions of "OPENING-PROMPT" remained repo-wide, and the two real inbound pointers
(`harness/tickets/28-backlog.md`, `tests/test_doctor_external_contract.py`) were both
fixed. Five commits, all pushed: `003f6fb` (new files), `6e209ab` (ticket 28.9 merge),
`ad5bdd5` (test docstring fix), `a2502f7` (slim `OPENING-PROMPT.md`), `e9cd551` ("Keep it
this way" section).

**Also updated, outside this repo: this session's own persistent memory** (the project's
Claude-memory directory). Two existing memory files cited "OPENING-PROMPT.md environment
notes" by name - fixed to point at `harness/GOTCHAS.md` instead. Saved a new memory,
`opening-prompt-is-an-index-not-a-log.md`, recording the new convention so a future
session doesn't recreate this same bloat out of habit rather than by reading the file
carefully every time.

**What was NOT done:** the 3D/WebGL ccstats dashboard idea (see "Next task" in
`OPENING-PROMPT.md`) - explicitly deferred to a new session, per the operator's own
request, both before and after this restructure. Nothing from ticket 28's remaining
backlog (28.2/28.10/28.11/28.12/28.14) or `ccw share --open` was touched.

**Same session, continued afterward: the restructure above was proved with a real Herdr
test, not just trusted.** The operator asked for a genuinely fresh Claude Code session,
launched in a sibling Herdr pane with no context from this conversation, to be driven
with the real opening command ("Read OPENING-PROMPT.md and follow instructions") and
watched for gaps. None were found: it correctly read the new ~100-line file, said nothing
was active, listed both the 3D-dashboard idea and the backlog, recommended the former
(matching the file's own framing), and - when told to actually start - read the right
background files (`tools/ccstats/README.md`, `PANEL-CONTRACT.md`) before entering Plan
Mode on its own, exactly matching this project's convention. Stopped there on purpose;
letting a full planning run happen unsupervised was out of scope for a structure test.

**A second, unrelated thing came out of that test: real gaps in how to drive Herdr
itself**, found by hitting them firsthand while running the test (not from docs). Three
real errors, each with a genuine root cause, not flukes:
- `agent_pane_busy` right after `pane split` - a freshly split pane runs its own shell
  startup/onboarding script first and is not yet "available"; guessing a sleep duration
  is the wrong fix.
- `agent_prompt_stalled` on `agent prompt --wait` - Herdr's own 5-second "did it start
  working" grace period is shorter than this environment's real per-turn overhead
  (session hooks, skill loading, a custom status line), so a healthy prompt can still
  trip the check.
- `herdr pane close --pane <id>` is a syntax error - `pane close` is the one `pane`
  subcommand that wants a bare positional ID, unlike most siblings that accept `--pane`.

All three, plus the general "wait via Herdr's own event system, never poll" pattern
(proved with a real 8-second measured block through a background Monitor task, not
assumed), were written up and folded into the actual places a reader already looks -
**`~/.claude/skills/herdr/SKILL.md`** (global, loads automatically whenever Herdr is
used, any project) and a short pointer added to **`~/.claude/PAI/USER/AISTEERINGRULES.md`**
(global, loads every session). Neither file lives in this repo; noted here only because
the work happened in this session and because a future cc-warehouse session driving
Herdr benefits from knowing it's already fixed upstream, not because cc-warehouse owns
either file. A stronger rule was added after discussion: never close a pane on
`agent_status: idle` alone, since a false-early idle (a known, still-unfixed Herdr
nested-TUI quirk) plus an immediate close would silently and unrecoverably kill real,
still-running work.

**Verified twice, not once.** The same nested Herdr test (a fresh agent launching its
OWN fresh agent and waiting on it correctly) was re-run after the skill-file fix: zero
errors the second time, including on the exact three traps above, on a brand-new agent
that had only the two updated files to go on - not this conversation's context. Every
test pane was closed afterward; nothing was left running.

---

### Eighteenth handoff, 2026-08-27

**Eighteenth handoff, 2026-08-27 (new session).** Opened by reading this file, then the operator
ran `/dashboard` directly (a fresh build + real-Chrome look, nothing else) rather than picking up
ticket 28.9's own backlog candidates (28.2/28.10/28.11/28.12/28.14, `ccw share --open` - none of
these were chosen or touched this session). Two follow-up asks landed after that, both about the
live dashboard's UI, not its data pipeline.

**1. Sub-agent population split.** The operator's own framing: sub-agent runs get counted as "a
session" today, which is right for some stats and wrong for others - asked for the two groups
worked out with reasoning, not guessed. The mechanism: every `session` row already carried a
`kind` (`mine`/`subagent`/`automated`, from the sixteenth handoff's own `session_kind()`), but
ONE page-wide toggle applied that classification to every panel identically - `inRange()` fed a
single `FS` array to all 20 panels. Split into two populations instead: `FS` ("my own work" -
sub-agent NEVER counted, because a sub-agent's engaged time sits INSIDE its parent session's own
clock time, so counting it again double-counts minutes) and `FSW` ("real work done" - sub-agent
ALWAYS counted, because its cost/tokens/tool-calls are genuine extra spend, not nested time).
`inRangeInteractive`/`inRangeWorkload` replace the old single `inRange`; `DEFAULT_KINDS` dropped
to `{mine}` alone (was `{mine, subagent}`); the "sub-agent runs" checkbox was removed from the
filter bar entirely (`.claude` reader can no longer toggle it - the rule is now fixed per panel,
by design, since a single toggle literally cannot serve two contradictory questions at once).
9 of 20 panels (Projects, Repositories, Project x month, Models, Model x month, Tokens, Thinking,
Tools, Skills & agents) now read `FSW`; the rest (Daily/Weekly/Monthly, Session sizes, Hour
heatmap, By weekday, Worktrees, Top/Longest sessions, and most of Overview's 15 KPI tiles) stayed
on `FS`. Two genuine judgment calls were put to the operator as a 2-option `AskUserQuestion`
rather than decided alone: **Tools panel now counts sub-agent tool calls** (real work, delegated
or not); **the "25 most expensive sessions" leaderboard excludes sub-agent runs** (it is a
leaderboard of the operator's OWN sessions, not a cost bucket). Overview's KPI accumulation loop
was split into two passes (one over `FS`, one over `FSW`) since it mixes both kinds of tile in one
panel - `session_kind()`'s own Python-side docstring in `dashboard.py` was updated to match, since
it used to claim sub-agent was "reachable via a toggle", which is no longer true.

Verified: `tools/ccstats/tests/test_dashboard_headless.py`'s three toggle-behaviour tests were
REWRITTEN, not just made pass again - they tested the OLD one-toggle behaviour on purpose, so a
green run against the new code would have meant the fix was reverted, not confirmed. The rewrite
adds an explicit regression guard that a scenario still naming `"subagent"` in `kinds` (mimicking
the removed checkbox) has ZERO effect on either population. Full suite: 132 passed (was 129
before this session even started, unrelated to this change), ruff clean, pyright unchanged (82
pre-existing errors, all in `tools/` which is outside strict `src/` by design, confirmed via
`git stash` that the count is identical before/after). The REAL `~/.cc-warehouse/stats` dashboard
was rebuilt from live data and headless-probed against the actual generated HTML (not a test
fixture): `fsLength` 661, `fswLength` 1950, "API cost" tile `US$ 53,747` - all three independently
cross-checked against a fresh direct SQL query (`is_real=1`, the same date window, the operator's
real 23-pattern exclude list applied) and matched exactly. Opened in a real Chrome tab over
loopback: 0 console errors, "sessions with a reply" 661 / "typical session length" 45.8 min (both
`FS`-driven, sub-agent excluded) alongside "API cost" `US$ 53,747` / "tool calls" 119,546 (both
`FSW`-driven, sub-agent included) rendered correctly side by side on the same page. Commit
`ee5d65a`, pushed.

**2. Layout gap + always-visible note, both operator-reported after looking at the rebuilt
page.** The note ("Sub-agent runs are handled automatically per chart...") read as too prominent
sitting permanently in the filter bar. Converted to a small `data-tip`-driven hover icon (an "i"
in a circle, reusing the page's own existing chart-tooltip mechanism, `.cc-tooltip` /
`document.addEventListener("mouseover", ...)` - no new JS infrastructure needed). The same
mechanism was used to answer the operator's own on-the-spot question ("what is this
`2,414 · US$ 66`?" - the live count/cost of "automated one-shots", off by default) by attaching a
second tooltip directly to that checkbox, so the answer now lives on the page itself, not just in
chat. Separately, a real ~100px dead gap above the date filters: `<header class="mast">` was
wrapped in the generic `.wrap` class, whose `padding: 0 28px 96px` exists for the PANELS wrap at
the very bottom of the page - reused on the header, its 96px bottom padding just opened a gap
nothing needed. Split into a new `.mast-wrap` (same max-width/centering/side-padding, zero bottom
padding of its own) confirmed via `grep` to be the only two places `.wrap` was used before
touching either.

Verified: 132 tests still green (no test covers pixel layout or tooltip visibility - this was a
real-browser-only check, matching this project's own "the only guard against a UI regression here
is a human looking" note from the sixteenth handoff). Rebuilt the real dashboard again, opened in
a real Chrome tab: 0 console errors before and after the change; a before/after screenshot pair
confirmed the gap closed and the filter bar visibly tightened; hovering the new "i" icon and the
"automated one-shots" label both showed their correct tooltip text and stayed hidden otherwise.
Commit `8f3b4ab`, pushed.

**The operator asked whether `.claude/commands/dashboard.md` also needed updating. Checked, not
guessed: it does not.** Read the whole command file - every step (resolve `$OUT`, refresh
`sessions.sqlite`, read/write `dashboard-defaults.json`, the `--exclude`/`--include` build flags,
serve over loopback, stop the server) is about the BUILD/SERVE workflow, none of which changed
this session. Nothing in the command's own text describes the generated page's internal filter-
bar wording, tooltip behaviour, or layout, so nothing in it went stale. Confirmed to the operator
rather than editing on a guess.

**What was NOT done:** ticket 28.9 remains closed and untouched (unrelated to this session's
work). None of the standing backlog candidates (28.2/28.10/28.11/28.12/28.14, `ccw share --open`)
were picked - still open, still the operator's to choose. Step 5 of the sixteenth handoff's own
dashboard plan (client-side concurrency reimplementation) remains deferred, not touched here
either. The unresolved `dashboard-defaults.json` overwrite mystery from the sixteenth handoff is
still unresolved - not chased down this session.

**Same session, after the two fixes above shipped: a NEW idea was raised, NOT started.** The
operator looked at an unrelated artifact ("Estate Orbit" - a 3D WebGL force-graph visualization
built for a completely different project, a personal decision-log system) and liked its visual/
interaction quality (drag-rotate/pan/zoom, click-to-spotlight, a live filter panel), not its
data model. Ask: a companion 3D/WebGL page for the ccstats corpus itself, alongside the existing
2D `claude-code-dashboard-live.html` - explicitly NOT a copy of Estate Orbit's node/link scheme
(planets/hubs/moons was one example, not a spec), designed ground-up for what ccstats data
actually is. The operator wants this PLANNED in a fresh session before any code is written, and
asked for an opening prompt to paste there - one was written and handed over (not saved to a
file in this repo, since it was meant to be pasted directly), covering: what already exists to
read first (`dashboard.py`, `dashboard_template.html`, README, PANEL-CONTRACT.md), the Estate
Orbit URL with an explicit "style only, not content" scope note, real measured corpus numbers as
of today (8,682 real sessions, 140 project labels, 105 repo roots, 88 tools, 9 model version
strings/~4 families, attribution: 10 agents/5 mcp_servers/31 mcp_tools/3 plugins/53 skills,
2026-02-14 to 2026-08-27), and this project's own house rules (self-contained HTML, no CDN,
never commit/upload the output, put every real fork to the operator as a table + a direct
question). **Nothing has been designed or built yet - if the next session opening this file is
NOT the planning session the operator described, ask before assuming any shape for this feature;
none has been chosen.**

---

### Seventeenth handoff, 2026-08-24

*(This entry did not exist as a dated log entry until this file was created on 2026-08-27 -
it lived only as a condensed status block inside `OPENING-PROMPT.md`'s "ACTIVE TASK: ticket
28.9" section, with no numbered handoff of its own even though every session around it had
one. Reconstructed here, text unmodified from the original except the correction note at the
end, so the handoff sequence is complete for the first time.)*

**FIX B DONE 2026-08-24.** The operator picked server-side reuse (over client-side
reconstruction) via a 2-option table when asked directly. Root cause turned out to be broader
than the ticket's own four-level framing: each level (row, phase, turn, whole-transcript) - plus
a FIFTH pass this investigation found, `_claude_turn_count` (the header's "N you / M Claude"
split, which called `_claude_md` per turn just to test truthiness) - independently re-derived
its own markdown fragment from scratch via a fresh call chain into `_render_block`, so a block
already rendered once at row level got rendered again up to four more times. Fix: a plain
`dict[(id(block), policy) -> list[str]]` cache (`_BlockCache`), created once per `_render_page`
call and threaded as a REQUIRED parameter (no default, so a missed call site is a pyright error,
not a silent loss of caching - this caught the fifth pass, `_claude_turn_count`, before it
shipped half-fixed) through 13 functions between it and `_render_block`. `_render_block` itself
is now a thin cache-check wrapper; the old body moved verbatim to `_render_block_uncached`, so
the rendering LOGIC is byte-for-byte unchanged, only WHEN it runs changed.

Verified, not assumed: full suite 1,198 passed (up from 1,197 on `master` at session start - the
"1,175" Fix A recorded is stale, 22 unrelated tests landed since, confirmed via `git stash`),
ruff clean, pyright 0 project errors. Output proved BYTE-IDENTICAL before/after on a real 9.7 MB
session (`cmp` on all four projection files, `git stash`/`stash pop`). Isolated to Fix B alone
(holding Fix A constant via `git stash`), wall time on the ticket's synthetic repro dropped ~31%
(0.511s -> 0.350s); peak memory stayed flat (28.00 -> 28.03 MiB, noise-level) - exactly as
predicted for this shape, since server-side reuse cuts redundant CPU/allocation work, not the
final page weight (only the unchosen client-side-reconstruction shape would have done that). A
new test, `test_render_block_is_memoized_across_copy_levels`
(`tests/test_render_html.py`), pins the cache's own invariant (no `(block, policy)` pair computed
twice) rather than only the byte-equality the existing locked test already covers; confirmed it
actually catches a regression by manually bypassing the cache in a throwaway script, which
reproduced up to 10 calls for a single block.

Real-browser check done per the operator's explicit requirement, and went further than Fix A's
own check: the real session's `conversation.html` served over loopback and opened in a real
Chrome tab via `claude-in-chrome` - zero console errors on load and after every interaction.
Reading the system clipboard triggered an OS permission prompt that froze one `javascript_tool`
call (worked around by not retrying it, per the dialog-avoidance rule in this file's own
system prompt); verification instead read the DOM directly, which the operator-approved plan's
own step 4 explicitly allows as an alternative to a literal clipboard read. EVERY
`[data-copy-src]` element on the real rendered page - 2,013 of them, covering all four levels
(1,477 row/block, 509 phase, 24 turn, 1 whole-transcript) plus the header meta and files index -
was base64-decoded and confirmed to be a substring of the real `transcript.md` fetched from the
same server: 2,013 of 2,013 passing, the same guarantee
`test_copy_as_markdown_payloads_equal_transcript_fragments` checks, now proven against a live
browser-rendered page. Real clicks on the whole-transcript, row-level and phase-level copy
buttons produced zero console errors.

**Not yet committed as of writing this paragraph** - `src/cc_warehouse/render.py`,
`tests/test_render_html.py`, `harness/tickets/28-backlog.md`, and this file are all modified in
the working tree. Full account and exact numbers: `harness/tickets/28-backlog.md`'s 28.9 entry.

**Correction, added 2026-08-27**: the "not yet committed" line just above is stale. This work
was committed as `7842549` before the eighteenth handoff's own session even started - that
session found and fixed the stale claim in this file's banner, and this note fixes it here too.

---

### Sixteenth handoff, 2026-08-24

**Sixteenth handoff, 2026-08-24 (new session).** Opened by reading this file (the fifteenth
handoff, above), which pointed straight at ticket 28.9 Fix B. Before touching it, the operator
asked to look at a specific number on the live dashboard - `~/.cc-warehouse/stats/claude-code-
dashboard-live.html`'s "1.2 min / typical session length" tile looked wrong - and asked for a
thorough, wide-blast-radius investigation into whether the dashboard's numbers were correct at
all: double-counted, missing, or stale values were all named as suspects. Fix B was NOT started
this session either.

**Investigation, not guesswork.** Three parallel Explore agents each read one full source file
(`dashboard.py`, `dashboard_template.html`, `collect.py`) and reported every SQL query, every
JS computation, and every column derivation verbatim with file:line refs. Every consequential
finding was then independently re-verified first-hand: real `sqlite3` queries against
`~/.cc-warehouse/stats/sessions.sqlite` (read-only), a real `find` census of both source trees'
sub-agent filenames, and a decode of the actual bytes in the shipped HTML file. Four real,
distinct defects were found and confirmed, none of them guesses:

1. **A sub-agent transcript existing in BOTH the archive and the live tree was stored TWICE.**
   `collect.py:1364-1367` keyed a scanned transcript by its raw filename stem; the archive names
   a sub-agent `<id>.jsonl`, the live tree keeps Claude Code's own `agent-<id>.jsonl` - different
   stems, different dedup keys, so the "duplicate payloads collapsed" pass never paired them.
   Measured: 1,908 pairs, all with IDENTICAL size/cost/engaged-time (1,908 of 1,908), inflating
   every summed figure corpus-wide by +US$5,750, +119 engaged hours, +69,518 turn rows.
2. **`is_real = 1` blended three unrelated populations into one "session" count**: the
   operator's own interactive sessions (`entrypoint` `cli`/`local-agent`/NULL, the last being
   138 real sessions that predate Claude Code recording the field at all, 2026-02-14..03-11),
   automated one-shot API calls (`entrypoint='sdk-cli'` - one prompt, a few seconds, zero tool
   calls: hooks, titling), and Task sub-agent runs (`is_subagent=1`). Measured: 46.5% of
   "sessions" in the default range were the latter two. This, not arithmetic, is why the tile
   read 1.2 min - the median was correct for the 6,443-row set the page was actually counting;
   that row set was never "your sessions".
3. **The tile itself measured `wall_seconds` (raw file span, includes idle), not
   `engaged_seconds`**, contradicting `PANEL-CONTRACT.md`'s own house rule and the tile's own
   label, with no disclosure either way.
4. **The shipped page carried NO project exclusions at all** (`default_unticked_projects: []`,
   verified by decoding the real HTML's embedded payload) even though
   `~/.cc-warehouse/stats/dashboard-defaults.json` listed six real patterns - `dashboard.py`
   never read that file, only `.claude/commands/dashboard.md`'s own flag-passing did, so a
   direct run (which is what built the page currently on disk) silently dropped them.

Full measured comparison (default range): page showed 6,443 "sessions" / 1.2 min typical /
US$65,310; the operator's true 666-673 interactive sessions measured 55-116 min typical (wall
vs. engaged) / US$54,229-54,524 - sessions +867%, tool calls +65%, replies +62%, cost +20%,
typical length 96x too low.

**Plan approved via ExitPlanMode, then a 2-option question on the one real design fork**: keep
all three populations but split them behind a toggle (recommended - sub-agent cost is real
money, hiding it is worse than blending it), vs. hard-filter to interactive sessions only and
drop the other two from the page entirely. **Operator chose the toggle**, with the exact default
tick-state specified in the question's own preview.

**Four fixes shipped, in dependency order, each proved red-then-green against a real `git
stash` of just its own production diff:**

1. **The double-count (D1)** - `collect.py:1364-1367` strips a leading `agent-` from a
   sub-agent's key before building its cache/dedupe identity; `CACHE_SCHEMA_VERSION` bumped
   1->2 so the one already-populated `scan-cache.sqlite` (97.9% of the corpus, all from a prior
   run) can't serve a stale per-tree row back out under the OLD key. Verified against real data:
   `is_real=1` row count dropped from 10,128 to 8,264 on rebuild, sub-agent files ~halved (3,821
   -> ~1,930), matching the measured 1,908-pair defect almost exactly (small residual is normal
   corpus growth between the two measurements, this machine captures continuously).
2. **The population split (D2)** - new `dashboard.py` classifier `session_kind()` (`is_subagent`
   wins first -> `subagent`; `entrypoint='sdk-cli'` -> `automated`; everything else, including
   the pre-field-recording NULL rows -> `mine`), a new `kind` column in the embedded payload
   (`lookups.kinds` + one int per `S` row, looked up by NAME client-side via `KIND_IDX`, never a
   hardcoded 0/1/2), and a new "Count as a session" control in the page's existing top filter
   bar - `[x] my sessions N  [ ] sub-agent runs N · US$c  [ ] automated one-shots N · US$c` -
   defaulting to `mine` only, each label live-updating via a new `kindCounts()` (date+project
   filtered, kind-toggle-independent on purpose, so a reader sees what TICKING a box would add
   rather than watching a number vanish the moment they tick it).
3. **The tile (D3)** - `dashboard_template.html`'s Overview panel now sorts/medians
   `IDX.S.engagedSec`, not `wallSec`; the note now says which column and which populations
   ("whichever kinds are ticked above").
4. **The exclusions (D4), two parts.** `dashboard.py` gained `load_default_filters()`, reading
   `<out_root>/dashboard-defaults.json` directly as a fallback when no `--include`/`--exclude`
   flag is given, so a direct run and a `/dashboard` run can no longer disagree. Separately, a
   real correctness bug found alongside it: `state.excluded` was keyed on the RAW project index
   while the Projects/Project-month panels grouped by the CANONICAL name (auto agent-worktree
   folders folded onto their parent, `CANON_PROJECT`) - un-ticking a parent left its worktree
   children ticked, and their hours reappeared folded under the very name just excluded. Fixed
   by keying BOTH sides on the canonical name (`CANON_LIST`, `defaultExcludedNames()`); the
   project checklist now also shows one row per real project instead of one per throwaway
   agent-worktree folder, a side benefit of the same fix.

**Step 5 of the approved plan (make the Concurrency panel and its two Overview tiles obey the
new project/kind filters too, via a client-side interval sweep over per-session start/end
timestamps) was explicitly named as the one deferrable piece in the plan itself, and was
deferred** - real timezone-aware calendar-day clipping (`build_overlap` in `collect.py`) is
genuinely complex to reimplement correctly client-side, the panel was never the operator's
actual complaint, and a wrong reimplementation would be worse than an honestly-labelled
limitation. Took the plan's own documented fallback instead: the D1 fix already cleans
`overlap_day`'s numbers (it's built from the same, now-deduplicated `session` table), and the
two Overview tiles' notes now say "whole corpus" on the tile itself, closing a real disclosure
gap `PANEL-CONTRACT.md` had claimed was already closed but wasn't.

**A new headless test harness, `tools/ccstats/tests/node/dashboard_probe.js`, is the other
lasting change.** Before this session `dashboard_template.html`'s client-side JS had ZERO test
coverage - nothing had ever executed it - which is how all four defects above shipped with a
fully green `pytest` suite. The harness runs the REAL generated `<script>` block (not a copy)
under Node's `vm` module against a minimal hand-built DOM stub (real enough for this page's
exact usage: id lookups, classList, dataset, one delegated `querySelectorAll` target; a broader
page rewrite would need it extended, which is intentional - it forces a human to look rather
than silently degrading). One non-obvious mechanic worth remembering: `vm.Script.runInContext`
does NOT attach top-level `let`/`const` bindings as properties of the context object (only `var`
would), so reading `context.FS` after the script runs returns `undefined` even though the
script ran fine - the fix is appending a small epilogue INSIDE the same script text
(`;globalThis.__probe = { state, ... };`) so it shares the real lexical scope, and using
closures/accessor functions (`getFS: () => FS`) for anything the page later REASSIGNS (`FS =
[]` inside `recomputeFilteredSessions`), since a captured snapshot goes stale the moment a
scenario re-triggers `renderAll()`. `test_dashboard_headless.py` (new) builds a tiny synthetic
`sessions.sqlite` with hand-computed expected numbers - 5 "mine" rows with engaged minutes
10/20/30/40/50 (median 30, cost $15.00 exactly), 2 sub-agent and 2 automated rows, one project
and its auto-worktree-suffixed child - and asserts the ACTUAL rendered tile text and `FS.length`
against those hand-computed numbers, never against `dashboard.py`'s own aggregation code, so a
bug in either the Python payload builder or the page's own JS is equally able to fail it. Also
confirms the canonical-exclusion fix directly: excluding the parent's name removes the worktree
child's session too.

**Verified for real, at every layer, matching this project's own "test the code, don't just
read the output" lesson**: 6 new headless tests + 7 new `session_kind()` tests + 8 new sub-agent
dedup tests, all proved red-then-green against real `git stash`ed production diffs; full
ccstats suite grew 110 -> 131 passing; main repo's 1,197-test oracle suite and pyright stayed
untouched and green (one pre-existing, unrelated pyright gap in `tests/test_render_open.py`,
confirmed via `git status` to predate this session, not touched); ruff clean repo-wide. A
scratch rebuild (`CCSTATS_OUT` pointed at a session-scratchpad dir, never
`~/.cc-warehouse/stats`) was run through the real `collect.py` + `dashboard.py` pipeline on this
machine's REAL corpus and opened in an actual Chrome tab via `claude-in-chrome` (loopback-served
on `127.0.0.1:8931`, `file://` is refused by the browser tool - see `harness/GOTCHAS.md`):
zero console errors on load and after interaction; the default view read exactly "668
sessions with a reply" / "55.6 min typical session length" / "US$ 54,506 API cost", matching the
headless probe's own numbers to the byte; ticking "sub-agent runs" live-recomputed every tile
with no reload (668 -> 2,184 sessions, "typical session length" 55.6 -> 4.6 min - directly
demonstrating the exact mechanism that produced the original 1.2 min bug - and API cost US$
54,506 -> 60,053, matching 54,506+5,547 exactly); the project checklist showed one row per real
project, named worktrees (e.g. `-.worktrees-ui-first`) correctly left un-folded per the existing
rule. Server killed and tab closed afterward.

Two commits, both pushed: `cf71d3c` (the collect.py dedup fix + its tests) and `4898c5f` (the
dashboard classifier, toggle, tile fix, exclusion fixes, the new Node harness, and their tests).
Every fix was verified against a session-scratchpad copy FIRST, before touching real data.

**The real `~/.cc-warehouse/stats` was then rebuilt for real, with the operator's explicit
go-ahead (asked via a 2-option question).** `collect.py`: `real_sessions` 10,128 -> 8,265 (the
D1 dedup fix landing on the real corpus, matching the scratch-run's proportional drop almost
exactly). `dashboard.py`: the real, already-existing `dashboard-defaults.json` (32 raw project
names, six patterns, saved by a prior session's `/dashboard` run) was picked up automatically
via `load_default_filters()` with NO flags passed - confirmed by decoding the rebuilt page's own
embedded payload (`default_unticked_projects`: 32 entries, was `[]`) - proving the D4 fix on the
real file it was written to fix, not just the synthetic one. Opened in a real Chrome tab
(loopback, `127.0.0.1:8932`): default view **488 sessions, 53.2 min typical session length**
(was 1.2 min), "Projects: 20 excluded" (32 raw names folded to 20 canonical, the D4b fix),
zero console errors. Both temporary HTTP servers (scratch on 8931, real on 8932) were killed and
both tabs closed afterward; nothing was left running.

**Three more operator follow-ups, same session, after seeing the toggle live, all DONE:**

1. **"sub-agent runs" now defaults ON too** (`DEFAULT_KINDS` -> `{mine, subagent}`), only
   "automated one-shots" still defaults off - a sub-agent is real work done on the operator's
   behalf, same as watching a Task call run. `test_dashboard_headless.py`'s default-view test
   rewritten for the new 7-row default population (was 5); a new test covers explicitly
   dropping to mine-only, since that is now the thing a reader has to opt INTO, not the default.
2. **The filterbar and panel-nav layout were tightened.** The filterbar wrapped onto three
   lines once the toggle row landed, with the summary line stranded alone on its own row -
   restructured into two explicit rows instead of one unconstrained wrapping flex row.
   Fixing this surfaced a real, separate bug: the sticky panel-nav bar below it was pinned at
   `top: 49px`, a hardcoded guess matching the OLD single-row filterbar height, already stale
   the moment the toggle row was added - replaced with `setNavTop()`, which measures the
   filterbar's real rendered height (re-measured on resize) instead of guessing. The panel-nav
   links themselves were also restyled from plain inline text (read as one continuous run) into
   bordered chips, with a permanent edge-fade (`mask-image`) on the scrolling strip as a visual
   "there's more this way" cue. `dashboard_probe.js`'s DOM stub gained `document.querySelector`,
   `document.documentElement`, and real `style.setProperty`/`getBoundingClientRect` stubs,
   needed by the above - the harness needing extension for a UI-only change is by design (its
   own header comment says so), not a gap.
3. **The real, saved `~/.cc-warehouse/stats/dashboard-defaults.json` held the WRONG exclude
   list**, discovered when the operator looked at the live "Projects" dropdown and it didn't
   match what they remembered dictating. Confirmed by direct comparison: the file on disk (6
   generic patterns - `.claude-worktrees-agent-`, `.worktree`, `private-tmp-`,
   `private-var-folders-`, `scratchpad`, `orchestration-drill`, mtime 2026-08-24T01:25, before
   this session started) does not match `CLAUDE.md`'s own "Fourth round" record of the
   operator's real 23-pattern list from 2026-08-22. **This was not introduced by this
   session** - the file was never written by anything in this session, only read, and its
   mtime predates this session's start. Something earlier today (not identified, not this
   session) replaced the operator's real list with a generic scratch/noise filter. Restored the
   real 23-pattern list from `CLAUDE.md` verbatim (tmp-file + `os.replace`, R2's idiom, even
   though this file lives outside the repo entirely). One value needed reconstruction:
   `CLAUDE.md` redacts the operator's real local username as `<local-username>-` (this repo's
   own privacy rule for anything git-tracked); confirmed, not assumed, by checking that real
   `project_label` values starting with the real account name actually exist in the corpus
   (`<local-username>-.claude`, `<local-username>-Temp`, etc. -
   Claude config/library folders outside `~/CODE`, exactly what that pattern exists to catch)
   before writing it. Dashboard rebuilt with the restored list: 58 raw names -> 57 canonical
   exclusions (was 32 -> 20 under the stale list), "my sessions" 564 (was 668). Verified in a
   real Chrome tab, zero console errors. **This file lives outside the repo
   (`~/.cc-warehouse/stats/`, not tracked in git at all per this project's own DATA-vs-CODE
   separation) - nothing to commit for this fix, it is a local-data correction only.**

One commit, pushed (`c10c851`, items 1-2; item 3 has no git artifact by design - see above).
132 ccstats tests passing, ruff clean.

**What was NOT done:** ticket 28.9 Fix B, again untouched - this is now the SECOND handoff in a
row where an operator-initiated redirect landed before Fix B was ever started (see "Next task"
at the top of this file). Step 5 of the dashboard plan (client-side concurrency reimplementation)
was explicitly deferred, not forgotten - see above. **Also unresolved and worth a future
session's attention, not chased down here**: WHAT overwrote the real `dashboard-defaults.json`
with a generic list sometime before 2026-08-24T01:25 - no session's own account in this file
claims to have done it, and the mechanism is unknown.


---

### Fifteenth handoff, 2026-08-24

**Fifteenth handoff, 2026-08-24 (new session).** Opened by reading this file (the fourteenth
handoff, above), which pointed straight at ticket 28.9 Fix B. Before touching that, the
operator asked for the `claude-code-dashboard-live.html` file to be opened in a real browser
(served over loopback, per `harness/GOTCHAS.md` - the browser tool refuses
`file://`), which was done cleanly, then killed on request. The operator then set a standing
preference, now recorded in memory (`give-full-paths-and-links.md`): use `~/...` in any path
shown to them, never the literal `/Users/<name>/...` form (it leaks the machine's real
username into anything that records the text), and do not spin up a local server by default
for a plain file path - only when the browser tool itself needs one.

Asked how deterministic `dashboard.py` is and how long the pipeline takes, and told to go
measure it rather than guess. **A real mistake happened here**: checking `dashboard.py
--help` (which the script does not support) actually ran `collect.py` for real against the
LIVE `~/.cc-warehouse/stats/` data instead of a scratch copy - this session's own memory rule
about testing with `CCSTATS_OUT` was not applied. Disclosed immediately, confirmed harmless
(refreshed the real stats DB early, touched nothing session-related, no `.building` file left
behind), and the operator approved rebuilding the live dashboard page to match. Measured
result, real data: `dashboard.py` is deterministic except one timestamp field (byte-identical
output twice, confirmed with `cmp` after normalising that one field); the full pipeline
(`collect.py` + `dashboard.py`) takes under 10 seconds warm, ~30-45s cold (estimate from an
earlier session's own measurement on a then-smaller corpus).

**The operator then asked to check whether real sessions in `~/.claude` were going
uncaptured**, suspecting the SessionEnd hook itself might not be firing. It was firing fine
(307/307 real hook-log entries "ok", zero errors) - the real, live finding was a 37-session
backlog from the prior ~2 hours, which `ccw sweep` cleared. **The operator explicitly rejected
this as "just a temporary manual fix"** and asked for the actual mechanism and real, durable
fixes, presented as options first. That investigation surfaced two independent, previously
undiscovered real bugs, found by reading logs and code directly rather than guessing:

1. **The weekly `ccw archive --to` job had been silently failing for two weeks** (612 real
   items failing, 0 folders written on its last real run) - `archive.migrate`'s vault-gone
   fallback path (a stale/missing archive folder falls back to reading the OLD vault store)
   was never updated when `objects/` was retired (ticket 27.4, 2026-08-20), so it tried to
   read a directory that no longer exists. Fixed same-session, oracle-tests-first, verified
   on real production data (`ccw archive --to ~/cc-warehouse-archive`: 612 failed -> 8 failed
   after the first fix, then 8 -> 0 after a second fix for the genuinely-permanent case
   below). Commits `db03dd6` (the vault-fallback fix, landed BEFORE the plan-mode arc below)
   and `24c9ea6` (the permanent-non-session case).
2. **`sweep()` has no per-item exception boundary at all** (`capture_transcript`'s own
   docstring already said so: "any deeper failure propagates to the caller's never-raise
   boundary" - the HOOK path has one, `_run_hook`; sweep does not) - one contended catalog
   write can silently abort the ENTIRE daily sweep batch mid-run, with nothing printed or
   logged, and everything still queued in that run simply never attempted (picked up by the
   next sweep, not lost, but invisible in between). This exact gap was already flagged, not
   yet fixed, in `harness/tickets/31-sweep-full-corpus-cost.md` section 31.4 (2026-08-20,
   "logging only... the retry loop stays unshipped... blocked on a confirmed exception").

**Entered plan mode** (operator-approved, `Plans/majestic-floating-cray.md`) to design real
fixes rather than another catch-up, after two Explore-agent codebase surveys both failed
twice on a transient Anthropic API 529 (server overloaded) - rather than keep retrying, every
file was read directly instead (`capture.py`, `catalog.py`, `store.py`, `sweep.py`, `cli.py`,
`notify.py`, `doctor.py`, `contract/DESIGN.md`'s R14, the freshness-check plugin and its
tests). The operator's own explanation of `win_go_app_test`'s rapid-fire session bursts
(Herdr/subagent-driven automated testing, confirmed NORMAL, not a bug to chase) shaped the
final plan: the real fix is tolerating that load, not investigating that project further.

**Four pieces shipped, each oracle-tests-first (red confirmed against unfixed code, then
green), each committed and pushed separately:**

- **Retry-with-backoff on catalog writes** (`capture.py`, commit `5aef3d3`). The real answer
  to "run captures without stepping on each other": SQLite's own reserved lock (`BEGIN
  IMMEDIATE` + the existing 5s `busy_timeout`) already coordinates writers (R14) - the gap
  was giving up after exactly one wait. `_capture_locked`'s two catalog calls now retry up to
  3 times on `sqlite3.OperationalError` matching "locked"/"busy" only; any other exception
  still raises immediately, unchanged.
- **Sweep per-item safety net + a durable failure log** (`sweep.py`, commit `a19710a`),
  directly answering both "stop one bad session from killing the batch" and "log bad sessions
  for review". `_capture_item` now catches any exception (matching `_archive_subagent`'s own
  existing pattern a few lines above it in the same file), logs it to the same
  `logs/capture.jsonl` the hook path's stage-failure logging already uses, and lets the batch
  continue. `BatchReport`/`ItemOutcome`'s shape is unchanged.
- **Watch the 3 real launchd jobs for failures** (`plugins/cc-capture/hooks/ccw-freshness-
  check.py`, commit `8d88cea`), directly answering "watch the daily/weekly jobs" - `ccw
  doctor`'s own PASS/FAIL verdict never covered these at all, which is exactly why the
  archive-job incident above sat unnoticed for two weeks. Shells out to `launchctl print
  gui/<uid>/<label>` for `com.captaincodeau.ccw-sweep`/`-archive`/`-repair`, best-effort and
  guarded (never blocks session start; a missing `launchctl`, e.g. non-macOS, reads as
  unknown, not broken).
- **Backlog growth-rate context on an already-escalating alert** (same file, commit
  `e35b7b6`), answering "alarm on a fast-growing backlog, not just a broken job" - applying
  this file's own hard-learned lesson (ticket 24.7's first draft alarmed on the raw
  uncaptured count and fired every session on a healthy machine): the growth rate rides along
  as context on a message the doctor-streak signal ALREADY decided to show, never as an
  independent trigger, because this session's own real numbers (37 in ~2h from ordinary
  multi-session usage, ~18/hr) are not reliably distinguishable from a real problem by rate
  alone.

**Verified against real production state at every step, not just pytest**: full suite grew
from 1,175 to 1,197 passing tests across the arc; ruff and pyright stayed clean throughout
(one pre-existing, unrelated pyright gap in `tests/test_render_open.py` predates this
session, confirmed via `git stash`, not touched). The frozen `ccw` binary was reinstalled
(`uv_tool_reinstall_current_project --no-extras`) after the code changes - this session
independently re-discovered the "editing the repo does not change what runs" trap
`CLAUDE.md`'s own hard rule already documents, the first time by forgetting it (an accidental
real-data `collect.py` run, see above), the second time by verifying a fix against the OLD
binary and getting confused before catching it. The real weekly `ccw archive --to` job was
run for real (`517 folders written, 0 failed`, exit 0) and the real launchd job was
kickstarted end-to-end (`launchctl kickstart`), confirmed via a background wait to finish
with `last exit code = 0`, and the freshness-check script confirmed silent afterward. The
plugin cache (a SEPARATE deployment surface from the `ccw` binary - Claude Code reads
`~/.claude/plugins/cache/cc-warehouse/cc-capture/<commit-hash>/`, not this repo directly) was
stale until the operator ran `/plugin marketplace update cc-warehouse` and `/reload-plugins`
themselves at the end of the session; confirmed byte-identical to this repo's copy afterward
(`diff`, exit 0) against the new cache directory `e35b7b6bb2bc`, matching this session's own
final commit hash exactly.

**What was NOT done:** ticket 28.9 Fix B (see "Next task" at the top of this file - entirely
untouched this session, the redirect happened before it was ever started). No other open
item from this file's own tracking was touched.


---

### Fourteenth handoff, 2026-08-24

**Fourteenth handoff, 2026-08-24 (new session).** Opened by reading this file (the thirteenth
handoff, above), which pointed straight at ticket 28.9's "ACTIVE TASK" section and its
operator-approved two-fix plan. Did Fix A only, exactly as that section specified: build it,
test it for real (gates + re-profile + a real Chrome tab), stop before Fix B.

**Fix A DONE.** `_render` and `_render_page` (`src/cc_warehouse/render.py`) now encode each
fragment to UTF-8 bytes and join with `b"\n".join(...)` instead of joining `str` and encoding
afterward - the fix scoped to exactly these two functions' final join, not the "dozens of call
sites" the ticket's own plan predicted might be needed, because encoding at that one boundary
per function was enough to stop the astral-plane 4x-inflation from reaching the whole document.
`render_markdown`/`render_html`'s PUBLIC return type changed from `tuple[str, str]` to
`tuple[bytes, bytes]` (both `build.py` call sites were encoding the result immediately anyway,
so `build.py` simplified rather than grew). That public-type change reached ~40 call sites
across 10 test files (`test_matrix.py`, `test_real_shapes.py`, `test_render_html.py`,
`test_render_html_regressions.py`, `test_render_md.py`, `test_render_md_regressions.py`,
`test_surrogates.py`, `test_thinking_withheld.py`, `test_truncation.py`, `test_chrome.py`) -
each fixed by decoding to `str` once at the point of use (a shared helper where one already
existed, e.g. `test_matrix.py`'s `_rendered`, otherwise a small local wrapper), with zero
assertion logic changed anywhere. `test_surrogates.py` needed one real adaptation, not just a
decode: two tests used to call `.encode("utf-8")` on the result to prove a lone surrogate didn't
break rendering; that encode now happens INSIDE `render_markdown`/`render_html`, so calling the
function at all (and it not raising) is now the assertion.

**Verified, not assumed, at every step**: full suite 1,175 passed, ruff clean, pyright 0 errors
(one pre-existing, unrelated pyright gap in `tests/test_render_open.py` was found and confirmed
via `git stash` to predate this session - not touched, out of scope for this ticket). Output
proved byte-identical before/after via `git stash`/`stash pop` around the production diff, on
TWO independent payloads: the ticket's own synthetic repro (1.60 MiB in, 40 turns) and a real
8.3 MB session pulled from this machine's own `~/.claude/projects` - all 5 projection files
(`transcript.md`, `transcript.compact.md`, `conversation.html`, `conversation.compact.html`,
`manifest.json`) matched with `cmp` both times. Peak memory on the synthetic repro dropped from
61.16 MiB to 28.00 MiB (peak/input ratio 38.18x -> 17.48x) - beating the ticket's own ~26 MiB /
~27x estimate, because the fix landed in both `_render` (markdown, called a second time inside
`_render_page` for the whole-transcript copy payload) and `_render_page` (HTML) rather than only
the HTML page's own join the estimate was based on.

**The real-browser check ran twice** - the Chrome extension was not connected on the first
attempt (a live occurrence of the same environment gap prior handoffs hit, not a new finding),
and the operator was asked to reconnect it rather than the session skipping the check or
declaring the fix done on `pytest` alone. On retry: the real 8.3 MB session's `conversation.html`
served over `127.0.0.1:8917` and opened in an actual Chrome tab via `claude-in-chrome`. Zero
console errors on load and after interaction. All four copy-button levels clicked with the
clipboard read back programmatically (`navigator.clipboard.readText()`, comparing against
`transcript.md` fetched from the same server): the whole-transcript button's output is
CHARACTER-IDENTICAL to `transcript.md` (545,316 chars, `===` true), and the row/phase/turn
buttons' output is each a substring of it - directly exercising
`test_copy_as_markdown_payloads_equal_transcript_fragments`'s own guarantee outside pytest, not
just trusting the test. Icons (including the astral-plane ones Fix A is about) rendered correctly
and round-tripped through copy intact, e.g. a row-level copy came back as
`"<details>\n<summary>🧩 session events</summary>..."` (a real 🧩 JIGSAW PUZZLE PIECE,
un-mangled).

One commit, pushed: `fb85934`, `fix: cut render_html/render_markdown peak memory 2x (ticket
28.9, Fix A)`. `harness/tickets/28-backlog.md`'s 28.9 entry and this file's "ACTIVE TASK" section
were both updated in place with the full account, matching every other closed step in this file.

**The operator then said: do Fix B in a new session, stop here now.** Fix B (the four-level
copy-as-markdown base64 duplication, Mechanism 2 in the ACTIVE TASK section above) was NOT
started - no code read or written toward it beyond what the investigation already covered before
this handoff. The two candidate shapes (server-side reuse vs. client-side reconstruction) are
still an open pick for whichever session does Fix B; see step 3 of the plan above. This file's
top "Next task" pointer and the ACTIVE TASK section's own status line were updated to send a
fresh session straight at Fix B rather than back through Fix A's now-closed investigation.

**What was NOT done:** Fix B, and everything downstream of it in the plan (step 4's browser
test). Nothing else was touched this handoff.


---

### Thirteenth handoff, 2026-08-24

**Thirteenth handoff, 2026-08-24 (new session).** Opened by reading this file, then asked the
operator to pick a starting point from ticket 28's backlog via a 4-option question (`--open`
28.1 / `--limit` on sweep 28.3 / the `render_html` perf issue 28.9 / stop for now). Operator
picked `--open`.

**28.1 DONE, scoped to `ccw render` only.** `notify.open_folder` reveals the folder a capture
landed in; nothing opened the actual rendered page. Read the specimen's own four `--open` sites
(`claude_code_transcripts/cli.py`, stdlib `webbrowser.open`) for the shape, then built the
cc-warehouse equivalent rather than porting it: `notify._open_with_system_default` is now the one
shared platform-opener primitive (R9, the exact C12 pattern ticket 28.13's architecture review had
just recommended), with `open_folder` (existing, reveals a folder) and the new `open_page` (opens
one file) as thin named wrappers. `cli.py` gained `_open_rendered_page`, which picks the archive
folder's `conversation.html` when `archive_root` is configured (mirroring `_reveal_target`'s own
"the archive is the deliverable" precedent) or the personal `projections/` copy otherwise, wired
to a new `--open` flag on both the `--session s:<key>` and ad-hoc forms of `ccw render`.
Best-effort throughout (DESIGN 12): a broken opener can never fail a render.

`ccw share`'s multi-session `index.html` was deliberately left out of this pass to keep the change
small and testable in one sitting; flagged in the ticket's own DONE note as a fast follow-up if
wanted, not attempted here.

8 new oracle tests (`tests/test_render_open.py`), proved red-then-green with a real `git stash` of
just the production diff (7 of 8 failed pre-fix; the 8th, a pre-existing typo-guard regression
test, was correctly unaffected). One test written for a third scenario -
`keep_projections=false` with no `archive_root`, meant to prove `--open` is a silent no-op with
nothing to open - was dropped after measuring that `config.py`'s own `_keep_projections` refusal
makes that combination unreachable: it silently falls back to `keep_projections=True` rather than
ever leaving a session with nowhere to render. The no-op branch in `_open_rendered_page` stays as
defensive code, not something a real config can trigger. Full suite: 1,163 passed, ruff clean,
pyright 0 errors on `src`/`tests`.

Ticket 28's own entry (`harness/tickets/28-backlog.md`) and this file's "Also on record, not
scheduled" section above were both updated in place to mark 28.1 done, rather than left to drift
the way 28.19 did.

One commit, pushed (production + tests + doc updates together, since the change is small).

**What was NOT done:** nothing new opened this part of the handoff. See the continuation directly
below for 28.3, picked next in the same session.


**Same day, continuing the thirteenth handoff.** Asked the operator to pick again from the
remaining backlog via a 3-option question (`--limit` on sweep 28.3 / the `render_html` perf issue
28.9 / stop for now). Operator picked `--limit` on sweep.

**28.3 DONE.** `ccw sweep --limit N` (and `--limit=N`) caps `sweep._walk_source`'s transcript list
to the first N in sorted (path) order - useful for exercising a slice of a source tree that can run
to tens of thousands of files in a real deployment, without walking the whole thing. Applied
identically to a real sweep and to `--dry-run` (one walk implementation, one place the cap lives).
It bounds candidates WALKED, never sessions STORED: the existing already-known skip still applies
on top, and the orphan-object catch-up pass (reads `objects/`, not the source tree) is untouched.
A malformed value (missing, non-numeric, zero, or negative) is a usage error, exit 2, matching
`--source`'s own validation posture - a silent `--limit 0` would look identical to a fresh, empty
warehouse. Narrowing a run loses nothing: a later unlimited sweep still picks up whatever a limited
one left behind, the same property `--since`/`--until` already have.

12 new oracle tests (`tests/test_sweep_limit.py`), proved red-then-green with a real `git stash` of
just the production diff (8 of 12 failed pre-fix; the other 4, the usage-error tests, were already
satisfied by the pre-existing "unrecognised option" guard before `--limit` was a known flag -
correctly unaffected, not a gap). Full suite: 1,175 passed, ruff clean, pyright 0 errors.

One commit, pushed. Ticket 28's own entry and this file's backlog pointer were both updated in
place.

**What was NOT done:** nothing new opened this handoff. Standing candidates for a future session:
ticket 28's remaining backlog items (28.2, 28.9, 28.10, 28.11, 28.12, 28.14), and `ccw share --open`
as a possible fast follow-up to 28.1's work above.


---

### Twelfth handoff, 2026-08-23

**Twelfth handoff, same day, same session, prompted by the operator's own tip ("you can always use
Herdr to launch a claude code session in a new pane... to do a fresh test without context
pollution") plus three follow-up questions.**

**Herdr verification, not just unit tests.** Split a sibling pane, started a fresh Claude Code
session (`herdr agent start`), ran `/plugin marketplace update cc-warehouse` in it (confirmed:
"Updated 1 marketplace, 1 plugin bumped", and the cache grew a new commit directory,
`~/.claude/plugins/cache/cc-warehouse/cc-capture/<new-hash>/`, already carrying the SessionStart
entry). Started a SECOND, genuinely fresh session and confirmed via the shared hook log
(`~/.claude/logs/ccw-hook.log`) that Claude Code's own SessionStart plumbing - not a manual script
invocation - actually fired `ccw-freshness-check.py` and logged a fresh, correct "ok" line. Closed
both test panes afterward.

**The operator then asked three questions, all answered by checking live state rather than
assuming:** (1) had the discarded `gz-claude-code-plugins` commit been reverted - no, not yet, but
confirmed harmless (`extraKnownMarketplaces` in `~/.claude/settings.json` has NO entry for that
marketplace at all - fully removed, not just disabled); (2) the full path to `cc-capture` and
whether it is the same one in this repo - yes, source at
`plugins/cc-capture/` here, running copy at
`~/.claude/plugins/cache/cc-warehouse/cc-capture/<commit-hash>/`; (3) what could prevent this exact
mistake from recurring, "not even accidentally".

**Answering (3) surfaced a SECOND real defect, this time in `ccw doctor` itself**, found while
designing the safeguard rather than assumed: `_hook_commands` globbed every plugin's cached
`hooks.json` with no regard for whether Claude Code still had that plugin enabled, so a retired
plugin's leftover cache directory (proven to exist on this exact machine -
`~/.claude/plugins/cache/gz-claude-code-plugins/claude-transcript-exporter/d8107737a5ee/`, and it
even carries Claude Code's OWN `.orphaned_at` marker, timestamp 2026-08-10T10:01:39Z, ~23 minutes
after the ticket 28.19 commit) could still be reported as a working capture hook. Fixed
oracle-tests-first (3 new tests in `tests/test_doctor.py`, proved red against the pre-fix code:
a plugin absent from `enabledPlugins`, one explicitly `false`, and the positive case of one that
really is `true`): `doctor.py` now reads `enabledPlugins` and only counts a plugin-sourced hook when
its exact `plugin@marketplace` key is `true` there, and the `hook` line now NAMES the serving
plugin (`found via cc-capture@cc-warehouse: ...`). Verified against real data via the editable dev
build (`uv run ccw doctor`): correctly ignores the real orphaned `gz-claude-code-plugins` cache and
correctly names `cc-capture@cc-warehouse`. One incidental fix along the way: a docstring using the
word "identical" tripped the R8/F6 guarantee-words fence
(`tests/test_fences.py::test_guarantee_words_cite_their_proving_test`) - reworded rather than
exempted, since the word was decorative prose, not an actual guarantee this function proves.

**A new hard rule went into `CLAUDE.md`** naming `cc-capture@cc-warehouse` as the only live capture
plugin and stating the exact check to run (`enabledPlugins`) before touching any hook file in any
repo. **Two memory files were also written/updated** (outside this repo, in the project's
Claude-memory directory): `ccw-deployment-on-this-machine.md` gained the plugin-migration facts and
the `.orphaned_at` timeline; a new `verify-live-state-before-editing-hooks.md` (type: feedback)
records the general lesson - check a tool's own live enabled-state before editing its
config, never infer it from a repo's docs - for reuse beyond this repo.

**The operator then chose, from a 3-option question, to "clean it up"**: in
`gz-claude-code-plugins`, `git revert --no-edit` undid the discarded commit (history preserved,
nothing force-pushed), and both that repo's top-level README and the plugin's own README gained a
prominent "RETIRED 2026-08-10" notice pointing at `cc-capture@cc-warehouse` in this repo. Both
commits pushed.

Five commits this handoff, all pushed to cc-warehouse: the `_run_hook` skip-reporting fix, the
freshness-check rebuild in the right plugin, the `doctor.py` `enabledPlugins` safeguard, and the
`CLAUDE.md` hard rule (four separate commits from earlier in the day, listed here for completeness)
plus none new to cc-warehouse in this specific handoff beyond what the "24.7 DONE" and
`enabledPlugins` sections above already cover. Two commits pushed to `gz-claude-code-plugins`: the
revert and the retirement-notice docs commit. Full cc-warehouse suite re-confirmed green after
every change this handoff: 1,155 tests, ruff clean, pyright 0 errors.

**What was NOT done:** nothing from items 1-7, or from tickets 24.7/28.13/28.19/28.22/30, remains
open as of this twelfth handoff. The `gz-claude-code-plugins` repo itself was NOT archived on
GitHub - the operator picked the middle option (revert + retirement notice), not the "archive the
whole repo too" option, so that remains available as a future ask if wanted but is not done. The
only standing candidate for a future session is ticket 28's backlog register (28.1, 28.2, 28.3,
28.9, 28.10, 28.11, 28.12, 28.14).


---

### Eleventh handoff, 2026-08-23

**Later the same day (eleventh handoff).** Given a straight choice between ticket 24.7
(session-start capture freshness) and a ticket 28.9 performance fix, the operator picked 24.7,
after first asking to confirm before the change touched a second, live repo (`gz-claude-code-plugins`)
whose `hooks.json` controls what runs at every real SessionStart on this machine - confirmed
before any edit there.

Two fixes landed, one per repo. In cc-warehouse: `_run_hook`'s `CCW_SKIP_HOOK=1` path used to
return 0 with zero record anywhere; it now reports `skipped_disabled` through the same
`notify.report` path `skipped_unchanged` already uses, proved red-then-green
(`tests/test_capture.py::test_kill_switch_reports_skipped_rather_than_silently`).

In the plugin repo: a new `SessionStart` hook, `ccw-freshness-check.py`, registered in
`hooks.json` beside the existing `SessionEnd` capture hook. **A real design correction was
found and fixed before shipping, not after**: the ticket's own wording ("reads ticket 23's gap
figure") reads as "alarm on the Uncaptured: N count", and the first draft did exactly that with
fixed numeric thresholds. Run against this machine's real data, it printed ALERT on a perfectly
healthy install, because that count sits at 250-350 here permanently (old sessions predating the
archive, hidden/warmup sessions) and `doctor.py` itself marks it "ok", never blocking. Rebuilt to
key the alarm on `ccw doctor`'s own PASS/FAIL exit code instead - the same signal `ccw-watch`
already relies on - escalating on consecutive broken session-starts in a row (a streak persisted
in `~/.claude/logs/ccw-freshness-state.json`), with the raw gap figure riding along as context
rather than as the trigger. Verified against real data three ways: the real 298-uncaptured healthy
machine now prints nothing; a simulated 6-session outage (`CCW_BIN` pointed at a fake failing
`ccw`) escalated mild -> WARNING (streak 2-4) -> ALERT (streak 5+); a simulated recovery went
silent and reset to streak 0 immediately.

The plugin repo had no test suite at all before this. Its first test file,
`tests/test_freshness_check.py` (stdlib `unittest`, no new dependency, 14 tests), covers the
escalation tiers, the streak persistence, the `uv tool run` fence (matched narrowly against the
argv-list shape so it does not flag the historical incident documentation already in `ccw-hook.py`'s
own docstring), and a hand-kept mirror of cc-warehouse's `CCW_*` env var list (necessarily
hand-kept, not a live cross-repo import - the two repos share no dependency). All 14 passed. Full
account, including why the fences do not live in cc-warehouse itself (hardcoding a sibling repo's
local path would violate this project's own "no personal machine paths" rule): the "24.7 DONE
2026-08-23" section of `harness/tickets/24-make-capture-work.md`.

Full cc-warehouse suite re-confirmed green after the fix: 1,138 tests, ruff clean, pyright 0
errors.

**CORRECTION, same handoff, found immediately after the operator read the summary above:** the
SessionStart hook had been built and pushed into the WRONG, DEAD plugin. `claude-transcript-
exporter@gz-claude-code-plugins` was already retired - ticket 28.19 had moved the plugin into this
very repo two weeks earlier (2026-08-10, `4b8dde4`, installed as `cc-capture@cc-warehouse`), and
this file's own "Also on record" list and CLAUDE.md's OPEN/next section were both stale about it,
still calling 28.19 open. Proof: `~/.claude/settings.json`'s `enabledPlugins` carries only
`"cc-capture@cc-warehouse": true` - the old slug is not merely `false`, it is absent entirely, and
the plugin cache for it is pinned to a commit from before this session even started.

Redone in the right place: `ccw-freshness-check.py` and the `SessionStart` hooks.json entry now
live in `plugins/cc-capture/hooks/` (this repo), identical logic to the discarded copy. This time
the oracle tests landed inside cc-warehouse's OWN gated suite
(`tests/test_cc_capture_freshness.py`, pytest, 14 tests) instead of a hand-rolled `unittest` file in
a separate repo - the original ticket's "the fences belong in this repo" is now literally true,
since the plugin genuinely is in this repo. One test could not exist in the discarded version at
all: a LIVE check that every `CCW_*` name the wrapper sets is a real name in
`cc_warehouse.config.ENV_VARS`, importing that module directly rather than hand-mirroring its
contents. Verified against real data again in the new location: the real machine (310 chronic
uncaptured, healthy doctor verdict) produces no output and one `"status": "ok"` log line.
**"Left in place rather than deleted" below is STALE as of the twelfth handoff - see that section**;
ticket 28.19's own entry in `harness/tickets/28-backlog.md` was corrected from open to
`DONE 2026-08-10`. Full account: `harness/tickets/24-make-capture-work.md`'s "24.7 DONE" section
and `harness/tickets/28-backlog.md`'s corrected 28.19 entry.

Full cc-warehouse suite re-confirmed green after the correction: 1,152 tests, ruff clean, pyright 0
errors.

**What was NOT done, as of the eleventh handoff:** nothing from items 1-7, or from tickets
24.7/28.13/28.22/30, remained open. Ticket 28.19 was not open either - it was already done, the
record was just wrong. **This was not actually the end of the day - see the twelfth handoff below
for real-data verification via Herdr, a second real defect found and fixed in `ccw doctor` itself,
and cleanup of the discarded repo.**


---

### Tenth handoff, 2026-08-23

**Later the same day (tenth handoff).** Given a straight choice between "incremental collect" and
picking an item from ticket 28's backlog, the operator picked incremental collect. See the
correction inside item 7 above for the full technical account - short version: `collect.py` now
caches each transcript's own scan result in a sibling `scan-cache.sqlite`, keyed by path + size +
mtime, so an unchanged file (almost all of them, once a session ends) is reused instead of being
re-read and re-parsed. A price or timezone change auto-invalidates the whole cache, since both are
baked into every cached row (`cost_usd`, `local_date`/`local_hour`) and an old row would otherwise
keep reporting stale numbers forever. `--no-cache` and `--limit`'s "never overwrite the cache with
a partial slice" behaviour are both new flags/rules, documented in `README.md`.

11 new tests (110 total), each proved red-then-green against a real `git stash` of just the
production changes. Measured on the real archive via a `CCSTATS_OUT` scratch dir (never touching
`~/.cc-warehouse/stats`): 26.9s cold, 7.5s warm with nothing changed - roughly 3.6x. A follow-up
attempt to shave the warm run further (reusing a cache hit's own raw JSON text instead of decoding
then re-encoding it) was tried and measured to make no real difference, so it was reverted in favour
of the simpler, symmetric code rather than kept on the assumption it must help.

One commit, pushed. Full suite re-confirmed green (1,137 main-repo tests, 110 ccstats tests, ruff
clean on both).

**What was NOT done:** item 7 is now fully closed - nothing from items 1-7 remains open. Standing
candidates for a future session, unchanged from the ninth handoff: ticket 24.7 (session-start
capture freshness, partly closed already from outside this repo) and the remaining items in ticket
28's backlog register.


---

### Ninth handoff, 2026-08-23

**Later the same day (ninth handoff).** Given the two remaining candidates, ticket 28.13 (the
architecture board) and ccstats polish, and told to do both, one at a time.

**Ticket 28.13.** The named review skill was not enabled in this session, so 5 parallel read-only
agents substituted for it - the same lens split as the 2026-07-24 review, plus a new lens for
`archive.py`, a 900+ line module that postdates that review entirely and had never been looked at
by this board. Two of the agents' findings were consequential enough to verify first-hand rather
than trust: both turned out to be real, LIVE bugs, not just architecture debt, and were fixed the
same session with oracle tests written first, proved red-then-green against the pre-fix code -
`write_subagent` silently dropping a same-size, content-different re-capture with no record
anywhere (worse than the session-writer twin ticket 30 had just fixed, since sub-agents have no
manifest to record a refusal in), and `ccw share --out` having no guard against writing inside the
warehouse's own store (unlike its `ccw render --out` sibling). The whole board was then re-derived
and re-ranked at HEAD, with the new top recommendation (C12) being exactly the lesson those two
bugs taught: one shared "replace if larger" rule instead of three near-identical copies. Three
commits, all pushed: `d9a2227` (the write_subagent fix), `4824098` (the share guard fix), `e067c8c`
(the board itself).

**ccstats polish.** Split all three flagged long functions (`collect.scan_transcript`,
`facts.compute`, `make_docs.main`) into named helpers, verified byte-identical against real data
before and after every split via `git stash` - a frozen transcript set, the same real
`sessions.sqlite`, and a real `DATA-GUIDE.md` regeneration (which caught and let a real
transcription slip get fixed before it shipped, rather than after). Also re-checked the pinned
model prices against the live pricing page: everything matched except Claude Sonnet 5's active
introductory rate, which the operator chose not to adopt (kept the post-intro steady-state price
instead, recorded in a comment so a future session does not read it as a missed update). One
commit, pushed (`dcac852`). "Incremental collect" (the third flagged ccstats item, a real feature
rather than a cleanup) was left alone, as scoped from the start.

Four commits this half of the session, all pushed: `d9a2227`, `4824098`, `e067c8c`, `dcac852`.
Full suite re-confirmed green after every change (1,124 main-repo tests, 99 ccstats tests, ruff
clean, pyright 0 errors on `src`/`tests`).

**What was NOT done:** nothing from items 1-7, ticket 28.22, or ticket 30's flagged defect remains
open as of this ninth handoff. Standing candidates for a future session: ticket 24.7 (session-start
capture freshness - partly closed already from outside this repo), the remaining items in ticket
28's backlog register, and ccstats' "incremental collect" (item 7's one leftover, a real feature,
not a cleanup - re-reads all ~25k transcripts every run, roughly 25 seconds).


---

### Eighth handoff, 2026-08-23

**Later the same day (eighth handoff).** Given the choice between ticket 30's equal-size defect
(item 4) and ticket 28.22 (item 5) and told to do both, picking which one to start with. Started
with 28.22 (the recommendation, since it was quick and closed a real risk): read `ccw-watch`'s
actual source in `fifty-shades-of-dotfiles` rather than trust this repo's own prior description of
what it depends on, found that description was imprecise (ccw-watch never matches on the word
"hook"), and wrote `tests/test_doctor_external_contract.py` pinning the real, narrower contract by
running ccw-watch's own sed/grep commands against real `ccw doctor` output - verified red-then-green
by mutating the wording it depends on and watching the test catch it. Then ticket 30's equal-size
defect: `write_session_folder` now compares actual bytes (not just size) when an offered payload
matches the archived one's length, taking the same conservative "refuse and record" branch as a
smaller payload when they differ. Verified the SAME way - a real `git stash` of just the production
fix showed every new/changed test fail against the pre-fix code, the end-to-end one with the exact
real-world "JSONL does not match manifest source_hash" symptom, before all passed once restored.

One incidental fix along the way: a doc edit for 28.22 named `fifty-shades-of-dotfiles`'s own
tracked copy of the script by its internal path, which uses that repo's OWN home-dir-mirroring
folder convention, not a real username - but the packaging gate's privacy-scan heuristic (`test_
packaging.py`) reads any slash-separated "home" segment followed by a word as a real user's home
directory, so it went red. Reworded the doc rather than touched the locked scan test.

Four commits, all pushed: `a197853` (PANEL-CONTRACT.md), `f60bc24` (ticket 27.8's decision record),
`32a31a3` (ticket 28.22's fence test), `f7f598c` + `962680a` (the packaging-gate reword and ticket
30's fix, split because the test file landed a commit early by an unintentional `git add` carry-over
- harmless, but worth knowing the history looks that way if anyone reads it later). Full suite
re-confirmed green after every change (1,122 tests, ruff clean, pyright 0 errors).

**What was NOT done:** nothing from items 1-5 remains open as of this eighth handoff. Ticket 28.13
(re-derive the architecture board) and ccstats polish (item 7) are the standing next candidates;
neither started this session.


---

### Seventh handoff, 2026-08-23

**2026-08-23 session (the one that produced this seventh handoff).** Opened by reading this file
(the sixth handoff, above) and asking the operator, in plain language, what to do about the two
threads it left open: the item-3 decision (ticket 27.8) and the item-2 loose end (the panel-contract
doc). The operator first asked for a plain-language explanation of what `keep_objects`/`store.py`
(the vault) vs `archive_root` (the archive folder) actually do before deciding anything on 27.8 -
answered by a sub-agent verifying the real mechanism from source (`config.py:162`,
`capture.py:189-261`, and the 7 specific tests named in the 2026-08-22 ticket-27.8 entry), not from
memory or this file's own prior summary. Given that explanation, the operator chose to KEEP BOTH
(the vault stays as a safety net) - see the correction inside item 3 above. That decision is now
recorded in `CLAUDE.md`, `harness/tickets/27-collapse-to-one-folder.md`, and `contract/DESIGN.md`
section 15; **item 3 has no remaining work and should not be re-opened without a new, explicit
reason.**

Separately, the operator said "write it now" for the panel-contract doc. Read
`dashboard_template.html` and `dashboard.py` directly to write `tools/ccstats/PANEL-CONTRACT.md` -
the data model, every chart/format helper, the house rules from `CHART-BRIEF.md`, and one fully
annotated example panel (Daily) - plus a one-line pointer from `tools/ccstats/README.md`. See the
correction inside the "One loose end" section above; that loose end is CLOSED.

One stale line noticed but NOT fixed, flagged instead: `tools/ccstats/README.md`'s "Scope, stated
rather than hidden" paragraph still says "Top sessions shows the top 50... not 200," but this file's
own item-2 "Fourth round" notes say that panel is 25, not 50, as of 2026-08-22. Out of scope for
this session's actual task; worth a one-line fix next time that file is touched.

**What was NOT done, as of the seventh handoff:** nothing from items 1-3 remains open. The next
real work is whatever the operator picks from "Also on record, not scheduled" below or
`CLAUDE.md`'s OPEN/next section - ticket 30's equal-size payload defect, ticket 28.22, ticket
28.13, or ccstats polish (item 7) are the standing candidates, none started this session.

