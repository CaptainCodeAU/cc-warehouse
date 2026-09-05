"""`review.py`: which projects have been ruled on, and which have not.

The operator maintains two lists - `keep` (projects that belong in the numbers)
and `exclude` (projects that do not) - and rules on new ones as they appear. A
project matching NEITHER has never been judged. It still counts, because an
unreviewed project silently missing from a total is worse than one visibly in
it, but it has to be visible or the ledger is a fiction.

WHY `--new` IS READ-ONLY AND `--record` IS SEPARATE. The scheduled job runs this
and puts anything new in its completion dialog. That dialog closes itself after
300 seconds, and the job's log is empty on a healthy run, so an unattended 13:00
run is very likely to go unseen. If the job also RECORDED what it reported, the
warning would be consumed by the run nobody watched and never appear again.
Recording is therefore only ever an explicit human act.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import review
from common import Out
from test_exports import SESSION_DEFAULTS, make_db


@pytest.fixture
def out(tmp_path: Path) -> Out:
    make_db(tmp_path / "sessions.sqlite")
    return Out(root=tmp_path)


def defaults(out: Out, **fields: object) -> None:
    (out.root / "dashboard-defaults.json").write_text(json.dumps(fields), encoding="utf-8")


def add_project(out: Out, key: str, label: str, day: str = "2026-07-03") -> None:
    """One more real session, so a project can appear that no list mentions."""
    conn = sqlite3.connect(out.db)
    row = dict(SESSION_DEFAULTS)
    row.update(
        key=key, local_date=day, local_hour=9, project_label=label,
        repo_root=f"/repo/{label}", first_ts=f"{day}T09:00:00Z",
        last_ts=f"{day}T09:15:00Z", source_path=f"/src/{key}.jsonl",
    )
    names = ", ".join(row)
    holes = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO session ({names}) VALUES ({holes})", tuple(row.values()))
    conn.commit()
    conn.close()


# --------------------------------------------------------------- the report


def test_it_runs_and_reports(out: Out, capsys) -> None:
    defaults(out, keep=["alpha"], exclude=["beta"])
    assert review.main(["--out", str(out.root)]) == 0
    assert capsys.readouterr().out.strip() != ""


def test_a_kept_project_is_named_as_reviewed(out: Out, capsys) -> None:
    defaults(out, keep=["alpha"], exclude=["beta"])
    review.main(["--out", str(out.root)])
    printed = capsys.readouterr().out
    assert "alpha" in printed


def test_an_excluded_project_names_the_pattern_that_did_it(out: Out, capsys) -> None:
    """A folder is skipped BY something. Naming the pattern is what lets the
    operator fix the right line instead of hunting for it."""
    defaults(out, keep=["alpha"], exclude=["bet"])
    review.main(["--out", str(out.root)])
    printed = capsys.readouterr().out
    assert "beta" in printed
    assert "bet" in printed


def test_a_project_in_neither_list_is_reported_as_unreviewed(out: Out, capsys) -> None:
    add_project(out, "g1", "gamma")
    defaults(out, keep=["alpha"], exclude=["beta"])
    review.main(["--out", str(out.root)])
    assert "gamma" in capsys.readouterr().out


def test_the_report_carries_session_counts(out: Out, capsys) -> None:
    """A folder name alone is not enough to rule on. 900 sessions and 1 session
    are different decisions.

    Asserts on the ROW, not on the digit: `"1" in printed` was satisfied by the
    header line "keep: 1 patterns" and would have passed with no counts at all.
    """
    add_project(out, "a2", "alpha")
    defaults(out, keep=["alpha"], exclude=["beta"])
    review.main(["--out", str(out.root)])
    rows = [ln for ln in capsys.readouterr().out.splitlines() if "  alpha" in ln]
    assert rows and rows[0].split()[:2] == ["2", "2"], rows


def test_an_allowlist_switches_off_what_it_does_not_name(out: Out, capsys) -> None:
    """The report must agree with the card. When `include` is non-empty it is an
    allowlist, so a project it does not name is OFF - and reporting that project
    as counted would have the report contradicting the thing it reports on."""
    defaults(out, keep=["alpha"], include=["alpha"], exclude=[])
    review.main(["--out", str(out.root)])
    printed = capsys.readouterr().out
    beta = next(ln for ln in printed.splitlines() if "  beta" in ln)
    assert "allowlist" in beta, beta


def test_the_report_writes_nothing(out: Out, capsys) -> None:
    before = sorted(p.name for p in out.root.iterdir())
    defaults(out, keep=["alpha"], exclude=["beta"])
    review.main(["--out", str(out.root)])
    after = sorted(p.name for p in out.root.iterdir())
    assert after == sorted([*before, "dashboard-defaults.json"])


def test_a_missing_database_is_refused(tmp_path: Path, capsys) -> None:
    assert review.main(["--out", str(tmp_path)]) == 1


def test_an_unknown_flag_is_refused(out: Out, capsys) -> None:
    assert review.main(["--out", str(out.root), "--wat"]) == 2


# ------------------------------------------------------------------- --new


def test_new_lists_unreviewed_projects_when_there_is_no_baseline(out: Out, capsys) -> None:
    """A missing baseline means nothing has been acknowledged yet, not an error."""
    add_project(out, "g1", "gamma")
    defaults(out, keep=["alpha"], exclude=["beta"])
    review.main(["--out", str(out.root), "--new"])
    assert "gamma" in capsys.readouterr().out


def test_new_says_nothing_when_every_project_is_ruled_on(out: Out, capsys) -> None:
    """Silence is the healthy state, matching this project's other jobs."""
    defaults(out, keep=["alpha"], exclude=["beta"])
    assert review.main(["--out", str(out.root), "--new"]) == 0
    assert capsys.readouterr().out.strip() == ""


def test_new_alone_does_not_record(out: Out, capsys) -> None:
    """THE ONE THAT MATTERS. The scheduled job runs `--new`. If that consumed
    the warning, an unattended run whose dialog nobody watched would eat it."""
    add_project(out, "g1", "gamma")
    defaults(out, keep=["alpha"], exclude=["beta"])
    review.main(["--out", str(out.root), "--new"])
    capsys.readouterr()
    review.main(["--out", str(out.root), "--new"])
    assert "gamma" in capsys.readouterr().out, "the first --new consumed the warning"


def test_record_acknowledges_and_silences(out: Out, capsys) -> None:
    add_project(out, "g1", "gamma")
    defaults(out, keep=["alpha"], exclude=["beta"])
    review.main(["--out", str(out.root), "--new", "--record"])
    capsys.readouterr()
    review.main(["--out", str(out.root), "--new"])
    assert capsys.readouterr().out.strip() == ""


def test_a_project_appearing_after_a_record_is_reported(out: Out, capsys) -> None:
    """"Warn when the list GROWS" is the whole point: acknowledging one project
    must not mute the next one."""
    add_project(out, "g1", "gamma")
    defaults(out, keep=["alpha"], exclude=["beta"])
    review.main(["--out", str(out.root), "--new", "--record"])
    capsys.readouterr()
    add_project(out, "d1", "delta")
    review.main(["--out", str(out.root), "--new"])
    printed = capsys.readouterr().out
    assert "delta" in printed
    assert "gamma" not in printed, "an acknowledged project came back"


def test_ruling_on_a_project_removes_it_without_recording(out: Out, capsys) -> None:
    """The real fix is a decision, not an acknowledgement. Adding the project to
    either list must clear it from the report on its own."""
    add_project(out, "g1", "gamma")
    defaults(out, keep=["alpha", "gamma"], exclude=["beta"])
    review.main(["--out", str(out.root), "--new"])
    assert capsys.readouterr().out.strip() == ""


def test_record_without_new_is_refused(out: Out, capsys) -> None:
    """`--record` describes what `--new` does with its answer; alone it has no
    meaning, and silently doing nothing would be worse than saying so."""
    assert review.main(["--out", str(out.root), "--record"]) == 2


def test_the_baseline_lands_under_the_resolved_root_only(out: Out, capsys) -> None:
    add_project(out, "g1", "gamma")
    defaults(out, keep=["alpha"], exclude=["beta"])
    review.main(["--out", str(out.root), "--new", "--record"])
    assert (out.root / "review-baseline.json").exists()


def test_a_corrupt_baseline_is_treated_as_empty(out: Out, capsys) -> None:
    """It is an acknowledgement ledger, not data. Degrading loudly-but-safely
    beats failing the daily job over a file nobody would miss."""
    add_project(out, "g1", "gamma")
    defaults(out, keep=["alpha"], exclude=["beta"])
    (out.root / "review-baseline.json").write_text("{{{not json", encoding="utf-8")
    assert review.main(["--out", str(out.root), "--new"]) == 0
    assert "gamma" in capsys.readouterr().out


def test_keep_is_not_a_filter(out: Out, capsys) -> None:
    """`keep` is a ledger. If it ever starts gating what counts, the page and
    the facts card change silently - which is exactly why it is not `include`."""
    add_project(out, "g1", "gamma")
    defaults(out, keep=["alpha"], exclude=[])
    review.main(["--out", str(out.root)])
    printed = capsys.readouterr().out
    assert "gamma" in printed, "a project outside `keep` must still be counted"
