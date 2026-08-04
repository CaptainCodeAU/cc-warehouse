"""Oracle tests: a swept session lands READABLE, not just stored (ticket 25).

Contract: DESIGN 15 "ARCHIVE-FIRST LAYOUT" ("The product is a READABLE ARCHIVE
... the deliverable is the projected folder tree"), ruling (b) (`ccw verify` is
archive integrity: all five files present), and section 7's sweep row.

FOUND ON REAL DATA, 2026-08-04. The scheduled sweep ran and rescued 642 sessions
and 1,411 sub-agent transcripts with zero failures. Then `ccw archive --verify`
reported 3,194 problems: 721 archive folders held a conversation and NONE of the
five generated files.

The cause is structural, not a slip. The hook renders by spawning a DETACHED
CHILD (`cli._spawn_render` -> `ccw render --session`), and only `_run_hook` ever
calls it. `sweep.py` captures and stops, so every session it rescues is stored
and unreadable. That is the archive-first premise inverted: the payload is safe,
which was the design intent, and the deliverable is missing.

Spawning one detached child per item is not the fix at sweep's scale: this sweep
would have started 2,064 processes. Rendering happens in-process instead, at the
rate `ccw archive` already sustains (13,829 folders in 6.0 minutes, about 38 per
second), so the cost is roughly a doubling of a 40-second sweep rather than the
step change I first assumed.

THE TESTS PIN THE PROPERTY, NOT THE MECHANISM: a swept session is readable
afterwards. Whether that is an inline mirror or an incremental build is an
implementation choice, and these stay green either way.
"""

from pathlib import Path

from conftest import basic_session, run_ccw, warehouse_root, write_transcript

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
UUID_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
PROJECTIONS = (
    "transcript.md",
    "transcript.compact.md",
    "conversation.html",
    "conversation.compact.html",
    "manifest.json",
)


def configure(env: dict[str, str], archive_root: Path) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(
        f'root = "{warehouse_root(env)}"\n'
        f'archive_timezone = "{ZONE}"\n'
        f'archive_root = "{archive_root}"\n',
        encoding="utf-8",
    )
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def _session_dirs(archive_root: Path) -> list[Path]:
    return [
        s
        for proj in archive_root.iterdir()
        if proj.is_dir()
        for s in proj.iterdir()
        if s.is_dir()
    ]


def test_a_swept_session_is_readable_not_just_stored(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE LOAD-BEARING TEST. 721 folders on the real machine failed exactly this."""
    archive = tmp_path / "archive"
    configure(ccw_env, archive)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    assert run_ccw(["sweep"], ccw_env).code == 0

    dirs = _session_dirs(archive)
    assert len(dirs) == 1, dirs
    missing = [f for f in PROJECTIONS if not (dirs[0] / f).is_file()]
    assert not missing, f"swept session is not readable, missing: {missing}"


def test_the_payload_is_still_there_too(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Rendering must not come at the cost of the thing that made it safe.
    `_archive_source` writes the JSONL synchronously on purpose, so that a
    renderer failure can never be what loses a session."""
    archive = tmp_path / "archive"
    configure(ccw_env, archive)
    source = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    assert run_ccw(["sweep"], ccw_env).code == 0

    stored = next(_session_dirs(archive)[0].glob("*.jsonl"))
    assert stored.read_bytes() == source.read_bytes()


def test_every_session_in_a_batch_is_readable(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A batch, because the real failure was a batch: one item working proves
    nothing about the loop that follows it."""
    archive = tmp_path / "archive"
    configure(ccw_env, archive)
    for uuid in (UUID_A, UUID_B):
        write_transcript(ccw_env, basic_session(session_id=uuid), session_id=uuid)

    assert run_ccw(["sweep"], ccw_env).code == 0

    dirs = _session_dirs(archive)
    assert len(dirs) == 2, dirs
    for directory in dirs:
        missing = [f for f in PROJECTIONS if not (directory / f).is_file()]
        assert not missing, f"{directory.name} missing: {missing}"


def test_ccw_verify_passes_over_a_swept_archive(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The end-to-end statement of the same property, through the verb that
    caught it on real data (ruling (b))."""
    archive = tmp_path / "archive"
    configure(ccw_env, archive)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0

    result = run_ccw(["archive", "--verify", "--to", str(archive)], ccw_env)

    assert "0 problems" in result.out, result.out


def test_a_dry_run_still_writes_nothing(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Whatever rendering the real sweep now does, the rehearsal must not do it."""
    archive = tmp_path / "archive"
    configure(ccw_env, archive)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    assert run_ccw(["sweep", "--dry-run"], ccw_env).code == 0

    assert not archive.exists(), "a dry-run rendered into the archive"
    assert not warehouse_root(ccw_env).exists(), "a dry-run created the warehouse"
