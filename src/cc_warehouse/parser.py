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
    # Lone surrogates replaced with U+FFFD so the projection can be written at
    # all (2026-08-01 ruling). Loss telemetry, never a silent substitution (F6).
    unencodable_chars: int
    summary: str
    hidden: bool
    # The assistant model that answered, from the first entry carrying
    # `message.model`. Optional: older payloads and user-only sessions have
    # none, and the emitters simply omit the field then.
    model: str | None = None
    # Claude Code's own human-readable session title, from a `type: "ai-title"`
    # entry's `aiTitle` field. Present in most recent sessions; the render title
    # prefers it over the summary-derived fallback (principal ruling 2026-07-23,
    # SPEC 8 title source extended). None when the session predates the field.
    ai_title: str | None = None
    # The title the OPERATOR set, from a `type: "custom-title"` entry's
    # `customTitle` field. It outranks ai_title, which the model generated: a
    # name a person chose beats a name a model invented (ticket 18, principal
    # ruling 2026-08-02). Measured: 910 custom-title ENTRIES across just 26
    # sessions, because each rename appends another entry, so last-wins below
    # is what makes the field mean the CURRENT name.
    custom_title: str | None = None


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


# U+FFFD, what the Unicode standard defines for a character that cannot be
# represented. Used for LONE SURROGATES, which arrive when Claude Code truncates
# a field mid-emoji and leaves half a surrogate pair behind: json.loads decodes
# that escape into a legal Python str with no utf-8 encoding at all, so the
# render succeeds and the WRITE fails. Found on real data 2026-08-01 (9 of
# 13,608 sessions; 11 of 13,836 stored objects).
#
# The character was already destroyed upstream, so this represents something
# broken rather than discarding something whole - but the count still travels to
# the manifest's `loss` block, because a projection that quietly substituted
# characters is exactly F6. The stored payload keeps the original bytes.
_REPLACEMENT = "\ufffd"


def _scrub_surrogates(value: object) -> tuple[object, int]:
    """Replace lone surrogates anywhere in a decoded JSON value.

    Returns (scrubbed, replaced count). Walks the decoded object rather than the
    raw text so that a WELL-FORMED astral character, which reaches json.loads as
    a proper surrogate PAIR and decodes to one legal character, is never touched.
    """
    if isinstance(value, str):
        if not any("\ud800" <= char <= "\udfff" for char in value):
            return value, 0
        out: list[str] = []
        count = 0
        for char in value:
            if "\ud800" <= char <= "\udfff":
                out.append(_REPLACEMENT)
                count += 1
            else:
                out.append(char)
        return "".join(out), count
    if isinstance(value, dict):
        scrubbed: dict[str, object] = {}
        total = 0
        for key, item in cast(dict[str, object], value).items():
            new_item, n = _scrub_surrogates(item)
            scrubbed[key] = new_item
            total += n
        return scrubbed, total
    if isinstance(value, list):
        items: list[object] = []
        total = 0
        for item in cast(list[object], value):
            new_item, n = _scrub_surrogates(item)
            items.append(new_item)
            total += n
        return items, total
    return value, 0


def _extract_entries(data: bytes) -> tuple[list[dict[str, object]], int, int, int]:
    """Route a raw payload to (entries, line_count, skipped_lines, unencodable).

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
            entries, unencodable = _scrubbed_entries(entries)
            return entries, len(raw_entries), skipped_lines, unencodable
        # Present but not a list: a malformed payload, not an empty one. Counted
        # so it is never indistinguishable from a genuinely empty session (F6).
        return [], 1, 1, 0

    entries, skipped_lines = _entries_from_jsonl(text)
    entries, unencodable = _scrubbed_entries(entries)
    return entries, len(text.splitlines()), skipped_lines, unencodable


def _scrubbed_entries(
    entries: list[dict[str, object]],
) -> tuple[list[dict[str, object]], int]:
    """Scrub every entry, summing what was replaced. One call site per routing
    branch, so both parse_session and build_conversation inherit it (R9)."""
    out: list[dict[str, object]] = []
    total = 0
    for item in entries:
        scrubbed, count = _scrub_surrogates(item)
        out.append(cast(dict[str, object], scrubbed))
        total += count
    return out, total


def parse_session(data: bytes) -> ParsedSession:
    """Parse a raw session payload: JSONL, or JSON with a `loglines` key.

    Malformed lines are counted (skipped_lines), never silently dropped: the
    parseable lines are still parsed even when others fail (F6).
    """
    entries, line_count, skipped_lines, unencodable = _extract_entries(data)

    session_uuid: str | None = None
    cwd: str | None = None
    slug: str | None = None
    git_branch: str | None = None
    version: str | None = None
    first_ts: str | None = None
    last_ts: str | None = None
    model: str | None = None
    ai_title: str | None = None
    custom_title: str | None = None

    for entry in entries:
        session_uuid = session_uuid or _as_nonempty_str(entry.get("sessionId"))
        cwd = cwd or _as_nonempty_str(entry.get("cwd"))
        slug = slug or _as_nonempty_str(entry.get("slug"))
        git_branch = git_branch or _as_nonempty_str(entry.get("gitBranch"))
        version = version or _as_nonempty_str(entry.get("version"))
        # A later ai-title supersedes an earlier one (the title is regenerated as
        # the conversation grows); keep the last, not the first.
        if entry.get("type") == "ai-title":
            title = _as_nonempty_str(entry.get("aiTitle"))
            if title is not None:
                ai_title = title
        # Same last-wins rule: an operator who renames a session twice meant the
        # second name.
        if entry.get("type") == "custom-title":
            chosen = _as_nonempty_str(entry.get("customTitle"))
            if chosen is not None:
                custom_title = chosen
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
        unencodable_chars=unencodable,
        summary=summary,
        hidden=hidden,
        model=model,
        ai_title=ai_title,
        custom_title=custom_title,
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

# ---------------------------------------------------------------------------
# The entry types this parser NAMES, grouped by what it does with each.
#
# Ticket 18 (principal ruling 2026-08-02, option 4). A field census of all
# 13,836 stored objects found eight entry types and three content-block types
# that rendered NOTHING and incremented NO counter: 62,577 entries dropped with
# `loss: 0` recorded beside them, which is silent loss by FINDINGS F6's own
# definition and a gap against DESIGN section 6's "the model now surfaces the
# rest". The rule adopted is: everything named here is surfaced, and anything
# NOT named here is surfaced as a marker AND counted into the manifest's
# top-level `unrecognised` block. `unrecognised` deliberately sits OUTSIDE the
# frozen `loss` key set, because an entry that rendered a marker was not lost,
# and filing it as loss would be F6 pointing the other way.
#
# The ROOT CAUSE these sets exist to fix: the previous census ran once, on
# 2026-07-23, and `frame-link` first appears 2026-07-03 with `file-history-delta`
# on 2026-07-14. A one-time census of a living format goes stale by
# construction. tests/test_real_shapes.py reads these sets off this source with
# an AST fence, so the fence cannot rot separately from the dispatch it fences;
# the `_ENTRY_TYPES` suffix is what that fence matches on, which is why the
# block-level sets below are named `_BLOCK_KINDS` instead.
# ---------------------------------------------------------------------------

# Carry the conversation itself; each has its own branch in build_conversation.
_CONVERSATION_ENTRY_TYPES = frozenset({"user", "assistant", "attachment", "system"})
# Informational, surfaced verbatim as `extra` blocks (principal ruling 2026-07-23).
_EXTRA_ENTRY_TYPES = frozenset(
    {"bridge-session", "queue-operation", "last-prompt", "agent-name"}
)
# Session METADATA owned by parse_session (title and summary sources), so
# build_conversation names them and deliberately emits nothing.
_METADATA_ENTRY_TYPES = frozenset({"summary", "ai-title", "custom-title"})
# Machinery: real, but not conversation. One compact marker each, exactly as
# `attachment`'s machinery kinds already do.
_MACHINERY_ENTRY_TYPES = frozenset(
    {"permission-mode", "mode", "file-history-snapshot", "file-history-delta", "started"}
)
# A sub-agent's RETURNED WORK. Measured at mean 2,234 bytes and max 6,908 across
# 173 real entries, so a one-line marker would bury a deliverable; it renders as
# its own block under the sub-agent phase.
_AGENT_RESULT_ENTRY_TYPES = frozenset({"result"})
# An artifact the session produced: a title plus the URL it lives at.
_LINK_ENTRY_TYPES = frozenset({"frame-link"})

KNOWN_ENTRY_TYPES = (
    _CONVERSATION_ENTRY_TYPES
    | _EXTRA_ENTRY_TYPES
    | _METADATA_ENTRY_TYPES
    | _MACHINERY_ENTRY_TYPES
    | _AGENT_RESULT_ENTRY_TYPES
    | _LINK_ENTRY_TYPES
)

# Content-block kinds inside message.content. `image` and `document` wrap a
# base64 `source`; `fallback` records a model swap mid-reply.
_MEDIA_BLOCK_KINDS = frozenset({"image", "document"})


@dataclass(frozen=True)
class Block:
    """One typed unit inside a turn.

    `kind` is one of: thinking, assistant_text, tool_use, tool_result,
    task_notification, stop_hook, continuation, machinery, reminder, subagent,
    agent_result, command, attachment, extra. `text` carries the primary content;
    tool_name/tool_input carry a tool call's typed payload (both None for
    non-tool blocks).
    """

    kind: str
    text: str
    tool_name: str | None = None
    tool_input: Mapping[str, object] | None = None
    # A tool_result's structured payload (`toolUseResult`): stdout/stderr,
    # `interrupted`, and `structuredPatch` for Edit diffs. None when the source
    # entry carried none.
    result: Mapping[str, object] | None = None
    # The sub-agent that produced a `subagent` block (`isSidechain` entries'
    # `agentId`), so a run of them folds under one labelled phase.
    agent_id: str | None = None


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
    unencodable_chars: int = 0
    # Entry and content-block type names the parser does not name, sorted and
    # de-duplicated, with the total number of occurrences (ticket 18). Each one
    # still RENDERED a marker, so this is not loss telemetry: it is the tripwire
    # that says Claude Code's format moved. `()` / 0 for every session in the
    # 2026-08-02 corpus, by construction.
    unrecognised: tuple[str, ...] = ()
    unrecognised_count: int = 0


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


_PHASE_CATEGORY = {
    "subagent": "subagent",
    # A `result` entry is the same sub-agent's returned work, so it folds into
    # the sub-agent phase rather than opening one of its own.
    "agent_result": "subagent",
    "command": "command",
    "attachment": "attachment",
    "extra": "extra",
}


def _segment_category(block: Block) -> str:
    """Which phase a block belongs to. Sub-agents, commands, attachments and the
    informational extras each get their OWN phase, so a sub-agent review is not
    jumbled in with the main tool calls (principal ruling 2026-07-23). Everything
    else (thinking, tools, machinery) is one 'research' category."""
    return _PHASE_CATEGORY.get(block.kind, "research")


def group_segments(turn: Turn) -> tuple[Segment, ...]:
    """Split a turn's blocks into reply segments and phase segments.

    Each `assistant_text` block is its own reply segment. Every other block joins
    a phase, but a phase breaks when the CATEGORY changes, so a run of sub-agent
    steps, a run of attachments, and a run of tool calls each fold separately.
    Concatenating every segment's blocks in order reproduces `turn.blocks`
    exactly, which is what makes the grouping safe to apply in one emitter and
    not another.
    """
    segments: list[Segment] = []
    run: list[Block] = []
    run_cat: str | None = None

    def flush_run() -> None:
        nonlocal run, run_cat
        if run:
            segments.append(Segment(is_phase=True, blocks=tuple(run)))
            run = []
            run_cat = None

    for block in turn.blocks:
        if block.kind == "assistant_text":
            flush_run()
            segments.append(Segment(is_phase=False, blocks=(block,)))
            continue
        category = _segment_category(block)
        if run and category != run_cat:
            flush_run()
        run.append(block)
        run_cat = category
    flush_run()
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


def _assistant_blocks(content: object, unknown: list[str]) -> list[Block]:
    """Blocks from an assistant message: thinking, text, and typed tool calls.

    `unknown` collects the names of block types this function does not handle,
    so a type Claude Code adds later is counted rather than dropped (ticket 18).
    """
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
        elif block_type == "fallback":
            # One real case: the reply switched models mid-flight. Machinery,
            # but machinery that explains why a transcript changes voice.
            out.append(Block("machinery", _fallback_text(block)))
        elif block_type in _MEDIA_BLOCK_KINDS:
            out.append(_media_block(block))
        else:
            out.append(_unknown_block(block, unknown))
    return out


def _fallback_text(block: dict[str, object]) -> str:
    """`{"type": "fallback", "from": {"model": ...}, "to": {"model": ...}}`."""

    def model_of(key: str) -> str:
        value = block.get(key)
        if isinstance(value, dict):
            return _as_nonempty_str(cast(dict[str, object], value).get("model")) or "?"
        return "?"

    return f"model fallback: {model_of('from')} -> {model_of('to')}"


def _media_block(block: dict[str, object]) -> Block:
    """An `image` or `document` content block as an attachment marker.

    The base64 `source.data` is NEVER inlined. The corpus' largest single object
    is 114,154,804 bytes and 97% of it is block content; a projection that
    embedded such a payload would be neither readable nor writable. The media
    type and the decoded size are what a reader can actually act on.
    """
    kind = _as_nonempty_str(block.get("type")) or "media"
    media_type = ""
    decoded = 0
    source = block.get("source")
    if isinstance(source, dict):
        src = cast(dict[str, object], source)
        media_type = _as_nonempty_str(src.get("media_type")) or ""
        data = src.get("data")
        if isinstance(data, str):
            # base64 encodes 3 bytes per 4 characters; padding makes this an
            # upper bound off by at most two bytes, which is honest at this
            # resolution and needs no decode of a multi-megabyte string.
            decoded = len(data) * 3 // 4
    detail = " \N{MIDDLE DOT} ".join(
        part for part in (media_type, f"{decoded:,} bytes" if decoded else "") if part
    )
    return Block("attachment", f"attachment ({kind})" + (f": {detail}" if detail else ""))


def _unknown_block(block: dict[str, object], unknown: list[str]) -> Block:
    """A content block whose `type` the parser does not name: surfaced as a
    marker and recorded, never dropped (ticket 18 tripwire)."""
    name = _as_nonempty_str(block.get("type")) or "(untyped)"
    unknown.append(f"block:{name}")
    return Block("machinery", f"block:{name}")


def _user_list_blocks(
    content: list[object],
    unknown: list[str],
    result: Mapping[str, object] | None = None,
) -> list[Block]:
    """Blocks from a user message whose content is a block array: tool results
    (machinery replies) and any embedded text blocks. `result` is the entry's
    `toolUseResult`, attached to the tool_result block so the emitter can render
    a structured diff or stdout/stderr rather than only the text (item 5).

    Before ticket 18 this returned an empty list for a message whose blocks were
    all `image` or `document`, and an empty list meant the WHOLE message vanished
    with `loss: 0` beside it: 87 image and 2 document blocks in the corpus, and
    one of them sits in the largest session there is. `unknown` collects the
    names of block types this function does not name.
    """
    out: list[Block] = []
    for raw in content:
        if not isinstance(raw, dict):
            continue
        block = cast(dict[str, object], raw)
        block_type = block.get("type")
        if block_type == "tool_result":
            out.append(Block("tool_result", _tool_result_text(block), result=result))
        elif block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                out.append(Block("assistant_text", text.strip()))
        elif block_type in _MEDIA_BLOCK_KINDS:
            out.append(_media_block(block))
        else:
            out.append(_unknown_block(block, unknown))
    return out


# Attachment kinds that carry conversation CONTENT (rendered) vs machinery
# (recorded as a one-line marker). Split confirmed by the principal 2026-07-23.
_ATTACHMENT_CONTENT = {
    "file",
    "edited_text_file",
    "already_read_file",
    "queued_command",
    "plan_mode",
    "plan_mode_exit",
    "opened_file_in_ide",
}


def _attachment_block(attachment: dict[str, object]) -> Block:
    """One `type: "attachment"` entry as a block. Content kinds render their
    payload; every other kind becomes a compact machinery marker so it is
    visible without dumping large hook/reminder bodies (item 3)."""
    kind = _as_nonempty_str(attachment.get("type")) or "attachment"
    if kind not in _ATTACHMENT_CONTENT:
        detail = _as_nonempty_str(attachment.get("filename")) or ""
        text = f"attachment:{kind}" + (f" {detail}" if detail else "")
        return Block("machinery", text)
    filename = _as_nonempty_str(attachment.get("filename")) or ""
    body = _attachment_text(attachment)
    header = f"attachment ({kind})" + (f": {filename}" if filename else "")
    return Block("attachment", header + ("\n\n" + body if body else ""))


def _attachment_text(attachment: dict[str, object]) -> str:
    """Readable body of a content attachment, dug out of its nested shape."""
    for key in ("snippet",):
        value = _as_nonempty_str(attachment.get(key))
        if value is not None:
            return value
    content = attachment.get("content")
    if isinstance(content, dict):
        file_obj = cast(dict[str, object], content).get("file")
        if isinstance(file_obj, dict):
            text = _as_nonempty_str(cast(dict[str, object], file_obj).get("content"))
            if text is not None:
                return text
        text = _as_nonempty_str(cast(dict[str, object], content).get("content"))
        if text is not None:
            return text
    for key in ("planFilePath", "command", "content"):
        value = _as_nonempty_str(attachment.get(key))
        if value is not None:
            return value
    return ""


def _subagent_blocks(entry: dict[str, object], unknown: list[str]) -> list[Block]:
    """A sidechain (sub-agent) entry rendered as `subagent` blocks tagged with
    its agentId, so a run of them folds under one labelled phase (item 2).

    Each inner unit (the prompt, a thinking block, a tool call, a reply) becomes
    one line so the fold stays scannable; the full detail is in the source."""
    agent_id = _as_nonempty_str(entry.get("agentId")) or "sub-agent"
    role = entry.get("type")
    content = _message_content(entry)
    lines: list[str] = []
    if role == "user":
        text = extract_text(content) if not isinstance(content, str) else content.strip()
        if isinstance(content, list):
            for raw in cast(list[object], content):
                if isinstance(raw, dict):
                    block = cast(dict[str, object], raw)
                    if block.get("type") == "tool_result":
                        lines.append("tool result")
        if text:
            lines.append(f"prompt: {_one_line(text)}")
    else:
        for block in _assistant_blocks(content, unknown):
            if block.kind == "thinking":
                lines.append(f"thinking: {_one_line(block.text)}")
            elif block.kind == "assistant_text":
                lines.append(_one_line(block.text))
            elif block.kind == "tool_use":
                lines.append(f"tool: {block.tool_name or 'tool'}")
    return [Block("subagent", line, agent_id=agent_id) for line in lines if line]


def _one_line(text: str, limit: int = 200) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 3] + "..."


def _value_summary(entry: dict[str, object], keys: tuple[str, ...]) -> str:
    """A `key=value` line for the informational entry types the principal asked
    to surface verbatim (item 6): bridge-session, queue-operation, last-prompt,
    agent-name."""
    parts: list[str] = []
    for key in keys:
        value = entry.get(key)
        if value in (None, "", [], {}):
            continue
        parts.append(f"{key}={_one_line(str(value))}")
    return " ".join(parts)


def _machinery_marker(entry: dict[str, object], kind: str) -> str:
    """One compact line for a machinery entry type (ticket 18).

    Every shape here was read off a real sample of that type, so each marker
    carries the ONE field a reader can act on and nothing else. The bodies are
    deliberately not inlined: a `file-history-snapshot` reaches 15,507 bytes in
    the corpus and 14,315 of them exist, so dumping them would drown the
    conversation the projection is for.
    """
    if kind == "permission-mode":
        return f"permission-mode: {_as_nonempty_str(entry.get('permissionMode')) or '?'}"
    if kind == "mode":
        return f"mode: {_as_nonempty_str(entry.get('mode')) or '?'}"
    if kind == "started":
        return f"sub-agent started: {_as_nonempty_str(entry.get('agentId')) or '?'}"
    if kind == "file-history-delta":
        path = _as_nonempty_str(entry.get("trackingPath")) or "?"
        return f"file-history-delta: {path}"
    # file-history-snapshot: the count of tracked files is the only part a
    # reader can use; the backups themselves are Claude Code's own bookkeeping.
    tracked = 0
    snapshot = entry.get("snapshot")
    if isinstance(snapshot, dict):
        backups = cast(dict[str, object], snapshot).get("trackedFileBackups")
        if isinstance(backups, dict):
            tracked = len(cast(dict[str, object], backups))
    update = " (update)" if entry.get("isSnapshotUpdate") is True else ""
    return f"file-history-snapshot: {tracked} tracked file(s){update}"


def _agent_result_block(entry: dict[str, object]) -> Block:
    """A `result` entry as the sub-agent's returned work, in full.

    Measured across all 173 real cases: mean 2,234 bytes, max 6,908. This is a
    deliverable, not machinery, so it keeps its content instead of being cut to
    a marker (principal ruling 2026-08-02).

    There is NO single result schema, which cost a first implementation here:
    reading only `summary` covered 12 of the 173, and the other 161 carry
    `verdict`/`evidence` (71), `candidates` (41), `verdicts` (45), `files`,
    `decisions` and more, one shape per agent. So `summary` leads when present
    and the structured payload travels alongside it in `result`, where the
    emitters fence it. Nothing about the shape is assumed.
    """
    agent_id = _as_nonempty_str(entry.get("agentId")) or "sub-agent"
    result = entry.get("result")
    if isinstance(result, str):
        return Block("agent_result", result.strip(), agent_id=agent_id)
    if not isinstance(result, dict):
        return Block("machinery", f"sub-agent result: {agent_id} (empty)")
    payload = cast(dict[str, object], result)
    summary = _as_nonempty_str(payload.get("summary")) or ""
    rest = {key: value for key, value in payload.items() if key != "summary"}
    return Block(
        "agent_result",
        summary,
        result=cast("Mapping[str, object]", rest) if rest else None,
        agent_id=agent_id,
    )


def _frame_link_text(entry: dict[str, object]) -> str:
    """An artifact the session produced: its title and the URL it lives at.

    Kept as plain text rather than a markdown link because the same string is
    rendered by BOTH emitters and only one of them runs it through the markdown
    renderer; a link here would render differently in the two files (R9).
    """
    title = _as_nonempty_str(entry.get("title")) or ""
    url = _as_nonempty_str(entry.get("frameUrl")) or ""
    path = _as_nonempty_str(entry.get("path")) or ""
    parts = [part for part in (title, url, path) if part]
    return "frame-link: " + " ".join(parts) if parts else "frame-link"


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

    Metadata entries (`summary`, `ai-title`, `custom-title`) are named here and
    deliberately emit nothing: parse_session owns them. Every OTHER entry type
    surfaces, machinery as a one-line marker; a type this parser does not name
    surfaces as a marker AND is counted into `unrecognised` (ticket 18,
    principal ruling 2026-08-02). Before that ruling this method dropped eight
    real entry types and three content-block types outright, 62,577 entries
    across the corpus, with `loss: 0` recorded beside them.
    """
    entries, _line_count, skipped_lines, unencodable = _extract_entries(data)
    unknown: list[str] = []

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

        # THE TRIPWIRE (ticket 18). Anything this parser does not name is
        # surfaced as a marker and counted, so the next entry type Claude Code
        # ships is visible in the projection AND answerable from the manifest,
        # rather than waiting for someone to re-run a census. Placed FIRST so no
        # later branch can silently swallow an unnamed type.
        if not isinstance(kind, str) or kind not in KNOWN_ENTRY_TYPES:
            name = kind if isinstance(kind, str) and kind else "(untyped)"
            unknown.append(f"entry:{name}")
            blocks.append(Block("machinery", f"entry:{name}"))
            continue

        # Sidechain entries are a sub-agent's own exchange, not the main
        # thread: fold them in as subagent blocks rather than letting them start
        # or join a top-level turn (item 2). Checked before role dispatch so a
        # sidechain user prompt never opens a main turn.
        if entry.get("isSidechain") is True and kind in ("user", "assistant"):
            blocks.extend(_subagent_blocks(entry, unknown))
            continue

        if kind == "attachment":
            attachment = entry.get("attachment")
            if isinstance(attachment, dict):
                blocks.append(_attachment_block(cast(dict[str, object], attachment)))
            continue
        if kind == "system":
            subtype = _as_nonempty_str(entry.get("subtype"))
            text = _as_nonempty_str(entry.get("content"))
            if subtype == "local_command" and text:
                # A slash command the user typed reads as user input (item 4).
                blocks.append(Block("command", text))
            elif text or subtype:
                label = f"system:{subtype or 'system'} {text or ''}".strip()
                blocks.append(Block("machinery", label))
            continue
        if kind in ("bridge-session", "queue-operation", "last-prompt", "agent-name"):
            summary = _value_summary(
                entry,
                (
                    "operation",
                    "content",
                    "lastPrompt",
                    "agentName",
                    "bridgeSessionId",
                    "leafUuid",
                    "lastSequenceNum",
                ),
            )
            if summary:
                blocks.append(Block("extra", f"{kind}: {summary}"))
            continue
        if kind in _MACHINERY_ENTRY_TYPES:
            blocks.append(Block("machinery", _machinery_marker(entry, kind)))
            continue
        if kind in _AGENT_RESULT_ENTRY_TYPES:
            blocks.append(_agent_result_block(entry))
            continue
        if kind in _LINK_ENTRY_TYPES:
            blocks.append(Block("extra", _frame_link_text(entry)))
            continue
        if kind in _METADATA_ENTRY_TYPES:
            # Named, and deliberately silent: parse_session owns the title and
            # summary sources, so emitting them here would duplicate the header.
            continue

        if kind == "assistant":
            blocks.extend(_assistant_blocks(content, unknown))
            continue
        if kind != "user":
            continue

        result = entry.get("toolUseResult")
        result_map = (
            cast("Mapping[str, object]", result) if isinstance(result, dict) else None
        )
        if entry.get("isCompactSummary") is True:
            blocks.append(Block("continuation", extract_text(content)))
            continue
        if isinstance(content, list):
            blocks.extend(
                _user_list_blocks(cast(list[object], content), unknown, result_map)
            )
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
        unencodable_chars=unencodable,
        # Sorted and de-duplicated for the manifest; the COUNT keeps every
        # occurrence, so ten of one new type reads as ten, not as one.
        unrecognised=tuple(sorted(set(unknown))),
        unrecognised_count=len(unknown),
    )
