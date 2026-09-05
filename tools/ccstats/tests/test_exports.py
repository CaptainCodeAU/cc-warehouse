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
    "local_weekday": 2, "tz_offset": "+10:00",
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


def test_the_dashboard_writes_its_payload_as_a_file(out: Out) -> None:
    assert dashboard.main(["--out", str(out.root)]) == 0
    assert out.data_json.exists()


def test_the_file_is_byte_identical_to_what_the_page_embeds(out: Out) -> None:
    """The whole reason this file exists: one string, written twice.

    If the JSON were rebuilt rather than reused, this could drift by a
    timestamp, a key order or a float repr and nothing would say so.
    """
    dashboard.main(["--out", str(out.root)])
    blob = out.data_json.read_text(encoding="utf-8")
    page = (out.root / "claude-code-dashboard-live.html").read_text(encoding="utf-8")
    assert blob in page


def test_the_payload_file_is_valid_json_with_the_column_map(out: Out) -> None:
    """A consumer needs `cols` to decode the row-major arrays; it must be there."""
    dashboard.main(["--out", str(out.root)])
    data = json.loads(out.data_json.read_text(encoding="utf-8"))
    assert set(data["cols"]) == {"S", "M", "T", "A", "O"}
    assert len(data["S"]) == 2


def test_the_payload_is_not_project_filtered(out: Out) -> None:
    """THE TEST THAT WAS MISSING, and its absence shipped a false claim.

    `--exclude beta` makes `beta` start UNTICKED in the page. That is a
    starting state for the browser's own checkboxes, not a filter on the data:
    every session must still be in the file. The first version of this feature
    asserted the opposite in a `scope` string, and on the real corpus 4,350 of
    10,214 embedded sessions belonged to projects that start unticked.
    """
    dashboard.main(["--out", str(out.root), "--exclude", "beta"])
    data = json.loads(out.data_json.read_text(encoding="utf-8"))
    assert data["default_unticked_projects"] == ["beta"]

    projects = data["lookups"]["projects"]
    column = data["cols"]["S"].index("project")
    labels = {projects[row[column]] for row in data["S"]}
    assert labels == {"alpha", "beta"}, "an unticked project must still be embedded"


def test_the_payload_scope_says_no_project_filter_was_applied(out: Out) -> None:
    """Structure, not prose. A sentence cannot be checked against the query
    that produced the rows; this can."""
    dashboard.main(["--out", str(out.root), "--exclude", "beta"])
    scope = json.loads(out.data_json.read_text(encoding="utf-8"))["scope"]
    assert scope["project_filter_applied"] is False
    assert scope["rows"] == "sessions with is_real = 1"


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


def test_the_payload_file_lands_under_the_resolved_root_only(out: Out) -> None:
    dashboard.main(["--out", str(out.root)])
    assert out.data_json.parent == out.root


def test_no_building_file_survives_a_good_run(out: Out) -> None:
    """mkstemp + os.replace, same as the HTML: nothing half-written left behind."""
    dashboard.main(["--out", str(out.root)])
    assert list(out.root.glob("*.building")) == []


# ------------------------------------------------------------ stats-facts.json


def test_export_writes_the_facts_card(out: Out) -> None:
    assert export.main(["--out", str(out.root)]) == 0
    assert out.facts_json.exists()


def test_the_facts_card_carries_the_headline_numbers(out: Out) -> None:
    export.main(["--out", str(out.root)])
    facts = json.loads(out.facts_json.read_text(encoding="utf-8"))["facts"]
    assert facts["sessions_real"] == 2
    assert facts["files_total"] == 2


def test_the_facts_card_is_stamped(out: Out) -> None:
    export.main(["--out", str(out.root)])
    card = json.loads(out.facts_json.read_text(encoding="utf-8"))
    assert card["generated_at"].endswith("Z")


def test_the_two_files_declare_DIFFERENT_populations(out: Out) -> None:
    """And that difference is the whole point of the facts card.

    The payload is whole - the page it mirrors needs every session so its date
    pickers and tick boxes can widen. The card is narrowed, because the program
    reading it has no pickers and no tick boxes. Both say which they are, in the
    same structured field, so a consumer can tell them apart with `==` rather
    than by reading two paragraphs of English.

    An earlier version of this test asserted the scopes were EQUAL. That was
    true, and correct to pin, until the card learned to filter.
    """
    (out.root / "dashboard-defaults.json").write_text('{"exclude": ["beta"]}', encoding="utf-8")
    dashboard.main(["--out", str(out.root)])
    export.main(["--out", str(out.root)])
    data = json.loads(out.data_json.read_text(encoding="utf-8"))["scope"]
    card = json.loads(out.facts_json.read_text(encoding="utf-8"))["scope"]

    assert data["project_filter_applied"] is False
    assert card["project_filter_applied"] is True
    assert card["projects"] == ["alpha"]
    assert data != card


def test_the_card_actually_counts_only_the_selected_projects(out: Out) -> None:
    """The scope field claiming a filter is not the same as a filter."""
    (out.root / "dashboard-defaults.json").write_text('{"exclude": ["beta"]}', encoding="utf-8")
    export.main(["--out", str(out.root)])
    narrowed = json.loads(out.facts_json.read_text(encoding="utf-8"))["facts"]["sessions_real"]
    (out.root / "dashboard-defaults.json").write_text("{}", encoding="utf-8")
    export.main(["--out", str(out.root)])
    whole = json.loads(out.facts_json.read_text(encoding="utf-8"))["facts"]["sessions_real"]
    assert narrowed == 1
    assert whole == 2


def test_the_saved_start_date_is_honoured(out: Out) -> None:
    (out.root / "dashboard-defaults.json").write_text(
        '{"since": "2026-07-02", "exclude": ["nothing-matches-this"]}', encoding="utf-8"
    )
    export.main(["--out", str(out.root)])
    card = json.loads(out.facts_json.read_text(encoding="utf-8"))
    assert card["scope"]["since"] == "2026-07-02"
    assert card["facts"]["sessions_real"] == 1


def test_an_explicit_since_beats_the_saved_one(out: Out) -> None:
    (out.root / "dashboard-defaults.json").write_text('{"since": "2026-07-02"}', encoding="utf-8")
    export.main(["--out", str(out.root), "--since", "2026-07-01"])
    assert json.loads(out.facts_json.read_text(encoding="utf-8"))["scope"]["since"] == "2026-07-01"


def test_a_malformed_saved_start_date_is_ignored_not_fatal(out: Out) -> None:
    """A typo in a settings file must not stop the daily job. A full-range card
    is a visible outcome; a job that did not run is a silent one."""
    (out.root / "dashboard-defaults.json").write_text('{"since": "last tuesday"}', encoding="utf-8")
    assert export.main(["--out", str(out.root)]) == 0
    assert json.loads(out.facts_json.read_text(encoding="utf-8"))["scope"]["since"] == ""


def test_the_scope_travels_with_the_window(out: Out) -> None:
    export.main(["--out", str(out.root), "--since", "2026-07-02"])
    scope = json.loads(out.facts_json.read_text(encoding="utf-8"))["scope"]
    assert scope["since"] == "2026-07-02"


def test_the_facts_card_carries_the_cost_disclaimer(out: Out) -> None:
    """`cost_usd` is a list-price estimate, never a bill. It must travel with
    the number, because this file is designed to be read somewhere else."""
    export.main(["--out", str(out.root)])
    card = json.loads(out.facts_json.read_text(encoding="utf-8"))
    assert "NOT a bill" in card["cost_note"]


def test_export_prints_the_path_it_wrote(out: Out, capsys) -> None:
    export.main(["--out", str(out.root)])
    assert str(out.facts_json) in capsys.readouterr().out


def test_export_refuses_a_missing_database(tmp_path: Path) -> None:
    assert export.main(["--out", str(tmp_path)]) == 1
    assert not (tmp_path / "stats-facts.json").exists()


def test_export_rejects_an_unknown_flag(out: Out) -> None:
    assert export.main(["--out", str(out.root), "--wat"]) == 2


def test_export_refuses_a_protected_output_root() -> None:
    """`resolve_out`'s fence must apply here too, not just to its siblings."""
    import common

    assert export.main(["--out", str(common.REPO_ROOT)]) == 2


def test_export_honours_the_window(out: Out) -> None:
    export.main(["--out", str(out.root), "--since", "2026-07-02"])
    facts = json.loads(out.facts_json.read_text(encoding="utf-8"))["facts"]
    assert facts["sessions_real"] == 1


def test_the_facts_card_lands_under_the_resolved_root_only(out: Out) -> None:
    export.main(["--out", str(out.root)])
    assert out.facts_json.parent == out.root


def test_export_leaves_no_building_file(out: Out) -> None:
    export.main(["--out", str(out.root)])
    assert list(out.root.glob("*.building")) == []


def test_the_facts_card_is_small(out: Out) -> None:
    """The point of this file over `dashboard-data.json` is that it is tiny.
    A card that grew into a second full export would have lost its reason to
    exist, so the size is a fence, not a coincidence."""
    export.main(["--out", str(out.root)])
    assert out.facts_json.stat().st_size < 8192


def test_a_pattern_matching_nothing_is_warned_about(out: Out, capsys) -> None:
    """An empty selection writes a card of zeros. That must look like a broken
    setting, not like a quiet week."""
    (out.root / "dashboard-defaults.json").write_text(
        '{"include": ["no-such-project"]}', encoding="utf-8"
    )
    export.main(["--out", str(out.root)])
    assert "matched no project_label" in capsys.readouterr().err


def test_a_filtered_card_drops_sessions_that_belong_to_no_project(out: Out) -> None:
    """A session outside the selection universe is not counted, so a filtered
    card reports fewer FILES than an unfiltered one over the same window.

    True by definition and stated in `card()`, because from the card alone the
    difference looks like a defect. Two populations are affected: sessions with
    no `project_label`, and sessions in a project that has never had a real
    session (the selection universe is drawn from `is_real = 1`, matching the
    page's). On the live corpus those are 8 and 50 files respectively.
    """
    import sqlite3

    conn = sqlite3.connect(out.db)
    conn.execute(
        "INSERT INTO session (key, local_date, is_real) VALUES ('orphan', '2026-07-01', 0)"
    )
    conn.commit()
    conn.close()

    export.main(["--out", str(out.root)])
    whole = json.loads(out.facts_json.read_text(encoding="utf-8"))["facts"]["files_total"]
    (out.root / "dashboard-defaults.json").write_text('{"exclude": ["zzz"]}', encoding="utf-8")
    export.main(["--out", str(out.root)])
    filtered = json.loads(out.facts_json.read_text(encoding="utf-8"))["facts"]["files_total"]
    assert whole == filtered + 1
