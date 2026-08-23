"""Oracle tests: HTML chrome initial states and date display (slice 15).

Contract: DESIGN section 15 entry 2026-08-01, block 2, plus shared rules (c)
flag = key with dashes and (d) chrome keys are page-level and VARIANT-AGNOSTIC,
so none of them has a `_full` or `_compact` form. DESIGN section 8 supplies the
key map and the defaults sentence: large / small / expanded / closed.

Every chrome element stays on the page (exporter parity); only the STARTING
position moves. Values are words, never the DOM's s/m/l letters, because config
is a human surface. LocalStorage interplay: config sets the fallback a fresh
browser sees, and a reader's own clicks win thereafter.

Both blocks live here. Ticket 15 asked for two things that could not both be
true - defaults byte-identical to post-slice-14 output, AND the date conversion
JS present by default - and the principal settled it on 2026-08-01: keep the
frozen `local` default and re-baseline. The four block-2 keys are all
default-PRESERVING; `html_dates` is the one that moved the anchor's two HTML
files, and that move is recorded beside the anchor in test_matrix.py.

The anchor itself is owned by test_matrix.py, which diffs on failure. Nothing
here re-asserts it.

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
# Deliberately a SECOND copy of what config.CHROME_KEYS holds, not an import:
# these tests assert the module's defaults, so taking the expected values from
# the module under test would make them self-certifying.
CHROME_KEYS = (
    ("html_width", ("small", "medium", "large"), "large"),
    ("html_font", ("small", "medium", "large"), "small"),
    ("html_turns", ("expanded", "collapsed"), "expanded"),
    ("details", ("closed", "open"), "closed"),
    ("html_dates", ("local", "iso"), "local"),
)

# Word -> the letter the DOM and localStorage already use. The mapping exists so
# the CONFIG stays human ("medium"), never the s/m/l the buttons carry.
SIZE_LETTER = {"small": "s", "medium": "m", "large": "l"}


def _pages(**chrome: object) -> dict[str, str]:
    # render_markdown/render_html return UTF-8 bytes (ticket 28.9, Fix A);
    # decode once here so every test in this file keeps comparing plain text.
    options = render.RenderOptions(**chrome)  # pyright: ignore[reportArgumentType]
    full_md, compact_md = render.render_markdown(matrix_session(), options)
    full_html, compact_html = render.render_html(matrix_session(), options)
    return {
        "transcript.md": full_md.decode("utf-8"),
        "transcript.compact.md": compact_md.decode("utf-8"),
        "conversation.html": full_html.decode("utf-8"),
        "conversation.compact.html": compact_html.decode("utf-8"),
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


# --- html_dates (block 4): client-side display, ISO markup ------------------
# The determinism argument is the whole design: markup keeps the raw ISO stamp,
# so an unchanged session re-projects to the same bytes forever. A baked local
# time would rewrite the warehouse on every timezone change and every DST
# transition, and would break build.py's incremental byte-compare with it.

ISO_STAMP = "2026-01-05T10:00:00.000Z"
DATE_SCRIPT_MARK = "ccw-local-dates"


def test_html_dates_defaults_to_local() -> None:
    """DESIGN 15 block 4: `html_dates` local|iso, default local. The third
    consecutive product decision on reader-respect, after hljs and the
    prefers-color-scheme candidate."""
    assert render.RenderOptions().html_dates == "local"
    assert load_config(env={"HOME": "/home/alice"}, no_config=True).render_html_dates == "local"


def test_local_emits_the_conversion_pass() -> None:
    assert DATE_SCRIPT_MARK in _pages(html_dates="local")["conversation.html"]


def test_iso_omits_the_conversion_pass() -> None:
    """`iso` is the audit-shaped choice: no JS at all, so what the reader sees is
    exactly what the markup says."""
    assert DATE_SCRIPT_MARK not in _pages(html_dates="iso")["conversation.html"]


@pytest.mark.parametrize("mode", ("local", "iso"))
def test_the_markup_carries_the_raw_iso_stamp_under_both_values(mode: str) -> None:
    """The stamp in the HTML is ISO whichever mode is set: `local` converts in
    the READER's browser, never at render time. This is what keeps the bytes
    deterministic and the incremental build's byte-compare meaningful."""
    page = _pages(html_dates=mode)["conversation.html"]
    assert f'<span class="timestamp">{ISO_STAMP}</span>' in page


@pytest.mark.parametrize("mode", ("local", "iso"))
def test_markdown_files_stay_iso_under_both_values(mode: str) -> None:
    """The machine-adjacent projection keeps the audit form. No JS can reach a
    .md file, so this is structural, but it is the promise block 4 makes."""
    pages = _pages(html_dates=mode)
    for name in ("transcript.md", "transcript.compact.md"):
        assert ISO_STAMP in pages[name], name


def test_the_conversion_keeps_the_iso_stamp_on_hover() -> None:
    """Hover keeps the ISO stamp: the reader can always recover the exact
    recorded instant, which is the whole reason the audit form is preserved."""
    page = _pages(html_dates="local")["conversation.html"]
    assert "title" in page.split(DATE_SCRIPT_MARK)[1][:600]


def test_rendering_never_reads_the_machine_clock_or_timezone() -> None:
    """R12 and the incremental byte-compare both rest on this. A baked local time
    would make the same payload render differently on two machines, or on the
    same machine after a DST change."""
    import ast

    source = (Path(__file__).resolve().parent.parent / "src" / "cc_warehouse" / "render.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    banned = {"now", "today", "utcnow", "astimezone", "localtime", "fromtimestamp"}
    offenders = [
        f"render.py:{node.lineno} {node.func.attr}()"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in banned
    ]
    assert not offenders, f"machine-clock use in rendering: {offenders}"


@pytest.mark.parametrize("mode", ("local", "iso"))
def test_the_same_payload_renders_to_the_same_bytes(mode: str) -> None:
    """The invariant block 4 exists to protect, asserted directly."""
    assert _pages(html_dates=mode) == _pages(html_dates=mode)


def test_the_two_places_config_states_a_chrome_default_agree() -> None:
    """config.py declares each chrome default TWICE: once as a Config dataclass
    field default, once in the CHROME_KEYS table the loader validates against.
    Nothing structural keeps them equal, and a Config built directly (which
    tests do) reads the first while load_config resolves the second, so a drift
    would be invisible until the two disagreed in production."""
    from cc_warehouse.config import CHROME_KEYS as TABLE
    from cc_warehouse.config import Config

    bare = Config(root=Path("/tmp/unused"))
    for key, (_allowed, default, _blurb) in TABLE.items():
        assert getattr(bare, f"render_{key}") == default, key


def test_the_render_layer_agrees_with_the_config_layer_on_defaults() -> None:
    """RenderOptions is the third declaration of the same defaults, and it is
    the one that must stay independent: render.py sits BELOW config.py and must
    not import it. Independent, but not allowed to disagree."""
    from cc_warehouse.config import CHROME_KEYS as TABLE

    options = render.RenderOptions()
    for key, (_allowed, default, _blurb) in TABLE.items():
        assert getattr(options, key) == default, key
