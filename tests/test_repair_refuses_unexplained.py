"""Oracle tests: `ccw repair` re-renders only what ccw itself explains (W-20260929-A82).

THE FAILURE THIS EXISTS FOR. Found 2026-09-29 while making doctor's desync check a
quick presence-and-size check (W-20260929-A74): `ccw repair` is now the only DAILY
sha256 check, and it re-rendered every folder its full check flagged. A re-render
rewrites the manifest from the files on disk, so a file whose bytes changed for a
reason ccw cannot explain was recorded as the new truth: repair logged "1 fixed",
exited 0, and every later check (repair, doctor, `ccw archive --verify`) read the
folder as clean. The one check that could see the change erased it.

THE RULING (Gavin, 2026-09-29): repair re-renders only mismatches ccw itself
explains, which are a missing generated file (the detached render child died,
ticket 32) and a payload that hashes to the catalog head (a re-capture whose render
has not landed). Any other hash mismatch is left untouched, reported "still broken",
exits 1, and raises the notify alert, once per distinct problem set, not daily.

Every render here is REAL (`ccw repair` runs `ccw render` as a subprocess), so the
re-bless is pinned as fixed against the real render path, not a stand-in.
"""

import json
from pathlib import Path
from typing import cast

import pytest
from test_doctor_quick_desync import (
    KINDS,
    UUID_A,
    flip_one_byte,
    rich_folder,
    targets,
)

from cc_warehouse import archive, capture, doctor, notify, store
from cc_warehouse.config import Config
from conftest import entry, jsonl, run_ccw, run_cli, write_transcript


def silent(*_args: object) -> None:
    """Stands in for a desktop or voice sink the test does not observe."""


def snapshot(folder: Path) -> dict[str, bytes]:
    """Every file in the folder, by relative path. A refused folder must equal its
    own snapshot afterwards, byte for byte: repair wrote nothing into it."""
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def full_problems(config: Config) -> list[str]:
    _folders, broken = doctor.desync_detail(config)
    return [p.problem for _f, found in broken for p in found]


def repair_records(config: Config) -> list[dict[str, object]]:
    path = config.root / "logs" / "capture.jsonl"
    out: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = cast(dict[str, object], json.loads(line))
        if str(record.get("message", "")).startswith("repair: "):
            out.append(record)
    return out


# ---------------------------------------------------------------------------
# 1. an unexplained change is left untouched, reported, exit 1 (every kind)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_repair_leaves_a_same_size_change_untouched(
    ccw_env: dict[str, str], tmp_path: Path, kind: str
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    flip_one_byte(targets(folder)[kind])
    before = snapshot(folder)
    flagged = full_problems(config)
    assert flagged, "fixture precondition: the full check sees the change"

    result = run_ccw(["repair"], ccw_env)

    assert result.code == 1, f"repair did not fail on an unexplained {kind} change: {result.out!r}"
    assert snapshot(folder) == before, f"repair wrote into a folder with a changed {kind}"
    assert full_problems(config) == flagged, "the evidence did not survive repair"
    assert folder.name in result.err, result.err
    assert "still broken" in result.out + result.err


def test_repair_leaves_a_truncated_payload_untouched(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A payload that no longer hashes to the catalog head is not a re-capture."""
    config, folder = rich_folder(ccw_env, tmp_path)
    payload = targets(folder)["payload"]
    payload.write_bytes(payload.read_bytes()[:-5])
    before = snapshot(folder)

    result = run_ccw(["repair"], ccw_env)

    assert result.code == 1, result.out
    assert snapshot(folder) == before
    assert "JSONL does not match manifest source_hash" in full_problems(config)


def test_a_folder_missing_pages_and_changed_is_left_untouched(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """BOTH shapes at once. Re-rendering for the missing pages would also rewrite
    the manifest over the changed file, so the whole folder is refused: the pages
    stay missing and the change stays visible."""
    config, folder = rich_folder(ccw_env, tmp_path)
    flip_one_byte(targets(folder)["tool-result"])
    (folder / "conversation.html").unlink()
    before = snapshot(folder)

    result = run_ccw(["repair"], ccw_env)

    assert result.code == 1, result.out
    assert snapshot(folder) == before
    problems = full_problems(config)
    assert "missing conversation.html" in problems
    assert any("does not match its hash" in p for p in problems), problems


# ---------------------------------------------------------------------------
# 2. the controls: what ccw explains is still re-rendered
# ---------------------------------------------------------------------------


def test_repair_still_rerenders_a_missing_render(ccw_env: dict[str, str], tmp_path: Path) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    for name in archive.GENERATED_NAMES:
        (folder / name).unlink()

    result = run_ccw(["repair"], ccw_env)

    assert result.code == 0, f"{result.out!r} {result.err!r}"
    for name in archive.GENERATED_NAMES:
        assert (folder / name).exists(), f"{name} was not restored"
    assert full_problems(config) == []


def test_repair_still_rerenders_a_recapture(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """A resumed session's re-capture wrote a new payload and its catalog row; the
    render that rewrites the manifest never landed. The payload hashes to the
    catalog head, so ccw explains it and repair re-renders."""
    config, folder = rich_folder(ccw_env, tmp_path)
    source = Path(ccw_env["HOME"]) / ".claude" / "projects"
    transcript = next(source.glob(f"*/{UUID_A}.jsonl"))
    grown = transcript.read_bytes() + jsonl(
        entry("user", "resumed", "2026-01-05T11:00:00.000Z", session_id=UUID_A)
    )
    write_transcript(ccw_env, grown, session_id=UUID_A, encoded_dir=transcript.parent.name)
    stored = capture.capture_transcript(
        config, transcript, session_id=UUID_A, cwd=None, defer_companions=True
    )
    assert stored.action == "stored", stored
    assert full_problems(config) == ["JSONL does not match manifest source_hash"]

    result = run_ccw(["repair"], ccw_env)

    assert result.code == 0, f"{result.out!r} {result.err!r}"
    assert full_problems(config) == []
    manifest = cast(dict[str, object], json.loads((folder / "manifest.json").read_text("utf-8")))
    assert manifest["source_hash"] == store.sha256_hex(grown)


# ---------------------------------------------------------------------------
# 3. the alert: raised once per distinct problem set, recorded, never a daily nag
# ---------------------------------------------------------------------------


def test_the_refusal_alert_fires_once_and_refires_on_a_new_problem(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    alerts: list[str] = []

    def record(_config: object, _title: str, message: str) -> None:
        alerts.append(message)

    monkeypatch.setattr(notify, "alert", record)
    monkeypatch.setattr(notify, "speak", silent)
    flip_one_byte(targets(folder)["tool-result"])

    first = run_cli(["repair", "--quiet"])
    assert first.code == 1
    assert len(alerts) == 1, alerts
    assert folder.name in alerts[0] or "1 archive folder" in alerts[0], alerts[0]

    second = run_cli(["repair", "--quiet"])
    assert second.code == 1, "a refused folder must keep failing the job"
    assert len(alerts) == 1, f"the same refusal alerted again: {alerts}"

    flip_one_byte(targets(folder)["custom-title"])
    third = run_cli(["repair", "--quiet"])
    assert third.code == 1
    assert len(alerts) == 2, f"a NEW problem on the same folder did not re-alert: {alerts}"

    refusals = [r for r in repair_records(config) if r.get("status") == "repair-refused"]
    assert len(refusals) == 2, refusals
    assert all(r.get("session_uuid") == UUID_A for r in refusals)


def test_a_refusal_is_never_counted_as_an_unrecoverable_session(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reconciliation ledger reads capture.jsonl too; a refusal record must not
    look like a capture error to it."""
    from cc_warehouse import reconcile

    config, folder = rich_folder(ccw_env, tmp_path)
    monkeypatch.setattr(notify, "alert", silent)
    monkeypatch.setattr(notify, "speak", silent)
    flip_one_byte(targets(folder)["tool-result"])
    assert run_cli(["repair", "--quiet"]).code == 1
    assert reconcile.known_unrecoverable_uuids(config) == frozenset()
    assert reconcile.find_unrecoverable(config, since=None) == ()
