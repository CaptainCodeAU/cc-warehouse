# Ticket 29: which copy of a session is the current one

Opened 2026-08-04 by principal ruling ("1 now, then 3 as its own ticket"), out of
ticket 25.5. NOT started. Needs scoping with the principal before any code.

This ticket is the CLASS. Ticket 25.5 hit one instance of it and stopped.

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
