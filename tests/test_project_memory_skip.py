"""Oracle tests: a project's `memory/` folder is never walked for transcripts (W-20260930-A59).

THE INCIDENT, 2026-09-30. The 12:30 `ccw sweep` cataloged 8 files that were not
transcripts: `claude -p --output-format stream-json` captures kept in a pj
record folder, `<project-key>/memory/WORK/...`. Every build after that tried
them and failed.

THE RULE, ruled by Gavin 2026-10-11 (cc-warehouse-main Q3 v2: 1) after a
re-measure of the live tree: the session test stays `archive.is_session` (a
session id, not a sub-agent), and `<project-key>/memory/` under the source
tree is never a session, for every consumer of the walk. It replaces the
2026-10-02 "user plus assistant lines" rule, which the re-measure showed would
have stopped archiving 18,239 one-sided files (18,019 background sdk-cli calls,
220 unanswered cli sessions). The 2026-09-30 guards (a) build-skip and (b)
capture-refusal were dropped: (b) was ruled obsolete 2026-10-02, and (a) has no
remaining trigger since W-20261001-A56 made the 8 rows' bytes findable.

Contract: DESIGN R5/F7 (conservative branch), R9 (one walk, one predicate).
"""

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from cc_warehouse import archive, config, doctor, import_tree, migrate, status, sweep
from conftest import (
    SRC_ROOT,
    entry,
    jsonl,
    mark_archive,
    run_ccw,
    warehouse_root,
    write_transcript,
)

ZONE = "UTC"
UUID_A = "a5911111-2222-3333-4444-555555555551"
UUID_B = "a5911111-2222-3333-4444-555555555552"
UUID_MEM = "a5911111-2222-3333-4444-5555555555ee"
CWD = "/home/alice/projects/widget"
ENCODED = "-home-alice-projects-widget"


def session(uuid: str, ts: str = "2026-05-07T03:47:45.000Z") -> bytes:
    return jsonl(
        entry("user", "Do the thing", ts, session_id=uuid, cwd=CWD, gitBranch="main"),
        entry("assistant", [{"type": "text", "text": "Done."}], ts, session_id=uuid, cwd=CWD),
    )


def stream_json(tag: str = "armA") -> bytes:
    """A `claude -p --output-format stream-json` capture.

    THE SHAPE IS THE REAL TOOL'S, NOT A GUESS. Line types, subtypes and key
    sets were read off one of the 8 real files on 2026-09-30
    (`memory/WORK/temp-cleanup/armA.jsonl`, 52 lines): `system` lines with
    `hook_started`/`init` subtypes, `assistant` and `user` lines with a
    `timestamp`, a `rate_limit_event`, and a closing `result`. Every line
    carries `session_id` in SNAKE case and none carries `sessionId`, which is
    what makes it name no session to this product. Values are placeholders.
    """
    sid = "5e722222-2222-3333-4444-555555555555"
    lines: list[dict[str, object]] = [
        {"type": "system", "subtype": "hook_started", "hook_id": "h1",
         "hook_name": "SessionStart", "hook_event": "SessionStart",
         "session_id": sid, "uuid": "u1"},
        {"type": "system", "subtype": "init", "cwd": CWD, "session_id": sid,
         "model": "claude-opus-5-5", "tools": [], "uuid": "u2"},
        {"type": "assistant", "session_id": sid, "uuid": "u3", "parent_tool_use_id": None,
         "timestamp": "2026-09-29T14:00:55.308Z",
         "message": {"role": "assistant", "type": "message", "id": "m1",
                     "content": [{"type": "text", "text": f"probe {tag}"}]}},
        {"type": "rate_limit_event", "session_id": sid, "uuid": "u4",
         "rate_limit_info": {}},
        {"type": "user", "session_id": sid, "uuid": "u5", "parent_tool_use_id": None,
         "timestamp": "2026-09-29T14:00:56.000Z",
         "message": {"role": "user", "content": "ok"}},
        {"type": "result", "subtype": "success", "session_id": sid, "uuid": "u6",
         "is_error": False, "num_turns": 1, "result": "done"},
    ]
    return jsonl(*lines)


def configure(env: dict[str, str], archive_root: Path, *, keep_objects: bool) -> config.Config:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(
        "\n".join([
            f'root = "{warehouse_root(env)}"',
            f'archive_root = "{archive_root}"',
            f'archive_timezone = "{ZONE}"',
            "keep_projections = false",
            f"keep_objects = {'true' if keep_objects else 'false'}",
        ]) + "\n",
        encoding="utf-8",
    )
    env["XDG_CONFIG_HOME"] = str(cfg.parent)
    if not (archive_root / archive.ROOT_MARKER).is_file():
        mark_archive(archive_root, ZONE)
    return config.load_config(xdg_config_home=cfg.parent)


def projects(env: dict[str, str]) -> Path:
    return Path(env["HOME"]) / ".claude" / "projects"


def put(env: dict[str, str], rel: str, data: bytes) -> Path:
    path = projects(env) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def uuids(env: dict[str, str]) -> list[str | None]:
    from conftest import catalog_rows

    rows = catalog_rows(env, "SELECT session_uuid FROM session ORDER BY session_uuid")
    return [cast("tuple[str | None]", row)[0] for row in rows]


def memory_transcript(env: dict[str, str], ts: str = "2026-05-01T00:00:00.000Z") -> Path:
    """A file that LOOKS like a real transcript, `sessionId` and all, so the
    session test cannot be what keeps it out: only the discovery guard can."""
    return put(env, f"{ENCODED}/memory/WORK/items/{UUID_MEM}.jsonl", session(UUID_MEM, ts))


def test_sweep_does_not_capture_anything_under_a_project_memory_dir(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    configure(ccw_env, tmp_path / "archive", keep_objects=False)
    memory_transcript(ccw_env)
    put(ccw_env, f"{ENCODED}/memory/WORK/temp-cleanup/armA.jsonl", stream_json())
    write_transcript(ccw_env, session(UUID_A), session_id=UUID_A)
    result = run_ccw(["sweep"], ccw_env)
    assert result.code == 0, result.err
    assert uuids(ccw_env) == [UUID_A]


def test_the_dry_run_does_not_list_it(ccw_env: dict[str, str], tmp_path: Path) -> None:
    cfg = configure(ccw_env, tmp_path / "archive", keep_objects=False)
    memory_transcript(ccw_env)
    write_transcript(ccw_env, session(UUID_A), session_id=UUID_A)
    report = sweep.plan(cfg, projects(ccw_env))
    assert [o.item for o in report.outcomes] == [f"{UUID_A}.jsonl"]


def test_source_transcripts_does_not_list_it(ccw_env: dict[str, str]) -> None:
    memory_transcript(ccw_env)
    put(ccw_env, f"{ENCODED}/memory/agent-x.jsonl", session(UUID_MEM))
    real = write_transcript(ccw_env, session(UUID_A), session_id=UUID_A)
    assert sweep.source_transcripts(projects(ccw_env)) == ([real], [])


def test_status_does_not_count_it_as_uncaptured(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    cfg = configure(ccw_env, tmp_path / "archive", keep_objects=False)
    put(ccw_env, f"{ENCODED}/memory/{UUID_MEM}.jsonl", session(UUID_MEM))
    assert status.uncaptured_gap(cfg, projects(ccw_env)).sessions == 0


def test_doctor_overdue_does_not_count_it(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Anchored in payload time: the archived session is 9 days newer than the
    memory file, so an unfiltered walk reads the memory file as overdue."""
    configure(ccw_env, tmp_path / "archive", keep_objects=False)
    write_transcript(ccw_env, session(UUID_A, "2026-05-10T00:00:00.000Z"), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    cfg = configure(ccw_env, tmp_path / "archive", keep_objects=False)
    memory_transcript(ccw_env, "2026-05-01T00:00:00.000Z")
    report = doctor.diagnose(cfg, home=Path(ccw_env["HOME"]), source=projects(ccw_env))
    (overdue,) = [c for c in report.checks if c.name == "overdue"]
    assert overdue.ok, overdue.detail


def test_doctor_dispatch_does_not_count_it(ccw_env: dict[str, str], tmp_path: Path) -> None:
    cfg = configure(ccw_env, tmp_path / "archive", keep_objects=False)
    logs = Path(ccw_env["HOME"]) / ".claude" / "logs"
    logs.mkdir(parents=True)
    (logs / "ccw-hook.log").write_text("", encoding="utf-8")
    recent = (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    memory_transcript(ccw_env, recent)
    report = doctor.diagnose(cfg, home=Path(ccw_env["HOME"]), source=projects(ccw_env))
    (dispatch,) = [c for c in report.checks if c.name == "dispatch"]
    assert dispatch.ok, dispatch.detail


def test_a_project_whose_name_contains_memory_is_still_walked(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Edge case 5. Only a segment EXACTLY `memory`, directly under a project
    key, is skipped: not `memory-tools`, and not a project key that is itself
    the word `memory` (that is a project, one level too high)."""
    configure(ccw_env, tmp_path / "archive", keep_objects=False)
    put(ccw_env, f"-home-alice-projects-memory-tools/{UUID_A}.jsonl", session(UUID_A))
    put(ccw_env, f"memory/{UUID_B}.jsonl", session(UUID_B))
    result = run_ccw(["sweep"], ccw_env)
    assert result.code == 0, result.err
    assert uuids(ccw_env) == [UUID_A, UUID_B]


def test_the_predicate_is_exact() -> None:
    root = Path("/r")
    assert sweep.is_project_memory(root, root / "-proj" / "memory")
    assert not sweep.is_project_memory(root, root / "memory")
    assert not sweep.is_project_memory(root, root / "-proj" / "memory-tools")
    assert not sweep.is_project_memory(root, root / "-proj" / "x" / "memory")
    assert not sweep.is_project_memory(root, root / "-proj" / "Memory")


# The skip is anchored on the real source tree as well as the walk root, so a
# `--source` pointed elsewhere in it still skips a project's memory/ (found by
# the 2026-10-11 red-team review: depth was counted from the walk root only).


def test_a_sweep_pointed_at_one_project_dir_still_skips_its_memory(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    cfg = configure(ccw_env, tmp_path / "archive", keep_objects=False)
    memory_transcript(ccw_env)
    write_transcript(ccw_env, session(UUID_A), session_id=UUID_A)
    report = sweep.plan(cfg, projects(ccw_env) / ENCODED)
    # Sessions only: the sidecar planner reads a walk root at another level
    # differently (W-20261011-A01), which is not what this pins.
    sessions = [o.item for o in report.outcomes if o.item.endswith(".jsonl")]
    assert sessions == [f"{UUID_A}.jsonl"]


def test_the_cli_source_flag_on_one_project_dir_skips_it_too(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    configure(ccw_env, tmp_path / "archive", keep_objects=False)
    memory_transcript(ccw_env)
    write_transcript(ccw_env, session(UUID_A), session_id=UUID_A)
    result = run_ccw(["sweep", "--dry-run", "--source", str(projects(ccw_env) / ENCODED)], ccw_env)
    assert result.code == 0, result.err
    assert UUID_A in result.out
    assert UUID_MEM not in result.out, result.out


def test_a_sweep_pointed_at_dot_claude_still_skips_memory(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    cfg = configure(ccw_env, tmp_path / "archive", keep_objects=False)
    memory_transcript(ccw_env)
    write_transcript(ccw_env, session(UUID_A), session_id=UUID_A)
    report = sweep.plan(cfg, projects(ccw_env).parent)
    # Sessions only: the sidecar planner reads a walk root at another level
    # differently (W-20261011-A01), which is not what this pins.
    sessions = [o.item for o in report.outcomes if o.item.endswith(".jsonl")]
    assert sessions == [f"{UUID_A}.jsonl"]


# `ccw import` and `ccw migrate` walk an operator-named tree with their own
# walk (`migrate.walk_jsonl`). Pointed at a Claude projects tree they must skip
# memory/ the same way: the ruling says nothing under it is a session, for
# every consumer.


def test_import_does_not_read_a_project_memory_dir(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    cfg = configure(ccw_env, tmp_path / "archive", keep_objects=False)
    memory_transcript(ccw_env)
    write_transcript(ccw_env, session(UUID_A), session_id=UUID_A)
    report = import_tree.plan(cfg, projects(ccw_env))
    named = [o.item for o in report.outcomes if o.action != import_tree.SKIPPED_BRANCH_ACTION]
    assert named == [f"{UUID_A}.jsonl"]
    pruned = [o.item for o in report.outcomes if o.action == import_tree.SKIPPED_BRANCH_ACTION]
    assert pruned == [str(projects(ccw_env) / ENCODED / "memory")]


def test_migrate_does_not_capture_a_project_memory_dir(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    cfg = configure(ccw_env, tmp_path / "archive", keep_objects=True)
    memory_transcript(ccw_env)
    write_transcript(ccw_env, session(UUID_A), session_id=UUID_A)
    migrate.migrate(cfg, projects(ccw_env))
    assert uuids(ccw_env) == [UUID_A]


# ---------------------------------------------------------------------------
# THE FENCE: every tree walk in the product is named, with why it is safe
# ---------------------------------------------------------------------------

# Every function in src/ that recursively walks a directory, and why it cannot
# discover a transcript under `<project-key>/memory/`. A NEW walker fails the
# fence until it is added here, which forces the question to be asked. The
# census behind this list was taken 2026-09-30 (W-20260930-A59).
WALKERS: dict[tuple[str, str], str] = {
    ("sweep.py", "_walk_source"): "THE source-tree walk; prunes is_project_memory",
    ("migrate.py", "walk_jsonl"): "import/migrate's walk; prunes is_project_memory",
    ("relocate.py", "_scan_content"): "configured repo roots, rewriting paths, never transcripts",
    ("relocate.py", "_subdir_encodings"): "a repo's own directories, names only",
    ("sweep.py", "_orphan_object_paths"): "the vault's objects/, not the source tree",
    ("store.py", "verify_walk"): "the vault's objects/, not the source tree",
    ("capture.py", "_archive_subagents_of"): "one session's own subagents/ dir",
    ("archive.py", "_mirror_tree"): "one session's own companion dir, copied",
    ("archive.py", "_companion_files"): "one companion dir inside an archive folder",
    ("archive.py", "stray_temp_files"): "a folder inside the archive",
    ("archive.py", "_files"): "one session's own <uuid>/ dirs and stores",
}

_WALK_ATTRS = {"walk", "rglob"}
# A `glob` is recursive only when its pattern holds `**`, so only those count.
_GLOB_ATTRS = {"glob", "iglob"}


def _is_recursive_glob(node: ast.Call) -> bool:
    return any(
        isinstance(arg, ast.Constant) and isinstance(arg.value, str) and "**" in arg.value
        for arg in node.args
    )


def _walk_sites() -> set[tuple[str, str]]:
    sites: set[tuple[str, str]] = set()
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if "vendor" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(func):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and (
                        node.func.attr in _WALK_ATTRS
                        or (node.func.attr in _GLOB_ATTRS and _is_recursive_glob(node))
                    )
                    and not (isinstance(node.func.value, ast.Name) and node.func.value.id == "ast")
                ):
                    sites.add((path.name, func.name))
    return sites


def test_every_tree_walk_is_named_with_a_reason() -> None:
    sites = _walk_sites()
    assert sites, "the census found no walkers; the fence is not looking"
    unnamed = sorted(sites - set(WALKERS))
    assert not unnamed, f"walks nobody has checked against memory/: {unnamed}"


def test_the_named_walkers_all_still_exist() -> None:
    """A rename must not leave a stale entry that silently exempts nothing."""
    stale = sorted(set(WALKERS) - _walk_sites())
    assert not stale, f"named walkers that no longer walk: {stale}"


def test_every_consumer_of_the_source_tree_goes_through_one_walk() -> None:
    """status, doctor and reconcile read transcripts only via
    `sweep.source_transcripts`, which is `_walk_source`: no second walk exists
    for the predicate to be missing from."""
    for name in ("status.py", "doctor.py", "reconcile.py"):
        text = (SRC_ROOT / name).read_text(encoding="utf-8")
        assert "sweep.source_transcripts(" in text, name
        assert not {s for s in _walk_sites() if s[0] == name}, name

