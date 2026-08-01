"""Oracle tests: lone surrogates in a payload never stop a projection.

Found on real data 2026-08-01, on the first `ccw build` at scale: 9 of 13,608
sessions failed with `UnicodeEncodeError: 'utf-8' codec can't encode character
'\\ud83d': surrogates not allowed`, and 11 of 13,836 stored objects carry one.

The cause is upstream and is not ours to fix: Claude Code truncates a field
mid-emoji, leaving the HIGH half of a surrogate pair with its low half cut off.
`json.loads` decodes that escape into a lone surrogate - a perfectly legal
Python str that has NO utf-8 encoding at all - so the render succeeds and the
WRITE fails.

The ruling (principal, 2026-08-01): replace with U+FFFD, the character the
Unicode standard defines for exactly this, and COUNT it. The character was
already destroyed upstream, so this is choosing how to represent something
broken rather than discarding something whole; but a projection that quietly
substituted characters would still be F6, so the count travels in the manifest's
`loss` block beside skipped_lines.

The stored payload keeps the original bytes either way. Nothing here is
reversible-only-in-theory: re-render at any time and the source is untouched.
"""

import json

import pytest

from cc_warehouse import render, store
from cc_warehouse.parser import build_conversation, parse_session
from conftest import entry, jsonl

# A HIGH surrogate with no low half, exactly as a truncated emoji leaves one.
LONE_HIGH = "\ud83d"
LONE_LOW = "\udc4d"
REPLACEMENT = "�"


def _session_with(text: str) -> bytes:
    """A session whose prompt carries `text`. Built by hand rather than through
    json.dumps' default escaping so the payload really holds the escape."""
    return jsonl(
        entry("user", text, "2026-01-05T10:00:00.000Z", gitBranch="main", slug="surrogate"),
        entry("assistant", [{"type": "text", "text": "Reply."}], "2026-01-05T10:00:05.000Z"),
    )


def test_the_fixture_really_carries_a_lone_surrogate() -> None:
    """Guard: if the payload did not actually contain one, every test below
    would pass while proving nothing."""
    data = _session_with(f"truncated emoji here {LONE_HIGH}")
    assert b"\\ud83d" in data, data[:200]


@pytest.mark.parametrize("bad", (LONE_HIGH, LONE_LOW))
def test_a_lone_surrogate_does_not_stop_the_markdown(bad: str) -> None:
    """The regression, stated as the thing that actually failed: the rendered
    text must be encodable, because that encode is what the write does."""
    full, compact = render.render_markdown(_session_with(f"x {bad} y"), render.RenderOptions())
    full.encode("utf-8")
    compact.encode("utf-8")


@pytest.mark.parametrize("bad", (LONE_HIGH, LONE_LOW))
def test_a_lone_surrogate_does_not_stop_the_html(bad: str) -> None:
    full, compact = render.render_html(_session_with(f"x {bad} y"), render.RenderOptions())
    full.encode("utf-8")
    compact.encode("utf-8")


def test_the_surrogate_becomes_the_replacement_character() -> None:
    """U+FFFD is the standard representation, so a reader sees the conventional
    "something was here and it was broken" glyph rather than a hole."""
    full, _ = render.render_markdown(_session_with(f"a{LONE_HIGH}b"), render.RenderOptions())
    assert REPLACEMENT in full
    assert LONE_HIGH not in full


def test_surrounding_text_survives_intact() -> None:
    """Only the unencodable character is replaced. A blunt fix that dropped the
    whole field, or the whole line, would lose content that is perfectly fine."""
    full, _ = render.render_markdown(
        _session_with(f"KEEPBEFORE{LONE_HIGH}KEEPAFTER"), render.RenderOptions()
    )
    assert "KEEPBEFORE" in full
    assert "KEEPAFTER" in full


def test_a_well_formed_emoji_is_untouched() -> None:
    """The fix must not touch valid astral characters, which arrive as PROPER
    surrogate pairs in JSON and decode to one legal character."""
    full, _ = render.render_markdown(_session_with("waving 👋 hand"), render.RenderOptions())
    assert "👋" in full
    assert REPLACEMENT not in full


def test_the_count_reaches_the_manifest_loss_block() -> None:
    """F6: a silent substitution is exactly what the loss telemetry exists to
    prevent. DESIGN 6's frozen `loss` key set grows by one."""
    data = _session_with(f"one {LONE_HIGH} two {LONE_HIGH} three")
    manifest = render.build_manifest(data, render.RenderOptions())
    loss = manifest["loss"]
    assert isinstance(loss, dict)
    assert loss["unencodable_chars"] == 2
    json.dumps(manifest)


def test_a_clean_session_reports_zero() -> None:
    manifest = render.build_manifest(_session_with("nothing broken here"), render.RenderOptions())
    loss = manifest["loss"]
    assert isinstance(loss, dict)
    assert loss["unencodable_chars"] == 0


def test_both_parser_entry_points_count_it() -> None:
    """parse_session and build_conversation both route through one extractor
    (R9), so neither can report a different number than the other."""
    data = _session_with(f"a {LONE_HIGH} b")
    assert parse_session(data).unencodable_chars == 1
    assert build_conversation(data).unencodable_chars == 1


def test_the_stored_payload_is_never_modified() -> None:
    """The substitution is a PROJECTION choice. The warehouse keeps the original
    bytes, lone surrogate and all, so a future reader can still recover exactly
    what the transcript said."""
    data = _session_with(f"a {LONE_HIGH} b")
    before = store.sha256_hex(data)
    render.render_markdown(data, render.RenderOptions())
    render.render_html(data, render.RenderOptions())
    render.build_manifest(data, render.RenderOptions())
    assert store.sha256_hex(data) == before
    assert b"\\ud83d" in data, "the original escape is still in the payload"
