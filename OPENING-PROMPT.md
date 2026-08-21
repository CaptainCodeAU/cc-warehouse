# Opening prompt for a fresh session, 2026-08-21 (second handoff of the day)

## Next task: item 1 below. The order is decided; do not re-litigate it.

The operator asked for the remaining work to be ordered and handed over. It is
ordered here. Work down the list. Ask before starting anything NOT on it.

---

## The order, with the reasoning

### 1. Protect `temp/ccstats/` and stop its disk leak  (~45 min)

**Do this first because it is the only item that protects work already done.**

`temp/ccstats/` holds 8 modules and 3 test files, 4,218 lines, built 2026-08-21:
a read-only session-statistics collector, a dependency-free `.xlsx` writer, a
generated data guide, and 72 tests. **`temp/` is in `.gitignore`, so none of it
is in git.** One `rm -rf temp/` and it is gone with no history and no backup.

Two jobs:

- **Move it somewhere tracked.** The operator has NOT chosen where. Two options
  were put to them and the question is still open, so ASK:
  - `tools/ccstats/` - tracked, committed, but outside `src/` so it is not
    subject to pyright strict, the oracle suite or the packaging test. It
    ships nothing, so no contract ruling is needed.
  - `src/cc_warehouse/` as a `ccw stats` verb - the permanent home, subject to
    every gate. **Needs the principal's ruling first**, because
    `contract/BRAINSTORM.md:82` assigns "effort/cost analytics" to `cc-vantage`
    while line 66 keeps "counts, activity timelines, per-project summaries" in
    the warehouse. Raw token counts read from a payload are a warehouse fact;
    the dollar layer is the half that sits across that line. That tension is
    not resolvable in-session.
- **Fix the leak.** `collect.py` renames the previous `sessions.sqlite` to
  `sessions.sqlite.prev` on every run and never removes it. That is **136 MB
  left behind per run**, two full databases on disk forever. Introduced
  2026-08-21 in this repo's own scratch tooling.

Run it end to end before and after, and confirm the numbers do not move:

    uv run python3 temp/ccstats/verify.py snapshot
    uv run python3 temp/ccstats/collect.py --quiet
    uv run python3 temp/ccstats/build_workbook.py --since 2026-06-08
    uv run python3 temp/ccstats/make_docs.py            # inherits the window
    uv run python3 temp/ccstats/check_consistency.py    # inherits the window
    uv run python3 temp/ccstats/verify.py compare
    uv run pytest temp/ccstats/tests -q                 # 72 tests

### 2. Ticket 27.5-27.8, the last open track

**27.1-27.4 are CLOSED**, including the `objects/` delete, re-verified
2026-08-21 (see the ticket; CLAUDE.md and the ticket both claimed the opposite
until then). What remains:

- **27.5** decide whether `root` moves into the archive
- **27.6** re-read the `ccw archive --to` guard
- **27.7** reconcile `ccw verify` with ruling (b)
- **27.8** retire `store.py`

**27.8 may now be much smaller than written.** `keep_objects=false` is live and
`objects/` is gone, so `store.py`'s object surface has no callers left on the
capture path. MEASURE that before planning; do not assume it.

**27.9 IS WITHDRAWN AND STAYS WITHDRAWN.** Nothing is ever deleted from
`~/.claude`. A satisfied gate is not consent.

### 3. Ticket 30's flagged-for-later: the equal-size payload defect

A real fidelity bug, in ticket 29's family. When a re-captured payload is the
SAME SIZE as the archived one but has different content, the JSONL is correctly
left alone, but `refused` stays False, so the folder's rendered markdown and
HTML describe the NEW payload while the JSONL beside them still holds the OLD
bytes. Mechanism 2 fixed the size-known-different case; this is the equal-size
case. Recorded at the end of `harness/tickets/30-incremental-archive-rebuild.md`.

Correctness of the deliverable beats everything below it.

### 4. Ticket 28.22: fence `ccw doctor`'s text output

`~/.local/bin/ccw-watch` (a DIFFERENT repo, `fifty-shades-of-dotfiles`) runs at
every Claude Code SessionStart and parses `ccw doctor` with a regex: the `hook`
line's wording and the `Uncaptured: N session(s)` figure. **Nothing in this
repo's suite protects that shape**, so a reformat breaks an external consumer
with nothing here going red. Pin the exact substrings a known-external parser
depends on, not the whole output.

Cheap, and this session nearly tripped over `doctor`'s output twice.

### 5. Ticket 28.13: re-derive the architecture board

Now urgent in a way it was not before. **The board's every `file:line` was
derived at master `1517bba`, and that commit no longer exists** - nor
`18fa5be`. Both were lost when the repository was deleted and re-created on
2026-08-10 for the go-public audit (28.20). So the refs are anchored to
nothing and their decay cannot even be measured: `git rev-list 1517bba..HEAD`
does not run. A decay banner recording this now sits at the top of
`cc-warehouse-architecture/SOURCE.md`; the cards are untouched.

The card REASONING still stands. Only the line numbers are dead. The fix is a
fresh review at a live commit, via `/architecture`, never hand-patching refs.

### 6. ccstats polish, once item 1 has made it safe

In rough value order: `--until` (only `--since` exists, so no closed period can
be charted) · split the three long functions (`collect.scan_transcript` 330,
`make_docs.main` 273, `facts.compute` 153) · re-check model prices (pinned at
2026-06-24, every dollar figure drifts) · incremental collect (re-reads all 25k
transcripts every run, ~25 s).

---

## Also on record, not scheduled

- **Ticket 24.7**, session-start capture freshness. Partly closed from outside
  this repo by `ccw-watch`, which this repo does not own or control.
- **Ticket 28**, the backlog register. Still open in it: `--open` (28.1),
  optional secret redaction on personal projections (28.2), `--limit` on sweep
  (28.3), `render_html` costing 74x the payload (28.9), test gaps (28.10),
  markdown/HTML for sub-agents (28.11), re-homing an orphaned sub-agent when
  its parent arrives (28.12), `prefers-color-scheme` for shared pages (28.14),
  move the plugin into this repo (28.19).
- **Ticket 31's inherited open question:** the lock-contention mechanism is
  still UNPROVEN. Debug logging shipped; the retry loop was deliberately not
  written until the real exception is observed. Do not design a fix for an
  unconfirmed cause.
- **Version cuts not started:** v1.1 proper (FTS5 + `ccw search` + HTML archive
  search + `ccw import`/inbox), v1.2 (`ccw mcp`), ticket 19 leftovers (`share`
  19g, and `status`/`relocate`/`project` on archive labels), DESIGN 15 item 7
  (registry backup/export story).

## Two environment facts that will bite

- **`ccw doctor` run from inside this repo reports `editable`, and that is not
  a rule violation.** `.envrc` (tracked 2026-08-21) sources `.venv/bin/activate`,
  so `.venv/bin/ccw` shadows `~/.local/bin/ccw` on PATH and doctor truthfully
  describes the venv copy - not what the hook runs. The install IS frozen.
  Unambiguous check:
  `env -u VIRTUAL_ENV PATH="$HOME/.local/bin:/usr/bin:/bin" ~/.local/bin/ccw doctor`
- **The SSH key drops out of the agent** (ticket 28.15, seen again 2026-08-21).
  `ssh-add -l` reported "no identities" and `git push` failed on access rights.
  Commits `3b284e5` and `a366275` are LOCAL AND UNPUSHED. The operator must run
  `ssh-add` themselves; a session cannot.

## What the previous session did

Built the session-statistics tooling in `temp/ccstats/` (item 1 above), then
reviewed it and fixed what the review found: ten duplicated constants collapsed
to zero, two window implementations collapsed to one, `--since` given real
validation, the export window recorded in a manifest so it is stated once
rather than retyped on three commands, and 72 regression tests added, one per
defect found.

Then corrected two records that disagreed with reality: 27.4's delete (already
run, both documents said pending) and the architecture board's dead anchor.
Tracked `.envrc`, which turned the packaging gate green - the sdist had been
shipping a file git did not track, which is exactly what that test exists to
catch.

**Five defects in the stats tooling were found by an external reviewer, not by
this session.** Every one was real: `elapsed_hours` off by 2.3x because session
intervals were never clipped to the calendar day, a fixed +10 timezone offset
that mis-bucketed 577 sessions recorded under AEDT, hardcoded prose numbers that
disagreed with the live sheets, unfiltered totals mixed with filtered ones, and
`active_hours` documented as compute time when it measures wall time including
idle. The lesson is on the record: verified OUTPUTS are not verified CODE, and
this tooling had six output self-checks and zero tests until the review.
