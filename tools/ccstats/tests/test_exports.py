"""The two JSON exports written beside the dashboard page.

`dashboard-data.json` is the page's OWN payload, written from the same string
that gets embedded, so a reader of the file and a reader of the page can never
be looking at different numbers. `stats-facts.json` is the small top-line card
`export.py` writes from `facts.compute`.

Every test here builds a tiny file-backed sqlite with known-by-construction
contents and drives the two commands through their `main(argv)` seam, the same
boundary the rest of this suite uses. Nothing reads the real
`~/.cc-warehouse/stats`, and nothing writes outside `tmp_path`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import collect
import dashboard
import export
import pytest
from common import Out

# The session table comes from `collect.session_ddl()`, never a copy typed here.
# `facts.compute` reads columns the dashboard does not (`tz_offset` among them),
# so a hand-written subset would pass one command and fail the other - which is
# exactly what a hand-written subset did on the first run of this file.
SESSION_DEFAULTS: dict[str, object] = {
    "is_worktree": 0, "engaged_seconds": 600.0, "cost_usd": 1.5,
    "tok_input": 100, "tok_output": 200, "tok_cache_write": 300,
    "tok_cache_read": 400, "tok_thinking": 50,
    "cc_version": "2.1.300", "primary_model": "claude-opus-5",
    "wall_seconds": 900.0, "active_seconds": 700.0,
    "n_user_prompts": 3, "n_tool_uses": 4, "n_assistant_turns": 5,
    "is_subagent": 0, "entrypoint": "cli", "is_real": 1,
    "local_hour": 9, "local_weekday": 2, "tz_offset": "+10:00",
}


def make_db(path: Path) -> None:
    """A two-session database, enough for every query both commands run."""
    conn = sqlite3.connect(path)
    conn.execute(collect.session_ddl())
    conn.execute(
        "CREATE TABLE turn ("
        " session_key TEXT, ordinal INTEGER, ts TEXT, model TEXT, effort TEXT,"
        " service_tier TEXT, speed TEXT, stop_reason TEXT, input_tokens INTEGER,"
        " output_tokens INTEGER, cache_write_5m INTEGER, cache_write_1h INTEGER,"
        " cache_read INTEGER, thinking_tokens INTEGER, web_search_requests INTEGER,"
        " web_fetch_requests INTEGER, cost_usd REAL)"
    )
    conn.execute(
        "CREATE TABLE tool_call ("
        " session_key TEXT, ts TEXT, tool_name TEXT, is_error INTEGER)"
    )
    conn.execute(
        "CREATE TABLE attribution ("
        " session_key TEXT, kind TEXT, name TEXT, count INTEGER)"
    )
    conn.execute(
        "CREATE TABLE overlap_day ("
        " local_date TEXT PRIMARY KEY, sessions_active INTEGER,"
        " sessions_started INTEGER, summed_hours REAL, elapsed_hours REAL,"
        " concurrency REAL, max_concurrent INTEGER)"
    )
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")

    for i, (key, day, label) in enumerate(
        [("s1", "2026-07-01", "alpha"), ("s2", "2026-07-02", "beta")]
    ):
        row = dict(SESSION_DEFAULTS)
        row.update(
            key=key, local_date=day, local_hour=9 + i,
            project_label=label, repo_root=f"/repo/{label}",
            first_ts=f"{day}T09:00:00Z", last_ts=f"{day}T09:15:00Z",
            source_path=f"/src/{key}.jsonl",
        )
        names = ", ".join(row)
        holes = ", ".join("?" for _ in row)
        conn.execute(f"INSERT INTO session ({names}) VALUES ({holes})", tuple(row.values()))
        conn.execute(
            "INSERT INTO turn VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, 1, f"{day}T09:01:00Z", "claude-opus-5", None, "standard",
             "standard", "end_turn", 100, 200, 300, 0, 400, 50, 0, 0, 1.5),
        )
        conn.execute(
            "INSERT INTO tool_call VALUES (?,?,?,?)", (key, f"{day}T09:02:00Z", "Bash", 0)
        )
        conn.execute("INSERT INTO attribution VALUES (?,?,?,?)", (key, "skill", "tdd", 1))
        conn.execute(
            "INSERT INTO overlap_day VALUES (?,?,?,?,?,?,?)", (day, 1, 1, 0.25, 0.25, 1.0, 1)
        )
    conn.executemany(
        "INSERT INTO meta VALUES (?,?)",
        [("local_timezone", "Australia/Melbourne"), ("prices_read_on", "2026-08-23")],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def out(tmp_path: Path) -> Out:
    make_db(tmp_path / "sessions.sqlite")
    return Out(root=tmp_path)


# --------------------------------------------------------- dashboard-data.json


def test_the_dashboard_writes_its_payload_as_a_file(out: Out, capsys) -> None:
    assert dashboard.main(["--out", str(out.root)]) == 0
    assert out.data_json.exists()


def test_the_file_is_byte_identical_to_what_the_page_embeds(out: Out, capsys) -> None:
    """The whole reason this file exists: one string, written twice.

    If the JSON were rebuilt rather than reused, this could drift by a
    timestamp, a key order or a float repr and nothing would say so.
    """
    dashboard.main(["--out", str(out.root)])
    blob = out.data_json.read_text(encoding="utf-8")
    page = (out.root / "claude-code-dashboard-live.html").read_text(encoding="utf-8")
    assert blob in page


def test_the_payload_file_is_valid_json_with_the_column_map(out: Out, capsys) -> None:
    """A consumer needs `cols` to decode the row-major arrays; it must be there."""
    dashboard.main(["--out", str(out.root)])
    data = json.loads(out.data_json.read_text(encoding="utf-8"))
    assert set(data["cols"]) == {"S", "M", "T", "A", "O"}
    assert len(data["S"]) == 2


def test_the_payload_file_states_its_own_scope(out: Out, capsys) -> None:
    """It IS project-filtered. Saying so inline stops it being averaged with
    `stats-facts.json`, which is not."""
    dashboard.main(["--out", str(out.root)])
    data = json.loads(out.data_json.read_text(encoding="utf-8"))
    assert "project" in data["scope"]


def test_the_dashboard_still_prints_the_html_path_first(out: Out, capsys) -> None:
    dashboard.main(["--out", str(out.root)])
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith(str(out.root / "claude-code-dashboard-live.html"))


def test_the_dashboard_prints_the_json_path_too(out: Out, capsys) -> None:
    dashboard.main(["--out", str(out.root)])
    printed = capsys.readouterr().out
    assert str(out.data_json) in printed


def test_refresh_still_reads_back_the_html_path_not_the_json(out: Out, capsys) -> None:
    """`refresh.page_path` scans this stdout. A second path line must not fool it."""
    import refresh

    dashboard.main(["--out", str(out.root)])
    assert refresh.page_path(capsys.readouterr().out) == str(
        out.root / "claude-code-dashboard-live.html"
    )


def test_the_payload_file_lands_under_the_resolved_root_only(out: Out, capsys) -> None:
    dashboard.main(["--out", str(out.root)])
    assert out.data_json.parent == out.root


def test_no_building_file_survives_a_good_run(out: Out, capsys) -> None:
    """mkstemp + os.replace, same as the HTML: nothing half-written left behind."""
    dashboard.main(["--out", str(out.root)])
    assert list(out.root.glob("*.building")) == []


# ------------------------------------------------------------ stats-facts.json


def test_export_writes_the_facts_card(out: Out, capsys) -> None:
    assert export.main(["--out", str(out.root)]) == 0
    assert out.facts_json.exists()


def test_the_facts_card_carries_the_headline_numbers(out: Out, capsys) -> None:
    export.main(["--out", str(out.root)])
    facts = json.loads(out.facts_json.read_text(encoding="utf-8"))["facts"]
    assert facts["sessions_real"] == 2
    assert facts["files_total"] == 2


def test_the_facts_card_is_stamped(out: Out, capsys) -> None:
    export.main(["--out", str(out.root)])
    card = json.loads(out.facts_json.read_text(encoding="utf-8"))
    assert card["generated_at"].endswith("Z")


def test_the_facts_card_states_its_own_scope(out: Out, capsys) -> None:
    """It is NOT project-filtered, unlike `dashboard-data.json`. Say so."""
    export.main(["--out", str(out.root)])
    card = json.loads(out.facts_json.read_text(encoding="utf-8"))
    assert "not" in card["scope"].lower()


def test_the_facts_card_carries_the_cost_disclaimer(out: Out, capsys) -> None:
    """`cost_usd` is a list-price estimate, never a bill. It must travel with
    the number, because this file is designed to be read somewhere else."""
    export.main(["--out", str(out.root)])
    card = json.loads(out.facts_json.read_text(encoding="utf-8"))
    assert "NOT a bill" in card["cost_note"]


def test_export_prints_the_path_it_wrote(out: Out, capsys) -> None:
    export.main(["--out", str(out.root)])
    assert str(out.facts_json) in capsys.readouterr().out


def test_export_refuses_a_missing_database(tmp_path: Path, capsys) -> None:
    assert export.main(["--out", str(tmp_path)]) == 1
    assert not (tmp_path / "stats-facts.json").exists()


def test_export_rejects_an_unknown_flag(out: Out, capsys) -> None:
    assert export.main(["--out", str(out.root), "--wat"]) == 2


def test_export_refuses_a_protected_output_root(capsys) -> None:
    """`resolve_out`'s fence must apply here too, not just to its siblings."""
    import common

    assert export.main(["--out", str(common.REPO_ROOT)]) == 2


def test_export_honours_the_window(out: Out, capsys) -> None:
    export.main(["--out", str(out.root), "--since", "2026-07-02"])
    facts = json.loads(out.facts_json.read_text(encoding="utf-8"))["facts"]
    assert facts["sessions_real"] == 1


def test_the_facts_card_lands_under_the_resolved_root_only(out: Out, capsys) -> None:
    export.main(["--out", str(out.root)])
    assert out.facts_json.parent == out.root


def test_export_leaves_no_building_file(out: Out, capsys) -> None:
    export.main(["--out", str(out.root)])
    assert list(out.root.glob("*.building")) == []


def test_the_facts_card_is_small(out: Out, capsys) -> None:
    """The point of this file over `dashboard-data.json` is that it is tiny.
    A card that grew into a second full export would have lost its reason to
    exist, so the size is a fence, not a coincidence."""
    export.main(["--out", str(out.root)])
    assert out.facts_json.stat().st_size < 8192
