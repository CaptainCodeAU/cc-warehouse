"""The /wrap-up command hands over to /pj:wrap-up and runs its steps only from there.

Gavin's picks, 2026-10-05 (engage #1014): /pj:wrap-up runs a project's own wrap-up
itself, and a project wrap-up typed on its own hands over to /pj:wrap-up. One path,
always marked. So `.claude/commands/wrap-up.md` must open with a handover step, must
be invocable by the model (no `disable-model-invocation`), must never mark the session
itself (`pj-wrap done` belongs to /pj:wrap-up), and must read the session id under
either name, since engage sessions set only `CLAUDE_CODE_SESSION_ID`.

These are text checks: the command is prose a model follows, so the words are the
contract. Each check has a control below it that proves it can fail.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMAND = ROOT / ".claude" / "commands" / "wrap-up.md"
PJ_HOMES = ROOT / ".claude" / "pj-homes"
HANDOFF = ROOT / "HANDOFF.md"

HANDOVER_LINE = "pj:wrap-up hands over to /wrap-up"
SESSION_ID = "${CLAUDE_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-}}"


def _frontmatter(text: str) -> str:
    return text.split("---", 2)[1]


def _steps(text: str) -> list[str]:
    """Each '## Step' section's text, in order."""
    return re.split(r"^## (?=Step )", text, flags=re.MULTILINE)[1:]


def _handover_problems(text: str) -> list[str]:
    """Why this command does not hand over first; empty when it does."""
    problems: list[str] = []
    if "disable-model-invocation" in _frontmatter(text):
        problems.append("the frontmatter still blocks the model from running it")
    steps = _steps(text)
    first = steps[0] if steps else ""
    for needed, why in (
        ("from-pj-wrap-up", "the first step does not check for the from-pj-wrap-up arg"),
        (HANDOVER_LINE, "the first step does not name the exact handover line"),
        ("~/.claude/pj/skills/wrap-up/SKILL.md", "the first step does not read /pj:wrap-up"),
        ("Handing over to /pj:wrap-up", "the first step does not say it is handing over"),
        ("`check`", "the first step does not say whether check mode hands over"),
    ):
        if needed not in first:
            problems.append(why)
    for line in text.splitlines():
        if "pj-wrap done" in line and "never" not in line.lower():
            problems.append(f"a line may run pj-wrap done: {line.strip()}")
    return problems


def _session_id_problems(text: str) -> list[str]:
    """Places that read the session id under one name only; empty when none do."""
    bare = text.replace(SESSION_ID, "")
    return [
        line.strip()
        for line in bare.splitlines()
        if re.search(r"\$\{?CLAUDE_(CODE_)?SESSION_ID", line)
    ]


def test_the_command_hands_over_to_pj_wrap_up_first() -> None:
    assert _handover_problems(COMMAND.read_text(encoding="utf-8")) == []


def test_the_handover_check_rejects_the_old_manual_only_command() -> None:
    """Control: the 2026-10-04 command (manual only, no handover step) must fail."""
    old = (
        "---\nname: wrap-up\ndisable-model-invocation: true\n---\n\n"
        "## Step 0 - did the last session actually close out?\n\nCheap.\n"
        "## Step 1 - the touched set\n\nThen run `pj-wrap done --skill`.\n"
    )
    problems = _handover_problems(old)
    assert any("frontmatter" in problem for problem in problems)
    assert any("from-pj-wrap-up" in problem for problem in problems)
    assert any("pj-wrap done" in problem for problem in problems)


def test_the_session_id_is_read_under_both_names() -> None:
    assert _session_id_problems(COMMAND.read_text(encoding="utf-8")) == []


def test_the_session_id_check_rejects_a_bare_name() -> None:
    """Control: the 2026-10-04 Step 0 line, which skipped every file in engage."""
    old = 'case "$f" in *"$CLAUDE_SESSION_ID"*) continue;; esac'
    assert _session_id_problems(old) != []
    assert _session_id_problems(f'case "$f" in *"{SESSION_ID}"*) continue;; esac') == []


def test_loose_ends_go_to_the_drawer_not_memory() -> None:
    """Memory is frozen under engage (D-20260929-A01); the queue is the drawer."""
    text = COMMAND.read_text(encoding="utf-8")
    assert "open-items add" in text
    assert "HANDOFF.md" in text
    assert "MemoryCuration" not in text
    assert "a memory file if it's a fact" not in text


def test_pj_homes_names_this_command_and_the_generated_handoff() -> None:
    homes = {
        key.strip(): value.strip()
        for key, value in (
            line.split(":", 1)
            for line in PJ_HOMES.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        )
    }
    assert homes["wrap-up"] == "/wrap-up"
    assert homes["handoff"] == "repo:HANDOFF.md"


def test_the_named_handoff_carries_the_generated_marker() -> None:
    """Without the marker /pj:wrap-up treats the file as hand-written and stops writing it."""
    first = HANDOFF.read_text(encoding="utf-8").splitlines()[0]
    assert first == "<!-- generated by /pj:wrap-up -->"
