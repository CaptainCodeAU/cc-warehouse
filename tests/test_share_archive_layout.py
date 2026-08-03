"""Oracle tests: a shared bundle looks like the archive it came from (19g).

Ruling (c), 2026-08-02: "`ccw share` KEEPS THE SAME LAYOUT, continuing to call
the one shared directory-naming function it already uses. One implementation
(R9); a shared bundle looks exactly like the archive it came from."

Share was still naming its directories the pre-archive way,
`<YYYY-MM-DD>_<slug>_s-<short>`, so a bundle and the archive it was built from
disagreed about what a session folder is called. That is the F8 class arriving
by omission rather than by copy-paste: one truth, two spellings, and the second
one only wrong because nobody moved it.

Contract: ruling (c) 2026-08-02; R9; DESIGN 9 (share stays sanitized and
self-contained); the redaction promises are unchanged and re-asserted here so
this slice cannot quietly weaken them.
"""

import json
from pathlib import Path

from cc_warehouse.build import archive_folder_name
from conftest import (
    entry,
    hook_payload,
    jsonl,
    run_ccw,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "c7111111-2222-3333-4444-555555555551"
CWD = "/home/alice/projects/widget"
FIRST_TS = "2026-05-07T03:47:45.000Z"


def session(uuid: str, text: str = "Ordinary content") -> bytes:
    return jsonl(
        entry(
            "user",
            text,
            FIRST_TS,
            session_id=uuid,
            cwd=CWD,
            gitBranch="main",
            slug="widget-work",
        ),
        entry(
            "assistant",
            [{"type": "text", "text": "Done."}],
            "2026-05-07T03:47:50.000Z",
            session_id=uuid,
            cwd=CWD,
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


def capture(env: dict[str, str], uuid: str, data: bytes) -> str:
    transcript = write_transcript(env, data, session_id=uuid, name=f"{uuid}.jsonl")
    assert (
        run_ccw(["hook"], env, stdin=hook_payload(transcript, cwd=CWD, session_id=uuid)).code == 0
    )
    from conftest import catalog_rows

    rows = catalog_rows(env, "SELECT short FROM session")
    assert rows, "fixture stored nothing"
    return str(tuple(rows[0])[0])  # type: ignore[index]


def shared_dirs(out: Path) -> list[Path]:
    return sorted(p for p in out.rglob("*") if p.is_dir() and (p / "transcript.md").is_file())


# ---------------------------------------------------------------------------
# The layout
# ---------------------------------------------------------------------------


def test_a_shared_session_dir_uses_the_archive_folder_name(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    configure(ccw_env, tmp_path / "archive")
    short = capture(ccw_env, UUID_A, session(UUID_A))
    out = tmp_path / "bundle"
    result = run_ccw(["share", f"s:{short}", "--out", str(out)], ccw_env)
    assert result.code == 0, result.err + result.out

    dirs = shared_dirs(out)
    assert len(dirs) == 1, dirs
    assert dirs[0].name == archive_folder_name(FIRST_TS, UUID_A, ZONE)


def test_the_old_projection_naming_is_gone(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The specific spelling this slice removes. Asserted directly, because a
    test that only checks the NEW name would pass while both existed."""
    configure(ccw_env, tmp_path / "archive")
    short = capture(ccw_env, UUID_A, session(UUID_A))
    out = tmp_path / "bundle"
    assert run_ccw(["share", f"s:{short}", "--out", str(out)], ccw_env).code == 0

    name = shared_dirs(out)[0].name
    assert "_s-" not in name, name
    assert not name.startswith("2026-05-07_"), name


def test_the_bundle_and_the_archive_agree_on_the_folder_name(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R9 stated as the property rather than as a call site: the two trees must
    name the same session identically, whichever function each happens to use."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    short = capture(ccw_env, UUID_A, session(UUID_A))
    assert run_ccw(["build", "--rebuild"], ccw_env).code == 0
    out = tmp_path / "bundle"
    assert run_ccw(["share", f"s:{short}", "--out", str(out)], ccw_env).code == 0

    from cc_warehouse import archive

    archived = next(archive.walk_folders(archive_root)).name
    assert shared_dirs(out)[0].name == archived


def test_the_configured_zone_reaches_the_bundle(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    configure(ccw_env, tmp_path / "archive")
    short = capture(ccw_env, UUID_A, session(UUID_A))
    out = tmp_path / "bundle"
    assert run_ccw(["share", f"s:{short}", "--out", str(out)], ccw_env).code == 0
    assert "+1000_" in shared_dirs(out)[0].name


# ---------------------------------------------------------------------------
# Nothing else about share moves
# ---------------------------------------------------------------------------


def test_the_bundle_still_carries_the_four_files_and_a_manifest(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    configure(ccw_env, tmp_path / "archive")
    short = capture(ccw_env, UUID_A, session(UUID_A))
    out = tmp_path / "bundle"
    assert run_ccw(["share", f"s:{short}", "--out", str(out)], ccw_env).code == 0
    names = {p.name for p in shared_dirs(out)[0].iterdir()}
    for expected in (
        "transcript.md",
        "transcript.compact.md",
        "conversation.html",
        "conversation.compact.html",
        "manifest.json",
    ):
        assert expected in names, expected


def test_a_shared_page_still_makes_no_third_party_request(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """DESIGN 15 item 8. Re-asserted here because this slice touches the share
    path, and a redaction or self-containment promise that quietly weakens while
    a layout changes is exactly the drift F6 exists to catch."""
    configure(ccw_env, tmp_path / "archive")
    short = capture(ccw_env, UUID_A, session(UUID_A))
    out = tmp_path / "bundle"
    assert run_ccw(["share", f"s:{short}", "--out", str(out)], ccw_env).code == 0
    page = (shared_dirs(out)[0] / "conversation.html").read_text(encoding="utf-8")
    assert "cdnjs" not in page
    assert "https://" not in page.split("<body")[0], "the head references something external"


def test_the_shared_jsonl_is_not_included(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The archive folder holds the raw session; a SHARED bundle must not, or
    redaction would be pointless - the unredacted source would ship beside the
    sanitized rendering."""
    configure(ccw_env, tmp_path / "archive")
    short = capture(ccw_env, UUID_A, session(UUID_A))
    out = tmp_path / "bundle"
    assert run_ccw(["share", f"s:{short}", "--out", str(out)], ccw_env).code == 0
    assert not list(out.rglob("*.jsonl")), "the raw payload shipped in a share"


def test_the_manifest_in_a_bundle_is_still_a_manifest(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    configure(ccw_env, tmp_path / "archive")
    short = capture(ccw_env, UUID_A, session(UUID_A))
    out = tmp_path / "bundle"
    assert run_ccw(["share", f"s:{short}", "--out", str(out)], ccw_env).code == 0
    manifest = json.loads(
        (shared_dirs(out)[0] / "manifest.json").read_text(encoding="utf-8")
    )
    assert "source_hash" in manifest
    assert "loss" in manifest
