"""Oracle tests: thinking withheld upstream, surfaced and overridable (ticket 20).

41,458 of 43,060 real thinking blocks arrive with `thinking: ""`. The text was
never delivered to this machine (claude-code issue 30958, v2.1.69, 2026-03-05),
so nothing was lost at capture time for 96% of the corpus; something never
arrived. Wording matters here in exactly the direction FINDINGS F6 bans.

Contract: DESIGN section 6 (entry-type coverage, manifest telemetry); FINDINGS
F6 (loss is never silent); DESIGN 15 shared rule (c), flag = key with dashes;
principal ruling 2026-08-02, option 4 plus an operator override.
"""

import json
from typing import cast

from cc_warehouse.config import THINKING_KEY, WORD_KEYS, word_problem
from cc_warehouse.parser import build_conversation
from cc_warehouse.render import RenderOptions, build_manifest, render_html, render_markdown
from conftest import entry, jsonl, matrix_session, run_cli

UUID_W = "c1111111-2222-3333-4444-555555555551"
CWD = "/home/alice/projects/widget"

CAPTION = "caption"
MARKER = "marker"
OFF = "off"


def withheld_session(
    *, empties: int = 3, with_text: bool = False, with_tool: bool = False
) -> bytes:
    """A session whose assistant reply carries empty thinking blocks.

    Shape copied verbatim from real data: `thinking` is the empty string and the
    signature is present, which is what the corpus carries 41,458 times. A real
    signature is ~2,412 characters; a short stand-in is used because nothing
    here reads it, and nothing here is ALLOWED to read it (ticket 20 non-scope).
    """
    blocks: list[dict[str, object]] = [{"type": "text", "text": "Working on it."}]
    if with_text:
        blocks.insert(
            0,
            {"type": "thinking", "thinking": "READABLETHOUGHT here", "signature": "Ev"},
        )
    if with_tool:
        blocks.insert(
            0,
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
        )
    for i in range(empties):
        blocks.insert(0, {"type": "thinking", "thinking": "", "signature": f"Ev{i}QVCpMB"})
    return jsonl(
        entry(
            "user",
            "Audit the widget",
            "2026-01-05T10:00:00.000Z",
            session_id=UUID_W,
            cwd=CWD,
            gitBranch="main",
            version="2.1.198",
        ),
        entry(
            "assistant",
            blocks,
            "2026-01-05T10:00:05.000Z",
            session_id=UUID_W,
            cwd=CWD,
        ),
    )


def opts(mode: str) -> RenderOptions:
    return RenderOptions(thinking_withheld=mode)


def md(data: bytes, mode: str) -> tuple[str, str]:
    # render_markdown returns UTF-8 bytes (ticket 28.9, Fix A); decode once
    # here so every test in this file keeps comparing plain text.
    full, compact = render_markdown(data, opts(mode))
    return full.decode("utf-8"), compact.decode("utf-8")


def html(data: bytes, mode: str) -> tuple[str, str]:
    full, compact = render_html(data, opts(mode))
    return full.decode("utf-8"), compact.decode("utf-8")


# ---------------------------------------------------------------------------
# 1. The block reaches the model at all
# ---------------------------------------------------------------------------


def test_an_empty_thinking_block_reaches_the_conversation_model() -> None:
    """Before this ticket `_assistant_blocks` produced NO block for an empty
    thinking field, so the count was unrecoverable downstream. Everything else
    here depends on this being true first."""
    conv = build_conversation(withheld_session(empties=3))
    kinds = [b.kind for t in conv.turns for b in t.blocks]
    assert kinds.count("thinking_withheld") == 3, kinds
    assert conv.withheld_thinking == 3


def test_a_text_bearing_thinking_block_is_still_an_ordinary_thought() -> None:
    conv = build_conversation(withheld_session(empties=2, with_text=True))
    kinds = [b.kind for t in conv.turns for b in t.blocks]
    assert kinds.count("thinking") == 1, kinds
    assert kinds.count("thinking_withheld") == 2, kinds
    assert conv.withheld_thinking == 2


# ---------------------------------------------------------------------------
# 2 and 3. The default adds NO new lines, only a caption bit, in BOTH emitters
# ---------------------------------------------------------------------------


def test_the_default_adds_no_lines_when_the_phase_already_prints_a_header() -> None:
    """The ruling's whole point, and the COMMON case: thinking is followed by
    tool calls in the same phase, so the header is already there and the fact
    joins it for free."""
    data = withheld_session(empties=3, with_tool=True)
    full_default, _ = md(data, CAPTION)
    full_off, _ = md(data, OFF)
    assert "3 thinking withheld" in full_default
    assert len(full_default.splitlines()) == len(full_off.splitlines())


def test_a_withheld_only_phase_costs_exactly_one_breadcrumb_line() -> None:
    """The honest exception, asserted rather than glossed. When a phase contains
    NOTHING but withheld thinking there is no existing header to join, so one
    breadcrumb line appears. Suppressing it instead would put the fact back in
    the dark, which is the whole thing this ticket exists to stop. One line per
    affected phase is still three orders of magnitude below the rejected
    per-block option."""
    data = withheld_session(empties=3)
    default = md(data, CAPTION)[0].splitlines()
    off = md(data, OFF)[0].splitlines()
    added = [line for line in default if line not in off]
    assert added == ["> \N{JIGSAW PUZZLE PIECE} Worked \N{MIDDLE DOT} 3 thinking withheld"]


def test_the_caption_bit_reaches_the_html_page_too() -> None:
    """Both emitters build their phase header from the same `_PhaseMeta.head()`,
    so this holds by construction. Asserted anyway: the standing lesson from
    slice 14 is that a fix applied to one emitter and not the other passes a
    green suite."""
    page, _ = html(withheld_session(empties=3), CAPTION)
    assert "3 thinking withheld" in page


def test_the_caption_bit_is_singular_for_one_block() -> None:
    full, _ = md(withheld_session(empties=1), CAPTION)
    assert "1 thinking withheld" in full
    assert "1 thinking withhelds" not in full


# ---------------------------------------------------------------------------
# 4. `marker` emits one line per block, in both emitters
# ---------------------------------------------------------------------------


def test_marker_mode_emits_one_line_per_block() -> None:
    """Counted on the BODY sentence, not on the words "thinking withheld": every
    HTML row prints its label and its body, so the label phrase legitimately
    appears twice per row and counting it would measure the markup, not the
    blocks."""
    data = withheld_session(empties=3)
    full, _ = md(data, MARKER)
    assert full.count("no text was provided for this block") == 3
    page, _ = html(data, MARKER)
    assert page.count("no text was provided for this block") == 3


def test_marker_mode_does_not_also_print_the_caption_bit() -> None:
    """The three positions are exclusive. Counting a thing twice in one file is
    its own small dishonesty."""
    full, _ = md(withheld_session(empties=3), MARKER)
    assert "3 thinking withheld" not in full


def test_marker_wording_never_claims_the_text_was_lost() -> None:
    """For 96% of the corpus the text never arrived. Saying "lost" or "dropped"
    would be an overclaim about our own behaviour, which is F6 pointed inward."""
    full, _ = md(withheld_session(empties=1), MARKER)
    lowered = full.lower()
    for word in ("lost", "dropped", "discarded", "removed"):
        assert word not in lowered, word


# ---------------------------------------------------------------------------
# 5. `off` emits nothing in either emitter
# ---------------------------------------------------------------------------


def test_off_emits_nothing_in_markdown_or_html() -> None:
    data = withheld_session(empties=3)
    full, _ = md(data, OFF)
    page, _ = html(data, OFF)
    assert "withheld" not in full
    assert "withheld" not in page


# ---------------------------------------------------------------------------
# 6. The manifest counts identically at every position
# ---------------------------------------------------------------------------


def test_the_manifest_counts_the_same_at_every_position() -> None:
    """Display is a choice; the count is a fact. `off` hides it from the reader
    and must not hide it from the record."""
    data = withheld_session(empties=3)
    for mode in (CAPTION, MARKER, OFF):
        manifest = build_manifest(data, opts(mode))
        withheld = cast("dict[str, object]", manifest["withheld"])
        assert withheld == {"thinking_blocks": 3}, mode


def test_withheld_is_a_top_level_key_not_a_loss_amendment() -> None:
    """Same reasoning as ticket 18's `unrecognised`: it was not lost by us, so
    filing it under `loss` would be the guarantee drift F6 exists to ban. The
    frozen loss set stays at four."""
    manifest = build_manifest(withheld_session(empties=2), opts(CAPTION))
    assert set(cast("dict[str, object]", manifest["loss"])) == {
        "skipped_lines",
        "truncated_blocks",
        "truncated_chars",
        "unencodable_chars",
    }
    assert "withheld" in manifest


def test_a_session_with_no_withheld_thinking_reports_zero() -> None:
    manifest = build_manifest(matrix_session(), opts(CAPTION))
    assert manifest["withheld"] == {"thinking_blocks": 0}


# ---------------------------------------------------------------------------
# 7. The compact variants never show it, at any position
# ---------------------------------------------------------------------------


def test_the_compact_variants_never_show_it() -> None:
    """Compact is prose-only by contract and thinking is welded OFF there
    (DESIGN 6). A withheld-thinking note is still a note about thinking."""
    data = withheld_session(empties=3)
    for mode in (CAPTION, MARKER, OFF):
        _, compact_md = md(data, mode)
        _, compact_page = html(data, mode)
        assert "withheld" not in compact_md, mode
        assert "withheld" not in compact_page, mode


# ---------------------------------------------------------------------------
# 8. The flag: bijection, legal values, and refusal of an illegal one
# ---------------------------------------------------------------------------


def test_the_key_carries_three_positions_and_defaults_to_caption() -> None:
    allowed, default, _blurb = WORD_KEYS[THINKING_KEY]
    assert set(allowed) == {CAPTION, MARKER, OFF}
    assert default == CAPTION
    assert RenderOptions().thinking_withheld == CAPTION


def test_the_flag_spelling_is_the_bijection() -> None:
    """Shared rule (c) from DESIGN 15, 2026-08-01: flag = key with dashes, zero
    exceptions. `--thinking-withheld` is not a spelling of anything else."""
    assert THINKING_KEY == "thinking_withheld"
    result = run_cli(["build", "-h"])
    assert "--thinking-withheld" in result.out
    assert "caption|marker|off" in result.out


def test_an_illegal_value_is_named_with_its_legal_alternatives() -> None:
    problem = word_problem(THINKING_KEY, "sometimes")
    assert problem is not None
    assert "sometimes" in problem
    for word in (CAPTION, MARKER, OFF):
        assert word in problem


def test_a_legal_value_has_no_problem() -> None:
    for word in (CAPTION, MARKER, OFF):
        assert word_problem(THINKING_KEY, word) is None


def test_the_cli_refuses_an_illegal_value_before_doing_any_work() -> None:
    """Flags are validated UP FRONT as a usage error, unlike a config file whose
    problems are recorded so a capture can still run (R5). The asymmetry is
    deliberate and this is the flag half of it."""
    result = run_cli(["build", "--thinking-withheld", "sometimes"])
    assert result.code != 0
    assert "thinking_withheld" in (result.err + result.out)


def test_the_three_config_declarations_of_the_default_agree() -> None:
    """The default is declared in three independent places: the WORD_KEYS table
    the loader validates against, the Config dataclass field, and RenderOptions,
    which sits BELOW config.py and must not import it. Independent, but not
    allowed to disagree."""
    from cc_warehouse.config import Config

    _allowed, default, _blurb = WORD_KEYS[THINKING_KEY]
    bare = Config(root=__import__("pathlib").Path("/tmp/unused"))
    assert getattr(bare, f"render_{THINKING_KEY}") == default
    assert getattr(RenderOptions(), THINKING_KEY) == default


# ---------------------------------------------------------------------------
# 9. Nothing else moves
# ---------------------------------------------------------------------------


def test_a_text_bearing_thought_renders_identically_at_every_position() -> None:
    """The override governs WITHHELD blocks only. A real thought is a real
    thought whatever this key says."""
    data = withheld_session(empties=0, with_text=True)
    rendered = {mode: md(data, mode)[0] for mode in (CAPTION, MARKER, OFF)}
    assert len(set(rendered.values())) == 1
    assert "READABLETHOUGHT" in rendered[CAPTION]


def test_matrix_session_is_untouched_at_the_default() -> None:
    """matrix_session's thinking block carries real text, so it produces no
    withheld block and no caption bit. tests/golden/matrix-anchor is therefore
    expected to hold byte for byte. If this fails the change is not additive and
    the anchor is NOT the thing to regenerate."""
    conv = build_conversation(matrix_session())
    assert conv.withheld_thinking == 0
    full, _ = md(matrix_session(), CAPTION)
    assert "withheld" not in full


def test_the_manifest_config_block_records_the_position_used() -> None:
    """`config` in the manifest is the RenderOptions actually used, so a reader
    can tell whether a transcript with no withheld note had none or was rendered
    with the note off."""
    manifest = build_manifest(withheld_session(empties=2), opts(OFF))
    config = cast("dict[str, object]", manifest["config"])
    assert config[THINKING_KEY] == OFF
    assert json.dumps(manifest)
