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
the full exporter-v8.10.1 chrome, each content class an independent toggle.
Gates are green: ruff clean, pyright strict 0 errors, 763 tests passing, zero stubs.

**Entry-type coverage was OVERCLAIMED here until 2026-08-02** and the correction is
worth keeping. This paragraph used to say "complete Claude Code entry-type coverage";
a census of 13,836 real sessions then found eight entry types and three content-block
types that rendered nothing and incremented no counter, 62,577 entries carrying
`loss: 0` beside them. Ticket 18 closed that, and the durable half is that anything
the parser does not name now renders a marker AND increments a new top-level
`unrecognised` manifest key, so the next type Claude Code ships announces itself
instead of vanishing. The word "complete" is not used again on purpose.

The v1 exit review has been held and closed. It reconciled the contract against
the code rather than against the tickets, which is how it found the two gaps no
milestone tag or green test could surface: `ccw project` was implemented one
subcommand of five, and the dispatcher accepted an undocumented internal verb.
Both are fixed, and the two decisions the review left open were also ruled:
shared pages now inline highlight.js and make **no third-party requests**, while
personal projections keep the CDN reference for exporter parity; pages stay
dark-only.

**v1.1 flag groups: COMPLETE 2026-08-01** (per-variant matrix, HTML chrome defaults,
truncation, `--since`/`--until`), tags `slice-14`..`slice-17`.

**Archive-first layout: 6 of 7 slices done, 2026-08-02.** The product is a readable
archive: one self-contained folder per session holding the raw JSONL beside its four
projections and a manifest, named `<YYYYMMDD-HHMMSS><offset>_<uuid>` in a zone pinned
in config so the same session yields the same folder on any machine. `ccw archive`
builds it. It has been run on a real 13,836-session corpus: 13,829 folders in six
minutes, zero failures, then verified with zero problems. **Nothing has been swapped**:
the content-addressed store is still the live warehouse and the hook still writes to it.

Then FTS5 with `ccw search` and `ccw import`, then `ccw mcp` in v1.2.

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
ccw archive    build (or --verify) the archive-first tree at --to DIR
ccw version    print the version (also -v)
```

Every session is projected into four files: `transcript.md`,
`transcript.compact.md`, `conversation.html` and `conversation.compact.html`,
plus a `manifest.json` recording the settings and counts that produced them.

`manifest.json` answers three separate questions and keeps them separate on purpose:
`loss` is what the renderer dropped, `unrecognised` is what Claude Code's format grew
that this parser does not name yet, and `withheld` is what never arrived (thinking
text stopped reaching the JSONL upstream at Claude Code v2.1.69). A rendered entry is
not a lost one, so none of the last two is filed under `loss`.

## Development

```
uv sync
uv run pytest          # oracle suite
uv run pyright         # strict mode (configured in pyproject)
uv run ruff check
```

License: PolyForm Noncommercial 1.0.0 (see LICENSE).
