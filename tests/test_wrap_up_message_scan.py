"""The /wrap-up command's commit-message leak scan must prove itself before it counts.

`.claude/commands/wrap-up.md` step 7 scans commit messages with gitleaks, because no
`git diff` ever shows them. On 2026-10-02 a session planted a HAND-TYPED control token
(the `ghp_aBcD...` shape), saw gitleaks pass it, and blamed the tool. gitleaks skips
low-entropy matches in every mode, so the control was invalid, not the tool. These
tests keep the snippet's control token random, and (where gitleaks is installed) prove
that the snippet's own commands catch a random token and pass clean text.
"""

from __future__ import annotations

import re
import secrets
import shutil
import string
import subprocess
from pathlib import Path

import pytest

COMMAND = Path(__file__).resolve().parents[1] / ".claude" / "commands" / "wrap-up.md"
_HAND_TYPED = re.compile(r"ghp_[A-Za-z0-9]{36}")


def _message_scan_snippet(text: str) -> list[str]:
    """The bash block under step 7's 'Commit MESSAGES' item, one command per line."""
    start = text.index("**Commit MESSAGES never appear")
    block = text[start:].split("```bash", 1)[1].split("```", 1)[0]
    return [line.strip() for line in block.strip().splitlines() if line.strip()]


def _control_problems(lines: list[str]) -> list[str]:
    """Why this snippet's control cannot be trusted; empty when it can."""
    problems: list[str] = []
    joined = "\n".join(lines)
    if _HAND_TYPED.search(joined):
        problems.append("a hand-typed ghp_ token (low entropy, gitleaks skips it)")
    planted = [line for line in lines if "ghp_" in line]
    if not planted:
        problems.append("no planted ghp_ control token before the real scan")
    elif "secrets" not in planted[0] or "range(36)" not in planted[0]:
        problems.append("the control token is not 36 characters from the secrets module")
    if "must be 1" not in joined:
        problems.append("the control's expected exit code (1) is not stated")
    scans = [index for index, line in enumerate(lines) if "git log --format=%B" in line]
    controls = [index for index, line in enumerate(lines) if "control rc=" in line]
    if not scans or not controls or controls[0] > scans[0]:
        problems.append("the control does not run before the real scan")
    return problems


def _scanner(lines: list[str]) -> str:
    """The gitleaks command the real scan pipes commit messages into."""
    scan = next(line for line in lines if "git log --format=%B" in line)
    return scan.split("|", 1)[1].strip()


def test_the_message_scan_control_token_is_random_and_runs_first() -> None:
    lines = _message_scan_snippet(COMMAND.read_text(encoding="utf-8"))
    assert _control_problems(lines) == []


def test_the_control_check_rejects_a_hand_typed_token() -> None:
    """Control for the test above: the 2026-10-02 mistake must be caught."""
    # Assembled at runtime: a literal token shape here would trip this repo's own
    # packaging scan and the pre-commit leak scan, which is them working correctly.
    hand_typed = "ghp" + "_" + "aBcDeFgHiJkLmNoPqRsTuVwXyZ" + "0123456789"
    bad = [
        f"printf 'token %s\\n' '{hand_typed}'"
        ' | gitleaks stdin --no-banner; echo "control rc=$? (must be 1)"',
        "git log --format=%B SESSION_START_REF..HEAD | gitleaks stdin --no-banner",
    ]
    assert any("hand-typed" in problem for problem in _control_problems(bad))


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not on PATH")
def test_the_snippets_scanner_catches_a_random_token_and_passes_clean_text() -> None:
    scanner = _scanner(_message_scan_snippet(COMMAND.read_text(encoding="utf-8")))
    token = "ghp_" + "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(36)
    )

    def run(text: str) -> int:
        return subprocess.run(
            ["bash", "-c", scanner],
            input=text,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        ).returncode

    assert run(f"docs: an ordinary commit message\n\nleaked {token}\n") == 1
    assert run("docs: an ordinary commit message\n\nnothing secret here\n") == 0
