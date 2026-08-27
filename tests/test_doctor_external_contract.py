"""Fence: the exact substrings `ccw-watch` (a DIFFERENT repo) depends on.

Contract: `CLAUDE.md` ticket 28.22 / `harness/tickets/28-backlog.md`'s 28.22 entry.
`~/.local/bin/
ccw-watch` (fifty-shades-of-dotfiles, not this repo) runs `ccw doctor` at every
Claude Code SessionStart and parses its text with shell regex. Nothing else in
this suite protects that shape: a reformat of doctor's wording can break that
external consumer with nothing in THIS repo going red. This file pins exactly
the pieces ccw-watch reads, no more, so a change that matters shows up here
first instead of silently on the next session start.

THE CONTRACT, copied verbatim from ccw-watch as it stood on 2026-08-23
(`home/.local/bin/ccw-watch` in fifty-shades-of-dotfiles):

  1. Exit code: 0 means healthy, non-zero means broken (`status=$?`, then
     `if [[ $status -eq 0 ]]`). Already proved by many tests in
     `test_doctor.py` (e.g. `test_a_healthy_warehouse_exits_zero`,
     `test_no_hook_registered_is_a_failure`); restated here as one line so
     this file is a complete account of the external contract on its own.
  2. On the healthy path (line 149), ccw-watch extracts a figure with:
         sed -n 's/.*Uncaptured: \\([0-9]*\\) session.*/\\1/p'
     which needs the literal substring "Uncaptured: <digits> session"
     somewhere in the report (`status.py:152`, `gap_line`).
  3. On the broken path (line 216), ccw-watch shows the operator every line
     matching:
         grep -E '^\\s*FAIL'
     which needs a failed BLOCKING check to render its line with a leading
     "FAIL" (optional indentation before it) - `doctor.py:440`, `report_text`.

Properties 2 and 3 are proved by running the REAL sed/grep commands from
ccw-watch against real `ccw doctor` output, not a Python re-implementation of
the regex that could quietly drift from what the shell actually does.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import basic_session, run_ccw, warehouse_root, write_transcript

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"


def configure(env: dict[str, str], archive_root: Path) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(
        f'root = "{warehouse_root(env)}"\n'
        f'archive_timezone = "{ZONE}"\n'
        f'archive_root = "{archive_root}"\n',
        encoding="utf-8",
    )
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def install_hook(env: dict[str, str]) -> None:
    settings = Path(env["HOME"]) / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "ccw hook"}]}]}}
        ),
        encoding="utf-8",
    )


def _sed_uncaptured_count(report: str) -> str:
    """The EXACT command ccw-watch's `handle_ok` runs."""
    proc = subprocess.run(
        ["sed", "-n", r"s/.*Uncaptured: \([0-9]*\) session.*/\1/p"],
        input=report,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _grep_fail_lines(report: str) -> list[str]:
    """The EXACT command ccw-watch's broken path runs."""
    proc = subprocess.run(
        ["grep", "-E", r"^\s*FAIL"],
        input=report,
        capture_output=True,
        text=True,
    )
    return [ln for ln in proc.stdout.splitlines() if ln]


@pytest.mark.skipif(shutil.which("sed") is None, reason="sed not on PATH")
def test_a_healthy_report_survives_ccw_watchs_real_sed_command(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    configure(ccw_env, tmp_path / "archive")
    install_hook(ccw_env)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0

    result = run_ccw(["doctor"], ccw_env)
    assert result.code == 0, f"fixture is not actually healthy: {result.out}"

    extracted = _sed_uncaptured_count(result.out)
    assert extracted.isdigit(), (
        f"ccw-watch's own sed command extracted {extracted!r}, not a plain "
        f"integer, from:\n{result.out}"
    )


@pytest.mark.skipif(shutil.which("grep") is None, reason="grep not on PATH")
def test_a_broken_report_survives_ccw_watchs_real_grep_command(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    configure(ccw_env, tmp_path / "archive")  # no install_hook(): the failure itself

    result = run_ccw(["doctor"], ccw_env)
    assert result.code != 0, f"fixture is not actually broken: {result.out}"

    lines = _grep_fail_lines(result.out)
    assert lines, (
        f"ccw-watch's own grep command found no FAIL line to show the "
        f"operator, from:\n{result.out}"
    )
