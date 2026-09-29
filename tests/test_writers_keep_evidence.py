"""Oracle tests: no writer records damage as the new truth (W-20260929-A82, A88).

THE FAILURE THIS EXISTS FOR. Verified 2026-09-29 in a sandbox with the real verbs:
`ccw build`, a `ccw sweep` that stores anything (its build covers the whole archive),
the weekly `ccw archive --to` job and `ccw repair` all re-rendered a folder whose
sub-agent or copied companion file had changed, and the re-render rebuilt the
manifest's records from the files on disk. The changed bytes became the recorded
truth and `ccw archive --verify` then reported 0 problems.

THE RULING (Gavin, 2026-09-29, F3). The shared manifest writer keeps the OLD record
when a companion file changed or vanished (ccw writes those with `write_if_absent`
and never rewrites or deletes one), or when a sub-agent changed without growing
(ccw's own sub-agent rule is replace-if-larger). The change then stays flagged by
doctor's quick check, `ccw repair` and `ccw archive --verify`. `prompts.jsonl` and
`custom-title.json` are NOT covered: ccw legitimately rewrites both, and nothing in
the archive tells that rewrite apart from damage. A grown sub-agent is explained by
growth and adopted (W-20260929-A76).

F1: while a batch lock is held, a mismatch on a file newer than its manifest is
pending for `ccw repair` too (doctor's a60d50d rule): no render, no refusal, no
alert, exit 0, one log line.
"""

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from test_doctor_quick_desync import UUID_A, flip_one_byte, rich_folder, targets

from cc_warehouse import archive, doctor, notify, store
from cc_warehouse.config import Config
from cc_warehouse.render import RenderOptions
from conftest import basic_session, entry, jsonl, run_ccw, run_cli, write_transcript

ZONE = "Australia/Melbourne"
UUID_NEW = "eeeeeeee-5555-4555-8555-eeeeeeeeeeee"


def silent(*_args: object) -> None:
    """Stands in for a desktop or voice sink the test does not observe."""


def manifest_of(folder: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads((folder / "manifest.json").read_text("utf-8")))


def full_problems(config: Config) -> list[str]:
    _folders, broken = doctor.desync_detail(config)
    return [p.problem for _f, found in broken for p in found]


# ---------------------------------------------------------------------------
# The four writers, real verbs, each against the same damage
# ---------------------------------------------------------------------------


def run_build(env: dict[str, str], _config: Config) -> None:
    assert run_ccw(["build"], env).code == 0


def run_storing_sweep(env: dict[str, str], _config: Config) -> None:
    """A sweep that STORES something, so its build runs over the whole archive."""
    write_transcript(env, basic_session(session_id=UUID_NEW), session_id=UUID_NEW)
    result = run_ccw(["sweep"], env)
    assert result.code == 0, result.err
    assert "1 stored" in result.out, result.out


def run_archive_job(env: dict[str, str], config: Config) -> None:
    assert run_ccw(["archive", "--to", str(config.archive_root)], env).code == 0


def run_repair(env: dict[str, str], _config: Config) -> None:
    run_ccw(["repair"], env)  # exits 1 on a refusal; what matters is what it wrote


WRITERS: dict[str, Callable[[dict[str, str], Config], None]] = {
    "build": run_build,
    "sweep-that-stores": run_storing_sweep,
    "archive-to": run_archive_job,
    "repair": run_repair,
}


def damage_same_size_tool_result(folder: Path) -> str:
    flip_one_byte(targets(folder)["tool-result"])
    return "tool-result"


def damage_truncated_tool_result(folder: Path) -> str:
    path = targets(folder)["tool-result"]
    path.write_bytes(path.read_bytes()[:-2])
    return "tool-result"


def damage_same_size_subagent(folder: Path) -> str:
    flip_one_byte(targets(folder)["sub-agent"])
    return "sub-agent"


def damage_shrunk_subagent(folder: Path) -> str:
    path = targets(folder)["sub-agent"]
    path.write_bytes(path.read_bytes()[:-2])
    return "sub-agent"


DAMAGE: dict[str, Callable[[Path], str]] = {
    "same-size-tool-result": damage_same_size_tool_result,
    "truncated-tool-result": damage_truncated_tool_result,
    "same-size-sub-agent": damage_same_size_subagent,
    "shrunk-sub-agent": damage_shrunk_subagent,
}


DAMAGE_KIND = {
    "same-size-tool-result": "tool-result",
    "truncated-tool-result": "tool-result",
    "same-size-sub-agent": "sub-agent",
    "shrunk-sub-agent": "sub-agent",
}


def records_for(manifest: dict[str, object], kind: str) -> object:
    return manifest["tool_results"] if kind == "tool-result" else manifest["subagents"]


@pytest.mark.parametrize("damage", sorted(DAMAGE))
@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_no_writer_records_damage_as_the_new_truth(
    ccw_env: dict[str, str], tmp_path: Path, writer: str, damage: str
) -> None:
    """Two outcomes are right and one is wrong. Right: the damage stays flagged
    (the old record kept), or the file is HEALED back to its recorded bytes from
    an intact source (a storing sweep re-copies a sub-agent from ~/.claude, and a
    larger original replaces a truncated copy). Wrong: the damaged bytes become
    the record."""
    config, folder = rich_folder(ccw_env, tmp_path)
    before = manifest_of(folder)
    original = targets(folder)[DAMAGE_KIND[damage]].read_bytes()
    kind = DAMAGE[damage](folder)
    flagged = full_problems(config)
    assert flagged, "fixture precondition: the full check sees the damage"

    WRITERS[writer](ccw_env, config)

    assert records_for(manifest_of(folder), kind) == records_for(before, kind), (
        f"{writer} rewrote the {kind} record over {damage}"
    )
    healed = targets(folder)[kind].read_bytes() == original
    if healed:
        assert full_problems(config) == [], f"{writer} healed the file but a problem remains"
        return
    assert full_problems(config) == flagged, f"{writer} erased the evidence of {damage}"
    verify = run_ccw(["archive", "--to", str(config.archive_root), "--verify"], ccw_env)
    assert verify.code != 0, f"archive --verify went clean after {writer}: {verify.out!r}"


def test_a_storing_sweep_heals_a_truncated_subagent_from_its_source(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Pins that the heal above is real and not the test excusing itself: the
    source in ~/.claude is intact and larger, so replace-if-larger restores it."""
    config, folder = rich_folder(ccw_env, tmp_path)
    original = targets(folder)["sub-agent"].read_bytes()
    damage_shrunk_subagent(folder)
    run_storing_sweep(ccw_env, config)
    assert targets(folder)["sub-agent"].read_bytes() == original
    assert full_problems(config) == []


@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_a_size_changing_damage_stays_visible_to_doctors_quick_check(
    ccw_env: dict[str, str], tmp_path: Path, writer: str
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    damage_truncated_tool_result(folder)
    WRITERS[writer](ccw_env, config)
    _checked, problems, _pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
    assert problems >= 1, f"doctor went clean after {writer}"
    assert first is not None and "tool-result" in first


# ---------------------------------------------------------------------------
# The writer rule itself, for every companion kind (unit level)
# ---------------------------------------------------------------------------


def unit_folder(root: Path) -> Path:
    return archive.write_session_folder(
        root, "widget", basic_session(session_id=UUID_A), RenderOptions(), ZONE
    ).directory


def rerender(root: Path) -> None:
    archive.write_session_folder(
        root, "widget", basic_session(session_id=UUID_A), RenderOptions(), ZONE, rebuild=True
    )


@pytest.mark.parametrize("name", sorted(archive.COMPANION_MANIFEST_KEYS))
def test_every_companion_kind_keeps_its_old_record_when_changed_or_gone(
    tmp_path: Path, name: str
) -> None:
    folder = unit_folder(tmp_path)
    key = archive.COMPANION_MANIFEST_KEYS[name]
    archive.write_companion_file(folder, name, Path("kept.txt"), b"original bytes\n")
    archive.write_companion_file(folder, name, Path("gone.txt"), b"will vanish\n")
    rerender(tmp_path)
    recorded = manifest_of(folder)[key]
    assert [r["name"] for r in cast(list[dict[str, object]], recorded)] == ["gone.txt", "kept.txt"]

    (folder / name / "kept.txt").write_bytes(b"ORIGINAL bytes\n")
    (folder / name / "gone.txt").unlink()
    archive.write_companion_file(folder, name, Path("new.txt"), b"a new copy\n")
    rerender(tmp_path)

    after = cast(list[dict[str, object]], manifest_of(folder)[key])
    old = {str(r["name"]): r for r in cast(list[dict[str, object]], recorded)}
    by_name = {str(r["name"]): r for r in after}
    assert by_name["kept.txt"] == old["kept.txt"], "a changed companion file was re-blessed"
    assert by_name["gone.txt"] == old["gone.txt"], "a vanished companion file was dropped"
    assert "new.txt" in by_name, "a newly copied file was not recorded"
    problems = [p.problem for p in archive.verify_folder(folder, ZONE)]
    assert any("kept.txt does not match its hash" in p for p in problems), problems
    assert any("gone.txt is missing" in p for p in problems), problems


def test_a_damaged_folder_is_current_so_build_does_not_rerender_it_forever(
    tmp_path: Path,
) -> None:
    """Keeping the old record must not make the folder look stale on every build."""
    folder = unit_folder(tmp_path)
    archive.write_companion_file(folder, "tool-results", Path("a.txt"), b"abc\n")
    rerender(tmp_path)
    (folder / "tool-results" / "a.txt").write_bytes(b"ABC\n")
    rerender(tmp_path)
    digest = store.sha256_hex(basic_session(session_id=UUID_A))
    assert archive.folder_is_current(folder, digest, RenderOptions()) is True


# ---------------------------------------------------------------------------
# NOT covered, by the ruling: prompts.jsonl and custom-title.json
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ("prompts", "custom-title"))
def test_a_file_ccw_may_rewrite_is_still_adopted_by_build(
    ccw_env: dict[str, str], tmp_path: Path, kind: str
) -> None:
    """PINS THE STATED LIMIT. ccw rewrites both (a later extraction fix, a rename),
    and nothing in the archive tells that apart from damage."""
    config, folder = rich_folder(ccw_env, tmp_path)
    flip_one_byte(targets(folder)[kind])
    assert run_ccw(["build"], ccw_env).code == 0
    assert full_problems(config) == []


# ---------------------------------------------------------------------------
# W-20260929-A76: a grown sub-agent is explained by growth
# ---------------------------------------------------------------------------


def grow_subagent(folder: Path) -> Path:
    agent = targets(folder)["sub-agent"]
    agent.write_bytes(
        agent.read_bytes()
        + jsonl(entry("assistant", "more work", "2026-05-07T14:10:00.000Z", session_id=UUID_A))
    )
    return agent


@pytest.mark.parametrize("verb", (["build"], ["repair"]))
def test_a_grown_subagent_is_adopted(
    ccw_env: dict[str, str], tmp_path: Path, verb: list[str]
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    agent = grow_subagent(folder)
    assert any("sub-agent" in p for p in full_problems(config))

    result = run_ccw(verb, ccw_env)

    assert result.code == 0, f"{result.out!r} {result.err!r}"
    assert full_problems(config) == []
    record = cast(list[dict[str, object]], manifest_of(folder)["subagents"])[0]
    assert record["sha256"] == store.sha256_hex(agent.read_bytes())


# ---------------------------------------------------------------------------
# F1: a batch lock makes a newer-than-manifest mismatch pending for repair
# ---------------------------------------------------------------------------


def age_manifest(folder: Path) -> None:
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(folder / "manifest.json", (old, old))


@pytest.mark.parametrize("kind", ("prompts", "custom-title", "tool-result"))
def test_a_newer_mismatch_is_pending_for_repair_while_a_batch_lock_is_held(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    flip_one_byte(targets(folder)[kind])
    age_manifest(folder)
    before = manifest_of(folder)
    alerts: list[str] = []

    def record(_config: object, _title: str, message: str) -> None:
        alerts.append(message)

    monkeypatch.setattr(notify, "alert", record)
    monkeypatch.setattr(notify, "speak", silent)
    assert store.acquire_lock(config.root, "sweep")
    try:
        result = run_cli(["repair", "--quiet"])
    finally:
        store.release_lock(config.root, "sweep")

    assert result.code == 0, f"a batch's own write failed repair: {result.err!r}"
    assert alerts == []
    assert manifest_of(folder) == before, "repair rendered while a batch was running"
    log = (config.root / "logs" / "capture.jsonl").read_text("utf-8").splitlines()
    pending = [line for line in log if '"status": "pending"' in line and "repair: " in line]
    assert len(pending) == 1, pending

    # The lock released, the same folder is an unexplained change again.
    assert run_cli(["repair", "--quiet"]).code == 1
    assert len(alerts) == 1


def test_a_mismatch_older_than_its_manifest_is_never_pending_under_a_lock(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    path = targets(folder)["tool-result"]
    flip_one_byte(path)
    old = (datetime.now(UTC) - timedelta(hours=3)).timestamp()
    os.utime(path, (old, old))
    monkeypatch.setattr(notify, "alert", silent)
    monkeypatch.setattr(notify, "speak", silent)
    assert store.acquire_lock(config.root, "sweep")
    try:
        result = run_cli(["repair", "--quiet"])
    finally:
        store.release_lock(config.root, "sweep")
    assert result.code == 1, "a file the batch did not write was excused by the lock"
