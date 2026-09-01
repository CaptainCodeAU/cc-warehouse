# SPEC - the specimen's actual behavior, with keep / change / drop verdicts

**Status:** Phase 1 contract document, 2026-07-17. Specimen:
`~/CODE/CaptainCodeAU/claude-code-transcripts` at commit `2c8fea7` (0.8, 521 tests
green). Companions: `FINDINGS.md` (failure classes), `DESIGN.md` (the new system),
`BRAINSTORM.md` (approved scope), `HARNESS.md` (build process).

**Method.** Every statement here was derived by reading the specimen's source, not its
documentation (the docs are proven to overpromise; see FINDINGS F6). File references are
to the specimen repo. This is the parity checklist: `KEEP` behaviors must survive into
cc-warehouse (possibly re-implemented), `CHANGE` behaviors survive with stated
differences, `DROP` behaviors die with the specimen. Oracle tests for KEEP items are
derived from this document, never ported from the specimen's suite (FINDINGS F6).

**Verdict legend:** `KEEP` preserve observable behavior | `CHANGE` preserve intent,
different mechanics (difference stated inline) | `DROP` not carried (reason inline).

---

## 1. Package shape and layering

- Layered package: stdlib-only `core/` (naming, jsonl, summary, archive, github,
  analysis, resolve, idempotency) + stdlib `notify.py`/`spawn.py`/`picker.py`, lazy
  `render/` (jinja2+markdown), lazy `fetch/` (httpx), `cli.py` (argparse).
  `__init__.py` is a PEP 562 lazy shim. Zero-dep fence test asserts `core` imports pull
  no third-party modules (`tests/test_core_zero_deps.py`).
  **KEEP the principles** (layering, import hygiene, fence tests as a gate style);
  **CHANGE the split**: cc-warehouse is stdlib-only everywhere, so the fence becomes
  "no third-party imports anywhere" plus a write-primitive fence (FINDINGS F9).
- 4 runtime deps (httpx, jinja2, markdown, pymdown-extensions), each confined to one
  layer. **DROP:** stdlib-only is locked; each dep's role is reimplemented (md
  rendering in-house, urllib for any fetch, string templates or generated HTML).

## 2. CLI surface and dispatch (`cli.py`)

- Entry point `claude-code-transcripts`; subcommands `{local, json, web, all, render,
  hook}`; bare invocation or unknown-leading-arg dispatches to `local`
  (`parse_args_with_default_subcommand`, cli.py:838-855); `-h/-v` pass through.
  **CHANGE:** new binary `ccw` with its own verb set (DESIGN section 7); no implicit
  default-subcommand trick (explicit verbs only; `ccw` with no args prints status +
  help). The specimen's `-v/--version` via `importlib.metadata`: KEEP.
- `CliError` maps to `Error: <msg>` on stderr, exit 1 (cli.py:53-58, 858-866). **KEEP**
  (same UX contract for `ccw`).

### 2.1 `local` (cli.py:98-178)

- Scans `~/.claude/projects` recursively, summary-parses EVERY jsonl, filters
  `warmup`/`(no summary)`, sorts by mtime, shows arrow-key picker of `--limit` (10)
  rows: date, size KB, truncated summary. Renders picked session; `--json` copies the
  jsonl in (default ON across local/json/web/all; `--no-json` disables: an opt-OUT,
  which changes default output contents); auto-opens browser when no `-o`/`--gist`/`-a`.
  **DROP as a command** (not selected as a must-keep; superseded by `ccw search` +
  catalog-backed listing in v1.1). The full-corpus scan is banned outright (FINDINGS
  F5). The stdlib picker WIDGET (`picker.py`: termios raw mode, TCSANOW enter/restore,
  k/j + arrows, graceful non-TTY cancel) is **KEEP** as a reusable component for any
  future interactive selection.

### 2.2 `json` (cli.py:220-282)

- Positional file-or-URL; URLs fetched via httpx to a temp file with suffix inference
  (cli.py:186-217); output dir defaulting and `-a` auto-naming; `--json` copy-in;
  auto-open logic identical to `local`.
  **CHANGE:** becomes `ccw render <path>` semantics for ad-hoc files (render without
  capture) plus `ccw import` for bringing files INTO the store. URL fetching: KEEP the
  capability with urllib (stdlib), same suffix inference intent.

### 2.3 `web` (cli.py:317-421, fetch/)

- Sessions API list + teleport-events pagination (limit 1000, cursor, 404 fallback to
  legacy session_ingress, mid-pagination 404 returns partial;
  fetch/api.py:19-114), keychain token (`Claude Code-credentials` generic password ->
  `claudeAiOauth.accessToken`, macOS only) + `~/.claude.json` org UUID
  (fetch/credentials.py), repo enrichment/filtering from session metadata
  (core/github.py:38-104), picker when no SESSION_ID.
  Reference caveat: pagination silently caps at `max_pages=100` (~100k entries) and
  truncates without error (fetch/api.py:78-80).
  **DROP for v1** (not a must-keep; claude.ai content arrives via exporter bundles and
  `ccw import` in v1.1). The API knowledge above is recorded here as the reference if a
  direct fetch source is ever added as a new source kind (BRAINSTORM someday bucket).

### 2.4 `all` (cli.py:424-514, render/html.py:26-110)

- Walks a source tree, groups sessions by parent dir name keyed lossily, renders every
  session, writes per-project and master indexes, `--dry-run` listing, `--quiet`,
  per-session failure collection (continues past failures, reports at end), progress
  callback every 10.
  **CHANGE:** becomes `ccw build` (rebuild projections from the catalog). KEEP:
  continue-past-failures with an end-of-run failure report; dry-run; quiet. DROP: the
  master/project/session index-page hierarchy and pagination (rejected bucket);
  display-name output keying (FINDINGS F4).

### 2.5 `render` (cli.py:517-535)

- Renders one already-filed jsonl into `-o`; on exception notifies error and re-raises
  (the detached child's only surviving signal); `TRANSCRIPT_OPEN_FOLDER=1` reveals the
  folder after HTML exists (deliberate ordering to avoid the empty-folder race).
  **KEEP the concept and both details** (error-notify-from-child; reveal only after
  files exist) in the new render child.

### 2.6 `hook` (cli.py:538-605)

- Reads SessionEnd JSON payload from stdin: `session_id`, `transcript_path`, `cwd`.
  `SKIP_SESSION_END_HOOK=1` no-ops. Missing/invalid payload or missing transcript ->
  error notify, exit without raising. Resolves project cwd-first, computes
  `<EXPORT_DIR>/<project>/<uuid>/`, size-based skip (section 4), copies jsonl, notifies
  ok with elapsed ms + resolution source label, spawns detached render.
  **KEEP the shape** (stdin payload contract incl. the three fields; env kill switch;
  never-raise-into-the-harness posture; fast exit with elapsed-ms reporting; detached
  render). **CHANGE the mechanics per FINDINGS:** hash-first identity, atomic store
  write, catalog row in a transaction, layout keyed by project ID (DESIGN section 4).

## 3. Naming and project resolution

- Encoding: cwd -> key by replacing `/`, `_`, `.` with `-` (core/resolve.py:15-17);
  lossy and irreversible. **KEEP the encoder only as an input normalizer** for matching
  against Claude Code's own folder names; it is never an identity (FINDINGS F4).
- Display name derivation (core/naming.py:10-62): strip prefixes (`-home-`,
  `-mnt-c-Users-`, `-Users-` case-insensitively), split on `-`, skip a leading username
  segment when a known dir follows, skip `skip_dirs` = {projects, code, repos, src,
  dev, work, documents}, join the rest; fallback last non-empty part.
  **CHANGE:** survives only as the DEFAULT LABEL suggestion when a project is first
  seen; the registry stores it as a mutable label. All grouping is by project ID.
- Resolution order (core/resolve.py:40-61): payload cwd -> first jsonl `cwd` ->
  transcript parent dir name -> `_unresolved`, each with a source label that is
  reported in notifications. **KEEP order, labels, and reporting** (they feed the
  registry attribution instead of a folder name).

## 4. Idempotency / skip

- `should_skip` (core/idempotency.py): skip iff `index.html` AND `<uuid>.jsonl` exist
  in the target AND archived size == source size; any OSError -> do not skip.
  **DROP the size proxy** (FINDINGS F1): the replacement is hash equality against the
  catalog. KEEP the observable outcomes: a re-fired unchanged session reports
  "skipped/unchanged"; a grown transcript re-captures (append-only JSONL means the
  hash changes); the skip branch still honors the open-folder opt-in (cli.py:582-584).

## 5. Capture pipeline plumbing

- `spawn.spawn_render` (spawn.py): detached child via `start_new_session=True`, all
  stdio to DEVNULL, `sys.executable -m <package> render ...`. **KEEP** verbatim
  pattern for the projection child.
- Notifications (notify.py): desktop (osascript / notify-send, best-effort Popen),
  opt-in voice POST via curl subprocess with 2s connect timeout
  (`TRANSCRIPT_VOICE_URL`/`_ID`), JSONL log line appended to
  `~/.claude/logs/transcript-export.log` with ts/session/project/status/duration/
  source/cwd, `report()` fanning out log+desktop+voice by status, `open_folder`
  best-effort. **KEEP all**, **CHANGE:** add config-driven webhook sinks (Telegram
  etc., BRAINSTORM notify lock); log path moves under the warehouse; every sink stays
  best-effort so capture never fails on notification infrastructure.
- Env vars honored: `TRANSCRIPT_EXPORT_DIR` (default `~/claude-code-transcripts`),
  `SKIP_SESSION_END_HOOK`, `TRANSCRIPT_VOICE_URL`, `TRANSCRIPT_VOICE_ID`,
  `TRANSCRIPT_OPEN_FOLDER`. **CHANGE:** renamed under one `CCW_` prefix with TOML
  equivalents (DESIGN section 8); a compatibility note in migrate docs maps old names.

## 6. Session parsing and the conversation model

- JSONL parse (core/jsonl.py:49-81): keeps only `user`/`assistant` typed lines;
  extracts `type`, `timestamp`, `message`, `isCompactSummary`; skips unparseable lines
  silently. **CHANGE:** the new parser preserves MORE raw fields (cwd, sessionId,
  gitBranch, slug, version) for the catalog, and it must count and report skipped/
  malformed lines (silent data loss is a guarantee-drift smell, FINDINGS F6). JSON
  (non-JSONL) session files with a `loglines` key: KEEP as an accepted input format.
- Content text extraction handles string or block-array content, text blocks only
  (core/jsonl.py:7-30). **KEEP.**
- Task-notification entries (`<task-notification>` string content) are machine
  messages: never user prompts, never conversation starters, rendered as tool-reply
  role (core/jsonl.py:93-104, render/blocks.py:221-229). **KEEP** (hard-won upstream
  fix; oracle test required).
- Conversation grouping (render/html.py:141-173): a non-task-notification user message
  with text starts a conversation; subsequent entries append to the current one, but
  entries BEFORE the first user prompt are silently dropped (the `elif current_conv`
  guard at 169-170); `isCompactSummary` marks a continuation, rendered collapsed and
  merged into the previous prompt's stats; prompts starting with `Stop hook feedback:`
  are excluded from the index timeline. **KEEP the semantics** that define "turn",
  **CHANGE the pre-first-prompt drop:** the new renderer must render or at minimum
  count such entries in manifest telemetry; silent loss violates the did-we-lose-
  anything principle.
- Analysis (core/analysis.py): tool-use counts, long-text collection (>=300 chars),
  commit detection via `\[[\w\-/]+ ([a-f0-9]{7,})\] (.+?)(?:\n|$)` over tool_result
  strings (the `(?:\n|$)` terminator is load-bearing: without it the lazy group
  matches one character), timestamped. **KEEP** (feeds header stats and commit cards
  in the new render).
- GitHub repo auto-detection from `git push` output (`github.com/<owner>/<repo>/pull/new/`,
  core/github.py:7-35). **KEEP** (commit links in the new HTML).

## 7. Rendering semantics (specimen HTML)

- Structure: 5 prompts per page (`page-NNN.html`) + `index.html` timeline with
  pagination, stats line, search modal (`templates/`, `render/html.py`).
  **DROP wholesale:** replaced by the exporter-style 4-file model (BRAINSTORM render
  lock). The following semantic behaviors survive into the new renderer:
  - tool-specific rendering: Bash (command+description), Edit (old/new diff,
    replace_all), Write (path+content), TodoWrite (status-markered task list), generic
    tool_use JSON, tool_result with commit cards + image blocks + error styling
    (render/blocks.py). **KEEP as semantics** (the new HTML groups them into
    collapsible phases per the exporter reference). Specimen caveat for oracle
    authors: `generate_html` and `generate_html_from_session_data` are ~170-line
    near-verbatim duplicates in one file (render/html.py:122-297 vs 300-469) and the
    `web` path renders through the SECOND copy; every KEEP semantic here exists twice
    in the specimen (FINDINGS F8), once in cc-warehouse.
  - copy-as-markdown instrumentation: every block carries its raw source
    (base64 `data-copy-src`), todo lists serialize to markdown task lists, edit tools
    to a unified-diff-like payload (render/blocks.py, render/markdown_ext.py).
    **KEEP** (exporter model does the same; payloads must equal the transcript.md
    fragments; oracle test).
  - markdown hardening: blank-line insertion before loose lists, trailing orphan fence
    stripping, fence-aware processing (render/markdown_ext.py:74-138). **KEEP** in the
    in-house md renderer.
  - `make_msg_id` anchors derive from timestamp only and can collide within the same
    timestamp (render/blocks.py:210-211). **CHANGE:** anchors must be unique (ordinal
    or hash-suffixed); message-level search deep links depend on it.
- Dark/light theme with localStorage toggle, embedded CSS/JS strings
  (render/assets.py, base.html). **DROP:** the new pages ship the exporter's
  Catppuccin-derived single-page look with width/font toggles.
- Gist publishing + gisthost preview JS injection (cli.py:60-95, render/gist.py).
  **DROP** (rejected bucket: superseded by static-site share).

## 8. Summary extraction and filtering

- Priority: first `type: summary` line's `summary` field; else first non-meta user
  message with non-`<`-prefixed text; 200-char cap with ellipsis; any failure ->
  `(no summary)` (core/summary.py:9-81). Sessions summarized `warmup` or
  `(no summary)` are hidden from listings (summary.py:100, archive.py:33).
  **KEEP** extraction priority and the warmup/no-summary hiding as catalog fields
  computed once at capture (FINDINGS F5), not re-derived per listing.
  Note (2026-07-23): this summary rule is unchanged. The RENDER title (the H1 / page
  title) is a separate concern and now prefers Claude Code's own `ai-title` entry over
  this summary-derived fallback (DESIGN section 6); the catalog `summary` field and the
  hidden logic still use the rule above.
  **AMENDED 2026-09-01 (principal ruling, DESIGN section 15).** The extraction priority
  and the display text ("(no summary)" when there's no candidate) are still KEEP,
  unchanged. Only the no-summary-candidate branch's HIDDEN decision is narrowed: it no
  longer hides unconditionally, but only when the session ALSO shows no substantial
  assistant engagement (fewer than two assistant turns with real text or a tool call -
  `parser._has_substantial_engagement`). Found because the reused signal conflated "no
  good display title" with "worth rendering": a session started by a slash command
  (excluded from the title candidate on purpose, being `<`-prefixed) and then run
  autonomously with no further typed user text was hidden even with substantial real
  work, measured on the live archive up to 1,010 lines / 216 assistant turns / 126 tool
  calls, permanently unrendered with zero warning. The `warmup` branch (a candidate
  exists but reads as `warmup`) is untouched.
- Agent-session filtering: files named `agent-*` are ALWAYS excluded from `local`
  (summary.py:96-97) and excluded by default from `all` with an `--include-agents`
  opt-in (archive.py:28-29, cli.py:782-786). **CHANGE:** cc-warehouse captures and
  catalogs agent sessions like any payload (the store never discriminates), but
  `sweep` skips `agent-*` by default (config opt-in) and cataloged agent sessions
  default to `hidden` in listings.
  **AMENDED 2026-08-03 (ticket 21, principal).** The opt-in exists as
  `archive_subagents` and DEFAULTS ON, because the premise changed: `~/.claude` is
  being cleared once the archive is backed up, so anything a sweep declines to
  take is DESTROYED rather than deferred. Measured before the change: 1,420
  sub-agent transcripts, 328.5 MiB, and only 7.3% of their content appears in the
  parent session, so 92.7% would have existed nowhere else.
  Two corrections ride with it. A sub-agent is identified by CONTENT
  (every conversational entry carries an `agentId`), never by the `agent-`
  filename - F4 forbids path-as-identity, and the old rule was exactly that.
  And a sub-agent is NOT a session: it carries its PARENT'S `sessionId`, so
  ruling (a)'s test said yes to every one of them, and acting on that would have
  filed a sub-agent under the parent's name and let replace-if-larger overwrite
  the parent's transcript. Sub-agents are archived into
  `<session>/subagents/<stamp>_<agentId>/` and get no catalog row, no markdown
  and no HTML; rendering them is recorded as future work behind its own flag.

## 9. Batch failure posture

- `generate_batch_html` records per-session failures and keeps going; the CLI prints a
  failure list at the end and still writes indexes (render/html.py:77-97,
  cli.py:499-503). **KEEP** for `ccw build`, `migrate`, `sweep`, `import`: item
  failures never abort the batch, and the end-of-run report names each failed item
  (FINDINGS F7: failures also never reclassify an item into a destructive branch).

## 10. Scripts (standalone, import from the package)

### 10.1 `scripts/reconcile_sessions.py` (both modes; agent-verified against source)

- Orphan mode: orphans are TOP-LEVEL archive dirs whose name matches the canonical
  UUID pattern (find_uuid_folders:707); categorize by precedence JSONL > HTML-only >
  empty > other (categorize_folder:202); project derived from the first non-empty
  jsonl `cwd`, else (HTML-only) a path regex over the HTML, else `_UNKNOWN`;
  case-insensitive matching against existing project dirs (resolve_target_project:252;
  the dir enumeration that skips dot/underscore-prefixed and UUID-named entries lives
  in list_existing_projects:304-312).
- Duplicate handling (compare_session_copies:366-409, _handle_duplicate:418): jsonl
  size decides (larger wins; equal = "identical"); one-sided jsonl wins; NEITHER side
  jsonl falls back to max-file-mtime with a 60-second tolerance band; OSError returns
  "identical" (FINDINGS F7). Orphan-wins = REPLACE (loser backed up to
  `_DELETE/replaced/`); otherwise the orphan is a duplicate destined for
  `_DELETE/duplicates/`.
- HTML regeneration happens BEFORE the move, into the still-in-place orphan folder,
  by shelling out to `uv run claude-code-transcripts json ... --no-json` with a 60s
  timeout; skipped entirely for `_UNKNOWN`-destined sessions (the `not is_unknown`
  guard at 520); a regen failure is reported ("moved with stale HTML") but the move
  still proceeds (process_category_a:520-548).
- Six per-group confirmations in fixed order (replaces, moves, unknowns, duplicate
  orphans, empties, unrecognized; main:1712-1786); declining one group skips it and
  continues. `_DELETE/{replaced,duplicates,empty,unrecognized}` taxonomy with `-1/-2`
  collision suffixes (move_to_delete_folder:1185-1201).
- Mtime correction at three points (moved session dirs, `_DELETE` destinations,
  affected project dirs) to the last JSONL internal timestamp (fix_session_mtime:127,
  fix_project_mtime:141); conditional reindex only when the archive actually changed.
- Drift mode (`--merge-drift`): iterate every session under every non-`_` project
  (`_is_session_dir`:412 counts a dir by UUID name OR jsonl/html content), re-derive
  from jsonl cwd (no-jsonl / no-cwd skipped with reason, left in place), classify
  MOVE / DEDUPE_IDENTICAL (size-equal, to `_DELETE/drift-dedupe/<wrong>/`) / CONFLICT
  (left in place, richer copy reported); ONE combined confirmation covering actions +
  drains; then a WHOLE-archive drain of non-`_` project dirs empty of session data
  (dotfile-aware `_project_dir_is_empty`:1423) to `_DELETE/drift-empty-projects/`;
  idempotent by full rescan. Known defect: collision is checked at plan time but not
  re-checked at apply time (TOCTOU; FINDINGS F3).
- `--fix-mtimes`: archive-wide session + project mtime correction to JSONL internals,
  independent of the other flows; real-run only.
- Non-TTY stdin auto-confirms every group (confirm:1256; FINDINGS F10).
- **DROP the machinery** (content-hash identity + the registry remove its reason to
  exist; BRAINSTORM rejected bucket) and **KEEP three principles as design rules:**
  (1) soft-delete only, with collision-suffixed destinations (FINDINGS F9);
  (2) authoritative timestamps come from JSONL internals, never file mtimes;
  (3) cleanup passes scan the whole target and are idempotent, dotfile-aware.

### 10.2 `scripts/migrate_project.py` (agent-verified against source)

- Moves a repo to `{os_root}/{owner or 3rdParty}/<LOCAL dir name>` (the local folder
  name, NOT the remote repo name; main:360). Owner from the git origin remote
  (HTTPS/SSH regex, parse_remote_url:61); own-account detection = remote host appears
  as a `Host git-*` alias in `~/.ssh/config.local`; anything else prompts for
  3rdParty/custom (prompt_3rdparty:260; `n` aborts the whole run). os_root: Darwin
  `~/CODE`, else `~/repos`.
- Safety: requires repo ROOT (not a subdir), refuses a non-empty target, no-ops when
  already in place, `--dry-run` prints the full plan and exits before the proceed
  prompt; caveat: the 3rdParty owner prompt fires BEFORE the dry-run exit, so an
  interactive dry-run on an unknown owner still prompts (and `n` exits 1).
- Execution order (main:471-538): mkdir target parent -> move repo -> rewrite memory
  file CONTENTS while Claude dirs still hold old names -> rename `~/.claude/projects/`
  encoded dirs -> rename the archive folder. Content rewriting applies three patterns
  (absolute path, tilde form, encoded form) to EVERY file under `memory/**` regardless
  of extension; nothing outside `memory/` is ever string-edited (dirs are renamed
  instead). Encoded-dir matching is prefix + boundary guard: the remainder must be
  empty or start with `-` (find_matching_directories:157).
- Non-TTY stdin auto-proceeds (confirm:247; FINDINGS F10). Archive rename only when
  the display names actually differ (main:416-423).
- **DROP the script; KEEP the hard-learned mechanics** for `ccw relocate`: contents
  before containers; full plan first; refuse non-empty targets; boundary-guarded
  prefix matching; dry-run default posture (DESIGN section 11).
- CORRECTION to the boundary-guard mechanic (decided 2026-07-19, principal; slice-12
  round 2 proved it by execution): the specimen's prefix + boundary rule is necessary
  but NOT sufficient. Its own encoder collapses `/`, `_` and `.` to `-`, so a repo
  SUBDIRECTORY and an unrelated SIBLING repo encode to the same name (`<repo>/two` and
  `<repo>-two` both give `...-two`), and the rule as written renames the sibling's
  transcript dir onto the relocated project. cc-warehouse keeps the boundary rule as a
  filter but requires PROOF of ownership before renaming; see DESIGN section 11. This is
  a deliberate divergence from the specimen, not a port of it.

## 11. Tests and CI posture (specimen facts that matter to Phase 2)

- 521 tests, 15 test modules + conftest, 18 HTML snapshots; heaviest on reconcile
  (151) and HTML (125);
  hook/spawn/idempotency thin (1-6 each); `TestCompareSessionCopies` encodes F1 as
  expected behavior. **Consequence (not a verdict):** oracle tests are written fresh;
  the specimen suite is reference material for edge-case IDEAS only.
- CI: ubuntu+macOS matrix (Windows dropped deliberately); publish workflow
  neutralized. cc-warehouse: same POSIX-only posture (BRAINSTORM non-goal), PyPI
  publishing IS planned (new name, reversed decision).

---

## Verdict summary

| Area | KEEP | CHANGE | DROP |
|---|---|---|---|
| CLI | error contract, version flag, picker widget | dispatch model (`ccw` verbs), json->render/import, all->build, hook mechanics | local, web, gist, default-subcommand trick |
| Identity | resolution order + source labels | display name becomes a label via registry | size-as-identity, path-as-identity |
| Capture | payload contract, kill switch, detached render, elapsed reporting, never-raise | atomic hash-first store + catalog | size skip |
| Notify | desktop/voice/log/open-folder, best-effort posture | + webhook sinks, CCW_ env names | - |
| Parsing/render | task-notification rule, grouping/continuations, tool semantics, copy-as-md, md hardening, commit detection | unique anchors, richer raw fields, malformed-line accounting | pagination, timeline index, themes, gist JS |
| Scripts | soft-delete + JSONL-timestamp + idempotent-sweep principles, migrate sequencing | absorbed into registry/relocate | both scripts as artifacts |
