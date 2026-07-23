# cc-warehouse - Brainstorm Output

**Status:** brainstorm phase complete, 2026-07-17. Scope approved by the principal after
7 interactive rounds. This document feeds Phase 1 (SPEC.md / DESIGN.md / FINDINGS.md /
HARNESS.md); it is the WHAT, not the HOW. No schemas, no API signatures here.

**Project:** full rewrite of claude-code-transcripts as `cc-warehouse` (CLI: `ccw`),
fresh public repo at `~/CODE/CaptainCodeAU/cc-warehouse`. Sibling project: `cc-vantage`
(insight/graph layer, built after this ships; see its ARCHITECTURE.v0.3.md, section 2a,
for the family contract).

## The one-line mission

Funnel every AI conversation, regardless of source (Claude Code CLI, claude.ai web,
future sources like Claude Cowork), into one immutable, well-labeled, content-addressed
warehouse, projected into uniform human-readable and agent-consumable files, so the
history is durable, findable, shareable, and never breaks when projects move.

## Foundations (locked, apply to everything)

- Session identity = sha256 of the raw payload; short citation key `s:<12hex>` appears
  in filenames, manifests, and search results. Never path- or folder-derived.
- Immutable event store; every write anywhere is tmp-file + os.replace; SQLite catalog.
- Source transcripts are never modified or deleted by anything, ever.
- Python 3.12+, stdlib-only runtime deps (own markdown renderer), pyright --strict +
  ruff as gates from commit one.
- Public from day one: PyPI + git-URL distribution, docs and install story real.
- Config: config.toml + env overrides + CLI flags (flags win), with per-project
  override sections. Platforms: macOS + Linux/WSL2.
- Non-goals (locked): no server/daemon (CLI + static files + the capture hook only);
  no transcript mutation; no embeddings before v1.1 ships; no Windows native.
- Method: scaled-down Bun-rewrite process. Spec docs first, black-box oracle tests
  before implementation (NOT ported from the old suite, which enshrines the
  size-equality bug as expected behavior), loops of 1 implementer + 2 adversarial
  reviewers + 1 fixer, trial run before scaling, fix-the-prompt-not-the-code.

## v1

| Area | Feature |
|---|---|
| Store | Content-addressed immutable store + SQLite catalog |
| Registry | Project IDs + time-stamped path aliases ("paths are claims, not identity"); moves/renames become metadata edits |
| Relocate | `ccw relocate`: repairs the external world after a repo move - Claude Code encoded dirs, project memory (markdown AND JSON path refs, JSON-aware), PAI-side files via config-driven root inventory; plan -> backup -> apply -> verify -> report, dry-run default. Riskiest v1 item; gets the heaviest adversarial review |
| Capture | SessionEnd hook: hash + store + catalog row in milliseconds, then a detached child renders; `ccw sweep` catches anything the hook missed |
| Notify | Desktop always; voice + open-folder opt-in; webhook sinks (Telegram etc.) |
| Render | 4 files per session, all mandatory: transcript.md, transcript.compact.md, conversation.html, conversation.compact.html. Exporter-style (claude-exporter v8.10.1 is the reference): grouped research phases with captions/durations/tool counts, collapsible turns, copy-as-markdown everywhere, elapsed times, Quick-Look-safe md separators. Thinking + tool calls ON in full variants; thinking-label type and caption stored separately; system reminders collapsed in full variants, stripped in compact |
| Migrate | One-shot hash-verified import of the ~7k-session archive; old archive visibly retired (single rename, e.g. _RETIRED_ prefix; never deleted) |
| Share | Static-site export: single session or multi-session bundle with one index page; sanitization at share time via config-driven redaction rules (home dir, username, email, custom patterns) plus a redaction report listing every hit. Added 2026-07-23 (principal): `--EXPOSED`, the one sanctioned unscrubbed-publish path, gated by a scrubbed-vs-exposed comparison, a typed confirmation, and a non-TTY abort (DESIGN section 9) |

## v1.1

- FTS5 search projection.
- `ccw search` CLI: session-level AND message-level hits, snippets, `s:` keys,
  project/date/source filters.
- Client-side search in the static HTML archive.
- `ccw import`: inbox drop folder + path args (zip / dir / raw jsonl, content-sniffed
  not extension-trusted); 3-layer dedupe: (1) zip sha256 before extracting a byte,
  (2) manifest chatId + exportTime, (3) chatId linking later re-exports as versions.
  Ingests claude.ai exporter bundles (we own the exporter; it can co-evolve).
- Open design call parked to here: which of the 4 files message-level deep links
  target, judged on speed, token cost for agents, and accuracy.

## v1.2

- MCP recall server: search, get-session (transcript md), list-projects, plus
  aggregate stats (counts, activity timelines, per-project summaries).

## Someday (warehouse)

- Playbooks: curated multi-session shareable projections.
- `ccw share` loose zip bundle (static-site export covers v1).
- Session replay/fork (operates on one stored session, so it stays warehouse-side).
- More sources: Claude Cowork, other harnesses.
- Exporter co-evolution: canonical raw API payload in the bundle, deterministic zip,
  sha256 sidecar, bundle format-version field.
- Embeddings / vector search (only after v1.1 is real).

## Moved to cc-vantage (not warehouse features; recorded in its v0.3 doc)

Decision-ledger extraction, failure-pattern detection, cross-session entity graph,
memory distiller, git-blame-to-session provenance (deterministic via C-Sess-Id commit
trailers), effort/cost analytics. Boundary rule: store/dedupe/project/serve = warehouse;
read-many-sessions-and-propose-structure = cc-vantage. cc-vantage consumes sessions only
through the warehouse catalog.

## Rejected, with reasons

- Timeline-index + paginated multi-page HTML (old renderer): superseded by the
  exporter-style single self-contained pages.
- Reconcile/folder-merge machinery: content-hash identity + the registry remove its
  reason to exist.
- Symlink shims for renames: Claude Code encodes cwd strings, symlinks never trigger.
- Gist publishing: superseded by static-site export; dropped gh/gisthost dependency.
- "Never publish to PyPI": reversed for the fresh unclaimed name; publishing is the plan.
- Windows native: deliberately out (was already dropped from the old repo's CI).

## Diagrams

The store and its projections (also in diagrams/event-store.mermaid.md):

```
  SOURCES                      IMMUTABLE STORE                DISPOSABLE PROJECTIONS
  SessionEnd hook          +-----------------------------+   4 files per session (v1)
  ~/.claude JSONLs  ------>+  objects/ sha256 identity   +-> static share site   (v1)
  exporter bundles (v1.1)  |  tmp + os.replace writes    |   FTS5 search       (v1.1)
  ~7k archive (migrate)    |  SQLite catalog + registry  |   MCP recall        (v1.2)
                           +-----------------------------+   delete + rebuild anytime
```

The family (cc-warehouse records, cc-vantage understands):

```
  conversations ->  cc-warehouse  --sessions channel-->  cc-vantage  -> dashboards,
  (any source)      store/serve       (read-only)        graph/drift    drill-downs
```

## Open questions (carried into Phase 1 docs)

1. Deep-link target file for message-level search hits (v1.1; speed/tokens/accuracy).
2. Warehouse read interface for cc-vantage: read-only SQLite ATTACH vs `ccw --json`
   vs MCP. Owned by our DESIGN.md; cc-vantage takes what we publish.
3. Exact form of the shared project-identity key (registry schema decision).
4. Default redaction rule set for share sanitization (seed from the old repo's
  sanitize-test-data conventions).
5. Name availability was spot-checked only; verify PyPI + GitHub before the repo
   goes public.
6. Python floor 3.12 vs 3.13 (assumed 3.12+; confirm at SPEC time).

## What happens next (do not start without being asked)

Phase 1 contract docs in this folder: SPEC.md (old tool's actual behavior, derived from
code, not its docs), DESIGN.md, FINDINGS.md (verified bug classes as constraints: H-1
size-only dedupe, RC-1 hook races, RC-2 index collisions, P-1 parse-everything, plus
size-equality-as-identity and torn writes generally), HARNESS.md + role prompts. Then
oracle tests, a one-module trial run of the harness, and the main build.
