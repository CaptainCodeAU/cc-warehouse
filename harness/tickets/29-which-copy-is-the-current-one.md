# Ticket 29: which copy of a session is the current one

Opened 2026-08-04 by principal ruling ("1 now, then 3 as its own ticket"), out of
ticket 25.5.

This ticket is the CLASS. Ticket 25.5 hit one instance of it and stopped.

## STATUS: mechanism (2) is DONE. Mechanism (1) is DONE 2026-08-20.

**Mechanism (1) fixed 2026-08-20**, scoped with the principal first (as this
ticket's own text required) after ticket 27.4's exercise step surfaced it
again in a harder form: `ccw build` raising `FileNotFoundError` instead of
silently serving the wrong-but-correct content, once `objects/` was
temporarily renamed aside. `build._heads` and `build.head_for_short` no
longer define a head as "the row no other row supersedes" (insertion order);
both now rank each session_uuid's rows by the SAME `COALESCE(last_ts,
captured_at) DESC, captured_at DESC, rowid DESC` ordering `catalog.
_latest_version` already used for picking a supersedes TARGET, via one
shared query fragment (`build._HEAD_RANK_CTE`, R9 - one definition, not four
independently-inlined copies of the old predicate). `catalog.add_session`'s
own supersedes-chain-building logic is UNCHANGED - only which row counts as
head is fixed, not how the chain links.

Verified two ways before trusting it: (1) oracle tests
(`tests/test_head_selection.py`) reproducing the exact real-world shape - a
truncated/out-of-order capture of the same uuid arriving with an EARLIER
`last_ts` than an already-stored fuller capture - RED before the fix
(confirmed via `git stash` on `build.py` alone), GREEN after, plus a
regression guard that ordinary in-place growth still promotes the newer,
larger version exactly as before. (2) On the REAL machine: all 4 sessions
ticket 27.4's exercise found broken now resolve, via the new query run
directly against the live catalog, to the exact hash sitting in each
archive folder (checked by `shasum -a 256` against the same 4 folders,
before touching the fix - only after does the query agree). Then the full
27.4 exercise was re-run for real: `objects/` renamed aside a second time,
`ccw status`/`verify`/`build`/`sweep --quiet`/a real live Claude Code
session end (via Herdr) all passed clean - `ccw build` specifically went
from `4 failed` to `0 failed` against the unchanged real corpus. `objects/`
was restored afterward; the delete itself is still the operator's to run,
separately, per this ticket's own DESTRUCTIVE marking on 27.4.

Gates: `uv run pytest` (1111 passed; the sole remaining failure is the
pre-existing, unrelated `.envrc` packaging gap, not this change), `uv run
pyright` (0 errors), `uv run ruff check` (clean), `tests/golden/matrix-
anchor` untouched (61 passed, re-run directly).

**Mechanism (2) fixed 2026-08-04** (principal ruling the same day, option 5:
"fix the writer first, then import"), commit `86394d3`. `write_session_folder`
now renders from the payload ON DISK when it refuses a smaller one, and re-derives
`hidden` from that payload for the same reason. Nine oracle tests in
`tests/test_refused_render.py`, four red first for the right reason, one
reproducing the production error string through `ccw archive --verify`.

The locked test `test_a_smaller_payload_is_refused_and_the_refusal_is_recorded`
passes UNCHANGED and was not narrowed. See the "Do NOT" section: its letter and
its decision agree, and the obvious fix (skip the render on refusal) would have
broken the half of the decision that says "saying so IN THE MANIFEST".

Proved on the real broken folder before the fix was committed, and this is the
evidence a future session should re-run rather than trust:

    BEFORE  jsonl sha=22b4cad77d46  manifest source_hash=bc2f997969b6  agree=False
    AFTER   jsonl sha=22b4cad77d46  manifest source_hash=22b4cad77d46  agree=True
            refusal still recorded: offered=8,659,426  archived=8,682,224
    throwaway tree: 7,694 folders, 1 problem -> 0 problems

**Mechanism (1) is still live.** A late-imported OLDER copy still becomes the
catalog head, so `ccw build` still RENDERS from it. That is now harmless for the
archive folder, because the writer refuses it and keeps the surviving payload's
rendering, but the catalog still reports the wrong row as current, which
`ccw status`, `ccw render --session` and any future search surface will believe.
Scope this with the principal before touching `catalog.add_session` or
`build._heads`; it is the most load-bearing pair of functions in the project.

## The defect, in one sentence

When a session has two stored payloads and one is a truncated prefix of the
other, which one the archive folder READS AS is decided by insertion order and
by two write paths that disagree with each other.

## The two mechanisms, both measured 2026-08-04

**(1) A late-imported OLDER copy becomes the head.** `catalog.add_session` points
each new row's `supersedes` at the previous latest version, so the new row is
never itself superseded, and `build._heads` selects "a row no other row
supersedes". The newest INSERT therefore wins regardless of its payload
timestamps. Measured on a real pair:

    short=bc2f997969b6   8,659,426 B   last_ts 2026-06-16T13:52   supersedes=22b4cad7   HEAD
    short=22b4cad77d46   8,682,224 B   last_ts 2026-06-17T01:16   supersedes=-          not head

The truncated copy, whose last entry is twelve hours EARLIER, is the head.
`catalog._latest_version`'s docstring says "a late-imported old export therefore
never displaces the newer copy". That is true of the supersedes POINTER and false
of head selection, and head selection is what renders.

**(2) `archive.write_session_folder` refuses a payload and then renders it
anyway.** `archive.py:479-490` refuses to shrink the JSONL when the offered
payload is smaller, sets `refused = True`, and then falls through to
`for name, payload in build.iter_projection_files(data, options)` and writes ALL
FIVE generated files from the payload it just refused. The result is a folder
whose JSONL is the full session and whose markdown, HTML and manifest are the
truncated one. `ccw archive --verify` catches it:

    CaptainCodeAU-cc-print-shop/20260616-165951+1000_c85f1e1b-...:
    JSONL does not match manifest source_hash

Mechanism (2) is the one that does the damage. Mechanism (1) only decides how
often (2) is reached. Both `build._mirror` and `ccw archive --to` route through
`write_session_folder`, so both carry it.

## Why this is not a one-line fix, and the fence that says so

`tests/test_archive_layout.py:131`
`test_a_smaller_payload_is_refused_and_the_refusal_is_recorded` is a LOCKED
oracle test, and its stated decision is:

> F6: never silent. A truncated re-capture must not be able to shrink the archive
> without saying so in the manifest.

Here the letter IS the decision. "Skip the projections on refusal" satisfies
"must not shrink" and BREAKS "saying so in the manifest", because the manifest is
one of the five files that would stop being written. So the fence is not too
broad and must not be narrowed; the fix has to keep a refusal recorded in the
manifest while leaving the folder readable as the LARGER payload.

The shape that satisfies both, for the principal to rule on: on refusal, render
from the payload ALREADY ON DISK (`jsonl.read_bytes()`, which is the larger one)
and annotate THAT manifest with the refusal. Costs one extra render on a rare
path; keeps manifest and JSONL in agreement, which is exactly what
`ccw archive --verify` checks.

## Blast radius today

Three uuids in `~/cc-warehouse-archive` have a truncated twin in the legacy tree
(`17e372b3`, `80721130`, `c85f1e1b`), and four vault objects are earlier
snapshots of archived sessions. None has lost anything: in every case the archive
holds the LARGER payload's JSONL and the smaller is a strict byte prefix of it.

## Oracle tests (write first)

- a refused smaller payload leaves the four RENDERED files byte-identical;
- a refused smaller payload still records the refusal in the manifest;
- after a refusal, manifest `source_hash` still equals the JSONL's hash, so
  `ccw archive --verify` reports no problem;
- the existing locked test at `test_archive_layout.py:131` still passes unchanged;
- head selection: a row inserted LATER with an EARLIER `last_ts` does not become
  the head (this is the mechanism-(1) half and may be split out);
- `ccw archive --to` over a catalog holding both payloads yields the same folder
  contents regardless of row order.

## TOUCHES

`src/cc_warehouse/archive.py` (write_session_folder), possibly
`src/cc_warehouse/catalog.py` (add_session / _latest_version) and
`src/cc_warehouse/build.py` (_heads) for mechanism (1), `contract/DESIGN.md`
section 15 entry, `tests/`.

## Do NOT

Do not narrow or edit `test_a_smaller_payload_is_refused_and_the_refusal_is_recorded`.
Its letter and its decision agree; it fired for exactly the right reason.
