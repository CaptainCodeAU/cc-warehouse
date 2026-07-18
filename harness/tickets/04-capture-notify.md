# Ticket 04: capture hook + notify

Slice 4 of 13. Depends on: 01, 02, 03. The render child stays a STUB until
slice 8: the oracle tests assert the spawn contract (argv, detachment), never
the child's output.

NOTE (slice 02 fixer round 1, 2026-07-18): the cwd encoder lands in this slice.
When it does, extend registry.move_project (slice 02) so it also claims the
ENCODED form of new_path; that claim was deferred from slice 02 because the
encoder did not yet exist, so a cwd-less capture at a moved location currently
splits into a new project instead of following the move.

Tracer bullet: `ccw hook` reads the SessionEnd payload from stdin and does the
whole DESIGN section 4 pipeline in milliseconds: hash, idempotent store,
project resolution, transactional catalog row + event, notifications, and a
detached `ccw render --session s:<key>` spawn.

## Work order (template from harness/prompts/implementer.md)

- SLICE: capture hook + notify
- GOAL: make the slice-4 oracle tests pass; capture never raises into the
  harness and never blocks on notification infrastructure.
- ORACLE TESTS: tests/test_capture.py (all), tests/test_notify.py (all).
- CONTRACT EXCERPTS: DESIGN sections 4, 12, 13; SPEC sections 2.6, 5 (KEEP
  columns); DESIGN 14 rules R1, R2, R5, R9, R14; FINDINGS F1, F2, F3, F7, F9.
- ADJACENT BEHAVIORS: store.put / store.atomic_write (slice 1: the ONLY
  store write path), catalog.add_session / record_event (slice 2),
  registry.resolve_project (slice 2), parser.parse_session (slice 3).
  capture_transcript is the shared routine that sweep (slice 5) and migrate
  (slice 10) MUST reuse verbatim (R9/F8): design its signature accordingly.
- TOUCHES: src/cc_warehouse/capture.py, src/cc_warehouse/notify.py,
  src/cc_warehouse/cli.py (hook verb + dispatch skeleton), and the MINIMAL
  subset of src/cc_warehouse/config.py needed here (see below).

## Phase 2 decisions frozen in the tests

- Payload: session_id / transcript_path / cwd JSON on stdin. Invalid or
  missing payload: error notify + log line, exit 0, nothing stored, no
  traceback (never-raise posture).
- Duplicate-invocation suppression window: 10 seconds, judged against
  capture_event.at for the same hash; inside it the action logged is
  `duplicate-invocation` and NO notifications fire. Outside it an unchanged
  re-fire logs `skipped_unchanged` (and honors the open-folder opt-in via
  notify.open_folder as a module attribute: the tests patch that seam).
- Resolution source labels: payload_cwd / jsonl_cwd / transcript_dir /
  unresolved.
- Spawn contract: subprocess.Popen with start_new_session=True and all stdio
  to DEVNULL, argv containing `--session` and an `s:` key.
- Config subset THIS slice implements inside config.load_config: CCW_ROOT,
  CCW_SKIP_HOOK, CCW_OPEN_FOLDER env vars and [[notify.webhook]] entries from
  <root>/config.toml (events default ok+error). Slice 13 completes the full
  layering; do not duplicate logic there, extend this.
- Audit log: logs/capture.jsonl, O_APPEND single-line JSON (sanctioned
  exception; the write fence allows os.open only in store.py and notify.py).

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only.
