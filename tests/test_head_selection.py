"""Oracle tests: which version of a session_uuid is the HEAD (ticket 29 mechanism 1).

Contract: `harness/tickets/29-which-copy-is-the-current-one.md`. `catalog.add_session`
points each new row's `supersedes` at whatever `_latest_version` currently returns, so a
row is never itself superseded once inserted -- `build._heads`'s old predicate ("a row
no other row supersedes") therefore picked the newest INSERT as head, regardless of
whether that payload's own last_ts was actually the most recent. Fixed by ranking each
session_uuid's rows by the SAME payload-internal recency `catalog._latest_version`
already uses (R12: content time, never insertion order), not by chain position.

These are ORACLE tests, not a private-function check: everything is proven through
`ccw build`'s rendered output, the same way `test_build.py::
test_superseded_version_leaves_one_canonical_dir` proves the ordinary (in-order) case.
"""

import hashlib

from conftest import entry, hook_payload, jsonl, run_ccw, run_cli, write_transcript

UUID = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"


def _capture(env: dict[str, str], data: bytes, name: str) -> None:
    transcript = write_transcript(env, data, session_id=UUID, name=name)
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, session_id=UUID))
    assert result.code == 0, result.err


def _session_dirs(env: dict[str, str]):
    from conftest import warehouse_root

    projections = warehouse_root(env) / "projections"
    return sorted(p for p in projections.glob("*/*") if p.is_dir())


def test_a_row_inserted_later_with_an_earlier_last_ts_does_not_become_the_head(
    ccw_env: dict[str, str],
) -> None:
    """The exact real-world shape ticket 29 measured: a truncated/out-of-order capture
    of the same session_uuid arrives AFTER the fuller one, but its own last_ts is
    EARLIER. The fuller, chronologically-later payload must stay head."""
    later_content = jsonl(
        entry("user", "hello", "2026-01-05T09:00:00.000Z", session_id=UUID),
        entry("assistant", "hi", "2026-01-05T12:00:00.000Z", session_id=UUID),
    )
    earlier_content = jsonl(
        entry("user", "hello", "2026-01-05T09:00:00.000Z", session_id=UUID),
    )
    _capture(ccw_env, later_content, "a.jsonl")
    _capture(ccw_env, earlier_content, "b.jsonl")  # inserted SECOND, last_ts EARLIER

    assert run_cli(["build"]).code == 0
    dirs = _session_dirs(ccw_env)
    assert len(dirs) == 1, f"expected exactly one canonical dir, got {[d.name for d in dirs]}"

    later_short = hashlib.sha256(later_content).hexdigest()[:12]
    earlier_short = hashlib.sha256(earlier_content).hexdigest()[:12]
    assert dirs[0].name.endswith(f"s-{later_short}"), (
        f"the earlier-content, later-inserted row became head: {dirs[0].name}"
        f" (later_short={later_short}, earlier_short={earlier_short})"
    )


def test_growth_in_place_still_promotes_the_newer_larger_version(
    ccw_env: dict[str, str],
) -> None:
    """Regression guard: the ordinary case (a session grows in place, so the newest
    INSERT and the newest last_ts always agree) must keep working exactly as
    `test_build.py::test_superseded_version_leaves_one_canonical_dir` already proves at
    the CLI level -- this pins the same property directly against build._heads' new
    ranking so a future change to the tie-break order cannot silently invert it."""
    original = jsonl(entry("user", "hello", "2026-01-05T09:00:00.000Z", session_id=UUID))
    grown = original + jsonl(entry("assistant", "hi", "2026-01-05T09:05:00.000Z", session_id=UUID))
    _capture(ccw_env, original, "a.jsonl")
    _capture(ccw_env, grown, "a.jsonl")

    assert run_cli(["build"]).code == 0
    dirs = _session_dirs(ccw_env)
    assert len(dirs) == 1

    grown_short = hashlib.sha256(grown).hexdigest()[:12]
    assert dirs[0].name.endswith(f"s-{grown_short}")
