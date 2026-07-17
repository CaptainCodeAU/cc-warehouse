# cc-warehouse

Content-addressed, immutable warehouse for AI conversation sessions (Claude Code,
claude.ai exports, future sources), projected into uniform markdown/HTML files.
CLI: `ccw`.

Status: pre-implementation. The contract lives in `docs/` (BRAINSTORM, SPEC,
DESIGN, FINDINGS, HARNESS); the oracle test suite in `tests/` is written before
the implementation and is expected to be red until the build lands.

## Development

```
uv sync
uv run pytest          # oracle suite
uv run pyright         # strict mode (configured in pyproject)
uv run ruff check
```

License: PolyForm Noncommercial 1.0.0 (see LICENSE).
