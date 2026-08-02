"""Oracle tests: the archive holds the payload BEFORE the render child (19k).

This is the slice that makes `objects/` retirable, and the reason it is needed
is durability rather than tidiness.

Until now the archive got its JSONL from the hook's DETACHED render child. That
is fine while `objects/` exists, because the payload is already safe in the
content-addressed store by the time the hook returns. Retire `objects/` under
that arrangement and a child that never runs - a crash, a kill, a full disk, an
OS that declined the spawn - means the session existed only in `~/.claude` and
the warehouse has nothing. The store is what makes the current design safe, so
anything replacing it has to take on the same job.

So the hook now writes the archive's JSONL SYNCHRONOUSLY, before it returns, and
the render child fills in the five generated files afterwards exactly as it fills
in a projection today. Same shape as the existing design: durable write first,
rendering second.

Contract: DESIGN section 4 (capture; the child is a renderer, never the thing
that makes a session safe); DESIGN 15 2026-08-02 (archive-first); R2 (atomic
writes); R4 as amended (the JSONL is never deletable); F9 (sources read-only).
"""

from pathlib import Path

from cc_warehouse import archive
from conftest import (
    entry,
    hook_payload,
    jsonl,
    run_ccw,
    session_count,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "f9111111-2222-3333-4444-555555555551"
UUID_B = "f9111111-2222-3333-4444-555555555552"
CWD = "/home/alice/projects/widget"


def session(uuid: str, tail: bytes = b"") -> bytes:
    return (
        jsonl(
            entry(
                "user",
                "Do the thing",
                "2026-05-07T03:47:45.000Z",
                session_id=uuid,
                cwd=CWD,
                gitBranch="main",
            ),
            entry(
                "assistant",
                [{"type": "text", "text": "Done."}],
                "2026-05-07T03:47:50.000Z",
                session_id=uuid,
                cwd=CWD,
            ),
        )
        + tail
    )


def configure(env: dict[str, str], archive_root: Path | None) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [f'root = "{warehouse_root(env)}"', f'archive_timezone = "{ZONE}"']
    if archive_root is not None:
        lines.append(f'archive_root = "{archive_root}"')
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def hook_only(env: dict[str, str], uuid: str, data: bytes) -> None:
    """Run ONLY the hook. No render child, which is the whole point: everything
    asserted after this call is what survives if the child never runs."""
    transcript = write_transcript(env, data, session_id=uuid, name=f"{uuid}.jsonl")
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, cwd=CWD, session_id=uuid))
    assert result.code == 0, result.err


def sole_jsonl(root: Path) -> Path:
    found = sorted(root.rglob("*.jsonl"))
    assert len(found) == 1, found
    return found[0]


# ---------------------------------------------------------------------------
# The payload is safe the moment the hook returns
# ---------------------------------------------------------------------------


def test_the_hook_writes_the_archive_jsonl_without_the_render_child(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE slice. If this needs the child, `objects/` can never be retired,
    because a child that never runs would mean a session with no home."""
    target = tmp_path / "archive"
    configure(ccw_env, target)
    data = session(UUID_A)
    hook_only(ccw_env, UUID_A, data)
    assert sole_jsonl(target).read_bytes() == data


def test_the_folder_is_the_one_the_verb_would_have_chosen(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R9 again, one level down. If the hook and `ccw archive` disagreed on the
    folder, the tree would silently double instead of failing."""
    target = tmp_path / "archive"
    configure(ccw_env, target)
    hook_only(ccw_env, UUID_A, session(UUID_A))

    from cc_warehouse.build import archive_folder_name

    folder = sole_jsonl(target).parent
    assert folder.name == archive_folder_name("2026-05-07T03:47:45.000Z", UUID_A, ZONE)


def test_the_render_child_then_fills_in_the_five_files(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Same shape as today's design: durable write first, rendering second."""
    target = tmp_path / "archive"
    configure(ccw_env, target)
    hook_only(ccw_env, UUID_A, session(UUID_A))
    folder = sole_jsonl(target).parent
    assert not (folder / "transcript.md").exists(), "the hook rendered, it should not"

    from conftest import catalog_rows

    rows = catalog_rows(ccw_env, "SELECT short FROM session")
    short = str(tuple(rows[0])[0])  # type: ignore[index]
    assert run_ccw(["render", "--session", f"s:{short}"], ccw_env).code == 0
    for name in archive.GENERATED_NAMES:
        assert (folder / name).is_file(), name


def test_a_session_captured_twice_keeps_one_folder(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, target)
    hook_only(ccw_env, UUID_A, session(UUID_A))
    hook_only(ccw_env, UUID_A, session(UUID_A))
    assert len(list(target.rglob("*.jsonl"))) == 1


def test_a_grown_session_replaces_the_archived_payload(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Start-keyed folder names are immutable, so a continued session lands in
    the folder it already occupies and the LARGER payload wins."""
    target = tmp_path / "archive"
    configure(ccw_env, target)
    hook_only(ccw_env, UUID_A, session(UUID_A))
    grown = session(
        UUID_A,
        tail=jsonl(
            entry(
                "assistant",
                [{"type": "text", "text": "GROWNMARKER"}],
                "2026-05-07T04:00:00.000Z",
                session_id=UUID_A,
                cwd=CWD,
            )
        ),
    )
    hook_only(ccw_env, UUID_A, grown)
    assert sole_jsonl(target).read_bytes() == grown


def test_two_sessions_get_two_folders(ccw_env: dict[str, str], tmp_path: Path) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, target)
    hook_only(ccw_env, UUID_A, session(UUID_A))
    hook_only(ccw_env, UUID_B, session(UUID_B))
    assert len(list(target.rglob("*.jsonl"))) == 2


# ---------------------------------------------------------------------------
# It never costs a capture, and it never touches the source
# ---------------------------------------------------------------------------


def test_an_unwritable_archive_still_stores_the_session(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The hook's job is to make the session safe. While `objects/` still exists
    it remains the fallback, so an archive problem must not fail the capture.
    When `objects/` is eventually retired this becomes the LAST line of defence
    and will need re-deciding - recorded here rather than assumed away."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    configure(ccw_env, blocker / "archive")
    hook_only(ccw_env, UUID_A, session(UUID_A))
    assert session_count(ccw_env) == 1


def test_the_hook_never_writes_to_the_claude_source(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F9: sources are read-only, and adding a second write target must not
    change that."""
    from conftest import claude_projects

    target = tmp_path / "archive"
    configure(ccw_env, target)
    transcript = write_transcript(ccw_env, session(UUID_A), session_id=UUID_A)
    before = tree_snapshot(claude_projects(ccw_env))
    run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, cwd=CWD, session_id=UUID_A))
    assert tree_snapshot(claude_projects(ccw_env)) == before


def test_no_archive_configured_means_no_change_to_capture(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    configure(ccw_env, None)
    hook_only(ccw_env, UUID_A, session(UUID_A))
    assert session_count(ccw_env) == 1
    assert not (tmp_path / "archive").exists()


def test_the_store_still_holds_the_payload_too(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Dual storage while `objects/` lives. Retiring it is a SEPARATE decision,
    and until it is taken the hook must keep both safe."""
    from cc_warehouse import store

    target = tmp_path / "archive"
    configure(ccw_env, target)
    data = session(UUID_A)
    hook_only(ccw_env, UUID_A, data)
    assert store.has(warehouse_root(ccw_env), store.sha256_hex(data))
    assert sole_jsonl(target).read_bytes() == data
