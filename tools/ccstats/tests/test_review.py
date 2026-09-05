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
    """A folder is skipped BY something. Grouping the folders UNDER that pattern
    is what lets the operator fix the right line instead of hunting for it."""
    defaults(out, keep=["alpha"], exclude=["bet"])
    review.main(["--out", str(out.root), "--projects"])
    printed = capsys.readouterr().out
    assert "bet" in printed
    beta = next(ln for ln in printed.splitlines() if ln.rstrip().endswith("beta"))
    assert printed.index("bet") < printed.index(beta)


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
    assert "not in the include allowlist" in printed, printed


def test_an_allowlist_orphan_is_not_lost_from_the_report(out: Out, capsys) -> None:
    """It belongs to no exclude pattern, so a pattern-shaped report could count
    it in the totals and show it in no row at all."""
    defaults(out, keep=["alpha"], include=["alpha"], exclude=[])
    review.main(["--out", str(out.root), "--projects"])
    assert "beta" in capsys.readouterr().out


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


# ------------------------------------------------------- the report's shape
# The first version printed one row per project: 139 rows and a 242-character
# line on the live corpus, three quarters of them repeating one prefix and two
# thirds printing the same number twice. The operator specified this selection
# as 31 KEYWORDS, so the default view answers in patterns and the per-project
# detail moves behind `--projects`. Nothing is removed, only reordered.


def report(out: Out, capsys, *args: str) -> str:
    review.main(["--out", str(out.root), *args])
    return capsys.readouterr().out


def test_the_unreviewed_section_comes_first(out: Out, capsys) -> None:
    """It is the only part that needs a decision. Burying it under 138 rows
    already ruled on is what the first version did."""
    add_project(out, "g1", "gamma")
    defaults(out, keep=["alpha"], exclude=["beta"])
    text = report(out, capsys)
    assert text.index("gamma") < text.index("alpha")


def test_the_cracks_section_prints_even_when_empty(out: Out, capsys) -> None:
    """A block that appears only sometimes is one the eye stops looking for.
    The heading and its count are always in the same place."""
    defaults(out, keep=["alpha"], exclude=["beta"])
    text = report(out, capsys)
    assert "NEVER RULED ON - in neither list  (0)" in text
    assert "none - every project matches" in text


def test_a_project_in_keep_that_exclude_overrides_is_reported(out: Out, capsys) -> None:
    """THE QUIETER CRACK. `exclude` wins over `keep`, so a project the operator
    explicitly asked to count can be dropped with nothing said. Eight of these
    existed on the live corpus and none was visible anywhere."""
    defaults(out, keep=["beta"], exclude=["bet"])
    text = report(out, capsys)
    assert "IN `keep` BUT EXCLUDED ANYWAY" in text
    # Summarised by default - the pattern to blame, not eighteen lines of folder
    assert "excluded by: bet" in text
    # ...and in full under --projects
    full = report(out, capsys, "--projects")
    assert "beta" in full.split("IN `keep` BUT EXCLUDED ANYWAY")[1]


def test_no_overrides_says_none(out: Out, capsys) -> None:
    defaults(out, keep=["alpha"], exclude=["beta"])
    section = report(out, capsys).split("IN `keep` BUT EXCLUDED ANYWAY")[1]
    assert section.splitlines()[1].strip() == "none."


def test_the_keep_section_has_one_row_per_pattern(out: Out, capsys) -> None:
    """Two projects, one pattern covering both: one row, not two."""
    add_project(out, "a2", "alpha-two")
    defaults(out, keep=["alpha"], exclude=[])
    rows = [ln for ln in report(out, capsys).splitlines() if ln.rstrip().endswith("alpha")]
    assert len(rows) == 1, rows


def test_a_pattern_row_counts_its_projects(out: Out, capsys) -> None:
    add_project(out, "a2", "alpha-two")
    defaults(out, keep=["alpha"], exclude=[])
    row = next(ln for ln in report(out, capsys).splitlines() if ln.rstrip().endswith("alpha"))
    assert row.split()[2] == "2", row


def test_a_pattern_row_counts_what_it_alone_holds(out: Out, capsys) -> None:
    """`only` is the delete signal: how much falls out if this pattern goes."""
    defaults(out, keep=["alpha", "lph"], exclude=[])
    text = report(out, capsys)
    alpha = next(ln for ln in text.splitlines() if ln.rstrip().endswith("alpha"))
    lph = next(ln for ln in text.splitlines() if ln.rstrip().endswith("lph"))
    assert alpha.split()[3] == "0", alpha
    assert lph.split()[3] == "0", lph


def test_patterns_covered_by_others_are_named(out: Out, capsys) -> None:
    defaults(out, keep=["alpha", "lph"], exclude=[])
    assert "lph" in report(out, capsys)


def test_the_redundancy_callout_warns_it_is_one_at_a_time(out: Out, capsys) -> None:
    """THE TRAP. `only` is computed per pattern in isolation. Two patterns can
    each read 0 because they cover EACH OTHER - drop either safely, drop both
    and the projects are gone. Live example: `infisical` and `agent-vault`."""
    defaults(out, keep=["alpha", "lph"], exclude=[])
    assert "one at a time" in report(out, capsys).lower()


def test_a_pattern_matching_nothing_is_named(out: Out, capsys) -> None:
    defaults(out, keep=["alpha", "no-such-thing"], exclude=[])
    text = report(out, capsys)
    assert "no-such-thing" in text
    assert "match nothing" in text.lower()


def test_rows_sort_by_sessions_in_the_window(out: Out, capsys) -> None:
    add_project(out, "a2", "alpha-two")
    add_project(out, "a3", "alpha-three")
    defaults(out, keep=["alpha", "beta"], exclude=[])
    lines = report(out, capsys).splitlines()
    assert lines.index(next(x for x in lines if x.rstrip().endswith("alpha"))) < lines.index(
        next(x for x in lines if x.rstrip().endswith("beta"))
    )


def test_projects_lists_the_folders(out: Out, capsys) -> None:
    add_project(out, "a2", "alpha-two")
    defaults(out, keep=["alpha"], exclude=[])
    assert "alpha-two" not in report(out, capsys)
    assert "alpha-two" in report(out, capsys, "--projects")


def test_the_default_report_is_short(out: Out, capsys) -> None:
    """The whole point. One row per project is what made it unreadable."""
    for i in range(30):
        add_project(out, f"p{i}", f"alpha-{i}")
    defaults(out, keep=["alpha"], exclude=["beta"])
    assert len(report(out, capsys).splitlines()) < 25


def test_new_is_unchanged_by_all_of_this(out: Out, capsys) -> None:
    """The scheduled job parses this. Its shape is a compatibility surface."""
    add_project(out, "g1", "gamma")
    defaults(out, keep=["alpha"], exclude=["beta"])
    line = report(out, capsys, "--new").strip()
    assert line.endswith("gamma")
    assert line.split()[:2] == ["1", "since"], line
