"""Oracle matrix: every writer and every reader agree on ONE folder
(W-20261001-A56, item C).

The uuid-less defect lived for six weeks because each side named the folder
its own way and the vault answered whenever they disagreed. This matrix runs
every writer that creates a session folder, then every reader that locates
one, and asserts they all land on the folder the writer actually made on disk
(found by walking the tree, not by asking the naming function), with the
bytes hash-matching.

With `keep_objects = false` the test also asserts `objects/` never appears,
so nothing can be served from the vault. With `keep_objects = true` the vault
exists, so `read_payload` would answer even from the wrong folder; the test
moves `objects/` aside for that read, and the "exactly one folder" checks
catch a reader that opens a second one.

Axes: payload {with sessionId, without} x keep_objects {true, false} x writer
{hook, sweep, build mirror, import}. Readers: `archive.read_payload`,
`doctor.desync_detail`, `share.share`, `ccw render --session`.
"""

from pathlib import Path
from typing import cast

import pytest

from cc_warehouse import archive, build, capture, catalog, doctor, import_tree, share, store, sweep
from cc_warehouse.config import Config, load_config
from conftest import jsonl, mark_archive, run_cli

ZONE = "Australia/Melbourne"
CWD = "/home/alice/projects/widget"
ENCODED = "-home-alice-projects-widget"
UUID = "d4111111-2222-3333-4444-555555555551"
HOOK_ID = "d4111111-2222-3333-4444-555555555559"
TS = "2026-09-29T14:01:24.763Z"


def payload(with_uuid: bool) -> bytes:
    extra: dict[str, object] = {"sessionId": UUID} if with_uuid else {}
    return jsonl(
        {"type": "system", "subtype": "init", "cwd": CWD, "timestamp": TS, **extra},
        {
            "type": "user",
            "timestamp": TS,
            "cwd": CWD,
            "message": {"role": "user", "content": "prompt for the matrix"},
            **extra,
        },
        {
            "type": "assistant",
            "timestamp": TS,
            "cwd": CWD,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]},
            **extra,
        },
    )


def configure(env: dict[str, str], tmp_path: Path, keep_objects: bool) -> Config:
    archive_root = mark_archive(tmp_path / "archive", ZONE)
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(
        "\n".join([
            f'root = "{env["CCW_ROOT"]}"',
            f'archive_root = "{archive_root}"',
            f'archive_timezone = "{ZONE}"',
            "keep_projections = false",
            f"keep_objects = {'true' if keep_objects else 'false'}",
        ])
        + "\n",
        encoding="utf-8",
    )
    return load_config(xdg_config_home=cfg.parent)


def place(env: dict[str, str], data: bytes) -> Path:
    path = Path(env["HOME"]) / ".claude" / "projects" / ENCODED / "matrix.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def write(writer: str, config: Config, env: dict[str, str], data: bytes, with_uuid: bool) -> None:
    source = place(env, data)
    if writer == "hook":
        # The real hook always hands Claude Code's session_id, payload uuid or not.
        hook_id = UUID if with_uuid else HOOK_ID
        result = capture.capture_transcript(config, source, session_id=hook_id, cwd=CWD)
        assert result.action == "stored", result.detail
    elif writer == "sweep":
        report = sweep.sweep(config, source.parent.parent)
        assert report.failures == (), report.failures
    elif writer == "build":
        result = capture.capture_transcript(config, source, session_id=None, cwd=None)
        assert result.action == "stored", result.detail
        assert build.build(config).failures == ()
    else:
        report = import_tree.import_tree(config, source.parent.parent)
        assert report.failures == (), report.failures


def written_jsonl(archive_root: Path) -> Path:
    """The one session JSONL on disk, found by walking: label/folder/file."""
    found = [
        p
        for p in archive_root.glob("*/*/*.jsonl")
        if not p.parent.parent.name.startswith("_") and p.name != "prompts.jsonl"
    ]
    assert len(found) == 1, f"expected exactly one session JSONL, found {found}"
    return found[0]


def head(config: Config) -> tuple[str, str, str, str | None, str | None]:
    conn = catalog.open_catalog(config.root)
    try:
        rows = conn.execute(
            "SELECT s.hash, s.short, p.label, s.first_ts, s.session_uuid FROM session s"
            " JOIN project p ON p.id = s.project_id"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1, rows
    return cast(tuple[str, str, str, str | None, str | None], tuple(rows[0]))


@pytest.mark.parametrize("writer", ["hook", "sweep", "build", "import"])
@pytest.mark.parametrize("keep_objects", [True, False], ids=["vault", "no-vault"])
@pytest.mark.parametrize("with_uuid", [True, False], ids=["uuid", "uuidless"])
def test_every_reader_finds_the_folder_the_writer_made(
    ccw_env: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
    keep_objects: bool,
    with_uuid: bool,
) -> None:
    config = configure(ccw_env, tmp_path, keep_objects)
    assert config.archive_root is not None
    monkeypatch.setenv("XDG_CONFIG_HOME", str(Path(ccw_env["HOME"]) / ".config"))
    data = payload(with_uuid)
    write(writer, config, ccw_env, data, with_uuid)

    if writer == "import" and not with_uuid:
        # `ccw import` decides "session" by content (archive.is_session needs a
        # sessionId) and files anything else under `_not-sessions/` with NO
        # catalog row (ruling (a)), so no reader is ever pointed at it. The
        # capture and sweep paths catalog the same payload as a session; that
        # split is filed, not changed here (W-20261001-A56 census).
        kept = list((config.archive_root / "_not-sessions").rglob("*.jsonl"))
        assert [store.sha256_hex(p.read_bytes()) for p in kept] == [store.sha256_hex(data)]
        stray = [
            p
            for p in config.archive_root.glob("*/*/*.jsonl")
            if not p.parent.parent.name.startswith("_")
        ]
        assert stray == []
        conn = catalog.open_catalog(config.root)
        try:
            assert conn.execute("SELECT COUNT(*) FROM session").fetchone() == (0,)
        finally:
            conn.close()
        return

    on_disk = written_jsonl(config.archive_root)
    folder = on_disk.parent
    assert store.sha256_hex(on_disk.read_bytes()) == store.sha256_hex(data)
    sha256, short, label, first_ts, session_uuid = head(config)
    assert sha256 == store.sha256_hex(data)

    # Reader 1: THE reader. The vault is moved aside for the read, so only the
    # archive folder the writer made can answer it.
    vault = config.root / "objects"
    aside = config.root / "objects.aside"
    if vault.exists():
        vault.rename(aside)
    try:
        assert archive.read_payload(
            config,
            label=label,
            first_ts=first_ts,
            session_uuid=session_uuid,
            short=short,
            sha256=sha256,
        ) == data
    finally:
        if aside.exists():
            aside.rename(vault)

    # Reader 2: doctor's catalog-driven folder list.
    folders, _problems = doctor.desync_detail(config)
    assert folder in folders

    # Reader 3: share names its bundle by the archive's own key.
    out = tmp_path / "shared"
    report = share.share(config, (f"s:{short}",), out, allow_findings=True, timezone=ZONE)
    assert report.errored == () and report.skipped == ()
    bundles = sorted({p.parent.relative_to(out) for p in out.glob("*/*/*") if p.is_file()})
    assert bundles == [folder.relative_to(config.archive_root)]

    # Reader 4: the render child mirrors into the SAME folder, never a second.
    result = run_cli(["render", "--session", f"s:{short}"])
    assert result.code == 0, result.err
    assert written_jsonl(config.archive_root) == on_disk
    assert (folder / "manifest.json").is_file()

    if not keep_objects:
        assert not (config.root / "objects").exists()
