"""Oracle tests: `-h` prints help and performs NO work, on every verb.

Contract: DESIGN section 7 ("`-h`/`--help` lists every USER-FACING verb", and
`run 'ccw <verb> -h' for a verb's options` is what bare ccw tells the operator to
do). The stronger property this file pins is not in any document because nobody
thought it needed saying: ASKING A TOOL FOR HELP MUST NOT MAKE IT ACT.

Found the hard way on 2026-08-01. `ccw sweep -h` did not print help; it ran a
full sweep and imported 13,836 sessions into a real warehouse. Eight of the ten
verbs never checked for the flag, and three of those eight mutate the world:
sweep imports, migrate imports a legacy archive, relocate moves things OUTSIDE
the warehouse entirely.

Nothing was lost, because the store is content-addressed and append-only and
sources are read-only (F9) - the damage a help flag can do here is bounded by
the same invariants that bound everything else. That is luck about this product,
not a property of the fix.

The verb list is taken from cli._VERBS, the same tuple the help text is built
from, so a verb added later is covered the day it is added rather than the day
someone remembers this file.
"""

from pathlib import Path

import pytest

from conftest import claude_projects, run_ccw, run_cli, warehouse_root


def _verbs_from_help() -> tuple[str, ...]:
    """Every verb `ccw -h` lists, read from the help text itself.

    Taken from the PUBLIC surface rather than from cli._VERBS: the promise being
    tested is about what an operator can type after reading the help, so the
    help is the right source. It also means a verb listed but unhandled, or
    handled but unlisted, shows up here rather than passing quietly.
    """
    listing = run_cli(["-h"]).out
    return tuple(
        line.strip().split()[0]
        for line in listing.splitlines()
        if line.startswith("  ") and line.strip() and not line.strip().startswith("-")
    )


VERB_NAMES = _verbs_from_help()

# The flags an operator would reasonably type to ask for help.
HELP_FLAGS = ("-h", "--help")


@pytest.mark.parametrize("verb", VERB_NAMES)
@pytest.mark.parametrize("flag", HELP_FLAGS)
def test_help_exits_zero_and_prints_something(
    ccw_env: dict[str, str], verb: str, flag: str
) -> None:
    """Help is a successful, informative outcome on every verb, not an error and
    not silence. `ccw share -h` used to print `Error: ccw share requires --out`."""
    result = run_ccw([verb, flag], ccw_env, stdin="")
    assert result.code == 0, f"{verb} {flag}: exit {result.code}, err={result.err!r}"
    assert result.out.strip(), f"{verb} {flag} printed nothing"
    assert not result.err.strip(), f"{verb} {flag} wrote to stderr: {result.err!r}"


@pytest.mark.parametrize("verb", VERB_NAMES)
@pytest.mark.parametrize("flag", HELP_FLAGS)
def test_help_creates_no_warehouse(ccw_env: dict[str, str], verb: str, flag: str) -> None:
    """The mechanical proof that no work happened: every verb that does anything
    real must open or create the warehouse root, so an untouched root means the
    verb returned before acting.

    This is what would have caught the sweep: it imported 13,836 sessions and
    still exited 0 with output, so only asking "did the world change" separates
    help from work."""
    root = warehouse_root(ccw_env)
    assert not root.exists(), "the fixture should start with no warehouse"
    run_ccw([verb, flag], ccw_env, stdin="")
    assert not root.exists(), f"`ccw {verb} {flag}` created the warehouse at {root}"


@pytest.mark.parametrize("flag", HELP_FLAGS)
def test_help_on_sweep_imports_nothing(ccw_env: dict[str, str], flag: str) -> None:
    """The regression that started this, pinned by name and with a session
    sitting in the source directory waiting to be swept."""
    projects = claude_projects(ccw_env) / "-home-alice-projects-widget"
    projects.mkdir(parents=True, exist_ok=True)
    from conftest import basic_session

    (projects / "waiting.jsonl").write_bytes(basic_session())
    result = run_ccw(["sweep", flag], ccw_env, stdin="")
    assert result.code == 0
    assert "stored" not in result.out, f"`ccw sweep {flag}` swept: {result.out!r}"
    assert not warehouse_root(ccw_env).exists()


@pytest.mark.parametrize("flag", HELP_FLAGS)
def test_help_on_migrate_imports_nothing(
    ccw_env: dict[str, str], tmp_path: Path, flag: str
) -> None:
    """migrate is the other importer, and it takes a path operand, so a help
    flag beside a real archive must still be help."""
    from conftest import basic_session

    archive = tmp_path / "legacy"
    archive.mkdir()
    (archive / "old.jsonl").write_bytes(basic_session())
    result = run_ccw(["migrate", str(archive), flag], ccw_env, stdin="")
    assert result.code == 0, result.err
    assert not warehouse_root(ccw_env).exists()


@pytest.mark.parametrize("flag", HELP_FLAGS)
def test_help_on_relocate_moves_nothing(
    ccw_env: dict[str, str], tmp_path: Path, flag: str
) -> None:
    """relocate is the one verb that mutates the world OUTSIDE the warehouse, so
    it is the one where a help flag doing work would be worst."""
    old = tmp_path / "old-project"
    old.mkdir()
    (old / "keep.txt").write_text("untouched")
    new = tmp_path / "new-project"
    result = run_ccw(["relocate", str(old), str(new), flag], ccw_env, stdin="")
    assert result.code == 0, result.err
    assert (old / "keep.txt").read_text() == "untouched", "relocate moved a real directory"
    assert not new.exists()


def test_the_verb_list_under_test_is_the_real_one() -> None:
    """Closed-world: the parametrization reads `ccw -h`, so this guards against
    the list silently going empty (which would make every test above vacuous)
    and against the parse drifting from the help format."""
    assert len(VERB_NAMES) >= 10, VERB_NAMES
    for expected in ("hook", "sweep", "render", "build", "share", "relocate", "verify"):
        assert expected in VERB_NAMES, f"{expected} missing from `ccw -h`"
