"""The /wrap-up command runs its steps only from /session-end, never on its own.

Gavin's picks, 2026-10-05 (engage #1014): one path closes a session, always marked.
That path was /pj:wrap-up until Gavin retired it (engage-main Q5 (v4): 1, 15 Oct 2026);
it is now /session-end, which runs this file in its middle with `from-pj-wrap-up`.
So `.claude/commands/wrap-up.md` must open with a step that checks for that argument,
must send a bare `/wrap-up` to /session-end and never to /pj:wrap-up, must be
invocable by the model (no `disable-model-invocation`), must never mark the session
itself (`pj-wrap done`), and must read the session id under either name, since engage
sessions set only `CLAUDE_CODE_SESSION_ID`.

Since 2026-10-19 (engage #3344) the captain's log entry /session-end writes is the one
handoff: `HANDOFF.md` is frozen, `.claude/pj-homes` names no handoff, and /wrap-up's
Step 5 writes no handoff file of its own.

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

HANDOVER_LINE = "session-end hands over to /wrap-up"
RETIRED_HANDOVER_LINE = "pj:wrap-up hands over to /wrap-up"
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
        ("Type /session-end instead", "the first step does not send a bare run to /session-end"),
        ("`check`", "the first step does not say whether check mode hands over"),
    ):
        if needed not in first:
            problems.append(why)
    for retired, why in (
        ("~/.claude/pj/skills/wrap-up/SKILL.md", "the first step still reads /pj:wrap-up"),
        ("Handing over to /pj:wrap-up", "the first step still hands over to /pj:wrap-up"),
        (RETIRED_HANDOVER_LINE, "the first step still waits for /pj:wrap-up's handover line"),
        ("Step H - hand over to /pj:wrap-up", "the first step's title still names /pj:wrap-up"),
    ):
        if retired in first:
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


def test_the_command_runs_only_from_session_end() -> None:
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


def test_the_handover_check_rejects_the_retired_pj_wrap_up_handover() -> None:
    """Control: the 2026-10-05 Step H, which sent a bare /wrap-up to /pj:wrap-up."""
    old = (
        "---\nname: wrap-up\n---\n\n"
        "## Step H - hand over to /pj:wrap-up, unless it sent you\n\n"
        f"Carry on with `from-pj-wrap-up`, or after the line `{RETIRED_HANDOVER_LINE}`,"
        " or in `check`.\n"
        'Otherwise say "Handing over to /pj:wrap-up; it runs these steps at its project step."\n'
        "Then Read `~/.claude/pj/skills/wrap-up/SKILL.md` and follow it.\n"
    )
    problems = _handover_problems(old)
    assert any("/session-end" in problem for problem in problems)
    assert any("still reads /pj:wrap-up" in problem for problem in problems)
    assert any("still hands over to /pj:wrap-up" in problem for problem in problems)
    assert any("handover line" in problem for problem in problems)
    assert any("title still names" in problem for problem in problems)


RETIRED_CALLER = (
    "started by /pj:wrap-up",
    "/pj:wrap-up marks the session",
    "/pj:wrap-up step 4 may have filed it",
    "from /pj:wrap-up, or `check` direct",
    "When /pj:wrap-up started this run",
)


def _caller_problems(text: str) -> list[str]:
    """Why the command still names /pj:wrap-up as its caller; empty when it names /session-end.

    Engage #3436. Whitespace is folded first, so a phrase broken across lines still counts.
    Step 0 must count /session-end and look for the captain's log entry, not pj's mark.
    """
    flat = " ".join(text.split())
    problems = [f"still says: {phrase}" for phrase in RETIRED_CALLER if phrase in flat]
    step0 = next((step for step in _steps(text) if step.startswith("Step 0 ")), "")
    if "session-end" not in step0:
        problems.append("Step 0 does not count /session-end")
    if "captains-log" not in step0:
        problems.append("Step 0 does not look for the captain's log entry")
    if ".local/state/pj/wrapped" in step0:
        problems.append("Step 0 still reads pj's wrapped mark")
    return problems


def test_the_command_names_session_end_as_its_caller() -> None:
    assert _caller_problems(COMMAND.read_text(encoding="utf-8")) == []


def test_the_caller_check_rejects_the_pj_wrap_up_wording() -> None:
    """Control: the 2026-10-19 wording, before engage #3436."""
    old = (
        "`from-pj-wrap-up <handoff lines>` = mode `all`, started\nby /pj:wrap-up (Step H).\n"
        "## Step 0 - did the last session actually close out?\n\n"
        "Since 2026-09-29 a session closes with `/pj:wrap-up`, so count both:\n"
        '[ -e "$HOME/.local/state/pj/wrapped/$id" ]\n'
        "## Step 9 - report\n\nWhen /pj:wrap-up started this run, the report goes back to it.\n"
    )
    problems = _caller_problems(old)
    assert any("started by /pj:wrap-up" in problem for problem in problems)
    assert any("When /pj:wrap-up started" in problem for problem in problems)
    assert any("count /session-end" in problem for problem in problems)
    assert any("captain's log entry" in problem for problem in problems)
    assert any("wrapped mark" in problem for problem in problems)


def test_the_session_id_is_read_under_both_names() -> None:
    assert _session_id_problems(COMMAND.read_text(encoding="utf-8")) == []


def test_the_session_id_check_rejects_a_bare_name() -> None:
    """Control: the 2026-10-04 Step 0 line, which skipped every file in engage."""
    old = 'case "$f" in *"$CLAUDE_SESSION_ID"*) continue;; esac'
    assert _session_id_problems(old) != []
    assert _session_id_problems(f'case "$f" in *"{SESSION_ID}"*) continue;; esac') == []


def test_loose_ends_go_to_engage_not_memory() -> None:
    """Memory is frozen under engage (D-20260929-A01); the queue is engage's to-dos."""
    text = COMMAND.read_text(encoding="utf-8")
    assert "engage-go add" in text
    assert "open-items" not in text
    assert "MemoryCuration" not in text
    assert "a memory file if it's a fact" not in text


def _step5_problems(text: str) -> list[str]:
    """Why Step 5 does not treat the captain's log as the one handoff; empty when it does."""
    step5 = next((step for step in _steps(text) if step.startswith("Step 5 ")), "")
    problems: list[str] = []
    if "captain's log entry" not in step5:
        problems.append("Step 5 does not name the captain's log entry as the handoff")
    if "engage-go handoff" not in step5:
        problems.append("Step 5 does not say how to read the handoff")
    for retired, why in (
        ("<!-- generated by /pj:wrap-up -->", "Step 5 still keeps the generated marker"),
        ("pj-homes", "Step 5 still names a handoff in .claude/pj-homes"),
        ('"Next: see `HANDOFF.md`"', "Step 5 still points the session log at HANDOFF.md"),
        ("wc -l OPENING-PROMPT.md HANDOFF.md", "Step 5 still measures HANDOFF.md"),
    ):
        if retired in step5:
            problems.append(why)
    return problems


def test_step5_makes_the_captains_log_the_one_handoff() -> None:
    assert _step5_problems(COMMAND.read_text(encoding="utf-8")) == []


def test_the_step5_check_rejects_the_pj_wrap_up_handoff_step() -> None:
    """Control: the 2026-10-17 Step 5, which kept HANDOFF.md as the live snapshot."""
    old = (
        "## Step 5 - the handoff, the session log, and anything with no home\n\n"
        "| `HANDOFF.md` | the live snapshot | /pj:wrap-up (named by `.claude/pj-homes`) |\n"
        "keep the first line exactly `<!-- generated by /pj:wrap-up -->`.\n"
        'lines: write "Next: see `HANDOFF.md`" instead.\n'
        "wc -l OPENING-PROMPT.md HANDOFF.md\n"
    )
    problems = _step5_problems(old)
    assert any("captain's log entry" in problem for problem in problems)
    assert any("generated marker" in problem for problem in problems)
    assert any("pj-homes" in problem for problem in problems)
    assert any("points the session log" in problem for problem in problems)
    assert any("measures HANDOFF.md" in problem for problem in problems)


def test_pj_homes_names_this_command_and_no_handoff() -> None:
    homes = {
        key.strip(): value.strip()
        for key, value in (
            line.split(":", 1)
            for line in PJ_HOMES.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        )
    }
    assert homes["wrap-up"] == "/wrap-up"
    assert "handoff" not in homes


def test_handoff_md_is_frozen_without_the_generated_marker() -> None:
    """With the marker, an old /pj:wrap-up would treat the file as its own and rewrite it."""
    text = HANDOFF.read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("<!-- frozen 2026-10-19")
    assert "<!-- generated by /pj:wrap-up -->" not in text
    assert "This is NOT the handoff" in text
