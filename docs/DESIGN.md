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
| `conversation.html` | single-page HTML: collapsible turns and phases, per-block copy-as-md, sticky toolbar, width/font toggles, elapsed times, Catppuccin-derived palette. NOT fully self-contained: highlight.js from CDN with graceful onerror fallback is the ONE permitted external reference (matching the exporter); whether shares inline it instead is an open decision (section 15) |
| `conversation.compact.html` | conversation-only page, same chrome |

Fixed policies (locked in brainstorm): thinking + tool calls ON in full variants;
thinking label TYPE and CAPTION stored separately, joined with `|` at render time;
system-reminder blocks COLLAPSED in full variants, STRIPPED in compact variants,
config-overridable for PERSONAL projections only (share builds ignore the override,
section 9); message anchors are unique (turn ordinal + short content hash, fixing
SPEC's `make_msg_id` collision); `manifest.json` records config, counts, and loss
telemetry so "did we lose anything" is always answerable (exporter principle).

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
as informational extras. Turns carry entry timestamps so the emitters show per-turn
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
| `ccw sweep` | import anything the hook missed from `~/.claude/projects` (or `--source`) |
| `ccw render` | (re)build the 4 files for `--session s:<hash>`; or render an ad-hoc `<path>` outside the store to `--out` (default: a temp dir, path printed), never under `projections/`, never touching the catalog; honors the content flags |
| `ccw build` | rebuild projections from the catalog; incremental by default, `--rebuild` for full, `--include-hidden` for hidden sessions; honors the content flags |
| `ccw migrate` | one-shot import of the legacy archive (section 10) |
| `ccw relocate` | move/rename a project across the external world (section 11) |
| `ccw project` | `list` / `show` / `rename` (label) / `move OLD NEW` (alias) / `merge A B` |
| `ccw share` | build a sanitized static site for chosen sessions (section 9) |
| `ccw status` | recent captures, counts, store size, last errors (reads catalog + log only) |
| `ccw verify` | re-hash objects against their names; catalog/object cross-check |
| `ccw version` | version (also `-v`) |
| v1.1: `ccw search`, `ccw import`; v1.2: `ccw mcp` | per BRAINSTORM cut |

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
adds `--EXPOSED` (section 9). Later flag groups (per-file matrix, HTML chrome defaults,
truncation, date-locale, `--since`/`--until`) are the v1.1 surface.

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
extras tool_output**; `[share]` redact_patterns; `[relocate]` roots; `[import]` inbox;
`[[notify.webhook]]` name url events template; `[project.<id>.<table>]` overrides. The
render toggles all default ON. Desktop notification is ALWAYS on (locked); voice,
open-folder, and webhooks are opt-in. TOML parsing is stdlib `tomllib`.

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
- R2 `atomic_write` is the only write path for files; direct `write_text`/`open("w")`
  on final paths is a rejection (F2). Sanctioned exceptions, closed list: SQLite's own
  catalog writes, the O_APPEND audit log, O_EXCL lock create/remove (section 13).
- R3 All grouping/joins go through project IDs; display labels and paths appear only
  at the presentation edge (F4).
- R4 Warehouse data is delete-free: no deletion primitives against the store, the
  catalog, or capture/import/migrate SOURCES (append/soft-flag only, F9); sources are
  read-only. Deletions are sanctioned ONLY in the projections/shares rebuild module.
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
6. PyPI name final check (`cc-warehouse` availability re-verified before repo goes
   public; spot-checked only).
7. Registry backup/export story (the registry is non-derivable live state, section 1):
   likely a `ccw project export` JSON dump; decide by the catalog slice.
8. Shares and highlight.js: inline it into shared pages (true self-containment,
   bigger files) vs keep the CDN reference (privacy note in the share report).
   Personal projections keep the CDN + fallback either way (exporter parity).
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

## 16. Version cut (from BRAINSTORM, restated as the build order)

v1: store + catalog + registry, hook + sweep, 4-file render, notify (+webhooks),
migrate + retire, relocate, share static site, status/verify, config. v1.1: FTS5 +
`ccw search` (session AND message hits) + HTML archive search + `ccw import`/inbox.
v1.2: `ccw mcp` (search, get-session, list-projects, stats). Later per BRAINSTORM.
