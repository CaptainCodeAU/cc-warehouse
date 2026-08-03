"""Oracle tests: `ccw doctor` reports the install mode it is RUNNING under.

Contract: DESIGN section 7 (`ccw doctor` row), section 15 entry "`ccw doctor`,
AND WHY IT IS A VERB", and the CLAUDE.md hard rule that `ccw` is installed as a
frozen snapshot.

WHY THE TOOL MUST ANSWER THIS AND NOT A SHELL FUNCTION. `pyproject.toml` can PIN
the mode, but a pin is a request: it is advisory, honoured only by the operator's
own shell functions, inert on any other machine, and overridable by an explicit
flag. Nothing about it proves what is installed. The question doctor exists to
answer is "is capture working", and "which code does the capture hook actually
run" is part of that.

THE INSTRUMENT IS THE IMPORT PATH, not a file lookup, and that is deliberate.
Reading PEP 610's direct_url.json is the standard way to ask what uv RECORDED,
but it is four levels down under a version-stamped .dist-info, and a lookup that
misses returns empty. Empty reads as "no editable flag" and therefore as FROZEN,
which is the dangerous wrong answer, delivered silently, in the one place you
were checking not to assume it. I shipped exactly that bug in a documented
command on 2026-08-03.

`cc_warehouse.__file__` cannot miss. It is where the interpreter actually loaded
the code from, so it answers the question being asked rather than a question
about a record of it.
"""

from pathlib import Path

from cc_warehouse import doctor


def test_a_module_inside_site_packages_is_frozen() -> None:
    """A real copy in the tool environment: what `uv tool install` without
    `--editable` produces."""
    path = Path(
        "/Users/x/.local/share/uv/tools/cc-warehouse/lib/python3.14"
        "/site-packages/cc_warehouse/__init__.py"
    )
    assert doctor.install_mode(path) == "frozen"


def test_a_module_in_a_source_checkout_is_editable() -> None:
    """The live-pointer case the CLAUDE.md hard rule exists to prevent."""
    path = Path("/Users/x/CODE/CaptainCodeAU/cc-warehouse/src/cc_warehouse/__init__.py")
    assert doctor.install_mode(path) == "editable"


def test_the_dist_packages_spelling_counts_too() -> None:
    """Debian and friends install into dist-packages. Not this machine, but the
    check should not silently call a system install editable."""
    path = Path("/usr/lib/python3/dist-packages/cc_warehouse/__init__.py")
    assert doctor.install_mode(path) == "frozen"


def test_doctor_reports_the_mode_and_the_path(ccw_env: dict[str, str]) -> None:
    """It must name WHERE, not just which mode. The 2026-07-24 failure was a name
    resolving to the wrong program, so a bare label is not enough."""
    from conftest import run_ccw

    result = run_ccw(["doctor"], ccw_env)
    line = next((ln for ln in result.out.splitlines() if " install " in ln), "")

    assert line, f"no install line in doctor output: {result.out!r}"
    assert "cc_warehouse" in line, line
    assert ("frozen" in line) or ("editable" in line), line


def test_the_install_check_never_blocks(ccw_env: dict[str, str]) -> None:
    """Reported, not enforced. Editable is the correct mode while developing, so
    failing on it would make doctor cry wolf for anyone working on the code, and
    a check that fails constantly is one nobody reads.

    Asserted by construction rather than by output: a warehouse healthy in every
    other respect exits 0 whatever the install mode happens to be.
    """
    checks = {c.name: c for c in doctor.diagnose(_config(ccw_env)).checks}
    assert "install" in checks, sorted(checks)
    assert checks["install"].blocking is False


def _config(env: dict[str, str]):
    from cc_warehouse.config import Config

    return Config(root=Path(env["CCW_ROOT"]))
