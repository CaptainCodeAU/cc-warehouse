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
rewrite passes doctor and is detected by the next daily repair. OPEN, pre-existing and now
load-bearing: repair then re-renders the folder, which records the changed bytes' hashes in
the manifest, logs "fixed" and exits 0, so the change stops being visible to every check
(docs/operations.md). Measured on the real machine:
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
