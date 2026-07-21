"""Session payload parsing: metadata extraction, summary, commit/repo detection.

Slice 3. SPEC section 6 (KEEP/CHANGE verdicts), DESIGN section 4 (parse ONCE).
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

# SPEC 6: commit output from a tool_result string, `[branch sha] message`. The
# `(?:\n|$)` terminator is load-bearing: without it the lazy message group
# would match only one character.
_COMMIT_PATTERN = re.compile(r"\[[\w\-/]+ ([a-f0-9]{7,})\] (.+?)(?:\n|$)")

# SPEC 6: repo auto-detected from `git push` pull/new output.
_GITHUB_REPO_PATTERN = re.compile(r"github\.com/([a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+)/pull/new/")

# SPEC 8: summary cap.
_SUMMARY_MAX_LEN = 200


@dataclass(frozen=True)
class Commit:
    sha: str
    message: str
    timestamp: str | None


@dataclass(frozen=True)
class ParsedSession:
    session_uuid: str | None
    cwd: str | None
    slug: str | None
    git_branch: str | None
    version: str | None
    first_ts: str | None
    last_ts: str | None
    line_count: int
    skipped_lines: int
    summary: str
    hidden: bool
    # The assistant model that answered, from the first entry carrying
    # `message.model`. Optional: older payloads and user-only sessions have
    # none, and the emitters simply omit the field then.
    model: str | None = None


def _as_nonempty_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _entries_from_jsonl(text: str) -> tuple[list[dict[str, object]], int]:
    """Parse raw JSONL text into entry dicts.

    Blank lines carry no data and are neither entries nor errors. A line that
    fails to parse as JSON, or parses but is not an object, yields no entry
    and is counted as skipped (F6): every non-blank line maps to exactly one
    of {usable entry, skipped}. Pathologically deep nesting can overflow the
    interpreter stack (RecursionError) rather than raise JSONDecodeError; that
    is also unparseable-as-an-entry and counted as skipped, never left to
    crash the parser.
    """
    entries: list[dict[str, object]] = []
    skipped = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, RecursionError):
            skipped += 1
            continue
        if isinstance(obj, dict):
            entries.append(cast(dict[str, object], obj))
        else:
            skipped += 1
    return entries, skipped


def _entries_from_loglines(raw_entries: list[object]) -> tuple[list[dict[str, object]], int]:
    """Treat a `loglines` array like JSONL lines: each item is one logical line."""
    entries: list[dict[str, object]] = []
    skipped = 0
    for item in raw_entries:
        if isinstance(item, dict):
            entries.append(cast(dict[str, object], item))
        else:
            skipped += 1
    return entries, skipped


def _summary_candidate(entries: list[dict[str, object]]) -> str | None:
    """SPEC 8 priority: first `type: summary` line's summary field; else the
    first non-meta user message whose text does not start with '<' (task
    notifications and command output are machine text, never summaries)."""
    for entry in entries:
        if entry.get("type") == "summary":
            summary = _as_nonempty_str(entry.get("summary"))
            if summary is not None and summary.strip():
                return summary
    for entry in entries:
        if entry.get("type") != "user" or entry.get("isMeta") is True:
            continue
        message = entry.get("message")
        content: object = None
        if isinstance(message, dict):
            content = cast(dict[str, object], message).get("content")
        text = extract_text(content)
        if text and not text.startswith("<"):
            return text
    return None


def _extract_entries(data: bytes) -> tuple[list[dict[str, object]], int, int]:
    """Route a raw payload to (entries, line_count, skipped_lines).

    Shared by parse_session and build_conversation so the JSONL-vs-loglines
    routing has one implementation (R9): a whole-payload JSON object carrying a
    `loglines` key is parsed like JSONL over that list; ordinary JSONL routes to
    the line-by-line path because the payload as a whole does not parse as a
    single JSON object with that key (a one-line JSONL entry that itself carries
    a top-level `loglines` field is a theoretical exception to this routing).
    Malformed lines are counted (skipped_lines), never silently dropped (F6).
    """
    # utf-8-sig strips a leading UTF-8 BOM if present (and behaves exactly
    # like utf-8 otherwise), so a BOM never knocks the routing check below off
    # course (F6).
    text = data.decode("utf-8-sig", errors="replace")
    stripped = text.strip()

    whole: object | None = None
    if stripped.startswith("{"):
        try:
            whole = json.loads(text)
        except (json.JSONDecodeError, RecursionError):
            whole = None

    if isinstance(whole, dict) and "loglines" in whole:
        whole_dict = cast(dict[str, object], whole)
        raw_loglines = whole_dict["loglines"]
        if isinstance(raw_loglines, list):
            raw_entries = cast(list[object], raw_loglines)
            entries, skipped_lines = _entries_from_loglines(raw_entries)
            return entries, len(raw_entries), skipped_lines
        # Present but not a list: a malformed payload, not an empty one. Counted
        # so it is never indistinguishable from a genuinely empty session (F6).
        return [], 1, 1

    entries, skipped_lines = _entries_from_jsonl(text)
    return entries, len(text.splitlines()), skipped_lines


def parse_session(data: bytes) -> ParsedSession:
    """Parse a raw session payload: JSONL, or JSON with a `loglines` key.

    Malformed lines are counted (skipped_lines), never silently dropped: the
    parseable lines are still parsed even when others fail (F6).
    """
    entries, line_count, skipped_lines = _extract_entries(data)

    session_uuid: str | None = None
    cwd: str | None = None
    slug: str | None = None
    git_branch: str | None = None
    version: str | None = None
    first_ts: str | None = None
    last_ts: str | None = None
    model: str | None = None

    for entry in entries:
        session_uuid = session_uuid or _as_nonempty_str(entry.get("sessionId"))
        cwd = cwd or _as_nonempty_str(entry.get("cwd"))
        slug = slug or _as_nonempty_str(entry.get("slug"))
        git_branch = git_branch or _as_nonempty_str(entry.get("gitBranch"))
        version = version or _as_nonempty_str(entry.get("version"))
        if model is None:
            message = entry.get("message")
            if isinstance(message, dict):
                model = _as_nonempty_str(cast(dict[str, object], message).get("model"))
        ts = _as_nonempty_str(entry.get("timestamp"))
        if ts is not None:
            if first_ts is None:
                first_ts = ts
            last_ts = ts

    candidate = _summary_candidate(entries)
    if candidate is None:
        summary = "(no summary)"
        hidden = True
    else:
        trimmed = candidate.strip()
        if len(trimmed) > _SUMMARY_MAX_LEN:
            summary = trimmed[: _SUMMARY_MAX_LEN - 3] + "..."
        else:
            summary = trimmed
        hidden = trimmed.lower() == "warmup"

    return ParsedSession(
        session_uuid=session_uuid,
        cwd=cwd,
        slug=slug,
        git_branch=git_branch,
        version=version,
        first_ts=first_ts,
        last_ts=last_ts,
        line_count=line_count,
        skipped_lines=skipped_lines,
        summary=summary,
        hidden=hidden,
        model=model,
    )


def extract_text(content: object) -> str:
    """Text from a message content field: plain string or block array (text blocks only)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts: list[str] = []
        for block in cast(list[object], content):
            if isinstance(block, dict):
                block_dict = cast(dict[str, object], block)
                if block_dict.get("type") == "text":
                    block_text = block_dict.get("text")
                    if isinstance(block_text, str) and block_text:
                        texts.append(block_text)
        return " ".join(texts).strip()
    return ""


def detect_commits(text: str) -> list[Commit]:
    """Commits mentioned in tool_result text. No timestamp source here, so
    Commit.timestamp is always None."""
    return [
        Commit(sha=match.group(1), message=match.group(2), timestamp=None)
        for match in _COMMIT_PATTERN.finditer(text)
    ]


def detect_github_repo(text: str) -> str | None:
    """The first `<owner>/<repo>` found in a `github.com/.../pull/new/` URL, else None."""
    match = _GITHUB_REPO_PATTERN.search(text)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Normalized conversation model (DESIGN section 6: one model feeds every
# emitter -- transcript.md/compact and, later, the HTML pages -- so rendering
# logic is not duplicated across variants, F8/R9). SPEC section 6/7 KEEP
# semantics decide what starts a turn and what is machinery.
# ---------------------------------------------------------------------------

# SPEC 6: a system-reminder is embedded inside the visible prompt string; it is
# split out here so the visible prompt survives in every variant while the
# reminder is folded or stripped per policy at render time (DESIGN section 6).
_REMINDER_PATTERN = re.compile(r"<system-reminder>(.*?)</system-reminder>", re.DOTALL)
# SPEC 6: task-notification entries are machinery, never conversation starters.
_TASK_NOTIFICATION_PATTERN = re.compile(
    r"<task-notification>(.*?)</task-notification>", re.DOTALL
)
# SPEC 6: prompts opening with this marker are excluded from turn-starts.
_STOP_HOOK_PREFIX = "Stop hook feedback:"


@dataclass(frozen=True)
class Block:
    """One typed unit inside a turn.

    `kind` is one of: thinking, assistant_text, tool_use, tool_result,
    task_notification, stop_hook, continuation, machinery, reminder. `text`
    carries the primary content; tool_name/tool_input carry a tool call's typed
    payload (both None for non-tool blocks).
    """

    kind: str
    text: str
    tool_name: str | None = None
    tool_input: Mapping[str, object] | None = None


@dataclass(frozen=True)
class Turn:
    """A conversation turn: one visible user prompt and the blocks that follow it
    until the next prompt.

    `reminders` holds any system-reminders split out of the prompt string.
    `synthetic` marks the holder for entries that precede the first real prompt
    so they are kept, not silently dropped (SPEC 6 CHANGE, F6); a synthetic turn
    has an empty prompt and is not counted as a prompt.

    `first_ts`/`last_ts` are the timestamps of the first and last source entries
    that fed this turn, or None when the entries carried none. They exist so the
    emitters can show a turn's clock time and the elapsed gap since the previous
    turn (DESIGN section 6 elapsed times); nothing in the model derives meaning
    from them, so a transcript whose entries carry no timestamp just omits those
    labels.
    """

    ordinal: int
    prompt: str
    reminders: tuple[str, ...]
    blocks: tuple[Block, ...]
    synthetic: bool = False
    first_ts: str | None = None
    last_ts: str | None = None


@dataclass(frozen=True)
class Conversation:
    turns: tuple[Turn, ...]
    prompt_count: int
    tool_call_count: int
    skipped_lines: int


@dataclass(frozen=True)
class Segment:
    """One stretch of a turn: either a single visible reply, or a PHASE.

    DESIGN section 6 has the parser produce "turns, phases, blocks". A phase is
    a run of consecutive non-reply blocks (thinking, tool calls, tool results,
    machinery) that the emitters fold into one collapsible unit; a reply block
    (`assistant_text`) ends the run and stands on its own. `is_phase` picks
    which: False means exactly one reply block, True means one or more grouped
    blocks. Grouping is presentation-neutral -- it reorders nothing and drops
    nothing, so the flat `Turn.blocks` sequence stays the source of truth.
    """

    is_phase: bool
    blocks: tuple[Block, ...]


def group_segments(turn: Turn) -> tuple[Segment, ...]:
    """Split a turn's blocks into reply segments and phase segments.

    A run of consecutive non-`assistant_text` blocks becomes one phase segment;
    each `assistant_text` block becomes its own reply segment and breaks the
    run. Concatenating every segment's blocks in order reproduces `turn.blocks`
    exactly, which is what makes the grouping safe to apply in one emitter and
    not another.
    """
    segments: list[Segment] = []
    run: list[Block] = []
    for block in turn.blocks:
        if block.kind == "assistant_text":
            if run:
                segments.append(Segment(is_phase=True, blocks=tuple(run)))
                run = []
            segments.append(Segment(is_phase=False, blocks=(block,)))
            continue
        run.append(block)
    if run:
        segments.append(Segment(is_phase=True, blocks=tuple(run)))
    return tuple(segments)


def split_reminder(text: str) -> tuple[str, tuple[str, ...]]:
    """Split embedded <system-reminder> blocks out of a prompt string.

    Returns (visible text, reminders). The visible prompt is what survives in
    both variants; the reminders are folded or stripped per policy (DESIGN
    section 6). Empty reminders are discarded.
    """
    reminders = tuple(
        inner
        for match in _REMINDER_PATTERN.finditer(text)
        if (inner := match.group(1).strip())
    )
    visible = _REMINDER_PATTERN.sub("", text).strip()
    return visible, reminders


def _message_content(entry: dict[str, object]) -> object:
    message = entry.get("message")
    if isinstance(message, dict):
        return cast(dict[str, object], message).get("content")
    return None


def _tool_result_text(block: dict[str, object]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    return extract_text(content)


def _assistant_blocks(content: object) -> list[Block]:
    """Blocks from an assistant message: thinking, text, and typed tool calls."""
    out: list[Block] = []
    if isinstance(content, str):
        if content.strip():
            out.append(Block("assistant_text", content.strip()))
        return out
    if not isinstance(content, list):
        return out
    for raw in cast(list[object], content):
        if not isinstance(raw, dict):
            continue
        block = cast(dict[str, object], raw)
        block_type = block.get("type")
        if block_type == "thinking":
            thinking = block.get("thinking")
            if isinstance(thinking, str) and thinking.strip():
                out.append(Block("thinking", thinking.strip()))
        elif block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                out.append(Block("assistant_text", text.strip()))
        elif block_type == "tool_use":
            name = block.get("name")
            tool_input = block.get("input")
            out.append(
                Block(
                    "tool_use",
                    "",
                    tool_name=name if isinstance(name, str) else None,
                    tool_input=cast("Mapping[str, object]", tool_input)
                    if isinstance(tool_input, dict)
                    else None,
                )
            )
    return out


def _user_list_blocks(content: list[object]) -> list[Block]:
    """Blocks from a user message whose content is a block array: tool results
    (machinery replies) and any embedded text blocks."""
    out: list[Block] = []
    for raw in content:
        if not isinstance(raw, dict):
            continue
        block = cast(dict[str, object], raw)
        block_type = block.get("type")
        if block_type == "tool_result":
            out.append(Block("tool_result", _tool_result_text(block)))
        elif block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                out.append(Block("assistant_text", text.strip()))
    return out


def build_conversation(data: bytes) -> Conversation:
    """Normalized conversation model shared by every emitter (DESIGN section 6).

    A user message with visible text starts a turn UNLESS it is a whole-message
    task-notification, a Stop-hook-feedback prompt, an isMeta entry, or has no
    visible text; those are machinery kept in the open turn, never turn starters
    (SPEC 6). isCompactSummary marks a continuation merged into the open turn,
    not a new turn. Assistant blocks (thinking, text, typed tool calls) and user
    tool_result blocks append to the open turn. Entries before the first real
    prompt are kept in a synthetic turn rather than silently dropped (SPEC 6
    CHANGE, F6).

    Scope is the conversation only: non-conversation entries (e.g. type
    "summary"/"system") and user messages whose content is neither a string nor
    a block array are session metadata owned by parse_session, not part of this
    model.
    """
    entries, _line_count, skipped_lines = _extract_entries(data)

    turns: list[Turn] = []
    ordinal = 0
    prompt = ""
    reminders: tuple[str, ...] = ()
    blocks: list[Block] = []
    started = False
    first_ts: str | None = None
    last_ts: str | None = None

    def flush() -> None:
        nonlocal blocks, first_ts, last_ts
        if started or blocks:
            turns.append(
                Turn(
                    ordinal=ordinal,
                    prompt=prompt,
                    reminders=reminders,
                    blocks=tuple(blocks),
                    synthetic=not started,
                    first_ts=first_ts,
                    last_ts=last_ts,
                )
            )
        blocks = []
        first_ts = None
        last_ts = None

    for entry in entries:
        kind = entry.get("type")
        content = _message_content(entry)
        stamp = _as_nonempty_str(entry.get("timestamp"))
        if stamp is not None:
            # The turn spans every entry that fed it; a prompt entry sets the
            # opening stamp below, after flush() has closed the previous turn.
            if first_ts is None:
                first_ts = stamp
            last_ts = stamp

        if kind == "assistant":
            blocks.extend(_assistant_blocks(content))
            continue
        if kind != "user":
            continue

        if entry.get("isCompactSummary") is True:
            blocks.append(Block("continuation", extract_text(content)))
            continue
        if isinstance(content, list):
            blocks.extend(_user_list_blocks(cast(list[object], content)))
            continue
        if not isinstance(content, str):
            continue

        visible, entry_reminders = split_reminder(content)
        if content.strip().startswith("<task-notification>"):
            # A WHOLE-message task-notification is machinery, never a turn
            # starter (SPEC 6). A real prompt that merely MENTIONS the tag is
            # not demoted: it falls through and starts a turn below.
            notification = _TASK_NOTIFICATION_PATTERN.search(content)
            inner = notification.group(1).strip() if notification is not None else visible
            blocks.append(Block("task_notification", inner))
            continue
        if visible.startswith(_STOP_HOOK_PREFIX):
            blocks.append(Block("stop_hook", visible))
            continue
        if entry.get("isMeta") is True or not visible:
            # Machinery text with no conversational role: kept, never a turn
            # starter, never silently dropped (F6).
            if visible:
                blocks.append(Block("machinery", visible))
            blocks.extend(Block("reminder", reminder) for reminder in entry_reminders)
            continue

        # A real prompt closes the open turn and starts a new one. A visible
        # prompt opening with "<" (e.g. "<div> help") is a real prompt: the
        # "<"-prefix rule is SPEC-8 summary logic, not SPEC-6 turn grouping.
        flush()
        ordinal += 1
        prompt = visible
        reminders = entry_reminders
        started = True
        # flush() cleared the span; this prompt entry opens the new turn's.
        first_ts = stamp
        last_ts = stamp

    flush()

    prompt_count = sum(1 for turn in turns if not turn.synthetic)
    tool_call_count = sum(
        1 for turn in turns for block in turn.blocks if block.kind == "tool_use"
    )
    return Conversation(
        turns=tuple(turns),
        prompt_count=prompt_count,
        tool_call_count=tool_call_count,
        skipped_lines=skipped_lines,
    )
