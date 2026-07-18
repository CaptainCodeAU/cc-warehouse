"""The 4-file projection emitters (slices 6-7). DESIGN section 6; SPEC sections 6-7.

One parser-produced conversation model (parser.build_conversation) feeds every
emitter. A single policy-parameterized core walks that model, so the full and
compact markdown variants are one implementation, not two near-verbatim copies
(F8/R9). The emitters take the raw payload so tests stay black-box.
"""

import base64
import json
import re
from dataclasses import asdict, dataclass
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
from cc_warehouse.store import sha256_hex


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


# --------------------------------------------------------------------------
# In-house markdown -> HTML (slice 7). Scope: the markdown WE emit plus the
# SPEC-7 hardening; stdlib only (R7), no third-party renderer. User TEXT is
# escaped; our own block-level HTML (<details>/<summary>) passes through.
# --------------------------------------------------------------------------

_MD_HEADING_RE = re.compile(r"^(#{1,6}) +(.*)$")
_MD_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)]) +(.*)$")
# Only the block-level HTML we emit ourselves passes through unescaped.
_MD_PASSTHROUGH_RE = re.compile(r"^(?:<details>|</details>|<summary>[^<]*</summary>)$")
_MD_INLINE_RE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<link>\[[^\]\n]+\]\([^)\n]+\))"
    r"|(?P<bold>\*\*.+?\*\*)"
)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_attr(text: str) -> str:
    return _escape(text).replace('"', "&quot;")


def _inline(text: str) -> str:
    """Inline markdown: bold, inline code, and links; all other text escaped."""
    out: list[str] = []
    pos = 0
    for match in _MD_INLINE_RE.finditer(text):
        out.append(_escape(text[pos : match.start()]))
        code = match.group("code")
        link = match.group("link")
        if code is not None:
            out.append(f"<code>{_escape(code[1:-1])}</code>")
        elif link is not None:
            label, _, tail = link[1:].partition("](")
            out.append(f'<a href="{_escape_attr(tail[:-1])}">{_escape(label)}</a>')
        else:
            bold = match.group("bold") or ""
            out.append(f"<strong>{_escape(bold[2:-2])}</strong>")
        pos = match.end()
    out.append(_escape(text[pos:]))
    return "".join(out)


def _paragraph_html(lines: list[str]) -> str:
    return f"<p>{_inline(chr(10).join(lines))}</p>"


def _list_html(items: list[str]) -> str:
    body = "".join(f"<li>{_inline(item)}</li>" for item in items)
    return f"<ul>{body}</ul>"


def _code_block_html(lines: list[str], lang: str) -> str:
    opener = f'<code class="language-{lang}">' if lang else "<code>"
    return f"<pre>{opener}{_escape(chr(10).join(lines))}</code></pre>"


def _md_to_html(md: str, allow_block_html: bool) -> str:
    """Render the markdown WE emit to HTML.

    Headings, paragraphs, loose lists, balanced code fences, and inline
    bold/code/links. Block-level <details>/<summary> lines pass through
    literally ONLY when allow_block_html is True (fragments WE authored: the
    header card, the reminder collapse, continuation blocks); with it False --
    USER prompt text and every other block -- such a line is ordinary text
    whose angle brackets are escaped, so user content can never inject page
    markup. A fence still open at end-of-input is closed defensively, so a
    page can never carry an unbalanced <pre> (SPEC 7 hardening;
    test_trailing_orphan_fence_is_stripped).
    """
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []
    fence: list[str] | None = None
    fence_open = ("", 0)
    fence_lang = ""

    def flush() -> None:
        if para:
            out.append(_paragraph_html(para))
            para.clear()
        if items:
            out.append(_list_html(items))
            items.clear()

    for line in md.split("\n"):
        if fence is not None:
            marker = _fence_marker(line)
            if (
                marker is not None
                and marker[0] == fence_open[0]
                and marker[1] >= fence_open[1]
                and not marker[2]
            ):
                out.append(_code_block_html(fence, fence_lang))
                fence = None
            else:
                fence.append(line)
            continue

        marker = _fence_marker(line)
        if marker is not None:
            flush()
            fence = []
            fence_open = (marker[0], marker[1])
            fence_lang = re.sub(r"[^A-Za-z0-9_-]", "", marker[2])
            continue

        if allow_block_html and _MD_PASSTHROUGH_RE.match(line):
            flush()
            out.append(line)
            continue

        heading = _MD_HEADING_RE.match(line)
        if heading is not None:
            flush()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue

        item = _MD_LIST_ITEM_RE.match(line)
        if item is not None:
            if para:
                out.append(_paragraph_html(para))
                para.clear()
            items.append(item.group(1))
            continue

        if not line.strip():
            flush()
            continue

        if items:
            out.append(_list_html(items))
            items.clear()
        para.append(line)

    if fence is not None:
        out.append(_code_block_html(fence, fence_lang))
    flush()
    return "\n".join(out)


# --------------------------------------------------------------------------
# HTML page emitter (slice 7). Per-block markdown fragments are the SINGLE
# source of truth: render_markdown joins them, render_html wraps each in a
# data-copy-src that carries the RAW markdown (base64) beside the rendered
# body, so a copied fragment reproduces its transcript.md source verbatim
# (DESIGN section 6; proven by test_copy_as_markdown_payloads_equal_transcript_fragments).
# --------------------------------------------------------------------------

_HLJS_BASE = "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0"
_HLJS_SCRIPT = (
    f'<script src="{_HLJS_BASE}/highlight.min.js" '
    'onload="hljs.highlightAll()" onerror="void 0"></script>'
)
# Double-click a block to copy its exact transcript.md markdown from the
# base64 data-copy-src payload. Best-effort; the page renders without it.
_COPY_SCRIPT = (
    "<script>\n"
    "(function () {\n"
    "  function decode(value) {\n"
    "    var binary = atob(value);\n"
    "    var bytes = new Uint8Array(binary.length);\n"
    "    for (var i = 0; i < binary.length; i += 1) {\n"
    "      bytes[i] = binary.charCodeAt(i);\n"
    "    }\n"
    '    return new TextDecoder("utf-8").decode(bytes);\n'
    "  }\n"
    '  document.addEventListener("dblclick", function (event) {\n'
    '    var node = event.target.closest("[data-copy-src]");\n'
    "    if (!node || !navigator.clipboard) {\n"
    "      return;\n"
    "    }\n"
    '    navigator.clipboard.writeText(decode(node.getAttribute("data-copy-src")));\n'
    "  });\n"
    "})();\n"
    "</script>"
)
_CSS = (
    ":root { color-scheme: light dark; }\n"
    "body { font: 16px/1.55 -apple-system, system-ui, sans-serif; margin: 0; }\n"
    "main.transcript { max-width: 52rem; margin: 0 auto; padding: 2rem 1rem; }\n"
    "section.turn { border-top: 1px solid rgba(128, 128, 128, 0.3); "
    "margin-top: 1.5rem; padding-top: 0.5rem; }\n"
    "h1, h2 { line-height: 1.2; }\n"
    "pre { overflow-x: auto; padding: 0.75rem; border-radius: 6px; "
    "background: rgba(128, 128, 128, 0.12); }\n"
    "p code, li code { padding: 0.1em 0.3em; border-radius: 4px; "
    "background: rgba(128, 128, 128, 0.15); }\n"
    "[data-copy-src] { cursor: copy; }\n"
    "summary { cursor: pointer; }\n"
    "a { color: #2563eb; }\n"
)


class _AnchorAllocator:
    """Content-derived, collision-free anchor ids (DESIGN section 6).

    An id is the turn ordinal plus a short hash of the block content; a numeric
    suffix disambiguates the rare content collision. Never derived from a
    timestamp, so entries that share a timestamp still get distinct anchors
    (test_message_anchors_are_unique_despite_equal_timestamps).
    """

    def __init__(self) -> None:
        self._used: set[str] = set()

    def allocate(self, ordinal: int, content: str) -> str:
        digest = sha256_hex(content.encode("utf-8"))[:8]
        base = f"turn-{ordinal}-{digest}"
        anchor = base
        suffix = 2
        while anchor in self._used:
            anchor = f"{base}-{suffix}"
            suffix += 1
        self._used.add(anchor)
        return anchor


def _document_head(title: str) -> list[str]:
    return [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_escape(title)}</title>",
        f"<style>\n{_CSS}</style>",
        "</head>",
        "<body>",
    ]


def _strip_separators(lines: list[str]) -> list[str]:
    """Drop the structural blank lines bracketing a block so the copy payload is
    the block's own markdown, still a verbatim substring of transcript.md."""
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _copy_block(
    anchors: _AnchorAllocator, ordinal: int, css: str, fragment: str, body: str
) -> str:
    anchor = anchors.allocate(ordinal, fragment)
    payload = base64.b64encode(fragment.encode("utf-8")).decode("ascii")
    return f'<div class="{css}" id="{anchor}" data-copy-src="{payload}">{body}</div>'


def _session_repo(conv: Conversation) -> str | None:
    """The GitHub owner/repo detected anywhere in the session's tool results;
    commit shas in any result link against it (SPEC 7 commit cards)."""
    for turn in conv.turns:
        for block in turn.blocks:
            if block.kind == "tool_result":
                repo = detect_github_repo(block.text)
                if repo is not None:
                    return repo
    return None


def _linkify_commits(body: str, text: str, repo: str) -> str:
    """Anchor each commit sha in a rendered result to its GitHub commit URL. The
    data-copy-src fragment stays the plain markdown; only the body gains links."""
    for commit in detect_commits(text):
        needle = f"<code>{_escape(commit.sha)}</code>"
        href = _escape_attr(f"https://github.com/{repo}/commit/{commit.sha}")
        body = body.replace(needle, f'<a href="{href}">{needle}</a>', 1)
    return body


def _block_html(
    block: Block, policy: _Policy, repo: str | None, ordinal: int, anchors: _AnchorAllocator
) -> str | None:
    lines = _strip_separators(_render_block(block, policy))
    if not lines:
        return None
    fragment = "\n".join(lines)
    body = _md_to_html(fragment, allow_block_html=block.kind == "continuation")
    if block.kind == "tool_result":
        result_repo = detect_github_repo(block.text) or repo
        if result_repo is not None:
            body = _linkify_commits(body, block.text, result_repo)
    return _copy_block(anchors, ordinal, f"block block-{block.kind}", fragment, body)


def _turn_html(
    turn: Turn, policy: _Policy, repo: str | None, anchors: _AnchorAllocator
) -> list[str]:
    if turn.synthetic and not policy.include_machinery:
        return []
    section_id = anchors.allocate(turn.ordinal, f"turn:{turn.ordinal}:{turn.prompt}")
    heading = "Pre-conversation entries" if turn.synthetic else f"Turn {turn.ordinal}"
    out = [f'<section class="turn" id="{section_id}">', f"<h2>{_escape(heading)}</h2>"]
    if turn.prompt:
        fragment = _harden(turn.prompt)
        body = _md_to_html(fragment, allow_block_html=False)
        out.append(_copy_block(anchors, turn.ordinal, "prompt", fragment, body))
    for reminder in turn.reminders:
        lines = _strip_separators(_render_reminder(reminder, policy.reminder_mode))
        if lines:
            fragment = "\n".join(lines)
            body = _md_to_html(fragment, allow_block_html=True)
            out.append(_copy_block(anchors, turn.ordinal, "reminder", fragment, body))
    for block in turn.blocks:
        block_html = _block_html(block, policy, repo, turn.ordinal, anchors)
        if block_html is not None:
            out.append(block_html)
    out.append("</section>")
    return out


def _render_page(
    conv: Conversation, meta: ParsedSession, policy: _Policy, repo: str | None
) -> str:
    anchors = _AnchorAllocator()
    parts = _document_head(_title(meta))
    parts.append('<main class="transcript">')
    parts.append(_md_to_html("\n".join(_header(meta, policy)), allow_block_html=True))
    for turn in conv.turns:
        parts.extend(_turn_html(turn, policy, repo, anchors))
    parts.extend(["</main>", _HLJS_SCRIPT, _COPY_SCRIPT, "</body>", "</html>"])
    return "\n".join(parts) + "\n"


def render_html(data: bytes, options: RenderOptions) -> tuple[str, str]:
    """Return (conversation.html, conversation.compact.html) contents.

    Both variants are complete single pages built from the shared conversation
    model. The per-block markdown fragments render_markdown joins are the single
    source of truth here too: each is wrapped in a data-copy-src carrying the
    RAW markdown (base64) beside its rendered body, so a copied fragment
    reproduces its transcript.md source verbatim (DESIGN section 6; proven by
    test_copy_as_markdown_payloads_equal_transcript_fragments). The compact
    variant reuses the policy that strips thinking, tools, machinery, reminders.
    """
    conv = build_conversation(data)
    meta = parse_session(data)
    repo = _session_repo(conv)
    full = _render_page(conv, meta, _full_policy(options), repo)
    compact = _render_page(conv, meta, _compact_policy(options), repo)
    return full, compact


def build_manifest(data: bytes, options: RenderOptions) -> dict[str, object]:
    """Per-session render manifest: source hash, counts, loss telemetry, config.

    Frozen keys (DESIGN section 6): source_hash (the payload's sha256),
    counts.prompts / counts.tool_calls, loss.skipped_lines (a malformed line is
    loss, never a silent drop, F6), and config (the RenderOptions used).
    """
    conv = build_conversation(data)
    manifest: dict[str, object] = {
        "source_hash": sha256_hex(data),
        "counts": {"prompts": conv.prompt_count, "tool_calls": conv.tool_call_count},
        "loss": {"skipped_lines": conv.skipped_lines},
        "config": asdict(options),
    }
    return manifest
