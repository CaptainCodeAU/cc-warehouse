---
name: wrap-up
description: End-of-session close-out for cc-warehouse - the "did I actually close this out" pass. Derives this session's real touched set from git (never memory, never a time window), runs the three guards (ruff, pyright, pytest) and quotes their real totals, checks whether a `pyproject.toml` version bump has a matching PUSHED `vX.Y.Z` tag (the exact way a release silently never reaches PyPI - discovered live 2026-09-06), checks a touched `harness/tickets/*.md` carries a dated status update and that `contract/DESIGN.md`/`HARNESS.md` picked up any decision or retro this session owes them, checks OPENING-PROMPT.md's "Next task" still matches reality and routes anything narrative to `harness/HANDOFFS.md` instead, scans the staged diff for a personal path/username before committing, then stages by name, commits, pushes, and tags only what the standing rules already authorize. Not a substitute for `/refresh` (that's the estate-wide ccstats/architecture sweep); this is scoped to THIS session's own work. Manual only.
argument-hint: "[all(default) | check(report-only)]"
disable-model-invocation: true
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# /wrap-up - close the session properly

Run this before ending a session that did real work - a code change, a ticket decision, a
release, a doc correction worth keeping. It exists because of a measured failure mode: on
2026-09-06 a session shipped a real fix, moved a release tag twice, and fixed a PyPI account
setting by hand-holding the operator through it - and every one of those needed the operator to
ask before it got written down anywhere durable. This command is the closing step that session
didn't have.

**Not a lighter `/refresh`.** `/refresh` reconciles the whole ccstats/architecture surface to
live ground truth and is expensive. This asks one smaller question: **did THIS session's work
get written down, gated, and pushed?**

**Modes.** No arg or `all` = do the checks below AND the writes/commit/push/tag. `check` = run
every check and report, change nothing.

**Autonomy.** Mode `all` does the additive, reversible parts without asking - a ticket status
line, a `HANDOFFS.md` entry, a commit, a push. It still asks before anything the standing rules
already gate: moving or deleting an existing tag, and (per the exception written into
`commit-push-tag-workflow` memory) pushing a `vX.Y.Z` release tag when something about the
version bump looks undeliberate rather than routine.

---

## Step 0 - did the last session actually close out?

Cheap, so always run it. Find the most recent OTHER session transcript for this project and
check whether `/wrap-up` ran near its end:

```bash
# Never hardcode this slug (it encodes the real machine path/username) - derive it fresh.
SLUG=$(pwd | sed 's/[^a-zA-Z0-9]/-/g')
TDIR="$HOME/.claude/projects/$SLUG"
for f in $(ls -1t "$TDIR"/*.jsonl 2>/dev/null); do
  case "$f" in *"$CLAUDE_SESSION_ID"*) continue;; esac
  n=$(wc -l < "$f"); [ "$n" -lt 50 ] && continue   # skip companion/remote-control stubs
  printf '%s  lines=%-6s wrap-up=%s\n' "$(basename "$f" | cut -c1-8)" "$n" \
    "$(grep -c '<command-name>/wrap-up</command-name>' "$f")"
done | head -3
```

A marker proves the command was typed, not that it finished - a session can be cut off mid-tool-
call. If the most recent real session shows the marker, confirm it actually produced something
(a commit that session, or a `HANDOFFS.md` entry dated that day). No marker, or a marker with
nothing behind it, is a gap: name the session (date + first user message) and fold anything it
left genuinely undone into this run rather than opening a second ritual.

**This command did not exist before 2026-09-06.** A run that walks back past that date and finds
nothing is expected, not a finding - do not report it as one.

---

## Step 1 - the touched set, derived from git alone

```bash
git status --short                          # uncommitted, including untracked
git log --oneline @{u}..HEAD 2>/dev/null    # committed this sitting, not yet pushed
git diff --name-only @{u}...HEAD 2>/dev/null
git describe --tags --abbrev=0 2>/dev/null
```

If `@{u}` fails (no upstream), use `git log --oneline origin/master..HEAD`. Union all of it into
one list - that is the real touched set for every step below, never what you remember editing.

🛑 **A dirty tree you don't recognise as your own work is a STOP.** Say so and ask; do not fold
it into your commit and do not route around it.

---

## Step 2 - the guards, run fresh, totals quoted verbatim

```bash
uv run ruff check
uv run pyright
uv run pytest -q
```

All three are merge gates per `CLAUDE.md`, so this should be a formality - if it isn't, stop and
fix the cause before anything else here. **Quote pytest's own final line** ("1222 passed"), never
"tests pass". `tests/test_packaging.py` runs inside that suite and is the one that most often
catches something real: it builds an actual sdist and fails on a file git doesn't track, a real
home directory, or a secret shape.

---

## Step 3 - a version bump with no pushed tag is a release that will silently never happen

**This is the step that exists because of last night.** `pyproject.toml`'s `version` field can
change while nobody pushes the matching `vX.Y.Z` tag - and since `.github/workflows/release.yml`
only runs on that tag, PyPI just quietly falls behind with no error anywhere. That happened for
three weeks (0.1.1 on PyPI, 0.1.2 already in `pyproject.toml`) before anyone noticed.

```bash
grep '^version = ' pyproject.toml
git tag -l "v$(grep '^version = ' pyproject.toml | sed -E 's/.*"(.+)".*/\1/')"
```

- **A tag already exists for the current version** - nothing to do.
- **No tag, and the version wasn't touched this session** - not this session's problem to fix,
  but say so plainly rather than silently skipping it: name the gap so it doesn't sit unnoticed
  the way it did last time.
- **No tag, and this session bumped it** - follow `RELEASING.md`'s checklist exactly (gates
  already ran in Step 2; confirm `CHANGELOG.md` has the `## Releases` entry for this version
  BEFORE tagging, per that file's own ordering). Then tag and push per the standing rule in the
  `commit-push-tag-workflow` memory: do this without asking, UNLESS something looks
  undeliberate (no changelog entry, a version bump that reads like an accident) - pause and ask
  only then.
- After pushing, watch the run once (`gh run watch`) rather than assuming: the gate can pass and
  the publish step can still fail for a reason git had nothing to do with (PyPI's trusted-
  publisher link, an account-side setting - see the `pypi-trusted-publisher-recovery` memory).

**Never confuse a release tag with a milestone tag.** `slice-NN` / `ticket-NN` / an ad hoc
descriptive tag record how the software was built and are free to create any time (the standing
cadence rule says tag generously). A `vX.Y.Z` tag publishes a real, irreversible PyPI release the
moment it's pushed - only push one because Step 3 above says a real version bump needs it.

---

## Step 4 - a touched ticket or decision needs its own record

For each `harness/tickets/<nn>-*.md` this session read or worked from: does it carry a dated
status line (DONE, or the specific rows that moved) for what actually happened? A ticket file is
this project's ledger - a change with no entry in it is invisible to the next session that opens
it cold.

If this session made or changed a real decision (not just wrote code to a decision already on
record), does `contract/DESIGN.md` section 15 have the dated entry? If it's a process lesson
about HOW the work went (not what was decided), does `contract/HARNESS.md` section 8 need one -
note that section has been informally superseded by `harness/HANDOFFS.md` since 2026-08-20, so
check which one this project is actually using before assuming the older file is still live.

Ticket file untouched but genuinely stale for OTHER reasons (a status line contradicted by what
this session found) - fix it in place. A ticket that says something false is worse than one that
says nothing.

---

## Step 5 - is OPENING-PROMPT.md still true, and did today's work get written down anywhere?

`OPENING-PROMPT.md` is the first thing a fresh session reads. Its own rules (see its "Keep it
this way" section) are explicit and this command should follow them exactly, not improvise:

- **Only touch its "Next task" / backlog sections if the LIVE status actually changed** - a
  ticket closed, a new blocker found, something that was "next" no longer is. Edit in place;
  it's a snapshot, not a log.
- **If today's work is worth a dated record, add a new entry to the TOP of
  `harness/HANDOFFS.md`** (newest-first) - never narrate it into `OPENING-PROMPT.md` itself. That
  habit is exactly what grew that file to 1,930 lines before the 2026-08-27 split.
- **A genuinely new, task-independent environment gotcha** (not specific to this session's
  ticket) belongs in `harness/GOTCHAS.md`, not either of the above.

```bash
wc -l OPENING-PROMPT.md
```

Say the line count in the report. It was restructured down from 1,930 lines once already - if it
has crept back up past roughly 150-200 lines, say a trim may be due; don't fix it here uninvited.

Also re-read the session for anything raised in prose as "worth doing later" / "still open" /
"not done yet" that has no home yet. Give it one: the ticket's own open-items list, `CLAUDE.md`'s
"OPEN / next" section, or a memory file if it's a fact that should outlive this repo state
(project convention: `~/.claude/projects/<slug>/memory/`, where `<slug>` is this checkout's own
path with `/` replaced by `-` - see Step 0's `SLUG` derivation; never hardcode it - following the
two-level convention already documented there). A caveat that only exists in this transcript
dies with it.

---

## Step 6 - CHANGELOG.md, only for what it actually covers

`CHANGELOG.md` carries two different things and they are not interchangeable: real PyPI
**releases** under `## Releases`, and **build milestones** (the `slice-*`/`ticket-*` tags),
which it deliberately does NOT duplicate - those live in the ticket files and `git show <tag>`.
Ticket work done this session needs its record in Step 4's files, not a CHANGELOG entry. A real
release (Step 3 fired) needs its entry written BEFORE the tag is pushed, per `RELEASING.md`.

---

## Step 7 - before staging: a live scan, not a hardcoded pattern

This is a **public** repo. `CLAUDE.md`'s standing rule is no personal data in it, ever - real
username, machine name, or personal path. Compute the pattern fresh each run rather than typing
it into this file (which would itself leak into a public repo):

```bash
# ^\+[^+] only matches ADDED lines (not the +++ file header, not removed/context lines) -
# this checks what's actually being introduced, not pre-existing content the diff shows for context.
git diff --cached -- . ':!*.lock' | grep -E '^\+[^+]' | grep -F "$(whoami)" \
  && echo "STOP: username found in an added line"
git diff --cached -- . ':!*.lock' | grep -E '^\+[^+]' | grep -E "/Users/[A-Za-z0-9_.-]+/" \
  && echo "STOP: a real macOS home path found in an added line"
```

The test suite's own sanctioned placeholder is `/home/alice` (a Linux-style example path used
inside test fixtures, per `CLAUDE.md`) - it never matches the `/Users/...` pattern above, so it
needs no exception. Anything that DOES match the checks above is a real leak - fix the source
line, never strip it from the diff after the fact.

**Stage by name.** Never `git add -A` or `git add .` - another session may share this tree.
Commit with the project's identity override
(`git -c user.name='CaptainCodeAU' -c user.email='69835039+CaptainCodeAU@users.noreply.github.com'
commit ...`, or rely on the repo's local config if it's already set - check with
`git config user.email` first) and a body that says *why*, not a restatement of the diff. Append
whatever session-attribution trailer line the current system context has given you for this
session - never invent one and never hand-add a `C-*` trailer, those are hook-stamped.

Push immediately once committed - this project's standing rule is not to offer first. Tag a real
milestone if this session's work amounts to one (see Step 3 for the release-tag distinction).

---

## Step 8 - memory, one soft line

If it's been a while since anything in this project's `~/.claude/projects/<slug>/memory/` (see
Step 0) was updated and this session surfaced something durable (a preference, a project fact, a
gotcha), make sure it actually got written - Step 5 already covers that. Beyond that, this step
is a single line, not an action: mention that the MemoryCuration skill exists for a periodic
audit, and stop. Never run it as part of this command.

---

## Step 9 - report back

Plain language, short bullets, written for someone picking this up cold. Use these three states
for anything that could otherwise read as a silent pass:

| State | Means | Never write |
|---|---|---|
| **CHECKED - none found** | The check ran and genuinely found nothing | "clean" with no number |
| **NOT APPLICABLE** | The precondition is false by construction (e.g. no version bump this session) | "n/a" with no reason given |
| **NOT MEASURED** | Couldn't actually run it (tool missing, command failed) | "skipped", or silence |

Cover: Step 0's result; the guard totals verbatim; the release-tag check and what (if anything)
was pushed; which ticket/decision files gained entries; whether `OPENING-PROMPT.md` needed a
correction and its current line count; the CHANGELOG entry if one was written; the secrets scan
result; commit + push confirmation and the tag name if any; anything still open with its trigger;
anything that needs the operator's own action, spelled out exactly. End with one line: the tree
is fully clean, or it explicitly is not and why.

In `check` mode, report the same list as findings and stop - nothing gets written.
