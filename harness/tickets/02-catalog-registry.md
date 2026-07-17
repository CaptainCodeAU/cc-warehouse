# Ticket 02: catalog + registry

Slice 2 of 13. Depends on: 01 (store hashes are the identity the catalog keys).

Tracer bullet: catalog.sqlite with the frozen DDL, session rows with short
citation keys and version links, and the project registry (stable IDs, path
aliases, mutable labels).

## Work order (template from harness/prompts/implementer.md)

- SLICE: catalog + registry
- GOAL: make the slice-2 oracle tests pass with a transactional SQLite
  catalog and a registry where paths are claims, never identity.
- ORACLE TESTS: tests/test_catalog.py (all), tests/test_registry.py (all).
- CONTRACT EXCERPTS: DESIGN sections 2, 3; DESIGN 14 rules R1, R3, R4, R12;
  FINDINGS F1, F4; SPEC section 3 (label derivation as a DEFAULT only).
- ADJACENT BEHAVIORS: store.sha256_hex / store.put (hash identity comes from
  slice 1; do not re-implement hashing); store.atomic_write (not used here:
  SQLite's own writes are the sanctioned exception, DESIGN R2).
- TOUCHES: src/cc_warehouse/catalog.py, src/cc_warehouse/registry.py, and
  (optional) src/cc_warehouse/schema.sql if the DDL lives in a file.

## Phase 2 decisions frozen in the tests

- Tables and columns exactly as asserted in test_catalog.py (DESIGN section 3
  DDL is now frozen by those assertions).
- Short keys: first 12 hex; on prefix collision the NEWER key extends until
  unique; older citations stay valid.
- add_session links supersedes to the latest earlier version of the same
  session_uuid; all versions kept.
- resolve_project: alias hit wins; miss creates project + alias rows (kinds
  cwd / encoded_dir) stamped first_seen/last_seen; distinct cwds NEVER merge
  through a shared encoded_dir (F4).
- rename = label edit only; move = new alias rows, old kept as history;
  merge = repoint sessions, soft-retire the merged row.

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only.
