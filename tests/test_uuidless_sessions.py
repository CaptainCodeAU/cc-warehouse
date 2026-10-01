"""Oracle tests: a payload with no `sessionId` is written where it is read
(W-20261001-A56).

A `claude -p` stream-json transcript carries no `sessionId`, so its catalog row
has `session_uuid = NULL` and its archive folder is named by a fallback stem.
The writers (`capture._archive_source`, `sweep._repair_head_jsonl`) used the
default stem `session`; every reader used `session-<short>`. While the vault
existed `read_payload` fell through to `store.get` and the mismatch was
invisible. With `keep_objects = false` there is nothing to fall through to, so
`ccw build` failed on every such head and the nightly sweep exited 1.

Every test here runs with `keep_objects = false` and asserts `objects/` does
not exist, so the vault cannot hide a disagreement between a writer and a
reader.

Contract: R1 (identity is sha256), R9 (one naming rule), R5/F7 (a read that
cannot be verified raises), F6 (nothing silent).
"""

import ast
from pathlib import Path
from typing import cast

from cc_warehouse import archive, build, capture, catalog
from cc_warehouse.config import Config
from conftest import jsonl, mark_archive

ZONE = "Australia/Melbourne"
LABEL_DIR = "-home-alice-projects-widget"
CWD = "/home/alice/projects/widget"


def uuidless(marker: str = "one", ts: str = "2026-09-29T14:01:24.763Z") -> bytes:
    """The shape `claude -p --output-format stream-json` writes: system, then
    result lines, with `cwd` and `timestamp` but no `sessionId` anywhere."""
    return jsonl(
        {"type": "system", "subtype": "init", "cwd": CWD, "timestamp": ts},
        {
            "type": "user",
            "timestamp": ts,
            "cwd": CWD,
            "message": {"role": "user", "content": f"prompt {marker}"},
        },
        {
            "type": "assistant",
            "timestamp": ts,
            "cwd": CWD,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]},
        },
        {"type": "result", "subtype": "success", "timestamp": ts},
    )


def vaultless(tmp_path: Path) -> Config:
    root = tmp_path / "warehouse"
    root.mkdir()
    archive_root = mark_archive(tmp_path / "archive", ZONE)
    return Config(
        root=root,
        archive_root=archive_root,
        archive_timezone=ZONE,
        keep_objects=False,
        keep_projections=False,
    )


def transcript(tmp_path: Path, data: bytes, name: str = "stream.jsonl") -> Path:
    path = tmp_path / "claude" / "projects" / LABEL_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def row(config: Config, sha256: str) -> tuple[str, str, str | None, str | None]:
    """(label, short, first_ts, session_uuid) for one catalog row."""
    conn = catalog.open_catalog(config.root)
    try:
        found = conn.execute(
            "SELECT p.label, s.short, s.first_ts, s.session_uuid FROM session s"
            " JOIN project p ON p.id = s.project_id WHERE s.hash = ?",
            (sha256,),
        ).fetchone()
    finally:
        conn.close()
    assert found is not None
    return cast(tuple[str, str, str | None, str | None], tuple(found))


def read_back(config: Config, sha256: str) -> bytes:
    label, short, first_ts, session_uuid = row(config, sha256)
    return archive.read_payload(
        config,
        label=label,
        first_ts=first_ts,
        session_uuid=session_uuid,
        short=short,
        sha256=sha256,
    )


# ---------------------------------------------------------------------------
# The hook writer and THE reader agree, with no vault behind them
# ---------------------------------------------------------------------------


def test_a_captured_uuidless_session_reads_back_with_no_vault(tmp_path: Path) -> None:
    config = vaultless(tmp_path)
    data = uuidless()
    result = capture.capture_transcript(
        config, transcript(tmp_path, data), session_id=None, cwd=None
    )
    assert result.action == "stored"
    assert not (config.root / "objects").exists()
    assert read_back(config, result.sha256) == data


def test_build_reports_no_failures_for_a_uuidless_head_with_no_vault(
    tmp_path: Path,
) -> None:
    config = vaultless(tmp_path)
    data = uuidless()
    capture.capture_transcript(config, transcript(tmp_path, data), session_id=None, cwd=None)
    report = build.build(config)
    assert not (config.root / "objects").exists()
    assert report.failures == ()


def test_a_hook_session_id_names_the_folder_once_across_capture_and_build(
    tmp_path: Path,
) -> None:
    """The hook hands `session_id` even when the payload has none, and the
    catalog row records it. Every writer must then name the folder by it, or
    the build mirror opens a second folder beside the hook's."""
    config = vaultless(tmp_path)
    data = uuidless()
    hook_id = "c1111111-2222-3333-4444-555555555551"
    result = capture.capture_transcript(
        config, transcript(tmp_path, data), session_id=hook_id, cwd=None
    )
    assert build.build(config).failures == ()
    assert read_back(config, result.sha256) == data
    assert config.archive_root is not None
    folders = sorted(p.name for p in (config.archive_root / "widget").iterdir() if p.is_dir())
    assert folders == [f"20260930-000124+1000_{hook_id}"]


# ---------------------------------------------------------------------------
# Fences: the stem cannot quietly get a default or a second spelling again
# ---------------------------------------------------------------------------

_NAMING = frozenset({"archive_dir", "archive_folder_name", "write_source", "write_session_folder"})


def _product_files() -> list[Path]:
    from conftest import SRC_ROOT

    tools = SRC_ROOT.parent.parent / "tools"
    return sorted(SRC_ROOT.glob("*.py")) + sorted(tools.rglob("*.py"))


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def test_no_naming_function_gives_fallback_stem_a_default() -> None:
    """A default is how the writers drifted: `write_source` inherited
    `"session"` from `archive_dir` and its caller never had to think about it.
    Required, pyright strict names every caller that forgets."""
    from conftest import SRC_ROOT

    defaulted: list[str] = []
    seen: set[str] = set()
    for path in sorted(SRC_ROOT.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.FunctionDef) or node.name not in _NAMING:
                continue
            seen.add(node.name)
            for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True):
                if arg.arg == "fallback_stem" and default is not None:
                    defaulted.append(f"{path.name}:{node.lineno} {node.name}")
    assert seen == _NAMING, f"control: every naming function found, got {sorted(seen)}"
    assert not defaulted, f"fallback_stem has a default again: {defaulted}"


def test_every_call_to_a_naming_function_passes_fallback_stem() -> None:
    calls = 0
    missing: list[str] = []
    for path in _product_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or _called_name(node) not in _NAMING:
                continue
            calls += 1
            if not any(k.arg == "fallback_stem" for k in node.keywords):
                missing.append(f"{path.name}:{node.lineno}")
    assert calls >= 10, f"control: expected the known call sites, found {calls}"
    assert not missing, f"call without fallback_stem: {missing}"


def test_the_uuidless_stem_is_spelled_in_one_place() -> None:
    """`session-<short>` written out by hand beside `build.session_stem` is a
    second derivation (R9): it was a hand-spelled stem on each side that
    drifted apart in the first place."""
    spelled: list[str] = []
    for path in _product_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if isinstance(func, ast.FunctionDef) and func.name == "session_stem":
                continue
            if not isinstance(func, ast.FunctionDef):
                continue
            for node in ast.walk(func):
                if (
                    isinstance(node, ast.JoinedStr)
                    and node.values
                    and isinstance(node.values[0], ast.Constant)
                    and node.values[0].value == "session-"
                ):
                    spelled.append(f"{path.name}:{node.lineno} in {func.name}")
    assert not spelled, f"uuid-less stem spelled outside build.session_stem: {spelled}"
