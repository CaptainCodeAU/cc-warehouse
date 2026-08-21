"""Pricing arithmetic, and the hand-rolled xlsx writer."""

from __future__ import annotations

import zipfile
from xml.etree import ElementTree as ET

import collect
import pytest
from xlsx import FMT_INT, FMT_MONEY, Sheet, col_ref, esc, write_workbook

# ------------------------------------------------------------------ pricing


def test_a_dated_model_id_resolves_by_longest_prefix() -> None:
    assert collect.rates_for("claude-haiku-4-5-20251001", "standard") == (1.00, 5.00)
    assert collect.rates_for("claude-opus-5", "standard") == (5.00, 25.00)


def test_an_unknown_model_returns_none_rather_than_zero() -> None:
    """A model released after the price table was read must be VISIBLE, not
    quietly billed at nothing."""
    assert collect.rates_for("claude-unreleased-9", "standard") is None
    assert collect.rates_for(None, "standard") is None


def test_fast_mode_is_priced_higher_where_it_exists() -> None:
    standard = collect.rates_for("claude-opus-5", "standard")
    fast = collect.rates_for("claude-opus-5", "fast")
    assert fast == (10.00, 50.00)
    assert fast[0] > standard[0] and fast[1] > standard[1]


def test_fast_mode_on_a_model_without_fast_rates_falls_back_to_standard() -> None:
    assert collect.rates_for("claude-haiku-4-5", "fast") == (1.00, 5.00)


def test_cache_tiers_are_priced_against_the_models_own_input_rate() -> None:
    r_in, _ = collect.rates_for("claude-opus-5", "standard")
    _, _, cw, cr = collect.turn_cost(
        "claude-opus-5", "standard", 0, 0, cw5=1_000_000, cw1h=0, cread=0
    )
    assert cw == pytest.approx(r_in * collect.CACHE_WRITE_5M)
    _, _, cw1h, _ = collect.turn_cost(
        "claude-opus-5", "standard", 0, 0, cw5=0, cw1h=1_000_000, cread=0
    )
    assert cw1h == pytest.approx(r_in * collect.CACHE_WRITE_1H)
    assert cw1h > cw, "the 1 hour tier costs more; 90% of writes are that tier"
    _, _, _, read = collect.turn_cost(
        "claude-opus-5", "standard", 0, 0, cw5=0, cw1h=0, cread=1_000_000
    )
    assert read == pytest.approx(r_in * collect.CACHE_READ)


def test_an_unknown_model_costs_zero_and_is_recorded() -> None:
    collect._UNPRICED.clear()
    cost = collect.turn_cost("claude-from-the-future", None, 100, 100, 0, 0, 0)
    assert cost == (0.0, 0.0, 0.0, 0.0)
    assert "claude-from-the-future" in collect._UNPRICED


def test_the_synthetic_placeholder_is_free_and_not_flagged_as_unpriced() -> None:
    """`<synthetic>` is a local placeholder for an interrupted reply. No API
    call happened, so zero is correct and it is not a missing price."""
    collect._UNPRICED.clear()
    assert collect.turn_cost("<synthetic>", None, 0, 0, 0, 0, 0) == (0.0, 0.0, 0.0, 0.0)
    assert "<synthetic>" not in collect._UNPRICED


# --------------------------------------------------------------------- xlsx


def test_column_references_roll_over_past_z() -> None:
    assert col_ref(1) == "A"
    assert col_ref(26) == "Z"
    assert col_ref(27) == "AA"
    assert col_ref(52) == "AZ"


def test_xml_special_characters_are_escaped() -> None:
    assert esc('a & b <c> "d"') == "a &amp; b &lt;c&gt; &quot;d&quot;"


def test_control_characters_are_stripped_because_excel_refuses_them() -> None:
    assert "\x07" not in esc("bell\x07here")
    assert esc("tab\tkept") == "tab\tkept"


def test_a_written_workbook_is_a_valid_zip_of_valid_xml(tmp_path) -> None:
    out = tmp_path / "t.xlsx"
    write_workbook(
        out,
        [
            Sheet("A & B", ["name", "n", "cost"], [["x<y>", 5, 1.5]],
                  formats=[0, FMT_INT, FMT_MONEY]),
            Sheet("Second", ["only"], [[1], [2]]),
        ],
        title="test",
    )
    with zipfile.ZipFile(out) as zf:
        assert zf.testzip() is None
        for name in zf.namelist():
            if name.endswith((".xml", ".rels")):
                ET.fromstring(zf.read(name))
        sheet = zf.read("xl/worksheets/sheet1.xml").decode()
    assert "x&lt;y&gt;" in sheet
    assert "<v>5</v>" in sheet, "numbers must stay numbers, not inline strings"


def test_a_sheet_name_is_trimmed_and_illegal_characters_replaced() -> None:
    s = Sheet("a/b:c[d]" + "x" * 40, ["h"], [[1]])
    assert len(s.name) <= 31
    assert not any(ch in s.name for ch in ':\\/?*[]')


def test_an_empty_sheet_still_writes_without_an_autofilter(tmp_path) -> None:
    out = tmp_path / "e.xlsx"
    write_workbook(out, [Sheet("Empty", ["a", "b"], [])], title="t")
    with zipfile.ZipFile(out) as zf:
        body = zf.read("xl/worksheets/sheet1.xml").decode()
    ET.fromstring(body)
    assert "autoFilter" not in body


# --------------------------------------------------- read_usage (extracted)
# These were unreachable while the logic sat inside a 362-line function.


def test_a_missing_usage_block_reads_as_zeros() -> None:
    u = collect.read_usage(None)
    assert (u.input, u.output, u.cache_write, u.cache_read, u.thinking) == (0, 0, 0, 0, 0)
    assert collect.read_usage("not a dict").output == 0


def test_the_cache_tiers_are_kept_apart() -> None:
    u = collect.read_usage(
        {
            "cache_creation_input_tokens": 300,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 100,
                "ephemeral_1h_input_tokens": 200,
            },
        }
    )
    assert (u.cache_write_5m, u.cache_write_1h, u.cache_write) == (100, 200, 300)
    assert u.declared_cache_write == 300


def test_a_split_that_does_not_reconcile_falls_back_to_the_declared_total() -> None:
    u = collect.read_usage(
        {
            "cache_creation_input_tokens": 500,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 1,
                "ephemeral_1h_input_tokens": 1,
            },
        }
    )
    assert u.cache_write == 500, "the declared total wins"
    assert u.cache_write_1h == 0, "and the cheaper tier is assumed"


def test_no_tier_breakdown_bills_the_cheaper_tier() -> None:
    u = collect.read_usage({"cache_creation_input_tokens": 800})
    assert (u.cache_write_5m, u.cache_write_1h) == (800, 0)


def test_thinking_is_clamped_to_output() -> None:
    assert collect.read_usage(
        {"output_tokens": 100, "output_tokens_details": {"thinking_tokens": 900}}
    ).thinking == 100
    assert collect.read_usage(
        {"output_tokens": 900, "output_tokens_details": {"thinking_tokens": 100}}
    ).thinking == 100


def test_server_tool_counts_are_read_when_present_and_zero_when_not() -> None:
    assert collect.read_usage({}).web_search == 0
    u = collect.read_usage(
        {"server_tool_use": {"web_search_requests": 3, "web_fetch_requests": 2}}
    )
    assert (u.web_search, u.web_fetch) == (3, 2)


def test_non_numeric_counters_do_not_crash() -> None:
    u = collect.read_usage({"input_tokens": None, "output_tokens": "many"})
    assert (u.input, u.output) == (0, 0)


def test_tier_and_speed_are_carried_through() -> None:
    u = collect.read_usage({"service_tier": "standard", "speed": "fast"})
    assert (u.service_tier, u.speed) == ("standard", "fast")
