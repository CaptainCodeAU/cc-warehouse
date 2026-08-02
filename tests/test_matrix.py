"""Oracle tests: the per-variant content matrix (slice 14).

Contract: DESIGN section 15 entry 2026-08-01, block 1 ("Per-file matrix", truer
name per-VARIANT matrix) and shared rules (a) flat keys, (b) an unsuffixed key
keeps its v1 meaning and an empty config renders byte-identical output before
and after v1.1, (c) flag spelling is the mechanical bijection flag = key with
dashes. DESIGN section 8 supplies the key map and the defaults sentence: the
full-variant toggles default ON, the `_compact` toggles default OFF.

The matrix is variant x toggle. Compact's hard-coded drops in
`render._compact_policy` become its DEFAULTS, changeable by five new keys; the
unsuffixed keys keep driving the full variant only. NON-SCOPE (stated in the
entry): thinking has no key on either variant, so nothing here asserts one.

Every test goes through a public seam -- `render.render_markdown`,
`render.render_html`, `render.build_manifest`, `build.render_options`,
`config.load_config`, and `ccw` itself -- never a private helper.
"""

import difflib
import json
from pathlib import Path

import pytest

from cc_warehouse import build, render
from cc_warehouse.config import Config, load_config
from conftest import matrix_session, rich_session, run_ccw

GOLDEN = Path(__file__).resolve().parent / "golden" / "matrix-anchor"

# The four projected files, in the order build.write_projection emits them.
PROJECTION_FILES = (
    "transcript.md",
    "transcript.compact.md",
    "conversation.html",
    "conversation.compact.html",
)

# One content class per row: (config key stem, the marker that class's block
# carries in conftest.matrix_session). The compact key is always the stem plus
# `_compact` and its flag is that key with dashes (shared rule c).
CONTENT_CLASSES = (
    ("subagents", "SUBAGENTMARKER"),
    ("attachments", "ATTACHMARKER"),
    ("commands", "COMMANDMARKER"),
    ("extras", "EXTRAMARKER"),
    ("tool_output", "TOOLSTDOUTMARKER"),
)

# Where a stem and the RenderOptions field its UNSUFFIXED key drives disagree.
# Exactly one class does: the `tool_output` key has driven a field called
# `toolresult_diff` since slice 6. That predates this slice and is left alone --
# the field name is internal, the manifest `config` block that exposes it is
# frozen v1 surface, and DESIGN 8 freezes CONFIG keys, not dataclass attributes.
# The NEW fields all match their keys, so the bijection holds where this slice
# creates it.
_FULL_FIELD = {"tool_output": "toolresult_diff"}


def _diff(name: str, expected: str, produced: str) -> str:
    """A readable unified diff, so an anchor break says WHAT moved, not just that
    something did (the suite's diagnose-mechanically rule)."""
    delta = difflib.unified_diff(
        expected.splitlines(), produced.splitlines(),
        fromfile=f"golden/{name}", tofile=f"produced/{name}", lineterm="",
    )
    return f"{name} is no longer byte-identical:\n" + "\n".join(list(delta)[:60])


def _rendered(data: bytes, options: render.RenderOptions) -> dict[str, str]:
    full_md, compact_md = render.render_markdown(data, options)
    full_html, compact_html = render.render_html(data, options)
    produced = (full_md, compact_md, full_html, compact_html)
    return dict(zip(PROJECTION_FILES, produced, strict=True))


def _options(**kwargs: object) -> render.RenderOptions:
    """RenderOptions built from a computed field name (the tests sweep the five
    classes rather than naming each field), which is the one thing pyright
    cannot check for us."""
    return render.RenderOptions(**kwargs)  # pyright: ignore[reportArgumentType]


def _variant_line(markdown: str) -> str:
    """The compact header's `Variant:` row: the one sentence the file says about
    itself."""
    return markdown.split("**Variant:**")[1].split("\n")[0]


# --- the regression anchor -------------------------------------------------
# Purely additive is the whole promise of shared rule (b). These goldens were
# generated from the slice-13 tree (c075c5d, src/ clean) BEFORE any slice-14
# edit, so they started as literally the pre-slice bytes. Slices 15-17 reuse
# them. They are never regenerated to make a change pass -- a break here means
# the change moved DEFAULT output, which is a ruling, not a fixup.
#
# ONE approved re-baseline so far, recorded so the anchor never quietly becomes
# "whatever the code does now":
#
#   2026-08-01, slice 15 block 4, principal's ruling (option 1 of a presented
#   fork). `html_dates` defaults to `local`, and DESIGN 15 block 4 froze that
#   default on the reader-respect principle, so the two HTML files gained the
#   date-conversion script. The delta was reviewed before the goldens moved:
#   +14 lines each, ZERO deletions, zero modified lines, and both MARKDOWN
#   goldens untouched (they still hold their original pre-slice-14 bytes).
#
#   2026-08-01, slice 15 again, COMPLETING the same approved change rather than
#   making a new one. A correctness census found the date pass reached the turn
#   stamps but not the header's own `Captured:` span, so one page showed two
#   clocks with nothing saying which was which. Wrapping that span moved ONE
#   line in each HTML file. All 21 data-copy-src payloads stayed byte-identical
#   and the header payload still reproduces transcript.md verbatim, so the
#   copy-as-markdown invariant is untouched; the markdown goldens did not move.


@pytest.mark.parametrize("name", PROJECTION_FILES)
def test_default_options_render_the_pre_slice_bytes(name: str) -> None:
    produced = _rendered(matrix_session(), render.RenderOptions())[name]
    expected = (GOLDEN / name).read_text(encoding="utf-8")
    assert produced == expected, _diff(name, expected, produced)


@pytest.mark.parametrize("name", PROJECTION_FILES)
def test_empty_config_renders_the_pre_slice_bytes(tmp_path: Path, name: str) -> None:
    """The same anchor reached the other way: through load_config with no config
    file and no flags. Defaults and the config path must not disagree."""
    config = load_config(env={"HOME": str(tmp_path)}, no_config=True)
    produced = _rendered(matrix_session(), build.render_options(config))[name]
    expected = (GOLDEN / name).read_text(encoding="utf-8")
    assert produced == expected, _diff(name, expected, produced)


def test_the_anchor_session_carries_every_content_class() -> None:
    """The anchor only anchors what it exercises. Each class must be present in
    the full variant and absent from the compact one at defaults, or a green
    matrix test below would be proving nothing."""
    files = _rendered(matrix_session(), render.RenderOptions())
    for _stem, marker in CONTENT_CLASSES:
        assert marker in files["transcript.md"], f"{marker} missing from the full variant"
        assert marker in files["conversation.html"], f"{marker} missing from the full page"
        assert marker not in files["transcript.compact.md"], f"{marker} leaked into compact"
        assert marker not in files["conversation.compact.html"], f"{marker} leaked into compact"


# --- the matrix: a compact key opens its class in the compact variant -------


@pytest.mark.parametrize("variant_file", ("transcript.compact.md", "conversation.compact.html"))
@pytest.mark.parametrize(("stem", "marker"), CONTENT_CLASSES)
def test_compact_key_opens_the_class_in_both_compact_files(
    stem: str, marker: str, variant_file: str
) -> None:
    """DESIGN 15 block 1: compact's hard-coded drops become its DEFAULTS.

    Parametrized over BOTH compact files rather than split into two tests,
    because one policy drives both emitters (R9) and a matrix cell that were
    true of only one of them would be the bug worth catching.
    """
    opened = _rendered(matrix_session(), _options(**{f"{stem}_compact": True}))
    assert marker in opened[variant_file]


@pytest.mark.parametrize(("stem", "marker"), CONTENT_CLASSES)
def test_compact_key_leaves_the_full_variant_byte_identical(
    stem: str, marker: str
) -> None:
    """Shared rule (b) read the other way: a `_compact` key is the door into
    compact ONLY. The full variant's bytes may not move."""
    data = matrix_session()
    base = _rendered(data, render.RenderOptions())
    opened = _rendered(data, _options(**{f"{stem}_compact": True}))
    assert opened["transcript.md"] == base["transcript.md"], marker
    assert opened["conversation.html"] == base["conversation.html"], marker


@pytest.mark.parametrize(("stem", "marker"), CONTENT_CLASSES)
def test_unsuffixed_key_off_strips_full_and_leaves_compact_untouched(
    stem: str, marker: str
) -> None:
    """Shared rule (b): an UNSUFFIXED key keeps its v1 meaning, the full variants.
    Turning it off must CHANGE the full variant and must not reach into the
    compact variant in either direction.

    "Changes the full variant" rather than "removes the marker" because the five
    classes do not all mean the same thing: four gate whether their block renders
    at all, while `tool_output` chooses between the structured stdout/stderr
    rendering and the raw result fence. That is the v1 meaning this rule
    preserves, not one this slice gets to redefine.
    """
    data = matrix_session()
    base = _rendered(data, render.RenderOptions())
    stripped = _rendered(data, _options(**{_FULL_FIELD.get(stem, stem): False}))
    assert marker in base["transcript.md"]
    assert stripped["transcript.md"] != base["transcript.md"], f"{stem} did nothing"
    assert stripped["transcript.compact.md"] == base["transcript.compact.md"]
    assert stripped["conversation.compact.html"] == base["conversation.compact.html"]


def test_unsuffixed_subagents_off_actually_strips_the_full_variant() -> None:
    """The v1 meaning still bites: --no-subagents drops sub-agent steps from the
    full variant. Named separately from the loop above because four of the five
    classes lose only their block while sub-agents also lose their phase."""
    data = matrix_session()
    full_off, _ = render.render_markdown(data, render.RenderOptions(subagents=False))
    assert "SUBAGENTMARKER" not in full_off
    assert "SUBAGENTREPLY" not in full_off


def test_the_two_variants_are_independent_cells() -> None:
    """The matrix is variant x toggle, not one axis: a class OFF in full and ON in
    compact is a legal, reachable cell."""
    data = matrix_session()
    files = _rendered(data, render.RenderOptions(subagents=False, subagents_compact=True))
    assert "SUBAGENTMARKER" not in files["transcript.md"]
    assert "SUBAGENTMARKER" in files["transcript.compact.md"]


def test_the_compact_markdown_note_never_denies_what_it_carries() -> None:
    """F6, the code overclaiming its own guarantees, applied to the one sentence
    the compact file says about itself.

    v1's note was the fixed string "conversation only, no thinking, tools, or
    reminders". The matrix can now put tool blocks into a compact file, and
    `reminders_compact` has been able to restore reminders since slice 6, so a
    fixed sentence would state the opposite of the file it heads. The default
    wording is unchanged (the anchor proves that); what changes is that the list
    now shrinks to match the policy.
    """
    data = matrix_session()
    _, default_note = render.render_markdown(data, render.RenderOptions())
    assert "no thinking, tools, or reminders." in default_note

    _, with_tools = render.render_markdown(
        data, render.RenderOptions(tool_output_compact=True)
    )
    assert "TOOLSTDOUTMARKER" in with_tools
    assert "tools" not in _variant_line(with_tools)

    _, with_reminders = render.render_markdown(
        rich_session(), render.RenderOptions(reminders_compact="show")
    )
    line = _variant_line(with_reminders)
    assert "reminders" not in line
    assert "compact" in line.lower(), "the word compact stays load-bearing"


def test_the_compact_html_meta_note_never_denies_what_it_carries() -> None:
    """The SAME rule for the SECOND place the compact variant describes itself.

    conversation.compact.html carries its own sentence in the meta strip, worded
    differently from the markdown note ("tool detail" rather than "tools"). The
    first version of this slice derived only the markdown one and left the HTML
    page saying "tool detail omitted" above rendered tool blocks - the same F6
    overclaim, in the emitter nobody looked at. Censusing the class rather than
    fixing the instance is what this test pins.
    """
    data = matrix_session()
    _, default_page = render.render_html(data, render.RenderOptions())
    assert "compact variant, thinking and tool detail omitted" in default_page

    _, with_tools = render.render_html(data, render.RenderOptions(tool_output_compact=True))
    assert "TOOLSTDOUTMARKER" in with_tools, "the page really does carry tool blocks"
    assert "tool detail omitted" not in with_tools
    assert "compact variant, thinking omitted" in with_tools


def test_no_thinking_render_toggle_exists_on_either_variant() -> None:
    """NON-SCOPE, stated in the entry: BRAINSTORM locks thinking ON in full
    variants and compact keeps it welded OFF. A thinking toggle would be its own
    future proposal, so its absence is contract, not an oversight.

    NARROWED 2026-08-02 by principal ruling (DESIGN 15, block 1 non-scope). This
    test previously banned any field whose NAME contained "thinking", which is
    the letter of the line rather than the decision behind it. Ticket 20's
    `thinking_withheld` collided with it while doing something the frozen
    decision never covered: real thinking renders identically at every one of
    its positions, and it governs only how a block whose text NEVER ARRIVED is
    reported. The ruling narrowed the contract; this test follows the contract.
    It was NOT relaxed to make code pass, and the alternative of renaming the key
    to dodge the substring was offered and rejected precisely because it would
    have left this fence defeatable by spelling.

    What is still banned, and is what the decision actually protects: a key that
    turns thinking RENDERING on or off, on either variant. The two assertions
    below are the boundary. `thinking_withheld` is allowed by name; a
    `thinking`/`thinking_compact` pair, or any field whose value space is a
    render on/off for thinking, is not.
    """
    fields = set(render.RenderOptions().__dataclass_fields__)
    banned = {"thinking", "thinking_compact", "thinking_full", "include_thinking"}
    assert not (fields & banned), fields & banned

    # The property the ban exists to protect, asserted directly rather than
    # inferred from a name: thinking renders in full and never in compact, and
    # no position of the one allowed thinking-named key can change that.
    data = matrix_session()
    for position in ("caption", "marker", "off"):
        options = render.RenderOptions(thinking_withheld=position)
        full_md, compact_md = render.render_markdown(data, options)
        assert "deep thoughts about widgets" in full_md, position
        assert "deep thoughts about widgets" not in compact_md, position


# --- config keys (shared rule a: flat, one-level merge) --------------------


def _config_with_every_compact_key_on(tmp_path: Path) -> Config:
    """An XDG config declaring all five flat `[render]` compact keys, resolved."""
    cfg_dir = tmp_path / "xdg" / "cc-warehouse"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    keys = "\n".join(f"{stem}_compact = true" for stem, _m in CONTENT_CLASSES)
    (cfg_dir / "config.toml").write_text(f"[render]\n{keys}\n")
    return load_config(xdg_config_home=tmp_path / "xdg", env={"HOME": str(tmp_path)})


def test_render_options_carry_the_five_compact_keys_from_config(tmp_path: Path) -> None:
    """build.render_options is the one bridge from Config to RenderOptions (R9):
    every compact key must cross it."""
    options = build.render_options(_config_with_every_compact_key_on(tmp_path))
    for stem, _marker in CONTENT_CLASSES:
        assert getattr(options, f"{stem}_compact") is True, stem


def test_config_compact_keys_reach_the_rendered_compact_files(tmp_path: Path) -> None:
    """End to end through the seam the operator actually uses: a flat `[render]`
    key opens every class in both compact files."""
    config = _config_with_every_compact_key_on(tmp_path)
    files = _rendered(matrix_session(), build.render_options(config))
    for _stem, marker in CONTENT_CLASSES:
        assert marker in files["transcript.compact.md"], marker
        assert marker in files["conversation.compact.html"], marker


# --- CLI flags (shared rule c: flag = key with dashes, zero exceptions) ----


def _render_to(env: dict[str, str], tmp_path: Path, name: str, *flags: str) -> dict[str, str]:
    """Run `ccw render <path> --out <dir>` with flags and read the four files back."""
    source = tmp_path / f"{name}.jsonl"
    source.write_bytes(matrix_session())
    out = tmp_path / name
    result = run_ccw(["render", str(source), "--out", str(out), *flags], env)
    assert result.code == 0, result.err
    return {f: (out / f).read_text(encoding="utf-8") for f in PROJECTION_FILES}


@pytest.mark.parametrize(("stem", "marker"), CONTENT_CLASSES)
def test_compact_flag_opens_the_class(
    ccw_env: dict[str, str], tmp_path: Path, stem: str, marker: str
) -> None:
    """`--x-compact` is the key with dashes, and it reaches both compact files."""
    flag = "--" + f"{stem}_compact".replace("_", "-")
    files = _render_to(ccw_env, tmp_path, f"on-{stem}", flag)
    assert marker in files["transcript.compact.md"]
    assert marker in files["conversation.compact.html"]


@pytest.mark.parametrize(("stem", "marker"), CONTENT_CLASSES)
def test_no_compact_flag_beats_the_config_key(
    ccw_env: dict[str, str], tmp_path: Path, stem: str, marker: str
) -> None:
    """DESIGN 8 precedence: a CLI flag is the highest tier, above the config file.
    `--no-x-compact` must win over `x_compact = true`."""
    cfg = Path(ccw_env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(f"[render]\n{stem}_compact = true\n")
    on = _render_to(ccw_env, tmp_path, f"cfg-{stem}")
    assert marker in on["transcript.compact.md"], "the config key did not take effect"
    flag = "--no-" + f"{stem}_compact".replace("_", "-")
    off = _render_to(ccw_env, tmp_path, f"flagoff-{stem}", flag)
    assert marker not in off["transcript.compact.md"]


@pytest.mark.parametrize(("stem", "marker"), CONTENT_CLASSES)
def test_the_compact_x_spelling_does_not_parse(
    ccw_env: dict[str, str], tmp_path: Path, stem: str, marker: str
) -> None:
    """Shared rule (c) is a BIJECTION: `--compact-subagents` is not a spelling of
    `--subagents-compact`. It is not a flag, so it changes nothing."""
    wrong = "--compact-" + stem.replace("_", "-")
    plain = _render_to(ccw_env, tmp_path, f"plain-{stem}")
    misspelled = _render_to(ccw_env, tmp_path, f"wrong-{stem}", wrong)
    assert misspelled == plain
    assert marker not in misspelled["transcript.compact.md"]


@pytest.mark.parametrize(("stem", "marker"), CONTENT_CLASSES)
def test_the_unsuffixed_flag_still_means_full_only(
    ccw_env: dict[str, str], tmp_path: Path, stem: str, marker: str
) -> None:
    """`--no-subagents` keeps its v1 meaning at the CLI too: full variants only.

    Each class's marker is what that class renders BY DEFAULT, so turning the
    unsuffixed key off removes it in all five cases -- for `tool_output` because
    the structured stdout block gives way to the raw result fence, not because
    the tool result disappears."""
    plain = _render_to(ccw_env, tmp_path, f"base-{stem}")
    flag = "--no-" + stem.replace("_", "-")
    stripped = _render_to(ccw_env, tmp_path, f"nofull-{stem}", flag)
    assert marker in plain["transcript.md"]
    assert marker not in stripped["transcript.md"]
    assert stripped["transcript.compact.md"] == plain["transcript.compact.md"]


def test_reminders_compact_flag_maps_to_the_reminders_compact_key(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`--reminders-compact {show|collapse|strip}` is the value-taking member of
    the bijection, over the pre-existing `reminders_compact` key. matrix_session
    carries no reminder, so this one uses rich_session."""
    reminder = "secret internal reminder text"
    source = tmp_path / "reminders.jsonl"
    source.write_bytes(rich_session())

    def compact_with(*flags: str) -> str:
        out = tmp_path / ("out" + "".join(flags).replace("-", ""))
        result = run_ccw(["render", str(source), "--out", str(out), *flags], ccw_env)
        assert result.code == 0, result.err
        return (out / "transcript.compact.md").read_text(encoding="utf-8")

    assert reminder not in compact_with(), "the default is strip"
    shown = compact_with("--reminders-compact", "show")
    collapsed = compact_with("--reminders-compact", "collapse")
    assert reminder in shown
    assert reminder in collapsed
    assert shown != collapsed, "show and collapse must render differently"
    assert reminder not in compact_with("--reminders-compact", "strip")


def test_reminders_compact_flag_does_not_disturb_the_full_variant_flag(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`--reminders` and `--reminders-compact` are different flags: the longer
    spelling must not be swallowed by the shorter one's parsing."""
    source = tmp_path / "both.jsonl"
    source.write_bytes(rich_session())
    out = tmp_path / "both-out"
    result = run_ccw(
        ["render", str(source), "--out", str(out),
         "--reminders", "strip", "--reminders-compact", "show"],
        ccw_env,
    )
    assert result.code == 0, result.err
    reminder = "secret internal reminder text"
    assert reminder not in (out / "transcript.md").read_text(encoding="utf-8")
    assert reminder in (out / "transcript.compact.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("verb", ("build", "render"))
def test_verb_help_lists_the_compact_flags(ccw_env: dict[str, str], verb: str) -> None:
    """Shared rule (c): help text may GROUP flags for readability, never respell
    them. Every compact flag the parser accepts is listed as the key with dashes."""
    result = run_ccw([verb, "-h"], ccw_env)
    assert result.code == 0, result.err
    for stem, _marker in CONTENT_CLASSES:
        dashed = f"{stem}_compact".replace("_", "-")
        assert dashed in result.out, f"--{dashed} missing from `ccw {verb} -h`"
        assert f"--compact-{stem.replace('_', '-')}" not in result.out
    assert "--reminders-compact" in result.out


# --- manifest --------------------------------------------------------------


def test_manifest_config_block_records_the_new_fields() -> None:
    """DESIGN section 6 freezes `config` as the RenderOptions actually used, so a
    per-variant decision is recoverable from the projection alone (F6: no silent
    behaviour). Every new key must appear, with its value."""
    options = _options(**{f"{stem}_compact": True for stem, _m in CONTENT_CLASSES})
    manifest = render.build_manifest(matrix_session(), options)
    config = manifest["config"]
    assert isinstance(config, dict)
    for stem, _marker in CONTENT_CLASSES:
        assert config[f"{stem}_compact"] is True, stem
    defaults = render.build_manifest(matrix_session(), render.RenderOptions())["config"]
    assert isinstance(defaults, dict)
    for stem, _marker in CONTENT_CLASSES:
        assert defaults[f"{stem}_compact"] is False, stem
    json.dumps(manifest)  # the manifest stays JSON-serializable
