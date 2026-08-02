"""Oracle tests: retiring the vault, and the promise that changes with it (19m).

`keep_objects = false` is the mirror of `keep_projections`, and it carries one
consequence the other did not.

Every archive write so far has been NEVER FATAL, on an argument that was true at
the time: the payload is already in the content-addressed store by the time the
archive is touched, so an archive problem must not fail a capture that has
already succeeded. Retire the store and that argument evaporates. A swallowed
failure would then mean the hook reports success while NOTHING holds the session.

So the promise flips with the switch. With a store, an archive failure is
reported and survivable. Without one, it is FATAL: the hook exits non-zero and
says so, because the one thing worse than a failed capture is a failed capture
that reported success.

The session is not lost either way - `~/.claude/projects` still has it, sources
being read-only (F9) - so a loud failure is a `ccw sweep` away from recovery. A
silent one is not, because nobody goes looking.

Contract: DESIGN 4 / 12 (capture reporting); ruling (b) 2026-08-02 (`ccw verify`
becomes archive integrity); R5/F7 (conservative branch); F6 (never silent).
"""

from pathlib import Path

from cc_warehouse import store
from conftest import (
    entry,
    hook_payload,
    jsonl,
    run_ccw,
    session_count,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "b7111111-2222-3333-4444-555555555551"
CWD = "/home/alice/projects/widget"


def session(uuid: str) -> bytes:
    return jsonl(
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


def configure(
    env: dict[str, str],
    *,
    archive_root: Path | None,
    keep_objects: bool | None = None,
) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [f'root = "{warehouse_root(env)}"', f'archive_timezone = "{ZONE}"']
    if archive_root is not None:
        lines.append(f'archive_root = "{archive_root}"')
        lines.append("keep_projections = false")
    if keep_objects is not None:
        lines.append(f"keep_objects = {'true' if keep_objects else 'false'}")
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def hook(env: dict[str, str], uuid: str, data: bytes) -> int:
    transcript = write_transcript(env, data, session_id=uuid, name=f"{uuid}.jsonl")
    return run_ccw(
        ["hook"], env, stdin=hook_payload(transcript, cwd=CWD, session_id=uuid)
    ).code


def stored_objects(env: dict[str, str]) -> int:
    objects = warehouse_root(env) / "objects"
    return len(list(objects.rglob("*.jsonl"))) if objects.is_dir() else 0


# ---------------------------------------------------------------------------
# The default is unchanged
# ---------------------------------------------------------------------------


def test_the_default_still_writes_the_store(ccw_env: dict[str, str], tmp_path: Path) -> None:
    configure(ccw_env, archive_root=tmp_path / "archive")
    assert hook(ccw_env, UUID_A, session(UUID_A)) == 0
    assert stored_objects(ccw_env) == 1


# ---------------------------------------------------------------------------
# Retired: one copy, not two
# ---------------------------------------------------------------------------


def test_with_keep_objects_off_the_payload_lives_only_in_the_archive(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The point of the whole ticket: ONE copy of the raw session."""
    target = tmp_path / "archive"
    configure(ccw_env, archive_root=target, keep_objects=False)
    data = session(UUID_A)
    assert hook(ccw_env, UUID_A, data) == 0
    assert stored_objects(ccw_env) == 0, "the vault was still written"
    assert sorted(target.rglob("*.jsonl"))[0].read_bytes() == data
    assert session_count(ccw_env) == 1, "the catalog row is still written"


def test_render_still_works_with_no_store_at_all(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The verified reader has no fallback now, so this proves it is reading the
    archive rather than quietly leaning on the vault."""
    target = tmp_path / "archive"
    configure(ccw_env, archive_root=target, keep_objects=False)
    assert hook(ccw_env, UUID_A, session(UUID_A)) == 0
    result = run_ccw(["build", "--rebuild"], ccw_env)
    assert result.code == 0, result.err + result.out
    folder = sorted(target.rglob("transcript.md"))
    assert len(folder) == 1


# ---------------------------------------------------------------------------
# THE PROMISE THAT FLIPS
# ---------------------------------------------------------------------------


def test_with_a_store_an_archive_failure_is_survivable(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Today's behaviour, pinned so the change below is visible as a CHANGE."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    configure(ccw_env, archive_root=blocker / "archive", keep_objects=True)
    assert hook(ccw_env, UUID_A, session(UUID_A)) == 0
    assert stored_objects(ccw_env) == 1, "the store took the session"


def test_without_a_store_an_archive_failure_is_REPORTED_not_swallowed(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The one thing worse than a failed capture is a failed capture nobody
    hears about. With no vault behind it, a swallowed archive error would mean
    the hook completing quietly while nothing holds the session.

    ASSERTED ON THE AUDIT LOG, NOT THE EXIT CODE, and the correction is worth
    keeping. The first version of this test demanded a non-zero exit, which
    collides with SPEC 2.6: the hook must NEVER raise into the harness, because
    a warehouse problem must not break the operator's Claude Code session. That
    rule is right and older than this slice, so the test moved to the surface
    where the failure actually has to show up. The property never changed - the
    failure must not be silent (F6) - only my idea of where to look for it.

    No catalog row either: the row must never name a payload nothing holds.
    """
    import json

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    configure(ccw_env, archive_root=blocker / "archive", keep_objects=False)
    assert hook(ccw_env, UUID_A, session(UUID_A)) == 0, "SPEC 2.6: never raise into the harness"

    log = warehouse_root(ccw_env) / "logs" / "capture.jsonl"
    assert log.is_file(), "nothing was recorded at all"
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
    assert any(r.get("status") == "error" for r in records), records
    assert session_count(ccw_env) == 0, "a catalog row names a payload nothing holds"


def test_the_source_transcript_is_untouched_by_the_failure(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Which is what makes the loud failure recoverable rather than terminal:
    `~/.claude` still has it (F9), so a `ccw sweep` retries. A SILENT failure
    would be just as recoverable and nobody would ever go looking."""
    from conftest import claude_projects, tree_snapshot

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    configure(ccw_env, archive_root=blocker / "archive", keep_objects=False)
    write_transcript(ccw_env, session(UUID_A), session_id=UUID_A, name=f"{UUID_A}.jsonl")
    before = tree_snapshot(claude_projects(ccw_env))
    hook(ccw_env, UUID_A, session(UUID_A))
    assert tree_snapshot(claude_projects(ccw_env)) == before


# ---------------------------------------------------------------------------
# The footgun, closed the same way as keep_projections
# ---------------------------------------------------------------------------


def test_keep_objects_off_without_an_archive_is_refused(ccw_env: dict[str, str]) -> None:
    """No vault AND no archive is a capture with nowhere to put anything. R5:
    the conservative branch is the default; F6: the refusal is recorded."""
    from cc_warehouse.config import load_config

    configure(ccw_env, archive_root=None, keep_objects=False)
    config = load_config(
        xdg_config_home=Path(ccw_env["HOME"]) / ".config",
        env={"HOME": ccw_env["HOME"], "CCW_ROOT": ccw_env["CCW_ROOT"]},
    )
    assert config.keep_objects is True, "the unsafe combination was obeyed"
    assert any("keep_objects" in problem for problem in config.config_errors)


def test_the_capture_still_stores_when_the_combination_is_refused(
    ccw_env: dict[str, str],
) -> None:
    configure(ccw_env, archive_root=None, keep_objects=False)
    assert hook(ccw_env, UUID_A, session(UUID_A)) == 0
    assert stored_objects(ccw_env) == 1


# ---------------------------------------------------------------------------
# ruling (b): verify follows the data
# ---------------------------------------------------------------------------


def test_verify_checks_the_archive_once_the_store_is_retired(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Ruling (b), 2026-08-02: `ccw verify` BECOMES archive integrity. Until the
    store retires it keeps checking the vault, because that is what holds the
    data; after, a verb that re-hashed an empty vault and reported "intact"
    would be the most dangerous kind of green."""
    target = tmp_path / "archive"
    configure(ccw_env, archive_root=target, keep_objects=False)
    assert hook(ccw_env, UUID_A, session(UUID_A)) == 0
    assert run_ccw(["build", "--rebuild"], ccw_env).code == 0

    result = run_ccw(["verify"], ccw_env)
    assert result.code == 0, result.err
    assert "folder" in (result.out + result.err), result.out


def test_verify_fails_when_an_archived_session_is_damaged(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The half that proves the verb is looking at something."""
    target = tmp_path / "archive"
    configure(ccw_env, archive_root=target, keep_objects=False)
    assert hook(ccw_env, UUID_A, session(UUID_A)) == 0
    assert run_ccw(["build", "--rebuild"], ccw_env).code == 0

    jsonl_path = sorted(target.rglob("*.jsonl"))[0]
    store.atomic_write(jsonl_path, b'{"type":"user","message":{"role":"user","content":"X"}}\n')
    assert run_ccw(["verify"], ccw_env).code != 0
