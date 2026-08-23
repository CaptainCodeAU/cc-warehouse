"""Contract-derived regression tests for the transcript.md emitters (slice 6,
post-review). NOT the frozen oracle suite (tests/test_render_md.py); these are the
operator-written regressions the HARNESS precedent calls for, pinning the reviewer
clusters the oracle did not cover. Cited in harness/tickets/06-render-markdown.md.

- RT-TURN: a real prompt is not demoted to machinery (a `<`-prefixed prompt, or a
  prompt that merely mentions <task-notification>, still starts a turn). [C-TURN]
- RT-FENCE: the md hardening does not corrupt a balanced nested-backtick block, and
  arbitrary content containing a code fence is wrapped in a safe (longer) fence. [C-FENCE]
- RT-REMINDER: an unknown reminder mode fails CLOSED (never leaks the reminder). [C-REMINDER-LEAK]
- RT-TOOLRESULT: a commit-bearing tool_result keeps its other text too. [C-TOOLRESULT-LOSS]
- RT-DETERMINISM / RT-PRESERVE: render is deterministic; pre-first-prompt content is
  preserved in full (proving the R8 guarantee words). [C-R8]
- RT-TOOLCOVERAGE: TodoWrite renders as a markdown task list. [C-TOOLCOVERAGE]
"""

import json
from collections.abc import Mapping

from cc_warehouse.parser import build_conversation
from cc_warehouse.render import RenderOptions
from cc_warehouse.render import render_markdown as _render_markdown_bytes


def render_markdown(data: bytes, options: RenderOptions) -> tuple[str, str]:
    """render_markdown returns UTF-8 bytes (ticket 28.9, Fix A); decode once
    here so every test in this file keeps comparing plain text."""
    full, compact = _render_markdown_bytes(data, options)
    return full.decode("utf-8"), compact.decode("utf-8")


def payload(*entries: Mapping[str, object]) -> bytes:
    return b"".join(json.dumps(dict(e)).encode() + b"\n" for e in entries)


def user(text: str) -> dict[str, object]:
    return {"type": "user", "message": {"role": "user", "content": text}}


def assistant(content: object) -> dict[str, object]:
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


def tool_result(text: str) -> dict[str, object]:
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "content": text}]},
    }


def test_angle_prefixed_prompt_starts_a_turn() -> None:
    """C-TURN: a legitimate prompt beginning with '<' is a conversation starter,
    not machinery (SPEC-6 grouping is NOT the SPEC-8 summary heuristic)."""
    data = payload(
        user("<div> will not render, help"),
        assistant([{"type": "text", "text": "try flex"}]),
    )
    conv = build_conversation(data)
    assert conv.prompt_count == 1
    _, compact = render_markdown(data, RenderOptions())
    assert "will not render" in compact
    assert "try flex" in compact


def test_task_notification_mention_does_not_eat_the_prompt() -> None:
    """C-TURN: a real prompt that merely MENTIONS the tag is not demoted whole to a
    task-notification machinery block."""
    data = payload(user("Why do we get <task-notification>ping</task-notification> spam here?"))
    conv = build_conversation(data)
    assert conv.prompt_count == 1


def test_pure_task_notification_is_still_machinery() -> None:
    """C-TURN: a whole-message task-notification is still machinery, kept out of the
    compact conversation (SPEC-6 KEEP)."""
    data = payload(user("<task-notification>background task finished</task-notification>"))
    conv = build_conversation(data)
    assert conv.prompt_count == 0
    _, compact = render_markdown(data, RenderOptions())
    assert "background task finished" not in compact


def test_hardening_keeps_a_balanced_nested_fence() -> None:
    """C-FENCE: a balanced 4-backtick block wrapping a literal 3-backtick line must
    survive md hardening (the trailing-orphan strip must not delete a real fence)."""
    data = payload(user("example:\n````\n```\n````"))
    full, _ = render_markdown(data, RenderOptions())
    assert full.count("````") >= 2


def test_tool_result_with_a_code_fence_uses_a_safe_fence() -> None:
    """C-FENCE: arbitrary tool output containing ``` must be wrapped in a longer fence
    so its content cannot break out of the code block."""
    data = payload(
        user("show me"),
        assistant(
            [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "x"}}]
        ),
        tool_result("see the file:\n```\ncode here\n```\ndone"),
    )
    full, _ = render_markdown(data, RenderOptions())
    assert "code here" in full
    assert "````" in full


def test_unknown_reminder_mode_never_leaks() -> None:
    """C-REMINDER-LEAK (F7): an unrecognized reminder mode fails CLOSED; a typo in the
    config must never leak a system-reminder into the output."""
    data = payload(user("real prompt <system-reminder>TOP SECRET</system-reminder>"))
    _, compact = render_markdown(data, RenderOptions(reminders_compact="hide"))
    assert "TOP SECRET" not in compact


def test_commit_tool_result_keeps_its_other_text() -> None:
    """C-TOOLRESULT-LOSS (F6): a commit-bearing tool_result shows the commit card AND
    the rest of its text; it does not drop the remainder."""
    data = payload(
        user("do it"),
        assistant(
            [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "git commit"}}]
        ),
        tool_result("[main abc1234] add widget frobnicator\n 1 file changed"),
    )
    full, _ = render_markdown(data, RenderOptions())
    assert "abc1234" in full
    assert "1 file changed" in full


def test_render_is_deterministic() -> None:
    """C-R8: rendering the same payload twice yields identical output (proves the
    'deterministic' docstring word)."""
    data = payload(
        user("first prompt"),
        assistant([{"type": "text", "text": "reply one"}]),
        user("second prompt"),
    )
    assert render_markdown(data, RenderOptions()) == render_markdown(data, RenderOptions())


def test_pre_conversation_content_is_preserved_in_full() -> None:
    """C-R8 / F6: content before the first user prompt is not silently dropped from the
    full transcript (proves the 'never silently dropped' claim for this class)."""
    data = payload(
        assistant([{"type": "text", "text": "an early note before any prompt"}]),
        user("hi"),
    )
    full, _ = render_markdown(data, RenderOptions())
    assert "an early note before any prompt" in full


def test_todowrite_renders_as_a_task_list() -> None:
    """C-TOOLCOVERAGE (SPEC 7): TodoWrite serializes to a markdown task list, not a raw
    JSON dump (the copy-as-md payloads slice 7 depends on)."""
    data = payload(
        user("track it"),
        assistant(
            [
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "TodoWrite",
                    "input": {
                        "todos": [
                            {"content": "write the parser", "status": "completed"},
                            {"content": "write the emitter", "status": "in_progress"},
                        ]
                    },
                }
            ]
        ),
    )
    full, _ = render_markdown(data, RenderOptions())
    assert "write the parser" in full
    assert "- [" in full
