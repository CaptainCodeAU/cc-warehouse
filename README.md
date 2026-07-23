# cc-warehouse

Content-addressed, immutable warehouse for AI conversation sessions (Claude Code,
claude.ai exports, future sources), projected into uniform markdown/HTML files.
CLI: `ccw`.

Status: **v1 is CLOSED.** Every slice in the DESIGN section 16 build order landed
and carries its milestone tag, `slice-01..13` including `slice-12a` and
`slice-12b`, 14 tags in all (store; catalog + registry; parser + conversation
model; capture hook + notify; sweep; markdown emitters; HTML emitters + manifest;
build/render orchestration; status + verify; migrate + retire; share + redaction;
relocate containers; relocate content; config + CLI + flags). The render carries
the full exporter-v8.10.1 chrome and complete Claude Code entry-type coverage
(ai-title titles, sub-agent phases, attachments, commands, structured tool output,
informational extras), each an independent toggle. Gates are green: ruff clean,
pyright strict 0 errors, 403 tests passing, zero stubs.

The v1 exit review has been held and closed. It reconciled the contract against
the code rather than against the tickets, which is how it found the two gaps no
milestone tag or green test could surface: `ccw project` was implemented one
subcommand of five, and the dispatcher accepted an undocumented internal verb.
Both are fixed, and the two decisions the review left open were also ruled:
shared pages now inline highlight.js and make **no third-party requests**, while
personal projections keep the CDN reference for exporter parity; pages stay
dark-only.

Next is v1.1: the deferred flag groups (per-file matrix, HTML chrome defaults,
truncation, `--since`/`--until`), then FTS5 with `ccw search` and `ccw import`,
then `ccw mcp` in v1.2.

**Not published, and not planned for publication for now** (principal, 2026-07-24).
The distribution name is `cc-warehouse` and the console scripts are `ccw` and
`cc-warehouse`, but nothing is on PyPI. Install from a git checkout with `uv sync`.

The contract lives in `contract/` (BRAINSTORM, SPEC, DESIGN, FINDINGS, HARNESS); the
oracle suite in `tests/` was written before the implementation.

## Verbs

```
ccw hook       SessionEnd capture from a stdin payload
ccw sweep      import anything the hook missed
ccw build      rebuild projections from the catalog (incremental by default)
ccw render     (re)build one session's four files, or render an ad-hoc file
ccw project    list / show / rename / move OLD NEW / merge A B
ccw share      build a sanitized static site for chosen sessions
ccw migrate    one-shot import of a legacy archive (+ --retire)
ccw relocate   repair the external world after a repo move (dry-run by default)
ccw status     recent captures, counts, store size, last errors
ccw verify     re-hash objects and cross-check them against the catalog
ccw version    print the version (also -v)
```

Every session is projected into four files: `transcript.md`,
`transcript.compact.md`, `conversation.html` and `conversation.compact.html`,
plus a `manifest.json` recording the settings and counts that produced them.

## Development

```
uv sync
uv run pytest          # oracle suite
uv run pyright         # strict mode (configured in pyproject)
uv run ruff check
```

License: PolyForm Noncommercial 1.0.0 (see LICENSE).
