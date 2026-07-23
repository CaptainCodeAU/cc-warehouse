# cc-warehouse

Content-addressed, immutable warehouse for AI conversation sessions (Claude Code,
claude.ai exports, future sources), projected into uniform markdown/HTML files.
CLI: `ccw`.

Status: v1 is CODE-COMPLETE. Every slice in the DESIGN section 16 build order has
landed and carries its milestone tag, `slice-01..13` including `slice-12a` and
`slice-12b` (store; catalog + registry; parser + conversation model; capture hook
+ notify; sweep; markdown emitters; HTML emitters + manifest; build/render
orchestration; status + verify; migrate + retire; share + redaction; relocate
containers; relocate content; config + CLI + flags). The render also carries the
full exporter-v8.10.1 chrome and complete Claude Code entry-type coverage
(ai-title titles, sub-agent phases, attachments, commands, structured tool output,
informational extras), each an independent toggle. Gates are green: ruff clean,
pyright strict 0 errors, 378 tests passing, zero stubs. Remaining before release:
the v1 exit review, then the deferred v1.1 flag groups and the open `--hljs` and
`--theme` rulings. The contract lives in `docs/` (BRAINSTORM, SPEC, DESIGN,
FINDINGS, HARNESS); the oracle suite in `tests/` was written before the
implementation.

## Development

```
uv sync
uv run pytest          # oracle suite
uv run pyright         # strict mode (configured in pyproject)
uv run ruff check
```

License: PolyForm Noncommercial 1.0.0 (see LICENSE).
