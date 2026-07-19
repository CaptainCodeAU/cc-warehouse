# cc-warehouse

Content-addressed, immutable warehouse for AI conversation sessions (Claude Code,
claude.ai exports, future sources), projected into uniform markdown/HTML files.
CLI: `ccw`.

Status: main build in progress, slice by slice per DESIGN section 16. Slices
01-09 have landed (store; catalog + registry; parser + conversation model;
capture hook + notify; sweep; markdown emitters; HTML emitters + manifest;
build/render orchestration; status + verify), tagged `slice-01..09`; next is
ticket 10 (migrate + retire). The contract lives in
`docs/` (BRAINSTORM, SPEC, DESIGN, FINDINGS, HARNESS); the oracle suite in
`tests/` was written before the implementation; each slice's tests go green as
it lands, and the rest stay red for the right reason (missing implementation)
until theirs does.

## Development

```
uv sync
uv run pytest          # oracle suite
uv run pyright         # strict mode (configured in pyproject)
uv run ruff check
```

License: PolyForm Noncommercial 1.0.0 (see LICENSE).
