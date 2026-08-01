"""The 4-file projection emitters (slices 6-7). DESIGN section 6; SPEC sections 6-7.

One parser-produced conversation model (parser.build_conversation) feeds every
emitter. A single policy-parameterized core walks that model, so the full and
compact markdown variants are one implementation, not two near-verbatim copies
(F8/R9). The emitters take the raw payload so tests stay black-box.
"""

import base64
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from cc_warehouse.parser import (
    Block,
    Conversation,
    ParsedSession,
    Segment,
    Turn,
    build_conversation,
    detect_commits,
    detect_github_repo,
    group_segments,
    parse_session,
    split_reminder,
)
from cc_warehouse.store import sha256_hex


@dataclass(frozen=True)
class RenderOptions:
    reminders_full: str = "collapse"  # collapse | strip | show (personal override only)
    reminders_compact: str = "strip"
    breadcrumbs: bool = False
    # Per-content-class switches, all default ON (principal ruling 2026-07-23,
    # "include everything"). Each is an independent toggle here; wiring them to
    # config keys and CLI flags is ticket 13's frozen scope.
    subagents: bool = True
    attachments: bool = True
    commands: bool = True
    extras: bool = True  # bridge-session / queue-operation / last-prompt / agent-name
    toolresult_diff: bool = True
    # The per-VARIANT matrix (DESIGN 15 entry 2026-08-01, block 1). The five
    # fields above are the FULL variant's toggles and keep their v1 meaning; the
    # five below are the same content classes for the COMPACT variant, where the
    # v1 hard-coded drops become the DEFAULTS. All default OFF, so an empty
    # config renders byte-identical output before and after v1.1 (shared rule b,
    # proven by tests/test_matrix.py against tests/golden/matrix-anchor).
    subagents_compact: bool = False
    attachments_compact: bool = False
    commands_compact: bool = False
    extras_compact: bool = False
    tool_output_compact: bool = False
    # HTML chrome initial states (DESIGN 15 entry 2026-08-01, block 2). Every
    # chrome element stays on the page (exporter parity); only the STARTING
    # position moves, and each default below is the position v1 already had.
    # Values are WORDS, never the DOM's s/m/l letters, because config is a human
    # surface. Shared rule (d): these are page-level and VARIANT-AGNOSTIC, so
    # neither a `_full` nor a `_compact` form exists.
    html_width: str = "large"  # small | medium | large
    html_font: str = "small"  # small | medium | large
    html_turns: str = "expanded"  # expanded | collapsed
    # Unprefixed on purpose: the initial <details> state is emitted MARKUP and
    # reaches the markdown files too, so `html_details` would name it dishonestly.
    details: str = "closed"  # closed | open
    # Date display (block 4). CLIENT-SIDE by design: the markup always carries the
    # raw ISO stamp, so an unchanged session re-projects to identical bytes
    # forever and build.py's incremental byte-compare keeps working. A baked
    # local time would rewrite the warehouse on every timezone move and every DST
    # transition. `local` shows each stamp in the READER's own zone; `iso` leaves
    # the page exactly as its markup reads.
    html_dates: str = "local"  # local | iso
    # Opt-in truncation (DESIGN 15 entry 2026-08-01, block 3). 0 (or absent) is
    # OFF and is the default: an audit-trail product does not start dropping
    # content because you upgraded. CHARACTERS, said in the name, because the
    # renderer's native unit is decoded str, the archetypal offender is a
    # single-line blob a line cap would miss, and a KB cap means different
    # amounts per alphabet. One cap, variant-agnostic.
    tool_output_max_chars: int = 0
    # highlight.js delivery: cdn | inline | off (DESIGN 15 item 8, principal 2026-07-24).
    # Personal projections keep `cdn` for exporter parity; `ccw share` sets `inline` so a
    # published page makes no third-party request. See _hljs_block.
    hljs: str = "cdn"


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
    include_subagents: bool
    include_attachments: bool
    include_commands: bool
    include_extras: bool
    toolresult_diff: bool
    # Chrome, carried here because every emitter already receives a policy.
    # These two are VARIANT-AGNOSTIC (shared rule d): both builders below read
    # them from the same option, and a future edit that lets them diverge would
    # be a category error, not a feature.
    details_open: bool
    turns_collapsed: bool
    tool_output_max_chars: int


# The compact variant describes ITSELF in two places, and both sentences are
# derived rather than fixed. The word "compact" is load-bearing in each (oracle
# test test_compact_carries_a_variant_note). Once the per-variant matrix can put
# tools back into a compact file, a sentence that still says "no tools" denies
# the file it heads, which is the code overclaiming its own guarantees (F6, and
# R8's rule that a guarantee word cites the test that proves it). The same was
# already true of reminders, which `reminders_compact = "show"` has been able to
# restore since slice 6.
#
# The two sentences keep their own vocabularies (the markdown note lists
# "tools", the HTML meta strip says "tool detail") because both are v1 strings
# the regression anchor pins. What they share is the RULE, and
# test_the_compact_variant_note_never_denies_what_it_carries checks BOTH
# emitters -- the first version of that test checked only the markdown one and
# the HTML sentence went on lying.


def _details_tag(policy: _Policy) -> str:
    """The `<details>` open tag for this render.

    `details = "open"` is the one chrome knob that reaches the MARKDOWN files as
    well as the HTML, which is why DESIGN 15 names it without an `html_` prefix.
    Every emission site goes through here so the two formats cannot drift, and
    so the markdown-to-HTML whitelist has exactly one spelling to admit.
    """
    return "<details open>" if policy.details_open else "<details>"


def _compact_note(options: RenderOptions) -> str:
    """The compact markdown note, listing only what this variant actually drops.

    At the defaults the list is thinking, tools, reminders and the sentence is
    byte-identical to the v1 one, which is what keeps the regression anchor
    green (test_default_options_render_the_pre_slice_bytes).
    """
    dropped = ["thinking"]
    if not options.tool_output_compact:
        dropped.append("tools")
    if options.reminders_compact == "strip":
        dropped.append("reminders")
    if len(dropped) > 2:
        tail = ", ".join(dropped[:-1]) + ", or " + dropped[-1]
    else:
        tail = " or ".join(dropped)
    return f"> Compact variant: conversation only, no {tail}."


def _compact_meta_note(policy: _Policy) -> str:
    """The compact HTML page's meta-strip sentence, derived from the POLICY.

    Reads the policy rather than the options because this runs at emission time,
    where the policy is the only thing that knows what the page in front of the
    reader actually contains.
    """
    omitted = ["thinking"]
    if not policy.include_tools:
        omitted.append("tool detail")
    return (
        f'<span class="m-note">compact variant, {" and ".join(omitted)} omitted'
        " (see conversation.html)</span>"
    )


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


def _render_tool_use(block: Block, details_tag: str) -> list[str]:
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
    # Untyped tool: the exporter hides the raw payload behind a per-row toggle
    # rather than dumping it inline, so a long input cannot swamp the row. The
    # typed tools above keep their SPEC-7 rendering and need no toggle.
    payload = json.dumps(dict(tool_input), indent=2, sort_keys=True, ensure_ascii=False)
    safe = name.replace("<", "").replace(">", "")
    return [
        f"**{name}**",
        "",
        details_tag,
        f"<summary>\N{GEAR} raw {safe}</summary>",
        "",
        *_fence(payload, "json"),
        "",
        "</details>",
    ]


def _truncate(text: str, cap: int) -> tuple[str, int]:
    """Cut `text` to at most `cap` characters. Returns (kept, characters omitted).

    The cut lands at the LAST line boundary at or below the cap, because half a
    line reads as corrupted data rather than as omitted data. A single-line blob
    has no boundary to fall back to and is cut at the cap exactly - that case is
    the whole reason block 3 counts characters instead of lines.
    """
    if cap <= 0 or len(text) <= cap:
        return text, 0
    window = text[:cap]
    boundary = window.rfind("\n")
    kept = window[:boundary] if boundary > 0 else window
    return kept, len(text) - len(kept)


def _result_payloads(block: Block, structured: bool) -> list[str]:
    """The strings a tool-result block puts inside code fences.

    The single definition of what the cap applies to. `_render_tool_result` cuts
    these and `_truncation_loss` counts them, so the marker on the page and the
    number in the manifest can never disagree about the same block.
    """
    if structured and block.result is not None:
        rich = _structured_result(block.result)
        if rich is not None:
            streams = (
                _as_str(block.result.get("stdout")),
                _as_str(block.result.get("stderr")),
            )
            return [value for value in streams if value]
    return [block.text]


def _structured_result(result: Mapping[str, object], cap: int = 0) -> list[str] | None:
    """Render a tool_result's structured `toolUseResult` payload: stdout and
    stderr as separate fenced blocks, plus an interrupted marker (item 5).

    The Edit patch carried here is deliberately NOT re-rendered: the matching
    Edit tool_use already shows that exact diff, so repeating it is noise. What
    the raw result text cannot show -- separated streams, an interrupted flag --
    is what this adds. Returns None when there is nothing structured to surface,
    so the caller falls back to the plain result text.
    """
    lines: list[str] = []
    stdout, _ = _truncate(_as_str(result.get("stdout")) or "", cap)
    stderr, _ = _truncate(_as_str(result.get("stderr")) or "", cap)
    if stdout:
        lines.extend(["stdout:", *_fence(stdout)])
    if stderr:
        lines.extend(["", "stderr:", *_fence(stderr)])
    if result.get("interrupted") is True:
        lines.append("> interrupted")
    return lines or None


# The marker. Both halves are load-bearing: the COUNT makes the loss legible and
# the second clause stops the reader inferring that the archive lost something
# (F6 - a projection that quietly dropped content would be the product lying
# about its own completeness). Proven by
# test_the_marker_states_what_was_omitted and
# test_the_marker_says_the_stored_session_is_complete.
def _truncation_marker(omitted: int) -> str:
    return (
        "> \N{BLACK SCISSORS} "
        f"{omitted:,} characters omitted here by tool_output_max_chars. "
        "The stored session is complete; only this projection is capped."
    )


def _render_tool_result(block: Block, structured: bool = True, cap: int = 0) -> list[str]:
    text = block.text
    body: list[str] = [
        f"- commit `{commit.sha}`: {commit.message}" for commit in detect_commits(text)
    ]
    repo = detect_github_repo(text)
    if repo is not None:
        body.append(f"- repo: {repo}")
    omitted = sum(
        _truncate(payload, cap)[1] for payload in _result_payloads(block, structured)
    )
    rich: list[str] | None = None
    if structured and block.result is not None:
        rich = _structured_result(block.result, cap)
    if rich is not None:
        body.extend(rich)
    else:
        # Always keep the raw result text (safe-fenced), in addition to any
        # commit/repo cards, so detection never drops the rest of the result (F6).
        kept, _ = _truncate(text, cap)
        body.extend(_fence(kept))
    if omitted:
        body.extend(["", _truncation_marker(omitted)])
    return ["**Result:**", "", *body]


def _render_subagent(block: Block) -> list[str]:
    # One step of a sub-agent's exchange, as a bullet. The phase caption already
    # names the agent, so the line carries only the step.
    return [f"- {block.text}"]


def _render_command(block: Block) -> list[str]:
    return ["", f"`{block.text}`"]


def _render_extra(block: Block) -> list[str]:
    return [f"- {block.text}"]


def _render_attachment(block: Block) -> list[str]:
    header, _, body = block.text.partition("\n\n")
    out = ["", f"**{header}**"]
    if body:
        out.extend(["", *_fence(body)])
    return out


def _render_reminder(reminder: str, mode: str, details_tag: str) -> list[str]:
    if mode == "show":
        return ["", f"> system-reminder: {reminder}"]
    if mode == "collapse":
        return [
            "",
            details_tag,
            "<summary>system-reminder</summary>",
            "",
            *_fence(reminder),
            "",
            "</details>",
        ]
    # Any other value (strip, or an unknown/typo like "hide" or "") fails
    # CLOSED: the reminder is never leaked into the output (F7).
    return []


def _thinking_label(block: Block) -> str:
    """The thinking label: TYPE, then CAPTION joined with a pipe when one can be
    derived (DESIGN section 6). claude.ai supplies the caption as
    `thinking.summaries`; here it comes from the thinking text's own first line,
    so the label degrades to the bare TYPE rather than inventing one."""
    caption = _caption_from_thinking(block.text)
    return f"Thinking | {caption}" if caption else "Thinking"


def _render_machinery(block: Block, details_tag: str) -> list[str]:
    if block.kind == "continuation":
        return [
            "",
            details_tag,
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
        if not policy.include_thinking:
            return []
        # DESIGN section 6: the label's TYPE and CAPTION are held separately and
        # joined with "|" here. The blockquote label survives macOS Quick Look,
        # which drops <summary> text (exporter v8.7).
        label = f"> \N{THOUGHT BALLOON} {_thinking_label(block)}"
        return ["", label, "", *_fence(block.text, "md")]
    if kind == "tool_use":
        return ["", *_render_tool_use(block, _details_tag(policy))] if policy.include_tools else []
    if kind == "tool_result":
        if not policy.include_tools:
            return []
        return [
            "",
            *_render_tool_result(
                block, policy.toolresult_diff, policy.tool_output_max_chars
            ),
        ]
    if kind == "subagent":
        return _render_subagent(block) if policy.include_subagents else []
    if kind == "command":
        return _render_command(block) if policy.include_commands else []
    if kind == "attachment":
        return _render_attachment(block) if policy.include_attachments else []
    if kind == "extra":
        return _render_extra(block) if policy.include_extras else []
    if not policy.include_machinery:
        return []
    return _render_machinery(block, _details_tag(policy))


# --------------------------------------------------------------------------
# Phase presentation (DESIGN section 6; exporter v8.10.1 is the reference).
# A phase is parser.group_segments' run of non-reply blocks, shown as one
# collapsible unit with a caption, a duration, and tool counts. Every helper
# here is shared by the markdown and HTML emitters so a copied fragment
# reproduces its transcript.md source (R9/F8).
# --------------------------------------------------------------------------

_CAPTION_MAX = 72
_FILE_TOOLS = ("Edit", "Write", "NotebookEdit", "MultiEdit")


def _iso_seconds(stamp: str | None) -> float | None:
    """Epoch seconds for an ISO-8601 entry timestamp, or None when absent or
    unparseable. Trailing 'Z' is normalized: fromisoformat accepts an offset."""
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _elapsed_nice(seconds: float) -> str | None:
    """The exporter's elapsed ladder: '18 s', '3 min 42 s', '4 hrs 12 m',
    '2 days 3 h'. Full label on the primary unit, single letter on the
    secondary. Negative or non-finite spans yield None."""
    if seconds < 0 or seconds != seconds or seconds in (float("inf"), float("-inf")):
        return None
    total = int(round(seconds))
    if total < 60:
        return f"{total} s"
    minutes = total // 60
    if minutes < 60:
        return f"{minutes} min {total % 60} s"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} {'hr' if hours == 1 else 'hrs'} {minutes % 60} m"
    days = hours // 24
    return f"{days} {'day' if days == 1 else 'days'} {hours % 24} h"


def _turn_elapsed(turn: Turn, previous: Turn | None) -> str | None:
    """Gap between this turn's opening entry and the previous turn's last one.
    The first turn is the zero point and renders '0' (exporter v8.6)."""
    start = _iso_seconds(turn.first_ts)
    if start is None:
        return None
    if previous is None:
        return "0"
    earlier = _iso_seconds(previous.last_ts) or _iso_seconds(previous.first_ts)
    if earlier is None:
        return None
    return _elapsed_nice(start - earlier)


def _caption_from_thinking(text: str) -> str | None:
    """A phase caption derived from the thinking text's first meaningful line.

    claude.ai supplies `thinking.summaries` for this; a Claude Code transcript
    has no such field, so the nearest real equivalent is the opening line of the
    thinking itself, trimmed to one clause. Returns None when nothing usable is
    left, and the caller falls back to a tool-derived caption.
    """
    for raw in text.split("\n"):
        line = raw.strip().lstrip("#>-*+ ").strip()
        # A caption lands inside a <summary> line and a blockquote, so angle
        # brackets and backticks are removed rather than escaped: the same
        # string has to read correctly in both places.
        line = line.replace("<", "").replace(">", "").replace("`", "").strip()
        if not line:
            continue
        if len(line) > _CAPTION_MAX:
            line = line[: _CAPTION_MAX - 3].rstrip() + "..."
        return line
    return None


@dataclass(frozen=True)
class _PhaseMeta:
    icon: str
    caption: str
    bits: tuple[str, ...]
    errors: bool

    def head(self) -> str:
        dot = " \N{MIDDLE DOT} "
        tail = dot.join(self.bits)
        warn = " \N{WARNING SIGN}" if self.errors else ""
        return f"{self.icon} {self.caption}{warn}{dot + tail if tail else ''}"


def _phase_meta(blocks: tuple[Block, ...]) -> _PhaseMeta:
    """Caption, duration bits and tool counts for one phase (exporter groupMeta).

    Caption priority mirrors the exporter: the LAST thinking block's caption
    wins, then any tool name, then the generic 'Worked'. DESIGN section 6 keeps
    label TYPE and CAPTION separate; they are joined at render time here.
    """
    thinking = [b for b in blocks if b.kind == "thinking" and b.text.strip()]
    caption: str | None = None
    for block in reversed(thinking):
        caption = _caption_from_thinking(block.text)
        if caption:
            break
    tool_uses = [b for b in blocks if b.kind == "tool_use"]
    if not caption:
        # No thinking to caption from: name the tools the phase actually ran,
        # in first-use order, so the summary line says what happened rather
        # than naming only the last call.
        names: list[str] = []
        for block in tool_uses:
            if block.tool_name and block.tool_name not in names:
                names.append(block.tool_name)
        if names:
            caption = ", ".join(names[:3]) + (", ..." if len(names) > 3 else "")
    subagent = {b.agent_id for b in blocks if b.kind == "subagent"}
    if not caption and subagent:
        names = sorted(a for a in subagent if a)
        caption = "sub-agent" + (f": {names[0]}" if len(names) == 1 and names[0] else "")
    if not caption:
        for kind, word in (("attachment", "attachments"), ("command", "commands"),
                           ("extra", "session events"), ("machinery", "background")):
            if any(b.kind == kind for b in blocks):
                caption = word
                break
    searches = sum(1 for b in tool_uses if b.tool_name == "WebSearch")
    fetches = sum(1 for b in tool_uses if b.tool_name == "WebFetch")
    others = len(tool_uses) - searches - fetches
    bits: list[str] = []
    n_sub = sum(1 for b in blocks if b.kind == "subagent")
    if n_sub:
        bits.append(f"{n_sub} sub-agent step" + ("" if n_sub == 1 else "s"))
    if searches:
        bits.append(f"{searches} search" if searches == 1 else f"{searches} searches")
    if fetches:
        bits.append(f"{fetches} fetch" if fetches == 1 else f"{fetches} fetches")
    if others:
        bits.append(f"{others} tool" if others == 1 else f"{others} tools")
    if thinking:
        count = len(thinking)
        bits.append("1 thought" if count == 1 else f"{count} thoughts")
    if subagent:
        icon = "\N{ROBOT FACE}"
    elif thinking:
        icon = "\N{MICROSCOPE}"
    else:
        icon = "\N{JIGSAW PUZZLE PIECE}"
    return _PhaseMeta(
        icon=icon,
        caption=caption or "Worked",
        bits=tuple(bits),
        errors=any(b.kind == "tool_result" and _looks_failed(b.text) for b in blocks),
    )


def _looks_failed(text: str) -> bool:
    """Whether a tool result reads as an error. claude.ai carries an `is_error`
    flag; a Claude Code tool_result carries only text, so this is a surface
    reading and deliberately conservative."""
    head = text.lstrip()[:200].lower()
    return head.startswith(("error", "error:", "traceback")) or "<tool_use_error>" in head


def _file_targets(conv: Conversation) -> list[tuple[str, str]]:
    """(path, verb) for every file-editing tool call, first mention wins.

    The exporter's Artifacts Index has no counterpart in a Claude Code session:
    there are no artifacts. The nearest real equivalent is the set of files the
    session created or edited, so that slot carries this instead of standing
    empty (operator ruling 2026-07-21: substitute an alternate value where one
    exists rather than blank the section).
    """
    seen: dict[str, str] = {}
    for turn in conv.turns:
        for block in turn.blocks:
            if block.kind != "tool_use" or block.tool_name not in _FILE_TOOLS:
                continue
            path = _as_str((block.tool_input or {}).get("file_path"))
            if not path or path in seen:
                continue
            seen[path] = "created" if block.tool_name == "Write" else "edited"
    return list(seen.items())


# --------------------------------------------------------------------------
# The single core: header card, then `***`-separated turns.
# --------------------------------------------------------------------------


def _title(meta: ParsedSession) -> str:
    """The page/document title. Priority (principal ruling 2026-07-23): Claude
    Code's own ai-title, then the slug, then the first line of the summary, then
    a bare fallback. The summary can be a machine-generated CONTEXT: wrapper, so
    it ranks below the real title."""
    if meta.ai_title:
        return meta.ai_title
    if meta.slug:
        return meta.slug
    visible, _ = split_reminder(meta.summary)
    visible = visible.strip()
    if visible and visible != "(no summary)":
        return visible.split("\n")[0]
    return "session"


def _claude_turn_count(conv: Conversation, policy: _Policy) -> int:
    """How many `## Claude` sections this variant emits: the turns whose Claude
    half survives the policy. Equals the number of Claude sections on the page,
    which is what makes the header's split honest."""
    return sum(1 for t in conv.turns if not t.synthetic and _claude_md(t, policy))


def _lean_rows(
    meta: ParsedSession, conv: Conversation, policy: _Policy, source_hash: str
) -> list[str]:
    """The header card's always-visible identity lines (exporter's lean header).

    The exporter shows Source URL / Exported / Model. A captured Claude Code
    session has none of those, so the same slots carry what does exist: the
    content address that names the stored payload, the project path, the branch,
    the session UUID and the captured span. A field with no value keeps its row
    and shows a blank, so the layout is stable across sessions (operator ruling
    2026-07-21).
    """
    dot = " \N{MIDDLE DOT} "
    span = " \N{RIGHTWARDS ARROW} ".join(x for x in (meta.first_ts, meta.last_ts) if x)
    # Claude TURNS, not assistant blocks: this is the count of "## Claude"
    # sections the file actually contains, so the split matches what is on the
    # page. Counting blocks reported 153 Claude against 13 you.
    replies = _claude_turn_count(conv, policy)
    rows = [
        f"> **Source:** s-{source_hash[:12]}{dot}sha256 `{source_hash}`",
        f"> **Project:** {meta.cwd or ''}",
        f"> **Branch:** {meta.git_branch or ''}",
        f"> **Session:** {meta.session_uuid or ''}",
        f"> **Captured:** {span}",
        f"> **Model:** {meta.model or ''}",
        f"> **Turns:** {conv.prompt_count}{dot}{conv.prompt_count} you /"
        f" {replies} Claude (source: claude-code)",
    ]
    if policy.variant_note:
        # Carries the word "compact" (test_compact_carries_a_variant_note) so the
        # variant needs no second, duplicate note line.
        rows.append(f"> **Variant:** {policy.variant_note}")
    if conv.skipped_lines:
        rows.append(
            f"> \N{WARNING SIGN} **{conv.skipped_lines} unreadable line(s)** skipped"
            f"{dot}see manifest.json loss telemetry"
        )
    return rows


def _detail_rows(meta: ParsedSession, conv: Conversation, policy: _Policy) -> list[str]:
    """The collapsed "More details" grid. Counts are computed from the model, so
    they describe THIS render rather than restating the source."""
    dot = " \N{MIDDLE DOT} "
    replies = _claude_turn_count(conv, policy)
    thinking = sum(1 for t in conv.turns for b in t.blocks if b.kind == "thinking")
    words = sum(len(t.prompt.split()) for t in conv.turns)
    words += sum(len(b.text.split()) for t in conv.turns for b in t.blocks)
    files = _file_targets(conv)
    rows = [
        f"- **Split:** {conv.prompt_count} you / {replies} Claude",
        f"- **Content:** ~{words:,} words{dot}{thinking} thinking blocks"
        f"{dot}{conv.tool_call_count} tool calls",
        f"- **Files touched:** {len(files)}",
        f"- **Loss:** {conv.skipped_lines} skipped line(s)",
        f"- **Slug:** {meta.slug or ''}",
        f"- **Model:** {meta.model or ''}",
        f"- **CLI version:** {meta.version or ''}",
        f"- **Source lines:** {meta.line_count}",
        f"- **Hidden:** {'yes' if meta.hidden else 'no'}",
        "- **Renderer:** cc-warehouse (reference: exporter v8.10.1)",
    ]
    visible, _ = split_reminder(meta.summary)
    visible = " ".join(visible.split())
    if visible and visible != "(no summary)":
        # The exporter's italic chat-summary line (.more-grid .full).
        rows.append(f"- **Summary:** *{visible}*")
    return rows


def _header(
    meta: ParsedSession,
    policy: _Policy,
    conv: Conversation,
    source_hash: str,
) -> list[str]:
    suffix = " (compact)" if policy.variant_note else ""
    lines = [f"# Transcript{suffix}: {_title(meta)}", ""]
    lines.extend(_lean_rows(meta, conv, policy, source_hash))
    if policy.header_details:
        lines.extend(
            [
                "",
                _details_tag(policy),
                "<summary>More details</summary>",
                "",
                "> \N{INFORMATION SOURCE}\N{VARIATION SELECTOR-16} More details",
                "",
                *_detail_rows(meta, conv, policy),
                "",
                "</details>",
            ]
        )
    lines.append("")
    return lines


def _phase_md(segment: Segment, policy: _Policy) -> list[str]:
    """One phase as markdown: a collapsible section whose summary is the caption
    line, with a blockquote breadcrumb repeating it inside.

    The breadcrumb is not decoration: macOS Quick Look drops <summary> text
    entirely, so a reader there would otherwise see an unlabelled block (the
    exporter's v8.7 hybrid-label finding). In the compact variant the section
    collapses to that breadcrumb alone, and only when breadcrumbs are on.
    """
    meta = _phase_meta(segment.blocks)
    inner: list[str] = []
    for block in segment.blocks:
        inner.extend(_render_block(block, policy))
    inner = _strip_separators(inner)
    if not inner:
        return ["", f"> {meta.head()}", ""] if policy.breadcrumbs else []
    # The leading blank is required, not cosmetic: CommonMark needs a blank line
    # before an HTML block, or a preceding paragraph swallows the open tag
    # (the spacing class the exporter fixed in v8.7).
    return [
        "",
        _details_tag(policy),
        f"<summary>{meta.head()}</summary>",
        "",
        f"> {meta.head()}",
        "",
        *inner,
        "",
        "</details>",
        "",
    ]


def _turn_body(turn: Turn, policy: _Policy) -> list[str]:
    """Everything under a turn's `## Claude` heading: phases and replies, in
    source order. Shared by the markdown file and the HTML copy payloads."""
    lines: list[str] = []
    for segment in group_segments(turn):
        if segment.is_phase:
            lines.extend(_phase_md(segment, policy))
            continue
        lines.extend(_render_block(segment.blocks[0], policy))
    # Segment boundaries each contribute their own blank line; collapse the
    # doubles so the file reads as one document rather than a concatenation.
    collapsed: list[str] = []
    for line in lines:
        if not line.strip() and collapsed and not collapsed[-1].strip():
            continue
        collapsed.append(line)
    return collapsed


def _user_md(turn: Turn, total: int, policy: _Policy, elapsed: str | None) -> list[str]:
    """The `## User` half of a turn: heading, optional breadcrumb, prompt,
    reminders. Shared with the HTML emitter so the user SECTION on the page and
    the user half of the file are built from one definition (R9)."""
    stamp = turn.first_ts or ""
    tail = f" \N{MIDDLE DOT} {stamp}" if stamp else ""
    if elapsed:
        tail += f" \N{MIDDLE DOT} \N{STOPWATCH} {elapsed}"
    lines = [f"## \N{BUST IN SILHOUETTE} User{tail}"]
    if policy.breadcrumbs:
        lines.append(f"> breadcrumb: turn {turn.ordinal} of {total}")
    lines.append("")
    if turn.prompt:
        lines.append(_harden(turn.prompt))
    for reminder in turn.reminders:
        lines.extend(_render_reminder(reminder, policy.reminder_mode, _details_tag(policy)))
    return _strip_separators(lines)


def _claude_md(turn: Turn, policy: _Policy) -> list[str]:
    """The `## Claude` half: every phase and reply that followed the prompt.
    Empty when the policy strips all of it (the compact variant of a turn whose
    only content was thinking and tools)."""
    body = _strip_separators(_turn_body(turn, policy))
    if not body:
        return []
    stamp = turn.last_ts or ""
    head = "## \N{ROBOT FACE} Claude"
    if stamp:
        head += f" \N{MIDDLE DOT} {stamp}"
    return [head, "", *body]


def _synthetic_md(turn: Turn, policy: _Policy) -> list[str]:
    body = _strip_separators(_turn_body(turn, policy))
    if not body:
        return []
    return ["## \N{ELECTRIC PLUG} Pre-conversation entries", "", *body]


def _render_turn(
    turn: Turn, total: int, policy: _Policy, elapsed: str | None = None
) -> list[str]:
    """One turn as markdown: the user half, then the Claude half, each preceded
    by the Quick-Look-safe rule. The exporter gives every ROLE turn its own
    heading and separator; our model pairs a prompt with its replies, so the
    pair is emitted as those same two role sections."""
    if turn.synthetic:
        if not policy.include_machinery:
            return []
        synthetic = _synthetic_md(turn, policy)
        return ["***", "", *synthetic, ""] if synthetic else []
    lines = ["***", "", *_user_md(turn, total, policy, elapsed), ""]
    claude = _claude_md(turn, policy)
    if claude:
        lines.extend(["***", "", *claude, ""])
    return lines


def _files_index_md(conv: Conversation) -> list[str]:
    files = _file_targets(conv)
    if not files:
        return []
    lines = ["***", "", "## \N{BOOKMARK TABS} Files Index", ""]
    for i, (path, verb) in enumerate(files, start=1):
        lines.append(f"{i}. **{path}** ({verb})")
    lines.append("")
    return lines


def _elapsed_labels(conv: Conversation) -> list[str | None]:
    """Per-turn elapsed labels, positionally aligned with conv.turns. Computed
    once here so the markdown and HTML emitters cannot disagree (R9)."""
    labels: list[str | None] = []
    previous: Turn | None = None
    for turn in conv.turns:
        if turn.synthetic:
            labels.append(None)
            continue
        labels.append(_turn_elapsed(turn, previous))
        previous = turn
    return labels


def _render(
    conv: Conversation, meta: ParsedSession, policy: _Policy, source_hash: str
) -> str:
    lines = _header(meta, policy, conv, source_hash)
    labels = _elapsed_labels(conv)
    for turn, elapsed in zip(conv.turns, labels, strict=True):
        lines.extend(_render_turn(turn, conv.prompt_count, policy, elapsed))
    lines.extend(_files_index_md(conv))
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
        include_subagents=options.subagents,
        include_attachments=options.attachments,
        include_commands=options.commands,
        include_extras=options.extras,
        toolresult_diff=options.toolresult_diff,
        details_open=options.details == "open",
        turns_collapsed=options.html_turns == "collapsed",
        tool_output_max_chars=options.tool_output_max_chars,
    )


def _compact_policy(options: RenderOptions) -> _Policy:
    """The compact variant's policy. Its v1 hard-coded drops are now DEFAULTS:
    each per-variant key (DESIGN 15 entry 2026-08-01, block 1) turns one content
    class back on for this variant alone, and every one of them defaults OFF.

    Thinking is the deliberate exception and has no key on either variant:
    BRAINSTORM locks it ON in full variants and welded OFF here, so a toggle for
    it would be its own future proposal (the entry's NON-SCOPE line).
    """
    return _Policy(
        include_thinking=False,
        # `tool_output_compact` lifts BOTH tool gates, not just the diff one. In
        # the full variant tool blocks always render and the unsuffixed
        # `tool_output` key chooses only how a RESULT is drawn; compact drops the
        # blocks outright, so binding the compact key to `toolresult_diff` alone
        # would make it a key that can never change a byte. DESIGN 15 block 3
        # settles which reading is intended: the truncation cap applies
        # "wherever a tool-result block renders (full by default; compact if the
        # matrix opened it)" -- so the matrix must be able to open it.
        include_tools=options.tool_output_compact,
        include_machinery=False,
        reminder_mode=options.reminders_compact,
        variant_note=_compact_note(options),
        breadcrumbs=options.breadcrumbs,
        # Exporter parity: the compact variant keeps the SAME header card as the
        # full one (its finalMdCompact reuses the built header verbatim), so the
        # two files stay comparable and the HTML page matches its markdown.
        header_details=True,
        # Compact is prose conversation only BY DEFAULT: sub-agents, attachments,
        # commands and the informational extras are detail it drops until the
        # matching key says otherwise.
        include_subagents=options.subagents_compact,
        include_attachments=options.attachments_compact,
        include_commands=options.commands_compact,
        include_extras=options.extras_compact,
        toolresult_diff=options.tool_output_compact,
        # Identical to the full policy's, by contract: chrome is page-level.
        details_open=options.details == "open",
        turns_collapsed=options.html_turns == "collapsed",
        # One cap, variant-agnostic (block 3): the same value as the full
        # policy's, so a block cut in one file is cut identically in the other.
        tool_output_max_chars=options.tool_output_max_chars,
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
    source_hash = sha256_hex(data)
    full = _render(conv, meta, _full_policy(options), source_hash)
    compact = _render(conv, meta, _compact_policy(options), source_hash)
    return full, compact


# --------------------------------------------------------------------------
# In-house markdown -> HTML (slice 7). Scope: the markdown WE emit plus the
# SPEC-7 hardening; stdlib only (R7), no third-party renderer. User TEXT is
# escaped; our own block-level HTML (<details>/<summary>) passes through.
# --------------------------------------------------------------------------

_MD_HEADING_RE = re.compile(r"^(#{1,6}) +(.*)$")
_MD_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)]) +(.*)$")
# Only the block-level HTML we emit ourselves passes through unescaped.
# `<details open>` is admitted alongside the bare tag: `details = "open"` puts
# the opened spelling into the markdown WE emit, and a whitelist that only
# knew the bare one would escape it onto the page as literal text.
_MD_PASSTHROUGH_RE = re.compile(
    r"^(?:<details(?: open)?>|</details>|<summary>[^<]*</summary>)$"
)
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
# DESIGN section 6 permits the highlight.js SCRIPT as the ONE external
# reference, and test_page_has_a_single_external_cdn_reference pins that count.
# The exporter also links a tokyo-night-dark stylesheet, which would be a second
# reference: instead the token colours are inlined into _CSS below, so the page
# keeps the exporter's look while honouring our stricter rule.
_HLJS_SCRIPT = (
    f'<script src="{_HLJS_BASE}/highlight.min.js" '
    'onload="hljs.highlightAll()" onerror="void 0"></script>'
)


def _hljs_block(mode: str) -> str:
    """The highlight.js delivery for one page (DESIGN 15 item 8, principal 2026-07-24).

    `cdn` keeps the single external reference plus its graceful onerror fallback, which is
    exporter parity and stays the default for personal projections. `inline` embeds the
    VENDORED script so a page makes no third-party request at all: `ccw share` sets this,
    because redaction scrubs the CONTENT while a CDN script exposes the READER, announcing
    their IP and the page URL to a third party. It also keeps a published archive working
    after a pinned CDN URL stops resolving. `off` emits nothing and code renders
    unhighlighted, which is what the cdn fallback already does when the network is absent.

    The payload is read from disk rather than pasted here, so it cannot drift from
    vendor/README.md's recorded sha256; the emitted bytes are asserted to equal that file
    in tests/test_render_html_regressions.py::
    test_hljs_modes_control_the_one_external_reference.

    An unknown mode falls back to `cdn`: this is presentation, and refusing to render a
    transcript over a misspelt display option would be the wrong conservative branch.
    """
    if mode == "off":
        return ""
    if mode == "inline":
        payload = (Path(__file__).parent / "vendor" / "highlight.min.js").read_text(
            encoding="utf-8"
        )
        # The vendored bundle contains no "</script>", so it needs no escaping; a future
        # bundle that did would break the page, which the byte-equality test would catch.
        return f"<script>{payload}\nhljs.highlightAll();</script>"
    return _HLJS_SCRIPT
_TOOLBAR = (
    '<div class="toolbar">'
    '<button data-act="collapse">Collapse all</button>'
    '<button data-act="expand-turns">Expand turns</button>'
    '<button data-act="expand-all">Expand all</button>'
    '<button data-act="copyall">Copy ALL as Markdown</button>'
    '<span class="turnpos" id="turnpos"></span>'
    '<span class="wbtns">'
    '<button data-w="s" title="950px">S</button>'
    '<button data-w="m" title="1400px">M</button>'
    '<button data-w="l" title="1900px">L</button></span>'
    '<span class="fbtns">'
    '<button data-f="s" title="12.8px">A-</button>'
    '<button data-f="m" title="14px">A</button>'
    '<button data-f="l" title="16px">A+</button></span>'
    "</div>"
)
# Double-click a block to copy its exact transcript.md markdown from the
# base64 data-copy-src payload. Best-effort; the page renders without it.
_COPY_SCRIPT_TEMPLATE = """\
<script>
(function () {
  function decode(value) {
    var binary = atob(value);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return new TextDecoder("utf-8").decode(bytes);
  }
  function payload(node) {
    return node ? decode(node.getAttribute("data-copy-src")) : "";
  }
  function flash(btn, text) {
    var old = btn.textContent;
    btn.textContent = text;
    setTimeout(function () { btn.textContent = old; }, 1200);
  }
  function copy(btn, text) {
    if (!navigator.clipboard) { flash(btn, "no clipboard"); return; }
    navigator.clipboard.writeText(text).then(
      function () { flash(btn, "Copied"); },
      function () { flash(btn, "Copy failed"); }
    );
  }
  // Every copy button reads the data-copy-src of its nearest carrier, so the
  // page has ONE payload mechanism: the per-fragment transcript.md markdown.
  document.querySelectorAll(".copy-md").forEach(function (btn) {
    btn.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      copy(btn, payload(btn.closest("[data-copy-src]")));
    });
  });
  document.addEventListener("dblclick", function (event) {
    var node = event.target.closest("[data-copy-src]");
    if (!node || !navigator.clipboard) { return; }
    navigator.clipboard.writeText(payload(node));
  });
  document.querySelectorAll(".turn-head").forEach(function (head) {
    head.addEventListener("click", function (event) {
      if (event.target.closest(".copy-md")) { return; }
      var section = head.closest("section.turn");
      if (section) { section.classList.toggle("collapsed"); }
    });
  });
  document.querySelectorAll(".toolbar button[data-act]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var act = btn.dataset.act;
      if (act === "copyall") {
        copy(btn, payload(document.getElementById("whole-transcript")));
        return;
      }
      document.querySelectorAll("section.turn").forEach(function (s) {
        s.classList.toggle("collapsed", act === "collapse");
      });
      if (act !== "expand-turns") {
        document.querySelectorAll("section.turn details").forEach(function (d) {
          d.open = act === "expand-all";
        });
      }
    });
  });
  function toggler(key, prefix, selector, fallback) {
    var btns = document.querySelectorAll(selector);
    var apply = function (value) {
      document.body.classList.remove(prefix + "s", prefix + "m", prefix + "l");
      document.body.classList.add(prefix + value);
      btns.forEach(function (b) {
        b.classList.toggle("active", b.dataset[prefix === "w-" ? "w" : "f"] === value);
      });
      try { localStorage.setItem(key, value); } catch (e) { /* private mode */ }
    };
    btns.forEach(function (b) {
      b.addEventListener("click", function () {
        apply(b.dataset[prefix === "w-" ? "w" : "f"]);
      });
    });
    var saved = fallback;
    try { saved = localStorage.getItem(key) || fallback; } catch (e) { /* private mode */ }
    apply(["s", "m", "l"].indexOf(saved) >= 0 ? saved : fallback);
  }
  toggler("ccw_html_width", "w-", ".wbtns button", "__W__");
  toggler("ccw_html_font", "f-", ".fbtns button", "__F__");
  var pos = document.getElementById("turnpos");
  var turns = [].slice.call(document.querySelectorAll("section.turn"));
  var ticking = false;
  function updatePos() {
    ticking = false;
    if (!pos || !turns.length) { return; }
    var bar = document.querySelector(".toolbar");
    var edge = (bar ? bar.getBoundingClientRect().bottom : 0) + 4;
    var cur = 0;
    for (var i = 0; i < turns.length; i += 1) {
      cur = i;
      if (turns[i].getBoundingClientRect().bottom > edge) { break; }
    }
    var who = turns[cur].classList.contains("user") ? "\\u{1F464}" : "\\u{1F916}";
    pos.innerHTML = who + " turn <b>" + (cur + 1) + "</b> / " + turns.length;
  }
  addEventListener("scroll", function () {
    if (!ticking) { ticking = true; requestAnimationFrame(updatePos); }
  }, { passive: true });
  updatePos();
  var top = document.createElement("button");
  top.id = "totop";
  top.textContent = "\\u2191";
  top.title = "Scroll to top";
  document.body.appendChild(top);
  top.addEventListener("click", function () {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  addEventListener("scroll", function () {
    top.classList.toggle("show", scrollY > innerHeight);
  }, { passive: true });
})();
</script>"""
_SIZE_LETTER = {"small": "s", "medium": "m", "large": "l"}

# The date pass (block 4). It reads the ISO stamp out of the span's OWN TEXT,
# which is why the markup needs no data attribute and no extra byte: under `iso`
# the page is exactly what it always was, and under `local` the only difference
# is this one script block. The original stamp moves to `title`, so hovering
# still recovers the exact recorded instant (the audit form is never lost).
#
# Nothing here runs at render time. The reader's browser holds the timezone, and
# this file never learns it -- that is the whole determinism argument.
_DATE_SCRIPT = """\
<script id="ccw-local-dates">
(function () {
  var nodes = document.querySelectorAll(".timestamp");
  for (var i = 0; i < nodes.length; i += 1) {
    var el = nodes[i];
    var iso = (el.textContent || "").trim();
    if (!iso) { continue; }
    var when = new Date(iso);
    if (isNaN(when.getTime())) { continue; }
    el.setAttribute("title", iso);
    el.textContent = when.toLocaleString();
  }
})();
</script>"""


def _date_block(options: RenderOptions) -> str:
    """The date pass, or nothing when the page is asked to stay ISO."""
    return _DATE_SCRIPT if options.html_dates == "local" else ""


def _copy_script(options: RenderOptions) -> str:
    """The page script, with the two size togglers' FALLBACKS filled in.

    A fallback is only what a fresh browser sees: the emitted JS still reads
    `localStorage.getItem(key) || fallback`, so a reader who has clicked the S/M/L
    buttons keeps their own choice forever after. Config sets the starting point,
    never the answer (DESIGN 15 block 2's localStorage-interplay sentence).

    The config values are WORDS and the DOM speaks s/m/l, so the mapping happens
    here, once, rather than letting `medium` leak into markup where the buttons
    and the saved value would stop agreeing about what they mean.
    """
    return _COPY_SCRIPT_TEMPLATE.replace(
        "__W__", _SIZE_LETTER[options.html_width]
    ).replace("__F__", _SIZE_LETTER[options.html_font])


# Catppuccin-Macchiato-derived palette and chrome (DESIGN section 6; the
# structure, class names and colour roles follow exporter v8.10.1 so a
# cc-warehouse page and an exporter page read as the same product).
_CSS = """\
:root {
  --bg:#1f202f; --text:#ccd3f3; --muted:#6f738b;
  --yellow:#ddca9d; --blue:#93acef; --green:#afd89b;
  --peach:#e5a982; --sky:#8ec2e1; --mauve:#c2a2f1;
  --surface:#262838; --deep:#181925; --line:#34364a;
  --mono:"JetBrainsMono Nerd Font Mono","JetBrains Mono","Fira Code",ui-monospace,monospace;
}
body { background:var(--bg); color:var(--text); font-family:var(--mono),system-ui,sans-serif;
  margin:0 auto; padding:24px; line-height:1.7; font-weight:300; transition:max-width .2s; }
body.f-s { font-size:0.8em; } body.f-m { font-size:0.875em; } body.f-l { font-size:1em; }
body.w-s { max-width:min(950px, 94vw); }
body.w-m { max-width:min(1400px, 94vw); }
body.w-l { max-width:min(1900px, 92vw); }
strong, summary, .role, th, button { font-weight:700; }
h1 { color:var(--mauve); border-bottom:1px solid var(--line); padding-bottom:12px;
  font-size:1.5em; }
h2,h3,h4,h5,h6 { color:var(--mauve); }
.role { font-weight:bold; font-size:0.85em; text-transform:uppercase; letter-spacing:1px;
  display:flex; align-items:center; margin:0; }
.user .role { color:var(--blue); } .assistant .role { color:var(--peach); }
.timestamp { color:var(--muted); font-size:0.85em; margin-left:12px; font-weight:normal;
  text-transform:none; letter-spacing:normal; }
.elapsed { color:var(--green); font-size:0.85em; margin-left:12px; font-weight:normal;
  text-transform:none; letter-spacing:normal; }
details { margin:8px 0; background:var(--deep); border-radius:8px; padding:8px 12px;
  border:1px solid var(--line); }
details > summary { cursor:pointer; font-weight:bold; color:var(--sky);
  display:flex; align-items:center; gap:8px; list-style-position:inside; }
pre { background:var(--deep); padding:14px 16px; border-radius:8px; overflow-x:auto;
  border:1px solid var(--line); }
code { font-family:var(--mono); font-size:0.9em; }
p code, li code, td code { background:rgba(175,216,155,0.12); color:var(--green);
  padding:2px 6px; border-radius:4px; }
a { color:var(--sky); } img { max-width:100%; border-radius:8px; margin:8px 0; }
strong { color:var(--yellow); }
table { border-collapse:collapse; margin:12px 0; width:100%; }
th,td { border:1px solid var(--line); padding:6px 10px; text-align:left; }
th { background:var(--surface); color:var(--blue); }
blockquote { border-left:3px solid var(--muted); margin:8px 0; padding:4px 12px;
  color:var(--muted); }
ul,ol { padding-left:24px; } li { margin:4px 0; }
.toolbar { display:flex; gap:8px; margin:0 0 20px; flex-wrap:wrap; align-items:center;
  position:sticky; top:0; z-index:5; background:var(--bg); padding:10px 0;
  border-bottom:1px solid var(--line); }
.toolbar button, .copy-md { background:transparent; border:1px solid var(--line);
  color:var(--muted);
  padding:5px 12px; border-radius:7px; cursor:pointer; font-size:12px; font-weight:600;
  font-family:var(--mono); transition:color .15s, border-color .15s; }
.toolbar button:hover, .copy-md:hover { color:var(--text); border-color:var(--muted); }
.toolbar button.active { border-color:var(--sky); color:var(--sky); }
.wbtns, .fbtns { display:flex; gap:6px; } .wbtns { margin-left:auto; }
.fbtns { border-left:1px solid var(--line); padding-left:12px; margin-left:6px; }
.turnpos { margin:0 auto; font-size:12px; color:var(--muted); background:var(--surface);
  border:1px solid var(--line); border-radius:999px; padding:4px 14px; white-space:nowrap; }
.turnpos b { color:var(--sky); font-weight:700; }
/* The class lives on a wrapper, never on the details element itself: every
   disclosure tag the page emits stays bare so opening and closing literals
   balance (test_user_details_line_is_escaped_and_page_balanced). Note this
   comment must not spell that tag out either, for the same reason. */
.turn { margin:24px 0; border-radius:10px; border:1px solid var(--line); padding:0;
  overflow:hidden; background:transparent; }
.turn.user { background:rgba(147,172,239,0.06); border-left:3px solid var(--blue); }
.turn.assistant { background:rgba(229,169,130,0.05); border-left:3px solid var(--peach); }
/* A turn collapses by CLASS, not by a disclosure element: the body is visible
   in plain HTML, so a reader with scripting off still sees the whole
   conversation, and the toolbar drives the same class. */
.turn-head { cursor:pointer; padding:12px 20px; display:flex; align-items:center;
  gap:10px; user-select:none; }
.turn-head::before { content:"\\25B6"; font-size:10px; color:var(--muted);
  transition:transform .15s; line-height:1; align-self:center; transform:rotate(90deg); }
.turn.collapsed .turn-head::before { transform:none; }
.turn.collapsed .turn-body { display:none; }
.turn-body { padding:0 20px 16px; }
.copy-md { margin-left:auto; flex-shrink:0; font-size:15px; line-height:1; padding:5px 11px; }
.copy-md.sub { padding:2px 9px; font-size:14px; margin-left:auto; }
.meta { position:relative; line-height:1.9; background:var(--surface); border:1px solid var(--line);
  border-radius:10px; padding:14px 20px 10px; margin-bottom:12px; color:var(--muted);
  font-size:0.9em; }
.meta > .copy-md { position:absolute; top:12px; right:14px; margin:0; }
.meta .m-key { color:var(--sky); }
.meta .m-warn { color:var(--yellow); }
.meta .m-model { color:var(--mauve); font-weight:700; background:rgba(194,162,241,0.12);
  padding:1px 9px; border-radius:6px; }
.meta .m-you { color:var(--blue); } .meta .m-claude { color:var(--peach); }
.more-grid .full { grid-column:1 / -1; font-style:italic; color:var(--muted); }
.row .rbody p { margin:6px 0; }
.row .rlabel .q { color:var(--green); }
.meta .m-note { color:var(--muted); font-size:0.88em; }
.meta .m-note::before { content:"\\2022"; color:var(--yellow); margin-right:7px; }
.more > details { background:transparent; border:none; border-top:1px solid var(--line);
  border-radius:0; padding:8px 0 0; margin:10px 0 0; }
.more > details > summary { color:var(--sky); font-size:0.9em; font-weight:700;
  display:inline-flex; align-items:center; gap:6px; cursor:pointer; }
.more > details > summary:hover { text-decoration:underline; }
.more > details > summary::before { content:"\\25B8"; font-size:11px; transition:transform .15s;
  line-height:1; }
.more > details[open] > summary::before { transform:rotate(90deg); }
.more-grid { display:grid; grid-template-columns:max-content 1fr; gap:2px 18px;
  font-size:0.88em; color:var(--muted); padding:8px 0 0 4px; }
.more-grid .k { color:var(--sky); }
.more-grid .v { color:var(--text); font-weight:300; }
.phase { background:var(--deep); border:1px solid var(--line);
  border-left:3px solid var(--sky);
  border-radius:10px; margin:14px 0; padding:0; overflow:hidden; }
.phase > details { margin:0; background:transparent; border:none; border-radius:0; padding:0; }
.phase > details > summary { cursor:pointer; padding:10px 16px; color:var(--sky);
  font-weight:700; display:flex; align-items:center; gap:10px; list-style-position:inside; }
.phase > details > summary .badges { color:var(--muted); font-weight:300; font-size:0.85em;
  margin-left:4px; }
.phase-body { padding:4px 16px 12px; }
.phase-line { color:var(--muted); font-size:0.92em; padding:8px 14px; margin:12px 0;
  background:var(--deep); border:1px solid var(--line); border-left:3px solid var(--sky);
  border-radius:8px; }
.row { display:flex; gap:10px; margin:10px 0; align-items:flex-start; }
.row .ic { flex-shrink:0; width:1.6em; text-align:center; opacity:0.85; }
.row .rw { flex:1; min-width:0; }
.row .rlabel { color:var(--text); display:flex; align-items:center; gap:8px; }
.row.err .rlabel { color:var(--yellow); }
.row .rbody { color:var(--muted); margin-top:4px; }
.reply { border-left:3px solid var(--mauve); background:rgba(194,162,241,0.05);
  border-radius:0 10px 10px 0; padding:6px 18px; margin:16px 0; }
.file-ref { background:rgba(194,162,241,0.08); border:1px solid var(--line);
  border-left:3px solid var(--mauve); border-radius:6px; padding:8px 12px; margin:8px 0;
  font-size:0.9em; }
.idx { margin:24px 0; padding:16px 20px; border-radius:10px; border:1px solid var(--line);
  border-left:3px solid var(--mauve); background:var(--surface); position:relative; }
#totop { position:fixed; right:22px; bottom:22px; width:42px; height:42px; border-radius:10px;
  background:var(--surface); border:1px solid var(--line); color:var(--muted); font-size:18px;
  cursor:pointer; opacity:0; pointer-events:none; transition:opacity .2s; z-index:9; }
#totop.show { opacity:0.3; pointer-events:auto; }
#totop:hover { opacity:1; color:var(--text); }
/* highlight.js token colours, inlined (tokyo-night-dark roles mapped onto the
   palette above) so the page needs no second external stylesheet. */
.hljs-comment, .hljs-quote { color:var(--muted); font-style:italic; }
.hljs-keyword, .hljs-selector-tag, .hljs-literal, .hljs-type { color:var(--mauve); }
.hljs-string, .hljs-attr, .hljs-addition { color:var(--green); }
.hljs-number, .hljs-symbol, .hljs-meta { color:var(--peach); }
.hljs-title, .hljs-name, .hljs-section, .hljs-built_in { color:var(--blue); }
.hljs-variable, .hljs-template-variable, .hljs-attribute { color:var(--yellow); }
.hljs-deletion { color:var(--peach); }
.hljs-emphasis { font-style:italic; } .hljs-strong { font-weight:700; }
"""


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
        '<body class="w-l f-s">',
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
    body = _md_to_html(
        fragment, allow_block_html=block.kind in ("continuation", "tool_use")
    )
    if block.kind == "tool_result":
        result_repo = detect_github_repo(block.text) or repo
        if result_repo is not None:
            body = _linkify_commits(body, block.text, result_repo)
    # A visible reply is the exporter's standout ".reply" block; everything else
    # keeps the generic block class.
    css = "reply" if block.kind == "assistant_text" else f"block block-{block.kind}"
    return _copy_block(anchors, ordinal, css, fragment, body)


_ROW_ICONS = {
    "thinking": "\N{THOUGHT BALLOON}",
    "tool_use": "\N{WRENCH}",
    "tool_result": "\N{CLIPBOARD}",
    "task_notification": "\N{BELL}",
    "stop_hook": "\N{OCTAGONAL SIGN}",
    "continuation": "\N{LINK SYMBOL}",
    "machinery": "\N{GEAR}",
    "reminder": "\N{INFORMATION SOURCE}",
    "subagent": "\N{ROBOT FACE}",
    "command": "\N{KEYBOARD}",
    "attachment": "\N{PAPERCLIP}",
    "extra": "\N{INFORMATION SOURCE}",
}
_COPY_BUTTON = '<button class="copy-md" title="Copy as Markdown">⧉</button>'
_COPY_BUTTON_SUB = '<button class="copy-md sub" title="Copy as Markdown">⧉</button>'


def _row_label(block: Block) -> str:
    """The one-line label for a phase row, from the block's own strings."""
    if block.kind == "tool_use":
        name = block.tool_name or "Tool"
        info = block.tool_input or {}
        query = _as_str(info.get("query"))
        if query:
            # The exporter renders a search query in green (.q) rather than as a
            # muted badge, because the query IS the content of that row.
            return f'{_escape(name)} <span class="q">"{_escape(query)}"</span>'
        detail = (
            _as_str(info.get("description"))
            or _as_str(info.get("file_path"))
            or _as_str(info.get("url"))
        )
        if not detail:
            return _escape(name)
        return f'{_escape(name)} <span class="badges">{_escape(detail)}</span>'
    if block.kind == "thinking":
        return _escape(_thinking_label(block))
    if block.kind == "tool_result":
        return "Result"
    # Label is the readable TYPE; the block's own content fills the row body, so
    # nothing is shown twice.
    labels = {
        "subagent": "sub-agent",
        "command": "command",
        "extra": "session event",
    }
    if block.kind == "attachment":
        return _escape(block.text.partition("\n\n")[0])
    return _escape(labels.get(block.kind, block.kind.replace("_", " ")))


def _row_icon(block: Block) -> str:
    if block.kind == "tool_use":
        if block.tool_name == "WebSearch":
            return "\N{LEFT-POINTING MAGNIFYING GLASS}"
        if block.tool_name == "WebFetch":
            return "\N{GLOBE WITH MERIDIANS}"
    return _ROW_ICONS.get(block.kind, "\N{WRENCH}")


def _phase_html(
    segment: Segment, policy: _Policy, repo: str | None, ordinal: int, anchors: _AnchorAllocator
) -> str | None:
    """One phase as a collapsible section of rows.

    The section's data-copy-src is the phase's OWN transcript.md markdown, and
    each row carries its block's fragment, so every copy button on the page
    yields text that appears verbatim in the transcript file.
    """
    meta = _phase_meta(segment.blocks)
    rows: list[str] = []
    for block in segment.blocks:
        lines = _strip_separators(_render_block(block, policy))
        if not lines:
            continue
        fragment = "\n".join(lines)
        # continuation and the untyped-tool raw toggle are disclosure blocks WE
        # author; their payloads sit inside fences, so no transcript text can
        # reach the passthrough.
        block_html_ok = block.kind in ("continuation", "tool_use")
        body = _md_to_html(fragment, allow_block_html=block_html_ok)
        if block.kind == "tool_result":
            result_repo = detect_github_repo(block.text) or repo
            if result_repo is not None:
                body = _linkify_commits(body, block.text, result_repo)
        anchor = anchors.allocate(ordinal, fragment)
        payload = base64.b64encode(fragment.encode("utf-8")).decode("ascii")
        err = " err" if block.kind == "tool_result" and _looks_failed(block.text) else ""
        rows.append(
            f'<div class="row{err}" id="{anchor}" data-copy-src="{payload}">'
            f'<span class="ic">{_row_icon(block)}</span><div class="rw">'
            f'<div class="rlabel">{_row_label(block)}{_COPY_BUTTON_SUB}</div>'
            f'<div class="rbody">{body}</div></div></div>'
        )
    head = _escape(meta.head())
    if not rows:
        return f'<div class="phase-line">{head}</div>' if policy.breadcrumbs else None
    fragment = "\n".join(_strip_separators(_phase_md(segment, policy)))
    anchor = anchors.allocate(ordinal, f"phase:{fragment}")
    payload = base64.b64encode(fragment.encode("utf-8")).decode("ascii")
    return (
        f'<div class="phase" id="{anchor}" data-copy-src="{payload}">{_details_tag(policy)}'
        f"<summary><span>{head}</span>{_COPY_BUTTON_SUB}</summary>"
        f'<div class="phase-body">{"".join(rows)}</div></details></div>'
    )


def _section_html(
    *,
    policy: _Policy,
    role: str,
    label: str,
    stamp: str,
    elapsed: str | None,
    fragment: str,
    inner: list[str],
    ordinal: int,
    anchors: _AnchorAllocator,
) -> list[str]:
    """One role section: head row plus body. `fragment` is the section's own
    transcript.md markdown, carried as the copy payload."""
    if not inner:
        return []
    section_id = anchors.allocate(ordinal, f"{role}:{ordinal}:{fragment}")
    payload = base64.b64encode(fragment.encode("utf-8")).decode("ascii")
    start = " collapsed" if policy.turns_collapsed else ""
    time_span = f'<span class="timestamp">{_escape(stamp)}</span>' if stamp else ""
    clock = f'<span class="elapsed">⏱ {_escape(elapsed)}</span>' if elapsed else ""
    return [
        f'<section class="turn {role}{start}" id="{section_id}" data-copy-src="{payload}">',
        f'<div class="turn-head"><span class="role">{label}{time_span}{clock}</span>'
        f"{_COPY_BUTTON}</div>",
        '<div class="turn-body">',
        *inner,
        "</div>",
        "</section>",
    ]


def _claude_inner(
    turn: Turn, policy: _Policy, repo: str | None, anchors: _AnchorAllocator
) -> list[str]:
    inner: list[str] = []
    for segment in group_segments(turn):
        if segment.is_phase:
            phase = _phase_html(segment, policy, repo, turn.ordinal, anchors)
            if phase is not None:
                inner.append(phase)
            continue
        block_html = _block_html(segment.blocks[0], policy, repo, turn.ordinal, anchors)
        if block_html is not None:
            inner.append(block_html)
    return inner


def _turn_html(
    turn: Turn,
    policy: _Policy,
    repo: str | None,
    anchors: _AnchorAllocator,
    total: int,
    elapsed: str | None,
) -> list[str]:
    """A turn as the SAME two role sections the markdown emits: one user section
    carrying the prompt and its reminders, one Claude section carrying the
    phases and replies. Emitting a single section here (with Claude's tool
    phases nested inside the user block) was the structural defect the operator
    caught on 2026-07-21.
    """
    if turn.synthetic:
        if not policy.include_machinery:
            return []
        return _section_html(
            policy=policy,
            role="assistant",
            label="\N{ELECTRIC PLUG} Pre-conversation",
            stamp=turn.first_ts or "",
            elapsed=None,
            fragment="\n".join(_synthetic_md(turn, policy)),
            inner=_claude_inner(turn, policy, repo, anchors),
            ordinal=turn.ordinal,
            anchors=anchors,
        )
    user_inner: list[str] = []
    if turn.prompt:
        prompt_md = _harden(turn.prompt)
        body = _md_to_html(prompt_md, allow_block_html=False)
        user_inner.append(_copy_block(anchors, turn.ordinal, "prompt", prompt_md, body))
    for reminder in turn.reminders:
        lines = _strip_separators(
            _render_reminder(reminder, policy.reminder_mode, _details_tag(policy))
        )
        if lines:
            reminder_md = "\n".join(lines)
            body = _md_to_html(reminder_md, allow_block_html=True)
            user_inner.append(
                _copy_block(anchors, turn.ordinal, "reminder", reminder_md, body)
            )
    out = _section_html(
        policy=policy,
        role="user",
        label="\N{BUST IN SILHOUETTE} User",
        stamp=turn.first_ts or "",
        elapsed=elapsed,
        fragment="\n".join(_user_md(turn, total, policy, elapsed)),
        inner=user_inner,
        ordinal=turn.ordinal,
        anchors=anchors,
    )
    claude_md = _claude_md(turn, policy)
    if claude_md:
        out.extend(
            _section_html(
                policy=policy,
                role="assistant",
                label="\N{ROBOT FACE} Claude",
                stamp=turn.last_ts or "",
                elapsed=None,
                fragment="\n".join(claude_md),
                inner=_claude_inner(turn, policy, repo, anchors),
                ordinal=turn.ordinal,
                anchors=anchors,
            )
        )
    return out


def _header_html(
    meta: ParsedSession,
    conv: Conversation,
    policy: _Policy,
    anchors: _AnchorAllocator,
    source_hash: str,
) -> str:
    """The header card: lean identity rows always visible, everything else in a
    collapsed More-details grid, with a copy button carrying the header's
    transcript.md markdown."""
    fragment = "\n".join(_strip_separators(_header(meta, policy, conv, source_hash)))
    payload = base64.b64encode(fragment.encode("utf-8")).decode("ascii")
    anchors.allocate(0, f"header:{fragment}")
    lean: list[str] = []
    for row in _lean_rows(meta, conv, policy, source_hash):
        label, _, value = row[2:].partition(":** ")
        key = _escape(label.replace("**", ""))
        css = "m-warn" if "\N{WARNING SIGN}" in row else "m-key"
        shown = _escape(value)
        if key == "Model" and value:
            shown = f'<span class="m-model">{shown}</span>'
        elif key == "Turns":
            # Colour the split the way the exporter does: you in blue, Claude
            # in peach, so the balance of the conversation reads at a glance.
            shown = re.sub(
                r"(\d+) you", r'<span class="m-you">\1 you</span>', shown, count=1
            )
            shown = re.sub(
                r"(\d+) Claude", r'<span class="m-claude">\1 Claude</span>', shown, count=1
            )
        lean.append(f'<span class="{css}">{key}</span>: {shown}')
    if policy.variant_note:
        lean.append(_compact_meta_note(policy))
    grid: list[str] = []
    for row in _detail_rows(meta, conv, policy):
        label, _, value = row[2:].partition(":** ")
        key = _escape(label.replace("**", ""))
        if key == "Summary":
            # Full-width italic row, the exporter's .full treatment.
            grid.append(f'<span class="full">{_escape(value.strip("*"))}</span>')
            continue
        grid.append(f'<span class="k">{key}</span><span class="v">{_escape(value)}</span>')
    return (
        f'<div class="meta" data-copy-src="{payload}">{_COPY_BUTTON}'
        + "<br>".join(lean)
        + f'<div class="more">{_details_tag(policy)}<summary>More details</summary>'
        f'<div class="more-grid">{"".join(grid)}</div></details></div></div>'
    )


def _files_index_html(conv: Conversation, anchors: _AnchorAllocator) -> str | None:
    files = _file_targets(conv)
    if not files:
        return None
    fragment = "\n".join(_strip_separators(_files_index_md(conv)[1:]))
    payload = base64.b64encode(fragment.encode("utf-8")).decode("ascii")
    anchor = anchors.allocate(0, f"files:{fragment}")
    items = "".join(
        f"<li><code>{_escape(path)}</code> <span class='badges'>({verb})</span></li>"
        for path, verb in files
    )
    return (
        f'<div class="idx" id="{anchor}" data-copy-src="{payload}">'
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">'
        f"<strong>\N{BOOKMARK TABS} Files Index</strong>{_COPY_BUTTON}</div>"
        f"<ol>{items}</ol></div>"
    )


def _render_page(
    conv: Conversation,
    meta: ParsedSession,
    policy: _Policy,
    repo: str | None,
    source_hash: str,
    options: RenderOptions,
) -> str:
    anchors = _AnchorAllocator()
    whole = _render(conv, meta, policy, source_hash)
    whole_payload = base64.b64encode(whole.encode("utf-8")).decode("ascii")
    parts = _document_head(_title(meta))
    parts.append(f'<div id="whole-transcript" hidden data-copy-src="{whole_payload}"></div>')
    variant = ' <span class="badges">(compact)</span>' if policy.variant_note else ""
    parts.append(f"<h1>{_escape(_title(meta))}{variant}</h1>")
    parts.append(_header_html(meta, conv, policy, anchors, source_hash))
    parts.append(_TOOLBAR)
    parts.append('<main class="transcript">')
    labels = _elapsed_labels(conv)
    for turn, elapsed in zip(conv.turns, labels, strict=True):
        parts.extend(
            _turn_html(turn, policy, repo, anchors, conv.prompt_count, elapsed)
        )
    index = _files_index_html(conv, anchors)
    if index is not None:
        parts.append(index)
    tail = [_hljs_block(options.hljs), _copy_script(options), _date_block(options)]
    parts.extend(["</main>", *[piece for piece in tail if piece], "</body>", "</html>"])
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
    source_hash = sha256_hex(data)
    full = _render_page(conv, meta, _full_policy(options), repo, source_hash, options)
    compact = _render_page(conv, meta, _compact_policy(options), repo, source_hash, options)
    return full, compact


def _truncation_loss(conv: Conversation, options: RenderOptions) -> tuple[int, int]:
    """(blocks cut, characters omitted) for one session at this cap.

    Counts each tool-result BLOCK once, not once per file. The cap is
    variant-agnostic, so a block cut in transcript.md is cut identically in
    transcript.compact.md when the matrix opened tool output there; counting per
    variant would double-report the same loss.

    Walks the same payloads the renderer cuts, through the same two helpers, so
    the number in the manifest and the marker on the page cannot disagree.
    """
    cap = options.tool_output_max_chars
    if cap <= 0:
        return 0, 0
    structured = options.toolresult_diff or options.tool_output_compact
    blocks = 0
    chars = 0
    for turn in conv.turns:
        for block in turn.blocks:
            if block.kind != "tool_result":
                continue
            omitted = sum(
                _truncate(payload, cap)[1]
                for payload in _result_payloads(block, structured)
            )
            if omitted:
                blocks += 1
                chars += omitted
    return blocks, chars


def build_manifest(data: bytes, options: RenderOptions) -> dict[str, object]:
    """Per-session render manifest: source hash, counts, loss telemetry, config.

    Frozen keys (DESIGN section 6): source_hash (the payload's sha256),
    counts.prompts / counts.tool_calls, loss (a malformed line is loss, never a
    silent drop, F6), and config (the RenderOptions used).

    The `loss` key set was AMENDED 2026-08-01 (DESIGN 15 entry, block 3) from
    skipped_lines alone to skipped_lines + truncated_blocks + truncated_chars,
    so that an opt-in cap is telemetry rather than a quiet subtraction. Both new
    counts are 0 whenever the cap is off, which is the default.
    """
    conv = build_conversation(data)
    truncated_blocks, truncated_chars = _truncation_loss(conv, options)
    manifest: dict[str, object] = {
        "source_hash": sha256_hex(data),
        "counts": {"prompts": conv.prompt_count, "tool_calls": conv.tool_call_count},
        "loss": {
            "skipped_lines": conv.skipped_lines,
            "truncated_blocks": truncated_blocks,
            "truncated_chars": truncated_chars,
        },
        "config": asdict(options),
    }
    return manifest
