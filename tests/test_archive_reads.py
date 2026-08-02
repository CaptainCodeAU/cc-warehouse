"""Oracle tests: reads come from the archive, not the store (ticket 19, slice 19l).

The last thing holding `objects/` in place. `store.get` was the read path in four
places - render, build, and share twice - so retiring the vault would have broken
every one of them. This slice puts ONE reader in front of them all: prefer the
archive, fall back to the store while it still exists.

THE READ IS VERIFIED, not trusted. The catalog names a session by sha256, and the
archive holds a file. If those disagree the archive is not the session the caller
asked for, and returning it anyway would be identity-by-location - the same class
as F1's identity-by-size, just with a different cheap proxy. So every archive read
is hashed against the hash the caller named, and a mismatch falls back rather than
being served.

Contract: R1 (identity is sha256, everywhere, no shortcut); R9 (one reader, not
four); R5/F7 (a mismatch takes the conservative branch); F6 (nothing silent).
"""

from pathlib import Path

from cc_warehouse import archive, store
from cc_warehouse.config import Config
from conftest import (
    entry,
    hook_payload,
    jsonl,
    run_ccw,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "a8111111-2222-3333-4444-555555555551"
CWD = "/home/alice/projects/widget"
LABEL = "widget"


def session(uuid: str, marker: str = "ORIGINAL") -> bytes:
    return jsonl(
        entry(
            "user",
            f"{marker} prompt",
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


def config_for(root: Path, archive_root: Path | None) -> Config:
    return Config(root=root, archive_root=archive_root, archive_timezone=ZONE)


def seeded(tmp_path: Path, data: bytes) -> tuple[Config, Path]:
    """A warehouse with the payload in the STORE, and an archive folder holding
    the same payload."""
    root = tmp_path / "warehouse"
    (root / "objects").mkdir(parents=True)
    store.put(root, data)
    archive_root = tmp_path / "archive"
    jsonl_path = archive.write_source(archive_root, LABEL, data, ZONE)
    return config_for(root, archive_root), jsonl_path


# ---------------------------------------------------------------------------
# One reader, preferring the archive
# ---------------------------------------------------------------------------


def test_the_payload_comes_from_the_archive_when_it_is_there(
    tmp_path: Path,
) -> None:
    data = session(UUID_A)
    config, _ = seeded(tmp_path, data)
    assert archive.read_payload(
        config,
        label=LABEL,
        first_ts="2026-05-07T03:47:45.000Z",
        session_uuid=UUID_A,
        short="abc123",
        sha256=store.sha256_hex(data),
    ) == data


def test_it_really_read_the_archive_and_not_the_store(tmp_path: Path) -> None:
    """The test above passes whichever source answered, because both hold the
    same bytes. This one removes the store entirely, so only the archive can
    have served it."""
    data = session(UUID_A)
    config, _ = seeded(tmp_path, data)
    store_path = store.object_path(config.root, store.sha256_hex(data))
    store_path.rename(store_path.with_suffix(".moved"))

    assert archive.read_payload(
        config,
        label=LABEL,
        first_ts="2026-05-07T03:47:45.000Z",
        session_uuid=UUID_A,
        short="abc123",
        sha256=store.sha256_hex(data),
    ) == data


def test_it_falls_back_to_the_store_when_the_archive_lacks_the_folder(
    tmp_path: Path,
) -> None:
    """During the transition the vault is still the backstop. A session captured
    before the archive existed has no folder, and must still render."""
    data = session(UUID_A)
    root = tmp_path / "warehouse"
    (root / "objects").mkdir(parents=True)
    store.put(root, data)
    config = config_for(root, tmp_path / "empty-archive")

    assert archive.read_payload(
        config,
        label=LABEL,
        first_ts="2026-05-07T03:47:45.000Z",
        session_uuid=UUID_A,
        short="abc123",
        sha256=store.sha256_hex(data),
    ) == data


def test_no_archive_configured_reads_the_store(tmp_path: Path) -> None:
    data = session(UUID_A)
    root = tmp_path / "warehouse"
    (root / "objects").mkdir(parents=True)
    store.put(root, data)
    config = config_for(root, None)
    assert archive.read_payload(
        config,
        label=LABEL,
        first_ts="2026-05-07T03:47:45.000Z",
        session_uuid=UUID_A,
        short="abc123",
        sha256=store.sha256_hex(data),
    ) == data


# ---------------------------------------------------------------------------
# The read is VERIFIED (R1): identity is the hash, never the location
# ---------------------------------------------------------------------------


def test_an_archive_file_that_does_not_match_its_hash_is_not_served(
    tmp_path: Path,
) -> None:
    """Identity-by-location would be F1 with a different cheap proxy. The
    catalog names a sha256; a file sitting in the right folder is not evidence
    that it IS that session."""
    data = session(UUID_A)
    config, jsonl_path = seeded(tmp_path, data)
    store.atomic_write(jsonl_path, session(UUID_A, marker="TAMPERED"))

    served = archive.read_payload(
        config,
        label=LABEL,
        first_ts="2026-05-07T03:47:45.000Z",
        session_uuid=UUID_A,
        short="abc123",
        sha256=store.sha256_hex(data),
    )
    assert served == data, "a mismatched archive file was served"
    assert b"TAMPERED" not in served


def test_a_mismatch_with_no_store_fallback_raises_rather_than_lying(
    tmp_path: Path,
) -> None:
    """Once `objects/` retires there is nothing to fall back to. Refusing is the
    conservative branch (R5/F7); serving the wrong session silently is the
    failure this whole project exists to prevent."""
    import pytest

    data = session(UUID_A)
    config, jsonl_path = seeded(tmp_path, data)
    store.atomic_write(jsonl_path, session(UUID_A, marker="TAMPERED"))
    store_path = store.object_path(config.root, store.sha256_hex(data))
    store_path.rename(store_path.with_suffix(".moved"))

    # OSError specifically, not a blind Exception: the point is that the read
    # FAILS at the filesystem, not that something somewhere went wrong. A blind
    # assert would also pass on a TypeError from a future signature change and
    # would report a refusal that never happened.
    with pytest.raises(OSError):
        archive.read_payload(
            config,
            label=LABEL,
            first_ts="2026-05-07T03:47:45.000Z",
            session_uuid=UUID_A,
            short="abc123",
            sha256=store.sha256_hex(data),
        )


# ---------------------------------------------------------------------------
# The consumers actually use it
# ---------------------------------------------------------------------------


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


def test_render_and_build_work_with_the_store_objects_removed(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The end-to-end proof that `objects/` is retirable: take it away and the
    verbs still produce output, because the archive is answering."""
    target = tmp_path / "archive"
    configure(ccw_env, target)
    data = session(UUID_A)
    transcript = write_transcript(ccw_env, data, session_id=UUID_A, name=f"{UUID_A}.jsonl")
    assert (
        run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, cwd=CWD, session_id=UUID_A)).code
        == 0
    )

    objects = warehouse_root(ccw_env) / "objects"
    objects.rename(objects.with_name("objects.moved"))

    result = run_ccw(["build", "--rebuild"], ccw_env)
    assert result.code == 0, result.err + result.out
    folder = next(archive.walk_folders(target))
    assert (folder / "transcript.md").is_file()
    assert "ORIGINAL" in (folder / "transcript.md").read_text(encoding="utf-8")


def test_no_consumer_calls_store_get_directly_any_more() -> None:
    """R9. Four call sites became one reader; a fifth appearing later would
    reintroduce the coupling this slice removed, and would keep working right up
    until `objects/` was deleted."""
    import ast

    from conftest import SRC_ROOT

    allowed = {"archive.py"}  # the reader itself, and the migration source
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.glob("*.py")):
        if path.name in allowed or path.name == "store.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "store"
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"store.get called outside the shared reader (R9): {offenders}"
