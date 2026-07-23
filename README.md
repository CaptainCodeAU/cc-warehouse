# cc-warehouse

Content-addressed, immutable warehouse for AI conversation sessions (Claude Code,
claude.ai exports, future sources), projected into uniform markdown/HTML files.
CLI: `ccw`.

Status: main build essentially complete. Slices 01-11 landed and tagged
`slice-01..11` (store; catalog + registry; parser + conversation model; capture
hook + notify; sweep; markdown emitters; HTML emitters + manifest; build/render
orchestration; status + verify; migrate + retire; share + redaction). The render
was then extended to the full exporter-v8.10.1 chrome and to complete Claude Code
entry-type coverage (ai-title titles, sub-agent phases, attachments, commands,
structured tool output, informational extras), each an independent toggle.
Slice 13 (config layering + the `ccw` help/version surface + the content flags +
`--no-config`/`--config` + `share --EXPOSED`) landed 2026-07-23 and the whole
oracle suite is green. Still open: relocate ticket 12a (containers) then 12b
(content), which were deferred out of the DESIGN 16 order. The contract lives in
`docs/` (BRAINSTORM, SPEC, DESIGN, FINDINGS, HARNESS); the oracle suite in
`tests/` was written before the implementation.

## Development

```
uv sync
uv run pytest          # oracle suite
uv run pyright         # strict mode (configured in pyproject)
uv run ruff check
```

License: PolyForm Noncommercial 1.0.0 (see LICENSE).
