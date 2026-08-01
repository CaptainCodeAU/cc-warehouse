"""Oracle tests: HTML chrome initial states (slice 15, block 2).

Contract: DESIGN section 15 entry 2026-08-01, block 2, plus shared rules (c)
flag = key with dashes and (d) chrome keys are page-level and VARIANT-AGNOSTIC,
so none of them has a `_full` or `_compact` form. DESIGN section 8 supplies the
key map and the defaults sentence: large / small / expanded / closed.

Every chrome element stays on the page (exporter parity); only the STARTING
position moves. Values are words, never the DOM's s/m/l letters, because config
is a human surface. LocalStorage interplay: config sets the fallback a fresh
browser sees, and a reader's own clicks win thereafter.

Block 4 (`html_dates`) is NOT here. Ticket 15 asks for two things that cannot
both be true - defaults byte-identical to post-slice-14 output, AND the date
conversion JS present by default - and that fork is the principal's to settle.
The four keys below are all default-PRESERVING, so they land without needing it.

Seams: `render.render_html`, `render.render_markdown`, `config.load_config`,
`build.render_options`, and `ccw` itself. The emitted JS is read back out of the
rendered page, which is output, not an internal.
"""

from pathlib import Path

import pytest

from cc_warehouse import build, render
from cc_warehouse.config import load_config
from conftest import matrix_session, run_ccw

# (config key, the word values it accepts, its default). The flag is the key
# with dashes and the config key is flat in [render], exactly like every other.
CHROME_KEYS = (
    ("html_width", ("small", "medium", "large"), "large"),
    ("html_font", ("small", "medium", "large"), "small"),
    ("html_turns", ("expanded", "collapsed"), "expanded"),
    ("details", ("closed", "open"), "closed"),
)

# Word -> the letter the DOM and localStorage already use. The mapping exists so
# the CONFIG stays human ("medium"), never the s/m/l the buttons carry.
SIZE_LETTER = {"small": "s", "medium": "m", "large": "l"}


def _pages(**chrome: object) -> dict[str, str]:
    options = render.RenderOptions(**chrome)  # pyright: ignore[reportArgumentType]
    full_md, compact_md = render.render_markdown(matrix_session(), options)
    full_html, compact_html = render.render_html(matrix_session(), options)
    return {
        "transcript.md": full_md,
        "transcript.compact.md": compact_md,
        "conversation.html": full_html,
        "conversation.compact.html": compact_html,
    }


def _toggler_call(page: str, key: str) -> str:
    """The one emitted `toggler(...)` line for a chrome key, read off the page."""
    for line in page.splitlines():
        if line.strip().startswith(f'toggler("{key}"'):
            return line.strip()
    raise AssertionError(f"no toggler call for {key} in the emitted page")


# --- defaults: the four keys exist and change nothing until asked -----------


@pytest.mark.parametrize(("key", "values", "default"), CHROME_KEYS)
def test_chrome_key_defaults_to_the_contract_value(
    key: str, values: tuple[str, ...], default: str
) -> None:
    """DESIGN 8's defaults sentence: large / small / expanded / closed."""
    assert default in values
    assert getattr(render.RenderOptions(), key) == default
    assert getattr(load_config(env={"HOME": "/home/alice"}, no_config=True), f"render_{key}") == (
        default
    )


@pytest.mark.parametrize("name", (
    "transcript.md", "transcript.compact.md", "conversation.html", "conversation.compact.html",
))
def test_chrome_defaults_keep_the_slice_14_anchor(name: str) -> None:
    """The four chrome keys move only STARTING positions, and their defaults are
    the positions v1 already had, so an empty config still renders the pre-v1.1
    bytes (shared rule b). The anchor is reused, never regenerated."""
    golden = Path(__file__).resolve().parent / "golden" / "matrix-anchor" / name
    assert _pages()[name] == golden.read_text(encoding="utf-8")


def test_chrome_keys_have_no_variant_forms() -> None:
    """Shared rule (d): chrome keys are page-level and variant-agnostic. A
    `html_width_compact` would be a category error, not a missing feature."""
    fields = set(render.RenderOptions().__dataclass_fields__)
    for key, _values, _default in CHROME_KEYS:
        assert key in fields
        assert f"{key}_compact" not in fields
        assert f"{key}_full" not in fields


# --- html_width / html_font: the JS toggler's fallback ----------------------


@pytest.mark.parametrize("word", ("small", "medium", "large"))
def test_html_width_sets_the_toggler_fallback(word: str) -> None:
    """The width toggler's fallback is what a FRESH browser uses. Config sets it;
    the buttons and localStorage keep working exactly as before."""
    call = _toggler_call(_pages(html_width=word)["conversation.html"], "ccw_html_width")
    assert call.endswith(f'"{SIZE_LETTER[word]}");'), call


@pytest.mark.parametrize("word", ("small", "medium", "large"))
def test_html_font_sets_the_toggler_fallback(word: str) -> None:
    call = _toggler_call(_pages(html_font=word)["conversation.html"], "ccw_html_font")
    assert call.endswith(f'"{SIZE_LETTER[word]}");'), call


def test_the_config_word_never_reaches_the_page_as_a_word() -> None:
    """Values are words in config and LETTERS in the DOM (the frozen decision).
    The page must not start carrying `medium`, or the buttons and the saved
    localStorage value would disagree about what they mean."""
    page = _pages(html_width="medium", html_font="large")["conversation.html"]
    assert '"m");' in page
    assert '"l");' in page
    assert "medium" not in page
    assert 'data-w="m"' in page, "the exporter's own buttons are untouched"


def test_localstorage_still_wins_after_first_paint() -> None:
    """The reader's own clicks beat the config default. The emitted JS must keep
    reading saved-THEN-fallback; reversing that order would make config
    overwrite a choice the reader already made."""
    page = _pages(html_width="small")["conversation.html"]
    assert "localStorage.getItem(key) || fallback" in page


# --- html_turns: the collapsed class at render time ------------------------


def test_html_turns_collapsed_marks_every_turn() -> None:
    """`.turn.collapsed` is already a live CSS state the toolbar toggles; this
    key only decides whether the page STARTS in it."""
    page = _pages(html_turns="collapsed")["conversation.html"]
    opens = [ln for ln in page.splitlines() if ln.startswith('<section class="turn')]
    assert opens, "no turn sections on the page"
    for line in opens:
        assert "collapsed" in line, line


def test_html_turns_expanded_is_the_untouched_default() -> None:
    page = _pages(html_turns="expanded")["conversation.html"]
    opens = [ln for ln in page.splitlines() if ln.startswith('<section class="turn')]
    assert opens
    for line in opens:
        assert "collapsed" not in line, line


# --- details: the one knob that reaches markdown too -----------------------


@pytest.mark.parametrize("name", ("conversation.html", "conversation.compact.html"))
def test_details_open_reaches_both_html_variants(name: str) -> None:
    pages = _pages(details="open")
    assert "<details open>" in pages[name]
    assert "<details>" not in pages[name]


@pytest.mark.parametrize("name", ("transcript.md", "transcript.compact.md"))
def test_details_open_reaches_both_markdown_variants(name: str) -> None:
    """`details` is deliberately UNPREFIXED (not `html_details`) because the
    initial <details> state is emitted MARKUP and reaches the markdown files
    too. Honest naming was the frozen decision; this is what it names."""
    pages = _pages(details="open")
    assert "<details open>" in pages[name]
    assert "<details>" not in pages[name]


def test_an_opened_details_tag_is_not_escaped_into_visible_text() -> None:
    """The markdown-to-HTML pass only lets through the block HTML it emits
    itself, matched against a whitelist. An opened tag that the whitelist did
    not anticipate would arrive on the page as literal `&lt;details open&gt;`
    text - visible, broken, and green under every other test here."""
    page = _pages(details="open")["conversation.html"]
    assert "&lt;details" not in page
    assert "&lt;/details&gt;" not in page


def test_details_closed_is_the_untouched_default() -> None:
    for name, text in _pages(details="closed").items():
        assert "<details open>" not in text, name


# --- config and CLI plumbing ------------------------------------------------


@pytest.mark.parametrize(("key", "values", "_default"), CHROME_KEYS)
def test_chrome_key_reaches_render_options_from_config(
    tmp_path: Path, key: str, values: tuple[str, ...], _default: str
) -> None:
    """Flat `[render]` keys, layering like every other (shared rule a)."""
    cfg = tmp_path / "xdg" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    chosen = values[-1] if values[0] == getattr(render.RenderOptions(), key) else values[0]
    (cfg / "config.toml").write_text(f'[render]\n{key} = "{chosen}"\n')
    config = load_config(xdg_config_home=tmp_path / "xdg", env={"HOME": str(tmp_path)})
    assert getattr(build.render_options(config), key) == chosen


@pytest.mark.parametrize(("key", "values", "_default"), CHROME_KEYS)
def test_chrome_flag_is_the_key_with_dashes(
    ccw_env: dict[str, str], tmp_path: Path, key: str, values: tuple[str, ...], _default: str
) -> None:
    """Shared rule (c) again, this time for VALUE-taking flags."""
    source = tmp_path / f"{key}.jsonl"
    source.write_bytes(matrix_session())
    out = tmp_path / key
    flag = "--" + key.replace("_", "-")
    result = run_ccw(["render", str(source), "--out", str(out), flag, values[-1]], ccw_env)
    assert result.code == 0, result.err
    assert (out / "conversation.html").exists()


@pytest.mark.parametrize(("key", "_values", "_default"), CHROME_KEYS)
def test_an_invalid_chrome_value_on_a_flag_is_a_usage_error(
    ccw_env: dict[str, str], tmp_path: Path, key: str, _values: tuple[str, ...], _default: str
) -> None:
    """Words, never the DOM's letters: `--html-width l` is exactly the mistake
    the word-values decision exists to catch, so it must fail loudly rather than
    silently fall back to a default."""
    source = tmp_path / f"bad-{key}.jsonl"
    source.write_bytes(matrix_session())
    out = tmp_path / f"bad-{key}"
    flag = "--" + key.replace("_", "-")
    result = run_ccw(["render", str(source), "--out", str(out), flag, "l"], ccw_env)
    assert result.code == 1, result.out
    assert result.err.startswith("Error: "), result.err
    assert not out.exists(), "a usage error must not write a projection"


@pytest.mark.parametrize(("key", "_values", "_default"), CHROME_KEYS)
def test_an_invalid_chrome_value_in_config_is_a_config_load_error(
    tmp_path: Path, key: str, _values: tuple[str, ...], _default: str
) -> None:
    """A key-shape problem travels in Config.config_errors rather than raising:
    load_config stays best-effort so a broken config can never stop a capture
    from storing a session (R5). The apply-class commands are what refuse."""
    cfg = tmp_path / "xdg" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(f'[render]\n{key} = "nonsense"\n')
    config = load_config(xdg_config_home=tmp_path / "xdg", env={"HOME": str(tmp_path)})
    assert any(key in problem for problem in config.config_errors), config.config_errors
    assert getattr(config, f"render_{key}") == _default, "an invalid value keeps the default"


@pytest.mark.parametrize("verb", ("build", "render"))
def test_verb_help_lists_the_chrome_flags_with_their_words(
    ccw_env: dict[str, str], verb: str
) -> None:
    result = run_ccw([verb, "-h"], ccw_env)
    assert result.code == 0, result.err
    for key, values, _default in CHROME_KEYS:
        dashed = "--" + key.replace("_", "-")
        assert dashed in result.out, f"{dashed} missing from `ccw {verb} -h`"
        assert "|".join(values) in result.out, f"{dashed} does not show its word values"
