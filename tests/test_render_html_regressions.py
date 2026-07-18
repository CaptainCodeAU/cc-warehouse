"""Contract-derived regression tests for the HTML emitters (slice 7, post-review).
NOT the frozen oracle suite (tests/test_render_html.py); these pin the reviewer
clusters the oracle did not cover. Cited in harness/tickets/07-render-html.md.

- RT-PASSTHROUGH: user text matching <details>/<summary> is ESCAPED, not passed
  through; the page stays structurally balanced. [C-PASSTHROUGH]
- RT-COMMIT-REPO: in a multi-repo session a commit sha links to ITS OWN result's
  repo, not the first repo found. [C-COMMIT-REPO]
- RT-CDN: the page carries exactly ONE external cdnjs reference. [C-CDN-COUNT]
- RT-INLINE: inline bold and links still render (locks the md->HTML inline branches).
"""

import json
from collections.abc import Mapping

from cc_warehouse.render import RenderOptions, render_html


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


def test_user_details_line_is_escaped_and_page_balanced() -> None:
    """C-PASSTHROUGH: a user prompt that is a bare <details> must be escaped, not
    emitted as a live tag; the page keeps its <details> balanced."""
    data = payload(user("<details>"), assistant([{"type": "text", "text": "reply"}]))
    full, _ = render_html(data, RenderOptions())
    assert "&lt;details&gt;" in full
    assert full.count("<details>") == full.count("</details>")


def test_user_summary_injection_is_escaped() -> None:
    """C-PASSTHROUGH: a user prompt shaped like a summary widget is escaped."""
    data = payload(user("<summary>INJECTED</summary>"))
    full, _ = render_html(data, RenderOptions())
    assert "<summary>INJECTED</summary>" not in full
    assert "INJECTED" in full


def test_user_script_is_escaped() -> None:
    """C-PASSTHROUGH: user text is HTML-escaped (no raw markup injection)."""
    data = payload(user("look: <script>alert(1)</script>"))
    full, _ = render_html(data, RenderOptions())
    assert "<script>alert(1)</script>" not in full
    assert "&lt;script&gt;" in full


def test_commit_links_to_its_own_result_repo() -> None:
    """C-COMMIT-REPO: when a result carries both a sha and a repo, the sha links to
    THAT repo, not the first repo detected elsewhere in the session."""
    data = payload(
        user("go"),
        assistant(
            [{"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": "git push"}}]
        ),
        tool_result("cloned https://github.com/alice/widget/pull/new/main"),
        tool_result("[main abc1234] fix\nsee https://github.com/bob/other/pull/new/main"),
    )
    full, _ = render_html(data, RenderOptions())
    assert "github.com/bob/other/commit/abc1234" in full
    assert "github.com/alice/widget/commit/abc1234" not in full


def test_page_has_a_single_external_cdn_reference() -> None:
    """C-CDN-COUNT: DESIGN-6 permits the ONE highlight.js CDN reference; no second
    external cdnjs asset."""
    data = payload(user("hi"))
    full, _ = render_html(data, RenderOptions())
    assert full.count("cdnjs.cloudflare.com") == 1
    assert "highlight.min.js" in full
    assert "github.min.css" not in full


def test_inline_bold_and_links_render() -> None:
    """Locks the md->HTML inline branches (untested by the oracle)."""
    data = payload(user("see **bold** and a [link](https://x.test) here"))
    full, _ = render_html(data, RenderOptions())
    assert "<strong>bold</strong>" in full
    assert 'href="https://x.test"' in full
    assert ">link</a>" in full
