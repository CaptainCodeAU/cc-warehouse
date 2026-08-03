"""Oracle tests: sweep captures sub-agents, verify checks them, share omits them.

Slices 21d, 21e and 21f. Together these are what make "leave nothing behind in
`~/.claude`" true rather than aspirational.

21d  sweep stops skipping them. SPEC section 8 said agent-* are skipped by the
     default sweep, with a note in sweep.py that "a config opt-in to include them
     lands with slice 13" - which was never built. The opt-in exists now and
     DEFAULTS ON, because the premise changed: `~/.claude` is being cleared, so
     anything the sweep declines to take is destroyed rather than deferred.
21e  the parent's manifest lists its sub-agents. Without it a deleted sub-agent
     folder is undetectable - verify would see five valid files and report clean,
     which is the most dangerous kind of green.
21f  share omits them by default. They carry raw tool output and whole file
     contents; publishing one by accident is far worse than omitting it.

Contract: SPEC 8 (amended); DESIGN 6 (manifest key set); ruling (b) 2026-08-02
(verify = archive integrity); DESIGN 9 (share is sanitized); R10; F6.
"""

import json
from pathlib import Path

from cc_warehouse import archive
from cc_warehouse.render import RenderOptions
from conftest import (
    DEFAULT_UUID,
    basic_session,
    hook_payload,
    run_ccw,
    subagent_meta,
    subagent_session,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
OPTS = RenderOptions()
LABEL = "widget"
AGENT = "a94d30c1d877f964d"
PARENT = "d3111111-2222-3333-4444-555555555551"
CWD = "/home/alice/projects/widget"


def configure(env: dict[str, str], archive_root: Path, *, subagents: bool | None = None) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [
        f'root = "{warehouse_root(env)}"',
        f'archive_timezone = "{ZONE}"',
        f'archive_root = "{archive_root}"',
    ]
    if subagents is not None:
        lines.append(f"archive_subagents = {'true' if subagents else 'false'}")
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def plant(env: dict[str, str]) -> None:
    """A parent session plus one sub-agent, laid out the way Claude Code does."""
    write_transcript(
        env, basic_session(session_id=PARENT), session_id=PARENT, name=f"{PARENT}.jsonl"
    )
    projects = Path(env["HOME"]) / ".claude" / "projects" / "-home-alice-projects-widget"
    sub = projects / PARENT / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / f"agent-{AGENT}.jsonl").write_bytes(
        subagent_session(agent_id=AGENT, parent_uuid=PARENT)
    )
    (sub / f"agent-{AGENT}.meta.json").write_bytes(subagent_meta())


# ---------------------------------------------------------------------------
# 21d: sweep takes them
# ---------------------------------------------------------------------------


def test_a_sweep_captures_the_subagent_alongside_its_parent(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, target)
    plant(ccw_env)
    result = run_ccw(["sweep"], ccw_env)
    assert result.code == 0, result.err

    subs = list(target.rglob(f"{AGENT}.jsonl"))
    assert len(subs) == 1, f"the sub-agent was not captured: {list(target.rglob('*.jsonl'))}"
    assert subs[0].parent.parent.name == archive.SUBAGENTS_DIR


def test_the_subagent_nests_under_its_parent_not_beside_it(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The principal's requirement stated as a test: never decouple a sub-agent
    from the session it ran inside."""
    target = tmp_path / "archive"
    configure(ccw_env, target)
    plant(ccw_env)
    assert run_ccw(["sweep"], ccw_env).code == 0

    sub = next(target.rglob(f"{AGENT}.jsonl"))
    session_folder = sub.parent.parent.parent
    assert session_folder.name.endswith(f"_{PARENT}")
    assert (session_folder / f"{PARENT}.jsonl").is_file()


def test_the_subagent_gets_no_markdown_or_html(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, target)
    plant(ccw_env)
    assert run_ccw(["sweep"], ccw_env).code == 0
    sub = next(target.rglob(f"{AGENT}.jsonl")).parent
    assert {p.name for p in sub.iterdir()} == {f"{AGENT}.jsonl", "meta.json"}


def test_the_opt_out_restores_the_old_behaviour(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """SPEC 8's original rule, still reachable. The DEFAULT changed, not the
    ability to have it the old way."""
    target = tmp_path / "archive"
    configure(ccw_env, target, subagents=False)
    plant(ccw_env)
    assert run_ccw(["sweep"], ccw_env).code == 0
    assert not list(target.rglob(f"{AGENT}.jsonl"))


def test_sweeping_twice_is_idempotent(ccw_env: dict[str, str], tmp_path: Path) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, target)
    plant(ccw_env)
    assert run_ccw(["sweep"], ccw_env).code == 0
    assert run_ccw(["sweep"], ccw_env).code == 0
    assert len(list(target.rglob(f"{AGENT}.jsonl"))) == 1


def test_the_parent_transcript_is_not_overwritten_by_the_sweep(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """21a's defect, asserted end to end through the real verb rather than at the
    library boundary."""
    target = tmp_path / "archive"
    configure(ccw_env, target)
    plant(ccw_env)
    assert run_ccw(["sweep"], ccw_env).code == 0
    parent_file = next(target.rglob(f"{PARENT}.jsonl"))
    assert parent_file.read_bytes() == basic_session(session_id=PARENT)


# ---------------------------------------------------------------------------
# 21e: the manifest records them, verify checks them
# ---------------------------------------------------------------------------


def test_the_parent_manifest_lists_its_subagents(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, target)
    plant(ccw_env)
    assert run_ccw(["sweep"], ccw_env).code == 0
    assert run_ccw(["build", "--rebuild"], ccw_env).code == 0

    manifest_path = next(target.rglob("manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    listed = manifest["subagents"]
    assert len(listed) == 1
    assert listed[0]["agent_id"] == AGENT
    assert listed[0]["bytes"] > 0
    assert len(listed[0]["sha256"]) == 64


def test_a_session_with_no_subagents_reports_an_empty_list(tmp_path: Path) -> None:
    """An empty list, never a missing key: a reader must be able to tell "none"
    from "this manifest predates the feature"."""
    result = archive.write_session_folder(tmp_path, LABEL, basic_session(), OPTS, ZONE)
    manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["subagents"] == []


def test_verify_fails_when_a_subagent_transcript_is_altered(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, target)
    plant(ccw_env)
    assert run_ccw(["sweep"], ccw_env).code == 0
    assert run_ccw(["build", "--rebuild"], ccw_env).code == 0

    sub = next(target.rglob(f"{AGENT}.jsonl"))
    sub.write_bytes(subagent_session(agent_id=AGENT, prompt="TAMPERED"))
    result = run_ccw(["archive", "--to", str(target), "--verify"], ccw_env)
    assert result.code != 0
    assert AGENT in (result.out + result.err)


# ---------------------------------------------------------------------------
# 21f: share omits them
# ---------------------------------------------------------------------------


def test_a_shared_bundle_contains_no_subagent_transcripts(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """They carry raw tool output and whole file contents. Publishing one by
    accident is far worse than omitting it, so the default is omission."""
    target = tmp_path / "archive"
    configure(ccw_env, target)
    plant(ccw_env)
    assert run_ccw(["sweep"], ccw_env).code == 0

    from conftest import catalog_rows

    rows = catalog_rows(ccw_env, "SELECT short FROM session")
    short = str(tuple(rows[0])[0])  # type: ignore[index]
    out = tmp_path / "bundle"
    assert run_ccw(["share", f"s:{short}", "--out", str(out)], ccw_env).code == 0

    assert not list(out.rglob("*.jsonl"))
    assert not list(out.rglob(archive.SUBAGENTS_DIR))
    assert "AGENTFINDING" not in "".join(
        p.read_text(encoding="utf-8", errors="replace") for p in out.rglob("*.md")
    )


def test_the_hook_captures_a_subagent_too(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The capture path, not just the sweep: a session ending must bring its
    sub-agents with it, or the archive drifts between sweeps."""
    target = tmp_path / "archive"
    configure(ccw_env, target)
    plant(ccw_env)
    transcript = (
        Path(ccw_env["HOME"]) / ".claude" / "projects"
        / "-home-alice-projects-widget" / f"{PARENT}.jsonl"
    )
    assert (
        run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, cwd=CWD, session_id=PARENT)).code
        == 0
    )
    assert list(target.rglob(f"{AGENT}.jsonl")), "the hook left the sub-agent behind"


def test_nothing_is_left_behind_for_a_swept_session(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The goal, stated as an assertion: every JSONL under the source has a
    byte-identical counterpart in the archive."""
    import hashlib

    target = tmp_path / "archive"
    configure(ccw_env, target)
    plant(ccw_env)
    assert run_ccw(["sweep"], ccw_env).code == 0

    def digests(root: Path) -> set[str]:
        return {
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*.jsonl")
            if p.is_file()
        }

    source = Path(ccw_env["HOME"]) / ".claude" / "projects"
    missing = digests(source) - digests(target)
    assert not missing, f"{len(missing)} source payloads have no archive copy"
    assert DEFAULT_UUID or True
