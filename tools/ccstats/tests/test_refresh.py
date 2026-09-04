"""`refresh.py`, the unattended dashboard rebuild.

Every test here fakes `subprocess.run`, so nothing scans a transcript, nothing
reads the real `sessions.sqlite`, and nothing writes a page. What is under test
is the ORCHESTRATION: which children run, with which arguments, in which order,
and what the exit code and log look like when one of them fails.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

CCSTATS = Path(__file__).resolve().parent.parent
if str(CCSTATS) not in sys.path:
    sys.path.insert(0, str(CCSTATS))

import refresh  # noqa: E402


class FakeProc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def install(monkeypatch: pytest.MonkeyPatch, outcomes: dict[str, FakeProc]) -> list[list[str]]:
    """Replace `subprocess.run` and record every command line it was given.

    `outcomes` is keyed by script basename; anything not named exits 0 silently.
    """
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> FakeProc:
        calls.append(list(cmd))
        return outcomes.get(Path(cmd[1]).name, FakeProc(0))

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def scripts(calls: list[list[str]]) -> list[str]:
    return [Path(c[1]).name for c in calls]


def test_happy_path_runs_collect_then_dashboard(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = install(monkeypatch, {})
    assert refresh.main(["--quiet"]) == 0
    assert scripts(calls) == ["collect.py", "dashboard.py"]
    # --quiet on success is silent, so an empty log means healthy.
    assert capsys.readouterr().out == ""


def test_children_inherit_this_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never a bare `python3`: under launchd that resolves to the 3.9 system build."""
    calls = install(monkeypatch, {})
    refresh.main(["--quiet"])
    assert [c[0] for c in calls] == [sys.executable, sys.executable]


def test_dashboard_gets_no_filter_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """The anti-drift property.

    `dashboard.py` reads `dashboard-defaults.json` itself. If this script ever
    starts passing its own --include/--exclude, the scheduled page and a
    `/dashboard` page can disagree, which is the exact bug
    `load_default_filters` was written to close.
    """
    calls = install(monkeypatch, {})
    refresh.main(["--quiet"])
    dash = next(c for c in calls if Path(c[1]).name == "dashboard.py")
    assert dash[2:] == []


def test_collect_is_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch, {})
    refresh.main([])
    coll = next(c for c in calls if Path(c[1]).name == "collect.py")
    assert coll[2:] == ["--quiet"]


def test_skip_collect_only_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch, {})
    assert refresh.main(["--skip-collect", "--quiet"]) == 0
    assert scripts(calls) == ["dashboard.py"]


def test_failed_scan_still_builds_but_reports_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stale page beats no page, but the exit status must not lie."""
    calls = install(monkeypatch, {"collect.py": FakeProc(2, stderr="boom")})
    assert refresh.main(["--quiet"]) == 1
    assert scripts(calls) == ["collect.py", "dashboard.py"]
    out = capsys.readouterr().out
    # --quiet is overridden by failure: the whole run must reach the log.
    assert "boom" in out
    assert "collect.py exited 2" in out


def test_failed_build_reports_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, {"dashboard.py": FakeProc(1, stderr="nope")})
    assert refresh.main(["--quiet"]) == 1
    assert "nope" in capsys.readouterr().out


def test_unknown_flag_refuses(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = install(monkeypatch, {})
    assert refresh.main(["--exclude", "secret-project"]) == 2
    assert calls == []
    assert "unknown argument" in capsys.readouterr().err


def test_help_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch, {})
    assert refresh.main(["--help"]) == 0
    assert calls == []


def test_non_quiet_success_still_logs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, {})
    assert refresh.main([]) == 0
    out = capsys.readouterr().out
    assert "ccstats refresh" in out
    assert "dashboard" in out
