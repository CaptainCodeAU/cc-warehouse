# Ticket 22: protect what is unprotected

DONE 2026-08-03, all four items, same day as defined. No product code changed,
so no new tests; gates re-run anyway and clean (ruff, pyright strict 0). Each
item's verification is recorded at the end of this file.

NOT a feature. Four actions that cost minutes and close the two ways the
migration can still lose data before any of it is rescued. No new code, no
tests, no contract change. It runs FIRST because every later ticket assumes
these are already true.

## Why this ticket exists

A read-only investigation on 2026-08-03 established, by execution rather than
recall, that the recovery plan had two holes nobody had named.

**HOLE 1: a tree everyone believed was disposable is the only copy of a third
of the corpus.** `~/CODE/my-claude-code-transcripts` (6.5 GB) is the output of
the retired transcript-exporter plugin. It was described in-session as "dead
weight". It is not:

    distinct session folders there ..................... 7,698
    sessions in NEITHER ~/.claude NOR the archive ...... 4,756
        with the original .jsonl recoverable ........... 4,754   (392.2 MiB)
        html only, payload gone ........................     2
    payload date range ............... 2026-02-14 -> 2026-07-03
    predating the warehouse's first capture (2026-05-01)  4,141

Instrument: distinct UUID folder names under that tree, minus every UUID in
`~/.claude/projects`, minus every UUID in the archive folder names. Deduplicated
after a first pass over-counted 4,756 as 9,541 by walking an internal
`duplicates/` subtree. Dates read from the payloads, not from mtimes (R12).

**HOLE 2: the seven workflow journals have no home.** They live in the vault and
in `~/.claude`, and both are scheduled for deletion. 399.5 KB. They are the only
data in either warehouse tree that is not duplicated somewhere else.

## Work order

- SLICE: protect the unprotected
- GOAL: after this ticket, no accident and no scheduled step can destroy
  anything that exists in only one place.

### 22.1  Record the orphan tree as protected

`~/CODE/my-claude-code-transcripts` joins CLAUDE.md's "do not delete" set
alongside the standing session/transcript rule, with the measurement beside it
so the next reader does not have to re-derive it. Written where a future session
reads it BEFORE acting, not in a ticket it might never open.

### 22.2  Install `ccw` so it exists on PATH

Via the principal's own shell function `uv_tool_install_current_project`
(`~/.zsh_python_functions:1327`), which runs:

    uv tool install --force --editable --python <venv version> .

Preconditions verified 2026-08-03: `pyproject.toml` present (name
`cc-warehouse`), `.venv` present (Python 3.14.3, floor is 3.12), console scripts
`ccw` and `cc-warehouse`, neither name taken on PATH.

EDITABLE is deliberate and matches how the specimen was installed (its uv
receipt records `editable = "/Users/.../claude-code-transcripts"`). Consequence
stated rather than discovered later: a hook then runs whatever is in the working
tree at that moment.

**THIS DOES NOT FIX THE CAPTURE BUG.** The specimen was installed exactly this
way and `uv tool run claude-code-transcripts` still resolved a different
package from PyPI. Installing makes `ccw` exist; ticket 24 makes the hook call
it. Both are required.

### 22.3  Copy the seven workflow journals somewhere safe

Interim home OUTSIDE both warehouse trees. Ticket 25 gives them a permanent one.

**BLAST RADIUS, checked in code before choosing the destination.** The obvious
destination, `<archive>/_not-sessions/`, is WRONG today. `archive.py:783` skips
only `build.RESERVED_LABELS` (`locks`, `catalog.sqlite`, `_orphaned-subagents`)
when walking the tree, so any other top-level folder is walked as a project
label and its children are yielded as session folders. `ccw archive --verify`
would then report them as malformed. Adding a reserved label is a code plus
contract change and belongs to ticket 25, not here.

COPY, never move: moving a JSONL means deleting one, which R4 as amended
forbids outside its closed list. The originals stay until their trees retire.

### 22.4  Correct CLAUDE.md about dual-write

CLAUDE.md's "OPEN / next" section states that "`capture.py` still calls
`store.put`, so every new session lands in the old store and the archive drifts
until someone re-runs the verb by hand". That was true before slice 19k and is
now FALSE. `capture.py:168-169` calls `_archive_source` and
`_archive_subagents_of` unconditionally on the fresh-identity path, and
`_archive_source` writes the archive folder synchronously inside the hook. Three
items the handoff listed as missing are already built: dual-write, sub-agent
capture, and the read half of an index rebuild (`archive.py:647`,
`read_projects`, called by nothing).

Leaving this uncorrected would have had ticket 24 re-implement a shipped
feature.

## Oracle tests

NONE, deliberately. This ticket writes no product code. Its verification is
observational and stated per item in the DONE annotation.

## Contract excerpts

R4 as amended (the rebuild module may delete only what it generated; copy is not
move), R12 (payload-internal timestamps, not mtimes), F9 (sources read-only),
and the CLAUDE.md hard rule that session data is never deleted or mutated.

## Adjacent

`build.py:131` RESERVED_LABELS · `archive.py:783` the session-folder walk ·
`archive.py:647` read_projects · `capture.py:164-169` the dual-write path.

## Process

No gates run because no code changes. CLAUDE.md edits are committed as
`docs(context)`. The install is a machine action with no repo footprint and is
recorded here rather than in a commit.

## DONE, with what was actually verified (2026-08-03)

**22.1** Two paragraphs added to CLAUDE.md's hard rules, naming
`~/CODE/my-claude-code-transcripts` as protected with the measurement and the
instrument beside it, and warning that `~/CODE/claude-code-transcripts` is a
DIFFERENT tree one word away which measured 0 sessions absent from both.

**22.2** Installed via the principal's own function, unmodified:

    uv_tool_install_current_project --no-extras
    -> Installed 2 executables: cc-warehouse, ccw
    -> ~/.local/bin/ccw, version 0.1.0
    -> receipt: editable = "<repo path>", python = "3.14"

Before sourcing `~/.zsh_python_functions` its 1,567 lines were checked for
top-level statements that would RUN on source; only two `compdef` completion
registrations, both inert.

**FINDING, measured immediately after and folded into ticket 24.2.** With `ccw`
now installed editable, `uv tool run cc-warehouse version` returns `0.1.0`,
OUR tool. The same form for `claude-code-transcripts` still returns the PyPI
package and still fails on `hook`. The observable difference is that one name
exists on PyPI and the other does not. **So the form WORKS for us today, and
that is exactly why it is banned:** a call that works now and breaks silently
the day someone registers the name gets adopted first. Same shape as the
original defect, one step earlier.

**22.3** Seven vault objects with no byte-identical archive copy were
re-derived from scratch rather than taken from the prior session's list, and
independently confirmed as journals: every one has `sessionId=False`,
`agentId=True`, and a first entry of `{"type":"started","key":"v2:..."}`.
409,059 bytes total, matching the earlier figure exactly.

Copied to `~/cc-warehouse-journals/` with Python rather than Bash `cp`, so the
operation could refuse rather than overwrite: it aborts if the destination
exists, aborts if the count is not exactly 7, asserts no target file exists
before each write, and re-hashes every file ON ARRIVAL against its source
filename (an object's name IS its sha256). A `PROVENANCE.json` records what,
why, when and the per-file verification. Vault originals confirmed present
afterwards.

DESTINATION CHOICE, and the blast-radius check behind it: the obvious
`<archive>/_not-sessions/` was REJECTED because `archive.py:783` skips only
`build.RESERVED_LABELS`, so any other top-level folder is walked as a project
label and its children yielded as session folders, which would make
`ccw archive --verify` report them as malformed. Adding the label is ticket
25.6.

**22.4** The stale dual-write paragraph in CLAUDE.md replaced with the measured
truth and an explicit note that it was stale, since the supersession is itself
the useful record. Also corrected: three items that list called missing are
already built. The real reason nothing is captured is that nothing invokes
capture.
