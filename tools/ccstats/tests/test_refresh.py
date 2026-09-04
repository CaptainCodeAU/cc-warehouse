"""`refresh.py`, the unattended dashboard rebuild.

Every test here fakes `subprocess.run`, so nothing scans a transcript, nothing
reads the real `sessions.sqlite`, nothing writes a page, and no notification
banner reaches the screen. What is under test is the ORCHESTRATION: which
children run, with which arguments, in which order, what the exit code and log
look like when one of them fails, and what the completion banner says.
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

PAGE = "/Users/x/.cc-warehouse/stats/claude-code-dashboard-live.html"
PAGE_LINE = f"{PAGE}  (1,714,214 bytes, 10,148 sessions, full range)"


class FakeProc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def key_of(cmd: list[str]) -> str:
    """What a recorded command line is keyed by: a child script, or osascript."""
    if Path(cmd[0]).name == "osascript":
        return "osascript"
    return Path(cmd[1]).name


def install(
    monkeypatch: pytest.MonkeyPatch, outcomes: dict[str, FakeProc] | None = None
) -> list[list[str]]:
    """Replace `subprocess.run` and record every command line it was given.

    `outcomes` is keyed the same way `key_of` keys; anything not named exits 0.
    `dashboard.py` defaults to a realistic success line so the page path this
    script reads back from it is exercised rather than stubbed away.
    """
    table = {"dashboard.py": FakeProc(0, stdout=PAGE_LINE)}
    table.update(outcomes or {})
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> FakeProc:
        calls.append(list(cmd))
        return table.get(key_of(cmd), FakeProc(0))

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def ran(calls: list[list[str]]) -> list[str]:
    return [key_of(c) for c in calls]


def banner(calls: list[list[str]]) -> str:
    """The AppleScript of the one notification posted."""
    posted = [c for c in calls if key_of(c) == "osascript"]
    assert len(posted) == 1, f"expected exactly one banner, got {len(posted)}"
    return posted[0][2]


# ------------------------------------------------------------- orchestration


def test_happy_path_runs_collect_then_dashboard(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = install(monkeypatch)
    assert refresh.main(["--quiet", "--no-notify"]) == 0
    assert ran(calls) == ["collect.py", "dashboard.py"]
    # --quiet on success is silent, so an empty log means healthy.
    assert capsys.readouterr().out == ""


def test_children_inherit_this_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never a bare `python3`: under launchd that resolves to the 3.9 system build."""
    calls = install(monkeypatch)
    refresh.main(["--quiet", "--no-notify"])
    assert [c[0] for c in calls] == [sys.executable, sys.executable]


def test_dashboard_gets_no_filter_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """The anti-drift property.

    `dashboard.py` reads `dashboard-defaults.json` itself. If this script ever
    starts passing its own --include/--exclude, the scheduled page and a
    `/dashboard` page can disagree, which is the exact bug
    `load_default_filters` was written to close.
    """
    calls = install(monkeypatch)
    refresh.main(["--quiet", "--no-notify"])
    dash = next(c for c in calls if key_of(c) == "dashboard.py")
    assert dash[2:] == []


def test_collect_is_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch)
    refresh.main(["--no-notify"])
    coll = next(c for c in calls if key_of(c) == "collect.py")
    assert coll[2:] == ["--quiet"]


def test_skip_collect_only_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch)
    assert refresh.main(["--skip-collect", "--quiet", "--no-notify"]) == 0
    assert ran(calls) == ["dashboard.py"]


def test_failed_scan_still_builds_but_reports_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stale page beats no page, but the exit status must not lie."""
    calls = install(monkeypatch, {"collect.py": FakeProc(2, stderr="boom")})
    assert refresh.main(["--quiet", "--no-notify"]) == 1
    assert ran(calls) == ["collect.py", "dashboard.py"]
    out = capsys.readouterr().out
    # --quiet is overridden by failure: the whole run must reach the log.
    assert "boom" in out
    assert "collect.py exited 2" in out


def test_failed_build_reports_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, {"dashboard.py": FakeProc(1, stderr="nope")})
    assert refresh.main(["--quiet", "--no-notify"]) == 1
    assert "nope" in capsys.readouterr().out


def test_unknown_flag_refuses(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = install(monkeypatch)
    assert refresh.main(["--exclude", "secret-project"]) == 2
    assert calls == []
    assert "unknown argument" in capsys.readouterr().err


def test_help_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch)
    assert refresh.main(["--help"]) == 0
    assert calls == []


def test_non_quiet_success_still_logs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch)
    assert refresh.main(["--no-notify"]) == 0
    out = capsys.readouterr().out
    assert "ccstats refresh" in out
    assert "dashboard" in out


# --------------------------------------------------------- the page path


def test_page_path_reads_the_dashboard_success_line() -> None:
    assert refresh.page_path(PAGE_LINE) == PAGE


def test_page_path_is_none_when_absent() -> None:
    """Better a banner that names no file than one that names the wrong file."""
    assert refresh.page_path("") is None
    assert refresh.page_path("error: refusing to write there") is None


# ------------------------------------------------------------ notification


def test_completion_posts_one_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch)
    assert refresh.main(["--quiet"]) == 0
    assert ran(calls) == ["collect.py", "dashboard.py", "osascript"]


def test_banner_names_the_program_and_the_page_in_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole ask: which program ran, and which file it produced, full paths."""
    calls = install(monkeypatch)
    refresh.main(["--quiet"])
    text = banner(calls)
    assert str(refresh.ME) in text
    assert PAGE in text
    assert "rebuilt" in text


def test_banner_uses_absolute_osascript(monkeypatch: pytest.MonkeyPatch) -> None:
    """launchd's PATH is near-empty, so a bare `osascript` would not resolve."""
    calls = install(monkeypatch)
    refresh.main(["--quiet"])
    posted = next(c for c in calls if key_of(c) == "osascript")
    assert posted[0] == "/usr/bin/osascript"
    assert posted[1] == "-e"


def test_banner_says_failed_when_the_page_was_not_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install(monkeypatch, {"dashboard.py": FakeProc(1, stderr="nope")})
    assert refresh.main(["--quiet"]) == 1
    text = banner(calls)
    assert "FAILED" in text
    assert "no page written" in text


def test_banner_says_stale_when_only_the_scan_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The page exists and is named, but the banner must not imply fresh data."""
    calls = install(monkeypatch, {"collect.py": FakeProc(2)})
    assert refresh.main(["--quiet"]) == 1
    text = banner(calls)
    assert "STALE" in text
    assert PAGE in text
    assert "data not refreshed" in text


def test_no_notify_posts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch)
    refresh.main(["--quiet", "--no-notify"])
    assert "osascript" not in ran(calls)


def test_a_broken_notifier_cannot_fail_the_job(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A notifier that takes down the job it reports on is worse than none."""
    install(monkeypatch, {"osascript": FakeProc(1, stderr="not allowed")})
    assert refresh.main([]) == 0
    out = capsys.readouterr().out
    assert "notification not sent" in out
    assert "not allowed" in out


def test_notifier_surviving_a_missing_binary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch)

    def boom(cmd: list[str], **_: Any) -> FakeProc:
        if key_of(cmd) == "osascript":
            raise OSError("No such file or directory")
        return FakeProc(0, stdout=PAGE_LINE)

    monkeypatch.setattr(subprocess, "run", boom)
    assert refresh.main([]) == 0
    assert "notification not sent" in capsys.readouterr().out


def test_applescript_quotes_are_escaped() -> None:
    """A path with a quote in it must not break out of the string literal."""
    got = refresh._applescript_string('a "b" \\ c')
    assert got == '"a \\"b\\" \\\\ c"'
