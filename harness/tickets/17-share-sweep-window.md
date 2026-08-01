# Ticket 17: --since/--until on share and sweep

Slice 17 of 17 (v1.1 flag groups; DESIGN 15 entry 2026-08-01, block 5). Depends
on: slice 13 (CLI surface); independent of the render slices - it lands last
only to keep render territory contiguous, per the entry's build order.

Tracer bullet: one shared window parser/validator; `ccw share` selects by
hashes OR a window (never both); `ccw sweep` imports only sessions whose R12
first timestamp falls in the window.

## Work order (template from harness/prompts/implementer.md)

- SLICE: date-window selection for share and sweep
- GOAL: `--since` / `--until` on both verbs. Bare `YYYY-MM-DD` = the OPERATOR'S
  LOCAL calendar day, inclusive both ends (since -> local 00:00:00, until ->
  end of that local day); naive datetimes read as local; offset-carrying ISO
  datetimes taken literally; comparison against the payload-internal FIRST
  timestamp (R12). One-sided windows valid. No relative forms.
- ORACLE TESTS (write first, in tests/test_window.py + additions to
  tests/test_cli.py; pin the timezone per test via the TZ env var so local-day
  semantics are deterministic under test):
  - bare-date inclusivity: sessions stamped inside either boundary day match;
    one second past the until-day's end does not;
  - the midnight-spanner: a session whose first stamp is 23:41 on day D and
    last stamp 01:12 on D+1 matches a window containing D and NOT one starting
    at D+1 (register decision 13);
  - the UTC-vs-local boundary: with TZ=Australia/Sydney, a session stamped
    2026-07-24T22:00:00Z (08:00 local on the 25th) MATCHES --since 2026-07-25
    even though its folder says 2026-07-24 (register decision 14, the stated
    consequence);
  - naive datetime = local; offset datetime = literal;
  - --since alone and --until alone both work on both verbs;
  - since after until: `Error: ...` to stderr, exit 1 (SPEC CLI contract);
  - unparseable values and relative forms ("7d", "yesterday"): usage errors;
  - share: hashes plus a window in one invocation is a usage error naming both
    modes; a window alone selects exactly the in-window catalog heads; hashes
    alone unchanged;
  - sweep: out-of-window sessions are skipped AND a later unwindowed sweep
    still imports them (narrowing loses nothing - re-runnable);
  - build does NOT accept the pair (refused in the entry; the flag is an
    unknown-argument error there).
- CONTRACT EXCERPTS: DESIGN 15 entry block 5 (including the REFUSED paragraph
  and the named tree-calendar candidate - do not implement it); DESIGN 7 verb
  table rows for share and sweep; R12; SPEC section 2 error contract.
- ADJACENT BEHAVIORS: share's session-operand parsing in cli.py (`_run_share`);
  sweep's source walk in sweep.py (it already parses payloads to catalog them -
  match on the parsed first timestamp, never an mtime, R12); the catalog heads
  query build uses (share's window selects among the same heads).
- TOUCHES: src/cc_warehouse/cli.py, src/cc_warehouse/sweep.py,
  src/cc_warehouse/share.py.

## Interview decisions frozen in the tests (register 12-15)

share + sweep only; build refused for the R4/index hazard (recorded, not
deferred); R12 first-timestamp matching (selection counts time the way every
listing presents it); local days inclusive (principal's call: wall-clock intent
over folder-name agreement - the boundary consequence is stated and TESTED, not
hidden); hash XOR window, union addable later.

## Process

Standard loop (HARNESS section 2); /tdd inside the implementer; reviewers get
diff + excerpts + the ADJACENT list only. Last slice of the v1.1 flag-group
run: after it lands, the OPEN queue moves to v1.1 proper (FTS5 + search +
import), and `ccw import` adopts this window definition when it arrives.
