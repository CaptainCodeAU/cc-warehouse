# Ticket 14: per-variant content matrix

Slice 14 of 17 (v1.1 flag groups; DESIGN 15 entry 2026-08-01, block 1 + shared
rules). Depends on: slice 13 (config layering, Group-A flags), slices 6/7 (the
render emitters and `_Policy`).

Tracer bullet: the five `_compact` keys and their flag pairs thread from CLI and
config through `RenderOptions` into `_compact_policy`, so compact's hard-coded
drops become defaults. An empty config renders byte-identical output to v1.

## Work order (template from harness/prompts/implementer.md)

- SLICE: per-variant content matrix
- GOAL: `subagents_compact`, `attachments_compact`, `commands_compact`,
  `extras_compact`, `tool_output_compact` (config keys, all default OFF) and
  their bijection-derived flag pairs (`--subagents-compact` /
  `--no-subagents-compact`, ..., plus `--reminders-compact VALUE`) reach the
  compact variants of all four files. Unsuffixed keys and flags keep their v1
  meaning (full variants only).
- ORACLE TESTS (write first, in tests/test_matrix.py + additions to
  tests/test_config.py and tests/test_cli.py):
  - empty config and no flags: all four files byte-identical to pre-slice output
    (the regression anchor for the whole flag-group run);
  - `subagents_compact = true` renders sub-agent turns in transcript.compact.md
    AND conversation.compact.html; same per key for the other four classes;
  - each `--x-compact` flag beats its config key (DESIGN 8 precedence);
  - unsuffixed `--no-subagents` still strips full variants and leaves compact
    unchanged;
  - flag spelling is the mechanical bijection (no `--compact-x` spellings parse);
  - `--reminders-compact show|collapse|strip` maps to `reminders_compact`;
  - the manifest `config` block records the new RenderOptions fields.
- CONTRACT EXCERPTS: DESIGN 15 entry 2026-08-01 (shared rules a-d, block 1);
  DESIGN 8 key map (the eleven v1.1 keys and the defaults sentence); DESIGN 7
  flag paragraph. Rules R9 (extend `_compact_policy` in place; a parallel policy
  builder is a rejection), R2 (writes), R8 (guarantee words cite tests).
- ADJACENT BEHAVIORS: render.RenderOptions and `_compact_policy` (complete in
  place); config.load_config's `[render]` section and Config fields;
  cli._CONTENT_BOOL_FLAGS / _content_flags and the verb help text; the
  NON-SCOPE line in the entry (no thinking key on either variant - do not add
  one).
- TOUCHES: src/cc_warehouse/render.py, src/cc_warehouse/config.py,
  src/cc_warehouse/cli.py.

## Interview decisions frozen in the tests (register 3-6, 16)

Matrix = variant x toggle; suffixed FLAT keys (no sub-tables; the one-level
merge is a constraint, not a bug); unsuffixed = full; compact defaults = its v1
drops; full CLI parity (principal's call over config-only); flag = key with
dashes, zero exceptions.

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only. First slice of the v1.1 run: the
byte-identical regression anchor lands here and slices 15-16 reuse it.
