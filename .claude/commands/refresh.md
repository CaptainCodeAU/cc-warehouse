---
name: refresh
description: Currency + consistency + gap sweep for cc-warehouse. Reconcile the phase/status surface (CLAUDE.md current-phase, README, doc status headers, HARNESS changelog), the ticket-to-test wiring, and the project memory to LIVE ground truth (git, the three gates, the red-for-the-right-reason check, stub inventory) so a future session cannot act on a stale phase note or a broken suite it believes is "red for the right reason". NEVER relitigates a locked contract decision; contradictions are flagged to the principal, not fixed. Computes every moving fact live, so the command itself never goes stale. Manual only.
argument-hint: "[all(default) | audit(report-only) | docs | tickets | memory | gates | claude | fix \"<old-term>\"]"
disable-model-invocation: true
allowed-tools: Bash, Read, Grep, Glob, Edit, Write, Task
---

# /refresh - keep cc-warehouse current, consistent, and deviation-proof

You are running the cc-warehouse **refresh sweep**: reconcile the status + wiring surface to **live
ground truth** so the next session opens on facts, not a stale snapshot. Follow this exactly; do not
improvise a lighter version.

> **This repo is a CONTRACT + an oracle suite + a harness, in that order of authority.** The five
> docs in `docs/` are locked contract; the oracle tests are the contract's executable form; the
> tickets and status prose are the only freely refreshable tier. That ordering decides what this
> sweep may touch (Guardrail 1).

**GOLDEN RULE - compute, don't trust.** Never trust a written count/status/claim - derive it live in
Phase 1, then find the files that disagree. This command hardcodes only stable STRUCTURE (which file
owns which fact), never a value that moves (test counts, red/green split, slice progress, HEAD).

**SECOND GOLDEN RULE - "red" is only healthy when it is red FOR THE RIGHT REASON.** A red pytest run
is the EXPECTED state until the build finishes; the thing to verify is the CAUSE. Failures traced to
`NotImplementedError` / the stub CLI are healthy. A collection error, an import error, or a failure
inside test code itself is a BROKEN TEST: a BLOCKING finding, reported and handed to the operator,
never "refreshed" and never edited-to-pass.

**Mode = `$ARGUMENTS`** (default `all`):
- **`all`** (blank) - full sweep: ground truth, harvest supersessions, staleness + coherence audit,
  surgical apply, re-verify, commit, report.
- **`audit`** / **`dry-run`** - read-only: Phases 1-4, present the drift ledger, then STOP. No edits.
- **`docs`** - CLAUDE.md + README + the docs/ STATUS surface (status headers, changelogs, section 15
  decided list) - status tier only, never contract substance.
- **`tickets`** - harness/tickets/ wiring: oracle-test references, ADJACENT lists, frozen-decision
  blurbs vs the tests, slice progress annotations.
- **`memory`** - the project memory store only.
- **`gates`** - run the three gates + the red-reason classification and reconcile every count/status
  they contradict.
- **`claude`** - the .claude/ tree (commands vs reality, settings hygiene).
- **`fix "<term>"`** - targeted: find every use of one superseded term and fix only the
  current-guidance hits (leave dated history), per the Phase-3 classification.

Treat everything READ-ONLY until Phase 5 (or forever, in `audit`/`dry-run`).

---

## Live signals (auto-probed at invocation - already the truth; files that disagree are stale)

- Now (UTC): !`date -u`
- Git state (branch, HEAD, uncommitted, remote delta if a remote exists): !`R=$(git rev-parse --show-toplevel); echo "branch $(git -C "$R" branch --show-current) | HEAD $(git -C "$R" log --oneline -1) | uncommitted $(git -C "$R" status --porcelain | wc -l | tr -d ' ') | $(git -C "$R" rev-list --left-right --count @{u}...HEAD 2>/dev/null || echo 'no upstream')"`
- Suite shape (cheap counts; the REAL gate run happens in Phase 1): !`R=$(git rev-parse --show-toplevel); echo "test files: $(ls "$R"/tests/test_*.py 2>/dev/null | wc -l | tr -d ' ') | test functions: $(grep -h 'def test_' "$R"/tests/test_*.py 2>/dev/null | wc -l | tr -d ' ') | tickets: $(ls "$R"/harness/tickets/*.md 2>/dev/null | wc -l | tr -d ' ')"`
- Stub inventory = slice progress (a module at 0 with functions is implemented; nonzero = still stubbed): !`R=$(git rev-parse --show-toplevel); for f in "$R"/src/cc_warehouse/*.py; do n=$(grep -c 'raise NotImplementedError' "$f"); [ "$n" -gt 0 ] && echo "$(basename "$f"): $n stubs"; done; echo "(no lines above = zero stubs left anywhere)"`
- Slice DONE annotations (Phase 3 cross-checks each against zero stubs + green ticket tests): !`R=$(git rev-parse --show-toplevel); D=""; for t in "$R"/harness/tickets/*.md; do grep -qE 'DONE 20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]' "$t" && D="$D $(basename "$t")"; done; [ -n "$D" ] && echo "DONE-annotated:$D" || echo "(no DONE annotations yet)"`
- Ticket-to-test wiring (every test file a ticket names must exist; every test file must be owned by some ticket): !`R=$(git rev-parse --show-toplevel); for t in $(grep -rhoE 'tests/test_[a-z_]+\.py' "$R"/harness/tickets/*.md 2>/dev/null | sort -u); do [ -f "$R/$t" ] || echo "MISSING (a ticket cites it): $t"; done; for f in "$R"/tests/test_*.py; do b="tests/$(basename "$f")"; grep -rq "$b" "$R"/harness/tickets/ 2>/dev/null || echo "UNOWNED (no ticket cites it): $b"; done; echo "(no lines above = wiring intact)"`
- Em-dash ban (CLAUDE.md hard rule; the char is built via printf so this file itself stays clean): !`R=$(git rev-parse --show-toplevel); EM=$(printf '\342\200\224'); H=$(git -C "$R" grep -rlI "$EM" -- ':!temp' 2>/dev/null); [ -n "$H" ] && echo "EM-DASH in: $H" || echo "(no em-dashes in tracked text)"`
- Personal-data leak scan (public repo; username + hostname derived live, never written here): !`R=$(git rev-parse --show-toplevel); U=$(id -un); HN=$(hostname -s); H=$(git -C "$R" grep -rlI -e "$U" -e "$HN" 2>/dev/null); [ -n "$H" ] && echo "LEAK candidate in: $H" || echo "(no username/hostname in tracked files)"`
- Phase note vs reality (the currency of CLAUDE.md's "Current phase" is judged in Phase 3 against the counts above): !`R=$(git rev-parse --show-toplevel); sed -n '/^## Current phase/,/^## /p' "$R/CLAUDE.md" | head -12`
- Memory index parity + dangling wiki-links (store lives OUTSIDE the repo; never committed): !`M=$HOME/.claude/projects/$(git rev-parse --show-toplevel | tr '/' '-')/memory; if [ ! -d "$M" ]; then echo "(no memory store yet)"; else T=$(find "$M" -name '*.md' ! -name 'MEMORY.md' | wc -l | tr -d ' '); P=$(grep -cE '\]\([^)]+\.md\)' "$M/MEMORY.md" 2>/dev/null || echo 0); echo "topic files: $T | index lines: $P (should match)"; for l in $(grep -rhoE '\[\[[a-z0-9-]+\]\]' "$M" 2>/dev/null | tr -d '[]' | sort -u); do [ "$l" = name ] && continue; [ -f "$M/$l.md" ] || echo "DANGLING [[${l}]]"; done; fi`

---

## Guardrails (non-negotiable - read first)

1. **The authority ladder decides what /refresh may edit.**
   - **CONTRACT (locked - NEVER edited by this sweep):** the decided substance of `docs/BRAINSTORM.md`,
     `docs/SPEC.md`, `docs/DESIGN.md`, `docs/FINDINGS.md`, `docs/HARNESS.md`, and the role prompts'
     rule bodies. A contradiction or defect found here is FLAGGED in the report as a proposed
     contract edit for the principal (HARNESS section 4); /refresh waits, it does not decide.
     The sanctioned doc writes are STATUS-tier only: appending a dated HARNESS changelog line,
     appending a dated prompt-changelog footer line, and recording an ALREADY-MADE principal
     decision in DESIGN section 15 (append with date + who decided; never reworded later).
   - **ORACLE TESTS (the contract's executable form):** NEVER edited to make code pass or to match
     drifted prose. A test /refresh believes is wrong is a flagged objection for operator triage,
     exactly like an implementer objection.
   - **STATUS tier (freely refreshable):** CLAUDE.md's Current phase, README status prose, ticket
     progress annotations, .claude/ hygiene, memory.
2. **Compute, don't trust.** Every "should be" comes from Phase 1; this file hardcodes no moving value.
3. **CURRENT-GUIDANCE, fix; DATED-HISTORICAL, leave.** A claim presented as true NOW that is wrong
   gets fixed. A dated changelog line, a dated decision, a prompt-footer history line records what
   was true then: leave it. When unsure, leave the history and fix the forward-facing statement.
4. **The specimen is read-only reference** (`~/CODE/CaptainCodeAU/claude-code-transcripts`): never
   swept, never edited, never has its tests ported.
5. **Sources and stored data are out of scope entirely.** The warehouse data root (default
   `~/cc-warehouse-data`) is runtime data, not docs; /refresh never touches it.
6. **Public-repo hygiene is a gate, not a suggestion.** No em-dashes in anything this sweep writes
   (ASCII punctuation); no personal data (username, hostname, personal absolute paths) in any
   tracked file; tests and docs use generic placeholders (alice, /home/alice/...).
7. **Surgical edits only.** Smallest change that makes the fact current. A fix needing genuine
   judgment (a design choice, not a stale number) is surfaced with options + a recommendation,
   never guessed.
8. **Git: stage BY NAME, noreply identity, memory never committed.** `git status` first; never
   `git add -A`/`.` (a parallel session may share the tree). Commit as
   `git -c user.name='CaptainCodeAU' -c user.email='69835039+CaptainCodeAU@users.noreply.github.com'`,
   end messages with the `Claude-Session:` trailer (hooks stamp the `C-` trailers; never hand-add).
9. **Verify every finding yourself.** If a subagent reports drift, re-check it with a direct
   grep/command before fixing; drop what does not survive; note any rejected claim in the report.

---

## Phase 1 - establish LIVE ground truth (read-only; everything reconciles to THIS)

Run only what the selected scope needs; `gates`/`docs`/`tickets`/`all` need the full gate run.

```bash
R=$(git rev-parse --show-toplevel)
uv --directory "$R" run ruff check
uv --directory "$R" run pyright | tail -2
uv --directory "$R" run pytest -q 2>&1 | tail -3          # the counts: X failed, Y passed
# RED-REASON classification (Golden Rule 2): every failure cause must be the stub tier.
# COLUMNS=400 matters: pytest truncates its short summary to the terminal width, and
# the un-widened output bins as unusable fragments (found 2026-07-18, guard below).
COLUMNS=400 uv --directory "$R" run pytest -q --tb=no 2>&1 | grep -E '^(FAILED|ERROR)' \
  | grep -oE ' - .*' | sed 's/ - //' | cut -c1-70 | sort | uniq -c | sort -rn | head -15
```

Hold as truth: ruff/pyright green or the exact errors (a red ruff/pyright is BLOCKING, report it);
the failed/passed split; the failure-cause classes (only `NotImplementedError`, stub-CLI
`Error: not implemented` assertions, and their downstream effects are healthy; anything else, incl.
a collection/import error, is a BROKEN TEST finding); the stub inventory (probe above) as the live
slice-progress map; the ticket/test/function counts; the git state.

## Phase 2 - harvest what was RECENTLY superseded (self-updating; no hardcoded pairs)

Read the newest material and extract OLD -> NEW relationships so the sweep tracks its own era:
- The newest `docs/HARNESS.md` changelog lines (section 8), the newest dated lines in each
  `harness/prompts/*.md` changelog footer, the newest DESIGN section 15 "Decided" entries, and the
  last few `git log --oneline` subjects since the previous sweep.
- Harvest every phrase like "supersedes / retires / replaces / renamed / decided / reversed /
  not X, use Y". Build the OLD -> NEW term list THIS run; hand it to Phase 3. (Example of the class,
  discovered not baked: the license question was "Apache-2.0 vs MIT", decided 2026-07-18 as
  PolyForm Noncommercial 1.0.0; any doc still framing it as open would be stale current-guidance.)

## Phase 3 - staleness sweep (moving claims + superseded terms)

Across CLAUDE.md, README.md, harness/tickets/, and the docs status tier (scope-dependent):
- **Phase currency:** CLAUDE.md's "Current phase" section vs reality (Phase 1 counts + git log).
  Tickets exist = Phase 2 happened; a module with zero stubs and its ticket's oracle tests green =
  that slice is plausibly DONE; the trial-run retro line in HARNESS section 8 tells you whether the
  trial ran. The phase note must say where the project ACTUALLY is. Slice completion is a
  three-way agreement: a dated DONE annotation on the ticket, zero stubs in its module(s), and
  that ticket's oracle tests green; any one present without the others is drift to reconcile.
  Third state: a slice legitimately MID-LOOP (uncommitted implementation in the working tree,
  harness loop not closed) carries a dated IN PROGRESS annotation instead of DONE.
- **Moving counts/claims:** any written test count, ticket count, slice number, "suite is red"
  claim, gate command, or "N stubs" statement that disagrees with Phase 1. README's status
  paragraph must match the live build stage and red/green reality.
- **Ticket wiring:** every ORACLE TESTS entry cites test files (and ids, where named) that exist
  under the live names; ADJACENT BEHAVIORS entries name functions that exist in src; a ticket for a
  finished slice carries a dated DONE annotation rather than reading as pending work.
- **Superseded terms:** for each Phase-2 OLD term, grep and classify every hit per Guardrail 3
  (fix current-guidance, leave dated history).
- **Hygiene:** the em-dash and personal-data probes above must be clean; any hit is a finding with
  the exact file list.

## Phase 4 - coherence + gap checks

- **Contract cross-agreement (FLAG-ONLY tier):** do SPEC verdicts, DESIGN rules, FINDINGS
  verification lines, and the reviewer checklists still agree with each other and with the oracle
  suite's sanctioned lists (e.g. the fence tests' allow-lists vs DESIGN R2/R4 closed lists)? A
  disagreement here is a CONTRACT DEFECT: report it with a proposed edit and stop; never patch
  contract substance from inside /refresh (Guardrail 1).
- **.claude/ coherence:** every file in `.claude/commands/` does what its frontmatter says and is
  current; settings files carry no secrets or machine-specific values; if a README/index ever
  enumerates the commands, it matches reality.
- **Memory:** index parity and dangling links (probe above); dead refs - a memory naming a file,
  function, or flag is verified against the live tree (`test -e` / grep); stale current-state
  claims fixed, dated history left; frontmatter `description:` lines still accurate.
- **Gap discipline:** any gap/inconsistency THIS sweep uncovers is surfaced in the report AND, when
  it is harness-process-relevant, appended as a dated line to HARNESS section 8 in the same run.
  There is no G-register in this repo; the report + HARNESS changelog are where gaps live.

## Phase 5 - APPLY (surgical; skip entirely in `audit`/`dry-run`)

In this order:
- Factual status fixes (auto, unambiguous): the CLAUDE.md phase note, README status prose, stale
  counts, ticket DONE annotations, dead .claude references.
- Append-only records: a dated HARNESS section 8 line for anything process-relevant this sweep
  found or changed; a DESIGN section 15 append ONLY for an already-made principal decision that
  was never recorded (state the date and that the principal decided it).
- Memory (local, unversioned, overwrites unrecoverable - be deliberate): fix current-guidance topic
  files, update `MEMORY.md` index lines, leave dated history.
- NEVER in this phase: contract substance, oracle tests, the specimen, the data root (Guardrails 1,
  4, 5).

## Phase 6 - re-verify

Re-run the three gates. Ruff and pyright must be green (as they were; /refresh edits no src code,
so a new red means /refresh broke something - fix or revert before committing). The pytest
failed/passed split and red-reason classification must be UNCHANGED by this sweep. Re-run the
em-dash and personal-data probes over the files you touched: both clean.

## Phase 7 - commit (skip in `audit`/`dry-run`, or when nothing changed)

Stage the changed tracked files BY NAME; group into logical commits (`docs(refresh): ...`,
`chore(refresh): ...`); noreply identity per Guardrail 8; end each message with the
`Claude-Session:` trailer. Memory is outside the repo - nothing of it is ever staged. Push only if
a remote exists and pushing is the repo's standing practice at that time.

## Phase 8 - report (compact) + self-improving guard

One table: `{stale -> refreshed}` per file · `{flagged for the principal}` (contract defects,
judgment calls, broken tests) · `{tickets: wiring intact / fixed, slices DONE-annotated}` ·
`{memory: fixed vs left-historical, dead refs}` · `{hygiene: em-dash + personal-data clean}` · and
the final GROUND TRUTH (branch · HEAD · ruff/pyright · pytest failed/passed + red-reason verdict ·
stub inventory · ticket count). In `audit`, the same content as a to-do list with no edits made.
**Self-improving guard:** if this run found drift a cheap probe SHOULD have caught, propose the
concrete new probe line for this command; when a probe-catchable drift recurs, ADD the probe
instead of re-proposing it.

---

## Deviation guard - the drifts a future session most often repeats (compute; never trust a value here)

- **Locked means locked.** Contract docs and merged oracle tests are never "fixed" to match code or
  each other by this sweep; the sweep's whole authority is the status tier. Decisions are
  relitigated with the principal or not at all.
- **A red suite is the healthy state until the build lands; the failure CAUSE is the check.** Never
  report bare "N failed" as a problem, and never report it as fine without the red-reason
  classification. The three vacuous-green classes (fence tests, negative-invariant tests, the
  stub's `Error:` contract) are expected pre-implementation greens, not evidence a slice is done.
- **Slice progress is the stub inventory + that ticket's tests going green**, never a prose claim.
  A ticket's dated DONE annotation is itself a claim: it must agree three ways with zero stubs and
  green ticket tests, and the check runs in both directions (annotation without evidence, or
  evidence without annotation, are both findings). Mid-loop is the sanctioned third state: green
  evidence with an uncommitted working-tree diff takes a dated IN PROGRESS annotation, never DONE,
  and the sweep must not stage or commit that in-flight diff.
- **The em-dash and personal-data bans apply to /refresh's own edits first.** This file builds the
  em-dash via printf precisely so it never contains one; keep it that way.
- **Probes must stay backtick-free inside their commands** (a literal backtick inside an inline
  probe truncates it at parse time; build special characters with printf octal escapes).
- **The specimen repo and the warehouse data root are permanently out of sweep scope.**
- **Commit identity is the GitHub noreply, always** - a default-identity commit in this public repo
  is itself a finding (fix with amend only if unpushed, otherwise flag).

## Canonical file map (stable structure; update only when the layout changes)

- Contract (locked): `docs/BRAINSTORM.md` · `docs/SPEC.md` · `docs/DESIGN.md` (rules: section 14;
  decided log: section 15) · `docs/FINDINGS.md` · `docs/HARNESS.md` (changelog: section 8).
- Harness: `harness/prompts/*.md` (role prompts, dated changelog footers) ·
  `harness/tickets/NN-*.md` (work orders; the freely-annotatable tier).
- Executable contract: `tests/` (oracle suite; conftest.py holds the shared helpers).
- Product: `src/cc_warehouse/` (stubs until slices land) · gates: `uv run pytest` ·
  `uv run pyright` (strict via pyproject) · `uv run ruff check`.
- Status tier: `CLAUDE.md` (Current phase) · `README.md`.
- Memory (outside the repo, never committed):
  `$HOME/.claude/projects/$(git rev-parse --show-toplevel | tr '/' '-')/memory/`.

*Keep this command self-maintaining: every moving fact is computed live (the probes + Phase 1), so
it does not rot. Only this stable structure (the file map + the deviation-guard list) needs a human
touch, when the layout changes or a new era-correction lands.*
