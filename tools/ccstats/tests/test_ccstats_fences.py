"""Structural fences: things that must stay true as the code moves.

These do not test behaviour. They make whole classes of drift impossible, in
the same spirit as the project's own `tests/test_fences.py`.
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

import collect
import pytest
from common import Out, Window, read_manifest_since, resolve_window, write_manifest

CCSTATS = Path(__file__).resolve().parent.parent
MODULES = sorted(p for p in CCSTATS.glob("*.py"))
REPO_SRC = CCSTATS.parent.parent / "src"


# ------------------------------------------------------- parity with src/
# `derive_label` is COPIED from src/cc_warehouse/registry.py so the labels here
# match what `ccw project list` shows. A copy with nothing enforcing it is a
# silent divergence waiting to happen, so this asserts they still agree.


def _real_derive_label():
    if str(REPO_SRC) not in sys.path:
        sys.path.insert(0, str(REPO_SRC))
    try:
        from cc_warehouse.registry import derive_label
    except ImportError:  # pragma: no cover - only when run outside the repo
        pytest.skip("src/cc_warehouse not importable")
    return derive_label


@pytest.mark.parametrize(
    "path",
    [
        "/Users/x/CODE/CaptainCodeAU/docbrain",
        "/Users/x/CODE/CaptainCodeAU/docbrain/.worktree/benchmarking",
        "/Users/x/CODE/Scaffoldings/fifty-shades-of-dotfiles",
        "/Users/x/.claude",
        "/home/y/projects/thing",
        "/mnt/c/users/z/dev/app",
        "/Users/x/CODE/repos/src/dev/work/documents/deep",
        "/",
        "relative/path",
        "",
    ],
)
def test_derive_label_matches_the_real_one(path: str) -> None:
    assert collect.derive_label(path) == _real_derive_label()(path)


# ------------------------------------------------ no duplicated constants
# OUT_DIR was defined 5 times, DB 3 times, XLSX 3 times, and COST_NOTE twice
# WITH DIFFERENT WORDING, so two CSVs in one folder carried two disclaimers.
# `DB`/`XLSX`/`DOC`/`REPORT`/`SESSIONS_CSV`/`SNAPSHOT`/`MANIFEST` are no longer
# bare names at all: they moved to `Out` properties (see
# `test_regressions.py::test_every_out_path_sits_under_the_resolved_root`),
# which structurally cannot be redefined per-module the way a bare constant
# could.

SHARED = {
    "DEFAULT_OUT", "REPO_ROOT", "ARCHIVE", "LIVE", "CATALOG", "HOME",
    "COST_NOTE", "IDLE_GAP_SECONDS", "DAY_SECONDS",
}


def test_shared_constants_are_defined_only_in_common() -> None:
    defined: dict[str, list[str]] = defaultdict(list)
    for module in MODULES:
        if module.name == "common.py":
            continue
        for node in ast.parse(module.read_text()).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in SHARED:
                        defined[target.id].append(f"{module.name}:{node.lineno}")
    assert defined == {}, (
        "these belong in common.py only, or they drift apart: "
        f"{dict(defined)}"
    )


def test_the_window_has_exactly_one_implementation() -> None:
    """No module may rebuild the `local_date >=` predicate by hand."""
    offenders = []
    for module in MODULES:
        if module.name == "common.py":
            continue
        for i, line in enumerate(module.read_text().split("\n"), 1):
            if "local_date >=" in line:
                offenders.append(f"{module.name}:{i}")
    assert offenders == [], (
        "build the predicate from common.Window instead: " + ", ".join(offenders)
    )


def test_no_module_parses_since_by_hand() -> None:
    """`--since` must go through common.parse_since, which validates it."""
    offenders = []
    for module in MODULES:
        if module.name == "common.py":
            continue
        text = module.read_text()
        for i, line in enumerate(text.split("\n"), 1):
            if 'index("--since")' in line:
                offenders.append(f"{module.name}:{i}")
    assert offenders == [], "unvalidated --since parsing: " + ", ".join(offenders)


# ---------------------------------------------------------- read-only-ness
# The collector reads source transcripts. It must contain no way to remove one.

DELETE_PRIMITIVES = ("rmtree", "os.remove", "os.rmdir", "shutil.move", "shutil.rmtree")


def test_no_module_can_delete_anything() -> None:
    offenders = []
    for module in MODULES:
        text = module.read_text()
        for primitive in DELETE_PRIMITIVES:
            if primitive in text:
                offenders.append(f"{module.name}: {primitive}")
        # `.unlink(` would also delete; allowed nowhere.
        if ".unlink(" in text:
            offenders.append(f"{module.name}: .unlink(")
    assert offenders == [], "ccstats must never delete: " + ", ".join(offenders)


# ------------------------------------------------------- window inheritance
# The window was retyped on three commands with nothing binding them, so the
# workbook and the guide came to describe different datasets.


def test_an_explicit_since_always_wins_over_the_manifest(tmp_path) -> None:
    out = Out(root=tmp_path)
    write_manifest(Window("2026-01-01"), "now", out)
    assert resolve_window(["--since", "2026-06-08"], out, inherit=True).since == "2026-06-08"


def test_with_no_flag_the_recorded_window_is_inherited(tmp_path) -> None:
    out = Out(root=tmp_path)
    write_manifest(Window("2026-06-08"), "now", out)
    assert resolve_window([], out, inherit=True).since == "2026-06-08"


def test_inheritance_can_be_declined(tmp_path) -> None:
    out = Out(root=tmp_path)
    write_manifest(Window("2026-06-08"), "now", out)
    assert resolve_window([], out, inherit=False).since == ""


def test_a_missing_manifest_means_full_range(tmp_path) -> None:
    out = Out(root=tmp_path / "absent")
    assert resolve_window([], out, inherit=True).since == ""


def test_manifest_roundtrip(tmp_path) -> None:
    out = Out(root=tmp_path)
    write_manifest(Window("2026-06-08"), "2026-08-21T00:00:00Z", out)
    assert read_manifest_since(out) == "2026-06-08"
