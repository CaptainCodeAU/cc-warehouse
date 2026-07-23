# Ticket 13: config + env + CLI polish

DONE 2026-07-23 (direct build, not the harness loop; principal chose Option 1,
v1 exit review followed). load_config now does the full DESIGN 8 layering;
the help/version/bare/unknown surface and the Group-A content flags + config
bypass (--no-config / --config) landed; --EXPOSED added to share. The whole
oracle suite is green (was 13 red) plus 7 contract-derived regression tests in
tests/test_cli_flags_regressions.py. Commits b723a71 (core) + c366a96
(--EXPOSED). Deferred to v1.1: per-file matrix, HTML chrome defaults, truncation,
formatting, --since/--until; --hljs (open item 8) and --theme still need their
own principal ruling.

Slice 13 of 13. Depends on: everything (this slice completes surfaces that
earlier slices stubbed or partially implemented).

Tracer bullet: the full DESIGN section 8 configuration layering, the complete
`ccw` verb surface with help/status/version polish, and the `ccw project`
management verbs.

## Work order (template from harness/prompts/implementer.md)

- SLICE: config + env + CLI polish
- GOAL: make the remaining oracle tests pass; the whole suite is green when
  this slice lands.
- ORACLE TESTS: tests/test_config.py (all), tests/test_cli.py (all remaining:
  version flag/verb, bare ccw status+usage, full verb help, unknown-verb
  usage error), plus the whole suite as the final gate.
- CONTRACT EXCERPTS: DESIGN sections 7, 8; SPEC section 2 (KEEP error
  contract + version, DROP default-subcommand dispatch); DESIGN 14 rules R3,
  R7, R9, R13.
- ADJACENT BEHAVIORS: the slice-4 config subset in config.load_config
  (COMPLETE it in place; a parallel loader is a rejection, R9),
  registry.rename_project / move_project / merge_projects (slice 2: the
  `ccw project` verbs wrap them), every verb handler added by earlier slices.
- TOUCHES: src/cc_warehouse/config.py, src/cc_warehouse/cli.py.

## Phase 2 decisions frozen in the tests

- Precedence: defaults -> XDG file (~/.config/cc-warehouse/config.toml,
  overridable via the xdg_config_home parameter) -> <root>/config.toml
  key-by-key -> [project.<registry-id>.<table>] sections -> CCW_* env ->
  flags. Frozen TOML map: top-level root; [notify] voice_url voice_id
  open_folder; [render] breadcrumbs reminders_full reminders_compact
  subagents attachments commands extras tool_output ([render] expanded
  2026-07-23 with the principal for the content toggles);
  [share] redact_patterns; [relocate] roots; [import] inbox;
  [[notify.webhook]] name url events template. Added 2026-07-23: --no-config
  (ignore both files) and --config PATH (substitute one file).
- Env vars: CCW_ROOT, CCW_SKIP_HOOK, CCW_VOICE_URL, CCW_VOICE_ID,
  CCW_OPEN_FOLDER, CCW_WEBHOOKS. NO legacy TRANSCRIPT_* name is honored.
- Bare ccw: short status + usage, exit 0. Unknown verb: usage error, no
  default dispatch. -v/--version and the version verb print the package
  version. Help lists all eleven v1 verbs.

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only. After this slice: full-suite green
run, then the DESIGN section 16 v1 exit review with the principal.
