# Ticket 39: archive everything a session points at, not only what it said

Opened 2026-09-07. **PLANNED, NOT STARTED.** The whole file below is the approved plan,
written by a planning session and approved by the operator the same day. The same text
also sits in the gitignored `Plans/well-we-clearly-want-whimsical-dove.md`; this file is
the tracked home.

**HARD DEPENDENCY: ticket 38 must ship first.** 39 reuses `store.write_if_absent` and 38's
notice/doctor/alert scaffolding. Building 39 first would create a second, incompatible
copy of exactly that scaffolding, which is the real duplication risk.

The execution session reads this file, then builds the slices below, oracle tests first.

**TWO OPERATOR RULINGS, 2026-09-07, recorded so they are not re-decided:**

1. **Ticket 38 ships FIRST and UNCHANGED.** It is not merged into 39, not reopened, and
   not rescoped to absorb any of this. Its approval and its red team were sized to its
   own attack table, and that is worth more than the convenience of one ticket.
2. **Start 39 at slice 39b, not 39a.** 39b is the `file-history/` mirror: 911 MB of
   irreplaceable protection that needs nothing from the `history.jsonl` work. 39a's
   census is bookkeeping and can ride alongside rather than gate the first real slice.
   This is safe because 39b's own risk table already handles the unknown it would have
   waited on: the ~5% of `file-history/` dirs that are not bare session uuids are
   REPORTED AS ANOMALIES by construction, so 39b never needed to know in advance what
   they are. **Still owed, just not as a blocker: 39a's DESIGN 15 entry** recording
   catalog-driven discovery and MEMORY's exclusion.

---


## Context

**The problem, measured 2026-09-07.** `~/.claude` holds 6.7 GB. cc-warehouse archives
`projects/` only, 4.2 GB of it. The remaining 2.5 GB is not junk: it is content that
sessions PRODUCED but that lives outside the transcript, and nothing reports its absence.

**Evidence that this is live loss, not theory.** `paste-cache/` holds 1,914 files, but
`history.jsonl` references **2,186 distinct content hashes**. **272 pasted blobs are
already gone** and unrecoverable. Something prunes that cache. Separately, ticket 38's
own census found **65.4 MB of `tool-results/` content that exists in no JSONL at all**,
lost since 2026-05-08 and unnoticed for four months.

**Intended outcome.** One gather mechanism, following the session id, so an archived
session folder holds everything that session produced, wherever Claude Code scattered it.

---

## Decision: a separate ticket 39, sequenced AFTER ticket 38, reusing its primitives

`harness/tickets/38-sidecars-tool-results-and-unknown-siblings.md` is **PLANNED,
RED-TEAMED, APPROVED, NOT STARTED** and is the current ACTIVE track. It covers the
sidecars INSIDE a session directory (`tool-results/`, `workflows/`).

**Ticket 39 is separate, and this is not ticket-splitting for its own sake:**

- **Different discovery shape.** Ticket 38 scans *beside the transcript*
  (`transcript_path.parent`). Items here live at `~/.claude/file-history/`,
  `~/.claude/paste-cache/`, `~/.claude/history.jsonl` - **siblings of `projects/`, not
  descendants of any transcript**. There is no parent directory to scan from, so
  discovery must be **catalog-driven**: walk the catalog's session_uuid list and look
  each one up, never walk `~/.claude`.
- **Reopening 38 costs its approval** for no benefit. Its red team closed a 17-row attack
  table sized to 135.7 MB. Absorbing 911 MB plus a join through an 18,295-row log would
  invalidate that, and 38's `tool-results` fix is urgent on its own.
- **The anti-duplication requirement is met by code reuse, not ticket fusion.** 39 imports
  38's primitives rather than re-deriving them.

**Hard dependency: 39 cannot start before 38 ships** `store.write_if_absent` and the
notice/doctor/alert scaffolding. Starting 39 first would build a second incompatible copy
of exactly that scaffolding, which is the duplication this ticket split exists to
avoid.

---

## What is new (recorded nowhere in this repo)

Censused: `paste-cache` **0 hits repo-wide**, `history.jsonl` **0 hits repo-wide**.

| Store | Scale | Keyed by session | Verified |
|---|---|---|---|
| `~/.claude/file-history/` | **1,010 entries, 911 MB** | directly, 95% | Versioned file snapshots (`23527e7c@v1..@v7`). **Bytes are NOT in the JSONL** - a sampled snapshot's first 200 bytes do not appear in its session's transcript, which carries only `file-history-snapshot` metadata |
| `~/.claude/history.jsonl` | **18,295 rows** | directly, **100%** carry `sessionId` | 86% match a session still in `projects/`; the archive holds 31,825 payloads vs 27,313 in `projects/`, so it can attribute prompts to sessions that already left |
| `~/.claude/paste-cache/` | 1,914 files | **indirectly**, via `history.jsonl` | 2,359 rows use `{id,type,contentHash}` (externalised), 852 use `{id,type,content}` (inlined). **272 referenced hashes are already missing; 0 files are unreferenced** |
| `~/.claude/todos/` | 3 files | directly | Trivial, rides along free |

**Three of my own findings were grep artifacts and are corrected here.** Repo hits for
`file-history` are the inline `file-history-snapshot` block type in `parser.py`; hits for
`todos` are `render.py::_render_todos` handling the `TodoWrite` tool call; and transcript
hits for `paste-cache` are **prose in sessions that were investigating `.claude`**, not
references. The directories are genuinely unhandled, but the earlier reasoning was wrong
each time. **paste-cache is reachable only by joining through `history.jsonl`**, which
sets the slice order.

### Operator rulings, 2026-09-07

- **`file-history/`: archive all of it**, backfilled and going forward. 911 MB against
  240 GiB free is not a space problem; the content exists nowhere else.
- **`~/.claude/MEMORY/` (317 MB): a SEPARATE ticket (40), destination
  `CC-SESSIONS-ARCHIVE`.** Not session-keyed, so it does not fit this mechanism. Another
  session is relocating it today, so designing storage now would target a path that is
  about to change. Record as a backlog note; revisit when that destination is stable.

---

## Design

### Layout - siblings inside the session folder ticket 38 already writes

```
<root>/<label>/<stamp>_<uuid>/
    <uuid>.jsonl
    transcript.md  transcript.compact.md
    conversation.html  conversation.compact.html
    manifest.json
    subagents/          (ticket 21)
    tool-results/       (ticket 38)
    workflows/          (ticket 38)
    file-history/       (39, NEW)  <hash>@v1..@vN, flat mirror
    pastes/             (39, NEW)  <contentHash>.txt, only those this session referenced
    prompts.jsonl       (39, NEW)  this session's history.jsonl rows, verbatim lines
```

`file-history/` and `pastes/` are copies of Claude Code's own bytes, so they use
`store.write_if_absent`: refuse-and-record on same-name/different-bytes, never overwrite.

### Discovery is catalog-driven

New leaf module `src/cc_warehouse/external.py`, sibling to 38's planned `sidecars.py`,
importing nothing from `archive` for the same reason. It walks the **catalog's
session_uuid list**, reusing the query shape at `archive.py:912-925`
(`SELECT s.hash, p.label, s.short, s.session_uuid FROM session s JOIN project p ...`)
and the `_parent_folder` scan at `archive.py:335-354`. **It never walks `~/.claude`.**

### `history.jsonl`: both whole and split

1. **Whole, content-addressed** under `_not-sessions/history-jsonl-snapshots/<sha256_12>.jsonl`,
   reusing `archive.write_not_a_session`'s shape (`archive.py:475-498`). Because the
   filename IS the hash, `exists()` genuinely means "same bytes" - the one place an
   exists-only skip does not reopen F1/F4. This is the backstop: it catches the 14% of
   rows with no archived session, future `pastedContents` format drift, and any bug in
   the split.
2. **Split per session** into `prompts.jsonl`, by **slicing raw lines** - parse only to
   read `sessionId` for routing, write the original bytes untouched. Never round-trip
   through `json.dumps` (unicode escaping, key order and float formatting all drift).
   Uses `store.write_if_changed`, so a later fix to the extraction can legitimately
   rewrite it.

**The trade-off, plainly:** (1) alone is safe but useless to a reader; (2) alone cannot be
the only copy, because a session-id bug would silently drop rows. Together, (2) is allowed
to be wrong and fixed later because (1) is never touched.

### Manifest

Follow ticket 38 ruling 7 (new top-level keys computed from the archive folder, not `loss`
amendments): `file_history: [{name, sha256, bytes}]`, `pastes: [...]`, and
`prompts: {present, sha256, bytes, lines}`. Absent-vs-empty distinguishes "none" from
"predates the feature" (F6), same as `subagents`.

### Verification

`_external_problems(directory, manifest)` - twin of `_subagent_problems`
(`archive.py:1123`). Hashes disk against the manifest, returns `[]` for an old manifest
without the keys, and **never starts a problem string with `missing `**
(`doctor.py:409`'s pending-render carve-out).

---

## Slices

| Slice | Delivers | Depends on |
|---|---|---|
| **39a** | Census + rulings: what the 5% non-uuid `file-history/` dirs are, `todos/` naming, DESIGN 15 entry recording catalog-driven discovery and MEMORY's exclusion | **ticket 38 shipped** |
| **39b** | **START HERE (operator ruling). FIRST VALUE SLICE: `file-history/` mirror** (+ `todos/` free). 911 MB protected, mechanically near-identical to 38's copier, **zero dependency** on the other items | ticket 38 only |
| **39c** | `history.jsonl` whole-file content-addressed snapshot + doctor staleness line. Independent value | 39a |
| **39d** | Per-session split into `prompts.jsonl`, verified against 39c's snapshot | 39c |
| **39e** | paste-cache gather, reusing 39d's in-memory sessionId index rather than re-parsing. A shared hash lands under every session that referenced it | 39d |
| **39f** | doctor/status/alert wiring; config keys `archive_file_history`, `archive_history_prompts` (mirroring `config.py:172`'s `archive_subagents`); sweep pass as an additional catalog-driven pass, not a `_walk_source` extension | 39b-e |
| **39g** | Docs, version bump, real-data acceptance script, CHANGELOG | all |

**39b is the slice that stands alone.** It protects the biggest irreplaceable number in
scope without touching `history.jsonl` at all, so it can ship even if the rest stalls.

---

## Constraints

- **Sources are read-only forever.** Nothing under `~/.claude` is modified, moved or
  deleted (operator rule, verbatim 2026-08-04).
- **Identity is the sha256 of payload bytes.** No archived payload changes.
- Writes go through `store.atomic_write` / `write_if_changed` / `write_if_absent`.
  `tests/test_fences.py` enforces that only `store.py`/`notify.py` open file handles.
- **Oracle tests before implementation.**
- **Best-effort, never fatal** - an auxiliary write must never turn a stored capture into
  a failed one. Proof pattern: `tests/test_capture_stage_logging.py`.

## Patterns to reuse (do not invent)

- `capture.py::_archive_subagents_of` - the only existing "companion beside the payload"
  implementation. Reads `child.with_suffix(".meta.json")`, passes bytes to
  `archive.write_subagent(..., meta=...)`.
- `archive.py::write_subagent`'s `meta: bytes | None` - bytes in, fixed name out,
  compare-before-write so mtimes do not churn.
- `archive.py::write_not_a_session` - content-addressed filename shape.
- `import_tree.py`'s lock-walk-classify-report as a SHAPE (R10 batch semantics) only.

## Known trap

`import_tree.py` walks `*.jsonl` via `migrate.walk_jsonl`. **Pointed at `~/.claude` it
swallows `history.jsonl`**, fails `archive.is_session`, and dumps 18,295 prompts into
`_not-sessions/imported/` as one blob with no session, date or label. A **fence test must
assert the new module never calls `migrate.walk_jsonl`.**

---

## Verification

Run from OUTSIDE the repo (the `.envrc` venv makes `ccw` ambiguous inside it):

```
uv run pytest -q                    # full suite, currently 1,241 tests
uv run pyright                      # strict, must be 0 errors
uv run ruff check .
env -u VIRTUAL_ENV PATH="$HOME/.local/bin:/usr/bin:/bin" ~/.local/bin/ccw doctor
```

**Real-data acceptance, mirroring ticket 38 section 7:**
1. `ccw sweep --dry-run` reports the new gather counts and writes nothing.
2. After a real pass: pick 3 sessions that have a `file-history/` entry, hash the source
   and the archived copy, assert byte-identical.
3. Assert every `prompts.jsonl` line is an exact substring of the source `history.jsonl`
   (proves raw-line slicing, no round-trip drift).
4. Assert one `contentHash` referenced by two sessions lands under **both**.
5. Run the sweep twice; the second pass must write **zero** new bytes (idempotence).
6. `ccw archive --verify` reports 0 problems.

**Key risks and their tests**

| Risk | Test |
|---|---|
| 5% of `file-history/` dirs are not bare uuids | Synthetic non-uuid dirname is reported as an anomaly, never silently skipped |
| `file-history/<uuid>/` whose session was never archived | Reported and landed under `_not-sessions/stranded-file-history/`, never invents a folder |
| Same name, different bytes on re-run | `write_if_absent` refuses and logs (R5) |
| Malformed `history.jsonl` line | Per-line try/except, named in the report, never aborts the batch (R10) |
| Split re-serialises instead of slicing | Byte-substring identity test (acceptance step 3) |
| Snapshot grows unbounded when unchanged | Content-addressed name means unchanged content writes zero bytes; two back-to-back sweeps prove it |
| New keys added to `GENERATED_NAMES`, becoming rebuild-deletable | Extend 38's `test_rebuild_never_touches_sidecars` to the three new names |

## Documentation to update (house style: a one-line pointer, not a paragraph)

- `OPENING-PROMPT.md` `## Next task` - **keep ticket 38 as ACTIVE**; add ticket 39 as the
  next track below it. The file is an index, not a log (`## Keep it this way`, line 105).
- `harness/tickets/39-*.md` - the full plan lives here.
- `harness/HANDOFFS.md` - new entry at the TOP (newest-first), twenty-eighth.
- `CLAUDE.md` `## OPEN / next` - one bold-led pointer paragraph appended at the end of the
  list, before `## Standing lessons`.
- `harness/tickets/28-backlog.md` - MEMORY/ as a backlog note pending ticket 40.
