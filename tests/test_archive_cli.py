"""Oracle tests: the `ccw archive` verb (ticket 19, slice 19h).

Until this verb exists the archive is something only a script can build, which
means the operator cannot regenerate, re-verify or re-zone a 5.1 GiB tree
without help. That is the worst property the post-migration state has and the
cheapest to fix.

Contract: DESIGN section 7 (the verb table and `-h` semantics); ruling (b)
2026-08-02 (verify = archive integrity: JSONL vs manifest source_hash, five
files present, folder name agrees with the payload); R5/R10 (report and carry
on); R13 (apply-class confirmation is explicit); F9 (sources read-only).
"""

import json
from pathlib import Path

from cc_warehouse import archive
from cc_warehouse.render import RenderOptions
from conftest import (
    entry,
    hook_payload,
    jsonl,
    run_ccw,
    run_cli,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "f1111111-2222-3333-4444-555555555551"
UUID_B = "f1111111-2222-3333-4444-555555555552"


def session(uuid: str, prompt: str = "Do the thing") -> bytes:
    return jsonl(
        entry(
            "user",
            prompt,
            "2026-05-07T03:47:45.000Z",
            session_id=uuid,
            gitBranch="main",
            version="2.0.0",
        ),
        entry(
            "assistant",
            [{"type": "text", "text": "Done."}],
            "2026-05-07T03:47:50.000Z",
            session_id=uuid,
        ),
    )


def capture(env: dict[str, str], uuid: str, data: bytes) -> None:
    transcript = write_transcript(env, data, session_id=uuid, name=f"{uuid}.jsonl")
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, cwd=None, session_id=uuid))
    assert result.code == 0, result.err


def populated(env: dict[str, str]) -> None:
    capture(env, UUID_A, session(UUID_A))
    capture(env, UUID_B, session(UUID_B, prompt="Second thing"))


# ---------------------------------------------------------------------------
# The verb exists, is listed, and its help does nothing
# ---------------------------------------------------------------------------


def test_archive_is_listed_in_the_top_level_help() -> None:
    """DESIGN 7: every user-facing verb appears in `ccw -h`. A verb that works
    but is not listed is a verb nobody finds."""
    listing = run_cli(["-h"]).out
    assert "archive" in listing


def test_archive_help_prints_options_and_performs_no_work(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The 2026-08-01 lesson, applied to a verb that did not exist then: asking a
    tool for help must not make it act. `ccw sweep -h` once imported 13,836
    sessions because eight verbs never checked the flag."""
    populated(ccw_env)
    target = tmp_path / "archive"
    before = tree_snapshot(warehouse_root(ccw_env))

    result = run_cli(["archive", "--to", str(target), "-h"])
    assert result.code == 0
    assert "--to" in result.out
    assert not target.exists(), "help built an archive"
    assert tree_snapshot(warehouse_root(ccw_env)) == before


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def test_archive_builds_the_tree_at_the_named_target(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    populated(ccw_env)
    target = tmp_path / "archive"
    result = run_cli(["archive", "--to", str(target)])
    assert result.code == 0, result.err
    folders = list(archive.walk_folders(target))
    assert len(folders) == 2
    for folder in folders:
        names = {p.name for p in folder.iterdir()}
        assert archive.GENERATED_NAMES[0] in names
        assert any(p.suffix == ".jsonl" for p in folder.iterdir())


def test_archive_leaves_the_source_warehouse_byte_identical(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Build BESIDE. The whole safety argument for running this on a live
    archive is that the old tree is not a participant."""
    populated(ccw_env)
    before = tree_snapshot(warehouse_root(ccw_env))
    result = run_cli(["archive", "--to", str(tmp_path / "archive")])
    assert result.code == 0, result.err
    assert tree_snapshot(warehouse_root(ccw_env)) == before


def test_archive_refuses_to_build_into_the_warehouse_itself(
    ccw_env: dict[str, str],
) -> None:
    """The one target that would make the operation destructive: writing the new
    tree on top of the vault it is reading from. Refused as a usage error before
    any work begins, never attempted and reported afterwards."""
    populated(ccw_env)
    root = warehouse_root(ccw_env)
    before = tree_snapshot(root)
    result = run_cli(["archive", "--to", str(root)])
    assert result.code != 0
    assert tree_snapshot(root) == before


def test_archive_requires_a_target(ccw_env: dict[str, str]) -> None:
    """No default target. A verb that picks a 5 GiB destination for you is a
    verb that writes 5 GiB somewhere you did not look."""
    populated(ccw_env)
    result = run_cli(["archive"])
    assert result.code != 0
    assert "--to" in (result.err + result.out)


def test_archive_prints_a_report_naming_what_it_did(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R10: a batch ends with a named-item report, not a bare count."""
    populated(ccw_env)
    result = run_cli(["archive", "--to", str(tmp_path / "archive")])
    assert "2 folders written" in result.out
    assert "0 failed" in result.out


def test_archive_is_idempotent_across_two_runs(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    populated(ccw_env)
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0
    first = tree_snapshot(target)
    assert run_cli(["archive", "--to", str(target)]).code == 0
    assert tree_snapshot(target) == first


# ---------------------------------------------------------------------------
# The zone
# ---------------------------------------------------------------------------


def test_the_zone_flag_overrides_the_configured_one(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Changing your mind about the zone must cost one command, not a
    conversation: every folder name in the tree depends on it."""
    populated(ccw_env)
    melbourne = tmp_path / "melbourne"
    utc = tmp_path / "utc"
    assert run_cli(["archive", "--to", str(melbourne), "--zone", ZONE]).code == 0
    assert run_cli(["archive", "--to", str(utc), "--zone", "UTC"]).code == 0
    mel_names = sorted(d.name for d in archive.walk_folders(melbourne))
    utc_names = sorted(d.name for d in archive.walk_folders(utc))
    assert mel_names != utc_names
    assert all("+1000_" in n for n in mel_names)
    assert all("+0000_" in n for n in utc_names)


def test_an_unknown_zone_is_a_usage_error_before_any_work(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A flag is validated up front and refused; a config file is recorded and
    the default kept (R5). This is the flag half of that split."""
    populated(ccw_env)
    target = tmp_path / "archive"
    result = run_cli(["archive", "--to", str(target), "--zone", "Mars/Olympus_Mons"])
    assert result.code != 0
    assert not target.exists()


# ---------------------------------------------------------------------------
# Verifying
# ---------------------------------------------------------------------------


def test_verify_flag_checks_an_existing_tree_and_exits_zero_when_clean(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    populated(ccw_env)
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0
    result = run_cli(["archive", "--to", str(target), "--verify"])
    assert result.code == 0, result.err
    assert "0 problems" in result.out or "intact" in result.out


def test_verify_exits_non_zero_and_names_a_tampered_folder(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Named, because a bare count of problems in a 13,829-folder tree is not
    something an operator can act on."""
    populated(ccw_env)
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0
    folder = next(archive.walk_folders(target))
    (folder / "conversation.html").rename(folder / "moved-away.html")

    result = run_cli(["archive", "--to", str(target), "--verify"])
    assert result.code != 0
    assert folder.name in (result.out + result.err)
    assert "conversation.html" in (result.out + result.err)


def test_verify_writes_nothing(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """A read-only-looking command must be PROVED read-only: exit 0 plus output
    is not evidence that nothing happened (2026-08-01)."""
    populated(ccw_env)
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0
    before = tree_snapshot(target)
    run_cli(["archive", "--to", str(target), "--verify"])
    assert tree_snapshot(target) == before


def test_verify_on_a_missing_tree_is_an_error_not_an_empty_pass(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The failure mode that reads as success: verifying nothing and reporting
    zero problems."""
    populated(ccw_env)
    result = run_cli(["archive", "--to", str(tmp_path / "never-built"), "--verify"])
    assert result.code != 0


def test_the_manifest_written_through_the_verb_carries_the_new_keys(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Tickets 18 and 20 reaching disk through the real verb, not through a
    library call a test made up."""
    populated(ccw_env)
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0
    folder = next(archive.walk_folders(target))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["unrecognised"] == {"count": 0, "types": []}
    assert manifest["withheld"] == {"thinking_blocks": 0}
    assert set(manifest["loss"]) == {
        "skipped_lines",
        "truncated_blocks",
        "truncated_chars",
        "unencodable_chars",
    }


def test_render_flags_reach_the_archive_verb(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The archive is built by the same emitters as everything else, so the same
    content flags govern it (R9). Otherwise the tree would be the one place your
    configuration silently does not apply."""
    populated(ccw_env)
    target = tmp_path / "archive"
    result = run_cli(
        ["archive", "--to", str(target), "--thinking-withheld", "marker"]
    )
    assert result.code == 0, result.err
    folder = next(archive.walk_folders(target))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["config"]["thinking_withheld"] == "marker"


def test_the_archive_verb_uses_the_default_render_options_otherwise(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    populated(ccw_env)
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0
    folder = next(archive.walk_folders(target))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["config"]["thinking_withheld"] == RenderOptions().thinking_withheld
