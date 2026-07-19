# cc-warehouse

Content-addressed, immutable warehouse for AI conversation sessions (Claude Code,
claude.ai exports, future sources), projected into uniform markdown/HTML files.
CLI: `ccw`.

Status: main build in progress, slice by slice per DESIGN section 16. Slices
01-11 have landed (store; catalog + registry; parser + conversation model;
capture hook + notify; sweep; markdown emitters; HTML emitters + manifest;
build/render orchestration; status + verify; migrate + retire; share +
redaction), tagged `slice-01..11`. Slice 12 (relocate) is landed on master as a working
checkpoint but is NOT done and carries no tag: its review loop did not converge and was
escalated under HARNESS section 4, which split it into ticket 12a (containers) and 12b
(content rewriting); next is ticket 12a. The contract lives in
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
