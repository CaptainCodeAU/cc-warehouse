# DESIGN - cc-warehouse v1 architecture

**Status:** Phase 1 contract document, 2026-07-17. Implements the scope locked in
`BRAINSTORM.md` under the constraints of `FINDINGS.md`, preserving the `KEEP` column of
`SPEC.md`. Built by the process in `HARNESS.md`. An implementer should be able to build
from this document without asking questions; a reviewer should be able to reject code by
pointing at a numbered rule in section 14.

**Mission (one line).** Funnel every AI conversation, from any source, into one
immutable content-addressed warehouse, projected into uniform human- and
agent-consumable files, durable and findable forever, immune to project renames.

**Locked foundations** (from BRAINSTORM; restated because rules below depend on them):
Python 3.12+, stdlib-only runtime; pyright --strict + ruff clean from commit one; every
write tmp-file + `os.replace`; session identity = sha256; SQLite catalog; public repo,
PyPI + git distribution; macOS + Linux/WSL2; no server/daemon in v1 (the v1.2 MCP
recall server is the one planned exception), no transcript mutation, no embeddings
until after v1.1 ships (someday bucket), no Windows.

---

## 1. On-disk layout

One warehouse root (default `~/cc-warehouse-data`; the repo and the data never share a
directory). Everything under it is owned by `ccw`:

```
<root>/
  objects/<hh>/<sha256>.jsonl      immutable store: raw session payloads, named by
                                   their own sha256, sharded by first 2 hex chars.
                                   Written once, never modified, never deleted.
  objects/<hh>/<sha256>.zip        (v1.1) imported exporter bundles, same rules.
  catalog.sqlite                   the catalog + registry (section 3). Session rows
                                   are rebuildable from objects/ + a rescan; the
                                   REGISTRY (labels, merges, alias history, flags) is
                                   live user state that a rebuild cannot re-derive,
                                   so the catalog is treated as live data backed by
                                   SQLite's own atomicity (backup story: section 15).
  projections/<label>/<YYYY-MM-DD>_<slug>_s-<hash12>/
      transcript.md                the 4 mandatory files (section 6)
      transcript.compact.md
      conversation.html
      conversation.compact.html
      manifest.json                per-session render manifest: config used, counts,
                                   loss telemetry (exporter-style), source hash.
  config.toml                      OPTIONAL data-root config overlay; overrides the
                                   XDG file key-by-key (section 8)
  shares/<name>/                   static-site share outputs (section 9)
  inbox/                           (v1.1) drop folder for exporter zips
  inbox/processed/                 (v1.1) ingested bundles, moved not deleted
  locks/                           O_EXCL lock files for sweep-class operations
  logs/capture.jsonl               append-only capture/audit log
```

Projection directory names are human-browsable conveniences ONLY (label + date + slug +
short hash); the hash suffix makes them collision-free and greppable. Nothing parses
them; the catalog is the source of every mapping (FINDINGS F4, F5). `projections/` and
`shares/` are disposable: `ccw build --rebuild` regenerates them from objects + catalog.

## 2. Identity

- **Session identity** is `sha256(raw payload bytes)`. Short citation key
  `s:<first 12 hex>` appears in projection dir names, manifests, search results, and
  is the universal cross-tool reference (cc-vantage contract). On the (astronomically
  rare) 12-hex prefix collision, the newer session's stored short key extends until
  unique (16, 20, ... hex); `s:` lookups resolve by unambiguous prefix match, so
  existing citations stay valid. Re-captured unchanged
  sessions hash identically: no-op. A grown JSONL (append-only) hashes differently: it
  becomes the session's new latest VERSION; versions of one Claude Code session UUID
  are linked in the catalog, newest is canonical for projections, all are kept.
- **Project identity** is a registry row ID, never a path or display name. Paths are
  time-stamped alias claims. Display labels are mutable strings suggested at first
  sight by the specimen's derivation logic (SPEC section 3) and editable via
  `ccw project rename` (a label edit, nothing moves).
- **Bundle identity** (v1.1): layer 1 sha256 of the zip, layer 2 manifest
  `chatId`+`exportTime`, layer 3 `chatId` linking re-exports as versions.

## 3. Catalog schema (v1 sketch; Phase 2 freezes the DDL in schema.sql)

```sql
project(id INTEGER PK, label TEXT NOT NULL, created_at TEXT NOT NULL,
        retired INTEGER NOT NULL DEFAULT 0)
project_alias(id INTEGER PK, project_id -> project, path TEXT NOT NULL,
        kind TEXT NOT NULL,          -- 'cwd' | 'encoded_dir' | 'label_claim'
        first_seen TEXT, last_seen TEXT, UNIQUE(path, kind))
session(hash TEXT PK,                -- full sha256
        short TEXT NOT NULL UNIQUE,  -- s: citation key, 12 hex
        project_id -> project,
        source_kind TEXT NOT NULL,   -- 'claude_code' | 'web_export' (v1.1) | ...
        session_uuid TEXT,           -- Claude Code session id (version-links copies)
        supersedes TEXT REFERENCES session(hash),  -- older version of same uuid
        slug TEXT, git_branch TEXT, cwd TEXT,
        first_ts TEXT, last_ts TEXT,               -- from JSONL internals, never mtime
        size_bytes INTEGER, line_count INTEGER, skipped_lines INTEGER,
        summary TEXT, hidden INTEGER NOT NULL DEFAULT 0,   -- warmup/no-summary
        captured_at TEXT NOT NULL, resolution_source TEXT) -- payload_cwd/jsonl_cwd/...
capture_event(id INTEGER PK, at TEXT, session_hash TEXT, action TEXT,
        -- 'stored' | 'skipped_unchanged' | 'superseded' | 'error'
        elapsed_ms INTEGER, detail TEXT)
```

Rules baked into the schema: soft flags instead of deletes (`retired`, `hidden`);
timestamps from payload internals; every listing/search/build reads ONLY these tables
(FINDINGS F5). FTS5 tables arrive in v1.1 as derived, droppable indexes.

## 4. Capture pipeline (v1)

```
SessionEnd payload (stdin)                     ccw sweep [--source DIR]
  |  ccw hook                                    |  scans ~/.claude/projects for
  v                                              v  jsonls the catalog lacks
read payload -> validate -> read transcript bytes
  -> sha256                                     (same path from here)
  -> hash in catalog?  yes -> log+notify "skipped/unchanged" -> maybe open folder -> exit
  -> atomic write objects/<hh>/<sha>.jsonl   (tmp + os.replace; no-op if exists)
  -> parse ONCE: cwd, uuid, slug, branch, timestamps, summary, line counts
  -> resolve project: alias lookup -> hit = project_id
       miss = create project (label from SPEC-3 derivation) + alias rows
  -> catalog transaction: session row (+ supersedes link if same uuid known)
       + capture_event
  -> notify ok (elapsed ms, resolution source)   [desktop | voice | webhooks | log]
  -> spawn detached render child: ccw render --session s:<hash>
       child: build 4 files + manifest atomically into projections/...,
              notify error on failure (its only surviving signal),
              reveal folder only after files exist (opt-in)
```

Properties, mapped to findings: identity-idempotent (F1, F3), atomic everywhere (F2),
registry attribution (F4), single parse into the catalog (F5), errors report-and-stop
per item (F7), hook shares 100% of its code with the CLI (F8), nothing deletes (F9).
`ccw sweep` uses the same store routine per file, takes a `locks/sweep` lock, continues
past item failures with an end report (SPEC section 9), and is safe to run any time.

**Wiring on the principal's machine (decided 2026-07-17): BOTH capture paths.** The
plugin thin-wrapper (primary; owns the `CCW_*` env) and a direct `settings.json`
SessionEnd entry (always-on backstop for plugin-cache breakage) are BOTH registered.
Claude Code hooks are additive, so both fire; hash idempotence makes the second a
no-op, and a **duplicate-notification suppression window** keeps it silent: when a
capture_event for the same session hash landed within the last few seconds, the later
invocation logs action `duplicate-invocation` and emits no notifications. Sweep is the
third net. Switch-over is a clean cut on migration day (no old-tool overlap; the
parallel-probation option was explicitly rejected).

## 5. Sources (v1: one; designed for more)

`source_kind` is a first-class column, the store accepts any blob, and render/search
dispatch on it. v1 implements `claude_code` (JSONL). v1.1 adds `web_export` (exporter
zips via `ccw import`: content-sniffed zip/dir/jsonl, inbox sweep, 3-layer dedupe,
move-to-processed, never delete). Future kinds (Cowork etc.) are new adapters behind
the same interface: `parse(payload) -> normalized conversation + metadata`.

## 6. Render pipeline: the 4-file projection

One parser produces a **normalized conversation model** (turns, phases, blocks) shared
by all emitters. Semantics carried from the specimen per SPEC section 6/7: task
notifications are machinery, compact-summary continuations merge into their prompt,
Stop-hook-feedback prompts are excluded from headers/indexes, tool blocks keep their
typed rendering, commit detection feeds commit cards, copy-as-markdown payloads equal
the transcript.md fragments byte for byte.

The four files (all mandatory, per session, exporter v8.10.1 is the visual/structural
reference):

| File | Contents |
|---|---|
| `transcript.md` | full: header card + collapsed details block, `***` separators (Quick-Look-safe), grouped research phases (caption, duration, tool counts), thinking in ```` ```md ```` fences, tool rows with raw JSON in nested details |
| `transcript.compact.md` | conversation only + variant note; optional breadcrumbs (config, default off) |
| `conversation.html` | single-page HTML: collapsible turns and phases, per-block copy-as-md, sticky toolbar, width/font toggles, elapsed times, Catppuccin-derived palette. PERSONAL projections are not fully self-contained: highlight.js from CDN with graceful onerror fallback is the ONE permitted external reference (matching the exporter). SHARED pages INLINE the vendored highlight.js instead and carry ZERO external references (decided 2026-07-24, section 15 item 8) |
| `conversation.compact.html` | conversation-only page, same chrome |

Fixed policies (locked in brainstorm): thinking + tool calls ON in full variants;
thinking label TYPE and CAPTION stored separately, joined with `|` at render time;
system-reminder blocks COLLAPSED in full variants, STRIPPED in compact variants,
config-overridable for PERSONAL projections only (share builds ignore the override,
section 9); message anchors are unique (turn ordinal + short content hash, fixing
SPEC's `make_msg_id` collision); `manifest.json` records config, counts, and loss
telemetry so "did we lose anything" is always answerable (exporter principle). The
`loss` key set is skipped_lines + truncated_blocks + truncated_chars + unencodable_chars
(amended twice on 2026-08-01: section 15's block 3 added the truncation pair, and the
lone-surrogate ruling the same day added the last). The manifest also carries a
TOP-LEVEL `unrecognised` block, `{count, types}`, added by ticket 18 (section 15,
2026-08-02) and deliberately NOT a third `loss` amendment: every entry it counts
rendered a marker, so nothing was lost, and filing a rendered entry under loss would be
the guarantee drift F6 exists to ban. It answers a different question, "has the format
moved since the last census". A third top-level block, `withheld`
`{thinking_blocks}`, was added by ticket 20 the same day and answers a THIRD question:
what never arrived. `loss` is what we dropped, `unrecognised` is what the format grew,
`withheld` is what upstream stopped sending. It is counted at every display position,
because what the emitters draw is a choice and the count is a fact. A fourth top-level
key, `subagents` (ticket 21, 2026-08-03), lists this session's sub-agent transcripts as
`{agent_id, sha256, bytes}`. It exists so a DELETED sub-agent folder is detectable:
without it verify sees five valid files, a matching source hash and a correct folder
name, and reports clean. A session with none carries an empty list, never a missing key,
so a reader can tell "none" from "this manifest predates the feature". A fifth top-level
key, `renderer_version` (ticket 30, 2026-08-18), is `cc_warehouse.__version__`. It exists
so an incremental rebuild (`archive.folder_is_current`) can tell "this folder's pages
were built by an OLDER renderer" apart from "the payload and config haven't changed" - a
distinction `source_hash` and `config` alone cannot make. Chosen over a hand-maintained
format counter because a version nobody has to remember to bump cannot be forgotten; it
costs one full rebuild after each release, which is the run an operator would want anyway.

**Entry-type coverage (principal rulings 2026-07-23).** A field census of the live
JSONL format found 13 entry types where the render consumed only `user`/`assistant`.
The model now surfaces the rest, each grouped into its own phase and each an
independent toggle (all default ON): the session TITLE prefers Claude Code's own
`ai-title` over the slug/summary fallback; sub-agent (`isSidechain`) exchanges fold
into a labelled phase; `attachment` entries split into content kinds (rendered) and
machinery kinds (one-line marker); a `system` `local_command` renders as user input,
other subtypes as machinery; a tool result's `toolUseResult` renders stdout/stderr
with an interrupted marker (the Edit patch is left to the tool_use, not repeated);
and bridge-session / queue-operation / last-prompt / agent-name are surfaced verbatim
as informational extras. **AMENDED 2026-08-02 (ticket 18, section 15).** "The model now
surfaces the rest" was a PROMISE, not a fact: a census of all 13,836 stored objects
found eight further entry types and three content-block types that rendered nothing and
incremented nothing, 62,577 entries carrying `loss: 0` beside them. The parser now holds
a NAMED registry of every entry type (`KNOWN_ENTRY_TYPES`, built from per-purpose sets so
a test fence can read it off the source), machinery types render a one-line marker
exactly as `attachment`'s machinery kinds do, `result` renders a sub-agent's returned
work in full, `frame-link` renders as an extra, `image`/`document` blocks name their
media type and size but NEVER their base64, and `custom-title` joins the title sources
ABOVE `ai-title`. Anything the registry does not name renders a marker AND increments the
manifest's `unrecognised` block, which is the durable half: the previous census ran once,
on 2026-07-23, and two of the types it missed had first appeared earlier that month. Turns carry entry timestamps so the emitters show per-turn
elapsed times; phases group by CATEGORY so a sub-agent run, an attachment run, and the
main tool calls fold separately. `message.model` is a header field. The compact
variant stays prose-only and drops all of these. When a
session gains a newer version (section 2), incremental build removes the superseded
version's projection dir (a sanctioned in-projections deletion, R4) so exactly one
browsable dir per session UUID reads as canonical. When a project LABEL changes
(`ccw project rename`), the next incremental build relocates that project's projection
dirs under the new label folder and removes the emptied old one (same sanctioned
projection-space deletion). **Hidden sessions** (warmup / no-summary, `hidden=1`) are
stored and cataloged but NOT rendered by default: `ccw build --include-hidden` or
un-hiding a session renders it on the next build; the tree stays meaningful.
The markdown-to-HTML renderer is in-house stdlib code; its scope is the markdown WE
emit plus the hardening rules from SPEC section 7.

## 7. CLI surface (v1 verbs; argparse, stdlib)

| Verb | Does |
|---|---|
| `ccw hook` | SessionEnd capture from stdin payload (section 4) |
| `ccw sweep` | import anything the hook missed from `~/.claude/projects` (or `--source`); `--since`/`--until` import window (section 15, 2026-08-01); `--dry-run` reports what a real run would import and writes NOTHING; `--quiet` drops per-item lines but never a failure (section 15, 2026-08-03, ticket 23) |
| `ccw render` | (re)build the 4 files for `--session s:<hash>`; or render an ad-hoc `<path>` outside the store to `--out` (default: a temp dir, path printed), never under `projections/`, never touching the catalog; honors the content flags |
| `ccw build` | rebuild projections from the catalog; incremental by default, `--rebuild` for full, `--include-hidden` for hidden sessions; honors the content flags |
| `ccw migrate` | one-shot import of the legacy archive (section 10) |
| `ccw import` | adopt a FOREIGN transcript tree at `--from DIR`: depth-agnostic walk, `_DELETE` and any other named branch pruned and REPORTED, every session routed through the one capture routine (R9), a sub-agent payload refused by name rather than filed under its parent, a payload with no `sessionId` kept under the reserved `_not-sessions/` home; `--dry-run` rehearses and writes NOTHING, `--quiet` drops per-item lines but never a failure (section 15, 2026-08-04, ticket 25.4) |
| `ccw relocate` | move/rename a project across the external world (section 11) |
| `ccw project` | `list` / `show` / `rename` (label) / `move OLD NEW` (alias) / `merge A B` |
| `ccw share` | build a sanitized static site for chosen sessions (section 9); sessions chosen by hashes OR a `--since`/`--until` window, never both |
| `ccw status` | recent captures, counts, store size, last errors; plus the UNCAPTURED GAP, how many sessions and sub-agents exist in the source tree with no archive folder. Reads catalog + log + the source tree, read-only (widened from "catalog + log only": section 15, 2026-08-03, ticket 23) |
| `ccw doctor` | is capture actually working, and if not since when: `ccw` reachability, whether a capture hook is registered, whether it has EVER fired and when it last did, the uncaptured gap, the effective config, and the last integrity outcome. READ-ONLY by construction and proved so by snapshot, not asserted. Exits non-zero when capture is not working, so it composes into cron and a session-start check (section 15, 2026-08-03, ticket 23) |
| `ccw verify` | re-hash objects against their names; catalog/object cross-check |
| `ccw archive` | build the archive-first tree at `--to DIR`, or `--verify` an existing one; `--zone NAME` overrides `archive_timezone` (section 15, 2026-08-02, ticket 19). `--to` is required and refuses the warehouse itself; `--verify` writes nothing; honors the content flags |
| `ccw reindex` | rebuild `catalog.sqlite` from the archive tree ALONE, which is what makes "the catalog is a disposable index" (section 15, 2026-08-02) a demonstrable property rather than a claim. `--from DIR` (default `archive_root`), `--to DIR` (default the warehouse root, so a rebuild can be proved beside a live one), `--dry-run` rehearses and writes NOTHING. Staged as a tmp FILE and moved with `os.replace` (R2). REFUSES a tree with no session folders. REPORTS what a tree cannot give back: `capture_event` history, superseded versions (a folder is keyed by uuid, so it holds one copy), and every project whose `project.json` is missing or unreadable (section 15, 2026-08-05, ticket 27.1) |
| `ccw version` | version (also `-v`) |
| v1.1: `ccw search`; v1.2: `ccw mcp` | per BRAINSTORM cut (`ccw import` landed early, 2026-08-04, ticket 25.4: the data it rescues exists in one place and `~/.claude` is scheduled to go) |

Errors print `Error: <msg>` to stderr, exit 1 (SPEC's CLI contract). No default-verb
dispatch; bare `ccw` prints short status + usage; an unknown verb is a usage error;
`-h`/`--help` lists every USER-FACING verb, `-v`/`--version`/`version` print the version.

**Internal verbs (amended 2026-07-24, principal, at the v1 exit review).** The table above
is the user-facing surface. A detached child process re-enters the CLI to do its work, so
the dispatcher also accepts INTERNAL verbs that are deliberately absent from `-h` and from
the table: they are machine-facing, take a serialized payload rather than operands, and
are not a supported way to drive the tool by hand. Re-entering `cli:main` rather than
adding a second module entry point is what keeps R9/F8 satisfied (one implementation; a
wrapper carries no logic). v1 has exactly one: `ccw notify --record <json>`, the detached
notify-only helper that keeps webhook and voice sinks off the capture hook's critical path
(section 12). An internal verb must still be listed HERE when it is added, so "absent from
`-h`" never means "absent from the contract".
Packaging (decided 2026-07-17): distribution `cc-warehouse` on PyPI, import package
`cc_warehouse`, console scripts `ccw` (primary) and `cc-warehouse` (alias to the same
entry).

**Flag surface (slice 13, principal-approved 2026-07-23).** `build` and `render` take
the Group-A content toggles, each a `--x` / `--no-x` pair defaulting ON, mapped onto
the same `[render]` config keys (section 8) so a flag overrides config for one run:
`--subagents`, `--attachments`, `--commands`, `--extras`, `--tool-output`,
`--breadcrumbs`, plus `--reminders {collapse|strip|show}`. Global config-source
switches on every verb: `--no-config` (ignore both config files; defaults + env +
flags only) and `--config PATH` (read one named file instead of the usual two). `share`
adds `--EXPOSED` (section 9). The five v1.1 flag groups (per-file matrix, HTML chrome
defaults, truncation, date-locale, `--since`/`--until`) are DEFINED in the section 15
entry of 2026-08-01: eleven new `[render]` keys, their bijection-derived flags, and
`--since`/`--until` on `share` and `sweep`.

## 8. Configuration

Two config files, key-by-key layering (principal's call, 2026-07-17): the XDG file
`~/.config/cc-warehouse/config.toml` (dotfiles-manageable) is the base; an optional
`<root>/config.toml` inside the warehouse data root overrides it (config travels with
the data when present). Precedence, lowest to highest: built-in defaults -> XDG file
-> data-root file -> `[project.<registry-id>]` sections (same two-file order; keyed by
stable registry ID, never by label: labels are mutable and R3 confines them to
presentation; `ccw project show` prints the ID to use) -> `CCW_*` environment
variables -> CLI flags. Env vars exist for
hook-wrapper ergonomics (the successor of `TRANSCRIPT_*`): `CCW_ROOT`, `CCW_SKIP_HOOK`,
`CCW_VOICE_URL`, `CCW_VOICE_ID`, `CCW_OPEN_FOLDER`, `CCW_WEBHOOKS`. Decided 2026-07-17:
the `CCW_` prefix is locked and the code honors NO legacy `TRANSCRIPT_*` names; the
plugin wrapper switches to the new names on migration day. `--no-config` ignores both
config files (defaults + env + flags only); `--config PATH` reads one named file
instead of the two.

The frozen TOML key map (Phase 2, `[render]` expanded 2026-07-23 with the principal for
the content toggles): top-level `root`; `[notify]` voice_url voice_id open_folder;
`[render]` breadcrumbs reminders_full reminders_compact **subagents attachments commands
extras tool_output** + the 2026-08-01 v1.1 keys: **subagents_compact attachments_compact
commands_compact extras_compact tool_output_compact** (default OFF) **html_width html_font
html_turns details html_dates tool_output_max_chars**; `[share]` redact_patterns;
`[relocate]` roots; `[import]` inbox; `[[notify.webhook]]` name url events template;
`[project.<id>.<table>]` overrides. The full-variant render toggles default ON; the
`_compact` toggles default OFF; chrome defaults are large/small/expanded/closed/local;
the truncation cap defaults off. Desktop notification is ALWAYS on (locked); voice,
open-folder, and webhooks are opt-in. TOML parsing is stdlib `tomllib`.

EXPANDED 2026-08-02 with two more keys, both recorded here because a live config key
absent from this map is exactly the contract-vs-code gap the v1 exit review existed to
catch. `[render] thinking_withheld` (ticket 20): `caption` | `marker` | `off`, default
`caption`, deciding what the projections say about thinking blocks Claude Code left
empty; it takes `--thinking-withheld` under the same bijection as every other render
key (shared rule c). And TOP-LEVEL `archive_timezone` (ticket 19), an IANA zone name
defaulting to `UTC`, which pins the zone the archive folder name is rendered in; it is
top-level rather than `[render]` because it is a property of the WAREHOUSE layout, not
of rendering, and an unknown zone is recorded with the default kept rather than raised,
because load_config runs inside `ccw hook` and a typo must never stop a capture (R5).

## 9. Share: static-site export (v1)

`ccw share <s:hash ...> [--out shares/<name>]`: builds a static site of one or more
sessions (multi-session gets one index page) using the SAME renderer and theme as
personal projections (one renderer, one set of bugs; decided 2026-07-17), running the
**sanitization pass at share time**: config-driven redaction rules (built-ins: home
dir, username, hostname, email; user-defined patterns) applied to COPIES of the
projection files, plus a **redaction report** listing every hit (pattern, file, line,
replacement) so the user verifies before publishing. **Secret-shaped strings** (API
key / token / private-key patterns) are detected but NOT auto-redacted: they ABORT the
share with a findings report (`--allow-findings` overrides), because auto-mangling a
token-shaped string in a conversation ABOUT tokens would corrupt legitimate content. Raw store and personal projections stay full-fidelity.
Share builds IGNORE any personal render overrides: shared compact variants are always
reminder-free and shared full variants always collapse reminders, regardless of config
(a share must never leak `~/.claude` context because of a personal preference). The
fixed share policy DOES show the entry-type content classes (sub-agents, attachments,
commands, extras), same as a personal build (Decision 2 = B, principal 2026-07-23):
redaction recurses the whole decoded payload including embedded attachment content, so
this is a completeness choice, not a redaction gap.

**`--EXPOSED` (principal-approved 2026-07-23; the ONE sanctioned exception to "a share
must never leak").** A deliberately scary ALL-CAPS flag that publishes UNSCRUBBED
content, the only irreversible outward-facing action in the tool. It renders BOTH a
scrubbed and an unscrubbed site into a private temp staging area, prints a per-session
byte-size comparison plus the redaction-hit and secret-finding counts, then gates on a
three-way choice: type the literal word `EXPOSED` to publish the raw site, `S` for
scrubbed-only, anything else aborts. A non-TTY stdin is NEVER consent (it aborts,
nothing written). On the EXPOSED choice BOTH `out/EXPOSED/` and `out/SCRUBBED/` land so
the operator keeps both for comparison; on scrubbed-only just `out/SCRUBBED/`. The
staging lifecycle and the move-into-place live in the share module (R4 delete
authority); the real `--out` is untouched until the operator confirms.

## 10. Migrate (one-shot legacy import, v1)

`ccw migrate <old-archive-root>`: walks the ~7.3k-session legacy archive, imports every
`<uuid>.jsonl` through the standard store routine (hash dedupe collapses the archive's
duplicate copies for free), attributes projects via each JSONL's internal cwd through
the registry, records a migration manifest (per-file: source path, hash, outcome), and
NEVER writes to the source tree. Continue-past-failures with end report. Completion
criteria: every source jsonl accounted for as stored / duplicate-of / failed-with-
reason; `ccw verify` green afterward. Then, as a separate explicit step the user runs,
`ccw migrate --retire <root>` renames the source root to
`_RETIRED_<YYYY-MM>_<original-name>` (e.g. `_RETIRED_2026-08_claude-code-transcripts`;
underscore prefix matches the archive's `_`-dir convention, the date stamps when it
stopped being live). This is the single sanctioned write to the old world, per the
visibly-retired decision.

## 11. Relocate (v1, the riskiest surface; FINDINGS F2/F7/F9 apply doubly)

`ccw relocate <repo-path> [--to <new-path>]` repairs the external world after a repo
move/rename, in the specimen-taught order (SPEC section 10.2): PLAN (enumerate every
edit: registry alias, `~/.claude/projects` encoded dir renames, memory file content
rewrites in markdown AND JSON with JSON-aware editing, PAI-side roots from the
config-driven inventory) -> show the full plan -> BACKUP (copy every file whose CONTENTS
this run rewrites into a timestamped backup dir; containers are moved by same-device
rename, which loses nothing, and a cross-device move is refused outright because R4
sanctions no copy+delete) -> APPLY (atomic per file) -> VERIFY (re-scan: no old-path
references remain in the inventory scope; renamed dirs exist) -> REPORT
(manifest of every change, like the share redaction report). Dry-run is the default;
`--apply` executes. Refuses non-empty targets. Item failure aborts THAT item and
reports; it never falls through to a rename with un-rewritten contents. Two details
inherited from the specimen's migrate script (SPEC 10.2): contents are rewritten BEFORE
containers are renamed, and encoded-dir matching uses the boundary-guarded prefix rule
(the remainder after the prefix must be empty or start with `-`, so `...-foo` never
matches `...-foobar`).

JSON-aware editing rewrites every string in the decoded document, KEYS INCLUDED, because
real project config is keyed BY absolute path; the boundary guard means only a whole path
component is ever replaced (decided 2026-07-19, principal; slice-12 round 2).

The boundary rule is necessary but NOT sufficient (decided 2026-07-19, principal; this
CORRECTS the specimen rule SPEC 10.2 records): the encoding collapses `/`, `_` and `.`
to `-`, so `<repo>/two` and `<repo>-two` encode identically, and the rule alone renames
an unrelated sibling's transcript dir. A hyphen-remainder candidate is renamed only when
PROVEN to belong to the repo (the catalog attributes it to a cwd at or under the repo, or
exactly one real directory encodes to that name and it lies under the repo); an unproven
candidate is skipped and NAMED, and `--claim-ambiguous` is the only way to take it.

Content rewriting of encoded-dir names tracks exactly the directories this run renames,
one literal old->new pair per rename, so a reference is updated when and only when its
directory actually moved. Content rewriting never descends into the warehouse root (a
stored object rewritten in place no longer hashes to its address) nor into
`~/.claude/projects` (captured transcripts are sources, read-only forever); both are
repaired by renaming their containers, never by editing their contents.

## 12. Notifications

`notify` module, all sinks best-effort and non-blocking (specimen posture): desktop
(osascript/notify-send via fire-and-forget Popen, directly from the hook), voice and
webhook POSTs (stdlib urllib, ALWAYS from a detached process, never the hook's
critical path: on new captures the render child sends them before rendering; on the
skip path the hook spawns a tiny detached notify-only helper), open-folder,
JSONL audit log, and webhook sinks: `[[notify.webhook]]` config entries (name, url,
template, events) POSTed per their `events` list, defaulting to `["ok", "error"]`
(skipped/unchanged silent by default; decided 2026-07-17); Telegram is just a webhook
entry. A failing sink
is logged, never raised (capture must survive notification infrastructure).

## 13. Errors, atomicity, concurrency (global policy)

- One write primitive: `atomic_write(path, bytes)` = tmp in same dir + `os.replace`.
  Everything uses it, with exactly three sanctioned exceptions (FINDINGS F2 blesses
  them): SQLite writing catalog.sqlite through its own transactional machinery; the
  append-only audit log (`logs/capture.jsonl`, O_APPEND single-line writes); and lock
  files created/removed with `O_EXCL` semantics.
- Catalog mutations happen in transactions; the store write precedes the catalog row;
  a crash between them leaves an orphan object that `ccw verify` reports and `sweep`
  re-adopts (safe: objects are content-named).
- Item-level errors: report + skip item, never reclassify (F7). Batch commands always
  end with a per-item failure report (SPEC section 9).
- Locks only where two writers are possible and identity-idempotence is not enough
  (`sweep`, `migrate`, `build --rebuild`): `locks/<op>` via `O_EXCL`, stale after a
  recorded PID dies.

## 14. Enforceable design rules (reviewers reject code against these by number)

- R1 Identity is sha256; no size or path ever decides equality (F1, F4).
  AMENDED 2026-08-02 (archive-first, section 15): sha256 remains the ONLY answer to
  "are these the same bytes". A session UUID answers a DIFFERENT question, "are these
  the same session", and size answers a third, "which of two payloads KNOWN to differ
  is larger". Using UUID or size for either of those is not an R1 breach; using either
  to decide byte-equality still is, and remains the bug F1 exists to prevent.
- R2 `atomic_write` is the only write path for files; direct `write_text`/`open("w")`
  on final paths is a rejection (F2). Sanctioned exceptions, closed list: SQLite's own
  catalog writes, the O_APPEND audit log, O_EXCL lock create/remove (section 13).
- R3 All grouping/joins go through project IDs; display labels and paths appear only
  at the presentation edge (F4).
- R4 Warehouse data is delete-free: no deletion primitives against the store, the
  catalog, or capture/import/migrate SOURCES (append/soft-flag only, F9); sources are
  read-only. Deletions are sanctioned ONLY in the projections/shares rebuild module.
  AMENDED 2026-08-02 (archive-first, section 15): once the source JSONL lives INSIDE an
  archive folder, that file is store-class data sitting in the one tree the rebuild
  module is allowed to delete from. The rebuild module may therefore delete only files
  it GENERATED (the markdown, HTML and manifest); the session JSONL is never deletable
  by it, and neither is a folder that still contains one. This is the load-bearing rule
  of the whole redesign: without it, maintenance code can destroy the only copy.
  RESERVED LABELS (amended 2026-08-04, ticket 25.6): a top-level name in
  `build.RESERVED_LABELS` is NOT a project label, and `archive.walk_folders` never
  yields its children as session folders. The set is `locks`, `catalog.sqlite`,
  `_orphaned-subagents` and `_not-sessions`. `_not-sessions/` is the home for payloads
  that ruling (a) says are not sessions and that therefore cannot be given a session
  folder: the 7 workflow journals, and anything `ccw import` rescues without a
  `sessionId`. An unreserved folder here is not cosmetic: the walk would yield its
  children as sessions and `ccw archive --verify` would report every one as malformed.
  External-world writers, closed list: `relocate` apply (after backup, section 11),
  `migrate --retire` (one rename, section 10), lock release (section 13).
- R5 Errors default to the conservative branch: report and leave alone (F7).
- R6 Reads come from the catalog; opening a stored JSONL outside capture/render/
  verify/explicit-rebuild is a rejection (F5).
- R7 Runtime code is stdlib-only; a third-party import is a rejection. Test files may
  import the test framework (pytest) and nothing else third-party.
- R8 Every guarantee word in a string/docstring cites the test that proves it (F6).
- R9 One implementation per behavior; wrappers carry env only (F8).
- R10 Batch operations continue past item failures and end with a named-item report.
- R11 pyright --strict and ruff clean; both are merge gates, not suggestions.
- R12 Timestamps shown to users derive from payload internals, never file mtimes.
- R13 Apply-class confirmation is explicit: an interactive yes or `--yes`. A non-TTY
  stdin without `--yes` aborts having changed nothing (F10).
- R14 Capture is idempotent by identity; any surface where two writers are possible
  and identity-idempotence does not already make the race harmless takes a
  `locks/<op>` O_EXCL lock. Coordination by assumption is a rejection (F3).

## 15. Open decisions carried (deciding here when Phase 2 needs them)

1. Message-level deep-link target file for search hits (speed/tokens/accuracy bake-off
   in v1.1).
2. cc-vantage read interface: read-only ATTACH vs `ccw --json` vs MCP; this repo owns
   the call and publishes it (cc-vantage v0.3 section 16 defers to us).
3. Registry key form shared with cc-vantage (`project.registry_key`).
4. Default redaction rule set details (seed from the specimen's sanitize conventions).
5. Exact `CCW_*` env names + config key map: DECIDED 2026-07-23 (principal). The env
   list is the six names in section 8; the frozen TOML map is section 8, with `[render]`
   expanded to carry the content toggles. No render toggle takes an env var.
6. PyPI name final check: DORMANT 2026-07-24 (principal). The distribution name is
   `cc-warehouse` (confirmed; already in pyproject.toml), but see the DISTRIBUTION POSTURE
   entry below: the project is not being published for now, so nothing waits on a PyPI
   name re-check. Reactivate this item if publication is taken up.
7. Registry backup/export story (the registry is non-derivable live state, section 1):
   likely a `ccw project export` JSON dump; decide by the catalog slice.
8. Shares and highlight.js: DECIDED 2026-07-24 (principal). SHARED pages INLINE the
   vendored highlight.js and make no third-party request; PERSONAL projections keep the
   CDN reference plus its graceful onerror fallback (exporter parity), as this item
   always specified. The deciding argument was PRIVACY rather than self-containment:
   `ccw share` exists so publishing does not leak, and redaction scrubs the CONTENT while
   a CDN `<script>` exposes the READER, announcing their IP and the page URL to a third
   party. Durability seconded it: a published archive keeps working after a pinned CDN
   URL stops resolving. The "bigger files" counterargument was MEASURED and did not
   survive: on a real session `conversation.html` goes 3,157 KB -> 3,275 KB (+3.7%),
   because highlight.js is 118.9 KB against pages that are megabytes. Implemented as a
   `RenderOptions.hljs` mode (`cdn` | `inline` | `off`, default `cdn`), so one renderer
   serves both callers (R9) and the v1.1 `--hljs` flag inherits its meaning from this.
   The asset is vendored at `src/cc_warehouse/vendor/` with its URL, version, sha256 and
   BSD-3-Clause licence recorded; the emitted payload is asserted byte-for-byte against
   that file so a swap cannot drift silently. This is NOT an R7 exception: R7 bans
   third-party PYTHON imports, and this is a static asset copied into an output file.
9. License: DECIDED 2026-07-18 (principal, Phase 2 bootstrap): PolyForm
   Noncommercial 1.0.0 (source-available; supersedes the Apache-2.0 vs MIT
   framing this item originally carried).

Decided during Phase 1 review (recorded, no longer open): Python floor is 3.12+
(assumption stated in-session and unobjected, 2026-07-17; revisit only if an
implementation need argues for 3.13+). Principal-confirmed in the 2026-07-17
preferences round: data root `~/cc-warehouse-data`; projection folder naming
`<label>/<YYYY-MM-DD>_<slug>_s-<hash12>/`; store internals visible in the one root;
config is two-layer with the data-root file overriding the XDG file (section 8).
Grill round, same day: verb set locked as drafted; `CCW_` prefix with no legacy env
names; webhook default events ok+error; shares reuse the personal renderer/theme;
tree follows label renames on incremental build; hidden sessions not rendered by
default; retirement name `_RETIRED_<date>_<name>`; packaging dist/module/scripts
locked with the `cc-warehouse` alias; share secrets block-and-report; capture wired
through BOTH plugin wrapper and settings.json with duplicate-notification
suppression. Slice-01 triage, 2026-07-18 (principal): the delete fence carries a
function-scoped carve-out sanctioning lock-file removal inside store.py's O_EXCL
lock helpers (acquire takeover, release), matching the section 13/R4 closed
lists; lock release performs real removal, not a rename-aside. Slice-12 escalation,
2026-07-19 (principal): relocate refuses a cross-device move outright (os.rename cannot
cross filesystems and R4 sanctions no copy+delete); content-phase atomicity is
pre-flight validation then per-file `atomic_write`, with a content failure halting all
container renames; the rename TOCTOU residual is accepted because stdlib exposes no
RENAME_NOREPLACE, mitigated by a re-check at the point of action plus the locks/relocate
lock; there is deliberately NO automatic undo or resume, the journal and manifest being
an operator record only; backup covers the files whose contents are rewritten, since
containers move by same-device rename; `registry.move_project` also claims the encoded
form of the new path; and `atomic_write` PRESERVES an existing target's mode, because
replacing the inode was silently changing permissions on every rewrite (section 11 and
the section 11 boundary-rule correction record the relocate-specific halves of this).
Slice-13 / entry-type rulings, 2026-07-23 (principal): the render surfaces all 13 JSONL
entry types, each a content class toggle defaulting ON (section 6); the session title
prefers `ai-title` (extends the SPEC 8 title source, does not replace the fallback); the
`[render]` config map is expanded with subagents/attachments/commands/extras/tool_output
(section 8), each settable as a flag, a config key, and a per-project override, with a
flag overriding config for one run; `--no-config` and `--config PATH` are added; shares
show the new content classes (Decision 2 = B); and `--EXPOSED` is the one sanctioned
unscrubbed-publish path, gated by a scrubbed-vs-exposed comparison plus a typed
confirmation with a non-TTY abort (section 9).

**v1 EXIT REVIEW HELD AND CLOSED, 2026-07-24 (principal).** Every slice in the section 16
build order is DONE and carries its milestone tag (slice-01..13 including 12a and 12b,
14 tags); gates ruff clean, pyright strict 0, whole suite green; zero stubs. The review
found two contract-vs-code gaps that no DONE annotation, milestone tag or green test could
have surfaced, because the oracle suite was written from the tickets, the tickets from the
slice list, and the slice list enumerated neither surface. Both were ruled and closed in
the review:
(1) `ccw project` was implemented 1-of-5 against the section 7 table. Ruled: build all
four missing subcommands NOW rather than deferring `move`/`merge` to v1.1. This was not
cosmetic - section 8 keys per-project config on `[project.<registry-id>]` and names
`ccw project show` as the way to obtain that id, so the per-project override feature
shipped in slice 13 had no documented way to be used. Closed by commit b32b235.
(2) The dispatcher accepted an undocumented `ccw notify --record <json>`, making section
7's "lists every verb" false. Ruled: sanction INTERNAL verbs in section 7, keep them out
of `-h`, and require each to be listed in section 7 when added. Closed by commit 61a7d62.
Standing lesson recorded so it is not relearned: SLICE COMPLETENESS IS NOT CONTRACT
COMPLETENESS. A green suite proves the code matches the tests; only reading the contract
against the code proves the tests cover the contract.
Left open by this review and CLOSED the same day, each by its own principal ruling:
item 8 (`--hljs`), and the `--theme` question below. STILL OPEN: items 6 (PyPI name
re-check) and 7 (registry backup/export story), both pre-release rather than pre-v1, and
the v1.1 flag groups named in section 7.

**`--theme`: DECIDED 2026-07-24 (principal). Dark-only stands; no flag is added.** This
was never a section 15 item; it entered as a "product theme-neutrality decision" in the
flag-surface plan, on a PREMISE THAT WAS FALSE. A census of render.py found no
`color-scheme` declaration and no `prefers-color-scheme` media query anywhere: the page
hard-codes a dark Catppuccin-derived palette, and SPEC section 7 had already DROPPED the
specimen's dark/light localStorage toggle in favour of "the exporter's Catppuccin-derived
single-page look". So the verdict existed; the question only looked open because the
neutrality premise was wrong. Confirming it rather than reversing it: SPEC 7's drop is
explicit and reasoned, exporter parity is a stated value, and nothing is broken.
RECORDED AS A NAMED v1.1 CANDIDATE, not dropped: honouring the READER's OS setting via
`prefers-color-scheme` (no toggle, no stored state, so it would not reverse SPEC 7's drop
of the toggle). The justification is the one that decided item 8 the same day - shares are
read by other people, so product decisions are made for the reader rather than for the
operator's own display preference. It is v1.1 rather than v1 because it needs a light
palette designed and, more importantly, the hand-mapped highlight.js token colours
re-verified for contrast on a light background; that is design work, not plumbing, since
the CSS already routes everything through `:root` custom properties.

**DISTRIBUTION POSTURE: publication DEFERRED, 2026-07-24 (principal).** The project is NOT
being published for now ("at least not now"). This SUPERSEDES the framing in the locked
foundations that this document and BRAINSTORM carry - BRAINSTORM's "Public from day one:
PyPI + git-URL distribution" (line 27) and its rejected-item note "publishing is the plan"
(line 94), this section's restated foundation "PyPI + git distribution" (section, top),
and SPEC section 11's "PyPI publishing IS planned". Those lines are left as the record of
what was true in July 2026; this dated entry is the current posture, exactly as item 9's
license decision superseded its own earlier Apache-vs-MIT framing without rewriting it.
The distribution name stays `cc-warehouse` and the console scripts stay `ccw` /
`cc-warehouse` (packaging is unchanged and still valid for a git-URL install); only the
act of publishing to PyPI is deferred. Item 6 above is DORMANT as a consequence. The
wording is deliberately neutral between "deferred" and "abandoned": the principal said
"at least not now", and only the principal settles which. Reactivating publication
reactivates item 6 and this posture is re-decided here with a new dated line.

**v1.1 FLAG GROUPS: DEFINED, 2026-08-01 (principal, 17-decision planning interview).** The
five groups section 7 names (per-file matrix, HTML chrome defaults, truncation,
date-locale, `--since`/`--until`) were labels without definitions: none is a specimen
port (the specimen's whole flag surface is output / repo / gist / json / open / limit /
token / org-uuid / source / include-agents / dry-run / quiet), and the slice-13 plan that
coined the names was never written into the repo. This entry defines all five. Section
7's flag paragraph and verb table, section 8's key map and section 16's build order are
amended the same day; BRAINSTORM and SPEC are untouched (all four files stay mandatory).

Shared rules, all groups: (a) config keys are FLAT in `[render]`, layering key-by-key
under the existing one-level merge; no nested sub-tables (a sub-table replaces wholesale
at level two, silently breaking section 8's key-by-key promise, or forces a rewrite of
tested layering code). (b) An UNSUFFIXED content key or flag keeps its v1 meaning, the
full variants; `_compact` keys are the only door into compact. Purely additive: an empty
config renders byte-identical output before and after v1.1. (c) Flag spelling is a
mechanical bijection, flag = key with dashes (`--subagents-compact`,
`--tool-output-max-chars`); help text may group flags for readability, never respell
them. (d) Chrome keys are page-level and variant-agnostic; the unsuffixed-means-full
rule governs CONTENT toggles only.

**1) Per-file matrix** (truer name: per-VARIANT matrix). The five Group-A content
toggles become settable per variant. Compact's hard-coded drops (render.py
`_compact_policy`) become its DEFAULTS, changeable by five new keys: `subagents_compact`,
`attachments_compact`, `commands_compact`, `extras_compact`, `tool_output_compact` (all
default OFF), generalizing the shape `reminders_compact` already has. Full CLI parity
ships with it: `--x-compact` / `--no-x-compact` pairs plus `--reminders-compact VALUE`
(principal's call over a config-only cut). Defaults stated as contract for the first
time: full = all five ON (the 2026-07-23 ruling restated), compact = all five OFF.
NON-SCOPE: thinking has no key on either variant; BRAINSTORM locks thinking ON in full
variants and compact keeps it welded OFF; a thinking toggle would be its own future
proposal.
NARROWED 2026-08-02 (principal, ticket 20). What was frozen is that there is no toggle
for WHETHER THINKING RENDERS: it stays ON in full variants and welded OFF in compact,
unchanged and still not negotiable. The line as written also banned any key whose NAME
contains "thinking", and the oracle fence enforcing it
(`test_no_thinking_key_exists_on_either_variant`) read the letter rather than the
decision. `thinking_withheld` is not a thinking toggle: real thinking renders exactly as
before at every one of its positions, and it governs only how a block whose text NEVER
ARRIVED is reported (ticket 20; the text stopped reaching the JSONL upstream at Claude
Code v2.1.69). The alternative offered and REJECTED was renaming the key to dodge the
substring, which would have bought a five-minute ship at the price of a fence anyone
could defeat by choosing a synonym, and a key named less accurately than the thing it
does. The fence is narrowed to the decision, not deleted: a key that would turn thinking
rendering on or off is still a rejection.

**2) HTML chrome defaults.** The four initial states the page already models become
config defaults; every chrome element remains (exporter parity), only starting positions
move: `html_width` small|medium|large (today large), `html_font` small|medium|large
(today small), `html_turns` expanded|collapsed (today expanded), `details` closed|open
(today closed). `details` is deliberately unprefixed: initial `<details>` state is
emitted markup and reaches the markdown files too, the one knob of the four that is not
HTML-only, named honestly. Values are words, not the DOM's s/m/l letters (config is a
human surface). LocalStorage interplay: config sets the fallback a fresh browser sees; a
reader's own clicks win thereafter. REFUSED: visibility knobs (hiding toolbar / copy
buttons / position indicator) - exporter-parity divergence with no named consumer;
recorded so it is proposed someday, not drifted into. The `prefers-color-scheme`
candidate stays a SEPARATE entry (2026-07-24, above): share-facing design work, not
chrome plumbing.

**3) Truncation.** Opt-in, projection-only cap on rendered tool-result blocks:
`tool_output_max_chars` (absent or 0 = off, the default; positive = per-block char cap).
Characters because the renderer's native unit is decoded str, the archetypal offender is
a single-line blob that a line cap would miss, and a KB cap means different amounts per
alphabet. The cut lands at the last line boundary at or below the cap. Loss is never
silent (F6): an in-page marker states what was omitted AND that the stored session is
complete; the manifest `loss` key set grows to skipped_lines + truncated_blocks +
truncated_chars. The cap applies wherever a tool-result block renders (full by default;
compact if the matrix opened it). One cap, variant-agnostic. Store, sources, catalog:
untouched by construction.

**4) Date-locale.** Client-side display, no baked dates: markup keeps the raw ISO stamp,
so bytes stay deterministic forever - the incremental build's byte-compare and the
"unchanged session re-projects to the same bytes" invariant survive untouched, where a
baked local time would rewrite the warehouse on every timezone or DST change. A small JS
pass shows each timestamp in the READER's local time and locale, on session pages and
indexes alike; hover keeps the ISO stamp; markdown files stay ISO (the machine-adjacent
projection keeps the audit form). One chrome-family key: `html_dates` local|iso, default
local. Third consecutive product decision on the reader-respect principle (hljs,
prefers-color-scheme, now this).

**5) `--since` / `--until`.** On `ccw share` (a window as an alternative selector to
hashes; the two modes are MUTUALLY EXCLUSIVE, mixing is a usage error; union is addable
later, additively) and `ccw sweep` (an import window; additive and re-runnable, nothing
lost by narrowing). A session matches on its R12 date, the payload-internal FIRST
timestamp, the same one every listing presents. Bare dates are the OPERATOR'S LOCAL
calendar days, inclusive both ends (principal's call over UTC-day string-compare:
wall-clock intent wins); naive datetimes read as local, offset-carrying ones literal;
one-sided windows are valid; since after until is a usage error; no relative forms in
v1.1. CONSEQUENCE, stated once: folders slice UTC days (build.py `first_ts[:10]`), so a
morning session can match a date its folder name does not show.
AMENDED 2026-08-03 (slice 19g): this described the PROJECTION tree, which archive-first
retires. Archive and share folders slice the `archive_timezone` day instead, so with the
zone set to the operator's own the disagreement above largely DISAPPEARS - the folder day
and the typed local day agree. It survives only where the configured zone differs from the
typed date's zone, and the default is UTC, which is exactly the case the locked window test
still pins. The wart this consequence recorded was fixed by the redesign rather than by
being designed away. NAMED CANDIDATE, not
designed here: re-filing the projection tree under local days (rebuild-module
territory). REFUSED: the pair on `ccw build` - a windowed build either deletes
out-of-window projections (R4) or emits an index that silently omits sessions; no
consumer justifies designing around that hazard. `ccw status` adds nothing (it IS a
recency view). `ccw import` (v1.1 proper) adopts this definition when it lands.

**ARCHIVE-FIRST LAYOUT: DECIDED, 2026-08-02 (principal, working session).** The
product is a READABLE ARCHIVE, not a forensic one. The deliverable is the projected
folder tree: it gets backed up, it outlives `~/.claude`, and different consumers take
the markdown, the HTML or the raw JSONL from it. Everything below follows from that one
sentence, and each was measured against the live 13,836-session corpus before deciding.

FOLDER NAME. `<root>/<project>/<YYYYMMDD-HHMMSS><offset>_<session-uuid>/`, e.g.
`20260507-134745+1000_006b0875-8f20-4ae1-9d62-ac38ab4af8bf`. Local wall time in a zone
PINNED IN CONFIG (`archive_timezone`, e.g. Australia/Melbourne), never read from the
machine clock: converting a fixed UTC instant to a NAMED zone is deterministic, so the
same session yields the same folder name on any machine forever, which reading `TZ`
would not. The offset is carried because Melbourne's moves (+1100 AEDT / +1000 AEST),
and without it a folder name is ambiguous once the tooling is gone. Sorts correctly by
name; the UUID makes it greppable.

SLUG: DROPPED. Measured: 13,549 of 13,836 sessions (97.9%) have no slug at all, so
almost every folder was already named `<date>_session_<hash>`. The 2% that exist read
like `tax-bhencho-spicy-lerdorf` - a prompt fragment plus a random word pair. It cost
length and delivered nothing.

KEYED ON THE SESSION START (`first_ts`), overriding the principal's stated instinct to
follow "whatever Claude Code defaults to" - it defaults to nothing, since its files are
named `<uuid>.jsonl` with no date, and its mtime is a filesystem artefact, not payload
data (R12). START wins because a start-keyed name is IMMUTABLE: an end-keyed one is
only final when the session is truly dead, so a session already backed up could sprout
a second folder later. For a tree that gets archived, that is the worse failure.

VERSIONING: DROPPED, and the evidence is unusually clean. Across 15,466 source files
there are 172 duplicate-UUID cases; 171 are byte-identical copies and the remaining one
is not a session at all (workflow `journal.jsonl` files sharing a stem). NOT ONE genuine
two-version session exists in the corpus. On re-capture the larger payload replaces the
smaller IN PLACE, and a refusal (new payload smaller) is recorded in `manifest.json`
rather than being silent. This honours the principal's stated preference - minimise
duplication, but not as a hard line - without a second folder.

`objects/` RETIRED. With a real JSONL in every archive folder, the content-addressed
store becomes a second copy of what already ships. It was also earning nothing: 0
supersede links and 13,829 distinct UUIDs across 13,836 rows, so it had deduplicated
nothing. The `projections/` level is dropped with it: `<root>/<project>/<session>/`.
Reserve `locks` and `catalog.sqlite` as project names so the flattened root cannot
collide.

CATALOG: DEMOTED TO A DISPOSABLE INDEX. Project LABELS survive without it, because the
label IS the parent folder name. What does not survive is `project_alias` (121 rows,
~1.9 encoded paths per project), which maps the paths Claude Code used to the name the
operator chose; losing it splits a renamed project in two on the next capture. A small
`project.json` per project folder carries label plus known paths, after which the
archive is genuinely self-describing and the catalog can be deleted and rebuilt by a
rescan.

REJECTED, recorded so they are not re-proposed: HARDLINKING the store object into each
archive folder (elegant and free - verified same-inode, zero extra bytes - but it makes
the deliverable depend on a vault that may not be shipped); NAMING ARCHIVE FILES BY
HASH (the principal's ruling: a hash filename adds nothing for a human and only
confuses); END-KEYED folders allowing two folders per UUID (loses the immutable-name
property above); and GZIPPING payloads (a measured 69% saving, but the file stops being
readable in place, which is the opposite of the goal).

CONSEQUENCES for section 14: R1 and R4 are amended above. R4's amendment is the
load-bearing one - the rebuild module may delete only what it GENERATED.

THE THREE OPEN ITEMS WERE CLOSED THE SAME DAY (principal):

(a) WHAT COUNTS AS A SESSION. Two questions were being conflated and are now answered
separately. "Is this a Claude Code session file at all?" is answered by the presence of
a `sessionId` anywhere in the payload; measured across all 14,066 non-agent source
files, that test skips EXACTLY the 7 workflow journals and nothing else. "Does this
session have anything worth reading?" is a different question, already answered by the
existing hidden flag. The principal first chose a single semantic rule ("skip anything
with no conversation"), and it was re-measured before being written down: it would also
have skipped 139 UUID-named sessions that carry only machinery entries, silently
superseding the locked stored-but-hidden decision. RULED after that measurement: junk is
filtered by the sessionId test; the 139 conversation-free sessions are ARCHIVED (their
JSONL is kept) but get no markdown or HTML, which is exactly today's hidden behaviour.
Recorded because it is the second time this week a rule was measured before adoption and
turned out to reach further than intended.

(b) `ccw verify` BECOMES AN ARCHIVE INTEGRITY CHECK. Per folder: the JSONL still matches
the `source_hash` already recorded in its manifest, all five files are present, and the
folder name agrees with the payload's own UUID and start time. It verifies the thing
actually shipped and needs no vault to exist.

(c) `ccw share` KEEPS THE SAME LAYOUT, continuing to call the one shared
directory-naming function it already uses. One implementation (R9); a shared bundle
looks exactly like the archive it came from.

MIGRATION ORDER, unchanged and not negotiable: read from `objects/`, NOT from
`~/.claude/projects`. Four stored objects have no surviving source, and reversing the
order loses them permanently.

**REAL-DATA ENTRY-TYPE COVERAGE: DECIDED, 2026-08-02 (principal), ticket 18.** A census
of all 13,836 stored objects found eight entry types and three content-block types that
rendered NOTHING and incremented NO counter: 62,577 entries dropped with `loss: 0`
recorded beside them, which is silent loss by F6's own definition and a gap against
section 6's "the model now surfaces the rest". FOUR OPTIONS were put up and option 4
taken: classified markers PLUS a new top-level manifest key.

WHY NOT A NEW `loss` KEY (the ticket's own proposal, rejected). Once an entry renders a
marker it is not lost, so counting it as loss is the guarantee drift F6 bans, pointed the
other way. `unrecognised` is therefore a SEPARATE top-level key and the frozen `loss` set
stays at four, avoiding a third amendment in two days.

WHY NOT A BLANKET MARKER FOR EVERYTHING (the ticket's recommendation, also rejected). The
ticket was written without sampling the types. Sampling changed the answer: `result`
carries a sub-agent's returned work, mean 2,234 bytes and max 6,908 across 173 entries, so
a one-line marker would have closed a silent-loss bug by opening a quieter one. Machinery
gets a marker; content gets a block. `custom-title` joins the title sources ABOVE
`ai-title` on the same argument, a name a person chose over a name a model generated.

THE DURABLE HALF is the `unrecognised` counter plus an AST fence that reads the parser's
named type sets off its own source. The ROOT CAUSE is not the eleven types; it is that the
prior census ran once, on 2026-07-23, while `frame-link` first appeared 2026-07-03 and
`file-history-delta` 2026-07-14. A one-time census of a living format goes stale by
construction, so the product now reports the drift itself.

MEASURED CONSEQUENCES, all read-only against the corpus: 0 unrecognised entries across
13,836 objects, so the registry covers today's data completely; 26 sessions change title,
not the 910 the raw `custom-title` entry count suggests, because a rename appends an
entry; the compact variants do not move at all, because machinery is already excluded
there by policy; and `tests/golden/matrix-anchor` holds byte for byte, which is the proof
the change is additive.

CARRIED, NOT DECIDED **[SUPERSEDED the same day by the ticket 20 entry below, which
DECIDED it; kept because the supersession is itself the useful record, and a reader
reaching this paragraph first would otherwise learn something false]**: 41,458 of 43,060
`thinking` blocks in the corpus arrive with
`thinking: ""` and their content in an opaque `signature` blob (encrypted extended
thinking). They render nothing and count nothing today, which is the same F6 class one
level below the dispatch, inside a NAMED branch. Surfacing them is a further visible
change of 41,458 markers and therefore its own ruling.

PROVENANCE, established 2026-08-02 against the corpus and the public record, and recorded
because the obvious reading of the data is the wrong one. This is a MODEL property, not a
date property. Every `claude-opus-4-7`, `claude-opus-4-8`, `claude-opus-5`,
`claude-fable-5` and `claude-sonnet-5` block in the corpus is empty and always was: 0 of
25,470 opus-4-8 blocks carry text, across both eras. All 1,602 readable blocks come from
just two models, `claude-haiku-4-5-20251001` (1,391) and `claude-sonnet-4-6` (211).
Upstream, `anthropics/claude-code` issue 30958 (opened 2026-03-05, still open, no
maintainer response) names v2.1.69 as where thinking text stopped reaching the JSONL, with
v2.1.68 the last working release; issue 32810 (opened 2026-03-10, closed as not planned)
reports the same against v2.1.72. Both predate this warehouse, whose first capture is
2026-05-01, so the change itself is not observable here, only its result. What IS
observable is the tail closing: haiku-4-5 wrote text on every one of its blocks up to
2026-07-01 under CLI 2.1.197 and none from 2026-07-02 under 2.1.198 onward, 22 consecutive
versions and 21,670 blocks with zero. CAUSE UNPROVEN: CLI version and date are confounded
on an auto-updating machine and no pre-2.1.198 version appears after the boundary to break
the tie. Circumstantial only, 2.1.198 shipped 2026-07-01 carrying both "subagents and
context compaction now inherit the session's extended thinking configuration" and the
Explore agent moving off haiku. Neither change was ever documented as affecting transcript
storage.

CONSEQUENCE for the pending ruling: a marker saying "thinking omitted" would be honest,
but a marker implying the text was ever available for an Opus session would not. For 96%
of this corpus there is nothing that was lost at capture time; there is something that
never arrived.

**DECIDED 2026-08-02 (principal), ticket 20, option 4 of four.** The count folds into the
phase caption the transcript ALREADY prints, so the default adds no lines where the phase
also renders something, plus a top-level `withheld` manifest block so the question is
answerable across 13,836 sessions without opening a transcript. REJECTED: a marker per
block (41,458 near-identical lines, clustered, failing the "well structured" half of the
principal's own requirement); a manifest counter alone (invisible where it happened); and
leaving it (a named F6 hole left open deliberately).

PLUS, ruled in the same breath: the operator gets a CLI argument to OVERRULE the default,
so the rejected options become runtime positions rather than closed doors. Key
`[render] thinking_withheld`, flag `--thinking-withheld`, three positions
`caption|marker|off`, default `caption` (the 2026-08-01 bijection, shared rule c).

HONEST COST, found by a test rather than by reasoning: "no new lines" holds when the
phase also contains something that renders, which is the common case. A phase containing
NOTHING but withheld thinking has no existing header to join, so it costs ONE breadcrumb
line. Suppressing that instead would put the fact back in the dark, which is what this
ticket exists to stop. The oracle suite pins both cases separately rather than gloss the
exception.

NON-SCOPE, withdrawn on reflection after being offered: splitting `narration` (1,397
blocks) from `thinking`. Reading that label means PARSING THE SIGNATURE, a field
Anthropic documents as opaque. Building visible product behaviour on an undocumented
internal encoding would break silently the first time it changed, which is the overclaim
class this project bans. The observation is recorded; the dependency is not built.

CARRIED to ticket 19: the signature blobs total 218,406,832 characters, about 14% of the
1.5 GB store, and under archive-first they ship inside every session folder as unreadable
payload. That is a storage decision and belongs to its own round.

**LONE SURROGATES: DECIDED, 2026-08-01 (principal), found on real data.** The first
`ccw build` at scale (13,608 sessions) failed on 9 of them with `UnicodeEncodeError:
surrogates not allowed`; a census found 11 of 13,836 stored objects affected. The cause
is upstream: Claude Code truncates a field mid-emoji and leaves the HIGH half of a
surrogate pair, which `json.loads` decodes into a legal Python str that has no utf-8
encoding at all, so the render succeeds and the WRITE fails. RULED: replace each lone
surrogate with U+FFFD, the character the standard defines for exactly this, and COUNT it
into the manifest `loss` block as `unencodable_chars` (section 6 amended accordingly).
REJECTED: `errors="surrogatepass"`, which preserves the bits but emits files that are not
valid utf-8; and replacing silently, which is F6 by definition. The reasoning for
replacement over preservation is that the character was ALREADY destroyed upstream, so
this chooses how to represent something broken rather than discarding something whole. The
store is untouched by construction: the original bytes, escape and all, stay recoverable.
The scrub walks the DECODED object, never the raw text, so a well-formed astral character
- which arrives as a proper surrogate PAIR and decodes to one legal character - is never
touched. Batch behaviour needed no change: R10 already reported each failed item by name
and carried on, which is how the 9 were found at all.

Build order: four slices, render-first - 14 matrix, 15 chrome + date-locale (one key
family, one JS file), 16 truncation (the manifest amendment rides alone in the smallest
slice), 17 window. Contract amendments land first; each slice runs the standard loop,
oracle tests first.

**`ccw doctor`, AND WHY IT IS A VERB: DECIDED 2026-08-03 (principal), ticket 23.**
Section 7 gains one verb and two amended rows. The amendment is recorded because
section 7 is the locked list and the 2026-07-24 exit review ruled that every verb,
internal ones included, must be listed there when added.

THE FAILURE THAT ARGUES FOR IT. Capture stopped on 2026-07-24 and nobody found out
for ten days. Every link an operator would check looked healthy: the plugin was
enabled, its cached files were byte-identical to their repo copies, and the CLI it
delegated to existed and still exposed the verb being called. The break was one layer
below all of that, `uv tool run` resolving a DIFFERENT package of the same name from
PyPI, and the wrapper discarded the non-zero exit with `check=False`.

NOTHING IN THE PRODUCT COULD HAVE SAID SO, and that is the design point. `ccw status`
reads the catalog, so a hook that never runs writes no row and raises no error;
silence is indistinguishable from idleness. The question "is the machinery working"
had no owner.

THREE OPTIONS were put up and option 1 taken. REJECTED: folding it into `ccw status`
as flags, because `status` answers "what is in the warehouse" and `doctor` answers "is
the machinery working", and conflating them reproduces the exact confusion that let
ten days pass; it would also have widened `status`'s contract row anyway, paying the
same cost for a muddier result. REJECTED: an internal verb absent from `-h`, which
hides the one command whose entire purpose is to be found when something is wrong.

`status` IS widened regardless, deliberately and narrowly: its row said "reads catalog
+ log only", and the uncaptured-gap figure needs the source tree too. Read-only, and
the number is one an operator asked for three times in a single day and had to get
from a throwaway script each time.

ORDERING, recorded because it is the unusual part: ticket 23 runs BEFORE the ticket
that fixes capture. Fixing first and asserting success is what produced the ten days;
building the instrument first makes ticket 24's exit condition a command rather than a
belief. `doctor` must therefore be READ-ONLY BY CONSTRUCTION and proved so by
snapshotting the tree, since exit 0 plus output is not evidence that nothing happened
(2026-08-01, `ccw sweep -h`).

`--dry-run` on sweep lands in the same ticket for the same reason: the first real
sweep after this processes about 1,857 payloads into a tree that is about to become
the only copy, and the same 2026-08-01 incident showed a sweep can run when nobody
intended it to. `--quiet` is a precondition for scheduling it, since a chatty cron job
is one whose output nobody reads.

**2026-08-04, ticket 25.4: `ccw import` is a NEW VERB, not an extension of `migrate`
(principal).** Section 7 already listed `ccw import` under the v1.1 cut and
`config.py` already reserved an `[import] inbox` key, so the verb was anticipated
rather than invented. Extending `migrate` was the alternative and was rejected: it is
"one-shot import of THE legacy archive" and would have become two tools wearing one
name. The verb is pulled FORWARD out of v1.1 because what it rescues (4,754 sessions,
392.2 MiB, dated 2026-02-14 to 2026-07-03) exists in neither `~/.claude` nor the
archive, and `~/.claude` is scheduled to be wiped.

WHAT THE DESIGN OWES TO MEASUREMENT rather than to reasoning, censused over ALL 4,754
payloads on 2026-08-04 (not a sample, which is the point):

- 0 are sub-agent transcripts. The hazard was real and is the reason import REFUSES a
  sub-agent by name instead of routing it: `capture` archives unconditionally with no
  `is_subagent` guard, so the session path would file one under its PARENT'S uuid and
  let replace-if-larger overwrite the parent's transcript. `migrate` has no such guard.
  With zero to rescue, a refusal that reports beats a rescue route nothing exercises.
- 0 fail to parse. The ticket called this "the largest unknown on the track"; it is not.
- 0 uuids exist ONLY inside the `_DELETE/` quarantine, so pruning that branch loses
  nothing. The prune is REPORTED, because a silent skip and a silent failure look the
  same from outside.
- exactly 2 carry no `sessionId`, and both are CURSOR transcripts (`{"role":..}` with
  no `type` key, no timestamp). Ruling (a) already decides them: not sessions, so the
  reserved home, not a session folder. Given a session folder they would BOTH compute
  `undated_session/session.jsonl` and the larger would silently displace the smaller.

The walk is `migrate.walk_jsonl`, promoted from private and given a `skip_dirs`
argument that prunes `dirnames` in place; the read-only catalog probe is
`sweep.cataloged_hashes_readonly`, promoted for the same reason. Neither is
reimplemented (R9). The real tree is NOT the uniform `<project>/<uuid>/` the ticket
assumed (sessions sit at depths 1 through 4 across 71 branches), and the existing walk
was already depth-agnostic, so no new walker was needed.

**2026-08-04, ticket 29 mechanism 2: THE PAYLOAD THAT RENDERS IS THE ONE THAT
SURVIVED.** `archive.write_session_folder` refused to shrink a folder's JSONL when
handed a smaller payload and then wrote all five generated files FROM THE PAYLOAD
IT HAD JUST REFUSED, leaving the folder's two halves describing different
sessions. `ccw archive --verify` reports that as "JSONL does not match manifest
source_hash". Both `build._mirror` and `ccw archive --to` route through this
function, so it was never specific to one verb, and which payload a folder READ
AS came down to insertion order.

It was found by RUNNING the thing, not by reading it: the ticket 25.5 rehearsal
imported the real legacy tree into a throwaway root and reported 7,671 stored, 0
failed, exit 0. Every signal said success. Verifying the RESULT found the folder.

The fix renders from the payload on disk and re-derives `hidden` from it, so a
truncated re-capture cannot decide whether the full session gets markdown.

REJECTED, and recorded because it is the obvious move: SKIPPING THE RENDER on
refusal. The locked oracle test
`test_a_smaller_payload_is_refused_and_the_refusal_is_recorded` protects "a
truncated re-capture must not be able to shrink the archive WITHOUT SAYING SO IN
THE MANIFEST", and the manifest is one of the five files a skip would stop
writing. That fence's letter and its decision AGREE, so it was not a candidate
for narrowing; it passes unchanged.

STILL OPEN (ticket 29 mechanism 1): `catalog.add_session` points each new row's
`supersedes` at the previous latest, so the newest INSERT is never superseded and
`build._heads` picks it. A late-imported older copy therefore becomes the catalog
head even when its own last timestamp is earlier. Harmless for the archive folder
now, and still wrong for every catalog-driven surface.

**2026-08-18, ticket 30: INCREMENTAL ARCHIVE REBUILD.** A weekly `ccw archive`
run redid every session's five files unconditionally - measured on this
machine's real archive: 20779 folders, ~40 minutes, ~90% CPU, every run,
regardless of how few sessions had actually changed. `_migrate_locked` walked
every catalog row with no cursor and no "only what changed since last time".

Fixed with one predicate, `archive.folder_is_current`, checked at two call
sites (`_migrate_locked`, before `store.get()` is even called, and
`write_session_folder` itself, covering the mirror/capture paths for free) so
there is one implementation of "would rebuilding this folder change anything",
not two. `ccw archive --rebuild` is the escape hatch, mirroring `ccw build
--rebuild`.

Skipping the RENDER, not just the write (which is what `ccw build`'s existing
`_write_if_changed` does, after a full byte-compare), is a strictly stronger
claim and opened two failure modes a byte-compare would have caught for free:

- A renderer upgrade must still reach every folder eventually. Closed by adding
  `renderer_version` to the manifest (section 6 above) rather than requiring an
  operator to remember `--rebuild` after every release.
- A sub-agent captured after its parent's last render must still force a
  rebuild, or the parent's `subagents` list goes stale and a later deletion
  becomes undetectable by `ccw archive --verify`. Closed by including
  `subagent_records(directory)` in the check. Measured before the fix: the
  weekly full rebuild was the ONLY thing keeping the real archive's 300
  sub-agent-bearing folders at 0 stale.

A THIRD failure mode was found by running the oracle suite, not by reasoning
about the design: the skip-check as first written trusted `manifest.json`
alone, and `tests/test_keep_projections.py::
test_build_still_refreshes_the_archive_when_projections_are_off` (which
deletes `transcript.md` and expects `ccw build --rebuild` to restore it)
regressed, because the manifest - the one file the test had NOT deleted -
still looked current. Fixed by requiring all five `GENERATED_NAMES` files to
be present before the manifest is even opened.

The proposal's one open question - could an interrupted run leave a manifest
that reads "current" beside stale pages - was answered by reading the code
rather than by adding a new mechanism: `build.iter_projection_files` already
yields `manifest.json` LAST, so a kill mid-write can only leave fresh pages
beside an OLD manifest, which fails the hash check and forces a rebuild. That
ordering is now a pinned invariant (`test_manifest_is_yielded_last`,
`tests/test_archive_incremental.py`), not incidental.

**2026-08-20, ticket 31.2: THE SAME DISEASE, A THIRD TIME, IN `build.build()`.**
`ccw sweep` calls `build.build()` at the end of every run that captures
anything (basically daily), and `build.build()` unconditionally read every
catalog head from the store to decide what changed - ticket 28.20 measured
~6 minutes of pure CPU for that alone on a 14,246-session corpus, stacked on
top of sweep's own 34-44 minute file walk. Found while investigating one
real session whose save half-completed during this exact daily window
(`contract/PROPOSALS/daily-sweep-full-corpus-cost.md`).

A first attempt (guard the whole `build.build()` call on `keep_projections`)
was caught and retracted BEFORE any code shipped: `build()`'s `_mirror()` call
is what renders a swept session's ARCHIVE pages, unconditionally, independent
of `keep_projections` - it is the only renderer a swept session ever gets,
since sweep never spawns a per-session detached render child (see
`tests/test_sweep_projects.py`). Skipping `build()` entirely would have turned
every safety-net capture into a folder with a saved JSONL and no readable
pages - deterministically reproducing, for every swept session, the exact
defect the investigation started from.

Fixed by extending ticket 30's own pattern to a SECOND axis. `archive.
folder_is_current` was split into a shared core (`archive._current_manifest`)
plus two public answers over that core: `folder_is_current` (unchanged
signature and behavior - archive folders, which can carry sub-agents) and the
new `archive.pages_are_current` (the old `projections/` tree, which never
can: `write_subagent` only ever writes under `archive_root`, so a projection
manifest has no `subagents` key and `folder_is_current` unmodified would
return False there unconditionally). `build._head_is_current` then ANDs
whichever of the two trees this deployment actually keeps - skipping a head's
entire read only when EVERY live tree already reflects it - computed from
catalog columns `_heads()` already selected (`_Head.hash`, `label`,
`first_ts`, `session_uuid`), no SQL widening needed, same "safe by
construction" argument ticket 30 already relies on for `_migrate_locked`: a
wrong computed path just fails to find a manifest and falls through to a
full rebuild, never a wrongful skip.

Two things this review surfaced that ticket 30 itself did not need:

- `folder_is_current` checks the five `GENERATED_NAMES` files but never the
  JSONL beside them; `ccw build` had always happened to restore a deleted
  archive JSONL as a side effect of unconditionally reading from the store.
  Operator decision (2026-08-20): keep that repair rather than lose it
  silently - `_head_is_current` also checks `archive.sole_jsonl(folder) is
  not None`, one `glob()` per archived head.
- `build._mirror()` never forwarded `rebuild` to `write_session_folder`, so
  `ccw build --rebuild` had always silently done nothing to an
  already-current archive folder (masked because real drift always trips
  `folder_is_current` anyway - only a forced rebuild of a genuinely current
  folder exposed it). Fixed alongside, since the skip depending on `rebuild`
  meaning something in both trees is what made the gap matter.

**2026-08-20, ticket 31.3: THE TICKET'S OWN PREMISE WAS MEASURED AND FOUND
FALSE, BEFORE THE FIX WAS DESIGNED.** `harness/tickets/31-sweep-full-corpus-
cost.md` section 31.3 asked what cheap-but-honest signal could replace the
read+hash `sweep.py` pays for every one of the ~16,400 daily
`skipped_unchanged` items, on the premise that the read+hash IS the expensive
part. Timed directly (a 150-file sample over the real corpus): read+hash costs
~0.4 ms/file, ~7 s total for the day's skips - not the driver of a 34.5-minute
daily window. The real per-item cost is the machinery WRAPPED AROUND the hash:
`_is_subagent_file`'s full JSON parse (~44 s/day), and - hidden because
`capture.py`'s own `elapsed_ms` timer stops one line before it -
`record_event`'s per-item O_EXCL lock file, fresh `sqlite3.connect` +
`executescript`, and `BEGIN IMMEDIATE`/INSERT/COMMIT (~19 s/day, timed in
isolation against a throwaway copy of the real catalog).

Fixed by reusing `sweep.plan()`'s own shipped, tested skip decision
(`sweep.py` ~line 292: read, hash, compare against a `cataloged_hashes_
readonly` snapshot) on `sweep()`'s hot path instead of inventing a new
signal. The snapshot is taken ONCE, before the per-item loop, and never
updated mid-run: a session captured elsewhere during the sweep is simply
absent from it and takes the full path (fails toward more work), and two
files with identical content both new to one run still go stored +
duplicate-invocation exactly as before, because neither is in the snapshot
yet either (`test_two_identical_new_files_in_one_sweep_still_get_stored_
then_duplicate`, `tests/test_sweep_incremental.py`). R1 holds without an
exception - the skip is decided on the same sha256 `capture._capture_locked`
decides on, never mtime or size - and R9 holds - `capture_transcript` remains
the only thing that stores or catalogs; a wrong pre-filter answer only ever
costs a redundant full pass, never a wrongful skip.

**Operator decision, 2026-08-20: the ~16,400/day per-item `skipped_unchanged`
`capture_event` rows are replaced by ONE aggregate row per run**, action
`sweep-unchanged` (a name deliberately distinct from `skipped_unchanged` so
it can never be miscounted as one session's own event, R10/F6),
`session_hash = NULL` (the column was already nullable; `catalog.
record_event`'s signature had just never needed to say so), `detail = "<N>
unchanged"`. This keeps `ccw doctor`'s `fired` check (`MAX(at) FROM
capture_event`) moving on a day nothing new is stored, at the cost of one
transaction instead of thousands.

**THE HEADLINE NUMBER THIS ENTRY DOES NOT CLAIM.** Every per-item mechanism
named above sums to roughly 72 s across a corpus this size - nowhere near the
2,072.5 s (34.5 min) the daily job actually took on 2026-08-20. That gap
(~91%) was not explained by anything in this codebase and is not claimed to
be closed by this fix; the leading unproven candidate is the machine's own
independently-confirmed resource contention under 4+ concurrent sessions
(`python-process-resource-limits.md`, operator memory), which an isolated
timing measurement cannot reproduce. **What WAS measured, on this machine,
against the real 21,734-session corpus, immediately after this fix shipped:
a real (non-dry-run) `ccw sweep` completed in 81.9 s wall-clock** (18,976
items, 200 stored, 1 aggregate `sweep-unchanged` row of 17,080 - `at`
`2026-08-20T08:07:37Z`, `elapsed_ms` 386 for the pre-filter pass itself).
Whether the daily launchd run reaches a similar number depends on whatever
was producing the other ~91%, which this ticket did not identify and 31.4/
31.5 should treat as the standing open question rather than assume closed.

**Cheap check, done first as the next session's handoff asked: no genuine
post-31.3 launchd run exists yet.** 31.3 was committed and tagged 08:10-08:11
UTC on 2026-08-20. That day's 12:30-local (02:30 UTC) `com.captaincodeau.
ccw-sweep` run started and finished (02:30:02-02:38:17 UTC per its 16,382
individual `skipped_unchanged` rows) BEFORE the deploy - the pre-31.3 shape,
confirmed from `capture_event` directly rather than assumed. The only
post-31.3 data point remains the 81.9 s interactive run this same entry
already flagged as not representative of launchd's own environment. The
~91% gap stays open; tomorrow's 12:30 run is still the first real test.

**2026-08-20, ticket 31.4: DEBUG LOGGING SHIPPED, THE RETRY LOOP DID NOT -
AND READING THE CODE FOUND A BIGGER GAP THAN THE ONE THE TICKET NAMED.** The
ticket's own instruction was narrow: add logging around the post-`_archive_
source` steps in `capture._capture_locked`, confirm the actual exception on
the next real occurrence, and do not design a fix for an unconfirmed cause.
That shipped as written - `catalog.add_session` and `catalog.record_event`
(`capture.py`) are each wrapped in a narrow try/except that appends a
stage-labeled line to the existing O_APPEND audit log (`notify.append_log`,
`logs/capture.jsonl` - R2's sanctioned exception, no new write path) and then
unconditionally re-raises, so behavior is unchanged except for the added
line. Reading `_capture_locked` and its two callers before writing anything,
per the ticket's own discipline, surfaced a mechanism the ticket had not
named: the HOOK path (`_run_hook`, `cli.py`) already wraps every capture in a
never-raise boundary and reports any exception via `notify.report` (SPEC
2.6/F7); the SWEEP path (`sweep.sweep` -> `_capture_item`, `sweep.py`, called
by `_run_sweep` with nothing wrapping it, `cli.py` ~line 628) has **no
per-item exception handling at all**, so an uncaught exception from
`_capture_locked` during a sweep aborts the whole `ccw sweep` process before
its report is ever built - nothing printed, nothing logged, and every
still-queued item in that run silently deferred to the next sweep rather
than lost. This is a more complete account of "silently" than the ticket's
own framing (a caught-but-unreported failure); it is still analysis, not a
live occurrence, and the fix (sweep-side per-item exception handling) is
deliberately UNSHIPPED, matching the same "don't fix an unconfirmed cause"
instruction.

Also found by reading `catalog.py`'s `writing()` before writing the log
wrapper: `add_session` and `record_event` are two SEPARATE transactions on
one connection, so a session CAN end up cataloged (the `session` row
committed) with no corresponding `stored` `capture_event` row, if
`record_event` is specifically the one that fails - a real partial-state
case the new stage label distinguishes from "nothing cataloged at all"
(an `add_session`-stage failure) for the first time.

**Decision, recorded per the ticket's instruction: 31.3 does not make this
moot.** 31.3 removed the ~16,382/day `skipped_unchanged` catalog writes
entirely; the suspected contention population was always the FRESH-IDENTITY
`add_session`/`record_event` pair (`stored` rows, 753/day, measured today),
which 31.3 never touched - it only ever ran the skip path, which never wrote
`stored`. Lower overall daily DB traffic plausibly lowers contention
probability as a side effect; that is not the same claim as a fix, and it is
not measured. The retry loop stays where the ticket left it: blocked on a
confirmed exception, which has not recurred (0 `capture_event` rows with
`action='error'` in the live catalog, and neither new wrap has fired) as of
this session.

Oracle tests: `tests/test_capture_stage_logging.py` (new, 2), RED-confirmed
via `git stash` on `capture.py` alone. Gates: `uv run pytest` 1109 passed
(the sole remaining failure, `.envrc` untracked, predates this session and
is not a file either 31.4 or 31.5 touches), `uv run pyright` 0 errors,
`uv run ruff check` clean.

**2026-08-20, ticket 31.5: A SAMPLED `ccw doctor` CHECK, SCOPED TO RECENT
FOLDERS BY DESIGN.** `archive.verify_folder`'s "JSONL does not match manifest
source_hash" check is exactly the instrument that found the real broken
folder (1 of 21,669), but only when run by hand via `ccw archive --verify`.
`doctor.py` gained a new `desync` check (blocking, same as `overdue`):
`doctor._recent_archive_folders` collects every archive folder via the
existing `archive.walk_folders`, reads each folder-name-encoded start
timestamp (R12, never mtime - `doctor._folder_moment`, already used by
`overdue`), and re-sorts globally by that moment (walk_folders is only
chronological WITHIN one label). `doctor._desync` then runs `archive.
verify_folder` against just the `_DESYNC_SAMPLE = 25` most recent. Decision,
recorded rather than defaulted silently: a desync from an in-flight capture
failure shows up in sessions just captured, not one archived months ago, so
a small bounded recent sample catches the exact failure mode this ticket
exists for, without re-adding the O(everything) cost ticket 31 removes
elsewhere. An old, long-standing desync outside the sample is explicitly NOT
caught by this check - `ccw archive --verify` over the full tree (by hand,
or the weekly `com.captaincodeau.ccw-archive` job) stays the complete
answer. `ccw doctor`'s existing text-output compatibility surface (the
`hook` line and `Uncaptured: N session(s)` figure `ccw-watch` regexes) is
untouched: `desync` is a new, distinctly-named check appended after
`overdue`.

Oracle tests: `tests/test_doctor.py` (+2) - one CLI-level (tamper a real
archived JSONL, assert non-zero exit and the folder named in the report),
one in-process against `doctor._desync` directly (the sample size is a
module constant, not a subprocess-overridable flag) proving the scope
decision itself: an old tampered folder outside a sample of 1 is invisible,
the same folder back in-sample (25) is caught. RED-confirmed via `git stash`
on `doctor.py` alone. Gates: same pytest/ruff run as 31.4 above; `uv run
pyright` needed `# pyright: ignore[reportPrivateUsage]` on the two direct
`_desync` calls (no existing codebase precedent for a test calling another
module's private function, so this was the narrower fix over making
`_desync` public for a use it does not otherwise need). `tests/golden/
matrix-anchor` untouched (re-run directly, 61 passed) - doctor's output is
not part of the projected matrix.

Ticket 31 is CLOSED as of this entry: 31.1 (folded into 31.2), 31.2, 31.3,
31.4, and 31.5 all DONE.

## 16. Version cut (from BRAINSTORM, restated as the build order)

v1: store + catalog + registry, hook + sweep, 4-file render, notify (+webhooks),
migrate + retire, relocate, share static site, status/verify, config. v1.1: FTS5 +
`ccw search` (session AND message hits) + HTML archive search + `ccw import`/inbox.
v1.2: `ccw mcp` (search, get-session, list-projects, stats). Later per BRAINSTORM.
v1.1 opens with the flag-group slices 14-17 (section 15 entry, 2026-08-01) before
FTS5/search/import.
