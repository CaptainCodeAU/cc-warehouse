---
name: wrap-up
description: End-of-session close-out for cc-warehouse - the "did I actually close this out" pass. Derives this session's real touched set from git, scoped from the session-start commit (HEAD's reflog at the time this session's transcript began) rather than the upstream comparison alone (this machine runs concurrent sessions against the same checkout, which can make "unpushed since upstream" read empty even after real work), runs the three guards (ruff, pyright, pytest) and quotes their real totals, checks whether a `pyproject.toml` version bump has a matching PUSHED `vX.Y.Z` tag (the exact way a release silently never reaches PyPI - discovered live 2026-09-06), checks a touched `harness/tickets/*.md` carries a dated status update and that `contract/DESIGN.md`/`HARNESS.md` picked up any decision or retro this session owes them (or plainly says neither fits and why), uses the handoff lines /pj:wrap-up hands it (HANDOFF.md) and adds the dated record to `harness/HANDOFFS.md`, sends loose ends to the open-items drawer, runs `git-leak-scan --since <session-start-ref>` - this machine's real leak scanner, already wired into the pre-commit hook, over this session's actual commits rather than whatever happens to be staged (this project commits continuously, so staging is usually empty by the time this runs) - before committing, then stages by name, commits, pushes, and tags only what the standing rules already authorize. Not a substitute for `/refresh` (that's the estate-wide ccstats/architecture sweep); this is scoped to THIS session's own work. Typed alone it hands over to /pj:wrap-up, which runs it at its project step; `check` runs direct. Model: invoke it only from /pj:wrap-up's project step, never on your own.
argument-hint: "[all(default) | check(report-only) | from-pj-wrap-up <handoff lines>]"
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
every check and report, change nothing. `from-pj-wrap-up <handoff lines>` = mode `all`, started
by /pj:wrap-up (Step H).

**Autonomy.** Mode `all` does the additive, reversible parts without asking - a ticket status
line, a `HANDOFFS.md` entry, a commit, a push. It still asks before anything the standing rules
already gate: moving or deleting an existing tag, and (per the exception written into
`commit-push-tag-workflow` memory) pushing a `vX.Y.Z` release tag when something about the
version bump looks undeliberate rather than routine.

---

## Step H - hand over to /pj:wrap-up, unless it sent you

Before anything else. One path closes a session, and it is always marked (Gavin, 2026-10-05,
engage #1014): /pj:wrap-up runs this command at its project step, after it has rewritten
`HANDOFF.md` and before its tidy, delivery and push, and it marks the session itself.

**Carry on to Step 0** when any one of these holds:

- The arguments start with `from-pj-wrap-up`. Everything after that word is /pj:wrap-up's
  step 5 handoff lines: keep them for Step 5. The mode is `all`.
- The line `pj:wrap-up hands over to /wrap-up` appears in this conversation after the user's
  last message. Take the handoff lines it gave with it, if any.
- An older /pj:wrap-up (before 2026-10-05) prints no handover line: its step 9 asked "run
  /wrap-up now, or not now" and the user's last message answered now. Never hand back to the
  skill that called you: that is a loop.
- The mode is `check`. It reports and writes nothing, so there is nothing for /pj:wrap-up to
  deliver or mark; it runs direct, at any time. Every other mode hands over.

**Otherwise** (typed alone as `/wrap-up` or `/wrap-up all`, or started by the model): say
"Handing over to /pj:wrap-up; it runs these steps at its project step." Then Read
`~/.claude/pj/skills/wrap-up/SKILL.md` and follow it from its first step, and stop following
this file: /pj:wrap-up comes back to it. (/pj:wrap-up is manual only, so the Skill tool cannot
start it; reading it can.)

This command never runs `pj-wrap done`: /pj:wrap-up marks the session.

---

## Step 0 - did the last session actually close out?

Cheap, so always run it. Find the most recent OTHER session transcripts for this project and
check whether a wrap-up ran near their end. Since 2026-09-29 a session closes with
`/pj:wrap-up` (which runs this command at its project step), so count both, and read pj's own
mark, which /pj:wrap-up's last step leaves only when it finished:

```bash
# Never hardcode this slug (it encodes the real machine path/username) - derive it fresh,
# from the MAIN checkout: a session started in .worktree/<name> keeps its transcript in
# "$SLUG--worktree-<name>", and those are this project's sessions too.
MAIN=$(git worktree list --porcelain 2>/dev/null | sed -n '1s/^worktree //p'); MAIN=${MAIN:-$PWD}
SLUG=$(printf '%s' "$MAIN" | sed 's/[^a-zA-Z0-9]/-/g')
SID="${CLAUDE_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-}}"
[ -n "$SID" ] || echo "no session id: this session's own transcript is not skipped"
find "$HOME/.claude/projects" -maxdepth 2 -name '*.jsonl' \
  \( -path "*/$SLUG/*" -o -path "*/$SLUG--worktree-*/*" \) -exec stat -f '%m %N' {} + 2>/dev/null |
sort -rn | cut -d' ' -f2- | while IFS= read -r f; do
  [ -n "$SID" ] && case "$f" in *"$SID"*) continue;; esac
  n=$(wc -l < "$f" | tr -d ' '); [ "$n" -lt 50 ] && continue   # companion/remote-control stubs
  id=$(basename "$f" .jsonl)
  printf '%s  lines=%-6s wrap-up=%s pj:wrap-up=%s marked=%s  %s\n' "$(printf '%s' "$id" | cut -c1-8)" "$n" \
    "$(grep -cE '"content":"<command-(message|name)>/?wrap-up</command-' "$f")" \
    "$(grep -cE '"content":"<command-(message|name)>/?pj:wrap-up</command-' "$f")" \
    "$([ -e "$HOME/.local/state/pj/wrapped/$id" ] && echo yes || echo no)" \
    "$(stat -f '%Sm' -t '%F %R' "$f")"
done | head -3
```

The two greps are anchored on `"content":"<command-`, the shape a typed command leaves; a plain
grep for the tag also counts every quote of it (this file being read, an agent prompt) and
overcounted 11 to 2 on 2026-10-05. `stat -f` is the macOS form. With no session id the newest
row is probably this session: skip it when its first user message is this conversation's, and
say so.

A marker proves the command was typed, not that it finished - a session can be cut off mid-tool-
call. `marked=yes` is stronger: /pj:wrap-up's last step wrote it. If the most recent real session
shows a marker, confirm it actually produced something (a commit that session, a `HANDOFFS.md`
entry or a `HANDOFF.md` dated that day). No marker, or a marker with nothing behind it, is a
gap: name the session (date + first user message) and fold anything it left genuinely undone
into this run rather than opening a second ritual.

**This command did not exist before 2026-09-06, and `/pj:wrap-up` not before 2026-09-29.** A run
that walks back past those dates and finds nothing is expected, not a finding - do not report it
as one.

---

## Step 1 - the touched set, derived from git alone

**First, find SESSION_START_REF** - the commit `HEAD` was at when this conversation began.
This matters because this machine routinely runs several sessions against the same checkout
at once (see `python-process-resource-limits` memory) - a concurrent session can commit AND
push while you're still working, which makes `@{u}..HEAD` read **empty even after this session
did real work**, because someone else's push already caught the upstream comparison up.
Measured live 2026-09-06: a session's own `@{u}..HEAD` showed nothing partway through its work
for exactly this reason, and the only thing that still showed the real picture was comparing
against the start commit.

Git already recorded it: the HEAD reflog logs every move of HEAD with its time, and this
session's transcript logs when the session began, so `HEAD@{<start time>}` is HEAD as it was
then. No hook is involved. A `C-Sess-Id` commit trailer is not used: this repo sets
`trailers.disable = true` (measured 2026-10-05: 0 of the last 200 commits carry one), and a
hook-stamped marker is absent exactly when a hook was skipped. Nor does it need the "Recent
commits" block, which engage sessions never get.

```bash
SID="${CLAUDE_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-}}"
MAIN=$(git worktree list --porcelain 2>/dev/null | sed -n '1s/^worktree //p'); MAIN=${MAIN:-$PWD}
T=""; [ -n "$SID" ] && T=$(find "$HOME/.claude/projects" -maxdepth 2 -name "$SID.jsonl" \
  -exec grep -o -m1 '"timestamp":"[^"]*"' {} + 2>/dev/null | head -1 | sed 's/.*"timestamp":"//; s/"$//')
SESSION_START_REF="NOT MEASURED"
if [ -n "$T" ]; then
  for d in "$PWD" "$MAIN"; do   # a worktree made after the session began has a shorter reflog;
    # never add -q below: it hides the "only goes back" warning that says so
    r=$(git -C "$d" rev-parse --verify "HEAD@{$T}" 2>&1) || continue
    case "$r" in *"only goes back"*) continue;; esac
    SESSION_START_REF=$r; break
  done
fi
echo "session ${SID:-(no id)} began ${T:-(no transcript found)}; SESSION_START_REF=$SESSION_START_REF"
```

Shell variables do not carry from one Bash call to the next: wherever this file writes
`SESSION_START_REF` below, substitute the sha this block printed.

**NOT MEASURED is reported, never papered over.** It means no session id, no transcript for
it, or a reflog that starts after the session did. Say which in the Step 9 report and name it
unresolved. Fall back to the upstream plus uncommitted work (`@{u}..HEAD` and
`git status --short` below; Step 7 then scans `--since @{u}`, or `--since origin/master` when
there is no upstream) and label every result built on
them a guess. Do not substitute the earliest commit you merely recognize as "probably" this
session's own - a wrong guess here certifies a range that quietly isn't the real one, and looks
identical to a correct one.

```bash
git status --short                              # uncommitted, including untracked
git log --oneline @{u}..HEAD 2>/dev/null        # unpushed right now - can be EMPTY even
                                                 # after real work; see above, don't trust
                                                 # this alone
git log --oneline SESSION_START_REF..HEAD       # everything since this session began,
                                                 # yours and any concurrent session's alike
git diff --name-only SESSION_START_REF...HEAD 2>/dev/null
git describe --tags --abbrev=0 2>/dev/null
```

If `@{u}` fails (no upstream), use `git log --oneline origin/master..HEAD`. Read
`SESSION_START_REF..HEAD` as a union, then split it: commits you actually made this
conversation are the real touched set for every step below. Commits you didn't - a
concurrent session's own, already committed and pushed - are not yours to fold in or
re-document; identify whose they look like (a commit message, a same-day `HANDOFFS.md`
entry) and say so plainly in Step 9 rather than silently absorbing or silently ignoring them.
Never substitute "what I remember editing" for what git actually shows. `HANDOFF.md`, when
/pj:wrap-up's step 5 rewrote it in this conversation, is this session's own: Step 7 commits it.

🛑 **Uncommitted changes you don't recognise as your own work are a STOP.** Say so and ask;
do not fold them into your commit and do not route around them. A concurrent session's own
work that is already cleanly committed and pushed is a different thing - not a stop, just
something to name correctly in the report instead of claiming or re-doing it.

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

**Not every real decision belongs in either file.** A decision that's genuinely cross-project,
purely a process/collaboration call, or otherwise outside `ccw`'s own internal design doesn't
force-fit into `DESIGN.md` section 15 just because a decision was made. Recording it in
`harness/HANDOFFS.md` instead (Step 5) is a legitimate outcome - state plainly that's the call
you made and why, rather than silently picking a home or leaving it in neither.

Ticket file untouched but genuinely stale for OTHER reasons (a status line contradicted by what
this session found) - fix it in place. A ticket that says something false is worse than one that
says nothing.

---

## Step 5 - the handoff, the session log, and anything with no home

Four files, four jobs. Never write the same thing into two of them:

| File | Holds | Written by |
|---|---|---|
| `HANDOFF.md` | the live snapshot: where things stand, the literal next step, decisions waiting, hazards | /pj:wrap-up, rewritten whole at its step 5 (named by `.claude/pj-homes`) |
| `harness/HANDOFFS.md` | the dated session log, newest first: what happened and the evidence | this step |
| `OPENING-PROMPT.md` | hand-written orientation for a fresh session; NOT the queue since 2026-10-02 | by hand only |
| `harness/GOTCHAS.md` | task-independent environment gotchas | this step, when one is new |

- **`HANDOFF.md`: use the lines /pj:wrap-up handed over** (the arguments after
  `from-pj-wrap-up`, or the lines given with its handover line). It wrote that file moments ago;
  do not rewrite it. If nothing was handed over, read the file instead. If this run found
  something that makes a line false (a gate failed, a push did not land), fix that line in place
  and keep the first line exactly `<!-- generated by /pj:wrap-up -->`: without it /pj:wrap-up
  treats the file as hand-written and stops writing it. If the file has lost that marker,
  /pj:wrap-up skipped its step 5 and handed you its proposed lines instead: write them as the
  whole file, first line the marker, at most 60 lines.
- **If today's work is worth a dated record, add a new entry to the TOP of
  `harness/HANDOFFS.md`.** Record what happened and its evidence (commits, measurements,
  rulings). Do not copy the next step, the waiting decisions or the hazards from the handoff
  lines: write "Next: see `HANDOFF.md`" instead, so the two never drift apart.
- **`OPENING-PROMPT.md` is not the queue.** Its "Next task" section says so itself: since
  2026-10-02 the live queue is the open-items drawer and `HANDOFF.md`. Do not add a queue, a
  next step or a narrative to it; fix it only where it now says something false. That narrating
  habit is what grew it to 1,930 lines before the 2026-08-27 split.

```bash
wc -l OPENING-PROMPT.md HANDOFF.md
```

Say both line counts in the report. If `OPENING-PROMPT.md` has crept past roughly 150-200 lines,
say a trim may be due; if `HANDOFF.md` is over 60 lines, say /pj:wrap-up's limit is broken. Do
not fix either here uninvited.

Also re-read the session for anything raised in prose as "worth doing later" / "still open" /
"not done yet" that has no home yet. Give it one: the ticket's own open list when it belongs to
a ticket this session worked, otherwise the drawer, from this checkout:

```bash
open-items --grep "<a few words>"          # already there? /pj:wrap-up step 4 may have filed it
open-items add "<title>" --done-when "<how we will know it is done>"
```

Never a memory file: memory is frozen (D-20260929-A01) and edits under
`~/.claude/projects/*/memory` are denied; `open-items` is the one sanctioned writer of the
drawer that lives there. A caveat that only exists in this transcript dies with it.

---

## Step 6 - CHANGELOG.md, only for what it actually covers

`CHANGELOG.md` carries two different things and they are not interchangeable: real PyPI
**releases** under `## Releases`, and **build milestones** (the `slice-*`/`ticket-*` tags),
which it deliberately does NOT duplicate - those live in the ticket files and `git show <tag>`.
Ticket work done this session needs its record in Step 4's files, not a CHANGELOG entry. A real
release (Step 3 fired) needs its entry written BEFORE the tag is pushed, per `RELEASING.md`.

---

## Step 7 - commit, then a live scan of the whole session before pushing

The order: stage by name and commit (the pre-commit hook scans each commit as it is made), then
the control and the range scans below, then push. Scanning before the commit would leave this
run's own commit outside the range.

This is a **public** repo. `CLAUDE.md`'s standing rule is no personal data in it, ever - real
username, machine name, or personal path. Compute the pattern fresh each run rather than typing
it into this file (which would itself leak into a public repo):

**Use `git-leak-scan --since SESSION_START_REF`, the machine's own real audit tool - do not
hand-roll a grep.** An earlier version of this step used two ad-hoc `grep` patterns
(username, `/Users/` path) against `git diff --cached`. That was wrong twice over: this
project's own standing rule is to commit and push continuously (`commit-push-tag-workflow`
memory), so by the time this step runs staging is almost always empty - the scan checked
nothing and still printed clean, which reads as a pass when nothing was tested. It also only
ever covered two leak categories. `git-leak-scan` (on PATH at `~/.local/bin/git-leak-scan`)
is this machine's real, already-battle-tested scanner: it's the SAME tool already wired into
this repo's pre-commit hook (`~/.config/git/hooks/_audit-chain`, confirmed active - check
`git config leakscan.disable` reads unset), so every individual commit this session made was
already checked once at commit time. This step is the belt-and-suspenders pass over the
WHOLE session's range in one shot, catching anything a `--no-verify` or
`LEAK_SCAN_DISABLE=1` commit slipped past, and it checks far more than username/path: GitHub/
Slack/AWS/OpenAI-shaped tokens, PEM private keys, and phone numbers.

**Prove the instrument before trusting its verdict** - run `--control` first, every time:

```bash
git-leak-scan --control
```

Read the line itself: "tested N of M rules, K disarmed" and every rule reading `FIRED`, none
`NOT TESTED`. A green control proves the SCANNER still works today, not that this session is
clean - the two are separate facts, and this is the same principle behind every other "verify
the instrument, not just the reading" moment in this project's own history. Only once this
comes back clean, count the range, then run the real scan:

```bash
git rev-list --count SESSION_START_REF..HEAD
git-leak-scan --since SESSION_START_REF
```

**A count of 0 means nothing was committed this session, so there is nothing to push:** write the
range scan as NOT APPLICABLE with that count and do not run it (on an empty range it refuses with
exit 2). On a non-empty range, exit 2 is a failure, never a pass.

Range mode prints a denominator line regardless of verdict (e.g. "scanned 20 commit(s), 1339
added line(s) in `<range>`") - **quote it verbatim in the Step 9 report**, the same way
Step 2 quotes pytest's own total, instead of just saying "scanned, clean." The count comes
from the scan that actually ran, so it doubles as proof `SESSION_START_REF` resolved to
something real rather than an accidentally-empty range.

Read its own exit codes, don't guess: **0** clean, **1** a real BLOCK-category hit (stop, do
not commit/push past it - if it's already in a pushed commit, say so explicitly and ask the
operator, a follow-up commit does not un-publish it), **2** it refused to scan at all (an
empty range, or bad usage - treat this the same as a failure, never as a pass). If
`git-leak-scan` isn't on PATH (a different machine, a fresh checkout), fall back to the two
`grep` patterns below against `git diff SESSION_START_REF..HEAD` and say plainly in the
report that the fallback ran, since its coverage is much narrower:

```bash
git diff SESSION_START_REF..HEAD -- . ':!*.lock' | grep -E '^\+[^+]' | grep -F "$(whoami)" \
  && echo "STOP: username found in an added line"
git diff SESSION_START_REF..HEAD -- . ':!*.lock' | grep -E '^\+[^+]' | grep -E "/Users/[A-Za-z0-9_.-]+/" \
  && echo "STOP: a real macOS home path found in an added line"
```

**Three things this scan cannot see, measured directly rather than assumed - one of them needs
an extra command, the other two are accepted limitations to state plainly rather than silently
trust past:**

1. **Commit MESSAGES never appear in any `git diff`.** A token pasted into a commit message
   (or an annotated tag message) scans clean forever - confirmed live: a real GitHub-token-shaped
   string in a commit message scanned exit 0 with `git-leak-scan`, while the same string in file
   content correctly blocked. Run this too:
   ```bash
   T="ghp_$(uv run --no-project python3 -c 'import secrets,string;print("".join(secrets.choice(string.ascii_letters+string.digits) for _ in range(36)))')"
   printf 'token %s\n' "$T" | gitleaks stdin --no-banner >/dev/null 2>&1; echo "control rc=$? (must be 1)"
   git log --format=%B SESSION_START_REF..HEAD | gitleaks stdin --no-banner
   ```
   (the underlying tool directly, since the wrapper has no stdin mode). Non-zero means a hit.
   **The control must exit 1 before the real scan counts, and its token must be RANDOM.**
   `gitleaks stdin` and `gitleaks detect --pipe` behave the same on gitleaks 8.30.1: both
   catch a random 36-character `ghp_` token (exit 1) and both pass a hand-typed
   low-entropy one such as `ghp_aBcD...0123456789` (exit 0), because gitleaks skips
   low-entropy matches. Measured 2026-10-02 after an earlier version of this note blamed
   `--pipe` on the strength of exactly that hand-typed control; a peer session caught it.
   A control that does not fire makes the scan an invalid trial, not a tool defect.
2. **Binary file content is invisible** - `git diff` prints "Binary files ... differ" and nothing
   else, confirmed live with a token embedded in a binary file (exit 0, no mention). This repo's
   own tracked files are all text as of this writing (checked); if that ever changes, this gap
   becomes real.
3. **FIXED upstream, no longer a gap for the common case:** a value added in one commit and
   removed in a LATER commit, both inside the same range, used to be invisible to a two-dot
   diff (`git diff A..B` compares endpoint trees only). `git-leak-scan` now audits ranges via
   `git log -p` (each commit's own diff) instead, so this case is caught - reconfirmed live
   2026-09-06 after the fix shipped. **What's still genuinely invisible, by design**: a value
   added BEFORE the range and removed INSIDE it - that addition never appears in this range's
   commits at all. A scan of this session's RANGE still certifies the range, never the repo's
   full history; that stronger guarantee takes a full-history audit
   (`git-leak-scan --range 4b825dc642cb6eb9a060e54bf8d69288fbee4904..HEAD`, diffing against
   git's empty-tree hash), which is heavier and belongs in `/refresh`'s scope, not here.

Also eyeball Step 1's `git status --short` output for untracked files - they never appear in any
diff either, staged, ranged, or otherwise, until something actually adds them.

The test suite's own sanctioned placeholder is `/home/alice` (a Linux-style example path used
inside test fixtures, per `CLAUDE.md`) - it never matches the `/Users/...` pattern above, so it
needs no exception. Anything that DOES match the checks above is a real leak - fix the source
line, never strip it from the diff after the fact.

**Stage by name** (this is the commit the order above puts first; include `HANDOFF.md` when
/pj:wrap-up rewrote it this session). Never `git add -A` or `git add .` - another session may share this tree.
Commit with the project's identity override
(`git -c user.name='CaptainCodeAU' -c user.email='69835039+CaptainCodeAU@users.noreply.github.com'
commit ...`, or rely on the repo's local config if it's already set - check with
`git config user.email` first) and a body that says *why*, not a restatement of the diff. Append
whatever session-attribution trailer line the current system context has given you for this
session - never invent one and never hand-add a `C-*` trailer, those are hook-stamped.

Push once the scans above are clean - this project's standing rule is not to offer first. Tag a real
milestone if this session's work amounts to one (see Step 3 for the release-tag distinction).

---

## Step 8 - memory: nothing to write

Memory is frozen (D-20260929-A01): this command writes no memory file. A durable fact this
session surfaced goes to the drawer or `harness/GOTCHAS.md` (Step 5). Reading memory, as
Step 3 does, is fine.

---

## Step 9 - report back

Plain language, short bullets, written for someone picking this up cold. Use these three states
for anything that could otherwise read as a silent pass:

| State | Means | Never write |
|---|---|---|
| **CHECKED - none found** | The check ran and genuinely found nothing | "clean" with no number |
| **NOT APPLICABLE** | The precondition is false by construction (e.g. no version bump this session) | "n/a" with no reason given |
| **NOT MEASURED** | Couldn't actually run it (tool missing, command failed) | "skipped", or silence |

Cover: who started this run (Step H: from /pj:wrap-up, or `check` direct); Step 0's result;
SESSION_START_REF and how Step 1 found it (or NOT MEASURED and why); the guard totals verbatim;
the release-tag check and what (if anything) was pushed; which ticket/decision files gained
entries; any line of `HANDOFF.md` this run corrected; whether `OPENING-PROMPT.md` needed a
correction, and both line counts; each item added to the drawer, by id; the CHANGELOG entry if
one was written; the `--control`
result AND the secrets scan's own summary line (both quoted, not summarized as "clean"); commit
+ push confirmation and the tag name if any; anything still open with its trigger; anything that
needs the operator's own action, spelled out exactly. End with one line: the tree is fully
clean, or it explicitly is not and why.

In `check` mode, report the same list as findings and stop - nothing gets written.

When /pj:wrap-up started this run, the report goes back to it and it carries on with whatever
of its steps remain (since 2026-10-05: tidy, delivery check, push, then the session mark; an
older /pj:wrap-up has only the mark left).
