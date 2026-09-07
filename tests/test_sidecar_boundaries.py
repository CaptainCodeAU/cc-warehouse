"""Fences: the three places copied sidecars must NOT reach (ticket 38, slice 38f).

Kept in one file rather than scattered across the share, relocate and build
regression suites, because they are one question asked of three verbs: now that
raw tool output lives inside session folders, what is allowed to touch it?

  share     must not publish it. `tool-results/` holds whole file contents and
            unredacted command output; publishing one by accident is far worse
            than omitting it, which is the same argument that keeps sub-agents
            out of a share by default (ticket 21f).
  relocate  must not rewrite it. A copied tool result is SOURCE-CLASS data, and
            string-editing source is the F9 class this project's riskiest verb
            exists under.
  build     must not delete it. R4 as amended lets the rebuild module delete only
            files it GENERATED; a sidecar is copied, never generated.

All three hold by construction today. They are pinned anyway, because "safe by
construction" is a property of the current code and not of the next change to it.
"""

import json
from pathlib import Path

from conftest import basic_session, hook_payload, run_ccw, warehouse_root, write_transcript

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
ENCODED = "-home-alice-projects-widget"
SECRET = b"AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY\n"
STDOUT_NAME = "hook-9c2f1a7b-3d4e-5f60-8a91-b2c3d4e5f607-stdout.txt"


def configure(
    env: dict[str, str], archive_root: Path, *, relocate_root: Path | None = None
) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [
        f'root = "{warehouse_root(env)}"',
        f'archive_timezone = "{ZONE}"',
        f'archive_root = "{archive_root}"',
    ]
    if relocate_root is not None:
        lines.append("[relocate]")
        lines.append(f'roots = ["{relocate_root}"]')
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def plant_and_capture(env: dict[str, str], archive_root: Path) -> Path:
    """One session with one tool result holding an obvious secret."""
    transcript = write_transcript(env, basic_session(session_id=UUID_A), session_id=UUID_A)
    where = Path(env["HOME"]) / ".claude" / "projects" / ENCODED / UUID_A / "tool-results"
    where.mkdir(parents=True, exist_ok=True)
    (where / STDOUT_NAME).write_bytes(SECRET)
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, session_id=UUID_A))
    assert result.code == 0, result.err
    folders = sorted(archive_root.glob(f"*/*_{UUID_A}"))
    assert len(folders) == 1, folders
    return folders[0]


def short_id(env: dict[str, str]) -> str:
    from conftest import catalog_rows

    rows = catalog_rows(env, "SELECT short FROM session LIMIT 1")
    first = rows[0]
    assert isinstance(first, tuple)
    return f"s:{first[0]}"


# ---------------------------------------------------------------------------
# share must not publish it
# ---------------------------------------------------------------------------


def test_a_shared_bundle_contains_no_tool_result_file(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_and_capture(ccw_env, archive_root)
    out = tmp_path / "share"
    result = run_ccw(["share", short_id(ccw_env), "--out", str(out)], ccw_env)
    assert result.code == 0, result.err
    assert [p for p in out.rglob("*") if "tool-results" in p.parts] == []


def test_a_shared_bundle_carries_none_of_the_tool_results_bytes(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Not just "no file with that name". The secret must not appear ANYWHERE in
    the published bytes, by any route."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_and_capture(ccw_env, archive_root)
    out = tmp_path / "share"
    assert run_ccw(["share", short_id(ccw_env), "--out", str(out)], ccw_env).code == 0
    published = [p for p in out.rglob("*") if p.is_file()]
    # A control, so "no leak" cannot be satisfied by an empty bundle.
    assert any(p.suffix == ".html" for p in published), published
    leaked = [p for p in published if SECRET.strip() in p.read_bytes()]
    assert leaked == []


# ---------------------------------------------------------------------------
# relocate must not rewrite it
# ---------------------------------------------------------------------------


def test_relocate_never_modifies_a_file_under_tool_results(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The archive is inside a configured relocate root here, which is the exact
    shape B10 was found in: a root containing the warehouse must never rewrite
    stored bytes, because a file that stopped matching its own hash is
    indistinguishable from rot."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root, relocate_root=tmp_path)
    folder = plant_and_capture(ccw_env, archive_root)
    landed = folder / "tool-results" / STDOUT_NAME
    before = landed.read_bytes()
    run_ccw(["relocate", str(tmp_path / "widget"), "--to", str(tmp_path / "gadget")], ccw_env)
    assert landed.read_bytes() == before


# ---------------------------------------------------------------------------
# build must not delete it
# ---------------------------------------------------------------------------


def test_a_rebuild_never_touches_a_sidecar(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """R4 as amended: the rebuild module may delete only what it GENERATED. A
    sidecar is copied, so it is not the rebuild module's to remove - the same rule
    that keeps a session's own JSONL safe from it."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    folder = plant_and_capture(ccw_env, archive_root)
    landed = folder / "tool-results" / STDOUT_NAME
    before = (landed.read_bytes(), landed.stat().st_mtime_ns)
    assert run_ccw(["build", "--rebuild"], ccw_env).code == 0
    after = (landed.read_bytes(), landed.stat().st_mtime_ns)
    assert after == before


def test_a_rebuild_keeps_the_manifest_listing_the_sidecar(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The other half: surviving is not enough if the rebuild drops the record
    that makes a later deletion detectable."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    folder = plant_and_capture(ccw_env, archive_root)
    assert run_ccw(["build", "--rebuild"], ccw_env).code == 0
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    listed = manifest["tool_results"]
    assert isinstance(listed, list)
    assert len(listed) == 1


def test_a_rebuild_never_touches_a_sidecar_notice(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    folder = plant_and_capture(ccw_env, archive_root)
    notice = folder / "sidecars.json"
    notice.write_text('{"schema": 1, "unarchived": ["zzz"], "refused": [],'
                      ' "unknown_inside_subagents": []}', encoding="utf-8")
    before = notice.read_bytes()
    assert run_ccw(["build", "--rebuild"], ccw_env).code == 0
    assert notice.read_bytes() == before
