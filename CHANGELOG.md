# Changelog

All notable changes to cc-warehouse.

**THE "no releases" NOTE THAT STOOD HERE IS SUPERSEDED (2026-08-09).** It read "There
have been no releases, and none are planned for now" and "nothing is on PyPI", on a
2026-07-24 ruling. `cc-warehouse` 0.1.0 was published to PyPI on 2026-08-09 by a later
principal ruling, so both statements are now false and are replaced rather than left to
mislead the next reader.

This file therefore carries two kinds of entry, and they are not the same thing:

- **Releases**, below, are versions anyone can install with `uv tool install cc-warehouse`.
- **Build milestones** are annotated git tags (`slice-01` .. `slice-17`, `ticket-18` ..
  `ticket-26`) recording how the software was built. They are not installable versions.

Each tag's own annotation carries the full record; `git show <tag>` is the primary source.
The per-slice retros live in `contract/HARNESS.md` section 8, and the decisions in
`contract/DESIGN.md` section 15.

---

## Unreleased

**A failed build names the frame that raised (2026-10-09, W-20261006-A43, `5faa141`).**
The nightly sweep's own build failed one old session on 2026-10-06 and again on 2026-10-09
with a bare `OSError: [Errno 22] Invalid argument`: no path and no call site, so the cause
could not be traced from `capture.jsonl`. A per-item build failure now ends with
`(at <file>:<line> in <func>, via <file>:<line> in <func>)`: the raising frame, plus the
last frame inside `cc_warehouse` when the raiser is outside it. The `<ExcType>: <message>`
prefix is unchanged, so readers keyed on it still match. A read-only scan put both
failures on the READ path (both folders were current, nothing was written).

**ccstats and `recover_hidden_sessions.py` no longer fall back to `~/cc-warehouse-archive`
(2026-10-09, `ca309e5`).** Both read `archive_root` from config and, when it is unset or
the config cannot load, stop with a clear message instead of reading the frozen pre-ticket-44
local tree (or, once it is removed, an empty archive). ccstats also takes the catalog and the
fenced data root from `config.root` (new shared `DATA_ROOT`). Tools only; `ccw` unchanged.

**`ccw sweep` waits for a vanished archive root, then carries on (2026-10-02,
W-20261002-A72).** The archive root is an SMB share on the live machine, and it dropped
four times in six days. The 2026-10-02 02:00 sweep checked the root marker once at
entry; the share went away at 02:31 for three minutes and the run ended with 767 failed
items, one lost `.tmp` write and 766 sub-agents refused with `Permission denied:
'/Volumes/mac'`. Every sweep item that writes into the archive is now checked first,
using `root_problem` (one call cost a median 0.04 ms against the real share, 0.20 ms when
spaced 3 s apart, 30 ms at worst on the first call). A root that is not proven pauses the
run, re-checking every 30 s for up to 15 min, then the run carries on. An item that
failed while the root vanished under it is retried once when the root returns; a failure
with the root still proven is an ordinary failure and never waits. A bare directory or a
marker naming another zone is not proven, so nothing is written into a leftover mount
point. When the root does not return, the run stops with one `sweep stopped:` line
saying when it was lost, why, and how many items were not attempted, and it exits 1 with
no per-item failures, no sweep-triggered build and no coverage record. A recovered pause
is logged once to `capture.jsonl` (status `archive-root-paused`) and counted in the
summary line (`paused N time(s) waiting for the archive root`), and the run exits 0 when
nothing else failed. The build the sweep triggers uses the same check for each head it is
about to write; `ccw build` run by hand is unchanged. Items reported `skipped_unchanged`
pay for no check. Two small side effects: a write failure in the history snapshot or the
paste gather is now a named failed item rather than an exception that ended the sweep,
and the summary's item count no longer counts its own pause or stop outcomes.

**The SessionEnd hook hands the capture to a detached runner (2026-10-01,
W-20261001-A65, folding in W-20260929-A127).** Measured with a `claude -p` probe on
Claude Code 2.1.286: a plugin hook's `timeout` does not raise Claude Code's SessionEnd
budget (only a settings-file hook's does), so `ccw-hook.py` got about 1.5 s, or 10 s in
a pj session, before SIGTERM to its process group killed `ccw hook` mid-capture. 15 of
894 logged runs had started and never finished; two that night reached the archive and
died before their catalog row. The hook now logs `dispatched` and `started`, starts a
copy of itself with `--run` in a new session (stdout and stderr on DEVNULL, payload
through a pipe it closes), and exits 0 at once. The runner runs `ccw hook` with the same
40 s ceiling and logs `ok`, `capture-error` or `error` as before; an unforeseen crash in
it logs `runner crashed` (R10). `started` now carries the SessionEnd `reason` in its own
key; `detail` stays the transcript path, which `ccw doctor`'s `hook runs` check reads.
No new status value. The wrapper's own spoken alerts now follow `CCW_VOICE_URL` when it
is set. Plugin-only change: it reaches a machine through a push and `/plugin` update,
not a `ccw` reinstall.

**Uuid-less sessions are written where they are read (2026-10-01, W-20261001-A56).** A
payload with no `sessionId`, such as a `claude -p` stream-json output, was archived by
the capture hook at `<stamp>_session/session.jsonl` and looked for by every reader at
`<stamp>_session-<short>/`. With `keep_objects = false` there was no vault behind the
read, so `ccw build` failed on each visible one and the nightly sweep exited 1. One
function, `build.session_stem`, now names the folder for every writer and reader, and
`fallback_stem` is a required argument so a caller cannot fall back to a different
default. When the hook supplies a `session_id` and the payload has none, that id names
the folder, matching the catalog row. `ccw doctor`: `overdue` now treats a file whose
exact bytes are cataloged as captured, whatever its file name (it read 8 such files as
overdue forever); the desync sample includes uuid-less heads; and a new `unreadable`
line names uuid-less heads whose JSONL is not at their archive path, failing only for
visible ones. Folders written before the fix are moved by the one-off
`tools/rename_uuidless_folders.py` (dry run by default). No version bump.

**`ccw doctor` reports a `ccw sweep` that started and never finished (2026-09-30,
W-20260930-A28).** A sweep wrote its only capture.jsonl record, the run summary, as it
ended, so a sweep killed mid-run left nothing: the 2026-09-29 12:30 sweep logged items until
12:49 AEST and never wrote its summary after its launchd job was reloaded at 13:57, and
doctor noticed only days later through `overdue`, with no way to say why. `ccw sweep` now
writes a `sweep-started` record, message `sweep started (pid N)`, before it does any work;
the message deliberately avoids the `sweep: ` run summary prefix, so every reader that counts
one summary per invocation is unchanged. A new never-blocking `sweep` line, placed right
after `overdue`, pairs the newest start with any later run summary (a completed run, a
failed one or a lock refusal) and reports a start older than 120 s whose process is gone
while no process holds the sweep lock. The pid is the main witness because `sweep.sweep`
releases its lock before the sweep-triggered build and the coverage scan, so a live sweep on
the share spends a long tail holding no sweep lock. Never blocking, the `companions` posture:
the next sweep redoes the work and `overdue` owns the FAIL. A log from before this change,
with no start line, reads as fine.

**The archive ends on a session's newest payload whatever order captures land in
(2026-09-29, W-20260929-A104; ruling: Gavin, option C).** The capture lock is per payload
HASH, so two captures of one session with different payloads ran at once, and the older one
could decide "no file yet" and write after the newer one finished; the sweep's pre-filter then
skipped the newer source forever and, with the vault retired, the build could not read it.
Reproduced deterministically (the older write paused while the newer capture runs in a second
thread). PREVENT: new `archive.session_lock` holds `locks/archive-<session_uuid>` in the
WAREHOUSE root (local disk) around the replace-if-larger decision and write in both JSONL
writers, `write_source` and `write_session_folder`, which gain a `warehouse_root` keyword;
every caller in `src/` passes it (fenced by a test), and a writer called without one, as the
folder-writer tests do, takes no lock. The lock is the flock from `store.acquire_lock`,
taken only inside the two writers because a flock is not re-entrant; a holder that does not
finish within 30 s makes the waiting writer raise, and its caller's own error path reports
it. REPAIR: for sessions whose catalog holds two or more versions (185 of 31,161 on
2026-09-29), the sweep compares the head's archive JSONL with the source that hashes to the
head and, when the archive copy is SHORTER, re-applies `write_source` (larger wins, same
lock); the new `repaired-archive-jsonl` outcome joins the actions that trigger the
post-sweep build. A missing JSONL or folder is left alone: whether a deleted folder
self-heals is ticket 45's open ruling.

**`ccw doctor` reports a SessionEnd hook that started and never finished (2026-09-29,
W-20260929-A105; ruling: Gavin, "fix all five").** A hook killed mid-capture leaves a
`started` line in `ccw-hook.log` with nothing after it, a half-written `.tmp` in the archive
folder and no catalog row, and doctor stayed green: on 2026-09-29 the installed doctor exited
0 ("capture is working") with two such sessions (f952df5f, fc69613b; 3.2 and 4.0 MB `.tmp`
files on the share). New `doctor._hook_unfinished` pairs each `started` with a later line for
the same session over the dispatch check's 7-day window. A new `hook runs` line WARNS when a
run older than 120 s (the hook's 45 s timeout plus a margin) never finished and its session has
no catalog row, and turns BLOCKING only once a `ccw sweep` has completed after that run (its
run summary in capture.jsonl; a refused sweep does not count) and the session is still
uncaptured (Gavin, 2026-09-29, option 1); a run since captured is clean. Stray `.tmp`
files are found without walking the archive (the session's or its project's catalog label,
then one label listing) and named, never deleted; the next `ccw sweep` re-captures from
`~/.claude`. 0.25 s on the real machine. Measured, read-only: 11 of 775 hook runs since
2026-09-06 never finished; 10 of the 11 were on transcripts of 1.7 MB or more (7 of 94 runs
at 3 MB or more died, against 1 of 442 under 1.5 MB), and finished runs reached 28 s, so
Claude Code's configured 45 s timeout is not what kills them; a shorter kill on some exit
paths is consistent with the data but not proven, because the log does not record the
SessionEnd reason. A hook killed before it writes `started` leaves nothing for this check.

**`ccw render --out` and `ccw share --out` refuse the archive (2026-09-29, W-20260929-A103;
ruling: Gavin, "fix all five").** The ad-hoc `--out` guard covered the warehouse's `objects/`
and `projections/` but not `archive_root`, so `ccw render <jsonl> --out <archive folder>`
exited 0 and overwrote the folder's generated files with a bare manifest, dropping its
sub-agent and companion records; reproduced in a sandbox by plain path, by `..` and through a
symlink. `_out_under_warehouse` now guards `archive_root` too, resolved, and `ccw share --out`,
which shares the guard, is closed with it. The message reads "must not be inside the warehouse
store, projections or archive".

**`ccw relocate` never rewrites the archive or `~/.claude`'s session stores (2026-09-29,
W-20260929-A102; ruling: Gavin, "fix all five").** The content scan string-edits files under
`[relocate].roots` and excluded only the warehouse and `~/.claude/projects`, so a root that
reached `archive_root` or `~/.claude` rewrote archived transcripts, `prompts.jsonl`,
`history.jsonl`, `file-history/`, `todos/` and `paste-cache/`; reproduced in a sandbox, all
six rewritten by one `--apply`. New `relocate._protected` lists every tree the scan must never
touch (warehouse, archive, `~/.claude/projects` and the four session stores, named by the
archiver's own constants), compared resolved; directories are pruned as before and files are
now checked too, since `history.jsonl` sits in a directory that is otherwise in scope. Each
declined tree is named in the plan with "not scanned", like every earlier exclusion. DESIGN
11's scope still works: memory and inventory files under the configured roots are repaired,
including ones under `~/.claude` (the test's control).

**An `archive_root` that overlaps the warehouse root is refused (2026-09-29,
W-20260929-A101; ruling: Gavin, "fix all five").** `ccw build` deletes whatever it did not
expect under `<root>/projections/`, so an archive at or inside the warehouse root could have
archived sessions deleted; reproduced in a sandbox (an archive at `<root>/projections/archive`
lost a session to one build). New `config.layout_problem(archive_root, warehouse_root)`
refuses the two containing each other in either direction, compared resolved so a symlink or
`..` cannot hide it. It is recorded in `config_errors`, and `archive.root_problem` and
`require_root` now take a REQUIRED `warehouse_root` keyword and refuse the layout first, so
every writer (hook, sweep, build, render --session, repair, import, `ccw archive --to`) and
doctor's `archive root` line say the same sentence; a caller cannot skip it by omission
(pyright names any that try). `ccw archive --to` refuses any overlapping target, not only the
warehouse itself. `projections`, `objects` and `logs` join `build.RESERVED_LABELS`, so a
project with one of those names is filed as `_projections` and so on (no real label uses them,
checked 2026-09-29). An existing install with an overlapping layout sees every writer refuse
and doctor FAIL with the move-it sentence; with the vault on, sessions still land in the vault.

**A82, three more rulings (2026-09-29, W-20260929-A82; Gavin).** (1) An unreadable
`manifest.json` HOLDS its folder instead of failing the run: `ccw build`, every sweep and
the weekly `ccw archive --to` skip it (`build.HELD` outcome, `MigrationReport.held`), log a
`writer-held` line (`archive.record_hold`), and exit 0 for that reason alone; build and
the archive job also say `N held for repair` (the sweep's own summary does not). A `writer-held` line opens a refusal in `reconcile.open_refusals`, so
`ccw repair` re-checks the folder every run, counts it in `repair-summary` and raises its
one alert, in or out of its sample. (2) "The sub-agent grew" now means it was APPENDED
to: `archive._appended` needs the file longer AND the sha256 of its first <recorded
bytes> bytes equal to the kept record, wherever growth is explained (the manifest writer
and `folder_is_current` via `kept_subagent_records`, and `FolderProblem.grew`, which
repair reads). A longer file that is not the old bytes plus more is held. (3) Copies set
aside under `_not-sessions/displaced/` are pinned untouchable: `ccw build --rebuild`, a
storing sweep, `ccw archive --to` (with and without `--rebuild`), `ccw archive --verify`,
`ccw repair` and `ccw doctor` leave every byte and mtime there as it was and report
nothing about it, and a second restore of different bytes adds a second copy without
touching the first. `notify.append_log_under` added so a writer with only the warehouse
root (migrate) can log. Tests: `tests/test_a82_held_growth_displaced.py`.

**A82 send-back: six holes in the evidence rules closed (2026-09-29, W-20260929-A82;
ruling: Gavin, "send back", after a five-reviewer sandbox review of 51523da).**
(1) A temp-shaped name (`.<name>.<8 chars>.tmp`, `store.atomic_write`'s own mkstemp, now
`store.is_temp_name`) is never recorded in a manifest, and one an older render recorded
is dropped, not kept; repair reports stray temp files (`repair-stray-temp` log line) and
never deletes them. Before, a render during a companion copy recorded the tmp and the
keep-old rule kept it forever, through `--rebuild`.
(2) The batch-lock excuse covers only files written AFTER the lock was taken
(`doctor.batch_started_at` over `store.lock_acquired_at`, which since the integration with
fix-os-locks is None whenever nobody holds the flock, so a stale lock file excuses
nothing), for doctor and repair alike. Before, a
15:30 repair inside the 12:30 sweep's lock called older damage "pending" every day.
(3) A missing `manifest.json` counts as explained only when every copied file matches its
original in `~/.claude` byte for byte (`archive.copies_match_sources`); an unreadable one
is never replaced by any writer (`archive.ManifestUnreadable`).
(4) Repair explains a changed `prompts.jsonl` or `custom-title.json` (ccw rewrites both),
as the writers already did; a rename during a resume no longer raises a false refusal.
(5) Repair restores a changed or deleted companion file or sub-agent byte for byte from
`~/.claude` when a source file's sha256 equals the manifest's kept record
(`archive.restore_from_sources`), after setting the changed copy aside under
`_not-sessions/displaced/`; with no matching source the folder stays held.
(6) `ccw repair` exits 1 only when repair itself failed. A held folder exits 0 and is
counted in one `repair-summary` log line per run (`open_refusals`, `oldest_refusal_at`),
which the start-up hook reads on its own time clock. Every open refusal is re-checked on
every run, even outside the 25-folder sample, and closes (`repair-refusal-resolved`) only
when its folder verifies clean. Changed tests, each for the ruling it follows: refusals
now exit 0 and change the source so no restore applies; batch-lock tests write after the
lock; the reconciliation ledger helper ignores the new per-run summary line. Tests:
`tests/test_repair_sendback.py`.

**No writer records a changed file as the new truth any more, and `ccw repair` stops
re-rendering over a change it cannot explain (2026-09-29, W-20260929-A82 and A88; ruling:
Gavin, F1, F2 (a), F3).** Verified in a sandbox with the real verbs: `ccw build`, a `ccw
sweep` that stores anything (its build covers the whole archive), the weekly `ccw archive
--to` job and `ccw repair` all re-rendered a folder whose sub-agent or copied companion
file had changed, and the re-render rebuilt the manifest's records from the files on
disk, so the changed bytes became the record and `ccw archive --verify` then reported 0
problems. Three parts:
(F3) The shared manifest writer keeps the OLD record, through one rule read by the writer
and by `folder_is_current` alike (`archive.kept_companion_records`,
`archive.kept_subagent_records`), so all four writers inherit it and a damaged folder is
not re-rendered on every build. A companion file (tool-results, workflows, file-history,
todos, pastes; all written with `write_if_absent`, never rewritten or deleted by ccw)
keeps its old record when it changed or vanished. A sub-agent keeps its old record when
it changed without growing, or vanished; a GROWN sub-agent is adopted, since ccw itself
replaces sub-agents only with larger ones (closes W-20260929-A76). NOT covered, by the
ruling: `prompts.jsonl` and `custom-title.json`. ccw legitimately rewrites both (an
extraction fix, a rename) and nothing in the archive tells that from damage, so a change
to either is still adopted by the next render. A damaged file that a storing sweep can
copy again from an intact, larger source in `~/.claude` is healed by the existing
replace-if-larger rule, which is the right outcome.
(F2 (a)) `ccw repair` re-renders only what `doctor.unexplained` calls explained: a missing
generated file, a payload mismatch whose JSONL hashes to the catalog head (a re-capture),
or a sub-agent that grew. Anything else leaves the folder untouched, whole even when
pages are also missing. It is reported `still broken` and writes an `error` record every
run. (It exited 1 on every run here; SUPERSEDED the same day by the send-back entry
above: a held folder exits 0 and is counted in a `repair-summary` line.) One desktop and voice alert fires per folder and distinct problem set, recorded
as a `repair-refused` line in `logs/capture.jsonl` keyed on (session_uuid, message); its
message starts `repair: `, so the reconciliation ledger never reads it as a capture error.
(F1) While any batch lock is held, a mismatch on a file newer than its manifest is the
batch's own write: repair logs one `pending` line for the folder and does not render,
refuse or alert, exit 0. This is doctor's a60d50d rule, now one function for both
(`doctor.pending_under_lock`), and it reads the file `verify_folder` names on the problem
(`FolderProblem.path`, new) instead of re-deriving it from the message text, so it covers
every file-level shape; doctor's own batch pending widens by the same amount (a sub-agent,
companion or `custom-title.json` newer than its manifest reads pending while a lock is
held, then fails once it is released, as payload and prompts already did).
`doctor._payload_is_head` is the one "hashes to the catalog head" rule doctor's re-capture
pending and repair's refusal both read. Tests: `tests/test_writers_keep_evidence.py` (a
real-verb matrix of the four writers against four kinds of damage, every companion kind
at unit level, the prompts/custom-title limit, A76, and the lock rule) and
`tests/test_repair_refuses_unexplained.py`, every render real.

**The background freshness check was sent back and fixed the same day (2026-09-29,
W-20260929-A93; ruling: Gavin, "send back, keep the background hook").** A review proved four
defects in a sandbox, and each now has a test that fails on 9383200. (1) A check that never
answered started the outage clock: `claude -p` kills async hooks at teardown (177 of 420
recent sessions were headless), and a killed check 2.5 h old turned the next single blip into
a spoken ALERT. Now only a real broken verdict from doctor opens or extends an outage; an
unanswered check logs `unknown` and tells the session, and counts for nothing. (2) A gap
counted as broken: a Friday blip and a Monday blip read as one 64 h outage. Now a failing
check continues an outage only if the previous failing check is under an hour old (about the
p90 gap between session starts), so a spoken alert always rests on three or more failing
checks. (3) A hung check made every pane alert (three panes, three desktop and three spoken
alerts). Now each tier alerts once per outage, recorded in the state file, and only the lock
holder raises anything. (4) A failing launchd job spoke at every session start. Now each job
runs the same clock from when the hook first saw it failing, with its own dedup; a job
launchctl cannot answer about keeps its period. Also new, by the interface agreed with the
repair side: archive folders `ccw repair` refuses to re-render are read from repair's latest
`repair-summary` line and run the same clock from `oldest_refusal_at`; a reminder within 10
minutes of repair's own run waits one check. The 30 minute and 2 hour thresholds are
unchanged. Two follow-up rulings the same day: unanswered checks that run unbroken for 2 hours
raise ONE desktop-only notice (never voice, never an outage), so a doctor that never answers is
not silent forever; and the hook takes the warehouse root from doctor's own `config` line
(pinned against real doctor output in `tests/test_doctor_external_contract.py`) instead of
re-reading config.toml, falling back to CCW_ROOT and then the default only when doctor gave no
answer.

**The SessionStart freshness check runs in the background, runs `ccw doctor` once for many
panes, and escalates on how long capture has been broken (2026-09-29, W-20260929-A93;
rulings: Gavin).** It used to block every session start for as long as doctor took (8 to 24 s
on the share, budget 45 s) and to count broken session starts: two sessions started five
seconds apart at 01:45:19 and 01:45:24 each ran their own doctor and turned one bad moment
into a WARNING. Now `plugins/cc-capture/hooks/hooks.json` marks the entry `"async": true`.
Claude Code's docs and the installed 2.1.284 binary agree on what that means: plain stdout is
dropped, a JSON `additionalContext` reaches the model on its next turn and never the screen,
and `timeout` is not enforced. So the hook prints that JSON, bounds itself with its own 45 s
doctor timeout, and reaches the human only through its existing desktop and voice alerts. The
first failed check stamps `broken_since`; a desktop alert comes at 30 minutes, the spoken one at
2 hours, and the first healthy check clears it. The thresholds come from the real log: across
1,293 checks five session starts span a median 40 minutes (p75 92), so ALERT lands no later
than it did on an ordinary day and a burst of panes can no longer bring it forward. A kernel
`flock` on `~/.claude/logs/ccw-freshness.lock`, inherited by the doctor child, makes concurrent
starts run one doctor and outlives a killed hook, so a doctor hung on the share cannot pile up
copies; a lock held over 5 minutes is reported as an unanswered check. No pid is trusted, so a
dead holder frees the lock. A corrupt or unwritable state file warns at once instead of
restarting the clock; an old count-style state file carries its broken period over. The check
of the three launchd jobs runs only in the lock holder. Only the SessionStart entry changed;
SessionEnd capture stays in the foreground. It reaches this machine only after a push and a
plugin update (docs/operations.md, "Picking up a change to the plugin's hooks").

**Batch and capture locks are kernel flocks the operating system releases when the holder dies
(2026-09-29, W-20260929-A84; ruling: Gavin, "OS-released lock").** A lock used to be an O_EXCL
file holding a PID, trusted through `os.kill(pid, 0)`: a dead holder's PID reused by an
unrelated process read as a live holder forever, and an age rule proposed to fix that could
free a lock whose holder was still running. `store.acquire_lock` now holds `flock(LOCK_EX)` on
`<root>/locks/<name>` for the job's life and keeps the descriptor; `release_lock` removes the
file while still holding it and then closes; an acquirer that wins a flock re-checks that the
path still names its inode. `lock_is_held` asks with `LOCK_SH|LOCK_NB` on an existing file and
never creates one, so doctor and repair can ask "is a batch running" without becoming a
holder; an acquirer retries a would-block for up to a second so a momentary probe never reads
as "busy". New: `store.lock_acquired_at` (the file's mtime, stamped at acquire even when the
PID text cannot be written, or None when nobody holds it), `store.held_lock_names`, and a
non-blocking `ccw doctor` `locks` line naming the locks held right now. Every caller keeps the
same API. The pre-change code survives, labelled PID FALLBACK, only where `fcntl` cannot be
imported. Tests hold a lock the real way through one shared helper,
`conftest.lock_held_elsewhere`, instead of writing a PID. Deploy note in `docs/operations.md`:
reinstall `ccw` only while no lock is held, because old and new builds do not see each
other's locks.

**The read-only share checks run in a bounded thread pool (2026-09-29, W-20260929-A91,
ticket 46 option A step 1; ruling: Gavin).** On SMB over Wi-Fi the archive costs about
50 ms per file opened, one at a time. New leaf module `parallel.py`: `map_reads` (answers
in item order; a worker's exception is handed back and re-raised where the serial code
met it, so it stays that item's failure, R10). `READ_WORKERS = 16` and `READ_CHUNK = 64`
are named constants; one worker starts no pool, so the single-session hook path never
does. In the pool: `build`'s per-head `_head_is_current`, one chunk at a time with the
A58 supersede re-check still first and serial; `doctor._desync_scan` (both `ccw repair`'s
full check and doctor's quick one); the coverage pass (`sidecar_gap`, `paste_gap`); and
`ccw archive --verify`, where a folder whose read raises is now one named problem
("could not be verified: ...") instead of the end of the run. The sweep itself is
unchanged. Every write stays on the main thread in the old order through the old
writers, and the SQLite catalog connection is never shared with a worker. The full verify is weighed by payload size against `READ_BUDGET_BYTES`
(256 MiB): the 8 largest heads checked 16 at a time peaked at 2.4 GB uncapped and 1.98 GB
capped (1.7 GB serial, the 114 MB session alone). Measured on the real share, read-only,
per item, serial against 16 workers: build check 245 to 592 ms against 46 to 86 ms at
normal priority and 5.2 s against 0.97 to 1.27 s under `taskpolicy -d throttle`; coverage
74 against 13.5 ms (throttled 594 against 257 to 297 ms); full verify 339 against 169 ms
(throttled 1,635 against 360 ms). NOT A GAIN, stated plainly: the sweep's read-ahead
measured no speed-up (sub-agents 3.9 s against 4.3 s per item, sidecars 4.2 s against
4.7 s) and was dropped before merge (conductor ruling, option A), because the cost is finding the folder, a scan of the whole label directory per
item (median 2.0 s cold), which parallel reads do not remove (W-20260929-A115). Under
the scheduled jobs' IO throttle a pooled build is still hours, so no scheduled-job
speed-up is claimed from the normal-priority numbers.

**`ccw doctor`'s desync check is a quick presence-and-size check; `ccw repair` keeps the
full hash (2026-09-29, W-20260929-A74; ruling: Gavin, option 1).** Doctor took 47 s and
48 s on the real machine, over the SessionStart freshness hook's 45 s, because
`archive.verify_folder` read and sha256-hashed every file in its 25 sampled folders (118 MB
in 557 opens over SMB on Wi-Fi) and parsed each payload. `verify_folder` now has two depths
over ONE set of rules (R9): with `known=` (a new `archive.KnownPayload` built from the
catalog row: `hidden`, `first_ts`, `session_uuid`, and `size_bytes` for every version of
the session) it compares each recorded file's length by `stat` and opens only
`manifest.json`; without it, it is the full check, unchanged. The two differ in one place,
the matcher (`_size_matches` against `_hash_matches`). A record with no `bytes` (older
manifests) is hashed, never skipped. Doctor's `_desync` uses the quick depth; `desync_detail`,
which `ccw repair` reads, keeps the full one. A re-capture still surfaces: its new JSONL is
longer than the payload the stale manifest names, and the pending rules (ticket 34, a60d50d,
A62's hash clause and pipeline clock) judge it as before. The desync line now ends `(quick
check: present and right size; ccw repair checks hashes)`; the exit code and the
`Uncaptured: <N> session` prefix are unchanged. `_prompts_problems` and
`_custom_title_problems` merged into `_single_file_problems`, and the sub-agent and
companion file listings are each shared by the record writer and the verifier. The F1
fence (`tests/test_fences.py::test_no_size_or_mtime_EQUALITY_anywhere`) gains a one-entry,
function-named exemption for `archive._size_matches`, which screens and never decides
identity; any other size or mtime equality still fails it. Accepted trade-off: a same-size
rewrite passes doctor and is detected by the next daily repair. Repair then used to
re-render over it and erase the evidence; fixed by the W-20260929-A82 entry above.
Measured on the real machine:
`ccw doctor` 7.1 to 9.7 s over five runs against 14.0 to 44.9 s for the installed 0.1.4,
interleaved. Tests: `tests/test_doctor_quick_desync.py`.

**`ccw doctor` no longer FAILs a resumed session while its re-capture is still
rendering (2026-09-29, W-20260929-A62).** Since 78daa4f the hook's render waits for the
companions copy, so a re-capture leaves the folder's new JSONL newer than its old manifest
for the copy-plus-render time, with no batch lock held. Ruling (Gavin, 2026-09-29, option
2, "hash check plus the clock starts when the save finishes"), four parts. (1) A payload
mismatch is excusable only when the JSONL is newer than the manifest AND hashes to the
catalog's current head, so an altered file on a fresh folder stays red. (2) With no lock,
a newer `prompts.jsonl` is never excused: its only writer is `ccw sweep`, under the sweep
lock. (3) doctor's batch-lock check now knows `import`, `migrate`, `relocate` and
`archive` as well as `sweep` and `build`; the test the code comment promised had never
existed and now enumerates every `store.acquire_lock` call site. (4) The render child
appends a `render-done` line to `logs/capture.jsonl`, and a waiting folder reads as
pending while its session's latest pipeline line (the hook's `ok`, `companions-started`,
`companions-done`) has no later `render-done` and is under `_COMPANIONS_GRACE_SECONDS`
(300 s) old. It fails at once after `render-done`, and 300 s after a silent helper's last
line. With no pipeline lines the `captured_at` + 120 s grace still decides. The log is read
only when a sampled folder is waiting with no lock: 1.1 ms for one folder, 7.3 ms for 25,
on a copy of the real 3,092-line log.

**`ccw repair` retracts the empty sessions it had already announced as unrecoverable
(2026-09-29, W-20260929-A61).** The empty-session ruling (A60, below) stopped new
announcements, but the 56 dedup records repair had already appended stayed in the
append-only `logs/capture.jsonl`, so `ccw doctor` kept reporting 56. Ruling (Gavin,
2026-09-29, option b): repair now appends one `unrecoverable-retracted` record, with the
same keys as the record it cancels, for each recorded session that
`reconcile._said_nothing` now calls empty, and `known_unrecoverable_count` /
`known_unrecoverable_uuids` subtract it. The latest record for a uuid decides, so a
session announced again after a retraction is back on record. No line is rewritten or
removed, a second repair appends nothing, no alert is raised, an unreadable history
retracts nothing, and one repair reads `history.jsonl` at most once, shared with the
new-loss check. The doctor count still reads only the ledger. Measured on a copy of the
real ledger: 38 of 56 retract (11 said only `/quit` or `/exit`, 27 had no history rows and
a session-env directory), 18 stay.

**`ccw repair` no longer calls an empty session "permanently unrecoverable"
(2026-09-29, W-20260929-A60).** A session opened and closed without a word never
gets a transcript, but its SessionEnd hook still logs "unreadable transcript", so
`ccw repair` announced 5 such sessions as lost. Nothing was lost. Ruling (Gavin,
2026-09-29, option B): `reconcile.find_unrecoverable` now drops a session whose
every `~/.claude/history.jsonl` row is exactly `/quit` or `/exit` (whitespace
stripped, case kept, no pasted content), and a session with ZERO history rows only
when `~/.claude/session-env/<uuid>` is a directory. Zero rows alone is not enough:
measured the same day, 3,550 real September headless (`sdk-cli`) sessions with
typed prompts had no history rows, while 763 of 770 interactive sessions had a
session-env directory. Every doubt fails toward alerting: no or unreadable
history, a history whose oldest row is not older than the error, or a session-env
that is not a directory. Other slash commands (`/clear`, `/model`) and the bare
word `exit` are outside the ruling and still alert. History is parsed with the
sweep's own `archive.split_history_by_session`. Measured read-only against this
machine's 56 records already on file: 38 would now be silenced (11 `/quit` or
`/exit` only, 27 zero rows with a session-env), 18 still alert, and all 5 from the
reported alert are among the 38. Records already written stay in `capture.jsonl`
(append-only), so `ccw doctor`'s reconcile count does not drop by itself; `ccw
reconcile` stops listing the empty ones.

**The hook's render now waits for the companions copy (2026-09-29).** The hook
spawned the render child and the companions child at the same moment, and the
render child's manifest lists the session folder's companion dirs as they
stand when it runs. Live on 2026-09-28, session 17756a71's manifest recorded a
`file_history` entry under the copier's own tmp name
(`.05ffbee409e8ffe2@v2.uthseyoc.tmp`) and `ccw doctor` FAILed until the next
build. Principal ruling, "copy, then render": with an archive configured the
hook now spawns only the companions child, and that child spawns the render
child on every way out (done, failed, no catalog row, unloadable config). The
hook spawns the render itself when the companions child cannot be started, and
at once when no archive is configured. The render child is unchanged, including
its error-notify path. Accepted cost: the render, and the open-folder reveal it
triggers, now lands after the copy, and a companions child killed outright
leaves its session to the next `ccw repair` or `ccw build`. The
`custom-title.json` fix below stays in place. Pinned by
`tests/test_render_after_companions.py`.

**`ccw build` no longer acts on a head a hook capture superseded during its own
run (2026-09-29, open item W-20260929-A58, ruling option A).** The build reads
the heads once and then works through them, which on the network share takes
over two hours; the SessionEnd hook does not take the build lock, so it can
store a newer version of a session the loop has not reached yet. On 2026-09-28
that turned session 5f32eac9e690 into a reported failure (its archive JSONL was
now 086a07ffdb78's and the vault is retired). Reproduced by execution, with the
race made deterministic in `tests/test_build_stale_heads.py`: with
`keep_objects = true` the stale, smaller payload wrote a misleading
`replace_refused` into the manifest, and with `keep_projections = true` the
end-of-run prune deleted the new head's projection dir, including when the new
version landed after the old head had already been built. Each head is now
re-checked with `catalog.latest_version` (made public; the same ranking as
`build._HEAD_RANK_CTE`) just before anything is done with it, and a superseded
one gets the new non-failure action `superseded`; `ccw build` appends
`, N superseded during this run` to its summary only when N is non-zero, so an
ordinary run's line is unchanged. The prune now also keeps every head current
at prune time, and prunes nothing when that read fails. A re-check that fails
(catalog locked past its 5 s busy timeout) is one failed item, never an aborted
batch (R10). `archive.read_payload`'s refusal is unchanged and remains the
backstop for the sub-second gap between the re-check and the read.

**`ccw doctor` no longer FAILs on a sweep's own not-yet-rendered writes
(2026-09-29).** A hand-run `ccw sweep` against the network share held its build
lock for over an hour between copying a larger payload and `prompts.jsonl` into
five folders and re-rendering their manifests, and the SessionStart freshness
check reported capture broken five times in a row. The ticket 34 pending rule
covered only missing generated files. While a sweep or build lock is held, a
payload or `prompts.jsonl` mismatch whose file is newer than the folder's
manifest now also reads as pending. A file older than its manifest, or any
mismatch with no lock held, still FAILs. Accepted cost: a file altered by
something else during a batch reads as pending until the lock is released. No
rendered byte changes.

**A renamed session no longer fails `ccw doctor` until the next build
(2026-09-29).** The hook spawns the render child and the companions child
together, and `custom-title.json` travelled with the companions child. Live: the
manifest was written at 03:14:25, the title arrived at 03:14:38, nothing
re-rendered, and doctor FAILed "custom-title.json exists but the manifest says
none" for hours. Possible since the title file was first archived (2026-09-10);
20 renamed sessions in the source tree carried one. The hook now copies the
title synchronously, before either child is spawned; the directory sidecars stay
deferred.

**Ticket 44 (2026-09-28): `archive_root` may live on a network share.** Whether this
ships as 0.1.5 or as an in-place reinstall at 0.1.4 is the operator's call at
reinstall time: `renderer_version` is `__version__`, so a bump re-renders every
archive folder (31k, and on the share that is hours), and nothing below changes a
rendered byte. Same reasoning as the ticket 42 entry that follows.

- **44a: an archive root must announce itself.** `archive_root` now carries a marker,
  `_archive-root.json`, holding the pinned `archive_timezone`, and EVERY writer (the
  hook, the companions child, `sweep`, `build`, `render --session`, `archive --to`,
  `import`, `repair`) refuses when it is absent, malformed or names another zone
  (`archive.require_root`, one named exception, one batch-report form). Before this,
  nothing checked that `archive_root` was the tree it was configured as: a leftover
  empty mount directory would have let the hook build a second archive on the boot
  disk with no signal. `ccw archive --to DIR --init` is the one way a marker is
  created; it marks and stops, never builds, and refuses a marker it cannot prove.
  `ccw doctor` gains a BLOCKING `archive root` line that names the exact `--init`
  command. **UPGRADE STEP, once per machine:** run `ccw archive --to <archive_root>
  --init` on the existing tree, or every capture refuses until you do (the next
  sweep recovers them; nothing is lost). Read-only verbs are unchanged, and
  `ccw sweep --dry-run` still predicts a normal run against an unmarked root (open).
- **44b: `ccw doctor` no longer walks the archive.** Measured on the real tree, one
  doctor run made 292,286 filesystem calls under `archive_root` (six full walks of
  31k folders, two of them opening a file per folder), 33.7 s on local disk and an
  estimated 15 to 40 minutes on the SMB share against the SessionStart hook's 55 s
  budget. The archived set, the overdue anchor and the 25-folder recency sample now
  come from the catalog (`doctor._catalog_index`, read-only, R12 kept: payload
  timestamps, never mtime); only those 25 folders are touched on disk, and that
  verify is the honesty control on the catalog (a row whose folder is missing FAILS).
  After: 1,080 calls, 6.4 s. The catalog's session set equalled the walk's on real
  data (31,112 = 31,112).
  - The `Uncaptured:` line in doctor reads `Uncaptured: N session(s) in <src> with no
    catalog row (sub-agents: ccw status)`. The parsed prefix `Uncaptured: N session`
    is unchanged (`ccw-freshness-check.py` is now its only consumer; `ccw-watch`
    stopped calling doctor on 2026-09-07). The sub-agent figure moved to `ccw status`
    until ticket 44d indexes sub-agents in the catalog.
  - The `sidecars` and `prompts` lines stay corpus-wide (ticket 38 ruling (e)) but are
    measured by `ccw sweep` after its post-sweep build, written to
    `<root>/logs/coverage.json`, and doctor prints them `(as of <iso>)`. Before the
    first sweep after upgrading, doctor prints `not measured yet: the next ccw sweep
    writes logs/coverage.json` and stays ok.
- **44c: the desync pending grace keys on capture time.** `_desync`'s 120 s window is
  measured from the catalog's `captured_at`, not the session's own start time in the
  folder name, so a 2020 session swept a minute ago with its render still running
  reads as pending rather than broken. Three tests that meant "old capture" and wrote
  "old session" were re-anchored.
- `pyproject.toml` sdist exclude gained `.worktree`: a worker's git worktree inside the
  repo rode into the sdist (217 members) until the packaging test caught it.

### Earlier, still unreleased (2026-09-09)

Logging-only fixes, deliberately shipped WITHOUT a version bump (2026-09-09, ticket
42 items #2/#3/#7). `render.py`'s `renderer_version` is `__version__`, so bumping the
package version would re-render all 29,700+ archive folders for a change set with no
rendering effect; the frozen install is reinstalled in place at 0.1.4 instead, proven
live by exercising the new records rather than by a version string.

- **Ticket 42 #3**: a sweep item's GRACEFUL capture error (an unreadable transcript,
  a stuck lock -- `capture_transcript` returns this rather than raising, R5/R10) now
  reaches `capture.jsonl`. Before this, the identical failure via the live hook was
  logged and the sweep path was not, so a sweep-discovered loss could never become a
  `reconcile.find_unrecoverable` candidate.
- **Ticket 42 #2**: `ccw sweep` and `ccw build` each write one durable run-summary
  record per invocation, success or failure, regardless of `--quiet` -- mirroring
  `_log_repair_outcome`'s own contract. Before this, a fully-successful scheduled run
  left no trace anywhere. **`ccw archive` deliberately does NOT get one**: found while
  building this that a warehouse-log write would break its "the source warehouse
  stays untouched" contract, pinned by an existing oracle test in
  `test_archive_cli.py`.
- **Ticket 42 #7**: `ccw hook` now prints its real outcome to stdout before returning
  (always 0, SPEC 2.6/F7 unchanged), and `ccw-hook.py`'s wrapper reads it instead of
  deciding ok-vs-error purely on the exit code. Measured 2026-09-09:
  `~/.claude/logs/ccw-hook.log` had never once written `error` for `ccw-hook` in
  1,238 real rows, because a graceful `error` result still exits 0. The wrapper logs
  this as a new status, `capture-error`, kept out of its own voice gate -- `ccw hook`
  already speaks a graceful failure itself. Deploy-order safe in either direction (an
  old `ccw` against the new wrapper, or a new `ccw` against the old wrapper).

### 0.1.4 - 2026-09-08

**More data that was never being archived now is.** `~/.claude` holds several stores
that are siblings of `projects/`, not descendants of any one transcript, so nothing
inside a session directory could ever point at them. Measured before this release:
`file-history/` alone (911 MB, versioned file snapshots) had bytes in no JSONL at all,
and `paste-cache/` had already lost 272 of 2,186 referenced pastes to some unknown
pruning, unnoticed the whole time.

- `~/.claude/file-history/` and `~/.claude/todos/` are now mirrored per session,
  discovered by walking the archive's own catalog rather than scanning `~/.claude`
  (there is no parent transcript directory to scan from). New config key
  `archive_file_history`, default ON.
- `~/.claude/history.jsonl` is backed up whole, byte-for-byte, content-addressed,
  under `_not-sessions/history-jsonl-snapshots/<hash>.jsonl` every sweep. This is the
  backstop: it catches every row, including the ones no session folder can claim.
- Each archived session also gets its own `prompts.jsonl` (a bare content split of
  the whole-file snapshot, sliced by raw line bytes so nothing is re-encoded) and a
  `pastes/` folder holding the `paste-cache/` files that session actually referenced.
- New config key `archive_history_prompts`, default ON, gates the snapshot, the
  split and the paste gather together, since all three come from one read of
  `history.jsonl`.
- New in `ccw status` and `ccw doctor`: a `Prompts:` line reporting how many
  archived sessions have `prompts.jsonl` and how many reference a paste, always
  non-blocking so it can never turn a healthy install red.
- A refused sidecar write (same name, different bytes, per the existing
  never-overwrite rule) is now visible in the sweep's own report for file-history,
  todos, and pastes, not only in the internal audit log.

**Upgrading.** Same mechanism as 0.1.3: the version bump makes every existing
archive folder stale, so the first `ccw build` or `ccw sweep` after upgrading
re-renders the whole tree once. That is the run that populates the new `prompts`
and `pastes` manifest keys. Existing folders raise no verify problems in the
meantime.

### 0.1.3 - 2026-09-08

**Data that was never being archived now is.** Claude Code writes several folders
beside every session transcript. cc-warehouse copied exactly one of them
(`subagents/`) and asked for it BY NAME, so it never noticed the others arriving.

- `tool-results/` has existed since 2026-05-08. Measured on one real corpus before
  this release: 1,067 directories, 2,084 files, 135.7 MB, of which **65.4 MB
  appears in no transcript at all**. That half existed only in `~/.claude`. It is
  now mirrored to `<session>/tool-results/<original relative path>`, nesting kept,
  and listed in `manifest.json` under a new `tool_results` key.
- `workflows/` is archived the same way, under a new `workflows` manifest key.
- `agent-<id>.forked-skill.json` and its marker sibling now travel with their
  sub-agent, like `meta.json` already did.

**The general defect, which is bigger than those two names.** Nothing in the
product ever ENUMERATED what sits beside a transcript, so a new sibling could
appear and the archive would quietly stop being complete. There is now one list of
known names (`sidecars.py`) with a fence asserting every name has a copier and
every copier has a name. Anything else is recorded in a `sidecars.json` notice in
the session folder, reported by a new informational `ccw doctor` line, and
announced once with a desktop notification. The doctor line is NEVER blocking: it
does not move the exit code, so it cannot become a banner nobody reads.

**Three hook-path bugs found while doing it, all fixed.**

- The sub-agent directory was located from the transcript's FILE STEM, so a
  `<uuid>.orphaned-<n>-<hash>.jsonl` transcript found none of its sidecars. It is
  located from the payload's own session uuid now, with the stem as a fallback.
- The sub-agent glob was not recursive, so Workflow-tool sub-agents at
  `subagents/workflows/wf_<id>/agent-*.jsonl` were reached only by the daily sweep.
- `ccw sweep` ran its post-sweep build only when a session had been STORED, and a
  back-fill stores none, so a sweep that copied sidecars would never record them
  in any manifest.

**New config keys**, both defaulting ON: `archive_tool_results` (top level) and
`[notify] desktop_alerts`.

**New in `ccw status`**: a `Sidecars:` line.

**Upgrading.** The version bump makes every existing archive folder stale, so the
first `ccw build` or `ccw sweep` after upgrading re-renders the whole tree once.
That is the run that populates the two new manifest keys. Existing folders raise no
verify problems in the meantime.

### 0.1.2 - 2026-08-18

**Bug fix.** `ccw doctor`'s `hook` check could report the wrong hook as "the
SessionEnd capture hook" and say ok for it.

- `_hook_commands` walked every event key in `hooks{}`, not just `SessionEnd`,
  and `diagnose()` labelled whichever command it found FIRST. An unrelated
  SessionStart command that merely contains the substring "ccw" (a monitoring
  script named `ccw-watch`, say) outranked the real plugin-registered
  SessionEnd hook, because settings.json is scanned before plugin
  `hooks.json` files and its own key order can put SessionStart first. The
  `hook` check would then say ok for the wrong command -- a false green that
  survives the real capture hook being removed entirely. Found 2026-08-18,
  while adding an unrelated SessionStart watcher to a machine already running
  cc-warehouse. `_hook_commands` is now scoped to the `SessionEnd` key only,
  in both settings files and plugin `hooks.json` files. Regression test:
  `test_a_ccw_looking_command_in_another_event_is_not_claimed_as_the_hook`.

### 0.1.1 - 2026-08-09

**Metadata only. No behaviour changed, and no file under `src/` differs from 0.1.0.**
The sole reason this version exists is that PyPI freezes a project's description into
each release, so a rewritten README cannot reach the project page without a new version.

- The README is now written for a reader rather than for the build. It had accumulated
  into a build journal: slice numbers, milestone tags, an exit-review paragraph and a
  self-documented overclaim, with the reader's first question answered last. The build
  record was not deleted, it was left where it belongs, in this file and in `contract/`.
- README links are absolute GitHub URLs. The README doubles as the PyPI
  `long_description`, and PyPI does not resolve relative links, so `](LICENSE)` rendered
  as a dead link on the project page.
- Packaging metadata gained `urls`, `keywords` and classifiers. No `License ::`
  classifier is present on purpose: PEP 639 forbids pairing one with `License-Expression`,
  and `OSI Approved` would additionally be untrue of PolyForm Noncommercial.

### 0.1.0 - 2026-08-09

First publication. The distribution name was unclaimed until this release, which is
itself part of the point: `ccw hook` runs at session end with a transcript on stdin, so
an unclaimed name on a public index is a squatting target. Claiming it closes that.

The sdist ships the contract documents and the harness tickets alongside the code, which
is deliberate. Nothing in it is a credential, and a pre-publication audit of all 1417 git
objects plus the built artifact found no keys, no account name, no machine name and no
personal paths.

---

## Unreleased

### Fixes waiting for the next release cut

- **`ccw doctor` no longer reports a hook ok when the script it names is gone**
  (`03f7921`, 2026-09-07). A false green: the `hook` check matched on the command
  STRING and returned before its own `is_file()` test, so a deleted plugin cache still
  read healthy. Converts a false `ok` into a real FAIL, so doctor's EXIT CODE moves on an
  affected machine. Recorded here because the version was not bumped that day and 0.1.2
  once sat unreleased for three weeks unnoticed; whoever cuts the next version owes this
  a `## Releases` entry. Full reasoning: `contract/DESIGN.md` section 15, 2026-09-07.

### v1.1 flag groups, closed 2026-08-01

The four deferred flag groups, each landing the day it was defined: the per-variant
content matrix (`slice-14`), the HTML chrome initial states plus date locale
(`slice-15`), an opt-in truncation cap (`slice-16`), and a `--since`/`--until` window on
`share` and `sweep` (`slice-17`). Named one by one rather than as a range: the currency
sweep checks that every real tag is named here, and a range satisfies a reader while
leaving the probe correct to complain. A byte-for-byte regression
anchor at `tests/golden/matrix-anchor` pins the four projected files under default
options, so any slice that moves DEFAULT output breaks it on purpose; it has moved twice,
both times by a recorded ruling with the delta measured first.

### Real-data coverage, 2026-08-02 (`ticket-18`, `ticket-20`)

A census of a real 13,836-session corpus found that the suite had been proving the
product against inputs someone imagined rather than inputs that exist.

- **`ticket-18`** Eight entry types and three content-block types rendered nothing and
  incremented no counter: 62,577 entries with `loss: 0` recorded beside them. All of them
  now surface, `result` keeps a sub-agent's returned work in full, `custom-title` outranks
  the model's `ai-title`, and anything the parser does not name renders a marker AND
  increments a new top-level `unrecognised` manifest key. That last part is the durable
  half: the previous census ran once, and Claude Code's format kept moving after it.
- **`ticket-20`** 41,458 of 43,060 thinking blocks arrive empty, because the text stopped
  reaching the JSONL upstream at Claude Code v2.1.69 and it is a model property, not a
  date one. The count now folds into the phase caption the transcript already prints, a
  top-level `withheld` manifest key records it, and `--thinking-withheld` lets the
  operator overrule the display.

### Archive-first layout, 2026-08-02 (`slice-19d`, `slice-19f`)

Six of seven slices. One self-contained folder per session holding the raw JSONL beside
its projections, named `<YYYYMMDD-HHMMSS><offset>_<uuid>` in a config-pinned zone so the
same session yields the same folder on any machine and the migration is idempotent.
`ccw archive` builds or `--verify`s it; `project.json` per project makes the catalog a
genuinely disposable index. Run on the real corpus: 13,829 folders in six minutes, zero
failures, verified with zero problems. **Nothing has been swapped.**

### v1, closed 2026-07-24

Every slice in the `contract/DESIGN.md` section 16 build order landed and carries its
milestone tag. Gates: ruff clean, pyright strict 0 errors, 403 tests, zero stubs.

**Capture and storage**

- Content-addressed immutable object store; identity is sha256 of the payload, never a
  size, a path or a timestamp. Every write is tmp-file plus `os.replace`.
- SQLite catalog and a registry where projects are stable IDs and paths are time-stamped
  alias claims, so a repo move is a metadata edit rather than lost history.
- `ccw hook` (SessionEnd capture), `ccw sweep` (anything the hook missed), `ccw migrate`
  (one-shot legacy import, plus a separate consent-gated `--retire`).

**Rendering**

- Four files per session: `transcript.md`, `transcript.compact.md`, `conversation.html`,
  `conversation.compact.html`, plus a `manifest.json` recording the settings and counts
  that produced them.
- Full exporter-v8.10.1 chrome and complete Claude Code entry-type coverage: ai-title
  titles, sub-agent phases, attachments, slash commands, structured tool output and the
  informational extras, each an independent toggle.
- The HTML copy-as-markdown payloads are byte-equal to the markdown fragments, so the two
  exports cannot drift apart.

**Publishing**

- `ccw share` builds a sanitized static site from copies. Redaction runs on the decoded
  payload; secret-shaped strings abort the share rather than being silently mangled.
  See `docs/sharing-and-redaction.md`.
- Shared pages inline highlight.js and make **no third-party requests**; personal
  projections keep the CDN reference for exporter parity.
- `--EXPOSED` is the one sanctioned unscrubbed publish, gated by a scrubbed-versus-exposed
  comparison, a typed confirmation, and a non-TTY abort.

**Repair and inspection**

- `ccw relocate` repairs the external world after a repo move: plan, backup, apply, verify,
  report, with dry-run as the default.
- `ccw project` (list / show / rename / move / merge), `ccw status`, `ccw verify`,
  `ccw build`, `ccw render`.

**Configuration**

- Two-file layering (XDG then data-root), per-project sections keyed by registry ID,
  `CCW_*` environment variables, and CLI flags, in that precedence order.
  `--no-config` and `--config PATH` bypass the files.

### Build milestones

| Tag         | Date       | What landed                                                      |
| ----------- | ---------- | ---------------------------------------------------------------- |
| `slice-01`  | 2026-07-18 | store module (the harness trial run)                             |
| `slice-02`  | 2026-07-18 | catalog + registry: transactional catalog, claims-based registry |
| `slice-03`  | 2026-07-18 | parser + conversation model                                      |
| `slice-04`  | 2026-07-18 | capture hook + notify                                            |
| `slice-05`  | 2026-07-18 | sweep: capture what the hook missed, orphan adoption             |
| `slice-06`  | 2026-07-18 | transcript.md emitters, full and compact                         |
| `slice-07`  | 2026-07-19 | HTML emitters, full and compact, plus the manifest               |
| `slice-08`  | 2026-07-19 | build/render orchestration; un-stubs the render child            |
| `slice-09`  | 2026-07-19 | status and `ccw verify`                                          |
| `slice-10`  | 2026-07-19 | migrate and retire                                               |
| `slice-11`  | 2026-07-19 | share and redaction                                              |
| `slice-12a` | 2026-07-23 | relocate containers and registry claims                          |
| `slice-13`  | 2026-07-23 | config layering, CLI/help surface, content flags, `--EXPOSED`    |
| `slice-12b` | 2026-07-24 | relocate content rewriting                                       |

`slice-12` has no tag by design: it escalated on 2026-07-19 as the build's only
non-converging loop and was split into 12a and 12b. Its ticket is kept as SUPERSEDED for
the record.

### Notable during v1

- **The v1 exit review found two gaps no test could.** It reconciled the contract against
  the code rather than against the tickets: `ccw project` was implemented one subcommand of
  five (which silently broke per-project configuration, since that feature is keyed by an ID
  only `ccw project show` prints), and the dispatcher accepted an undocumented internal
  verb. Both fixed; the internal-verb concept is now sanctioned and documented.
- **Relocate was the one slice to escalate**, and closing it turned up defects worse than
  their tickets described: a symlinked warehouse or `~/.claude` let it rewrite an immutable
  stored object and a captured transcript, and its backups were produced by a
  locale-dependent, newline-translating read that corrupted a CRLF file and its own backup
  while reporting success. Backups are now proven byte-exact before an original is eligible
  to be touched.
- **A private config reader in three modules** meant `[relocate] roots` and
  `[share] redact_patterns` declared in the XDG tier were ignored. In share that was a
  publish-path leak: a redaction rule the operator set was silently dropped and the content
  it named was published.
