# Ticket 38: archive the sidecar folders (`tool-results/`, `workflows/`) and add an unknown-sibling signal

Opened 2026-09-06. **PLANNED, NOT STARTED.** The whole file below is the approved plan from the planning session (handoff 23), saved here because `Plans/` is gitignored. The execution session builds slices 38a-38f in order, oracle tests first, and appends the FINDINGS-re-derived-by-execution, Acceptance results and the `DONE <date>` block at the bottom in ticket 37's shape. 38g is a follow-up needing its own ruling.

---


Written 2026-09-06 in plan mode (nothing in the repo was changed). Every number here was
measured this session against the live `~/.claude/projects` tree and `~/cc-warehouse-archive`
unless marked otherwise. Two Plan agents produced a mechanism design and a red-team review;
every load-bearing claim of theirs that reached this file was re-checked in source by the
lead session, and two of their claims were corrected (noted inline). Their full write-ups
lived in the session scratchpad and are NOT committed; this file is the one that survives.

The execution session should read, in order: this file, `harness/tickets/21-subagent-
transcripts.md` (the twin feature), `harness/tickets/37-*.md` (the daily-rewrite bug the
new writes must not reintroduce), `contract/DESIGN.md` section 14 (R1-R14), and
`contract/FINDINGS.md`.

## 1. Context: the problem, measured

Claude Code writes per-session sidecar folders at `~/.claude/projects/<proj>/<session-uuid>/`
beside `<session-uuid>.jsonl`. cc-warehouse archives one of them (`subagents/`, ticket 21)
and has never looked at the others. A census of every `<uuid>/` dir (1,196 real ones) found
exactly four child names:

| child | dirs | archived today? |
|---|---|---|
| `tool-results/` | 1,067 | **no** (0 references in `src/`, census-proven over 26 files with a control hit) |
| `subagents/` | 481 | yes, ticket 21 |
| `workflows/` | 9 | **no** |
| `.DS_Store` | 79 | ignorable |

**What `tool-results/` holds.** 2,084 files, 135.7 MB. Names: `hook-<uuid>-stdout.txt`
(1,067, exactly one per dir, a hook's captured stdout; the uuid is per invocation and NEVER
equals the session uuid, 0 of 1,067), `[a-z0-9]{9}.txt` (856, oversized tool output),
`toolu_<id>.{txt,json}` (42, older naming), `mcp-<server>-<tool>-<ts>.txt` (6),
`artifact-*.html`, `webfetch-*.pdf` (8), and the only nesting, `pdf-<uuid>/page-NN.jpg`
(72 files in 19 dirs). Largest file 3.3 MB, largest dir 6.8 MB. New name shapes appear
often; the copier must mirror the tree, not match names.

**How the JSONL points at them.** A `user` entry whose `message.content[0]` is a
`tool_result` with content `<persisted-output>\nOutput too large (132.9KB). Full output
saved to: <absolute path>\n\nPreview (first 2KB):\n...`, and whose `toolUseResult` dict
carries `stdout`, `stderr`, `interrupted`, `isImage`, `noOutputExpected`,
`persistedOutputPath`. **`toolUseResult.stdout` is itself capped** (measured: 29,574 of
136,057 bytes on one file). Sub-agent JSONLs (331 of 2,533) point at their PARENT's dir;
there is no per-sub-agent `tool-results`. `pdf-*/page-NN.jpg` are referenced by no JSONL.

**How much is genuinely only there.** A byte check of every file against every JSONL in its
session (parent plus sub-agents): **65.4 MB of the 135.7 MB exists in no JSONL** (all 1,067
hook-stdout files, 419 of 856 overflow files, 15 of 42 `toolu_` files, every pdf/jpg). The
rest is a redundant copy of `toolUseResult.stdout`. So this is real data loss on roughly
half the files, since the feature appeared on 2026-05-08 (four months unnoticed).

**Rendering today** shows the capped `toolUseResult.stdout` (default `tool_output` on) and
the manifest's `loss` block reports 0 for it. That is the F6 overclaim shape. There is zero
handling of `persisted-output` in `src/`.

**Why it went unnoticed.** Nothing in the product ever enumerates what sits beside a
transcript. `capture.py:366` asks for `subagents/` by name and ignores everything else. This
is the general defect the operator asked to close: the next unknown sibling must announce
itself.

**The same shape, found while looking.** Three more things the current copier skips:
- `subagents/workflows/wf_<id>/agent-*.jsonl` (Workflow-tool sub-agents; 432 files, 33 MB,
  211 distinct transcripts). The hook's `subagents.glob("*.jsonl")` is non-recursive and
  misses them; the daily sweep's `os.walk` catches them and **all 211 are in the archive
  today**. A hook-path gap with a working net; fix the hook anyway.
- `subagents/agent-<id>.forked-skill.json` and `.forked-skill.marker.json` (10 each): not
  copied by anything.
- `<uuid>/workflows/wf_<id>.json` + `workflows/scripts/<name>-wf_<id>.js` (9 sessions,
  1.1 MB): not copied by anything.

**Stranded sidecars.** 91 `<uuid>/` dirs have no `<uuid>.jsonl` beside them; 39 hold
`tool-results/`; of those 39, 4 match an archived session folder by uuid, 2 have a
transcript in a different project dir, 35 have no transcript anywhere (0.9 MB total, three
under a `/var/folders/.../T` temp project). Also: exactly 1 transcript in the source tree
has a stem that is not the bare uuid (`<uuid>.orphaned-<n>-<hash>.jsonl`, the blind spot
`status.py:96-101` already documents).

**Sanity checks that hold.** Session id inside the transcript equals the sidecar dir name in
450 of 450 sampled. The plugin hook script only shells out to `ccw hook`, so no `/plugin`
update is needed; the frozen `ccw` reinstall is. `ccw share` re-renders from the payload
into a fresh folder and copies no sidecars (`share.py:455-531`), so secrets in
`tool-results` cannot leak through sharing today. No `relocate_roots` are configured in the
live config, so `relocate`'s content rewrite cannot touch the archive today. The archive
holds 125 stray `.DS_Store` files inside session folders already; the copier and the scan
must ignore that name at every depth.

## 2. Rulings the principal takes before code (recorded in DESIGN 15)

**Ruling (c), sidecar identity.** Ticket 21's ruling (a) decides identity from content. A
`.txt` carries no `sessionId`, so the parent MUST come from the path:

> A sidecar file belongs to the session whose transcript sits beside the sidecar dir. The
> transcript's identity is still decided from its content (ruling (a)); the sidecar dir is
> located by that content uuid first (`<proj>/<session_uuid>/`) and by the file stem second.
> The dir name is a source-layout FILTER, the same exemption `sweep` already has for the
> `agent-` prefix (F4 fence). It is never used to file a sidecar whose transcript is absent
> as if it were a session.

**Ruling (d), stranded sidecars** (35 dirs with no transcript anywhere, 0.9 MB). My call:
copy them to `<archive>/_not-sessions/stranded-sidecars/<dirname>/` with a `stranded.json`
note (`{"schema":1,"dir_name":..., "reason":"no transcript found beside this dir"}`), the
dir name recorded as a label, not claimed as identity. Why: `_not-sessions/` already exists
for payloads without session identity, the archive is the deliverable, and 0.9 MB is the
whole cost. The alternative (leave them, count them in doctor) loses nothing today because
`~/.claude` is never deleted, but leaves the archive knowingly incomplete.

**Ruling (e), how an unknown sibling gets attention. TAKEN 2026-09-06 by the operator:
informational doctor line PLUS an OS-level alert.** The `sidecars` doctor line is never
blocking (doctor's exit code, `ccw-watch`'s banner and the freshness hook stay untouched by
it). Attention comes from a new desktop-notification sink fired at the moment a NEW anomaly
is recorded (the notice changed to a non-empty set), once per session per change, so it can
never nag daily. Same sentence goes to the existing voice sink, which this machine already
has configured to speak on capture failures. Guard still applies: the release must ship
`tool-results` and `workflows` in the known set, or every install alerts on day one.

**Rulings (d) TAKEN 2026-09-06: copy under `_not-sessions/stranded-sidecars/`. Scope
TAKEN: `tool-results/`, `workflows/` and the forked-skill files all in ticket 38.**
Ruling (c) is the one still to be formally recorded in DESIGN 15 by the execution session;
it records existing practice and the operator has not objected to it.

## 3. Scope decisions

| # | Decision | Call | Why |
|---|---|---|---|
| 1 | Layout | `<session>/<sidecar>/<original relative path>`, flat mirror, nesting kept | The JSONL path resolves by basename; a `<stamp>_` prefix would come from mtime (R12 forbids) |
| 2 | `workflows/` | Archive it in this ticket with the same generic copier | 9 dirs, 1.1 MB, zero extra design; otherwise the anomaly line is red on day one for a known thing |
| 3 | Non-standard files inside `subagents/` | Copy `agent-<id>.forked-skill*.json` into the matching `<stamp>_<agentId>/` folder (through `write_if_changed`, like `meta.json`); make the hook's glob recursive so `workflows/wf_*/agent-*.jsonl` reach `write_subagent`; anything else inside `subagents/` is an anomaly | Closes the hook gap; content still decides identity via `is_subagent` |
| 4 | Same name, different bytes | Refuse, record, never overwrite (new `store.write_if_absent`) | R5; there is no "larger wins" argument for a tool result, so no size branch at all |
| 5 | Skip rule on repeat runs | `write_if_absent` reads the target and compares bytes; never `exists()`, never size | F1/F4: location is not identity. Cost: source + target read, about 270 MB a day, a couple of seconds; measured hashing of 135.7 MB is about one second |
| 6 | Anomaly record | `sidecars.json` notice file in the session folder, NOT a manifest key | The manifest is re-rendered minutes later by `build`/the render child, which cannot see the source dir; ~617 hidden sessions have no manifest (28,787 JSONL vs 28,170 manifests); `folder_is_current` would need a compare or the key freezes |
| 7 | Manifest keys | `tool_results` and `workflows`: `[{name, sha256, bytes}]`, always present, `[]` when none, computed from the ARCHIVE folder at render time like `subagents` | DESIGN 6: new top-level keys, not `loss` amendments; `[]` distinguishes none from predates-the-feature (F6) |
| 8 | Verify strings | `tool-result <name> is missing` / `does not match its hash`; `workflow file <name> ...` | Must never start with `missing ` or doctor.py:409 reclassifies them as pending render |
| 9 | Sweep | Third pass over EVERY session path the walk yields, including `skipped_unchanged` ones; no change to `_walk_source` or the `source_transcripts` 2-tuple | A sidecar can arrive after the last capture with the JSONL hash unchanged; status.py:132 and doctor.py:465 consume the tuple |
| 10 | Config | `archive_tool_results: bool = True`, one switch for hook and sweep, governing `tool-results` and `workflows` | Ticket 21 finding 5 |
| 11 | Doctor | NEW line `sidecars`, informational (never blocking); corpus-wide (one stat of `sidecars.json` per archive folder, one scandir per project dir), never hashes | Ruling (e); existing lines are `ccw-watch`'s parse surface and stay byte-identical |
| 11b | Attention | New `notify.alert()` desktop sink (`osascript -e 'display notification'` on macOS, no-op elsewhere, best-effort, 3 s timeout) + `notify.speak()`; fired only when a notice CHANGES to non-empty | Ruling (e): "grab my attention" without a chronic red banner; dedup is the notice compare, so at most one alert per new anomaly |
| 12 | Render marker + `persisted` key | Separate slice 38g, own ruling, after the copy lands | Moves default output and the golden anchor |
| 13 | `ccw share` | Unchanged; sidecars never copied; 38g must not link them in shared output | Safe by construction today |
| 14 | `ccw archive --to` (migrate) | Unchanged; note in docs that a fresh `--to` tree carries no sidecars (it carries no sub-agents today either) | Out of scope; recorded |
| 15 | `cli.py:705` | `if stored or report.archived_sidecars:` | Verified: the post-sweep build runs only `if stored:`; a back-fill stores 0 |
| 16 | Version | 0.1.3, CHANGELOG, then `uv_tool_reinstall_current_project --no-extras` | `renderer_version` mismatch (archive.py:544) forces the one full rebuild that populates the new keys |

## 4. The mechanism

Reuse first: `store.atomic_write` (store.py:50), `store.write_if_changed` (store.py:71),
`notify.append_log` (notify.py:50, six keys `{at,status,session,project,message,elapsed_ms}`,
never `notify.report`, so no webhook or voice fires), `archive._parent_folder`
(archive.py:333), `archive.subagent_records`/`_with_subagents` (357/747) as the twins,
`archive._subagent_problems` (1123) as the verify twin, `sweep._archive_subagent` (184) as
the sweep twin, `conftest.ccw_env`/`write_transcript`/`subagent_session`/`tree_snapshot`/
`record_opens` and `tests/test_subagent_capture.py:41-73`'s `configure()`/`plant()` shape
for tests.

### 4.1 New leaf module `src/cc_warehouse/sidecars.py` (imports nothing from `archive`)

The one place that says what may sit beside a transcript. A fence asserts
`set(COPIERS) == SESSION_SIDECARS`, so adding a name without a copier, or a copier without
a name, fails the suite. That is the "one switch" the operator asked for; a config key
that acknowledges a name without copying it is exactly what the fence forbids.

```python
SESSION_SIDECARS = frozenset({"subagents", "tool-results", "workflows"})   # copied
IGNORED = frozenset({".DS_Store"})                                        # every depth
PROJECT_KNOWN = frozenset({"memory"})                # plus *.jsonl and <uuid>/ dirs
SUBAGENT_CHILD_RE = re.compile(r"^agent-[A-Za-z0-9_.-]+\.(jsonl|meta\.json|forked-skill(\.marker)?\.json)$|^workflows$")

@dataclass(frozen=True)
class SidecarScan:
    sidecar_dir: Path | None
    known: tuple[str, ...]
    unknown: tuple[str, ...]                    # level A: unknown child of <uuid>/
    unknown_inside_subagents: tuple[str, ...]   # level C

def locate(transcript_path: Path, session_uuid: str | None) -> Path | None   # uuid first, stem second (ruling (c))
def scan(transcript_path: Path, session_uuid: str | None) -> SidecarScan    # one scandir, two if subagents/ exists; never opens a file; OSError -> empty scan
def scan_project_dir(project_dir: Path) -> tuple[str, ...]                   # level B strangers (doctor only)
def stranded_dirs(project_dir: Path) -> tuple[Path, ...]                     # <uuid>/ with no <uuid>.jsonl
```

Levels: A (children of `<uuid>/`) and C (children of `subagents/`) are scanned per capture
and per sweep. B (project-dir children other than `*.jsonl`, `<uuid>/`, `memory/`,
`.DS_Store`; today nothing else exists) is reported by doctor only, once per project dir.
Names INSIDE `tool-results/` are NOT judged: the copier mirrors the whole tree, so a new
shape is archived, not lost, and flagging it would be permanent noise (the ticket 24.7
lesson). One rule instead: the copier recurses (the `pdf-<uuid>/` dirs prove a top-level
listing is not enough), fence-tested.

F4 fence note: `tests/test_subagent_identity.py:146` rejects the exact string constants
`"agent-"` and `"agent-*"` in any module but `sweep.py`. The regex above is a different
constant and is used for anomaly classification, never identity; if the fence's AST rule
is later widened, exempt `sidecars.py` by name with the same justification as `sweep.py`.

### 4.2 `store.py`: `write_if_absent(path, data) -> Literal["wrote","unchanged","refused"]`

Beside `write_if_changed`. Missing target: `atomic_write`, `wrote`. Same bytes (full read,
never size): `unchanged`. Different bytes, or an unreadable target: `refused`, nothing
written (R5; this differs from `write_if_changed`, which falls through to a write, and the
docstring says why). Lives in store.py so the R2 fence holds and C12 keeps one
compare-before-write family. No guarantee words in the docstring, or add the
`GUARANTEE_PROOFS` entry in `tests/test_fences.py`.

### 4.3 `archive.py`

- `TOOL_RESULTS_DIR = "tool-results"`, `WORKFLOWS_DIR = "workflows"`, `SIDECAR_NOTICE =
  "sidecars.json"`, `STRANDED_DIR = "stranded-sidecars"` beside `SUBAGENTS_DIR` (192).
  `sidecars.json` and `stranded.json` are NOT in `GENERATED_NAMES` (fence-pinned), so
  `_current_manifest`, `verify_folder`'s five-name check, `_sole_jsonl` and the rebuild
  module never touch them (R4).
- `write_sidecar_file(parent_dir, sidecar, relative, data) -> SidecarOutcome`: mkdir
  parents, skip `IGNORED` names, `store.write_if_absent`. One writer for `tool-results` and
  `workflows`. `COPIERS = {"subagents": ..., "tool-results": ..., "workflows": ...}`.
- `write_sidecar_notice(session_dir, scan, refused) -> bool`: body is a pure function of the
  sorted names, NO timestamp (a timestamp re-creates ticket 37 Part A):
  `{"schema": 1, "unarchived": [...], "unknown_inside_subagents": [...], "refused": [...]}`.
  Written through `store.write_if_changed` only when a list is non-empty OR a notice already
  exists (a fixed anomaly is rewritten to empty lists, never deleted: archive.py keeps no
  deletion primitive, fence at `tests/test_subagent_folders.py:263`).
- `sidecar_records(session_dir, sidecar) -> [{name, sha256, bytes}]`: twin of
  `subagent_records`, `rglob("*")`, files only, `IGNORED` skipped, sorted by POSIX path.
- `_with_sidecars(manifest_bytes, directory)`: sets `tool_results` and `workflows`. Called at
  archive.py:728 right after `_with_subagents`. `folder_is_current` (591) compares both.
  `pages_are_current` untouched.
- `_sidecar_problems(directory, manifest)`: the strings in decision 8; a manifest without
  the keys yields `[]` (old folders do not false-alarm in the daily `ccw repair`). Called
  after `_subagent_problems` at archive.py:1118. Known limit, recorded: hidden sessions have
  no manifest, so their sidecars are copied but not hash-verified, like sub-agents today.
- `write_subagent`: accept the forked-skill companions, written like `meta.json`.
- `write_stranded_sidecars(archive_root, dir_name, source_dir)`: under
  `_not-sessions/stranded-sidecars/<dir_name>/`, mirror plus `stranded.json`. Only if ruling
  (d) is "copy"; `build.RESERVED_LABELS` already keeps `_not-sessions` out of `walk_folders`.

### 4.4 `capture.py`

- `capture.py:366` becomes `sidecars.locate(transcript_path, parsed.session_uuid) / SUBAGENTS_DIR`.
- `_archive_subagents_of`: `glob("*.jsonl")` -> `rglob("*.jsonl")`; pass companions.
- New `_archive_sidecars_of(config, conn, project_id, transcript_path, parsed)` called at
  capture.py:236: guard on `archive_root`/`archive_tool_results`; parent via
  `_parent_folder` (None means the source write failed: return, R5); for each sidecar in
  `SESSION_SIDECARS - {"subagents"}` mirror with `write_sidecar_file`, per-file try/except
  continue (R10). **Unlike the sub-agent twin, every refusal and per-file exception is
  logged** (`status: "refused"`/`"error"`, message `"tool-result <name> of <uuid>: archived
  N bytes, offered M bytes"`).
- New `_note_unknown_siblings(config, transcript_path, parsed, parent_dir, refused)`: run
  `sidecars.scan`, `write_sidecar_notice`; if that returned True (changed), append ONE log
  line `status: "unarchived-sibling"`, message `"unarchived sibling(s) beside <uuid>.jsonl:
  foo, bar.json"`. That is the dedup: once per session per change of the set, never once
  per sweep.
- Both wrapped in the `_archive_project_file` never-fatal posture (DESIGN 12).

### 4.5 `sweep.py`

- Third pass after the deferred sub-agent loop (sweep.py:475-477), over EVERY non-sub-agent
  path in `wanted` (the `skipped_unchanged` ones included): `sidecars.locate(...)`; if it
  is not a dir, continue (an ENOENT stat, ~24,000 a day, sub-millisecond each; 1,196 exist).
  Else `_archive_sidecars(config, path)`: parse the JSONL for `session_uuid`, label via the
  catalog row as sweep.py:213-224, `_parent_folder` (None -> `skipped-sidecars-no-parent`,
  file left in place), mirror via `write_sidecar_file`, scan + notice + log as in 4.4.
  Then `stranded_dirs` per project dir -> `write_stranded_sidecars` (ruling (d)).
- `plan()` (355) gets the same pass with `would-archive-sidecars`; writes nothing (the
  dry-run-on-a-fresh-root property in `tests/test_sweep_dry_run.py` must still hold).
- Outcomes: `archived-sidecars` (detail: file count), `refused-sidecar`, `skipped_unchanged`
  (reused), `skipped-sidecars-no-parent`, `would-archive-sidecars`, `sidecar-anomaly`,
  `archived-stranded-sidecars`.
- `cli.py:705`: `if stored or report.archived_sidecars:`; the end report prints the counts.
- Race with the hook: identical bytes make it harmless (`atomic_write`); the refusal path
  is read-then-write, the same shape `write_subagent` already accepted under R14. No new lock.

### 4.6 `config.py`

`archive_tool_results: bool = True` at :172/:526 mirroring `archive_subagents`. Fix the
doc-comment at :1-15, which today omits all four `archive_*` keys.

### 4.7 `doctor.py` + `status.py`

New check `sidecars`, inserted before `install` in `diagnose` (doctor.py:484-586). Name is
8 chars, fits `{name:<11}`. Two shapes:

```
  ok   sidecars    0 folder(s) with unarchived siblings, 39 sidecar dir(s) without a transcript
       sidecars    3 folder(s) with unarchived siblings, e.g. <label>/<folder>: zzz-probe; 39 sidecar dir(s) without a transcript
```

- First figure: corpus-wide, one `stat` of `sidecars.json` per archive folder inside the
  walk `_overdue` (doctor.py:444) already pays for, parse only the ones that exist. NOT the
  25-folder desync sample: the whole reason this was missed for four months is that nothing
  looked at old sessions. Second figure: `sidecars.stranded_dirs` over the project dirs
  (54 scandirs). Level B strangers append `; project-level: <names>` when any exist.
- Never blocking (ruling (e)): `Check(name="sidecars", ok=<first figure is 0>, blocking=False,
  ...)`, same class as `uncaptured`. The line prints `   ` (not `FAIL`) when non-zero, and
  the names, so a reader of `ccw doctor` still sees exactly what is being left behind.
  Attention is the alert sink in 4.9, not the exit code.
- Never hashes: `test_doctor_does_not_hash_sidecars` monkeypatches `store.sha256_hex` to
  raise. Doctor stays read-only by snapshot (`tests/test_doctor.py:98` shape).
- Emits no `FolderProblem`, so doctor.py:409's pending carve-out is untouched.
- `Uncaptured: ...` and `hook` lines: byte-for-byte unchanged, pinned by a new test in
  `tests/test_doctor_external_contract.py`. `ccw-watch` (`grep -E '^\s*FAIL'`) and
  `ccw-freshness-check.py` (exit code, line 343) need no change and, by ruling (e), never
  see this check; a test proves doctor's exit code is 0 with a non-empty `sidecars` figure.
- `ccw status` gains one line `Sidecars: N unarchived, M without transcript` from the same
  reads (`status.sidecar_gap` beside `uncaptured_gap` at :112). `ccw-watch` does not parse
  `ccw status`.
- Back-scan: no new verb. The first `ccw sweep` after the reinstall scans all 1,196 dirs,
  writes notices, logs each once; the next `ccw doctor` reports corpus-wide.

### 4.9 `notify.py`: the attention sink (ruling (e))

- `alert(config, title, message) -> None`: best-effort desktop notification. On
  `sys.platform == "darwin"`, `subprocess.run(["osascript", "-e", 'display notification
  "<message>" with title "<title>"'], timeout=3, capture_output=True)`; any exception
  swallowed; on other platforms a no-op. Message text is escaped for AppleScript quotes.
  Config: `[notify] desktop_alerts = true` by default (an attention sink that defaults off
  is the F6 "parses and does nothing" shape the `speak` docstring already condemns);
  `false` disables. The doc-comment at `config.py:7` gains the key.
- Callers: `capture._note_unknown_siblings` and the sweep's twin, ONLY when
  `write_sidecar_notice` returned True AND the new set is non-empty. Sentence:
  `"cc-warehouse: unarchived sibling(s) beside <short-uuid>: foo, bar. Add a copier in
  sidecars.py."` Sent to `alert()` and to `speak()` (the latter is already opt-in by
  `voice_url` and configured on this machine).
- Off the hook's critical path: on the hook path route through `_spawn_notify_helper`'s
  detached child (DESIGN 12) by adding an `alert` field to the helper's record; on the sweep
  path (a launchd batch job) call inline. Never raises into capture.
- Tests (`tests/test_notify.py` additions): `alert` invokes `osascript` with the escaped
  text on darwin (monkeypatch `subprocess.run`), is a no-op elsewhere, swallows a timeout,
  and is NOT called when the notice is unchanged or empty; a planted anomaly in
  `test_sidecar_capture.py` asserts exactly one `alert` and one `speak` call across two
  sweeps.

### 4.8 `render.py` / `parser.py`: nothing in 38a-38f

Slice 38g (own ruling) adds `<persisted-output>` / `persistedOutputPath` detection at
`parser.py:647`, a marker line in `_render_tool_result` (render.py:439) linking the relative
`tool-results/<name>`, and a `persisted: {seen, resolved, unresolved}` manifest key
(render.py:2335). It re-baselines the golden anchor by recorded ruling in
`tests/test_matrix.py:107-133`'s comment block, and must NOT emit the link in `ccw share`
output.

## 5. Red-team findings and how the design closes each

| Attack | Failure | Rule | Closed by |
|---|---|---|---|
| Sidecar dir keyed by file stem | `<uuid>.orphaned-<n>-<hash>.jsonl` (1 exists) never finds `<uuid>/`; `capture.py:366` has this gap today | F4 | `sidecars.locate` uses the content uuid first, stem second; test `test_sidecars_are_found_when_the_stem_is_not_the_bare_uuid` |
| Cross-project parent | 2 stranded dirs have their transcript under another project; a label derived from the sidecar's dir computes a folder that does not exist | F4 | Parent found by `_parent_folder` from the transcript's own label; a sidecar with no parent goes to `skipped-sidecars-no-parent` (or stranded under ruling (d)), never creates a session folder |
| Same name, different bytes | Silent overwrite | R5/F1 | `write_if_absent` refuses, records in `sidecars.json` `refused` and the log; hook uuids are per invocation so natural collisions should be 0 |
| "Exists means copied" | Location as identity; drift undetectable | F1/R1 | Rejected; bytes compared on every run (a couple of seconds a day); `ccw archive --verify` hashes against the manifest |
| Rebuild deletes sidecars | `build._prune` (build.py:482) treats them as generated | R4 | It prunes only under `projections/`; sidecars outside `GENERATED_NAMES`; `archive.py` has no deletion primitive (fence); test `test_rebuild_never_touches_sidecars` |
| `relocate` rewrites bytes inside copied tool results | Source-class data mutated | F9 | No `relocate_roots` configured today; test `test_relocate_never_modifies_a_file_under_tool_results` |
| Secrets via share | Raw output rides along unredacted | share contract | share copies no folders (verified); test `test_a_shared_bundle_contains_no_tool_results`; 38g must not link |
| Daily rewrite (ticket 37 A) | 2,084 files rewritten a day; notice rewritten a day | C12 | `write_if_absent`/`write_if_changed` everywhere; notice has no timestamp; whole-tree mtime tests |
| Doctor pending carve-out | Hash mismatch hidden as pending render | doctor.py:409 | Problem strings never start with `missing `; doctor's new check emits no `FolderProblem` |
| Back-fill never builds | 0 stored so `build.build` skipped | cli.py:705 | Condition extended (verified) |
| Sidecar arrives after capture | JSONL hash unchanged, hook already ran, file never copied | completeness | Sweep pass three runs for `skipped_unchanged` sessions too; test `test_a_file_added_after_capture_is_picked_up_by_the_next_sweep` |
| Hidden sessions | No manifest to carry a key | F6 | Notice file, not a manifest key; test `test_a_hidden_session_still_gets_a_sidecar_notice` |
| Sweep ordering | Sidecar before parent = orphan | ticket 21.4 | Pass three runs after sessions; hook writes the parent first; test `test_a_sidecar_is_never_written_before_its_parent_folder_exists` |
| `.DS_Store` | Finder turns every browsed folder into an anomaly or a copy | noise | `IGNORED` at every depth in copier and scan; test `test_ds_store_is_neither_copied_nor_reported` |
| Sub-agent with its own nested sidecar (none today) | Uncopied and unflagged | completeness | Level C scan flags an unknown dir name inside `subagents/`; test `test_an_unknown_dir_inside_subagents_is_reported` |
| Signal fails a capture | Unreadable dir raises | DESIGN 12 | Never-fatal posture; test with `chmod 000`, result still `stored` |
| External parsers | `ccw-watch` regex breaks | compat | Existing lines untouched; new line only |
| Frozen install | Hook keeps old code | ops | Reinstall in acceptance; `ccw doctor` from outside the repo shows 0.1.3 |
| Packaging scan | A fixture carries `/Users/<name>` or a session URL | test_packaging | Fixtures synthesise `/home/alice/...` placeholders in the `<persisted-output>` text |
| Size | Archive +135 MB (+34 MB workflows sub-agents already there) of 9.3 GB, about 1.5% | ops | Recorded in docs/operations.md; no cap |
| `workflows/` alerts on day one | An alert for a known thing | design | Archived in this ticket |
| Alert fatigue | A banner every daily sweep | ticket 24.7 lesson | Alert only when the notice CHANGES to non-empty; test asserts one alert across two sweeps |
| Alert blocks the hook | `osascript` hangs | DESIGN 12 | 3 s timeout, exception swallowed, detached helper on the hook path |

## 6. Slices, in dependency order (oracle tests FIRST in every slice)

### 38a  `sidecars.py` + `store.write_if_absent` + rulings (c), (d), (e)
`tests/test_sidecars_scan.py`: known/unknown/ignored classification; never opens a file
(`record_opens`); sees inside `subagents/`; unreadable dir yields empty scan; `locate` by
uuid first then stem; `stranded_dirs`; fences: `set(COPIERS) == SESSION_SIDECARS`, module is
stdlib-only and imports no peer, `sidecars.json`/`stranded.json` not in `GENERATED_NAMES`.
`tests/test_write_if_absent.py`: absent -> exact bytes; same bytes -> `unchanged` and
mtime_ns unchanged (compare locals, F1 fence); different bytes -> `refused`, target
untouched; unreadable target -> `refused`; goes through `atomic_write`.
Contract: DESIGN 15 entries for (c), (d), (e); DESIGN 14 R1 note (a sidecar file is
sha256-identified like every file; its parent is the transcript beside it, ruling (c)).

### 38b  archive writer, notice, manifest keys, verify
`tests/test_sidecar_archive.py`: mirrored under original relative path incl.
`pdf-x/page-01.jpg`; byte-identical; manifest lists name/sha256/bytes for both keys; none
-> `[]`; `write_session_folder` alone creates no sidecar dir (keeps
`test_archive_layout.py:64` green by construction); `folder_is_current` false after a file
is added; verify reports missing and altered; problem strings never start with `missing `;
old manifest -> no problems; same-name-different-bytes refused, original kept, refusal in
the notice; notice body keys exactly `schema/unarchived/unknown_inside_subagents/refused`,
no timestamp; notice not rewritten when unchanged; fixed anomaly rewritten to empty lists,
never deleted; hidden session still copied and still gets a notice; forked-skill
companions land in the agent folder; stranded copy under `_not-sessions/stranded-sidecars/`
with `stranded.json`; `archive.py` and `sidecars.py` have no deletion primitive.
Contract: DESIGN 6 new manifest keys; README.md:169.

### 38c  config + hook path
`tests/test_sidecar_capture.py`: hook copies `tool-results` and `workflows`; nested pages
keep subfolder; switch honoured by hook and sweep alike; refusal logged with six keys;
one unreadable file never costs the capture; `subagents` still resolves via `locate`;
recursive glob reaches `workflows/wf_x/agent-*.jsonl`; planted `foo/` -> one
`unarchived-sibling` log line + notice, second run adds nothing; `.DS_Store` -> nothing;
`chmod 000` sidecar dir -> capture still `stored`.
Contract: SPEC 8 amendment beside ticket 21's (`archive_tool_results`, default ON, the
sub-agent-references-parent statement, ruling (c)).

### 38d  sweep third pass + `cli.py:705`
`tests/test_sidecar_sweep.py`: back-fill for an already-archived (skipped) session; file
added after capture picked up despite unchanged hash; second sweep writes nothing under any
sidecar dir, no notice rewrite, no `meta.json` rewrite (whole-tree mtime snapshot, the
`test_archive_incremental.py:170` technique); dry-run reports and touches nothing on a
fresh root; no parent -> reported not invented; sweep triggers a build when only sidecars
were archived; `source_transcripts` still a 2-tuple; refused file named in report and log;
stranded dirs copied once; sidecar never written before its parent folder.

### 38e  doctor `sidecars` line, status line, alert sink
Additions to `tests/test_doctor.py`, `tests/test_doctor_external_contract.py`,
`tests/test_status_gap.py`, `tests/test_notify.py`: the two line shapes; non-blocking and
exit 0 when a notice exists, ok on a clean archive; corpus-wide (anomaly on the oldest of
30 folders still shows); project-level stranger reported; doctor still writes nothing;
doctor never hashes; `Uncaptured`/`hook` lines byte-identical; `alert()` behaviour per 4.9;
`desktop_alerts` config key parsed with default true.
Docs: `docs/operations.md` doctor line list, the alert, and the migrate note.

### 38f  docs, release, back-fill, real-data acceptance
`pyproject.toml` 0.1.3; `CHANGELOG.md` (0.1.2 entry shape); `README.md:169`;
`contract/DESIGN.md` sections 6, 14, 15; `contract/SPEC.md` section 8; `CLAUDE.md` OPEN list
(one pointer paragraph); `docs/operations.md`; `cc-warehouse-architecture/SOURCE.md`
(archive.py lens; C12 has new callers; `sidecars.py` is a new module); `contract/HARNESS.md`
section 8 retro line; `harness/tickets/38-sidecars-tool-results-and-unknown-siblings.md` in
ticket 37's shape (timeline table, FINDINGS re-derived by execution, Acceptance, DONE
block, NOT DONE for 38g); `tools/ccstats/README.md` note that `collect.py:919-955` walks
only `subagents`. Also add `test_a_shared_bundle_contains_no_tool_results`,
`test_relocate_never_modifies_a_file_under_tool_results`, `test_rebuild_never_touches_sidecars`
to the existing share/relocate/build test files. Tag `ticket-38` after section 7 passes;
then `harness/HANDOFFS.md` entry and `OPENING-PROMPT.md`.

### 38g  render marker + `persisted` key (follow-up, needs its own ruling)
Not in this build. Recorded in the ticket's NOT DONE section with the golden-anchor and
share constraints.

## 7. Real-data acceptance (from OUTSIDE the repo, after 38f and the frozen reinstall)

```
env -u VIRTUAL_ENV PATH="$HOME/.local/bin:/usr/bin:/bin" ~/.local/bin/ccw doctor
#   install frozen, 0.1.3; sidecars line: ok, 0 folders with unarchived siblings, 39 without a transcript
ccw sweep --dry-run          # 1,076 would-archive-sidecars (1,067 tool-results + 9 workflows), 0 written
touch /tmp/m1; nice -n 10 ccw sweep
#   archived-sidecars 1,076, refused 0, no-parent 0, archived-stranded-sidecars 35 (ruling d); build runs
find ~/cc-warehouse-archive -path '*/tool-results/*' -type f | wc -l                  # 2,084 minus the stranded ones, plus those under _not-sessions
find ~/cc-warehouse-archive -path '*/tool-results/*' -type f -exec stat -f %z {} + | awk '{s+=$1} END {print s}'   # 135724066 across both locations
find ~/cc-warehouse-archive -name sidecars.json | wc -l                                # 0 (workflows and forked-skill are known and copied)
grep -c '"unarchived-sibling"' ~/cc-warehouse-data/logs/capture.jsonl                  # 0
grep -c '"status": "refused"' ~/cc-warehouse-data/logs/capture.jsonl                   # 0 (tests the written-once assumption)
ccw archive --verify                                                                   # 0 problems after the build finishes
touch /tmp/m2; nice -n 10 ccw sweep                                                    # second run
find ~/cc-warehouse-archive -newer /tmp/m2 \( -path '*/tool-results/*' -o -path '*/workflows/*' -o -name sidecars.json -o -name meta.json \) | wc -l   # 0
ccw doctor; echo exit=$?     # sidecars ok; Uncaptured/hook lines unchanged (diff against a capture taken before the change); exit 0
```

Plus: end one real Claude Code session and check its new folder holds
`tool-results/hook-*-stdout.txt` listed in `manifest.json` with a matching sha256, and
`~/.claude/logs/ccw-hook.log` shows `started` then `ok`. In a SCRATCH `~/.claude/projects`-
shaped tree (never the real one; this project never writes to `~/.claude`), plant a
`zzz-probe/` dir beside a transcript, sweep, show the `sidecars` line naming it, the log
line, a macOS notification banner and the spoken sentence; sweep again, show NO second
alert; remove the probe, sweep, show the line clear and the notice rewritten to empty lists. Sample 20 sessions with
`persistedOutputPath`: every basename resolves in the archive folder's `tool-results/`.

Budget: the sweep reads 135.7 MB once and the triggered build is the full 0.1.3 rebuild
(about 22,000 folders; 13,829 took 6 minutes on 2026-08-02, so budget 10 to 15 minutes).
Run it `nice`d; the machine runs several sessions at once. Take the doctor output capture
BEFORE the reinstall so the byte-identical diff has a baseline.

## 8. Blast radius (everything that changes or could break)

| File | Change | Breaks? |
|---|---|---|
| `src/cc_warehouse/sidecars.py` | new leaf module | new |
| `src/cc_warehouse/store.py` | `write_if_absent` | no |
| `src/cc_warehouse/archive.py` | constants, `COPIERS`, `write_sidecar_file`, `write_sidecar_notice`, `sidecar_records`, `_with_sidecars` (+ call :728), `folder_is_current` :591, `_sidecar_problems` (+ call :1118), `write_subagent` companions, `write_stranded_sidecars` | no; old folders rebuild once, absorbed by the 0.1.3 rebuild |
| `src/cc_warehouse/capture.py` | :366 via `locate`, recursive glob, `_archive_sidecars_of`, `_note_unknown_siblings`, calls after :235 | no |
| `src/cc_warehouse/sweep.py` | third pass, stranded pass, `plan()` twin, 7 outcome names | no |
| `src/cc_warehouse/cli.py:705` | build condition; sweep end-report counts | no |
| `src/cc_warehouse/config.py` | key :172/:526, doc-comment :1-15 | no |
| `src/cc_warehouse/doctor.py`, `status.py` | `sidecars` check, `sidecar_gap`, status line | no; existing lines pinned |
| `src/cc_warehouse/notify.py` | `alert()` desktop sink; `_spawn_notify_helper` record gains an `alert` field; `append_log`/`speak` reused | no; `tests/test_notify.py` extended |
| `src/cc_warehouse/config.py` | `desktop_alerts` under `[notify]`, default true, in the frozen key map | no |
| `tests/test_fences.py` | `GUARANTEE_PROOFS` entry only if a guarantee word is used; R2 fence must stay green | by design |
| `tests/test_archive_layout.py:64,93`, `test_subagent_capture.py:116` | none | stay green: the session writer never creates sidecar dirs (the mechanism agent corrected my first claim that they would break) |
| `tests/test_subagent_identity.py:134` (F4 fence) | none expected; see 4.1 | verify |
| `tests/test_sweep_dry_run.py`, `test_help_is_inert.py`, `test_unknown_flags.py` | none | must stay green: pass three in `plan()` only reads |
| `tests/golden/matrix-anchor` | none in 38a-f | untouched |
| New tests | `test_sidecars_scan.py`, `test_write_if_absent.py`, `test_sidecar_archive.py`, `test_sidecar_capture.py`, `test_sidecar_sweep.py`; additions to doctor, external-contract, status-gap, freshness, share, relocate, build test files | new |
| `pyproject.toml`, `CHANGELOG.md` | 0.1.3 | one full rebuild |
| `README.md:169`, `contract/DESIGN.md` 6/14/15, `contract/SPEC.md` 8, `CLAUDE.md`, `docs/operations.md`, `cc-warehouse-architecture/SOURCE.md`, `contract/HARNESS.md` 8 | records | no |
| `harness/tickets/38-*.md`, `harness/HANDOFFS.md`, `OPENING-PROMPT.md` | new / updated | no |
| `tools/ccstats/collect.py:919-955` | none now; sibling walk noted in its README | no |
| `plugins/cc-capture/` | none | no `/plugin` update |
| External: `ccw-watch`, launchd `ccw-sweep`/`ccw-repair`/`ccw-archive` | none | the daily sweep back-fills by itself if not run by hand; the archive grows about 135 MB |

## 9. Housekeeping the execution session does first

1. `OPENING-PROMPT.md` "Next task" (lines 6-47) still says "Nothing is currently active"
   and does not mention ticket 37 at all. Replace lines 8-9 with a pointer to ticket 38 and
   this plan file, and one line that ticket 37 Part B row 1 IS now live (verified today:
   `~/.claude/plugins/cache/cc-warehouse/cc-capture/2f374c2eddf9/hooks/ccw-hook.py`
   contains `_started`, and `~/.claude/logs/ccw-hook.log` shows `started` lines), closing
   the "first thing next session" check in handoff 22.
2. Add handoff 23 to `harness/HANDOFFS.md` (this planning session: the two questions, the
   census, the 65.4 MB figure, the workflows/forked-skill finds, the rulings, this plan).
3. Commit the plan file and those two edits before any code, as the noreply identity,
   staged by name, and push.

## 10. Gates (every slice)

`uv run ruff check`, `uv run pyright` (strict), `nice -n 10 uv run pytest` (about 1,200
tests), oracle tests shown red before green in the commit message. Commit and push per
slice; tag `ticket-38` after section 7 passes. No em-dashes anywhere; placeholders only in
fixtures and docs; nothing under `~/.claude` is ever written by this work.
