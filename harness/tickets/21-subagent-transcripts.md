# Ticket 21: sub-agent transcripts

DONE 2026-08-03. Commits 3c4c551 (21a) and 0d4a8c0 (21b-21f). Gates: ruff clean,
pyright strict 0 errors, 870 tests. Six slices, all landed the day they were
planned.

## Why this ticket exists

The principal is about to back the archive up to an external drive and clear
`~/.claude`. That reframed every question in it: the warehouse stopped being one
of two copies and became the ONLY copy, so anything not in it dies with the
machine.

Measured before deciding: 1,788 distinct payloads in `~/.claude/projects` were
not in the warehouse at all (376.5 MiB) - 383 real project sessions including
work from that morning, and 1,420 sub-agent transcripts that `sweep` skips by
SPEC 8. A plain sweep would have recovered the 383 and left the rest to be
destroyed.

## FINDINGS, re-derived by execution

1. **A SUB-AGENT IS NOT A SESSION, AND RULING (a) COULD NOT TELL.** Every one of
   the 1,420 real sub-agent files carries a `sessionId`, and the value is THE
   PARENT'S. Ruling (a) - "a file is a session if any entry carries a sessionId" -
   therefore says yes to all of them. Acting on that computes the parent's
   folder, names the payload `<parent-uuid>.jsonl`, lands it in the parent's own
   folder, and lets replace-if-larger OVERWRITE the parent's transcript. At a
   median 192 KB against a session's 3.7 KB that is the COMMON case, not the edge.
   The defect was masked only by the `agent-` skip this ticket removes, so
   relaxing that skip without 21a would have destroyed transcripts. A test
   reproduces it exactly and requires the refusal.

2. **MY DISCRIMINATOR WAS WRONG TWICE, AND A FIXTURE CAUGHT THE SECOND.** "Any
   entry carries an agentId" fails on a main session's `started`/`result` entries
   (173 of each in the corpus) and on a main session that embeds sidechain
   entries. `matrix_session` - built for the sub-agent phase feature - is exactly
   that second shape, and it failed the test I had just written. Only then did I
   measure: in a sub-agent EVERY conversational entry carries the agentId (10,182
   of 10,182); in a main session NONE do (0 of 34,732). Requiring ALL of them
   keeps a sidechain-embedding session a session. Two guesses, then a measurement.

3. **THE PRESERVATION FIGURE REVERSED MY RECOMMENDATION.** I advised leaving
   sub-agents behind, on the reasoning that their answers are already in the
   parent. Measured over 120 of them: 7.3% of their content appears in the
   parent, so 92.7% exists nowhere else. The advice was an assumption wearing a
   recommendation's clothes.

4. **ORDERING IS LOAD-BEARING IN THE SWEEP.** A sub-agent nests inside its
   parent, so the parent must exist first. A single pass in filename order filed
   most sub-agents as orphans purely because they sorted earlier. Two passes:
   sessions, then sub-agents. The hook needs no such care, having just written
   the parent.

5. **ONE SWITCH FOR ONE THING.** The key was first called `sweep_subagents` and
   governed the sweep's walk while the capture path ignored it. A test caught the
   two paths disagreeing about the same setting. Renamed `archive_subagents` and
   honoured in both.

6. **ZERO ORPHANS, AND THE NET WAS STILL BUILT.** 0 of 1,420 sub-agents lack a
   parent in the warehouse; the earlier "1 in 5" was measured against `~/.claude`,
   where some parent FILES were gone though the sessions were captured months
   ago. `_orphaned-subagents/` exists anyway, because it is cheap now and a
   retrofit later.

## Layout

    <root>/<label>/<stamp>_<parent-uuid>/
        <parent-uuid>.jsonl   transcript.md  ...  manifest.json
        subagents/
            <stamp>_<agentId>/
                <agentId>.jsonl
                meta.json

A FOLDER per sub-agent rather than a loose file, decided against the principal's
own lighter proposal and accepted by them: the stated future is markdown and HTML
for sub-agents, and loose files make that day a restructure of every folder in a
13,829-folder archive while folders make it additive.

## Contract amendments

- **SPEC 8**: `agent-*` skipped by default -> `archive_subagents` opt-in, default ON.
- **DESIGN 6**: manifest gains a fourth top-level key, `subagents`.
- **ruling (a)**: a session has a sessionId AND no agentId.
- **R8 fence**: a proof mapping for "identical" in the new naming docstring.

## NOT DONE, recorded

**Markdown and HTML for sub-agents.** The principal's stated future idea. Purely
additive now that each sub-agent has a folder: a config key, a flag, and the
files appear beside the JSONL.

**Re-homing an orphan when its parent later arrives.** Unreachable today (zero
orphans) and it collides with R4 as amended: moving a JSONL means deleting one,
which the rebuild module may never do. It would have to join R4's closed list of
sanctioned external-world writers alongside `relocate` and `migrate --retire`.
Recorded with the constraint so nobody implements it casually.
