"""Oracle tests: two new files Claude Code writes beside a session (2026-11-02).

    <uuid>/auto-mode-classifier-error.txt          beside subagents/, one flat file
    <uuid>/subagents/agent-<id>.prefix.json        beside each sub-agent transcript

Both were found by the ticket 38 notice doing its job: `ccw doctor`'s sidecars
line named them, and nothing copied them. Measured on the live machine the day
they were taken in: one classifier error report (266,958 bytes, 522 lines, the
debug dump Claude Code writes when auto mode's safety check fails) and four
prefix files (6.5 to 7.6 KB each, how the sub-agent started: model, tool names,
feature flags, an outline of its instructions; 3 of its 13 long text pieces
appear nowhere in the sub-agent's transcript).

THE ERROR REPORT IS A PLAIN FILE, NOT A MANIFEST KEY. `custom-title.json` has
its own manifest record because the title is shown and must not drift from the
render; this file is only kept. A manifest key would bump what every folder's
manifest must say, so a whole-corpus re-render for a debug file. So: copied by
`write_if_changed` (Claude Code rewrites the file in place when the check fails
again; the archive keeps the latest), never checked by `verify_folder`, never
deleted by the rebuilder (it is not in GENERATED_NAMES).

THE PREFIX FILE TRAVELS LIKE `.forked-skill.json` already does: inside the
sub-agent's own folder, as one more companion of its payload.

Contract: R2, R4, R9, R10; FINDINGS F6; section 15 ruling (c).
"""

from pathlib import Path

from cc_warehouse import archive, sidecars
from cc_warehouse.render import RenderOptions
from conftest import (
    basic_session,
    hook_payload,
    mark_archive,
    run_ccw,
    settle_companions,
    subagent_meta,
    subagent_session,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
PARENT = "d3111111-2222-3333-4444-555555555551"
AGENT = "a94d30c1d877f964d"
ENCODED = "-home-alice-projects-widget"
ERROR_NAME = "auto-mode-classifier-error.txt"
ERROR_BYTES = b"=== error ===\ntimestamp: 2026-10-02T02:12:12Z\nmodel: m\n"
PREFIX_NAME = f"agent-{AGENT}.prefix.json"
PREFIX_BYTES = b'{"v":1,"by":"x","state":{"toolNames":["Read"]},"outlines":[]}\n'


def configure(env: dict[str, str], archive_root: Path) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [
        f'root = "{warehouse_root(env)}"',
        f'archive_timezone = "{ZONE}"',
        f'archive_root = "{archive_root}"',
    ]
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)
    mark_archive(archive_root, ZONE)


def sidecar_root(env: dict[str, str]) -> Path:
    return Path(env["HOME"]) / ".claude" / "projects" / ENCODED / PARENT


def plant_session(env: dict[str, str]) -> Path:
    return write_transcript(
        env, basic_session(session_id=PARENT), session_id=PARENT, name=f"{PARENT}.jsonl"
    )


def plant_subagent(env: dict[str, str], *, with_prefix: bool) -> None:
    subs = sidecar_root(env) / "subagents"
    subs.mkdir(parents=True, exist_ok=True)
    (subs / f"agent-{AGENT}.jsonl").write_bytes(
        subagent_session(agent_id=AGENT, parent_uuid=PARENT)
    )
    (subs / f"agent-{AGENT}.meta.json").write_bytes(subagent_meta())
    if with_prefix:
        (subs / PREFIX_NAME).write_bytes(PREFIX_BYTES)


def plant_error(env: dict[str, str], data: bytes = ERROR_BYTES) -> None:
    root = sidecar_root(env)
    root.mkdir(parents=True, exist_ok=True)
    (root / ERROR_NAME).write_bytes(data)


def fire_hook(env: dict[str, str], transcript: Path) -> None:
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, session_id=PARENT))
    assert result.code == 0, result.err


def sweep(env: dict[str, str], *extra: str) -> str:
    result = run_ccw(["sweep", *extra], env)
    assert result.code == 0, result.err + result.out
    return result.out


def session_folder(archive_root: Path) -> Path:
    folders = sorted(archive_root.glob(f"*/*_{PARENT}"))
    assert len(folders) == 1, f"expected one session folder, got {folders}"
    return folders[0]


def prefix_copies(archive_root: Path) -> list[Path]:
    return sorted(session_folder(archive_root).glob(f"subagents/*_{AGENT}/{PREFIX_NAME}"))


# ---------------------------------------------------------------------------
# The fence: a known name has a copier, and neither is a stranger any more
# ---------------------------------------------------------------------------


def test_the_error_report_is_a_known_sidecar_name() -> None:
    assert sidecars.CLASSIFIER_ERROR_FILE == ERROR_NAME
    assert ERROR_NAME in sidecars.SESSION_SIDECARS


def test_the_error_report_has_a_registered_copier() -> None:
    assert archive.COPIERS[ERROR_NAME] == "write_session_file"
    assert callable(archive.write_session_file)


def test_the_scan_no_longer_calls_either_file_a_stranger(tmp_path: Path) -> None:
    project = tmp_path / ENCODED
    project.mkdir()
    transcript = project / f"{PARENT}.jsonl"
    transcript.write_bytes(b"{}\n")
    subs = project / PARENT / "subagents"
    subs.mkdir(parents=True)
    (subs / f"agent-{AGENT}.jsonl").write_bytes(b"{}\n")
    (subs / PREFIX_NAME).write_bytes(b"{}\n")
    (project / PARENT / ERROR_NAME).write_bytes(b"x\n")
    scan = sidecars.scan(transcript, PARENT)
    assert scan.unknown == ()
    assert scan.unknown_inside_subagents == ()
    assert ERROR_NAME in scan.known


def test_a_still_unknown_name_inside_subagents_is_still_reported(tmp_path: Path) -> None:
    """The control: widening the pattern must not make it accept everything."""
    project = tmp_path / ENCODED
    project.mkdir()
    transcript = project / f"{PARENT}.jsonl"
    transcript.write_bytes(b"{}\n")
    subs = project / PARENT / "subagents"
    subs.mkdir(parents=True)
    (subs / f"agent-{AGENT}.prefixes.json").write_bytes(b"{}\n")
    assert sidecars.scan(transcript, PARENT).unknown_inside_subagents == (
        f"agent-{AGENT}.prefixes.json",
    )


# ---------------------------------------------------------------------------
# write_session_file
# ---------------------------------------------------------------------------


def _folder(root: Path) -> Path:
    return archive.write_session_folder(
        root, "widget", basic_session(session_id=PARENT), RenderOptions(), ZONE,
        fallback_stem="session",
    ).directory


def test_write_session_file_lands_the_bytes_at_the_same_name(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    assert archive.write_session_file(folder, ERROR_NAME, ERROR_BYTES) is True
    assert (folder / ERROR_NAME).read_bytes() == ERROR_BYTES


def test_write_session_file_writes_nothing_when_unchanged(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    archive.write_session_file(folder, ERROR_NAME, ERROR_BYTES)
    assert archive.write_session_file(folder, ERROR_NAME, ERROR_BYTES) is False


def test_write_session_file_refuses_a_name_that_is_not_a_plain_file_sidecar(
    tmp_path: Path,
) -> None:
    """It must never become a way to overwrite the manifest or the payload."""
    folder = _folder(tmp_path)
    for bad in ("manifest.json", "custom-title.json", "../escape.txt", "subagents"):
        try:
            archive.write_session_file(folder, bad, b"x")
        except ValueError:
            continue
        raise AssertionError(f"write_session_file accepted {bad!r}")


def test_the_error_report_does_not_make_a_folder_fail_verification(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    archive.write_session_file(folder, ERROR_NAME, ERROR_BYTES)
    assert archive.verify_folder(folder, ZONE) == []


def test_a_rebuild_leaves_the_error_report_alone(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    archive.write_session_file(folder, ERROR_NAME, ERROR_BYTES)
    archive.write_session_folder(
        tmp_path, "widget", basic_session(session_id=PARENT), RenderOptions(), ZONE,
        rebuild=True, fallback_stem="session",
    )
    assert (folder / ERROR_NAME).read_bytes() == ERROR_BYTES


# ---------------------------------------------------------------------------
# The hook path
# ---------------------------------------------------------------------------


def test_the_hook_brings_the_error_report(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant_session(ccw_env)
    plant_error(ccw_env)
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    assert (session_folder(archive_root) / ERROR_NAME).read_bytes() == ERROR_BYTES


def test_the_hook_brings_the_prefix_file_with_its_subagent(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant_session(ccw_env)
    plant_subagent(ccw_env, with_prefix=True)
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    landed = prefix_copies(archive_root)
    assert len(landed) == 1, landed
    assert landed[0].read_bytes() == PREFIX_BYTES


def test_the_hook_writes_no_notice_for_either_file(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant_session(ccw_env)
    plant_subagent(ccw_env, with_prefix=True)
    plant_error(ccw_env)
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    assert not (session_folder(archive_root) / "sidecars.json").exists()


def test_the_source_files_are_not_touched(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant_session(ccw_env)
    plant_subagent(ccw_env, with_prefix=True)
    plant_error(ccw_env)
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    assert (sidecar_root(ccw_env) / ERROR_NAME).read_bytes() == ERROR_BYTES
    assert (sidecar_root(ccw_env) / "subagents" / PREFIX_NAME).read_bytes() == PREFIX_BYTES


# ---------------------------------------------------------------------------
# The sweep path: the back-fill for sessions archived before today
# ---------------------------------------------------------------------------


def test_a_sweep_backfills_the_error_report(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant_session(ccw_env)
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    plant_error(ccw_env)
    sweep(ccw_env)
    assert (session_folder(archive_root) / ERROR_NAME).read_bytes() == ERROR_BYTES


def test_a_sweep_keeps_the_latest_error_report(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant_session(ccw_env)
    plant_error(ccw_env)
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    later = ERROR_BYTES + b"=== error ===\ntimestamp: 2026-10-03T00:00:00Z\n"
    plant_error(ccw_env, later)
    sweep(ccw_env)
    assert (session_folder(archive_root) / ERROR_NAME).read_bytes() == later


def test_a_sweep_backfills_the_prefix_file_for_an_archived_subagent(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The live case: the 4 real sub-agents were archived on 28 October with
    their prefix files left behind, and their transcripts will never change."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant_session(ccw_env)
    plant_subagent(ccw_env, with_prefix=False)
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    assert prefix_copies(archive_root) == []
    (sidecar_root(ccw_env) / "subagents" / PREFIX_NAME).write_bytes(PREFIX_BYTES)
    sweep(ccw_env)
    landed = prefix_copies(archive_root)
    assert len(landed) == 1, landed
    assert landed[0].read_bytes() == PREFIX_BYTES


def test_a_dry_run_sweep_names_the_error_report_and_writes_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant_session(ccw_env)
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    plant_error(ccw_env)
    out = sweep(ccw_env, "--dry-run")
    assert f"would-archive-sidecars: {PARENT}.jsonl" in out
    assert not (session_folder(archive_root) / ERROR_NAME).exists()
