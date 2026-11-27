"""Fixtures for the ccstats suite.

These tests are deliberately OUTSIDE the project's oracle suite: pyproject sets
`testpaths = ["tests"]`, so `uv run pytest` at the repo root never collects them
and the 1,112-test contract suite is unaffected. Run them with:

    uv run pytest tools/ccstats/tests -q
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

CCSTATS = Path(__file__).resolve().parent.parent


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    """Point ccw's config at a throwaway one before any test imports `common`.

    `common.py` reads ccw's config AT IMPORT and stops when it names no
    archive_root (#8025). Left alone, that made this suite read the real
    machine's config: it could not start in a test box that has none, and on a
    machine that has one it pointed ARCHIVE/DATA_ROOT at real data. Configure
    runs before collection, so every module sees the throwaway config.

    The folder comes from pytest's own temp factory (its basetemp inside
    TMPDIR), so pytest removes it with its other numbered folders; this file
    deletes nothing. The run refuses to start unless the paths ccw resolves sit
    inside that folder."""
    factory: pytest.TempPathFactory = config._tmp_path_factory  # type: ignore[attr-defined]
    sandbox = factory.mktemp("ccstats-cfg").resolve()
    data_root, archive_root, xdg = sandbox / "data", sandbox / "archive", sandbox / "xdg"
    for folder in (data_root, archive_root, xdg / "cc-warehouse"):
        folder.mkdir(parents=True)
    (xdg / "cc-warehouse" / "config.toml").write_text(
        f"root = {json.dumps(str(data_root))}\narchive_root = {json.dumps(str(archive_root))}\n"
    )
    os.environ["XDG_CONFIG_HOME"] = str(xdg)
    os.environ["CCW_ROOT"] = str(data_root)

    from cc_warehouse.config import load_config

    resolved = load_config()
    for name, path in (("root", resolved.root), ("archive_root", resolved.archive_root)):
        if path is None or not Path(path).resolve().is_relative_to(sandbox):
            raise pytest.UsageError(
                f"ccstats tests: ccw's {name} resolved to {path}, outside the throwaway "
                f"config {sandbox}; refusing to run against a real warehouse"
            )
if str(CCSTATS) not in sys.path:
    sys.path.insert(0, str(CCSTATS))


def entry(**fields: object) -> str:
    """One JSONL line."""
    return json.dumps(fields)


def assistant(
    ts: str,
    *,
    model: str = "claude-opus-5",
    inp: int = 10,
    out: int = 100,
    cw5: int = 0,
    cw1h: int = 0,
    read: int = 0,
    thinking: int | None = None,
    speed: str | None = "standard",
    tools: list[str] | None = None,
) -> str:
    """An assistant entry carrying a realistic `usage` block."""
    usage: dict[str, object] = {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_creation_input_tokens": cw5 + cw1h,
        "cache_read_input_tokens": read,
        "cache_creation": {
            "ephemeral_5m_input_tokens": cw5,
            "ephemeral_1h_input_tokens": cw1h,
        },
        "service_tier": "standard",
    }
    if speed is not None:
        usage["speed"] = speed
    if thinking is not None:
        usage["output_tokens_details"] = {"thinking_tokens": thinking}
    content: list[dict[str, object]] = [{"type": "text", "text": "ok"}]
    for name in tools or []:
        content.append({"type": "tool_use", "name": name, "input": {}})
    return entry(
        type="assistant",
        timestamp=ts,
        sessionId="s-1",
        cwd="/Users/x/CODE/demo",
        message={"role": "assistant", "model": model, "usage": usage, "content": content},
    )


def user(ts: str, text: str = "hello") -> str:
    return entry(
        type="user",
        timestamp=ts,
        sessionId="s-1",
        cwd="/Users/x/CODE/demo",
        message={"role": "user", "content": [{"type": "text", "text": text}]},
    )


def payload(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode()


@pytest.fixture
def scan():
    """`collect.scan_transcript` bound to a throwaway path."""
    import collect

    def run(data: bytes, tmp_path: Path, **kw: object):
        target = tmp_path / "s-1.jsonl"
        target.write_bytes(data)
        return collect.scan_transcript(
            target,
            source_tree=kw.get("source_tree", "live"),
            container=kw.get("container", "demo"),
            is_subagent=bool(kw.get("is_subagent", False)),
            parent_uuid=kw.get("parent_uuid"),
        )

    return run
