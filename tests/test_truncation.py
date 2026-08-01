"""Oracle tests: opt-in tool-output truncation (slice 16, block 3).

Contract: DESIGN section 15 entry 2026-08-01 block 3; DESIGN section 6 (the
manifest's frozen keys: config used, counts, loss telemetry); FINDINGS F6, the
code overclaiming its own guarantees - the in-page marker IS a guarantee, so
these tests are its citation (R8).

The frozen decisions: opt-in and OFF by default, because an audit-trail product
does not change your files because you upgraded. CHARACTERS, said in the key
name, because the renderer's native unit is decoded str, a line cap misses the
archetypal single-line blob, and a KB cap means different amounts per alphabet.
Projection-only BY CONSTRUCTION: the store and the catalog are never in the path.

One cap, variant-agnostic. It applies wherever a tool-result block renders: the
full variant by default, and the compact variant when slice 14's matrix opened
tool output there.
"""

import json
from pathlib import Path
from typing import cast

import pytest

from cc_warehouse import render, store
from cc_warehouse.config import load_config
from conftest import entry, jsonl, matrix_session

# Two shapes of offender. The multi-line one proves the cut lands on a boundary;
# the single-line blob is the case a LINE cap would have missed entirely, which
# is the stated reason the cap counts characters.
LINE = "abcdefghij"  # 10 chars + newline
MULTILINE_BODY = "\n".join(f"{LINE}{i}" for i in range(40))  # 40 lines of 11 chars
BLOB_BODY = "z" * 900  # one line, no boundary to cut on


def _session(body: str) -> bytes:
    """A session whose single tool result carries `body` as its raw text."""
    return jsonl(
        entry("user", "Run it", "2026-01-05T10:00:00.000Z", gitBranch="main", slug="cap"),
        entry(
            "assistant",
            [{"type": "tool_use", "id": "t1", "name": "Bash",
              "input": {"command": "cat big", "description": "Read"}}],
            "2026-01-05T10:00:01.000Z",
        ),
        entry(
            "user",
            [{"type": "tool_result", "tool_use_id": "t1", "content": body}],
            "2026-01-05T10:00:02.000Z",
        ),
        entry("assistant", [{"type": "text", "text": "Done."}], "2026-01-05T10:00:03.000Z"),
    )


def _md(body: str, cap: int) -> str:
    full, _compact = render.render_markdown(_session(body), _options(cap))
    return full


def _options(cap: int, **extra: object) -> render.RenderOptions:
    return render.RenderOptions(tool_output_max_chars=cap, **extra)  # pyright: ignore[reportArgumentType]


def _manifest_loss(body: str, cap: int) -> dict[str, int]:
    manifest = render.build_manifest(_session(body), _options(cap))
    loss = manifest["loss"]
    assert isinstance(loss, dict)
    return cast("dict[str, int]", loss)


# --- off by default: the upgrade changes nothing ---------------------------


def test_the_cap_is_absent_by_default() -> None:
    """An audit-trail product does not start dropping content because you
    upgraded. Absent means off, and off is the default."""
    assert render.RenderOptions().tool_output_max_chars == 0
    config = load_config(env={"HOME": "/home/alice"}, no_config=True)
    assert config.render_tool_output_max_chars == 0


def test_an_explicit_zero_equals_absent() -> None:
    """`tool_output_max_chars = 0` is the documented way to say off, so it must
    render exactly what an unset key renders."""
    assert _md(MULTILINE_BODY, 0) == _md(MULTILINE_BODY, 0)
    absent = render.render_markdown(_session(MULTILINE_BODY), render.RenderOptions())[0]
    assert _md(MULTILINE_BODY, 0) == absent


@pytest.mark.parametrize("name", (
    "transcript.md", "transcript.compact.md", "conversation.html", "conversation.compact.html",
))
def test_no_cap_keeps_the_anchor(name: str) -> None:
    """Shared rule (b) again: the anchor must survive a slice that adds an
    opt-in feature. Reused, never regenerated."""
    golden = Path(__file__).resolve().parent / "golden" / "matrix-anchor" / name
    data = matrix_session()
    options = render.RenderOptions()
    full_md, compact_md = render.render_markdown(data, options)
    full_html, compact_html = render.render_html(data, options)
    produced: dict[str, str] = {
        "transcript.md": full_md,
        "transcript.compact.md": compact_md,
        "conversation.html": full_html,
        "conversation.compact.html": compact_html,
    }
    assert produced[name] == golden.read_text(encoding="utf-8")


def test_an_under_cap_block_is_untouched() -> None:
    """The cap is a ceiling, not a reformatter."""
    small = "one\ntwo\nthree"
    assert _md(small, 10_000) == _md(small, 0)
    assert small in _md(small, 10_000)


# --- where the cut lands ---------------------------------------------------


def test_the_cut_lands_on_a_line_boundary_at_or_below_the_cap() -> None:
    """Never mid-line when a boundary is available: a half-line of output reads
    as corrupted data rather than as omitted data."""
    cap = 100
    out = _md(MULTILINE_BODY, cap)
    kept = [ln for ln in MULTILINE_BODY.split("\n") if ln in out]
    assert kept, "nothing survived the cut"
    assert len("\n".join(kept)) <= cap
    # the next line would have crossed the cap, so it must be gone
    following = MULTILINE_BODY.split("\n")[len(kept)]
    assert following not in out


def test_a_single_line_blob_is_still_cut() -> None:
    """The archetypal offender, and the whole reason the cap counts CHARACTERS:
    one enormous line has no boundary to fall back to, and a line-based cap
    would have let it through untouched."""
    cap = 100
    out = _md(BLOB_BODY, cap)
    assert BLOB_BODY not in out, "the blob passed through uncut"
    assert "z" * cap not in out or len([ln for ln in out.splitlines() if ln.count("z") > cap]) == 0


# --- the marker: loss is never silent (F6) ---------------------------------


@pytest.mark.parametrize("body", (MULTILINE_BODY, BLOB_BODY))
def test_the_marker_states_what_was_omitted(body: str) -> None:
    """F6: a projection that quietly dropped content would be the product lying
    about its own completeness. The count is part of the guarantee."""
    out = _md(body, 100)
    omitted = _manifest_loss(body, 100)["truncated_chars"]
    assert omitted > 0
    assert str(omitted) in out, f"the marker does not state the {omitted} omitted characters"


@pytest.mark.parametrize("body", (MULTILINE_BODY, BLOB_BODY))
def test_the_marker_says_the_stored_session_is_complete(body: str) -> None:
    """The reassurance is the point: truncation is a PROJECTION choice, and the
    warehouse still holds every byte. A marker without this sentence would read
    as data loss."""
    out = _md(body, 100).lower()
    assert "stored" in out
    assert "complete" in out


def test_the_marker_reaches_the_html_variant_too() -> None:
    """One policy, both emitters. Slice 14's lesson: a self-describing string
    fixed in one emitter and not the other is the recurring defect here."""
    full, _compact = render.render_html(_session(MULTILINE_BODY), _options(100))
    assert "stored" in full.lower()
    omitted = _manifest_loss(MULTILINE_BODY, 100)["truncated_chars"]
    assert str(omitted) in full


def test_no_marker_when_nothing_was_truncated() -> None:
    """Marker if and only if truncation happened: a marker on untouched output
    is its own kind of lie."""
    out = _md("one\ntwo", 10_000)
    assert "stored" not in out.lower()


# --- the manifest amendment ------------------------------------------------


def test_manifest_loss_gains_the_two_truncation_keys() -> None:
    """DESIGN 6's frozen `loss` key set grows to skipped_lines +
    truncated_blocks + truncated_chars. This is the whole reason the slice
    travels alone.

    `unencodable_chars` joined the set later the same day, on the lone-surrogate
    ruling; the assertion is exact rather than a subset because the point of a
    FROZEN key set is that a key cannot appear or vanish unnoticed."""
    loss = _manifest_loss(MULTILINE_BODY, 100)
    assert set(loss) == {
        "skipped_lines",
        "truncated_blocks",
        "truncated_chars",
        "unencodable_chars",
    }


def test_manifest_counts_are_zero_when_the_cap_is_off() -> None:
    loss = _manifest_loss(MULTILINE_BODY, 0)
    assert loss["truncated_blocks"] == 0
    assert loss["truncated_chars"] == 0


def test_truncated_blocks_counts_blocks_not_variants() -> None:
    """One tool result that gets cut is ONE truncated block, however many files
    it appears in. The cap is variant-agnostic, so the same block is cut
    identically everywhere and counting per variant would double-report."""
    assert _manifest_loss(MULTILINE_BODY, 100)["truncated_blocks"] == 1


def test_truncated_chars_is_exactly_what_was_omitted() -> None:
    """An exact count, not an estimate: R8 says a guarantee word cites its test,
    and 'what was omitted' is a guarantee."""
    cap = 100
    body = MULTILINE_BODY
    loss = _manifest_loss(body, cap)
    out = _md(body, cap)
    kept = [ln for ln in body.split("\n") if ln in out]
    survived = len("\n".join(kept))
    assert loss["truncated_chars"] == len(body) - survived


def test_the_manifest_stays_json_serializable() -> None:
    json.dumps(render.build_manifest(_session(MULTILINE_BODY), _options(100)))


# --- reach: the matrix-opened compact variant ------------------------------


def test_the_cap_applies_in_the_full_variant_by_default() -> None:
    assert BLOB_BODY not in _md(BLOB_BODY, 100)


def test_the_cap_reaches_a_matrix_opened_compact_variant() -> None:
    """DESIGN 15 block 3, verbatim: the cap applies wherever a tool-result block
    renders, "full by default; compact if the matrix opened it"."""
    options = _options(100, tool_output_compact=True)
    _full, compact = render.render_markdown(_session(BLOB_BODY), options)
    assert "z" in compact, "the matrix did not open tool output in compact"
    assert BLOB_BODY not in compact, "the cap did not reach the compact variant"


def test_the_cap_has_no_variant_form() -> None:
    """One cap, variant-agnostic (block 3's own words). A `_compact` sibling
    would contradict the contract, not extend it."""
    fields = set(render.RenderOptions().__dataclass_fields__)
    assert "tool_output_max_chars" in fields
    assert "tool_output_max_chars_compact" not in fields


# --- projection-only, by construction --------------------------------------


def test_the_stored_payload_is_untouched_by_a_capped_render(tmp_path: Path) -> None:
    """The one invariant this product exists for. Truncation is a rendering
    choice and the store is read-only, so a capped render must leave the source
    bytes hash-identical."""
    data = _session(BLOB_BODY)
    before = store.sha256_hex(data)
    render.render_markdown(data, _options(50))
    render.render_html(data, _options(50))
    render.build_manifest(data, _options(50))
    assert store.sha256_hex(data) == before


# --- validation -------------------------------------------------------------


def test_a_negative_cap_in_config_is_a_config_load_error(tmp_path: Path) -> None:
    cfg = tmp_path / "xdg" / "cc-warehouse"
    cfg.mkdir(parents=True)
    (cfg / "config.toml").write_text("[render]\ntool_output_max_chars = -5\n")
    config = load_config(xdg_config_home=tmp_path / "xdg", env={"HOME": str(tmp_path)})
    assert any("tool_output_max_chars" in problem for problem in config.config_errors)
    assert config.render_tool_output_max_chars == 0, "an invalid cap keeps the default"


def test_a_non_integer_cap_in_config_is_a_config_load_error(tmp_path: Path) -> None:
    cfg = tmp_path / "xdg" / "cc-warehouse"
    cfg.mkdir(parents=True)
    (cfg / "config.toml").write_text('[render]\ntool_output_max_chars = "lots"\n')
    config = load_config(xdg_config_home=tmp_path / "xdg", env={"HOME": str(tmp_path)})
    assert any("tool_output_max_chars" in problem for problem in config.config_errors)
    assert config.render_tool_output_max_chars == 0
