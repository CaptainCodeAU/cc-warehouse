"""Oracle tests: `ccw sweep --dry-run` and `--quiet` (ticket 23, slice 23a).

Contract: DESIGN section 7 (the sweep row, amended 2026-08-03) and section 15
entry "`ccw doctor`, AND WHY IT IS A VERB", which lands `--dry-run` in the same
ticket for the same reason: the first real sweep after ticket 23 processes about
1,857 payloads into a tree that is about to become the only copy.

WHY THE SNAPSHOT TESTS ARE THE POINT. On 2026-08-01 `ccw sweep -h` exited 0,
printed output, and imported 13,836 sessions. Exit 0 plus output is not evidence
that nothing happened; only asking whether the WORLD CHANGED separates a
rehearsal from a run.

Two write paths make this non-trivial, and both were found by reading the code
rather than by assuming:

  store.acquire_lock  does `lock.parent.mkdir(parents=True, exist_ok=True)`,
                      so taking the sweep lock CREATES <root>/locks/
  catalog.open_catalog "Open (creating if needed)", so reading the cataloged
                      hash set CREATES catalog.sqlite

A dry-run that took either path would leave a warehouse behind on a fresh root.
test_dry_run_on_a_fresh_root_creates_no_warehouse is the test that catches it,
and it is the reason the fresh-root case is tested separately from the
existing-warehouse case: on an existing warehouse both paths are invisible,
because the directory and the database are already there.
"""

from collections.abc import Mapping
from pathlib import Path

from conftest import (
    basic_session,
    claude_projects,
    run_ccw,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)

UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
UUID_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"


def _seed_two_sessions(env: Mapping[str, str]) -> tuple[Path, Path]:
    a = write_transcript(env, basic_session(session_id=UUID_A), session_id=UUID_A)
    b = write_transcript(env, basic_session(session_id=UUID_B), session_id=UUID_B)
    return a, b


# ---------------------------------------------------------------------------
# --dry-run writes nothing
# ---------------------------------------------------------------------------


def test_dry_run_on_a_fresh_root_creates_no_warehouse(ccw_env: dict[str, str]) -> None:
    """THE LOAD-BEARING TEST. A dry-run must not create the warehouse root, which
    means it may neither take the sweep lock (that mkdirs locks/) nor open the
    catalog (that creates the database)."""
    _seed_two_sessions(ccw_env)
    root = warehouse_root(ccw_env)
    assert not root.exists(), "fixture precondition: the root must not exist yet"

    result = run_ccw(["sweep", "--dry-run"], ccw_env)

    assert result.code == 0, f"exit {result.code}, err={result.err!r}"
    assert not root.exists(), (
        f"--dry-run created the warehouse root: {sorted(p.name for p in root.rglob('*'))}"
    )


def test_dry_run_leaves_an_existing_warehouse_byte_identical(
    ccw_env: dict[str, str],
) -> None:
    """A real sweep first, so the warehouse exists and is populated. A dry-run
    over MORE work must then change not one byte."""
    _seed_two_sessions(ccw_env)
    assert run_ccw(["sweep"], ccw_env).code == 0
    root = warehouse_root(ccw_env)
    before = tree_snapshot(root)

    write_transcript(
        ccw_env,
        basic_session(session_id="cccccccc-3333-4333-8333-cccccccccccc"),
        session_id="cccccccc-3333-4333-8333-cccccccccccc",
    )
    result = run_ccw(["sweep", "--dry-run"], ccw_env)

    assert result.code == 0, f"exit {result.code}, err={result.err!r}"
    assert tree_snapshot(root) == before, "--dry-run mutated the warehouse"


def test_dry_run_does_not_consume_the_source(ccw_env: dict[str, str]) -> None:
    """Sources are read-only (F9), and a rehearsal must not change that."""
    a, b = _seed_two_sessions(ccw_env)
    before = {p: p.read_bytes() for p in (a, b)}

    run_ccw(["sweep", "--dry-run"], ccw_env)

    assert {p: p.read_bytes() for p in (a, b)} == before


# ---------------------------------------------------------------------------
# --dry-run predicts the real run
# ---------------------------------------------------------------------------


def test_dry_run_names_every_item_the_real_run_imports(ccw_env: dict[str, str]) -> None:
    """The rehearsal is only worth running if it agrees with the performance.
    Both sessions must be NAMED, not merely counted, so an operator can read the
    list before committing to it."""
    _seed_two_sessions(ccw_env)

    rehearsal = run_ccw(["sweep", "--dry-run"], ccw_env)
    assert rehearsal.code == 0
    for uuid in (UUID_A, UUID_B):
        assert f"{uuid}.jsonl" in rehearsal.out, (
            f"{uuid} missing from the dry-run report: {rehearsal.out!r}"
        )


def test_dry_run_count_agrees_with_the_real_run(ccw_env: dict[str, str]) -> None:
    """Same fixture, rehearsal then run: the number of items the dry-run said it
    would import is the number the real run stores."""
    _seed_two_sessions(ccw_env)

    rehearsal = run_ccw(["sweep", "--dry-run"], ccw_env)
    real = run_ccw(["sweep"], ccw_env)

    assert rehearsal.code == 0 and real.code == 0
    assert "2" in rehearsal.out, f"dry-run did not report 2 items: {rehearsal.out!r}"
    assert "2 stored" in real.out, f"real run did not store 2: {real.out!r}"


def test_dry_run_reports_nothing_to_do_as_zero_not_as_failure(
    ccw_env: dict[str, str],
) -> None:
    """An empty rehearsal is a successful answer, not an error."""
    _seed_two_sessions(ccw_env)
    assert run_ccw(["sweep"], ccw_env).code == 0

    rehearsal = run_ccw(["sweep", "--dry-run"], ccw_env)

    assert rehearsal.code == 0
    assert rehearsal.out.strip(), "a dry-run with nothing to do still reports"


def test_dry_run_honours_the_import_window(ccw_env: dict[str, str]) -> None:
    """--dry-run composes with --since/--until rather than ignoring them, or the
    rehearsal would misrepresent a windowed run."""
    _seed_two_sessions(ccw_env)

    narrowed = run_ccw(["sweep", "--dry-run", "--since", "2099-01-01"], ccw_env)

    assert narrowed.code == 0
    for uuid in (UUID_A, UUID_B):
        assert f"{uuid}.jsonl" not in narrowed.out, (
            "a window in the future still listed sessions"
        )


# ---------------------------------------------------------------------------
# --quiet
# ---------------------------------------------------------------------------


def test_quiet_suppresses_the_summary_on_a_clean_run(ccw_env: dict[str, str]) -> None:
    """A cron sweep that prints on every success is one whose output nobody
    reads. NOTE: `_run_sweep` emits no per-item SUCCESS lines today, only
    failures plus one end summary, so the summary IS what --quiet suppresses."""
    _seed_two_sessions(ccw_env)

    loud = run_ccw(["sweep"], ccw_env)
    assert loud.code == 0 and loud.out.strip()

    _seed_two_sessions(ccw_env)
    quiet = run_ccw(["sweep", "--quiet"], ccw_env)

    assert quiet.code == 0
    assert not quiet.out.strip(), f"--quiet still printed: {quiet.out!r}"


def test_quiet_never_suppresses_a_failure(ccw_env: dict[str, str]) -> None:
    """R10: a batch names every failed item and carries on. --quiet is about
    noise, never about hiding a problem.

    THE FIRST VERSION OF THIS TEST WAS WRONG, and the product was right. It fed
    a malformed payload (`{ this is not json`) expecting a capture failure.
    Measured: `sweep: 1 items, 1 stored, 0 failed`. The store is content
    addressed and takes the bytes whatever they are; malformed LINES are counted
    into the manifest's loss block, not rejected. A capture that refused
    unparseable input would lose exactly the sessions most worth keeping.

    So this uses a genuinely reachable failure instead: `_walk_source` turns an
    unreadable source directory into a named error item via os.walk(onerror=...),
    which is the R10 path the flag must never hide.
    """
    unreadable = claude_projects(ccw_env) / "-home-alice-locked"
    unreadable.mkdir(parents=True)
    (unreadable / f"{UUID_A}.jsonl").write_bytes(basic_session(session_id=UUID_A))
    unreadable.chmod(0o000)
    try:
        result = run_ccw(["sweep", "--quiet"], ccw_env)
    finally:
        unreadable.chmod(0o755)

    assert result.code != 0, f"an unreadable source directory exited 0: {result.out!r}"
    assert result.err.strip(), "a failing item produced no output under --quiet"
    assert "locked" in result.err, f"the failed item was not named: {result.err!r}"


def test_quiet_and_dry_run_compose(ccw_env: dict[str, str]) -> None:
    """Both flags together stay a rehearsal, and stay quiet."""
    _seed_two_sessions(ccw_env)
    root = warehouse_root(ccw_env)

    result = run_ccw(["sweep", "--dry-run", "--quiet"], ccw_env)

    assert result.code == 0
    assert not root.exists(), "--dry-run --quiet created the warehouse"
    assert not result.out.strip(), f"--quiet printed: {result.out!r}"
