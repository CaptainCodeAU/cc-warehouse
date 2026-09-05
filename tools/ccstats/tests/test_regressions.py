"""One test per defect found on 2026-08-21.

Every one of these shipped. Each test fails against the code as it was, so the
suite is a record of what actually went wrong rather than a guess at what might.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import collect
import common
import pytest
from common import BadOut, BadWindow, Out, Window, parse_since, resolve_out

from conftest import assistant, payload, user

# ------------------------------------------------------------------ bug 1
# `--since` was parsed in three files and validated in none. `local_date` is
# compared as TEXT, so an unpadded '2026-6-8' sorts above every real date and
# silently selected zero sessions, then crashed inside facts.compute.


@pytest.mark.parametrize("bad", ["2026-6-8", "2026-6-08", "garbage", "26-06-08", ""])
def test_unpadded_or_malformed_since_is_refused(bad: str) -> None:
    with pytest.raises(BadWindow):
        parse_since(["--since", bad])


def test_impossible_calendar_date_is_refused() -> None:
    with pytest.raises(BadWindow):
        parse_since(["--since", "2026-13-99"])


def test_since_without_a_value_is_refused() -> None:
    with pytest.raises(BadWindow):
        parse_since(["--since"])


def test_a_real_date_is_accepted_and_absence_means_full_range() -> None:
    assert parse_since(["--since", "2026-06-08"]) == "2026-06-08"
    assert parse_since([]) == ""


def test_the_unpadded_date_really_would_have_matched_nothing() -> None:
    """The reason validation matters, demonstrated on real text comparison."""
    assert "2026-6-8" > "2026-12-31"  # sorts above EVERY date in the corpus
    assert not ("2026-06-20" >= "2026-6-8")


# ------------------------------------------------------------------ bug 2
# The window had two implementations (facts.py and build_workbook.py). One now.


def test_window_forms_all_derive_from_one_since() -> None:
    w = Window("2026-06-08")
    assert w.session == "is_real = 1 AND local_date >= '2026-06-08'"
    assert w.session_as_s == "s.is_real = 1 AND s.local_date >= '2026-06-08'"
    assert w.overlap_where == " WHERE local_date >= '2026-06-08'"
    assert "session_key IN" in w.child_keys
    assert w.session in w.child_keys  # the child filter reuses the session filter


def test_empty_window_filters_only_on_is_real() -> None:
    w = Window()
    assert w.session == "is_real = 1"
    assert w.session_as_s == "s.is_real = 1"
    assert w.overlap_where == ""
    assert w.child_keys == ""
    assert w.and_clause == ""


def test_window_forms_agree_against_a_real_table() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE session (key TEXT, is_real INT, local_date TEXT)")
    conn.executemany(
        "INSERT INTO session VALUES (?,?,?)",
        [
            ("a", 1, "2026-06-07"),
            ("b", 1, "2026-06-08"),
            ("c", 1, "2026-07-01"),
            ("d", 0, "2026-07-01"),
        ],
    )
    conn.execute("CREATE TABLE turn (session_key TEXT)")
    conn.executemany("INSERT INTO turn VALUES (?)", [("a",), ("b",), ("c",), ("d",)])
    w = Window("2026-06-08")
    sessions = conn.execute(f"SELECT COUNT(*) FROM session WHERE {w.session}").fetchone()[0]
    turns = conn.execute(f"SELECT COUNT(*) FROM turn WHERE 1=1{w.child_keys}").fetchone()[0]
    assert sessions == 2, "b and c only"
    assert turns == 2, "the child filter must select the same sessions"


# ------------------------------------------------------------------ bug 3
# thinking_tokens is a SUBSET of output_tokens. Adding them double counts.


def test_thinking_is_never_counted_on_top_of_output(scan, tmp_path) -> None:
    result = scan(
        payload(
            user("2026-06-10T01:00:00.000Z"),
            assistant("2026-06-10T01:00:10.000Z", out=500, thinking=400),
        ),
        tmp_path,
    )
    assert result.session["tok_output"] == 500
    assert result.session["tok_thinking"] == 400
    assert result.session["tok_thinking"] <= result.session["tok_output"]


def test_a_payload_claiming_more_thinking_than_output_is_clamped(scan, tmp_path) -> None:
    """Defensive: the corpus never does this, but the invariant is asserted."""
    result = scan(
        payload(assistant("2026-06-10T01:00:00.000Z", out=100, thinking=999)),
        tmp_path,
    )
    assert result.session["tok_thinking"] == 100


# ------------------------------------------------------------------ bug 4
# The 5m/1h cache split must reconcile with the declared total, because the two
# tiers are priced differently (1.25x vs 2x the input rate).


def test_cache_tiers_reconcile_with_the_declared_total(scan, tmp_path) -> None:
    result = scan(
        payload(assistant("2026-06-10T01:00:00.000Z", cw5=100, cw1h=900)),
        tmp_path,
    )
    s = result.session
    assert s["tok_cache_write_5m"] == 100
    assert s["tok_cache_write_1h"] == 900
    assert s["tok_cache_write"] == s["tok_cache_write_declared"] == 1000


def test_a_payload_with_no_tier_breakdown_bills_the_cheaper_tier(scan, tmp_path) -> None:
    """Older payloads carry no `cache_creation` block. An unknown must never
    inflate the estimate, so the whole write goes to the 1.25x tier."""
    line = assistant("2026-06-10T01:00:00.000Z", cw5=0, cw1h=0)
    doctored = line.replace(
        '"cache_creation_input_tokens": 0', '"cache_creation_input_tokens": 800'
    )
    result = scan(payload(doctored), tmp_path)
    assert result.session["tok_cache_write_5m"] == 800
    assert result.session["tok_cache_write_1h"] == 0


# ------------------------------------------------------------------ bug 5
# `is_real`: a transcript with no assistant reply is not a session.


def test_a_transcript_with_no_reply_is_not_a_real_session(scan, tmp_path) -> None:
    result = scan(payload(user("2026-06-10T01:00:00.000Z")), tmp_path)
    assert result.session["is_real"] == 0
    assert result.session["has_usage"] == 0


def test_a_transcript_with_a_reply_is_a_real_session(scan, tmp_path) -> None:
    result = scan(
        payload(user("2026-06-10T01:00:00.000Z"), assistant("2026-06-10T01:00:05.000Z")),
        tmp_path,
    )
    assert result.session["is_real"] == 1
    assert result.session["has_usage"] == 1


# ------------------------------------------------------------------ bug 6
# engaged_seconds must drop gaps over the idle threshold.


def test_a_long_gap_is_excluded_from_engaged_time(scan, tmp_path) -> None:
    result = scan(
        payload(
            user("2026-06-10T01:00:00.000Z"),
            assistant("2026-06-10T01:01:00.000Z"),   # +60s, counted
            assistant("2026-06-10T05:00:00.000Z"),   # +4h gap, NOT counted
            assistant("2026-06-10T05:00:30.000Z"),   # +30s, counted
        ),
        tmp_path,
    )
    s = result.session
    assert s["engaged_seconds"] == pytest.approx(90.0)
    assert s["wall_seconds"] == pytest.approx(14430.0)
    assert s["idle_seconds"] == pytest.approx(14340.0)


# ------------------------------------------------------------------ bug 7
# Malformed lines are counted, never fatal.


def test_a_broken_line_does_not_lose_the_others(scan, tmp_path) -> None:
    result = scan(
        payload(
            user("2026-06-10T01:00:00.000Z"),
            "{not json at all",
            assistant("2026-06-10T01:00:05.000Z", out=42),
        ),
        tmp_path,
    )
    assert result.session["n_malformed_lines"] == 1
    assert result.session["tok_output"] == 42
    assert result.session["is_real"] == 1


# ------------------------------------------------------------------ bug 8
# The timezone must be DST-aware, and the config must beat the machine clock.


def test_the_detected_zone_is_dst_aware_not_a_frozen_offset() -> None:
    assert isinstance(collect._LOCAL_TZ, ZoneInfo), (
        "a fixed-offset tzinfo silently ignores daylight saving; 577 sessions "
        "were bucketed an hour early because of exactly that"
    )


def test_a_dst_aware_zone_gives_different_offsets_across_the_year() -> None:
    zone = ZoneInfo("Australia/Melbourne")
    winter = datetime(2026, 6, 20, 4, 0, tzinfo=UTC).astimezone(zone)
    summer = datetime(2026, 2, 20, 4, 0, tzinfo=UTC).astimezone(zone)
    assert winter.strftime("%z") == "+1000"
    assert summer.strftime("%z") == "+1100"
    assert winter.utcoffset() != summer.utcoffset()


def test_config_timezone_beats_the_machine(tmp_path, monkeypatch) -> None:
    cfg = tmp_path / "cc-warehouse"
    cfg.mkdir()
    (cfg / "config.toml").write_text('archive_timezone = "Europe/Berlin"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    name, source = collect._config_timezone()
    assert name == "Europe/Berlin"
    assert source.startswith("config")


def test_an_unknown_config_zone_is_ignored_rather_than_raised(tmp_path, monkeypatch) -> None:
    """config._archive_timezone's R5 rule: a typo must never stop the run."""
    cfg = tmp_path / "cc-warehouse"
    cfg.mkdir()
    (cfg / "config.toml").write_text('archive_timezone = "Mars/Olympus_Mons"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    name, _source = collect._config_timezone()
    assert name is None


# ------------------------------------------------------------------ bug 9
# `collect.py` renamed the previous `sessions.sqlite` aside to `.sqlite.prev`
# on every run and never removed it: two full copies of a 137 MB file, kept
# on disk forever. Publishing now builds into a temp file in the same
# directory and `os.replace`s it onto the target.


def _run_collect(tmp_path, monkeypatch, extra_argv=()):
    """Run `collect.main()` against one real session, writing into `tmp_path/out`.

    ARCHIVE/LIVE are pointed at throwaway trees so the test never touches this
    machine's real archive or `~/.claude/projects`, and carries exactly one
    session so aggregate stats have real data to divide by.
    """
    live_root = tmp_path / "live"
    (live_root / "demo-project").mkdir(parents=True)
    (live_root / "demo-project" / "s-1.jsonl").write_bytes(
        payload(
            user("2026-06-10T01:00:00.000Z"),
            assistant("2026-06-10T01:00:05.000Z"),
        )
    )
    monkeypatch.setattr(collect, "ARCHIVE", tmp_path / "no-archive")
    monkeypatch.setattr(collect, "LIVE", live_root)
    out_root = tmp_path / "out"
    monkeypatch.setattr(
        sys, "argv", ["collect.py", "--out", str(out_root), "--quiet", *extra_argv]
    )
    return out_root


def test_publishing_the_database_leaves_no_prev_file(tmp_path, monkeypatch) -> None:
    out_root = _run_collect(tmp_path, monkeypatch)
    assert collect.main() == 0
    assert (out_root / "sessions.sqlite").exists()
    assert not list(out_root.glob("*.prev")), "the old rename-aside must never happen again"


def test_a_second_run_replaces_rather_than_doubling(tmp_path, monkeypatch) -> None:
    out_root = _run_collect(tmp_path, monkeypatch)
    assert collect.main() == 0
    assert collect.main() == 0
    db_files = sorted(out_root.glob("sessions.sqlite*"))
    assert db_files == [out_root / "sessions.sqlite"], (
        f"a second run must leave exactly one database file, not {db_files}"
    )


def test_no_building_file_survives_a_clean_run(tmp_path, monkeypatch) -> None:
    out_root = _run_collect(tmp_path, monkeypatch)
    assert collect.main() == 0
    assert not list(out_root.glob("*.building"))


def test_a_crashed_build_never_replaces_the_last_good_database(tmp_path, monkeypatch) -> None:
    """Simulates a crash mid-build. The previously published database must
    survive byte-for-byte, and the orphaned temp file is left behind rather
    than deleted (removal is the operator's call, never automatic)."""
    out_root = _run_collect(tmp_path, monkeypatch)
    assert collect.main() == 0
    before = (out_root / "sessions.sqlite").read_bytes()

    def _boom() -> str:
        raise RuntimeError("simulated crash mid-build")

    monkeypatch.setattr(collect, "session_ddl", _boom)
    with pytest.raises(RuntimeError):
        collect.main()

    after = (out_root / "sessions.sqlite").read_bytes()
    assert after == before, "a crashed build must never replace the last good database"
    leftovers = list(out_root.glob("*.sqlite.building"))
    assert len(leftovers) == 1, "the orphaned temp file is left for the operator to remove"


def test_a_stale_building_file_is_reported_not_deleted(tmp_path, monkeypatch) -> None:
    out_root = _run_collect(tmp_path, monkeypatch)
    out_root.mkdir(parents=True)
    orphan = out_root / "sessions.leftover.sqlite.building"
    orphan.write_bytes(b"stale")
    assert collect.main() == 0
    assert orphan.exists(), "a stale build file must never be removed automatically"
    report = json.loads((out_root / "collect-report.json").read_text())
    assert str(orphan) in report["stale_building_files"]


# ------------------------------------------------------------------ bug 10
# `--out` needed the same write fence `--since` already has for its own hazard:
# refuse loudly, before any write happens, rather than write wherever it lands.


def test_out_precedence_flag_beats_env_beats_default(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CCSTATS_OUT", raising=False)
    assert resolve_out([]).root == common.DEFAULT_OUT.resolve()

    monkeypatch.setenv("CCSTATS_OUT", str(tmp_path / "from-env"))
    assert resolve_out([]).root == (tmp_path / "from-env").resolve()

    flagged = resolve_out(["--out", str(tmp_path / "from-flag")])
    assert flagged.root == (tmp_path / "from-flag").resolve(), "the flag must win over the env"


def test_every_out_path_sits_under_the_resolved_root(tmp_path) -> None:
    out = Out(root=tmp_path)
    for path in (
        out.db, out.xlsx, out.doc, out.report, out.sessions_csv, out.snapshot, out.manifest,
        out.data_json, out.facts_json,
    ):
        assert path.parent == tmp_path


@pytest.mark.parametrize(
    "bad",
    [
        str(common.HOME / ".claude"),
        str(common.HOME / ".claude" / "projects"),
        str(common.ARCHIVE),
        str(common.ARCHIVE / "some-project"),
        str(common.HOME / "cc-warehouse-data"),
        str(common.REPO_ROOT),
    ],
)
def test_out_refuses_a_protected_root(bad: str) -> None:
    with pytest.raises(BadOut):
        resolve_out(["--out", bad])


def test_out_accepts_an_ordinary_directory(tmp_path) -> None:
    """The control case for the fence: an unrelated directory must NOT trip it."""
    target = tmp_path / "ccstats-probe"
    assert resolve_out(["--out", str(target)]).root == target.resolve()
