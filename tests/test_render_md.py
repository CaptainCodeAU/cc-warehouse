"""Oracle tests: transcript.md + transcript.compact.md emitters (slice 6).

Contract: DESIGN section 6 (4-file model, fixed policies), SPEC section 7
(KEEP semantics), BRAINSTORM render lock (exporter v8.10.1 reference).
"""

from cc_warehouse.render import RenderOptions
from cc_warehouse.render import render_markdown as _render_markdown_bytes
from conftest import rich_session

REMINDER = "secret internal reminder text"


def render_markdown(data: bytes, options: RenderOptions) -> tuple[str, str]:
    """render_markdown returns UTF-8 bytes (ticket 28.9, Fix A); decode once
    here so every test in this file keeps comparing plain text."""
    full, compact = _render_markdown_bytes(data, options)
    return full.decode("utf-8"), compact.decode("utf-8")


def render_pair() -> tuple[str, str]:
    return render_markdown(rich_session(), RenderOptions())


def test_full_transcript_has_separators_and_both_prompts() -> None:
    """Quick-Look-safe `***` separators; conversation content in order."""
    full, _ = render_pair()
    assert "***" in full
    first = full.find("First real prompt about widgets")
    second = full.find("Second real prompt: now document it")
    assert 0 <= first < second


def test_thinking_rendered_in_md_fences_full_only() -> None:
    """Thinking ON in full variants inside ```md fences; compact is
    conversation-only."""
    full, compact = render_pair()
    assert "deep thoughts about widgets" in full
    assert "```md" in full
    assert "deep thoughts about widgets" not in compact


def test_tool_calls_full_only() -> None:
    full, compact = render_pair()
    assert "git commit -m widget" in full
    assert "git commit -m widget" not in compact


def test_reminders_collapsed_in_full_stripped_in_compact() -> None:
    """DESIGN section 6 fixed policy: system-reminder blocks are collapsed in
    full variants and stripped from compact variants."""
    full, compact = render_pair()
    assert REMINDER in full
    assert "<details>" in full
    assert REMINDER not in compact


def test_reminder_policy_is_config_overridable_for_personal_renders() -> None:
    _, compact = render_markdown(
        rich_session(), RenderOptions(reminders_compact="show")
    )
    assert REMINDER in compact


def test_compact_carries_a_variant_note() -> None:
    _, compact = render_pair()
    assert "compact" in compact.lower()


def test_task_notification_never_appears_in_compact_conversation() -> None:
    """SPEC 6 KEEP: task notifications are machinery, not conversation."""
    _, compact = render_pair()
    assert "background task finished" not in compact


def test_breadcrumbs_option_changes_compact_output() -> None:
    """BRAINSTORM: optional breadcrumbs in compact, config-driven, default off."""
    _, plain = render_markdown(rich_session(), RenderOptions())
    _, with_crumbs = render_markdown(rich_session(), RenderOptions(breadcrumbs=True))
    assert plain != with_crumbs
