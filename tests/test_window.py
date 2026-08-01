"""Oracle tests: the --since / --until window (slice 17, block 5).

Contract: DESIGN section 15 entry 2026-08-01 block 5. Frozen decisions:
`share` + `sweep` only (`build` REFUSED, for the R4 / silent-index hazard);
matching on the R12 payload-internal FIRST timestamp, the same instant every
listing already presents; bare dates are the OPERATOR'S LOCAL calendar days,
inclusive at both ends (the principal's call: wall-clock intent beats
folder-name agreement); hash XOR window, with union addable later.

This is the ONE place local time is contract-correct. Rendering must never
learn the machine's zone (slice 15 has a fence for that); SELECTION is about
what the operator meant when they typed a date, so it reads their calendar.

Every test that depends on the local calendar pins TZ explicitly, so the
local-day semantics are deterministic rather than dependent on whoever runs the
suite.
"""

from pathlib import Path

import pytest

from cc_warehouse import capture
from cc_warehouse.config import Config
from conftest import entry, jsonl, run_ccw, warehouse_root

SYDNEY = "Australia/Sydney"


def _uuid_for(slug: str) -> str:
    """A distinct session UUID per slug.

    Not cosmetic: sessions sharing a UUID form a VERSION CHAIN, and only the
    newest is a head. Reusing conftest's default here made three separate
    sessions look like three versions of one, so a window correctly selected a
    single head and the test read as a window bug. Every fixture that wants N
    independently selectable sessions must give them N identities.
    """
    digits = f"{abs(hash(slug)) % 10**12:012d}"
    return f"{digits[:8]}-{digits[8:12]}-1111-2222-333333333333"


def _session_at(stamp: str, slug: str = "windowed") -> bytes:
    """A one-turn session whose R12 first timestamp is exactly `stamp`."""
    uuid = _uuid_for(slug)
    return jsonl(
        entry("user", f"Prompt {slug}", stamp, session_id=uuid, gitBranch="main", slug=slug),
        entry("assistant", [{"type": "text", "text": "Reply."}], stamp, session_id=uuid),
    )


def _spanning_session(first: str, last: str, slug: str = "spanner") -> bytes:
    """A session that STARTS on one day and ends on the next."""
    uuid = _uuid_for(slug)
    return jsonl(
        entry("user", "Late night prompt", first, session_id=uuid, gitBranch="main", slug=slug),
        entry("assistant", [{"type": "text", "text": "Morning reply."}], last, session_id=uuid),
    )


def _capture(env: dict[str, str], data: bytes, name: str) -> str:
    source = Path(env["HOME"]) / f"{name}.jsonl"
    source.write_bytes(data)
    result = capture.capture_transcript(
        Config(root=warehouse_root(env)), source, session_id=None, cwd="/home/alice/x"
    )
    # A fixture that quietly failed to store would make every window assertion
    # below vacuously true: an empty catalog selects nothing for ANY window.
    assert result.action == "stored", f"{name}: {result.action} {result.detail}"
    assert result.short
    return result.short


def _share(env: dict[str, str], tmp_path: Path, *args: str) -> tuple[int, str, list[str]]:
    """Run `ccw share` with a window and report (exit, stderr, shared session dirs)."""
    out = tmp_path / f"out-{abs(hash(args))}"
    result = run_ccw(["share", *args, "--out", str(out)], env)
    shared = (
        sorted(p.name for p in out.rglob("conversation.html")) if out.exists() else []
    )
    return result.code, result.err, shared


def _shared_slugs(env: dict[str, str], tmp_path: Path, *args: str) -> set[str]:
    out = tmp_path / f"slugs-{abs(hash(args))}"
    result = run_ccw(["share", *args, "--out", str(out)], env)
    assert result.code == 0, f"code={result.code} out={result.out!r} err={result.err!r}"
    return {p.parent.name for p in out.rglob("conversation.html")}


# --- parsing: what a typed value means --------------------------------------


def test_a_bare_date_covers_the_whole_local_day(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`--since D --until D` is a one-day window, inclusive at both ends. A date
    the operator typed means their calendar day, not an instant."""
    ccw_env["TZ"] = "UTC"
    _capture(ccw_env, _session_at("2026-03-10T00:00:00.000Z", "dawn"), "dawn")
    _capture(ccw_env, _session_at("2026-03-10T23:59:59.000Z", "dusk"), "dusk")
    _capture(ccw_env, _session_at("2026-03-11T00:00:01.000Z", "next"), "next")
    slugs = _shared_slugs(ccw_env, tmp_path, "--since", "2026-03-10", "--until", "2026-03-10")
    assert len(slugs) == 2, slugs


def test_one_second_past_the_until_day_does_not_match(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    ccw_env["TZ"] = "UTC"
    _capture(ccw_env, _session_at("2026-03-10T12:00:00.000Z", "inside"), "inside")
    _capture(ccw_env, _session_at("2026-03-11T00:00:00.000Z", "just-past"), "just-past")
    slugs = _shared_slugs(ccw_env, tmp_path, "--until", "2026-03-10")
    assert len(slugs) == 1, slugs


def test_a_session_matches_on_its_first_timestamp_not_its_last(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The midnight-spanner (register decision 13). A session that starts at
    23:41 on day D and ends at 01:12 on D+1 belongs to D, because R12's first
    timestamp is what every listing already shows."""
    ccw_env["TZ"] = "UTC"
    _capture(
        ccw_env,
        _spanning_session("2026-03-10T23:41:00.000Z", "2026-03-11T01:12:00.000Z"),
        "spanner",
    )
    on_d = _shared_slugs(ccw_env, tmp_path, "--since", "2026-03-10", "--until", "2026-03-10")
    assert len(on_d) == 1, "the spanner did not match the day it STARTED on"
    code, _err, later = _share(ccw_env, tmp_path, "--since", "2026-03-11")
    assert code != 0 or not later, "the spanner matched a window starting after it began"


def test_the_local_day_can_disagree_with_the_folder_name(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Register decision 14, the STATED consequence, tested rather than hidden.

    Projection folders slice UTC days (build.py's first_ts[:10]), but a typed
    date is the operator's local day. In Sydney, 2026-07-24T22:00:00Z is 08:00
    on the 25th, so it matches --since 2026-07-25 while its folder says
    2026-07-24. The principal chose wall-clock intent over folder agreement.
    """
    ccw_env["TZ"] = SYDNEY
    _capture(ccw_env, _session_at("2026-07-24T22:00:00.000Z", "sydney-morning"), "sydney-morning")
    slugs = _shared_slugs(ccw_env, tmp_path, "--since", "2026-07-25")
    assert len(slugs) == 1, "the local calendar day did not win"
    assert any("2026-07-24" in name for name in slugs), (
        "the folder should still carry the UTC day, which is the whole point of the "
        "consequence being worth stating"
    )


def test_a_naive_datetime_reads_as_local(ccw_env: dict[str, str], tmp_path: Path) -> None:
    ccw_env["TZ"] = SYDNEY
    _capture(ccw_env, _session_at("2026-07-24T22:00:00.000Z", "sydney-morning"), "sydney-morning")
    inside = _shared_slugs(ccw_env, tmp_path, "--since", "2026-07-25T07:00:00")
    assert len(inside) == 1, "a naive datetime was not read in the operator's zone"
    code, _err, after = _share(ccw_env, tmp_path, "--since", "2026-07-25T09:00:00")
    assert code != 0 or not after


def test_an_offset_carrying_datetime_is_taken_literally(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """An explicit offset is an explicit instant: the operator said exactly what
    they meant, so the local calendar does not get a vote."""
    ccw_env["TZ"] = SYDNEY
    _capture(ccw_env, _session_at("2026-07-24T22:00:00.000Z", "sydney-morning"), "sydney-morning")
    inside = _shared_slugs(ccw_env, tmp_path, "--since", "2026-07-24T21:00:00+00:00")
    assert len(inside) == 1
    code, _err, after = _share(ccw_env, tmp_path, "--since", "2026-07-24T23:00:00+00:00")
    assert code != 0 or not after


# --- one-sided windows ------------------------------------------------------


@pytest.mark.parametrize("flag", ("--since", "--until"))
def test_a_one_sided_window_is_valid_on_share(
    ccw_env: dict[str, str], tmp_path: Path, flag: str
) -> None:
    ccw_env["TZ"] = "UTC"
    _capture(ccw_env, _session_at("2026-03-10T12:00:00.000Z", "only"), "only")
    slugs = _shared_slugs(ccw_env, tmp_path, flag, "2026-03-10")
    assert len(slugs) == 1


# --- usage errors -----------------------------------------------------------


def test_since_after_until_is_a_usage_error(ccw_env: dict[str, str], tmp_path: Path) -> None:
    ccw_env["TZ"] = "UTC"
    _capture(ccw_env, _session_at("2026-03-10T12:00:00.000Z", "any"), "any")
    out = tmp_path / "backwards"
    result = run_ccw(
        ["share", "--since", "2026-03-11", "--until", "2026-03-10", "--out", str(out)],
        ccw_env,
    )
    assert result.code == 1
    assert result.err.startswith("Error: ")
    assert not out.exists(), "a usage error must publish nothing"


@pytest.mark.parametrize("value", ("7d", "yesterday", "last week", "2026-13-45", "notadate"))
def test_unparseable_and_relative_forms_are_usage_errors(
    ccw_env: dict[str, str], tmp_path: Path, value: str
) -> None:
    """No relative forms in v1.1 (block 5, stated). They are rejected loudly
    rather than guessed at, because a guessed window silently shares the wrong
    sessions."""
    ccw_env["TZ"] = "UTC"
    _capture(ccw_env, _session_at("2026-03-10T12:00:00.000Z", "any"), "any")
    out = tmp_path / f"bad-{abs(hash(value))}"
    result = run_ccw(["share", "--since", value, "--out", str(out)], ccw_env)
    assert result.code == 1, result.out
    assert result.err.startswith("Error: ")
    assert not out.exists()


# --- share: hashes XOR window -----------------------------------------------


def test_hashes_and_a_window_together_are_a_usage_error(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The two selectors are MUTUALLY EXCLUSIVE (block 5). Union is addable
    later, additively; guessing which one the operator meant is not."""
    ccw_env["TZ"] = "UTC"
    short = _capture(ccw_env, _session_at("2026-03-10T12:00:00.000Z", "both"), "both")
    out = tmp_path / "mixed"
    result = run_ccw(
        ["share", f"s:{short}", "--since", "2026-03-10", "--out", str(out)], ccw_env
    )
    assert result.code == 1
    assert result.err.startswith("Error: ")
    assert "since" in result.err.lower() or "window" in result.err.lower()
    assert not out.exists()


def test_hashes_alone_still_work(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """The v1 path is untouched: this slice is additive."""
    ccw_env["TZ"] = "UTC"
    short = _capture(ccw_env, _session_at("2026-03-10T12:00:00.000Z", "byhash"), "byhash")
    out = tmp_path / "byhash"
    result = run_ccw(["share", f"s:{short}", "--out", str(out)], ccw_env)
    assert result.code == 0, result.err
    assert list(out.rglob("conversation.html"))


def test_a_window_selects_exactly_the_in_window_heads(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    ccw_env["TZ"] = "UTC"
    _capture(ccw_env, _session_at("2026-03-08T12:00:00.000Z", "before"), "before")
    _capture(ccw_env, _session_at("2026-03-10T12:00:00.000Z", "inside-a"), "inside-a")
    _capture(ccw_env, _session_at("2026-03-11T12:00:00.000Z", "inside-b"), "inside-b")
    _capture(ccw_env, _session_at("2026-03-20T12:00:00.000Z", "after"), "after")
    slugs = _shared_slugs(ccw_env, tmp_path, "--since", "2026-03-10", "--until", "2026-03-11")
    assert len(slugs) == 2, slugs


# --- sweep: narrowing loses nothing -----------------------------------------


def test_sweep_skips_out_of_window_sessions_and_a_later_sweep_still_gets_them(
    ccw_env: dict[str, str],
) -> None:
    """Additive and re-runnable is the whole reason a window is safe on sweep:
    narrowing an import can never lose anything, unlike narrowing a build."""
    from conftest import claude_projects, session_count

    projects = claude_projects(ccw_env) / "-home-alice-projects-widget"
    projects.mkdir(parents=True, exist_ok=True)
    (projects / "a.jsonl").write_bytes(_session_at("2026-03-10T12:00:00.000Z", "in"))
    (projects / "b.jsonl").write_bytes(_session_at("2026-03-20T12:00:00.000Z", "out"))
    ccw_env["TZ"] = "UTC"

    windowed = run_ccw(["sweep", "--until", "2026-03-11"], ccw_env)
    assert windowed.code == 0, windowed.err
    assert session_count(ccw_env) == 1, "the window did not narrow the import"

    everything = run_ccw(["sweep"], ccw_env)
    assert everything.code == 0, everything.err
    assert session_count(ccw_env) == 2, "a later unwindowed sweep lost the skipped session"


# --- build stays out of it --------------------------------------------------


@pytest.mark.parametrize("flag", ("--since", "--until"))
def test_build_does_not_accept_the_window(ccw_env: dict[str, str], flag: str) -> None:
    """REFUSED in block 5, and recorded rather than deferred: a windowed build
    either deletes out-of-window projections (R4) or emits an index that
    silently omits sessions. No consumer justifies designing around that."""
    result = run_ccw(["build", flag, "2026-03-10"], ccw_env)
    assert result.code != 0
    assert result.err.strip(), "an unsupported flag must say so"
