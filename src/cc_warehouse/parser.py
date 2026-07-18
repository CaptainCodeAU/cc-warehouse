"""Session payload parsing: metadata extraction, summary, commit/repo detection.

Slice 3. SPEC section 6 (KEEP/CHANGE verdicts), DESIGN section 4 (parse ONCE).
"""

import json
import re
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


def parse_session(data: bytes) -> ParsedSession:
    """Parse a raw session payload: JSONL, or JSON with a `loglines` key.

    Malformed lines are counted (skipped_lines), never silently dropped: the
    parseable lines are still parsed even when others fail (F6). A whole-
    payload JSON object carrying a `loglines` key is parsed like JSONL over
    that list; ordinary JSONL routes to the line-by-line path because the
    payload as a whole does not parse as a single JSON object with that key
    (a one-line JSONL entry that itself carries a top-level `loglines` field
    is a theoretical exception to this routing).
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
            line_count = len(raw_entries)
        else:
            # Present but not a list: a malformed payload, not an empty one.
            # Counted so it is never indistinguishable from a genuinely empty
            # session (F6).
            entries, skipped_lines, line_count = [], 1, 1
    else:
        entries, skipped_lines = _entries_from_jsonl(text)
        line_count = len(text.splitlines())

    session_uuid: str | None = None
    cwd: str | None = None
    slug: str | None = None
    git_branch: str | None = None
    version: str | None = None
    first_ts: str | None = None
    last_ts: str | None = None

    for entry in entries:
        session_uuid = session_uuid or _as_nonempty_str(entry.get("sessionId"))
        cwd = cwd or _as_nonempty_str(entry.get("cwd"))
        slug = slug or _as_nonempty_str(entry.get("slug"))
        git_branch = git_branch or _as_nonempty_str(entry.get("gitBranch"))
        version = version or _as_nonempty_str(entry.get("version"))
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
