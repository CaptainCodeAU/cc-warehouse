"""Oracle tests: conversation.html + compact HTML emitters and the render
manifest (slice 7).

Contract: DESIGN section 6 (unique anchors, copy-as-markdown byte equality,
manifest loss telemetry), SPEC section 7 KEEP semantics (tool-typed rendering,
commit cards, markdown hardening).
"""

import base64
import hashlib
import importlib
import re
from typing import Any, cast

import pytest

from cc_warehouse.render import RenderOptions, build_manifest, render_html, render_markdown
from conftest import entry, jsonl, rich_session

REMINDER = "secret internal reminder text"


def render_pair() -> tuple[str, str]:
    # render_html returns UTF-8 bytes (ticket 28.9, Fix A); decode once here so
    # every test in this file keeps comparing plain text.
    full, compact = render_html(rich_session(), RenderOptions())
    return full.decode("utf-8"), compact.decode("utf-8")


def test_both_variants_are_complete_single_pages() -> None:
    full, compact = render_pair()
    for page in (full, compact):
        assert "<html" in page.lower()
        assert "First real prompt about widgets" in page


def test_message_anchors_are_unique_despite_equal_timestamps() -> None:
    """DESIGN section 6: anchors are turn ordinal + short content hash; the
    rich session carries two entries with the same timestamp (SPEC's
    make_msg_id collision)."""
    full, _ = render_pair()
    ids = re.findall(r'id="([^"]+)"', full)
    assert ids, "no anchors found"
    assert len(ids) == len(set(ids)), f"duplicate anchors: {ids}"


def test_copy_as_markdown_payloads_equal_transcript_fragments() -> None:
    """SPEC 7 KEEP (oracle required): every data-copy-src payload equals the
    corresponding transcript.md fragment byte for byte."""
    full_md, _ = render_markdown(rich_session(), RenderOptions())
    full_md = full_md.decode("utf-8")
    full_html, _ = render_pair()
    payloads = re.findall(r'data-copy-src="([^"]+)"', full_html)
    assert payloads, "no copy-as-markdown payloads found"
    for encoded in payloads:
        fragment = base64.b64decode(encoded).decode("utf-8")
        assert fragment in full_md


def test_render_block_is_memoized_across_copy_levels(monkeypatch: pytest.MonkeyPatch) -> None:
    """ticket 28.9 Fix B: the same (block, policy) pair is independently needed
    at row, phase, turn and whole-transcript copy-payload granularity. A
    regression here would silently reintroduce the quadruple recomputation Fix
    B removed, so this pins the cache's own invariant rather than only the
    byte-equality it must preserve (that's the test above). Reached by name
    (getattr/setattr) rather than attribute access: the function is
    module-private, and this test only needs to observe how often it runs."""
    render_mod = importlib.import_module("cc_warehouse.render")
    # getattr, not attribute access: the function is module-private, so pyright's
    # reportPrivateUsage would otherwise flag a direct `render_mod._render_block_
    # uncached` from this test module.
    original: Any = getattr(render_mod, "_render_block_uncached")  # noqa: B009

    calls: dict[tuple[int, object], int] = {}

    def counting(block: object, policy: object) -> object:
        key = (id(block), policy)
        calls[key] = calls.get(key, 0) + 1
        return original(block, policy)

    monkeypatch.setattr(render_mod, "_render_block_uncached", counting)
    render_html(rich_session(), RenderOptions())
    assert calls, "no blocks were rendered"
    repeats = {k: v for k, v in calls.items() if v > 1}
    assert not repeats, f"a (block, policy) pair was rendered more than once: {repeats}"


def test_tool_typed_rendering_semantics() -> None:
    """SPEC 7 KEEP: Bash command, Edit old/new, commit cards with repo links."""
    full, _ = render_pair()
    assert "git commit -m widget" in full
    assert "old_widget()" in full
    assert "new_widget()" in full
    assert "abc1234" in full
    assert re.search(r'href="[^"]*github\.com/alice/widget/commit/abc1234', full)


def test_reminders_collapsed_full_stripped_compact() -> None:
    full, compact = render_pair()
    assert REMINDER in full
    details_span = re.search(r"<details[\s\S]*?</details>", full)
    assert details_span is not None
    assert REMINDER not in compact


def test_markdown_hardening_renders_loose_lists() -> None:
    """SPEC 7 KEEP: blank-line insertion before loose lists survives into HTML."""
    full, _ = render_pair()
    assert re.search(r"<li>\s*alpha", full)
    assert re.search(r"<li>\s*beta", full)


def test_trailing_orphan_fence_is_stripped() -> None:
    """SPEC 7 KEEP: a message ending with a dangling ``` never produces an
    unbalanced code block."""
    full, compact = render_pair()
    for page in (full, compact):
        assert page.count("<pre") == page.count("</pre")


def test_manifest_records_hash_counts_and_loss() -> None:
    """DESIGN section 6: manifest.json answers "did we lose anything".
    Frozen keys: source_hash, counts.prompts, counts.tool_calls,
    loss.skipped_lines, config."""
    data = rich_session()
    manifest = build_manifest(data, RenderOptions())
    assert manifest["source_hash"] == hashlib.sha256(data).hexdigest()
    counts = cast(dict[str, object], manifest["counts"])
    # Continuations merge into their prompt; stop-hook feedback and task
    # notifications are never prompts: the rich session has exactly 2.
    assert counts["prompts"] == 2
    assert counts["tool_calls"] == 2
    loss = cast(dict[str, object], manifest["loss"])
    assert loss["skipped_lines"] == 0
    assert isinstance(manifest["config"], dict)


def test_manifest_counts_malformed_lines_as_loss() -> None:
    data = jsonl(
        entry("user", "prompt", "2026-01-05T10:00:00.000Z"),
        "garbage not json",
    )
    manifest = build_manifest(data, RenderOptions())
    loss = cast(dict[str, object], manifest["loss"])
    assert loss["skipped_lines"] == 1
