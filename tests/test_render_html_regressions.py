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

from cc_warehouse.render import RenderOptions
from cc_warehouse.render import render_html as _render_html_bytes


def render_html(data: bytes, options: RenderOptions) -> tuple[str, str]:
    """render_html returns UTF-8 bytes (ticket 28.9, Fix A); decode once here so
    every test in this file keeps comparing plain text."""
    full, compact = _render_html_bytes(data, options)
    return full.decode("utf-8"), compact.decode("utf-8")


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


def test_hljs_modes_control_the_one_external_reference() -> None:
    """DESIGN 15 item 8, ruled by the principal 2026-07-24.

    Shared pages INLINE highlight.js so a published archive is self-contained and makes
    no third-party request; personal projections keep the CDN reference plus its graceful
    onerror fallback (exporter parity). The mode is a RenderOptions field so the two
    callers differ without a second renderer (R9).

    The inlined payload is asserted to be the vendored file BYTE FOR BYTE: a hand-copied
    or re-minified variant would drift from the recorded sha256 in vendor/README.md.
    """
    from pathlib import Path

    from cc_warehouse import render

    data = payload(user("hello"), assistant([{"type": "text", "text": "world"}]))
    vendored = (
        Path(render.__file__).parent / "vendor" / "highlight.min.js"
    ).read_text(encoding="utf-8")

    cdn, _ = render_html(data, render.RenderOptions(hljs="cdn"))
    assert cdn.count("cdnjs.cloudflare.com") == 1, "personal pages keep exactly one CDN ref"
    assert "onerror" in cdn, "the graceful fallback was dropped"
    assert vendored not in cdn, "the cdn mode shipped the payload too"

    inline, inline_compact = render_html(data, render.RenderOptions(hljs="inline"))
    for page in (inline, inline_compact):
        assert "cdnjs.cloudflare.com" not in page, "an inlined page still calls out to a CDN"
        assert vendored in page, "the inlined payload is not the vendored file verbatim"
        assert "hljs.highlightAll()" in page, "highlighting is not actually invoked"

    off, _ = render_html(data, render.RenderOptions(hljs="off"))
    assert "cdnjs.cloudflare.com" not in off
    assert vendored not in off, "hljs=off still shipped the payload"


def test_hljs_defaults_to_cdn_for_personal_projections() -> None:
    """Exporter parity is the default; inlining is opt-in and share sets it."""
    from cc_warehouse import render

    assert render.RenderOptions().hljs == "cdn"
