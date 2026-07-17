"""Session payload parsing: metadata extraction, summary, commit/repo detection.

Slice 3. SPEC section 6 (KEEP/CHANGE verdicts), DESIGN section 4 (parse ONCE).
"""

from dataclasses import dataclass


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


def parse_session(data: bytes) -> ParsedSession:
    """Parse a raw session payload: JSONL, or JSON with a `loglines` key.

    Malformed lines are counted (skipped_lines), never silently dropped.
    """
    raise NotImplementedError


def extract_text(content: object) -> str:
    """Text from a message content field: plain string or block array (text blocks only)."""
    raise NotImplementedError


def detect_commits(text: str) -> list[Commit]:
    raise NotImplementedError


def detect_github_repo(text: str) -> str | None:
    raise NotImplementedError
