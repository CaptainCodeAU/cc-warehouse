"""Oracle tests: session payload parsing (slice 3).

Contract: SPEC section 6 (KEEP: content extraction, task-notification rule,
summary priority; CHANGE: richer raw fields, malformed lines counted, never
silent), SPEC section 8 (summary + warmup/no-summary hiding), SPEC section 6
commit/repo detection; DESIGN section 4 (parse ONCE feeds the catalog).
"""

import json

from cc_warehouse import parser
from conftest import DEFAULT_CWD, DEFAULT_UUID, basic_session, entry, jsonl


def test_parse_extracts_rich_raw_fields() -> None:
    parsed = parser.parse_session(basic_session())
    assert parsed.session_uuid == DEFAULT_UUID
    assert parsed.cwd == DEFAULT_CWD
    assert parsed.slug == "fix-flux"
    assert parsed.git_branch == "main"
    assert parsed.version == "2.0.0"
    assert parsed.first_ts == "2026-01-05T10:00:00.000Z"
    assert parsed.last_ts == "2026-01-05T10:00:05.000Z"
    assert parsed.line_count == 2
    assert parsed.skipped_lines == 0
    assert parsed.hidden is False


def test_malformed_lines_are_counted_never_silent() -> None:
    """SPEC 6 CHANGE / F6: silent data loss is banned; the parser must count
    and report unparseable lines while keeping the parseable ones."""
    data = jsonl(
        entry("user", "Real prompt", "2026-01-05T10:00:00.000Z"),
        "this is not json {",
        entry("assistant", "Reply", "2026-01-05T10:00:05.000Z"),
    )
    parsed = parser.parse_session(data)
    assert parsed.line_count == 3
    assert parsed.skipped_lines == 1
    assert parsed.summary == "Real prompt"


def test_json_file_with_loglines_key_is_accepted() -> None:
    """SPEC 6 KEEP: JSON (non-JSONL) session files with a `loglines` key parse."""
    payload = {
        "loglines": [
            entry("user", "Prompt via loglines", "2026-01-05T10:00:00.000Z"),
            entry("assistant", "Reply", "2026-01-05T10:00:05.000Z"),
        ]
    }
    parsed = parser.parse_session(json.dumps(payload).encode())
    assert parsed.summary == "Prompt via loglines"
    assert parsed.session_uuid == DEFAULT_UUID


def test_extract_text_string_and_block_array() -> None:
    """SPEC 6 KEEP: content is a plain string or a block array; text blocks only."""
    assert parser.extract_text("plain words") == "plain words"
    blocks: list[object] = [
        {"type": "text", "text": "alpha"},
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}},
        {"type": "text", "text": "beta"},
    ]
    text = parser.extract_text(blocks)
    assert "alpha" in text
    assert "beta" in text
    assert "tool_use" not in text


def test_summary_prefers_summary_line() -> None:
    """SPEC 8 KEEP: first `type: summary` line wins over user text."""
    data = jsonl(
        {"type": "summary", "summary": "The canonical summary"},
        entry("user", "A user prompt", "2026-01-05T10:00:00.000Z"),
    )
    assert parser.parse_session(data).summary == "The canonical summary"


def test_summary_caps_at_200_chars() -> None:
    long_prompt = "x" * 300
    parsed = parser.parse_session(
        jsonl(entry("user", long_prompt, "2026-01-05T10:00:00.000Z"))
    )
    assert len(parsed.summary) <= 200
    assert parsed.summary.startswith("x" * 50)


def test_summary_skips_angle_prefixed_and_task_notification_text() -> None:
    """SPEC 6/8 KEEP: `<`-prefixed machine text and task notifications are never
    prompts, never summaries, never conversation starters."""
    data = jsonl(
        entry(
            "user",
            "<task-notification>machine chatter</task-notification>",
            "2026-01-05T10:00:00.000Z",
        ),
        entry(
            "user",
            "<local-command-stdout>noise</local-command-stdout>",
            "2026-01-05T10:00:01.000Z",
        ),
        entry("user", "The real prompt", "2026-01-05T10:00:02.000Z"),
    )
    assert parser.parse_session(data).summary == "The real prompt"


def test_warmup_session_is_hidden() -> None:
    parsed = parser.parse_session(
        jsonl(entry("user", "warmup", "2026-01-05T10:00:00.000Z"))
    )
    assert parsed.hidden is True


def test_session_without_summary_is_hidden_with_placeholder() -> None:
    parsed = parser.parse_session(
        jsonl(entry("assistant", "only assistant text", "2026-01-05T10:00:00.000Z"))
    )
    assert parsed.summary == "(no summary)"
    assert parsed.hidden is True


def test_commit_detection_with_newline_terminator() -> None:
    """SPEC 6 KEEP: `\\[[\\w\\-/]+ ([a-f0-9]{7,})\\] (.+?)(?:\\n|$)`; the
    terminator is load-bearing, so a multi-line result yields exact messages."""
    text = "[main abc1234] add widget frobnicator\n 1 file changed, 2 insertions(+)"
    commits = parser.detect_commits(text)
    assert len(commits) == 1
    assert commits[0].sha == "abc1234"
    assert commits[0].message == "add widget frobnicator"


def test_commit_detection_at_end_of_string() -> None:
    commits = parser.detect_commits("[feature/x 1234abc] terse fix")
    assert len(commits) == 1
    assert commits[0].sha == "1234abc"
    assert commits[0].message == "terse fix"


def test_commit_detection_multiple() -> None:
    text = "[main abc1234] first change\nnoise\n[dev 4321cba] second change\n"
    messages = [(c.sha, c.message) for c in parser.detect_commits(text)]
    assert messages == [("abc1234", "first change"), ("4321cba", "second change")]


def test_github_repo_detection_from_push_output() -> None:
    """SPEC 6 KEEP: repo auto-detected from `git push` pull/new output."""
    text = (
        "remote: Create a pull request for 'main' on GitHub by visiting:\n"
        "remote:   https://github.com/alice/widget/pull/new/main"
    )
    assert parser.detect_github_repo(text) == "alice/widget"
    assert parser.detect_github_repo("nothing relevant here") is None
