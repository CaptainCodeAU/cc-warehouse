"""Oracle tests: no catalog row may name bytes that nothing holds (W-20260930-A59).

THE INCIDENT, 2026-09-30. The 12:30 `ccw sweep` stored 8 catalog rows with no
`session_uuid`. Their sources were `claude -p --output-format stream-json`
captures kept in a pj record folder, `<project-key>/memory/WORK/...`, which is
not a transcript. With `keep_objects = false` there is no vault; the capture
path wrote each payload to `<stamp>_session/session.jsonl`, and the build's
reader looks for `<stamp>_session-<short>/session-<short>.jsonl`. So every
sweep-triggered build then failed all 8 with "no bytes ... in the vault".

Three guards, all ruled by Gavin the same day, each proved here:

(a) BUILD: a row with no session_uuid whose bytes nothing can serve is skipped
    as not a session, exactly as `ccw archive` already does. A row WITH a uuid
    whose bytes are gone still fails.
(b) CAPTURE: while `keep_objects` is false, a payload that names no session is
    never cataloged, decided from the payload's content, never the file stem.
(c) DISCOVERY: `<project-key>/memory/` under the source tree is pj's record
    folder and is never walked for transcripts, by any consumer of the walk.

Contract: DESIGN R5/F7 (conservative branch), R9 (one walk, one predicate),
R10 (a batch names its failures), F4 (identity from content, never a name),
ruling (a) as narrowed by ticket 21 (`archive.is_session`), ticket 27.8
(`keep_objects = true` keeps the vault as a home for every payload).
"""

import ast
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from cc_warehouse import archive, build, capture, config, doctor, status, sweep
from conftest import (
    SRC_ROOT,
    entry,
    hook_payload,
    jsonl,
    mark_archive,
    run_ccw,
    session_count,
    subagent_session,
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


def historical_no_uuid_row(env: dict[str, str], tmp_path: Path) -> tuple[Path, config.Config]:
    """Reproduce today's 8 rows by the path that made them.

    With the vault ON, guard (b) does not apply (ticket 27.8: the vault is a
    home), so capture catalogs the no-uuid payload exactly as 0.1.4 did with
    the vault off, writing `<stamp>_session/session.jsonl` into the archive.
    Capture only, no build: the real 8 were never built, and a vault-on build
    here would write a second folder under the reader's own name and hide the
    defect. Then the vault is retired the way ticket 27.4 retired the real
    one, and the config flipped. What is left is a catalog row whose bytes the
    reader cannot find, because `<stamp>_session/` is not the name
    `archive.read_payload` computes (`<stamp>_session-<short>/`).
    """
    target = tmp_path / "archive"
    cfg = configure(env, target, keep_objects=True)
    path = put(env, f"{ENCODED}/armA.jsonl", stream_json())
    assert capture.capture_transcript(cfg, path, session_id=None, cwd=None).action == "stored"
    assert uuids(env) == [None], "fixture made no no-uuid row; the test would prove nothing"
    assert [p.name for p in target.rglob("session.jsonl")] == ["session.jsonl"]
    shutil.rmtree(warehouse_root(env) / "objects")
    return target, configure(env, target, keep_objects=False)


# ---------------------------------------------------------------------------
# (a) BUILD skips a no-uuid row with no bytes; a uuid row with none still FAILS
# ---------------------------------------------------------------------------


def test_build_skips_a_no_uuid_row_that_nothing_can_serve(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The 12:30 incident, end to end: `ccw build` exits 0 and names no failure."""
    historical_no_uuid_row(ccw_env, tmp_path)
    result = run_ccw(["build"], ccw_env)
    assert result.code == 0, result.err
    assert "build failed" not in result.err
    assert "1 not a session" in result.out, result.out


def test_build_reports_the_skip_with_its_own_action(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    _target, cfg = historical_no_uuid_row(ccw_env, tmp_path)
    report = build.build(cfg)
    assert report.failures == ()
    assert [o.action for o in report.outcomes] == [build.SKIPPED_NOT_A_SESSION]


def test_a_sweep_triggered_build_does_not_fail_it_either(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The path that raised on 2026-09-30: `cli._run_sweep` -> `build.build`.
    A real session arriving makes the sweep run its post-capture build."""
    historical_no_uuid_row(ccw_env, tmp_path)
    write_transcript(ccw_env, session(UUID_A), session_id=UUID_A)
    result = run_ccw(["sweep"], ccw_env)
    assert result.code == 0, result.err
    assert "projection failed" not in result.err
    assert "0 failed" in result.out, result.out


def test_a_reindexed_no_uuid_row_is_skipped_too(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`reindex` catalogs every readable folder, uuid or not (reindex.py
    `_pending_sessions`), so it re-creates these rows from `<stamp>_session/`.
    The guard has to hold for a row made that way as well."""
    target, _cfg = historical_no_uuid_row(ccw_env, tmp_path)
    (warehouse_root(ccw_env) / "catalog.sqlite").unlink()
    result = run_ccw(["reindex", "--from", str(target)], ccw_env)
    assert result.code == 0, result.err
    assert uuids(ccw_env) == [None], "reindex did not re-create the row"
    result = run_ccw(["build"], ccw_env)
    assert result.code == 0, result.err
    assert "build failed" not in result.err


def test_a_row_WITH_a_uuid_and_no_bytes_anywhere_still_fails(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Edge case 6. Guard (a) is for rows that name no session; a real session
    that nothing can serve is a loss and must stay loud (R5/F7)."""
    target = tmp_path / "archive"
    configure(ccw_env, target, keep_objects=True)
    write_transcript(ccw_env, session(UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    shutil.rmtree(warehouse_root(ccw_env) / "objects")
    for jsonl_file in target.rglob(f"{UUID_A}.jsonl"):
        jsonl_file.unlink()
    configure(ccw_env, target, keep_objects=False)
    result = run_ccw(["build", "--rebuild"], ccw_env)
    assert result.code == 1, result.out
    assert "build failed" in result.err


# ---------------------------------------------------------------------------
# (b) CAPTURE: vault off, no session named in the payload -> never cataloged
# ---------------------------------------------------------------------------


def test_with_the_vault_off_a_payload_naming_no_session_is_not_cataloged(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, target, keep_objects=False)
    put(ccw_env, f"{ENCODED}/armA.jsonl", stream_json())
    result = run_ccw(["sweep"], ccw_env)
    assert result.code == 0, result.err
    assert "failed:" not in result.err
    assert session_count(ccw_env) == 0
    assert not list(target.rglob("*_session")), "an archive folder was written for it"


def test_the_refusal_is_reported_with_the_not_a_session_action(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    cfg = configure(ccw_env, tmp_path / "archive", keep_objects=False)
    path = put(ccw_env, f"{ENCODED}/armA.jsonl", stream_json())
    result = capture.capture_transcript(cfg, path, session_id=None, cwd=None)
    assert result.action == capture.NOT_A_SESSION
    assert result.short == ""


def test_the_hook_reports_it_and_spawns_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A hook-supplied `session_id` does not give the bytes a home: the archive
    writer names the folder from the PAYLOAD, so the reader could never find
    it under the hook's id either. The payload decides."""
    configure(ccw_env, tmp_path / "archive", keep_objects=False)
    path = put(ccw_env, f"{ENCODED}/{UUID_A}.jsonl", stream_json())
    result = run_ccw(["hook"], ccw_env, stdin=hook_payload(path, cwd=CWD, session_id=UUID_A))
    assert result.code == 0, result.err
    assert result.out.strip().startswith("skipped_not_a_session"), result.out
    assert session_count(ccw_env) == 0


def test_a_real_transcript_with_a_non_uuid_stem_is_still_captured(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Edge case 1: `<uuid>.orphaned-<n>-<hash>.jsonl` (ticket 38). The stem is
    not a uuid; the payload's `sessionId` is what counts (F4)."""
    configure(ccw_env, tmp_path / "archive", keep_objects=False)
    put(ccw_env, f"{ENCODED}/{UUID_A}.orphaned-1-abcdef12.jsonl", session(UUID_A))
    result = run_ccw(["sweep"], ccw_env)
    assert result.code == 0, result.err
    assert uuids(ccw_env) == [UUID_A]


def test_with_the_vault_on_nothing_changes(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Edge case 3: `keep_objects = true` (the shipped default) keeps the vault
    as the home for a no-uuid payload (ticket 27.8 ruling: keep both)."""
    configure(ccw_env, tmp_path / "archive", keep_objects=True)
    put(ccw_env, f"{ENCODED}/armA.jsonl", stream_json())
    result = run_ccw(["sweep"], ccw_env)
    assert result.code == 0, result.err
    assert uuids(ccw_env) == [None]


def test_sub_agents_are_archived_exactly_as_before(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Edge case 2. Both sub-agent layouts: `subagents/agent-*.jsonl` and
    `subagents/workflows/wf_<id>/agent-*.jsonl`. Their stems are not uuids and
    they never reach `capture_transcript`; each lands in its parent's folder."""
    target = tmp_path / "archive"
    configure(ccw_env, target, keep_objects=False)
    write_transcript(ccw_env, session(UUID_A), session_id=UUID_A)
    put(ccw_env, f"{ENCODED}/{UUID_A}/subagents/agent-a1.jsonl",
        subagent_session(agent_id="a1", parent_uuid=UUID_A))
    put(ccw_env, f"{ENCODED}/{UUID_A}/subagents/workflows/wf_1/agent-a2.jsonl",
        subagent_session(agent_id="a2", parent_uuid=UUID_A))
    result = run_ccw(["sweep"], ccw_env)
    assert result.code == 0, result.err
    assert uuids(ccw_env) == [UUID_A]
    (folder,) = target.rglob(f"*_{UUID_A}")
    agents = sorted(p.name for p in (folder / "subagents").iterdir())
    assert len(agents) == 2, agents


def test_imported_journals_are_untouched(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Edge case 4: `ccw import` rescues a payload that names no session into
    `_not-sessions/imported/` without ever cataloging it, and a build after it
    has nothing to fail on."""
    target = tmp_path / "archive"
    configure(ccw_env, target, keep_objects=False)
    source = tmp_path / "legacy"
    source.mkdir()
    journal = jsonl({"type": "workflow", "step": 1, "timestamp": "2026-05-01T00:00:00Z"})
    (source / "journal-1.jsonl").write_bytes(journal)
    result = run_ccw(["import", "--from", str(source)], ccw_env)
    assert result.code == 0, result.err
    assert session_count(ccw_env) == 0
    rescued = list((target / archive.NOT_SESSIONS_LABEL).rglob("*.jsonl"))
    assert [p.read_bytes() for p in rescued] == [journal]
    assert run_ccw(["build"], ccw_env).code == 0


# ---------------------------------------------------------------------------
# (c) DISCOVERY: `<project-key>/memory/` is never walked for transcripts
# ---------------------------------------------------------------------------


def memory_transcript(env: dict[str, str], ts: str = "2026-05-01T00:00:00.000Z") -> Path:
    """A file that LOOKS like a real transcript, `sessionId` and all, so guard
    (b) cannot be what keeps it out: only the discovery guard can."""
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


# ---------------------------------------------------------------------------
# THE FENCE: every tree walk in the product is named, with why it is safe
# ---------------------------------------------------------------------------

# Every function in src/ that recursively walks a directory, and why it cannot
# discover a transcript under `<project-key>/memory/`. A NEW walker fails the
# fence until it is added here, which forces the question to be asked. The
# census behind this list was taken 2026-09-30 (W-20260930-A59).
WALKERS: dict[tuple[str, str], str] = {
    ("sweep.py", "_walk_source"): "THE source-tree walk; prunes is_project_memory",
    ("migrate.py", "walk_jsonl"): "an operator-named --from tree, classified by content",
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
                    and node.func.attr in _WALK_ATTRS
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

