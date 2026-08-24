"""Oracle tests: the archive folder, migration and integrity check (ticket 19).

Slices 19c, 19d and 19e. The folder NAME is owned by test_archive_naming.py;
this file owns what goes INSIDE one, how the migration fills the tree, and what
`ccw verify` becomes once the vault is gone.

Contract: DESIGN 15 entry 2026-08-02 in full; R4 as amended the same day (the
rebuild module may delete only what it GENERATED; the session JSONL is never
deletable and neither is a folder containing one); R1 as amended (size answers
"which of two differing payloads is larger", never "are these the same bytes");
R2 (atomic writes), R5/F7 (conservative branch), R10 (named-item batch report),
F6 (loss is never silent), F9 (sources are read-only).
"""

import json
from pathlib import Path

from cc_warehouse import archive, catalog, store
from cc_warehouse.render import RenderOptions
from conftest import DEFAULT_UUID, basic_session, entry, jsonl, matrix_session, tree_snapshot

ZONE = "Australia/Melbourne"
OPTS = RenderOptions()
LABEL = "widget"

UUID_A = "d1111111-2222-3333-4444-555555555551"
UUID_B = "d1111111-2222-3333-4444-555555555552"


def session_with(
    uuid: str,
    prompt: str = "Do the thing",
    ts: str = "2026-05-07T03:47:45.000Z",
) -> bytes:
    return jsonl(
        entry("user", prompt, ts, session_id=uuid, gitBranch="main", version="2.0.0"),
        entry(
            "assistant",
            [{"type": "text", "text": "Done."}],
            "2026-05-07T03:47:50.000Z",
            session_id=uuid,
        ),
    )


def machinery_only(uuid: str) -> bytes:
    """A session with a sessionId but no conversation: 139 real cases. Archived,
    but no markdown or HTML (ruling (a), 2026-08-02)."""
    return jsonl(
        {"type": "permission-mode", "permissionMode": "default", "sessionId": uuid},
        {"type": "mode", "mode": "normal", "sessionId": uuid},
    )


# ---------------------------------------------------------------------------
# 19c: what one folder contains
# ---------------------------------------------------------------------------


def test_the_folder_holds_the_jsonl_beside_its_five_projections(tmp_path: Path) -> None:
    data = session_with(UUID_A)
    result = archive.write_session_folder(tmp_path, LABEL, data, OPTS, ZONE)
    names = {p.name for p in result.directory.iterdir()}
    assert names == {f"{UUID_A}.jsonl", *archive.GENERATED_NAMES}
    assert result.directory.parent.name == LABEL
    assert result.wrote_projections


def test_the_archived_jsonl_is_byte_identical_to_the_source(tmp_path: Path) -> None:
    """The whole point of the redesign: the raw session is a REAL file in the
    folder, not a re-serialization of it."""
    data = session_with(UUID_A)
    result = archive.write_session_folder(tmp_path, LABEL, data, OPTS, ZONE)
    assert result.jsonl.read_bytes() == data
    assert store.sha256_hex(result.jsonl.read_bytes()) == store.sha256_hex(data)


def test_the_manifest_source_hash_matches_the_archived_jsonl(tmp_path: Path) -> None:
    data = session_with(UUID_A)
    result = archive.write_session_folder(tmp_path, LABEL, data, OPTS, ZONE)
    manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_hash"] == store.sha256_hex(data)


def test_a_conversation_free_session_is_archived_without_projections(tmp_path: Path) -> None:
    """139 real cases. The JSONL is kept; no markdown or HTML is generated. The
    single "skip anything with no conversation" rule was MEASURED before
    adoption and would have discarded all 139, which is why emptiness and
    is-this-a-session are two questions here, not one."""
    result = archive.write_session_folder(tmp_path, LABEL, machinery_only(UUID_A), OPTS, ZONE)
    assert result.jsonl.exists()
    assert not result.wrote_projections
    names = {p.name for p in result.directory.iterdir()}
    assert names == {f"{UUID_A}.jsonl"}


def test_a_payload_with_no_session_id_is_not_a_session() -> None:
    """Ruling (a): the test that skips EXACTLY the 7 workflow journals across all
    14,066 non-agent source files, and nothing else."""
    assert archive.is_session(session_with(UUID_A))
    assert archive.is_session(machinery_only(UUID_A))
    assert not archive.is_session(b'{"type":"log","message":"no session id here"}\n')


# ---------------------------------------------------------------------------
# 19c: re-capture semantics (versioning DROPPED, replace in place)
# ---------------------------------------------------------------------------


def test_a_larger_payload_replaces_in_place_and_the_folder_name_holds(
    tmp_path: Path,
) -> None:
    """Start-keyed names are IMMUTABLE, so a longer session lands in the folder
    it already occupies rather than sprouting a second one."""
    first = session_with(UUID_A)
    grown = first + jsonl(
        entry(
            "assistant",
            [{"type": "text", "text": "And one more thing."}],
            "2026-05-07T04:00:00.000Z",
            session_id=UUID_A,
        )
    )
    one = archive.write_session_folder(tmp_path, LABEL, first, OPTS, ZONE)
    two = archive.write_session_folder(tmp_path, LABEL, grown, OPTS, ZONE)
    assert two.directory == one.directory
    assert two.replaced
    assert two.jsonl.read_bytes() == grown


def test_a_smaller_payload_is_refused_and_the_refusal_is_recorded(tmp_path: Path) -> None:
    """F6: never silent. A truncated re-capture must not be able to shrink the
    archive without saying so in the manifest."""
    full = session_with(UUID_A) + jsonl(
        entry("assistant", [{"type": "text", "text": "More."}], "2026-05-07T04:00:00.000Z",
              session_id=UUID_A)
    )
    archive.write_session_folder(tmp_path, LABEL, full, OPTS, ZONE)
    result = archive.write_session_folder(tmp_path, LABEL, session_with(UUID_A), OPTS, ZONE)
    assert result.refused_smaller
    assert result.jsonl.read_bytes() == full
    manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
    assert "replace_refused" in manifest
    assert manifest["replace_refused"]["offered_bytes"] < manifest["replace_refused"][
        "archived_bytes"
    ]


def test_an_equal_size_content_mismatch_is_refused_and_recorded(tmp_path: Path) -> None:
    """Ticket 30's flagged case, closed 2026-08-23: same SIZE as the archived
    payload is not the same thing as same BYTES (F1). A distinct field from
    `refused_smaller` (`refused_equal_size`), and a distinct manifest reason,
    because F6 says the reason is never allowed to go silent OR be misreported."""
    archived = session_with(UUID_A, prompt="Do the thing")
    offered = session_with(UUID_A, prompt="Do the OTHER")
    assert len(offered) == len(archived), "fixture precondition: equal length"
    assert offered != archived, "fixture precondition: different content"

    archive.write_session_folder(tmp_path, LABEL, archived, OPTS, ZONE)
    result = archive.write_session_folder(tmp_path, LABEL, offered, OPTS, ZONE)

    assert result.refused_equal_size
    assert not result.refused_smaller
    assert result.jsonl.read_bytes() == archived
    manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
    assert "replace_refused" in manifest
    assert manifest["replace_refused"]["reason"] != (
        "a re-captured payload was smaller than the archived one"
    ), "an equal-size mismatch must not be reported as the smaller-payload case"
    assert manifest["replace_refused"]["archived_bytes"] == len(archived)
    assert manifest["replace_refused"]["offered_bytes"] == len(offered)


def test_re_writing_an_identical_payload_leaves_the_jsonl_untouched(tmp_path: Path) -> None:
    """Idempotence: the migration has to be safe to run twice, and a rewrite
    that churns mtimes for nothing would make a backup tool think every session
    changed."""
    data = session_with(UUID_A)
    first = archive.write_session_folder(tmp_path, LABEL, data, OPTS, ZONE)
    before = first.jsonl.stat().st_mtime_ns
    second = archive.write_session_folder(tmp_path, LABEL, data, OPTS, ZONE)
    assert second.jsonl.stat().st_mtime_ns == before
    assert not second.replaced
    assert not second.refused_smaller
    assert not second.refused_equal_size


# ---------------------------------------------------------------------------
# R4 AMENDED: the load-bearing test of the whole redesign
# ---------------------------------------------------------------------------


def test_the_archive_module_has_no_deletion_primitive_at_all() -> None:
    """R4 as amended 2026-08-02, the rule the entry itself calls load-bearing:
    once the JSONL lives inside the archive, the module that maintains that tree
    must not be able to remove it. Enforced structurally, by AST, rather than by
    remembering: without this, maintenance code can destroy the only copy."""
    import ast

    from conftest import SRC_ROOT

    tree = ast.parse((SRC_ROOT / "archive.py").read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {
                "unlink", "rmdir", "rmtree", "remove", "removedirs",
            }:
                offenders.append(f"archive.py:{node.lineno} .{func.attr}")
    assert not offenders, f"deletion primitives in the archive module (R4): {offenders}"


def test_rewriting_a_folder_never_removes_the_jsonl(tmp_path: Path) -> None:
    """The behavioural half of the rule above, because a static fence proves the
    call is absent and this proves the outcome."""
    data = session_with(UUID_A)
    result = archive.write_session_folder(tmp_path, LABEL, data, OPTS, ZONE)
    for _ in range(3):
        archive.write_session_folder(tmp_path, LABEL, data, OPTS, ZONE)
    assert result.jsonl.exists()
    assert result.jsonl.read_bytes() == data


# ---------------------------------------------------------------------------
# 19d: the migration
# ---------------------------------------------------------------------------


def captured(env: dict[str, str], *payloads: bytes) -> None:
    from conftest import hook_payload, run_ccw, write_transcript

    for i, data in enumerate(payloads):
        uuid = f"e1111111-2222-3333-4444-55555555555{i}"
        transcript = write_transcript(env, data, session_id=uuid, name=f"{uuid}.jsonl")
        result = run_ccw(["hook"], env, stdin=hook_payload(transcript, cwd=None, session_id=uuid))
        assert result.code == 0, result.err


def test_migration_builds_the_tree_from_objects_and_touches_nothing_else(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Build BESIDE, never in place. The worst outcome of a failure at any point
    must be a partly-built new tree next to a completely intact old one."""
    from conftest import warehouse_root

    captured(ccw_env, session_with(UUID_A), session_with(UUID_B, prompt="Second thing"))
    old_root = warehouse_root(ccw_env)
    before = tree_snapshot(old_root)

    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    report = archive.migrate(old_root, archive_root, OPTS, ZONE)

    assert report.written == 2, report.summary()
    assert not report.failed, report.failed
    assert tree_snapshot(old_root) == before, "the migration modified the old warehouse"


def test_migration_is_idempotent(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Same name from the same payload, so a second pass finds every session
    already where it belongs instead of building a shadow tree."""
    from conftest import warehouse_root

    captured(ccw_env, session_with(UUID_A))
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    archive.migrate(warehouse_root(ccw_env), archive_root, OPTS, ZONE)
    first = tree_snapshot(archive_root)
    archive.migrate(warehouse_root(ccw_env), archive_root, OPTS, ZONE)
    assert tree_snapshot(archive_root) == first


def test_migration_reports_a_failed_item_by_name_and_carries_on(tmp_path: Path) -> None:
    """R10, the rule that made the 2026-08-01 failure diagnosable: name the item
    and finish the batch, never abort on the first."""
    report = archive.MigrationReport()
    report.failed.append(("abc123", "UnicodeEncodeError: surrogates not allowed"))
    report.written = 9
    assert "abc123" in report.failed[0][0]
    assert "1 failed" in report.summary()
    assert "9 folders written" in report.summary()


def test_migration_recovers_a_stale_folder_when_the_vault_is_gone(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The vault (`objects/`) can be retired entirely once `keep_objects=false`
    (ticket 27.4). A session that already has a real archive folder must not need
    the vault to REFRESH that folder when it goes stale (a renderer-version bump,
    say) - its own JSONL, already safely on disk, is the payload. Only a catalog
    row with no archive folder at all genuinely has nothing left to recover.
    Real case, 2026-08-24: the weekly `ccw archive --to` job failed 591
    already-archived sessions this way once `objects/` was gone."""
    from conftest import warehouse_root

    captured(ccw_env, session_with(UUID_A))
    warehouse = warehouse_root(ccw_env)
    archive_root = tmp_path / "archive"
    archive_root.mkdir()

    first = archive.migrate(warehouse, archive_root, OPTS, ZONE)
    assert first.written == 1, first.summary()
    folder = next(archive_root.glob(f"*/*_{UUID_A}"))

    # Go stale (folder_is_current reads manifest.json; ANY doubt returns
    # False, so a missing manifest is enough) and lose the vault.
    (folder / "manifest.json").unlink()
    for obj in (warehouse / "objects").rglob("*.jsonl"):
        obj.unlink()

    report = archive.migrate(warehouse, archive_root, OPTS, ZONE)

    assert not report.failed, report.failed
    assert (folder / "manifest.json").exists()


def test_migration_never_permanently_fails_a_row_with_no_session_identity(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Real shape found 2026-08-24: 8 catalog rows on the operator's own machine
    (the workflow-journal vault objects `is_session`'s own docstring already
    names as permanently excluded - no `sessionId`, so `session_uuid` is NULL)
    have no vault blob left (`objects/` retired, ticket 27.4) and never had an
    archive folder (they predate archive-first, or were catalog-only imports).
    Reporting these as `failed` forever would make `ccw archive --to`'s exit
    code permanently non-zero regardless of whether anything is actually wrong
    - exactly the chronic-false-alarm shape ticket 24.7 already learned to
    avoid once. A row with no session identity at all was never going to
    become a real session folder either way; it belongs in the existing
    `skipped_not_a_session` bucket, not `failed`."""
    from conftest import warehouse_root

    warehouse = warehouse_root(ccw_env)
    conn = catalog.open_catalog(warehouse)
    try:
        cursor = conn.execute(
            "INSERT INTO project (label, created_at) VALUES (?, ?)",
            ("_not-sessions", "2026-08-01T00:00:00Z"),
        )
        assert cursor.lastrowid is not None
        project_id = cursor.lastrowid
        meta = catalog.SessionMeta(
            sha256="f" * 64,
            source_kind="claude_code",
            session_uuid=None,
            slug=None,
            git_branch=None,
            cwd=None,
            first_ts=None,
            last_ts=None,
            size_bytes=123,
            line_count=1,
            skipped_lines=0,
            summary="",
            hidden=False,
            resolution_source="payload_cwd",
        )
        catalog.add_session(conn, meta, project_id, "2026-08-01T00:00:00Z")
    finally:
        conn.close()
    # No vault object was ever written for this hash, and no archive folder
    # exists either - exactly the real, permanent state on disk.
    archive_root = tmp_path / "archive"
    archive_root.mkdir()

    report = archive.migrate(warehouse, archive_root, OPTS, ZONE)

    assert not report.failed, report.failed
    assert report.skipped_not_a_session == ["f" * 64]


# ---------------------------------------------------------------------------
# 19e: verify becomes archive integrity
# ---------------------------------------------------------------------------


def test_verify_passes_a_freshly_written_folder(tmp_path: Path) -> None:
    result = archive.write_session_folder(tmp_path, LABEL, session_with(UUID_A), OPTS, ZONE)
    assert archive.verify_folder(result.directory, ZONE) == []


def test_verify_fails_a_folder_whose_jsonl_no_longer_matches_its_manifest(
    tmp_path: Path,
) -> None:
    result = archive.write_session_folder(tmp_path, LABEL, session_with(UUID_A), OPTS, ZONE)
    store.atomic_write(result.jsonl, session_with(UUID_A, prompt="TAMPERED"))
    problems = [p.problem for p in archive.verify_folder(result.directory, ZONE)]
    assert any("source_hash" in p for p in problems), problems


def test_verify_fails_a_folder_missing_any_generated_file(tmp_path: Path) -> None:
    result = archive.write_session_folder(tmp_path, LABEL, session_with(UUID_A), OPTS, ZONE)
    (result.directory / "conversation.html").rename(tmp_path / "moved-away.html")
    problems = [p.problem for p in archive.verify_folder(result.directory, ZONE)]
    assert any("conversation.html" in p for p in problems), problems


def test_verify_fails_a_folder_whose_name_disagrees_with_its_payload(
    tmp_path: Path,
) -> None:
    """The check that catches a hand-renamed folder, which is the one way an
    archive can lie about when something happened."""
    result = archive.write_session_folder(tmp_path, LABEL, session_with(UUID_A), OPTS, ZONE)
    wrong = result.directory.parent / f"19990101-000000+1000_{UUID_A}"
    result.directory.rename(wrong)
    problems = [p.problem for p in archive.verify_folder(wrong, ZONE)]
    assert any("disagrees" in p for p in problems), problems


def test_verify_reports_a_folder_with_no_jsonl_at_all(tmp_path: Path) -> None:
    empty = tmp_path / LABEL / "20260507-134745+1000_nothing"
    empty.mkdir(parents=True)
    problems = [p.problem for p in archive.verify_folder(empty, ZONE)]
    assert problems == ["no session JSONL in the folder"]


def test_walk_folders_finds_every_session_and_skips_reserved_names(
    tmp_path: Path,
) -> None:
    archive.write_session_folder(tmp_path, LABEL, session_with(UUID_A), OPTS, ZONE)
    archive.write_session_folder(tmp_path, "other", session_with(UUID_B), OPTS, ZONE)
    (tmp_path / "locks").mkdir()
    (tmp_path / "catalog.sqlite").write_bytes(b"not a project")
    found = list(archive.walk_folders(tmp_path))
    assert len(found) == 2
    assert {d.parent.name for d in found} == {LABEL, "other"}


# ---------------------------------------------------------------------------
# The config key that pins the zone
# ---------------------------------------------------------------------------


def test_the_zone_comes_from_config_and_defaults_to_utc(tmp_path: Path) -> None:
    from cc_warehouse.config import load_config

    config = load_config(xdg_config_home=tmp_path / "xdg", env={"HOME": str(tmp_path)})
    assert config.archive_timezone == "UTC"


def test_a_configured_zone_is_honoured(tmp_path: Path) -> None:
    from cc_warehouse.config import load_config

    cfg = tmp_path / "xdg" / "cc-warehouse"
    cfg.mkdir(parents=True)
    (cfg / "config.toml").write_text(f'archive_timezone = "{ZONE}"\n')
    config = load_config(xdg_config_home=tmp_path / "xdg", env={"HOME": str(tmp_path)})
    assert config.archive_timezone == ZONE


def test_an_unknown_zone_is_recorded_and_the_default_kept(tmp_path: Path) -> None:
    """R5: load_config runs inside `ccw hook`, so a typo in a config file must
    never be able to stop a session being stored."""
    from cc_warehouse.config import load_config

    cfg = tmp_path / "xdg" / "cc-warehouse"
    cfg.mkdir(parents=True)
    (cfg / "config.toml").write_text('archive_timezone = "Mars/Olympus_Mons"\n')
    config = load_config(xdg_config_home=tmp_path / "xdg", env={"HOME": str(tmp_path)})
    assert config.archive_timezone == "UTC"
    assert any("archive_timezone" in p for p in config.config_errors)


# ---------------------------------------------------------------------------
# Sources stay read-only (F9)
# ---------------------------------------------------------------------------


def test_writing_a_folder_never_touches_the_claude_projects_source(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    from conftest import claude_projects

    captured(ccw_env, matrix_session(), basic_session(session_id=DEFAULT_UUID))
    before = tree_snapshot(claude_projects(ccw_env))
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    from conftest import warehouse_root

    archive.migrate(warehouse_root(ccw_env), archive_root, OPTS, ZONE)
    assert tree_snapshot(claude_projects(ccw_env)) == before
