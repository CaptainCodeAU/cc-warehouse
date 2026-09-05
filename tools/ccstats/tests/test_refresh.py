"""`refresh.py`, the unattended dashboard rebuild.

Every test here fakes `subprocess.run`, so nothing scans a transcript, nothing
reads the real `sessions.sqlite`, nothing writes a page, no dialog box opens and
no Finder window appears. What is under test is the ORCHESTRATION: which
children run, with which arguments, in which order, what the exit code and log
look like when one of them fails, and what the completion dialog says and does.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

CCSTATS = Path(__file__).resolve().parent.parent
if str(CCSTATS) not in sys.path:
    sys.path.insert(0, str(CCSTATS))

import refresh  # noqa: E402

PAGE = "/Users/x/.cc-warehouse/stats/claude-code-dashboard-live.html"
PAGE_LINE = f"{PAGE}  (1,714,214 bytes, 10,148 sessions, full range)"
GAVE_UP = "gave up:true"


def pressed(button: str) -> str:
    """`osascript` stdout for a run where someone clicked `button`."""
    return f"button returned:{button}, gave up:false"


class FakeProc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def key_of(cmd: list[str]) -> str:
    """What a recorded command line is keyed by: a helper binary, or a child script."""
    name = Path(cmd[0]).name
    if name in {"osascript", "open"}:
        return name
    return Path(cmd[1]).name


def install(
    monkeypatch: pytest.MonkeyPatch, outcomes: dict[str, FakeProc] | None = None
) -> list[list[str]]:
    """Replace `subprocess.run` and record every command line it was given.

    `outcomes` is keyed the same way `key_of` keys; anything not named exits 0.
    `dashboard.py` defaults to a realistic success line so the page path this
    script reads back from it is exercised rather than stubbed away, and the
    dialog defaults to timing out, so a test that says nothing about buttons
    triggers no follow-up action.
    """
    table = {
        "dashboard.py": FakeProc(0, stdout=PAGE_LINE),
        "osascript": FakeProc(0, stdout=GAVE_UP),
    }
    table.update(outcomes or {})
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> FakeProc:
        calls.append(list(cmd))
        return table.get(key_of(cmd), FakeProc(0))

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def ran(calls: list[list[str]]) -> list[str]:
    return [key_of(c) for c in calls]


def dialog(calls: list[list[str]]) -> str:
    """The AppleScript of the one dialog shown."""
    shown = [c for c in calls if key_of(c) == "osascript"]
    assert len(shown) == 1, f"expected exactly one dialog, got {len(shown)}"
    return shown[0][2]


def opened(calls: list[list[str]]) -> list[list[str]]:
    """The arguments of every `/usr/bin/open` call, in order."""
    return [c[1:] for c in calls if key_of(c) == "open"]


# ------------------------------------------------------------- orchestration


def test_happy_path_runs_collect_then_dashboard_then_export(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = install(monkeypatch)
    assert refresh.main(["--quiet", "--no-notify"]) == 0
    assert ran(calls) == ["collect.py", "dashboard.py", "export.py", "review.py"]
    # --quiet on success is silent, so an empty log means healthy.
    assert capsys.readouterr().out == ""


def test_children_inherit_this_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never a bare `python3`: under launchd that resolves to the 3.9 system build."""
    calls = install(monkeypatch)
    refresh.main(["--quiet", "--no-notify"])
    assert [c[0] for c in calls] == [sys.executable] * 4


def test_dashboard_gets_no_filter_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """The anti-drift property.

    `dashboard.py` reads `dashboard-defaults.json` itself. If this script ever
    starts passing its own --include/--exclude, the scheduled page and a
    `/dashboard` page can disagree, which is the exact bug
    `load_default_filters` was written to close.
    """
    calls = install(monkeypatch)
    refresh.main(["--quiet", "--no-notify"])
    dash = next(c for c in calls if key_of(c) == "dashboard.py")
    assert dash[2:] == []


def test_collect_is_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch)
    refresh.main(["--no-notify"])
    coll = next(c for c in calls if key_of(c) == "collect.py")
    assert coll[2:] == ["--quiet"]


def test_skip_collect_only_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch)
    assert refresh.main(["--skip-collect", "--quiet", "--no-notify"]) == 0
    assert ran(calls) == ["dashboard.py", "export.py", "review.py"]


def test_failed_scan_still_builds_but_reports_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stale page beats no page, but the exit status must not lie."""
    calls = install(monkeypatch, {"collect.py": FakeProc(2, stderr="boom")})
    assert refresh.main(["--quiet", "--no-notify"]) == 1
    assert ran(calls) == ["collect.py", "dashboard.py", "export.py", "review.py"]
    out = capsys.readouterr().out
    # --quiet is overridden by failure: the whole run must reach the log.
    assert "boom" in out
    assert "collect.py exited 2" in out


def test_failed_build_reports_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, {"dashboard.py": FakeProc(1, stderr="nope")})
    assert refresh.main(["--quiet", "--no-notify"]) == 1
    assert "nope" in capsys.readouterr().out


def test_unknown_flag_refuses(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = install(monkeypatch)
    assert refresh.main(["--exclude", "secret-project"]) == 2
    assert calls == []
    assert "unknown argument" in capsys.readouterr().err


def test_help_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch)
    assert refresh.main(["--help"]) == 0
    assert calls == []


def test_non_quiet_success_still_logs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch)
    assert refresh.main(["--no-notify"]) == 0
    out = capsys.readouterr().out
    assert "ccstats refresh" in out
    assert "dashboard" in out


# --------------------------------------------------------------- the page path


def test_page_path_reads_the_dashboard_success_line() -> None:
    assert refresh.page_path(PAGE_LINE) == PAGE


def test_page_path_is_none_when_absent() -> None:
    """Better a dialog that names no file than one that names the wrong file."""
    assert refresh.page_path("") is None
    assert refresh.page_path("error: refusing to write there") is None


# ------------------------------------------------------------- the dialog box


def test_completion_shows_one_dialog(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch)
    assert refresh.main(["--quiet"]) == 0
    assert ran(calls) == ["collect.py", "dashboard.py", "export.py", "review.py", "osascript"]


def test_dialog_names_the_program_and_the_page_in_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole ask: which program ran, and which file it produced, full paths."""
    calls = install(monkeypatch)
    refresh.main(["--quiet"])
    text = dialog(calls)
    assert str(refresh.ME) in text
    assert PAGE in text
    assert "rebuilt" in text


def test_dialog_offers_three_buttons_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three is AppleScript's ceiling, so all three must earn their place."""
    calls = install(monkeypatch)
    refresh.main(["--quiet"])
    text = dialog(calls)
    for label in (refresh.SHOW_SCRIPT, refresh.SHOW_FOLDER, refresh.OPEN_PAGE):
        assert f'"{label}"' in text
    assert f'default button "{refresh.OPEN_PAGE}"' in text


def test_dialog_hides_the_page_buttons_when_there_is_no_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A button that opens nothing is worse than no button."""
    calls = install(monkeypatch, {"dashboard.py": FakeProc(1)})
    refresh.main(["--quiet"])
    text = dialog(calls)
    assert refresh.OPEN_PAGE not in text
    assert refresh.SHOW_FOLDER not in text
    assert f'"{refresh.SHOW_SCRIPT}"' in text
    assert f'"{refresh.DISMISS}"' in text


def test_dialog_always_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """Modal plus unattended equals a process parked for days without this."""
    calls = install(monkeypatch)
    refresh.main(["--quiet"])
    assert f"giving up after {refresh.DIALOG_TIMEOUT_SECONDS}" in dialog(calls)


def test_dialog_uses_absolute_osascript(monkeypatch: pytest.MonkeyPatch) -> None:
    """launchd's PATH is near-empty, so a bare `osascript` would not resolve."""
    calls = install(monkeypatch)
    refresh.main(["--quiet"])
    shown = next(c for c in calls if key_of(c) == "osascript")
    assert shown[0] == "/usr/bin/osascript"
    assert shown[1] == "-e"


def test_dialog_says_failed_when_the_page_was_not_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install(monkeypatch, {"dashboard.py": FakeProc(1, stderr="nope")})
    assert refresh.main(["--quiet"]) == 1
    text = dialog(calls)
    assert "FAILED" in text
    assert "no page was written" in text


def test_dialog_says_stale_when_only_the_scan_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The page exists and is named, but the dialog must not imply fresh data."""
    calls = install(monkeypatch, {"collect.py": FakeProc(2)})
    assert refresh.main(["--quiet"]) == 1
    text = dialog(calls)
    assert "STALE" in text
    assert PAGE in text
    assert "data was not refreshed" in text


def test_no_notify_shows_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch)
    refresh.main(["--quiet", "--no-notify"])
    assert "osascript" not in ran(calls)


# ---------------------------------------------------------- what a button does


def test_open_page_button_opens_the_page(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch, {"osascript": FakeProc(0, pressed(refresh.OPEN_PAGE))})
    refresh.main(["--quiet"])
    assert opened(calls) == [[PAGE]]


def test_show_folder_button_reveals_the_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """`-R` opens the enclosing folder AND selects the file, which is "take me to it"."""
    calls = install(monkeypatch, {"osascript": FakeProc(0, pressed(refresh.SHOW_FOLDER))})
    refresh.main(["--quiet"])
    assert opened(calls) == [["-R", PAGE]]


def test_show_script_button_reveals_this_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install(monkeypatch, {"osascript": FakeProc(0, pressed(refresh.SHOW_SCRIPT))})
    refresh.main(["--quiet"])
    assert opened(calls) == [["-R", str(refresh.ME)]]


def test_timing_out_opens_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch)  # default stdout is `gave up:true`
    refresh.main(["--quiet"])
    assert opened(calls) == []


def test_dismiss_opens_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch, {"osascript": FakeProc(0, pressed(refresh.DISMISS))})
    refresh.main(["--quiet"])
    assert opened(calls) == []


def test_button_parsing() -> None:
    assert refresh._button_pressed(pressed("Open page")) == "Open page"
    assert refresh._button_pressed(GAVE_UP) is None
    assert refresh._button_pressed("") is None


def test_a_failed_open_cannot_fail_the_job(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(
        monkeypatch,
        {
            "osascript": FakeProc(0, pressed(refresh.OPEN_PAGE)),
            "open": FakeProc(1, stderr="no application knows how"),
        },
    )
    assert refresh.main([]) == 0
    out = capsys.readouterr().out
    assert "no application knows how" in out


# ------------------------------------------------- the notifier cannot bite


def test_a_broken_dialog_cannot_fail_the_job(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A notifier that takes down the job it reports on is worse than none."""
    install(monkeypatch, {"osascript": FakeProc(1, stderr="not allowed")})
    assert refresh.main([]) == 0
    out = capsys.readouterr().out
    assert "dialog not shown" in out
    assert "not allowed" in out


def test_dialog_surviving_a_missing_binary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch)

    def boom(cmd: list[str], **_: Any) -> FakeProc:
        if key_of(cmd) == "osascript":
            raise OSError("No such file or directory")
        return FakeProc(0, stdout=PAGE_LINE)

    monkeypatch.setattr(subprocess, "run", boom)
    assert refresh.main([]) == 0
    assert "dialog not shown" in capsys.readouterr().out


def test_applescript_escapes_quotes_backslashes_and_newlines() -> None:
    """A path with a quote in it must not break out of the string literal."""
    assert refresh._applescript_string('a "b" \\ c') == '"a \\"b\\" \\\\ c"'
    # A literal newline cannot live inside an AppleScript string.
    assert refresh._applescript_string("one\ntwo") == '"one\\ntwo"'


def test_a_dialog_that_never_appeared_breaks_the_quiet_convention(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty log means "ran fine". The box is the only other sign the job ran.

    Losing both at once is indistinguishable from a job that never fired, so a
    dialog that could not appear must reach the log even under --quiet. It still
    must not change the exit status.
    """
    install(monkeypatch, {"osascript": FakeProc(1, stderr="not allowed")})
    assert refresh.main(["--quiet"]) == 0
    out = capsys.readouterr().out
    assert "dialog not shown" in out
    assert "not allowed" in out


def test_a_shown_dialog_keeps_quiet_quiet(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, {"osascript": FakeProc(0, pressed(refresh.OPEN_PAGE))})
    assert refresh.main(["--quiet"]) == 0
    assert capsys.readouterr().out == ""


# --------------------------------------------------- the data export, third child
# The page is for a human. `export.py` writes the same run's numbers as files a
# DIFFERENT program can read. It runs last because it is the least important of
# the three: a failure here must not cost anyone the page.


DATA = "/Users/x/.cc-warehouse/stats/dashboard-data.json"
FACTS = "/Users/x/.cc-warehouse/stats/stats-facts.json"
FACTS_LINE = f"{FACTS}  (2,410 bytes, full range)"


def test_export_runs_after_the_dashboard(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch)
    refresh.main(["--quiet", "--no-notify"])
    assert ran(calls).index("export.py") > ran(calls).index("dashboard.py")


def test_export_gets_no_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same anti-drift rule the dashboard child follows: it resolves its own
    output root and its own window, so this script passes neither."""
    calls = install(monkeypatch)
    refresh.main(["--quiet", "--no-notify"])
    exp = next(c for c in calls if key_of(c) == "export.py")
    assert exp[2:] == []


def test_a_failed_export_fails_the_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, {"export.py": FakeProc(1, stderr="nope")})
    assert refresh.main(["--quiet", "--no-notify"]) == 1
    out = capsys.readouterr().out
    assert "nope" in out
    assert "export.py exited 1" in out


def test_a_failed_export_does_not_stop_the_page_being_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The page was written. Its buttons must still work."""
    calls = install(monkeypatch, {"export.py": FakeProc(1)})
    refresh.main(["--quiet"])
    assert PAGE in dialog(calls)


def test_an_export_failure_is_not_called_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """STALE means `the data was not refreshed`, which is what a FAILED SCAN
    means. Reusing that word for an export failure would send someone looking
    at the collector for a fault that is not there."""
    calls = install(monkeypatch, {"export.py": FakeProc(1)})
    refresh.main(["--quiet"])
    shown = next(c for c in calls if key_of(c) == "osascript")[2]
    assert "STALE" not in shown
    assert "EXPORT" in shown


def test_a_run_where_two_children_fail_names_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A severity-ordered if/elif ladder drops every fault but the worst.

    This exact run - scan failed AND export failed - used to be titled STALE,
    with the export failure absent from the title entirely.
    """
    calls = install(
        monkeypatch,
        {"collect.py": FakeProc(2), "export.py": FakeProc(1)},
    )
    assert refresh.main(["--quiet"]) == 1
    shown = next(c for c in calls if key_of(c) == "osascript")[2]
    assert "STALE" in shown
    assert "EXPORT FAILED" in shown


def test_a_clean_run_names_no_fault(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control case: the fault list must be empty when nothing failed."""
    calls = install(monkeypatch)
    refresh.main(["--quiet"])
    shown = next(c for c in calls if key_of(c) == "osascript")[2]
    assert "rebuilt" in shown
    assert "FAILED" not in shown
    assert "STALE" not in shown


def test_the_dialog_names_the_data_files(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(
        monkeypatch,
        {
            "dashboard.py": FakeProc(
                0, stdout=f"{PAGE_LINE}\n{DATA}  (1,650,000 bytes of payload)"
            ),
            "export.py": FakeProc(0, stdout=FACTS_LINE),
        },
    )
    refresh.main(["--quiet"])
    text = dialog(calls)
    assert DATA in text
    assert FACTS in text


def test_a_reshaped_export_line_is_not_guessed_at(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same rule `page_path` follows: name no file rather than the wrong one."""
    install(monkeypatch, {"export.py": FakeProc(0, stdout="something else entirely")})
    assert refresh._path_named("something else entirely", refresh.FACTS_NAME) is None


# ------------------------------------------- the unreviewed-projects warning
# `review.py --new` prints projects matching neither the keep nor the exclude
# list. Anything it names goes in the dialog. It is ADVISORY: it must never
# fail the run, and - the point of the whole design - it is run WITHOUT
# `--record`, so an unattended dialog nobody watched cannot consume the warning.


def test_review_runs_without_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE ONE THAT MATTERS. `--record` here would let a 13:00 run whose box
    timed out unread acknowledge the warning on the operator's behalf."""
    calls = install(monkeypatch)
    refresh.main(["--quiet", "--no-notify"])
    rev = next(c for c in calls if key_of(c) == "review.py")
    assert rev[2:] == ["--new"]
    assert "--record" not in rev


def test_a_new_unreviewed_project_reaches_the_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install(
        monkeypatch, {"review.py": FakeProc(0, stdout="   42  CaptainCodeAU-something-new")}
    )
    refresh.main(["--quiet"])
    text = dialog(calls)
    assert "CaptainCodeAU-something-new" in text


def test_nothing_unreviewed_adds_no_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence is the healthy state. A warning printed every day is wallpaper.

    Asserts on `REVIEW_HEADING` itself, not on a paraphrase of it. The first
    version looked for "never ruled on", which is not a substring of "Projects
    neither list has ruled on:" - so it passed whether or not the line was
    there, and would have gone on passing if the line were never removed.
    """
    calls = install(monkeypatch, {"review.py": FakeProc(0, stdout="")})
    refresh.main(["--quiet"])
    assert refresh.REVIEW_HEADING not in dialog(calls)


def test_a_dead_review_check_does_not_look_like_a_clean_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheduled job runs `--quiet`, which suppresses the log on a good run.
    Without a dialog line, a review.py broken for months is indistinguishable
    from a clean backlog - and clean is what silence is defined to mean."""
    calls = install(monkeypatch, {"review.py": FakeProc(1)})
    refresh.main(["--quiet"])
    assert "review.py failed" in dialog(calls)


def test_a_long_unreviewed_list_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """`display dialog` has no scrollbar. A first run against an empty baseline
    can name a hundred projects."""
    many = "\n".join(f"    0 since /    1 all   project-{i}" for i in range(40))
    calls = install(monkeypatch, {"review.py": FakeProc(0, stdout=many)})
    refresh.main(["--quiet"])
    text = dialog(calls)
    assert "project-0" in text
    assert "project-39" not in text
    assert f"and {40 - refresh.REVIEW_MAX_LINES} more" in text


def test_a_failing_review_does_not_fail_the_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Advisory, unlike the other three children. A backlog report that can take
    down the job it advises on is worse than no report."""
    install(monkeypatch, {"review.py": FakeProc(1, stderr="nope")})
    assert refresh.main(["--quiet", "--no-notify"]) == 0


def test_a_failing_review_still_reaches_the_log(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Not fatal is not the same as invisible."""
    install(monkeypatch, {"review.py": FakeProc(1, stderr="nope")})
    refresh.main(["--no-notify"])
    assert "nope" in capsys.readouterr().out


def test_review_runs_last(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch)
    refresh.main(["--quiet", "--no-notify"])
    order = ran(calls)
    assert order.index("review.py") > order.index("export.py")


def test_a_crashed_review_puts_nothing_in_the_dialog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Half a line from a dying advisory child reads as a real finding."""
    calls = install(
        monkeypatch, {"review.py": FakeProc(1, stdout="   42  half-a-proj")}
    )
    refresh.main(["--quiet"])
    assert "half-a-proj" not in dialog(calls)
