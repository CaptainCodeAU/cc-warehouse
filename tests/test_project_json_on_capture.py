"""Oracle tests: the sidecar is written by whatever CREATES the folder (28.21).

Ticket 19f shipped `project.json` and proved the round trip, and the proof was
sound. What no test asked was WHO writes it. `archive.write_project_files` had
exactly one caller, the `ccw archive` verb, so every project folder created by
capture or import afterwards had no sidecar and nobody found out.

Measured on the real archive 2026-08-05, during ticket 27.2's rebuild:

    label dirs on disk ........  90
    read_projects recovers ....  57
    aliases recovered .........  114 of 4,913   (2.3%)

Sessions and labels round-tripped perfectly; aliases did not. Ticket 27.4
deletes `objects/` on the argument that the archive is a complete substitute,
so this had to close before that could be true.

THE SHAPE OF THE BUG IS THE INTERESTING PART, and it is why these tests are
about the WRITE path rather than about the file's contents. 19f's tests all ran
`ccw archive` first, so they exercised the one caller that did the right thing.
A green suite is a statement about the inputs you imagined.

Contract: DESIGN 15 (the catalog is a disposable index), R2 (tmp-file plus
os.replace), R9/F8 (one implementation), F6, F9, DESIGN 12 (the capture path
never turns a stored session into a reported failure).
"""

import json
from pathlib import Path
from typing import cast

from conftest import (
    catalog_path,
    entry,
    hook_payload,
    jsonl,
    run_ccw,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "c3111111-2222-3333-4444-555555555551"
UUID_B = "c3111111-2222-3333-4444-555555555552"
UUID_C = "c3111111-2222-3333-4444-555555555553"
CWD_A = "/home/alice/projects/widget"
CWD_B = "/home/alice/projects/gadget"


def session(uuid: str, cwd: str) -> bytes:
    return jsonl(
        entry(
            "user",
            "Do the thing",
            "2026-05-07T03:47:45.000Z",
            session_id=uuid,
            cwd=cwd,
            gitBranch="main",
        ),
        entry(
            "assistant",
            [{"type": "text", "text": "Done."}],
            "2026-05-07T03:47:50.000Z",
            session_id=uuid,
            cwd=cwd,
        ),
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


def capture(env: dict[str, str], uuid: str, cwd: str, encoded: str = "-home-alice") -> None:
    data = session(uuid, cwd)
    transcript = write_transcript(
        env, data, session_id=uuid, encoded_dir=encoded, name=f"{uuid}.jsonl"
    )
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, cwd=cwd, session_id=uuid))
    assert result.code == 0, result.err


def sidecars(archive_root: Path) -> list[Path]:
    return sorted(archive_root.glob("*/project.json"))


def sidecar_of(archive_root: Path, label_dir: str) -> dict[str, object]:
    raw = (archive_root / label_dir / "project.json").read_text(encoding="utf-8")
    loaded: object = json.loads(raw)
    assert isinstance(loaded, dict)
    return cast("dict[str, object]", loaded)


# ---------------------------------------------------------------------------
# The capture path writes it. This is the whole ticket.
# ---------------------------------------------------------------------------


def test_a_captured_session_gets_a_project_json_without_running_archive(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """28.21. `ccw archive` is NEVER run here, which is the entire point: before
    this fix the only caller of the sidecar writer was that verb."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)

    capture(ccw_env, UUID_A, CWD_A)

    assert sidecars(archive_root), "capture created a project folder with no project.json"


def test_the_sidecar_carries_the_exact_label_and_every_alias(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The LABEL survives without the sidecar because it is the folder name.
    `project_alias` does not, and it is what stops a renamed project splitting
    in two on the next capture."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)

    capture(ccw_env, UUID_A, CWD_A, encoded="-home-alice-projects-widget")

    found = sidecars(archive_root)
    assert len(found) == 1, found
    payload = sidecar_of(archive_root, found[0].parent.name)
    raw = payload["aliases"]
    assert isinstance(raw, list)
    aliases = cast("list[object]", raw)
    assert aliases, "the sidecar recorded no aliases, which is the 2.3% bug"
    paths = {
        str(cast("dict[str, object]", a)["path"]) for a in aliases if isinstance(a, dict)
    }
    assert CWD_A in paths


def test_two_projects_each_get_their_own_sidecar(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)

    capture(ccw_env, UUID_A, CWD_A, encoded="-home-alice-projects-widget")
    capture(ccw_env, UUID_B, CWD_B, encoded="-home-alice-projects-gadget")

    assert len(sidecars(archive_root)) == 2


def test_sweep_writes_sidecars_too(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """`sweep` routes through `capture.capture_transcript` exactly as the hook
    does, so one fix should serve both. VERIFIED by running it, not assumed."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(
        ccw_env,
        session(UUID_C, CWD_A),
        session_id=UUID_C,
        encoded_dir="-home-alice-projects-widget",
        name=f"{UUID_C}.jsonl",
    )

    result = run_ccw(["sweep"], ccw_env)

    assert result.code == 0, result.err
    assert sidecars(archive_root), "a swept session's project folder has no sidecar"


def test_import_writes_sidecars_too(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Same claim for `ccw import`, and the import path is the one that created
    most of the 33 sidecar-less folders on the real archive."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    foreign = tmp_path / "foreign"
    (foreign / "someproject").mkdir(parents=True)
    (foreign / "someproject" / f"{UUID_C}.jsonl").write_bytes(session(UUID_C, CWD_B))

    result = run_ccw(["import", "--from", str(foreign)], ccw_env)

    assert result.code == 0, result.err
    assert sidecars(archive_root), "an imported session's project folder has no sidecar"


# ---------------------------------------------------------------------------
# It must not cost anything it does not have to
# ---------------------------------------------------------------------------


def test_an_unchanged_sidecar_is_not_rewritten(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A 4,756-payload import would otherwise rewrite one project's sidecar
    thousands of times. Compare bytes and skip, which also keeps the file
    mtime-stable the way the projection writer is."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    capture(ccw_env, UUID_A, CWD_A, encoded="-home-alice-projects-widget")
    target = sidecars(archive_root)[0]
    before = target.stat().st_mtime_ns

    capture(ccw_env, UUID_C, CWD_A, encoded="-home-alice-projects-widget")

    assert target.stat().st_mtime_ns == before, "an unchanged sidecar was rewritten"


def test_a_new_alias_does_refresh_the_sidecar(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The skip must be on CONTENT, not on existence: a project that learns a
    new path has to have it recorded, or the skip becomes the bug."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    capture(ccw_env, UUID_A, CWD_A, encoded="-home-alice-projects-widget")
    target = sidecars(archive_root)[0]
    before = json.loads(target.read_text(encoding="utf-8"))

    # Same project (same cwd resolves to it), reached through a NEW encoded dir.
    capture(ccw_env, UUID_C, CWD_A, encoded="-a-different-encoded-dir")

    after = json.loads(target.read_text(encoding="utf-8"))
    assert after != before, "a newly learned alias never reached the sidecar"


# ---------------------------------------------------------------------------
# It must never cost a capture
# ---------------------------------------------------------------------------


def test_a_sidecar_that_cannot_be_written_does_not_fail_the_capture(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """DESIGN 12: the capture path never turns a stored session into a reported
    failure. A sidecar is an INDEX AID, not the payload; the session is safe
    without it, so failing a capture over one would be the wrong trade. The
    payload write does raise when the vault is gone, and that difference is
    deliberate."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    capture(ccw_env, UUID_A, CWD_A, encoded="-home-alice-projects-widget")
    label_dir = sidecars(archive_root)[0].parent
    # A directory where the file must go: the write fails, the capture must not.
    (label_dir / "project.json").unlink()
    (label_dir / "project.json").mkdir()

    data = session(UUID_C, CWD_A)
    transcript = write_transcript(
        ccw_env,
        data,
        session_id=UUID_C,
        encoded_dir="-home-alice-projects-widget",
        name=f"{UUID_C}.jsonl",
    )
    result = run_ccw(
        ["hook"], ccw_env, stdin=hook_payload(transcript, cwd=CWD_A, session_id=UUID_C)
    )

    assert result.code == 0, result.err
    assert sorted(archive_root.glob("*/*/*.jsonl")), "the session itself was not archived"


# ---------------------------------------------------------------------------
# THE END TO END PROOF: capture only, never `ccw archive`, then rebuild
# ---------------------------------------------------------------------------


def test_capture_only_then_reindex_recovers_labels_and_aliases(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The claim 28.21 broke, restated as a test that could not pass before.

    `ccw archive` is never run. Sessions arrive only through capture, the
    catalog is deleted, and `ccw reindex` rebuilds it from the tree. The fixture
    is asserted to hold aliases FIRST, because a round trip over an empty set
    passes for the wrong reason (19f's lesson)."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    capture(ccw_env, UUID_A, CWD_A, encoded="-home-alice-projects-widget")
    capture(ccw_env, UUID_B, CWD_B, encoded="-home-alice-projects-gadget")

    import sqlite3

    with sqlite3.connect(catalog_path(ccw_env)) as conn:
        before_labels = sorted(str(r[0]) for r in conn.execute("SELECT label FROM project"))
        before_aliases = sorted(
            (str(r[0]), str(r[1])) for r in conn.execute("SELECT path, kind FROM project_alias")
        )
    assert before_aliases, "fixture stored no aliases, the round trip would prove nothing"

    catalog_path(ccw_env).unlink()
    result = run_ccw(["reindex", "--from", str(archive_root)], ccw_env)
    assert result.code == 0, result.err

    with sqlite3.connect(catalog_path(ccw_env)) as conn:
        after_labels = sorted(str(r[0]) for r in conn.execute("SELECT label FROM project"))
        after_aliases = sorted(
            (str(r[0]), str(r[1])) for r in conn.execute("SELECT path, kind FROM project_alias")
        )

    assert after_labels == before_labels
    assert after_aliases == before_aliases
