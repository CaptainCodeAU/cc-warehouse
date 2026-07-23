"""Contract-derived regression tests for ccw relocate (slice 12).

Written from DESIGN section 11, SPEC section 10.2 and FINDINGS F2/F4/F6/F7/F9 (not
ported from the implementation) to pin the confirmed reviewer findings of the slice-12
loop. Every test here guards a class where a regression silently corrupts or loses a
user's data, or breaks a locked rule:

- B10 (R4/F9): a [relocate] root containing the warehouse must never rewrite a stored
  object; an object that stopped hashing to its own name is indistinguishable from rot.
- SPEC 10.2 / R4: captured transcripts are SOURCES. Containers are renamed; nothing
  outside the memory roots is ever string-edited.
- B1/F4: the encoding collapses `/`, `_` and `.` to `-`, so an encoded name alone cannot
  tell a repo SUBDIR from an unrelated SIBLING. Only proven members are renamed.
- B2/F9: a relative <repo> must not turn the pattern into a bare word.
- A10/F4: the boundary guard must cover `.` so `widget.bak` is not swept up.
- A9/B9 (R4/F9): a symlinked memory file must never be replaced by a regular file.
- B6/B4/A2 (R5/F7): symlinked source, nested target, and a malformed config are refusals
  that change nothing, never half-applied runs.
- A11/B12: `--to`'s operand must never be mistaken for the positional <repo>.

Ticket 12a carried-forward findings (added 2026-07-23, each proven to FAIL against the
pre-fix code before the fix landed, per the slice-12 escalation lesson):

- 12a-1 (R4/F9): the warehouse and source-transcript exclusions compared UNRESOLVED
  paths. A symlinked `CCW_ROOT` or a symlinked `~/.claude` (any dotfile-managed account)
  meant the walk reached the REAL path while the exclusion held the SYMLINK path, so the
  two never compared equal and the guard silently did nothing. This is the same locked
  rule the slice-12 escalation caught ("source transcripts are never modified by
  anything, ever"), left open for the symlinked case.
"""

import hashlib
import json
import re
import shutil
import stat
from pathlib import Path
from typing import cast

from conftest import (
    basic_session,
    claude_projects,
    hook_payload,
    run_ccw,
    tree_snapshot,
    warehouse_root,
)


def encode(path: Path) -> str:
    return re.sub(r"[/_.]", "-", str(path))


class World:
    """A repo with a real subdir, a hyphen sibling, a dotted sibling, and an inventory."""

    def __init__(self, env: dict[str, str], tmp_path: Path, roots: list[str] | None = None) -> None:
        home = Path(env["HOME"])
        self.env = env
        self.repo = home / "projects" / "widget"
        self.repo.mkdir(parents=True)
        (self.repo / "main.py").write_text("print('widget')\n")
        self.sub = self.repo / "sub"
        self.sub.mkdir()
        self.sibling = home / "projects" / "widget-two"
        self.sibling.mkdir()
        self.bak = home / "projects" / "widget.bak"
        self.bak.mkdir()
        self.new_repo = home / "code" / "widget-next"

        self.inventory = tmp_path / "pai-root"
        self.inventory.mkdir()
        self.memory_md = self.inventory / "memory.md"
        self.memory_md.write_text(
            f"repo {self.repo}\nsibling {self.sibling}\nbackup {self.bak}\n"
            "the widget word alone must survive\n"
        )
        self.state_json = self.inventory / "state.json"
        self.state_json.write_text(json.dumps({"p": str(self.repo), "sib": str(self.sibling)}))

        self.root = warehouse_root(env)
        self.root.mkdir(parents=True, exist_ok=True)
        chosen = roots if roots is not None else [str(self.inventory)]
        (self.root / "config.toml").write_text(
            "[relocate]\nroots = [" + ", ".join(f'"{r}"' for r in chosen) + "]\n"
        )
        self.payload = self.capture(self.repo, "11111111-2222-3333-4444-555555555555")

    def capture(self, cwd: Path, session_id: str) -> bytes:
        directory = claude_projects(self.env) / encode(cwd)
        directory.mkdir(parents=True, exist_ok=True)
        data = basic_session(cwd=str(cwd), session_id=session_id)
        transcript = directory / "capture.jsonl"
        transcript.write_bytes(data)
        result = run_ccw(
            ["hook"], self.env, stdin=hook_payload(transcript, cwd=str(cwd), session_id=session_id)
        )
        assert result.code == 0, result.err
        return data

    def encoded_dir(self, cwd: Path) -> Path:
        return claude_projects(self.env) / encode(cwd)

    def apply(self, *extra: str):
        return run_ccw(
            ["relocate", str(self.repo), "--to", str(self.new_repo), "--apply", "--yes", *extra],
            self.env,
        )


def test_stored_objects_are_never_content_rewritten(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R4/F9: a root that contains the warehouse must not rewrite immutable objects."""
    world = World(ccw_env, tmp_path, roots=[str(tmp_path)])
    digest = hashlib.sha256(world.payload).hexdigest()
    obj = world.root / "objects" / digest[:2] / f"{digest}.jsonl"
    assert obj.exists()
    assert world.apply().code == 0
    assert hashlib.sha256(obj.read_bytes()).hexdigest() == digest, "store object was rewritten"
    assert run_ccw(["verify"], ccw_env).code == 0, "verify no longer clean after relocate"


def test_source_transcripts_are_never_string_edited(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """SPEC 10.2 / R4: containers are renamed; source transcripts are read-only."""
    world = World(ccw_env, tmp_path, roots=[str(tmp_path)])
    assert world.apply().code == 0
    moved = world.encoded_dir(world.new_repo)
    transcripts = list(moved.rglob("*.jsonl"))
    assert transcripts, "the encoded dir should have been renamed, carrying its transcripts"
    assert str(world.repo) in transcripts[0].read_text(), "a SOURCE transcript was string-edited"


def test_sibling_encoded_dir_owned_by_another_project_is_never_renamed(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F4: `/x/widget-two` encodes exactly like `/x/widget/two`; a dir the catalog proves
    belongs to another project is never re-namespaced, even with --claim-ambiguous."""
    world = World(ccw_env, tmp_path)
    world.capture(world.sibling, "33333333-2222-3333-4444-555555555555")
    sibling_dir = world.encoded_dir(world.sibling)
    assert world.apply("--claim-ambiguous").code == 0
    assert sibling_dir.is_dir(), "another project's encoded dir was renamed"


def test_real_subdir_encoded_dir_is_renamed_even_when_uncaptured(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A candidate is proven to belong to the repo when a REAL subdirectory encodes to
    its exact name; forward encoding is exact where decoding would be guesswork."""
    world = World(ccw_env, tmp_path)
    stale = world.encoded_dir(world.sub)  # never captured, but <repo>/sub exists
    stale.mkdir(parents=True)
    assert world.apply().code == 0
    assert not stale.exists()
    assert (claude_projects(ccw_env) / (encode(world.new_repo) + "-sub")).is_dir()


def test_unproven_encoded_dir_is_skipped_and_named_by_default(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """No catalog record and no matching subdirectory means no proof: skipped and NAMED
    rather than re-namespaced onto the relocated project (R5/F7)."""
    world = World(ccw_env, tmp_path)
    ghost = claude_projects(ccw_env) / (encode(world.repo) + "-ghost")
    ghost.mkdir(parents=True)
    result = world.apply()
    assert result.code == 0
    assert ghost.is_dir(), "an unproven encoded dir was renamed by default"
    assert "ghost" in result.out + result.err, "the skipped dir was not named"


def test_claim_ambiguous_takes_the_unproven_encoded_dir(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The operator can opt in to claiming unproven candidates; it stays opt-in."""
    world = World(ccw_env, tmp_path)
    ghost = claude_projects(ccw_env) / (encode(world.repo) + "-ghost")
    ghost.mkdir(parents=True)
    assert world.apply("--claim-ambiguous").code == 0
    assert not ghost.exists(), "--claim-ambiguous did not take the unproven dir"
    assert (claude_projects(ccw_env) / (encode(world.new_repo) + "-ghost")).is_dir()


def test_relative_source_never_becomes_a_bare_word_pattern(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F9: the rewrite pattern is the absolute path, so the bare word survives."""
    world = World(ccw_env, tmp_path)
    assert world.apply().code == 0
    assert "the widget word alone must survive" in world.memory_md.read_text()


def test_dotted_sibling_directory_is_not_over_rewritten(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F4: `.` is a name char for the boundary guard, so `widget.bak` is a different
    directory and must be left exactly as it is."""
    world = World(ccw_env, tmp_path)
    assert world.apply().code == 0
    text = world.memory_md.read_text()
    assert str(world.bak) in text, "the .bak sibling path was rewritten"
    assert str(world.sibling) in text, "the -two sibling path was rewritten"
    assert str(world.new_repo) in text, "the repo path itself was not rewritten"


def test_symlinked_memory_file_is_never_written_through(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R4/F9: replacing a symlink with a regular file destroys the link and leaves the
    real file stale; the link is reported as unrepaired instead."""
    world = World(ccw_env, tmp_path)
    real = tmp_path / "outside.md"
    real.write_text(f"outside ref {world.repo}\n")
    link = world.inventory / "linked.md"
    link.symlink_to(real)
    result = world.apply()
    assert result.code == 0
    assert link.is_symlink(), "the symlink was replaced by a regular file"
    assert str(world.repo) in real.read_text(), "the symlink target was rewritten"
    assert "linked.md" in result.out + result.err, "the skipped symlink was not named"


def test_symlinked_source_is_refused_untouched(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """R5/F7: renaming a symlink moves the link, not the repo; refuse instead."""
    world = World(ccw_env, tmp_path)
    link = Path(ccw_env["HOME"]) / "projects" / "widget-link"
    link.symlink_to(world.repo)
    before = tree_snapshot(world.inventory)
    result = run_ccw(
        ["relocate", str(link), "--to", str(world.new_repo), "--apply", "--yes"], ccw_env
    )
    assert result.code != 0
    assert world.repo.is_dir() and not world.new_repo.exists()
    assert tree_snapshot(world.inventory) == before


def test_target_nested_in_source_is_refused_untouched(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R5/F7: os.rename of a directory into itself is EINVAL; refuse before rewriting."""
    world = World(ccw_env, tmp_path)
    before = tree_snapshot(world.inventory)
    result = run_ccw(
        ["relocate", str(world.repo), "--to", str(world.repo / "moved"), "--apply", "--yes"],
        ccw_env,
    )
    assert result.code != 0
    assert tree_snapshot(world.inventory) == before, "a nested target rewrote content anyway"


def test_malformed_config_refuses_rather_than_meaning_no_roots(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R5/F7: a typo must never masquerade as 'nothing to rewrite' while the containers
    are renamed anyway, which would report success over a half-repaired world."""
    world = World(ccw_env, tmp_path)
    (world.root / "config.toml").write_text("[relocate]\nroots = this is not toml\n")
    before = tree_snapshot(claude_projects(ccw_env))
    result = world.apply()
    assert result.code != 0
    assert world.repo.is_dir() and not world.new_repo.exists()
    assert tree_snapshot(claude_projects(ccw_env)) == before


def test_to_operand_is_never_taken_as_the_positional_repo(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F6: consent must be collected for the operation the user actually named."""
    world = World(ccw_env, tmp_path)
    result = run_ccw(
        ["relocate", "--to", str(world.new_repo), str(world.repo)], ccw_env
    )
    assert result.code == 0, result.err
    assert f"{world.repo} -> {world.new_repo}" in result.out


def test_content_failure_reports_and_halts_container_renames(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F7 + DESIGN 11: an unwritable inventory is named and nothing is moved."""
    world = World(ccw_env, tmp_path)
    world.inventory.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        result = world.apply()
        assert result.code != 0
        assert world.memory_md.name in result.out + result.err
        assert world.encoded_dir(world.repo).is_dir()
        assert world.repo.is_dir() and not world.new_repo.exists()
    finally:
        world.inventory.chmod(stat.S_IRWXU)


def test_subdir_proof_does_not_rename_a_contested_sibling(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F4: `<repo>/two` and `<repo>-two` encode IDENTICALLY, so a matching subdirectory
    is not by itself proof of ownership; a real sibling of the same encoded name makes
    the candidate contested and it must be left alone."""
    world = World(ccw_env, tmp_path)
    (world.repo / "two").mkdir()  # a real subdir: encodes the same as the sibling below
    assert world.sibling.is_dir()  # <repo>-two exists as an unrelated real directory
    contested = claude_projects(ccw_env) / (encode(world.repo) + "-two")
    contested.mkdir(parents=True)
    result = world.apply()
    assert result.code == 0
    assert contested.is_dir(), "a contested encoded dir was renamed on a subdir match"
    assert "two" in result.out + result.err


def test_every_cwd_claim_is_returned_for_an_encoded_dir(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F4: alias claims are append-only (R4), so a project that has been relocated keeps
    its previous cwd row. Attribution must see EVERY claim; returning one arbitrary row
    hands back a stale path and mislabels the project that owns the encoded dir, which
    makes a legitimately owned dir permanently unrenameable."""
    from cc_warehouse import catalog, registry

    root = warehouse_root(ccw_env)
    root.mkdir(parents=True, exist_ok=True)
    conn = catalog.open_catalog(root)
    try:
        resolved = registry.resolve_project(
            conn, cwd="/x/widget", encoded_dir="-x-widget", now="2026-01-05T10:00:00Z"
        )
        registry.move_project(
            conn, resolved.project_id, "/x/widget", "/x/new", "2026-01-05T11:00:00Z"
        )
        claims = registry.cwds_for_encoded_dir(conn, "-x-widget")
    finally:
        conn.close()
    assert set(claims) == {"/x/widget", "/x/new"}, "attribution saw only one arbitrary cwd row"


def test_json_path_keys_are_rewritten_and_do_not_fake_a_failure(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F6: real config is keyed BY absolute path. Leaving keys stale both fails to repair
    the field that resolves a project and makes verify report a failure on a run that
    actually completed."""
    world = World(ccw_env, tmp_path)
    keyed = world.inventory / "claude-ish.json"
    keyed.write_text(json.dumps({"projects": {str(world.repo): {"note": "hi"}}}))
    result = world.apply()
    assert result.code == 0, result.err
    data = cast(dict[str, object], json.loads(keyed.read_text()))
    projects = cast(dict[str, object], data["projects"])
    assert str(world.new_repo) in projects, "the path-shaped JSON KEY was not rewritten"
    assert str(world.repo) not in projects


def test_a_root_containing_the_repo_does_not_manufacture_failures(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """DESIGN 11 VERIFY: files under the repo move WITH it, so verification must follow
    them; reading the pre-move path would report failure on a successful run."""
    home = Path(ccw_env["HOME"])
    world = World(ccw_env, tmp_path, roots=[str(home / "projects")])
    inside = world.repo / "NOTES.md"
    inside.write_text(f"this repo lives at {world.repo}\n")
    result = world.apply()
    assert result.code == 0, f"verify manufactured a failure: {result.err}"
    moved = world.new_repo / "NOTES.md"
    assert moved.exists() and str(world.new_repo) in moved.read_text()


def test_reference_to_a_renamed_encoded_dir_is_rewritten(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F4/F6: the run must not create its own dangling references - a memory file naming
    an encoded dir this run renames is updated to the new encoded name."""
    world = World(ccw_env, tmp_path)
    world.capture(world.sub, "55555555-2222-3333-4444-555555555555")
    ref = world.inventory / "encoded-ref.md"
    ref.write_text(f"memory at ~/.claude/projects/{encode(world.sub)}/memory/MEMORY.md\n")
    assert world.apply().code == 0
    text = ref.read_text()
    expected = encode(world.new_repo) + "-sub"
    assert expected in text, "a reference to a dir this run renamed was left dangling"
    assert encode(world.sub) not in text


def test_stored_objects_survive_a_symlinked_warehouse_root(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """12a-1 (R4/F9): the warehouse exclusion must compare RESOLVED paths.

    `CCW_ROOT` pointing at a symlink is ordinary (an external disk, a dotfile-managed
    data dir). The scan reaches the object by its real path, so an exclusion that holds
    the symlink path never matches it, and an immutable object gets string-edited. An
    object that stopped hashing to its own name is indistinguishable from rot.
    """
    real_root = tmp_path / "real-warehouse"
    real_root.mkdir()
    Path(ccw_env["CCW_ROOT"]).symlink_to(real_root)
    world = World(ccw_env, tmp_path, roots=[str(tmp_path)])
    digest = hashlib.sha256(world.payload).hexdigest()
    obj = real_root / "objects" / digest[:2] / f"{digest}.jsonl"
    assert obj.exists(), "the capture did not land where the symlink resolves"
    result = world.apply()
    # The rule first, the exit code second: a run that violates R4 and THEN fails for an
    # unrelated reason must still fail on the violation, not on the symptom.
    assert hashlib.sha256(obj.read_bytes()).hexdigest() == digest, (
        "a stored object was rewritten through a symlinked warehouse root"
    )
    assert str(real_root) not in result.err, "the warehouse subtree was touched at all"
    assert result.code == 0, result.err
    assert run_ccw(["verify"], ccw_env).code == 0, "verify no longer clean after relocate"


def test_source_transcripts_survive_a_symlinked_claude_dir(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """12a-1 (SPEC 10.2 / R4): the source-transcript exclusion must compare RESOLVED paths.

    A dotfile-managed `~/.claude` is a symlink on a great many real accounts. The walk
    enumerates the transcript by its real path, so an exclusion holding
    `~/.claude/projects` never matches, and relocate string-edits a captured transcript:
    the exact locked-rule violation the slice-12 escalation caught.
    """
    home = Path(ccw_env["HOME"])
    real_claude = home / "dotfiles-claude"
    shutil.move(str(home / ".claude"), str(real_claude))
    (home / ".claude").symlink_to(real_claude)
    world = World(ccw_env, tmp_path, roots=[str(home)])
    result = world.apply()
    # The rule first, the exit code second (see the sibling test): with the bug the run
    # rewrites the transcript and only THEN fails, because the file it rewrote moved.
    assert "rewritten: " + str(real_claude) not in result.err, (
        "a SOURCE transcript was string-edited through a symlinked ~/.claude"
    )
    moved = real_claude / "projects" / encode(world.new_repo)
    transcripts = list(moved.rglob("*.jsonl"))
    assert transcripts, "the encoded dir should have been renamed, carrying its transcripts"
    assert str(world.repo) in transcripts[0].read_text(), (
        "a SOURCE transcript was string-edited through a symlinked ~/.claude"
    )
    assert result.code == 0, result.err


def test_registry_gains_both_the_cwd_and_encoded_claims(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F4: a project first captured without a cwd must not resolve to a stale encoded
    alias after the move, so the encoded form of the new path is claimed too."""
    from conftest import catalog_rows

    world = World(ccw_env, tmp_path)
    assert world.apply().code == 0
    paths = {
        cast(tuple[str], row)[0]
        for row in cast(
            list[tuple[object, ...]], catalog_rows(ccw_env, "SELECT path FROM project_alias")
        )
    }
    assert str(world.new_repo) in paths
    assert encode(world.new_repo) in paths
