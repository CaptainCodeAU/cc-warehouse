"""Static fence tests: structural rules enforced as gates from commit one.

These scan the runtime source tree (src/cc_warehouse) and are expected to be
GREEN at all times, including before implementation; they make whole failure
classes impossible rather than testing behavior (FINDINGS F1, F6, F9; DESIGN
R2, R4, R7, R8).
"""

import ast
import sys
from pathlib import Path

from conftest import SRC_ROOT, TESTS_ROOT

# Modules sanctioned to delete files, and only inside projections/ / shares/
# (DESIGN R4: the projections/shares rebuild module).
DELETE_SANCTIONED = {"build.py", "share.py"}

# The O_EXCL lock helpers in store.py may remove lock files: DESIGN section 13's
# closed list sanctions lock files "created/removed with O_EXCL semantics" and
# DESIGN R4's closed list names lock release. Function-scoped so the store's
# object/catalog surface stays delete-free. Decided at slice-01 triage,
# 2026-07-18 (principal).
LOCK_DELETE_SANCTIONED: dict[str, set[str]] = {
    "store.py": {"acquire_lock", "release_lock"},
}

# Modules sanctioned to open file handles for writing: store.py owns the write
# primitive (tmp + os.replace) and the O_EXCL locks; notify.py owns the
# O_APPEND audit log (DESIGN section 13 closed list).
WRITE_SANCTIONED = {"store.py", "notify.py"}

# R8 / F6: guarantee words in runtime strings must cite the oracle test that
# proves them. (file name, word) -> test function name that must exist.
GUARANTEE_WORDS = ("atomic", "identical", "byte-equal", "byte for byte", "never delete")
GUARANTEE_PROOFS: dict[tuple[str, str], str] = {
    ("store.py", "atomic"): "test_interrupted_write_leaves_no_partial_final_file",
    ("relocate.py", "atomic"): "test_interrupted_write_leaves_no_partial_final_file",
}


def runtime_files() -> list[Path]:
    files = sorted(SRC_ROOT.glob("*.py"))
    assert files, f"no runtime files under {SRC_ROOT}"
    return files


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_runtime_is_stdlib_only() -> None:
    """DESIGN R7: a third-party import anywhere in runtime code is a rejection."""
    offenders: list[str] = []
    for path in runtime_files():
        for node in ast.walk(parse(path)):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                top = name.split(".")[0]
                if top != "cc_warehouse" and top not in sys.stdlib_module_names:
                    offenders.append(f"{path.name}: import {name}")
    assert not offenders, f"non-stdlib imports in runtime code (R7): {offenders}"


def _is_delete_call(node: ast.Call) -> str | None:
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    attr = func.attr
    if isinstance(func.value, ast.Name) and func.value.id in {"os", "shutil"}:
        if (func.value.id, attr) in {
            ("os", "remove"),
            ("os", "unlink"),
            ("os", "rmdir"),
            ("os", "removedirs"),
            ("shutil", "rmtree"),
        }:
            return f"{func.value.id}.{attr}"
        return None
    # Method-style deletions (Path.unlink, Path.rmdir) on any receiver.
    if attr in {"unlink", "rmdir", "rmtree"}:
        return f".{attr}"
    return None


def test_no_deletion_primitives_outside_rebuild_modules() -> None:
    """DESIGN R4 / FINDINGS F9: the store's object/catalog surface has no delete
    primitive; file removal exists only in the projections/shares rebuild modules
    and the O_EXCL lock helpers (DESIGN section 13 closed list)."""
    offenders: list[str] = []
    for path in runtime_files():
        if path.name in DELETE_SANCTIONED:
            continue
        tree = parse(path)
        sanctioned_funcs = LOCK_DELETE_SANCTIONED.get(path.name, set())
        skip_lines: set[int] = set()
        for top in tree.body:
            if isinstance(top, ast.FunctionDef) and top.name in sanctioned_funcs:
                skip_lines.update(range(top.lineno, (top.end_lineno or top.lineno) + 1))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.lineno not in skip_lines:
                hit = _is_delete_call(node)
                if hit:
                    offenders.append(f"{path.name}:{node.lineno} {hit}")
    assert not offenders, f"deletion primitives outside sanctioned modules (R4): {offenders}"


def _compare_uses_stat_field(node: ast.Compare) -> str | None:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr in {
            "st_size",
            "st_mtime",
            "st_mtime_ns",
        }:
            return sub.attr
    return None


def test_no_size_or_mtime_equality_anywhere() -> None:
    """FINDINGS F1 grep gate: no comparison of st_size / st_mtime values anywhere
    in runtime code; sizes and mtimes are display metadata, never identity."""
    offenders: list[str] = []
    for path in runtime_files():
        for node in ast.walk(parse(path)):
            if isinstance(node, ast.Compare):
                hit = _compare_uses_stat_field(node)
                if hit:
                    offenders.append(f"{path.name}:{node.lineno} compares {hit}")
    assert not offenders, f"stat-attribute comparisons (F1): {offenders}"


def _is_write_open(node: ast.Call) -> str | None:
    func = node.func
    # builtins.open(path, "w"/"a"/"x"/...b) with a write-capable mode.
    if isinstance(func, ast.Name) and func.id == "open":
        mode: object = "r"
        if len(node.args) >= 2:
            arg = node.args[1]
            mode = arg.value if isinstance(arg, ast.Constant) else None
        for kw in node.keywords:
            if kw.arg == "mode":
                mode = kw.value.value if isinstance(kw.value, ast.Constant) else None
        if mode is None:
            return "open(with non-literal mode)"
        if isinstance(mode, str) and any(c in mode for c in "wax+"):
            return f"open(mode={mode!r})"
        return None
    if isinstance(func, ast.Attribute):
        if func.attr in {"write_text", "write_bytes"}:
            return f".{func.attr}"
        if (
            func.attr == "open"
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
        ):
            return "os.open"
    return None


def test_write_handles_only_in_sanctioned_modules() -> None:
    """DESIGN R2: atomic_write (tmp + os.replace) is the only file write path;
    direct write_text / open('w') on final paths is a rejection. Closed
    exceptions: SQLite's own writes, the O_APPEND audit log, O_EXCL locks."""
    offenders: list[str] = []
    for path in runtime_files():
        if path.name in WRITE_SANCTIONED:
            continue
        for node in ast.walk(parse(path)):
            if isinstance(node, ast.Call):
                hit = _is_write_open(node)
                if hit:
                    offenders.append(f"{path.name}:{node.lineno} {hit}")
    assert not offenders, f"write handles outside sanctioned modules (R2): {offenders}"


def _string_constants(tree: ast.Module) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.lineno, node.value))
    return out


def _proof_exists(test_name: str) -> bool:
    for path in TESTS_ROOT.glob("test_*.py"):
        if f"def {test_name}(" in path.read_text(encoding="utf-8"):
            return True
    return False


def test_guarantee_words_cite_their_proving_test() -> None:
    """DESIGN R8 / FINDINGS F6: any guarantee word in a runtime string or
    docstring must map to an existing oracle test that proves that word."""
    problems: list[str] = []
    for path in runtime_files():
        for lineno, text in _string_constants(parse(path)):
            lowered = text.lower()
            for word in GUARANTEE_WORDS:
                if word in lowered:
                    proof = GUARANTEE_PROOFS.get((path.name, word))
                    if proof is None:
                        problems.append(
                            f"{path.name}:{lineno} says {word!r} with no proof mapping"
                        )
                    elif not _proof_exists(proof):
                        problems.append(
                            f"{path.name}:{lineno} cites missing test {proof!r}"
                        )
    assert not problems, f"unproven guarantee words (R8/F6): {problems}"


def test_prompt_wrappers_carry_no_logic() -> None:
    """DESIGN R9 / FINDINGS F8: wrapper entry points carry env only. The console
    scripts must resolve to the single cli:main implementation."""
    text = (SRC_ROOT.parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert 'ccw = "cc_warehouse.cli:main"' in text
    assert 'cc-warehouse = "cc_warehouse.cli:main"' in text
