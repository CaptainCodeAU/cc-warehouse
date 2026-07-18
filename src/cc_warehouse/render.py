"""The 4-file projection emitters (slices 6-7). DESIGN section 6; SPEC sections 6-7.

One parser-produced conversation model (parser.build_conversation) feeds every
emitter. A single policy-parameterized core walks that model, so the full and
compact markdown variants are one implementation, not two near-verbatim copies
(F8/R9). The emitters take the raw payload so tests stay black-box.
"""

import json
import re
from dataclasses import dataclass
from typing import cast

from cc_warehouse.parser import (
    Block,
    Conversation,
    ParsedSession,
    Turn,
    build_conversation,
    detect_commits,
    detect_github_repo,
    parse_session,
    split_reminder,
)


@dataclass(frozen=True)
class RenderOptions:
    reminders_full: str = "collapse"  # collapse | strip | show (personal override only)
    reminders_compact: str = "strip"
    breadcrumbs: bool = False


@dataclass(frozen=True)
class _Policy:
    """What a variant emits. Full and compact differ only by this policy."""

    include_thinking: bool
    include_tools: bool
    include_machinery: bool
    reminder_mode: str  # collapse | strip | show
    variant_note: str | None
    breadcrumbs: bool
    header_details: bool


# Compact variant note. The word "compact" is load-bearing (oracle test
# test_compact_carries_a_variant_note).
_COMPACT_NOTE = "> Compact variant: conversation only, no thinking, tools, or reminders."

_LIST_MARKER = re.compile(r"^\s*([-*+] |\d+[.)] )")


# --------------------------------------------------------------------------
# In-house markdown hardening (SPEC section 7). Scope: the markdown WE emit.
# Shared by both variants (and reused by the HTML emitter in slice 7).
# --------------------------------------------------------------------------


def _fence_marker(line: str) -> tuple[str, int, str] | None:
    """Parse a code-fence marker line.

    Returns (char, run_length, info) where char is a backtick or a tilde,
    run_length is the count of leading fence characters (at least 3), and info
    is any trailing text after the run (empty for a bare marker). Returns None
    when the line is not a fence marker.
    """
    stripped = line.strip()
    if not stripped:
        return None
    char = stripped[0]
    if char not in ("`", "~"):
        return None
    run = len(stripped) - len(stripped.lstrip(char))
    if run < 3:
        return None
    return char, run, stripped[run:]


def _fence(content: str, info: str = "") -> list[str]:
    """Fence arbitrary/untrusted content safely (SPEC 7 hardening).

    Opens and closes with a run of backticks one longer than the longest
    backtick run inside `content` (minimum three), so content that itself
    contains a ``` line cannot break out of the block. Returns the fenced lines.
    """
    longest = 0
    current = 0
    for char in content:
        if char == "`":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    ticks = "`" * max(3, longest + 1)
    return [f"{ticks}{info}", content, ticks]


def _strip_trailing_orphan_fence(text: str) -> str:
    """SPEC 7 hardening: drop a dangling code fence that opens a block never
    closed, so a fragment does not leave an unbalanced ``` behind.

    Fence-aware: the opener's marker (char + run length) is tracked, so a bare
    marker only closes the block when it is the same char and at least as long.
    A balanced block that itself wraps a shorter fence line is left intact; only
    a fence still open at end-of-text is stripped.
    """
    lines = text.split("\n")
    open_marker: tuple[str, int] | None = None
    open_index = -1
    for i, line in enumerate(lines):
        marker = _fence_marker(line)
        if marker is None:
            continue
        char, run, info = marker
        if open_marker is None:
            open_marker = (char, run)
            open_index = i
        elif char == open_marker[0] and run >= open_marker[1] and not info:
            open_marker = None
            open_index = -1
    if open_marker is not None:
        del lines[open_index]
    return "\n".join(lines).rstrip()


def _blank_before_loose_lists(text: str) -> str:
    """SPEC 7 hardening: a list starting on the line right after a paragraph line
    needs a blank line before it or CommonMark folds it into the paragraph.
    Fence-aware: nothing inside a code fence is transformed."""
    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence and _LIST_MARKER.match(line) and out:
            previous = out[-1]
            if previous.strip() and _LIST_MARKER.match(previous) is None:
                out.append("")
        out.append(line)
    return "\n".join(out)


def _harden(text: str) -> str:
    return _blank_before_loose_lists(_strip_trailing_orphan_fence(text))


# --------------------------------------------------------------------------
# Typed block rendering (SPEC section 7 tool-specific semantics).
# --------------------------------------------------------------------------


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _render_todos(todos: object) -> list[str] | None:
    """A TodoWrite `todos` array as a markdown task list: `- [x]` completed,
    `- [~]` in progress, `- [ ]` pending. Returns None for a non-list or
    otherwise malformed value so the caller falls back to the generic JSON dump."""
    if not isinstance(todos, list):
        return None
    lines: list[str] = []
    for raw in cast(list[object], todos):
        if not isinstance(raw, dict):
            return None
        item = cast(dict[str, object], raw)
        content = _as_str(item.get("content"))
        status = item.get("status")
        if status == "completed":
            lines.append(f"- [x] {content}")
        elif status == "in_progress":
            lines.append(f"- [~] {content}")
        else:
            lines.append(f"- [ ] {content}")
    return lines


def _render_tool_use(block: Block) -> list[str]:
    name = block.tool_name or "tool"
    tool_input = block.tool_input or {}
    if name == "Bash":
        command = _as_str(tool_input.get("command"))
        description = _as_str(tool_input.get("description"))
        head = f"**Bash** ({description})" if description else "**Bash**"
        return [head, "", *_fence(command, "bash")]
    if name == "Write":
        path = _as_str(tool_input.get("file_path"))
        return [f"**Write** `{path}`", "", *_fence(_as_str(tool_input.get("content")))]
    if name == "Edit":
        path = _as_str(tool_input.get("file_path"))
        old = _as_str(tool_input.get("old_string"))
        new = _as_str(tool_input.get("new_string"))
        note = " (replace all)" if tool_input.get("replace_all") is True else ""
        diff = [f"-{line}" for line in old.split("\n")]
        diff += [f"+{line}" for line in new.split("\n")]
        return [f"**Edit** `{path}`{note}", "", *_fence("\n".join(diff), "diff")]
    if name == "TodoWrite":
        todos = _render_todos(tool_input.get("todos"))
        if todos is not None:
            return ["**TodoWrite**", "", *todos]
    payload = json.dumps(dict(tool_input), indent=2, sort_keys=True, ensure_ascii=False)
    return [f"**{name}**", "", *_fence(payload, "json")]


def _render_tool_result(block: Block) -> list[str]:
    text = block.text
    body: list[str] = [
        f"- commit `{commit.sha}`: {commit.message}" for commit in detect_commits(text)
    ]
    repo = detect_github_repo(text)
    if repo is not None:
        body.append(f"- repo: {repo}")
    # Always keep the raw result text too (safe-fenced), in addition to any
    # commit/repo cards, so detection never drops the rest of the result (F6).
    body.extend(_fence(text))
    return ["**Result:**", "", *body]


def _render_reminder(reminder: str, mode: str) -> list[str]:
    if mode == "show":
        return ["", f"> system-reminder: {reminder}"]
    if mode == "collapse":
        return [
            "",
            "<details>",
            "<summary>system-reminder</summary>",
            "",
            *_fence(reminder),
            "",
            "</details>",
        ]
    # Any other value (strip, or an unknown/typo like "hide" or "") fails
    # CLOSED: the reminder is never leaked into the output (F7).
    return []


def _render_machinery(block: Block) -> list[str]:
    if block.kind == "continuation":
        return [
            "",
            "<details>",
            "<summary>continued conversation</summary>",
            "",
            block.text,
            "",
            "</details>",
        ]
    labels = {
        "task_notification": "task-notification",
        "stop_hook": "stop-hook",
        "reminder": "system-reminder",
        "machinery": "machinery",
    }
    return ["", f"> [{labels.get(block.kind, block.kind)}] {block.text}"]


def _render_block(block: Block, policy: _Policy) -> list[str]:
    kind = block.kind
    if kind == "assistant_text":
        return ["", _harden(block.text)]
    if kind == "thinking":
        return ["", *_fence(block.text, "md")] if policy.include_thinking else []
    if kind == "tool_use":
        return ["", *_render_tool_use(block)] if policy.include_tools else []
    if kind == "tool_result":
        return ["", *_render_tool_result(block)] if policy.include_tools else []
    if not policy.include_machinery:
        return []
    return _render_machinery(block)


# --------------------------------------------------------------------------
# The single core: header card, then `***`-separated turns.
# --------------------------------------------------------------------------


def _title(meta: ParsedSession) -> str:
    if meta.slug:
        return meta.slug
    visible, _ = split_reminder(meta.summary)
    visible = visible.strip()
    if visible and visible != "(no summary)":
        return visible.split("\n")[0]
    return "session"


def _header(meta: ParsedSession, policy: _Policy) -> list[str]:
    suffix = " (compact)" if policy.variant_note else ""
    lines = [f"# Transcript{suffix}: {_title(meta)}", ""]
    if policy.variant_note:
        lines.extend([policy.variant_note, ""])
    if policy.header_details:
        detail = ["<details>", "<summary>Session details</summary>", ""]
        if meta.slug:
            detail.append(f"- slug: {meta.slug}")
        if meta.git_branch:
            detail.append(f"- branch: {meta.git_branch}")
        if meta.session_uuid:
            detail.append(f"- session: {meta.session_uuid}")
        if meta.first_ts:
            detail.append(f"- first entry: {meta.first_ts}")
        if meta.last_ts:
            detail.append(f"- last entry: {meta.last_ts}")
        detail.extend(["", "</details>", ""])
        lines.extend(detail)
    return lines


def _render_turn(turn: Turn, total: int, policy: _Policy) -> list[str]:
    if turn.synthetic and not policy.include_machinery:
        return []
    lines = ["***", ""]
    if turn.synthetic:
        lines.append("## Pre-conversation entries")
    else:
        lines.append(f"## Turn {turn.ordinal}")
        if policy.breadcrumbs:
            lines.append(f"> breadcrumb: turn {turn.ordinal} of {total}")
    lines.append("")
    if turn.prompt:
        lines.append(_harden(turn.prompt))
    for reminder in turn.reminders:
        lines.extend(_render_reminder(reminder, policy.reminder_mode))
    for block in turn.blocks:
        lines.extend(_render_block(block, policy))
    lines.append("")
    return lines


def _render(conv: Conversation, meta: ParsedSession, policy: _Policy) -> str:
    lines = _header(meta, policy)
    for turn in conv.turns:
        lines.extend(_render_turn(turn, conv.prompt_count, policy))
    return "\n".join(lines).rstrip() + "\n"


def _full_policy(options: RenderOptions) -> _Policy:
    return _Policy(
        include_thinking=True,
        include_tools=True,
        include_machinery=True,
        reminder_mode=options.reminders_full,
        variant_note=None,
        breadcrumbs=False,
        header_details=True,
    )


def _compact_policy(options: RenderOptions) -> _Policy:
    return _Policy(
        include_thinking=False,
        include_tools=False,
        include_machinery=False,
        reminder_mode=options.reminders_compact,
        variant_note=_COMPACT_NOTE,
        breadcrumbs=options.breadcrumbs,
        header_details=False,
    )


def render_markdown(data: bytes, options: RenderOptions) -> tuple[str, str]:
    """Return (transcript.md full, transcript.compact.md).

    Both variants are produced by one policy-parameterized core over the shared
    conversation model (parser.build_conversation): the full variant keeps
    thinking, typed tool rows, machinery, and folded system-reminders; the
    compact variant is conversation only. Output is deterministic -- it derives
    from payload internals, never file mtimes (R12).
    """
    conv = build_conversation(data)
    meta = parse_session(data)
    full = _render(conv, meta, _full_policy(options))
    compact = _render(conv, meta, _compact_policy(options))
    return full, compact


def render_html(data: bytes, options: RenderOptions) -> tuple[str, str]:
    """Return (conversation.html, conversation.compact.html) contents."""
    raise NotImplementedError


def build_manifest(data: bytes, options: RenderOptions) -> dict[str, object]:
    """Per-session render manifest: config used, counts, loss telemetry, source hash."""
    raise NotImplementedError
