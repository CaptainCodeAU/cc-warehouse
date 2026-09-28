"""Oracle tests: the hook's render waits for the companions copy (open item
W-20260929-A59, principal ruling 2026-09-29: "copy, then render").

THE RACE THIS CLOSES, live 2026-09-28. `_report_capture` spawned the render
child and the companions child at the same moment. The render child writes
`manifest.json`, whose companion records LIST the session folder's companion
dirs at that instant, while the companions child was still copying into them.
Session 17756a71's manifest recorded a `file_history` entry named
`.05ffbee409e8ffe2@v2.uthseyoc.tmp`, the copier's own tmp file, and `ccw doctor`
FAILed "file-history entry ... is missing" until the next scheduled build.

THE SHAPE NOW: with an archive configured, the hook spawns ONLY the companions
child, and that child spawns the render child when its copying is over, whether
it finished, failed, or found nothing to do. The hook spawns the render itself
only when there is no companions child to hand it to (the spawn failed) or
nothing for one to copy into (no archive configured).

HOW THE RACE IS REPRODUCED WITHOUT A SLEEP. `subprocess.Popen` is replaced by a
recorder, so every child the code spawns lands in a queue instead of running.
The test then plays the children in the worst order: companions first, and
`store.atomic_write` is wrapped so that, with a companion file's tmp file on
disk and not yet renamed, every render queued so far runs to completion. On the
old code the hook had already queued the render, so it ran mid-copy and wrote
the tmp name into the manifest; on the new code nothing is queued until the copy
is over. Every child runs in-process through the real `cli.main`.
"""

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

import pytest

from cc_warehouse import archive, capture, store
from conftest import (
    basic_session,
    hook_payload,
    mark_archive,
    run_ccw,
    run_cli,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
PARENT = "d3111111-2222-3333-4444-555555555551"
ENCODED = "-home-alice-projects-widget"
# The name shape Claude Code really writes into tool-results/ (the same fixture
# test_sidecar_capture.py uses).
STDOUT_NAME = "hook-9c2f1a7b-3d4e-5f60-8a91-b2c3d4e5f607-stdout.txt"
STDOUT_BYTES = b"Output too large (132.9KB). Full output saved to: /home/alice/x\n"
CHILD_PREFIX = [sys.executable, "-m", "cc_warehouse"]


def configure(env: dict[str, str], archive_root: Path | None) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [f'root = "{warehouse_root(env)}"', f'archive_timezone = "{ZONE}"']
    if archive_root is not None:
        lines.append(f'archive_root = "{archive_root}"')
        mark_archive(archive_root, ZONE)
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def plant(env: dict[str, str]) -> Path:
    transcript = write_transcript(
        env, basic_session(session_id=PARENT), session_id=PARENT, encoded_dir=ENCODED
    )
    tool_results = transcript.parent / PARENT / "tool-results"
    tool_results.mkdir(parents=True)
    (tool_results / STDOUT_NAME).write_bytes(STDOUT_BYTES)
    return transcript


def grow(transcript: Path) -> None:
    extra = json.dumps({"type": "user", "sessionId": PARENT, "message": {"role": "user"}})
    transcript.write_bytes(transcript.read_bytes() + extra.encode() + b"\n")


def session_folder(archive_root: Path) -> Path:
    folders = sorted(archive_root.glob(f"*/*_{PARENT}"))
    assert len(folders) == 1, f"expected one session folder, got {folders}"
    return folders[0]


def manifest(archive_root: Path) -> dict[str, object]:
    path = session_folder(archive_root) / "manifest.json"
    assert path.is_file(), f"no manifest: the session was never rendered ({path})"
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


class _NoProcess:
    """What the recorder hands back in place of a real child."""

    pid = 0


class Children:
    """Records every `ccw` child the code spawns instead of starting it."""

    def __init__(self) -> None:
        self.queue: list[list[str]] = []
        self.refuse: set[str] = set()

    def popen(self, argv: Sequence[str], **_kwargs: object) -> _NoProcess:
        args = [str(a) for a in argv]
        if args[: len(CHILD_PREFIX)] != CHILD_PREFIX:
            return _NoProcess()  # not a ccw child (a desktop alert, say): ignore
        verb = args[len(CHILD_PREFIX)]
        if verb in self.refuse:
            raise OSError(11, "Resource temporarily unavailable")
        self.queue.append(args[len(CHILD_PREFIX) :])
        return _NoProcess()

    def verbs(self) -> list[str]:
        return [args[0] for args in self.queue]

    def take(self, verb: str) -> list[list[str]]:
        taken = [args for args in self.queue if args[0] == verb]
        self.queue = [args for args in self.queue if args[0] != verb]
        return taken

    def run(self, verb: str) -> None:
        for args in self.take(verb):
            run_cli(args)


@pytest.fixture()
def children(monkeypatch: pytest.MonkeyPatch) -> Children:
    recorder = Children()
    monkeypatch.setattr(subprocess, "Popen", recorder.popen)
    return recorder


def slow_companion_copies(
    monkeypatch: pytest.MonkeyPatch, children: Children
) -> Callable[[], int]:
    """Make every copy into a companion dir pause with its tmp file on disk and
    run whatever render has been queued by then. Returns a counter of how many
    companion copies took the pause, so a test can prove the window was real."""
    real_atomic_write = store.atomic_write
    paused = 0
    companion_dirs = set(archive.COMPANION_MANIFEST_KEYS)

    def atomic_write(path: Path, data: bytes) -> None:
        nonlocal paused
        if not companion_dirs.intersection(path.parts):
            real_atomic_write(path, data)
            return
        paused += 1
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        children.run("render")  # the render child wins the race, as it did live
        os.replace(tmp, path)

    monkeypatch.setattr(store, "atomic_write", atomic_write)
    return lambda: paused


def fire_hook(transcript: Path) -> None:
    result = run_cli(["hook"], stdin=hook_payload(transcript, session_id=PARENT))
    assert result.code == 0, result.err


# ---------------------------------------------------------------------------
# (1) the manifest lists every companion file under its final name
# ---------------------------------------------------------------------------


def test_a_slow_companion_copy_never_reaches_the_manifest_as_a_tmp_name(
    ccw_env: dict[str, str],
    tmp_path: Path,
    children: Children,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    paused = slow_companion_copies(monkeypatch, children)

    fire_hook(transcript)
    children.run("companions")
    children.run("render")  # whatever the companions child handed over

    assert paused() >= 1, "fixture precondition: no companion copy took the slow path"
    records = cast(list[dict[str, object]], manifest(archive_root).get("tool_results"))
    names = sorted(str(r["name"]) for r in records)
    on_disk = sorted(
        p.relative_to(session_folder(archive_root) / "tool-results").as_posix()
        for p in (session_folder(archive_root) / "tool-results").rglob("*")
        if p.is_file()
    )
    assert names == [STDOUT_NAME], f"manifest recorded {names}, disk holds {on_disk}"
    assert names == on_disk
    assert not children.queue, f"children left unrun: {children.queue}"


def test_with_an_archive_the_hook_spawns_only_the_companions_child(
    ccw_env: dict[str, str], tmp_path: Path, children: Children
) -> None:
    """The structural half of the ruling: the render is not started by the hook,
    so it cannot start before the copy it must list."""
    configure(ccw_env, tmp_path / "archive")
    fire_hook(plant(ccw_env))
    assert children.verbs() == ["companions"]


def test_the_companions_child_hands_over_to_the_render_when_it_is_done(
    ccw_env: dict[str, str], tmp_path: Path, children: Children
) -> None:
    configure(ccw_env, tmp_path / "archive")
    fire_hook(plant(ccw_env))
    [companions] = children.take("companions")
    children.take("render")  # count only what the companions child spawns
    run_cli(companions)
    renders = children.take("render")
    assert len(renders) == 1, f"the companions child spawned {renders}"
    assert renders[0][1:] == ["--session", companions[2]]


# ---------------------------------------------------------------------------
# (2) the render still happens when the companions child fails or never runs
# ---------------------------------------------------------------------------


def test_a_companions_child_that_raises_still_hands_over_to_the_render(
    ccw_env: dict[str, str],
    tmp_path: Path,
    children: Children,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge case 1: the copy crashes part way. The render still runs, and the
    manifest it writes lists only the files that really landed."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    fire_hook(plant(ccw_env))

    def crash(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("copy died part way")

    monkeypatch.setattr(capture, "archive_companions", crash)
    children.take("render")  # count only what the companions child spawns
    children.run("companions")
    assert children.verbs() == ["render"], "a failed companions pass left the session unrendered"
    children.run("render")
    records = cast(list[dict[str, object]], manifest(archive_root).get("tool_results"))
    assert records == [], f"nothing was copied, yet the manifest lists {records}"


def test_a_companions_child_with_no_catalog_row_still_hands_over_to_the_render(
    ccw_env: dict[str, str], tmp_path: Path, children: Children
) -> None:
    """The render child owns the "no stored session" report (exit 1, stderr), so
    the companions child passes the short on rather than deciding for it."""
    configure(ccw_env, tmp_path / "archive")
    transcript = plant(ccw_env)
    result = run_cli(
        ["companions", "--session", "s:deadbeef0000", "--transcript", str(transcript)]
    )
    assert result.code == 1
    assert children.queue == [["render", "--session", "s:deadbeef0000"]]


def test_a_failed_companions_spawn_makes_the_hook_spawn_the_render_itself(
    ccw_env: dict[str, str], tmp_path: Path, children: Children
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    children.refuse.add("companions")
    fire_hook(plant(ccw_env))
    assert children.verbs() == ["render"]
    children.run("render")
    assert manifest(archive_root)["tool_results"] == []


def test_with_no_archive_the_hook_spawns_the_render_at_once(
    ccw_env: dict[str, str], children: Children
) -> None:
    """Edge case 6: nothing is copied into an archive folder, so there is nothing
    to wait for and the render starts with no added delay."""
    configure(ccw_env, None)
    fire_hook(plant(ccw_env))
    assert sorted(children.verbs()) == ["companions", "render"]
    children.run("companions")
    assert sorted(children.verbs()) == ["render"], "the render must not be spawned twice"


# ---------------------------------------------------------------------------
# (3) the inline path (defer_companions=False) still renders a full manifest
# ---------------------------------------------------------------------------


def test_the_inline_path_still_renders_a_complete_manifest(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`ccw sweep` captures with companions inline and renders in its own build,
    no children involved; the manifest lists the copied file."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant(ccw_env)
    result = run_ccw(["sweep"], ccw_env)
    assert result.code == 0, result.err
    records = cast(list[dict[str, object]], manifest(archive_root).get("tool_results"))
    assert [r["name"] for r in records] == [STDOUT_NAME]


# ---------------------------------------------------------------------------
# edge cases 3 and 5
# ---------------------------------------------------------------------------


def test_a_duplicate_invocation_spawns_no_child(
    ccw_env: dict[str, str], tmp_path: Path, children: Children
) -> None:
    configure(ccw_env, tmp_path / "archive")
    transcript = plant(ccw_env)
    fire_hook(transcript)
    children.queue.clear()
    fire_hook(transcript)
    assert children.queue == []


def test_two_quick_captures_render_the_later_payload(
    ccw_env: dict[str, str], tmp_path: Path, children: Children
) -> None:
    """A resumed session: two fresh captures before either child has run. The
    worst order runs the later render first, then the earlier one."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    fire_hook(transcript)
    grow(transcript)
    fire_hook(transcript)
    assert children.verbs() == ["companions", "companions"]
    first, second = children.take("companions")
    run_cli(second)
    run_cli(first)
    for args in reversed(children.take("render")):
        run_cli(args)
    assert manifest(archive_root)["source_hash"] == store.sha256_hex(transcript.read_bytes())
