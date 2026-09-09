"""Oracle tests: `find_ccw()` must never hand back a path inside a `.venv`
(ticket 41 Finding 1).

Confirmed live 2026-09-09: this repo's own `.envrc` activates `.venv/bin`
whenever a shell's cwd is under the repo, which puts it ahead of
`~/.local/bin` on PATH. Both hook scripts resolve `ccw` with
`shutil.which("ccw")`, so a hook fired from a cc-warehouse session picked the
editable dev checkout instead of the frozen install - proven the same day by
a `ccw-hook.log` "started" line whose own `python` field pointed at
`.../cc-warehouse/.venv/bin/python3`, and a freshness-check `TimeoutExpired`
against that same dev copy (`_DOCTOR_TIMEOUT=45`, four session-starts running).
The dev checkout is CLAUDE.md's own documented hazard: editing it live-edits
what the hook runs. `find_ccw()` must skip a PATH hit under `.venv` and fall
through to the frozen shim instead of trusting whatever `shutil.which` finds.
"""

from pathlib import Path
from types import ModuleType

import pytest

from conftest import load_hook_module

MODULES = [
    ("ccw_hook", "ccw-hook.py"),
    ("ccw_freshness_check", "ccw-freshness-check.py"),
]


@pytest.mark.parametrize("name,filename", MODULES)
def test_skips_a_venv_path_and_falls_back_to_the_shim(
    name: str, filename: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module: ModuleType = load_hook_module(name, filename)
    dev_checkout = str(tmp_path / "some-repo" / ".venv" / "bin" / "ccw")

    def _which(_name: str) -> str:
        return dev_checkout

    monkeypatch.setattr(module.shutil, "which", _which)
    shim = tmp_path / ".local" / "bin" / "ccw"
    shim.parent.mkdir(parents=True)
    shim.write_text("#!/bin/sh\necho fake\n", encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("CCW_BIN", raising=False)

    assert module.find_ccw() == str(shim)


@pytest.mark.parametrize("name,filename", MODULES)
def test_still_prefers_a_non_venv_path_on_path(
    name: str, filename: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module: ModuleType = load_hook_module(name, filename)
    real = "/usr/local/bin/ccw"

    def _which(_name: str) -> str:
        return real

    monkeypatch.setattr(module.shutil, "which", _which)
    monkeypatch.delenv("CCW_BIN", raising=False)

    assert module.find_ccw() == real


@pytest.mark.parametrize("name,filename", MODULES)
def test_ccw_bin_override_still_wins_even_inside_a_venv(
    name: str, filename: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module: ModuleType = load_hook_module(name, filename)
    override = tmp_path / ".venv" / "bin" / "ccw"
    override.parent.mkdir(parents=True)
    override.write_text("#!/bin/sh\necho fake\n", encoding="utf-8")
    override.chmod(0o755)
    monkeypatch.setenv("CCW_BIN", str(override))

    assert module.find_ccw() == str(override)
