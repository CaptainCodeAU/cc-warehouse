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

Ticket 12b carried-forward findings (added 2026-07-24):

- 12b-1 (R2/F9): the pre-image was produced by `Path.read_text()`, which is BOTH
  locale-dependent AND newline-translating, while the scan had validated the file with an
  explicit `raw.decode("utf-8")`. The backup was then written from that round-tripped
  STRING rather than from the original bytes. Three reproducible symptoms of one defect:
  a CRLF file silently loses every `\\r` (no unusual locale needed); a non-ASCII file under
  a latin-1 locale is written back as mojibake; and under LC_ALL=C relocate refuses to run
  at all on any accented file. In the first two the SAME damage is stored as the backup,
  so there is no recoverable pre-image anywhere, and the run exits 0 reporting success.
  The fix reads bytes, stores bytes, decodes explicitly, and PROVES each backup by
  reading it back before the original is eligible to be touched.
"""

import hashlib
import json
import re
import shutil
import stat
import subprocess
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


def test_home_unset_is_refused_rather_than_running_with_guards_inert(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """12a-2 (R5/F7): HOME unset must REFUSE, not proceed blind.

    Under cron or launchd there is often no HOME. `os.path.expanduser` still finds the
    account's home through `pwd`, so the scan reaches the real tree, but every guard and
    every encoded-dir lookup reads `os.environ["HOME"]` and goes inert: no encoded dir is
    ever renamed, and the source-transcript exclusion protects nothing. Half a relocate is
    worse than none, so the absence of HOME is the conservative branch (F7/F10 in spirit:
    the absence of context is never permission).
    """
    home = Path(ccw_env["HOME"])
    world = World(ccw_env, tmp_path, roots=[str(home)])
    blind = {k: v for k, v in ccw_env.items() if k != "HOME"}
    before_inventory = tree_snapshot(world.inventory)
    before_projects = tree_snapshot(claude_projects(ccw_env))

    dry = run_ccw(["relocate", str(world.repo), "--to", str(world.new_repo)], blind)
    assert dry.code != 0, "a dry-run with HOME unset printed a plan it cannot honour"

    result = run_ccw(
        ["relocate", str(world.repo), "--to", str(world.new_repo), "--apply", "--yes"], blind
    )
    assert result.code != 0, "relocate ran with HOME unset"
    assert "HOME" in result.err, "the refusal does not name the reason"
    assert world.repo.is_dir() and not world.new_repo.exists(), "the repo moved anyway"
    assert tree_snapshot(world.inventory) == before_inventory, "content was rewritten anyway"
    assert tree_snapshot(claude_projects(ccw_env)) == before_projects, "a container moved anyway"

    # The public module API must not slip past the guard either: a caller enumerating a
    # plan with HOME unset has to SEE why it is not honourable, rather than read a short
    # edit list as "not much to do" (R8: home_error's docstring promises exactly this).
    import os

    from cc_warehouse import relocate as relocate_mod
    from cc_warehouse.config import load_config

    saved = os.environ.pop("HOME")
    try:
        blind_plan = relocate_mod.plan_relocate(load_config(), world.repo, world.new_repo)
    finally:
        os.environ["HOME"] = saved
    assert any("HOME is not set" in edit.detail for edit in blind_plan.edits), (
        "plan_relocate returned a plan that cannot be honoured without saying so"
    )


def test_to_parent_that_is_a_regular_file_is_refused_before_any_rewrite(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """12a-3 (R5/F7): pre-flight must PROVE the target parent can become a directory.

    `_existing_parent` walked up until something existed, and a regular file exists, so a
    `--to` under a file passed every pre-flight check. Contents were then rewritten to
    point at a path that could never come into being, and only the rename failed: the
    half-repaired world DESIGN 11 exists to prevent ("it never falls through to a rename
    with un-rewritten contents" has a mirror image, and this is it).
    """
    world = World(ccw_env, tmp_path)
    blocker = Path(ccw_env["HOME"]) / "blocker"
    blocker.write_text("i am a regular file\n")
    before_inventory = tree_snapshot(world.inventory)
    before_projects = tree_snapshot(claude_projects(ccw_env))
    result = run_ccw(
        ["relocate", str(world.repo), "--to", str(blocker / "gadget"), "--apply", "--yes"],
        ccw_env,
    )
    assert result.code != 0
    assert tree_snapshot(world.inventory) == before_inventory, (
        "content was rewritten toward a target that can never exist"
    )
    assert tree_snapshot(claude_projects(ccw_env)) == before_projects
    assert world.repo.is_dir(), "the source repo was moved"
    assert blocker.is_file() and blocker.read_text() == "i am a regular file\n"


def test_to_parent_that_is_a_dangling_symlink_is_refused_before_any_rewrite(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """12a-3 (R5/F7): a dangling symlink is the other shape of an uncreatable parent.

    It reports `exists() == False`, so the walk stepped straight past it to a real
    ancestor and pre-flight approved a parent that `mkdir` cannot create.
    """
    world = World(ccw_env, tmp_path)
    dangling = Path(ccw_env["HOME"]) / "dangling"
    dangling.symlink_to(Path(ccw_env["HOME"]) / "nowhere")
    before_inventory = tree_snapshot(world.inventory)
    result = run_ccw(
        ["relocate", str(world.repo), "--to", str(dangling / "gadget"), "--apply", "--yes"],
        ccw_env,
    )
    assert result.code != 0
    assert tree_snapshot(world.inventory) == before_inventory, (
        "content was rewritten toward an uncreatable target"
    )
    assert world.repo.is_dir(), "the source repo was moved"
    assert dangling.is_symlink() and not dangling.exists()


def test_apply_refuses_when_the_world_drifted_after_planning(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """12a-4 (R13): consent is collected against a PLAN, so apply must honour that plan.

    `apply_relocate` took a RelocatePlan and then ignored `plan.edits` entirely,
    recomputing its own set from the repo paths. Anything that started referencing the old
    path between planning and applying was rewritten without ever having been shown or
    consented to. R13 makes apply-class confirmation explicit; confirmation of a set the
    operator never saw is not confirmation.

    The frozen slice-12 decision keeps a re-check AT THE POINT OF ACTION, so the fix is
    not "trust the stale plan": apply recomputes and REFUSES on any divergence, leaving
    the operator to re-plan and re-consent (R5/F7).
    """
    from cc_warehouse import relocate as relocate_mod
    from cc_warehouse.config import load_config

    world = World(ccw_env, tmp_path)
    config = load_config()
    plan = relocate_mod.plan_relocate(config, world.repo, world.new_repo)
    planned = {str(e.target) for e in plan.edits if e.kind == "memory_file"}
    assert planned, "the fixture should plan at least one content rewrite"

    latecomer = world.inventory / "latecomer.md"
    latecomer.write_text(f"also at {world.repo}\n")
    before_latecomer = latecomer.read_text()
    before_inventory = tree_snapshot(world.inventory)

    report = relocate_mod.apply_relocate(
        config, plan, backup_dir=world.root / "backups" / "drift"
    )
    rewritten = {o.item for o in report.outcomes if o.action == "rewritten"}
    assert not rewritten - planned, "apply rewrote a file the operator never consented to"
    assert latecomer.read_text() == before_latecomer, "an unconsented file was rewritten"
    assert tree_snapshot(world.inventory) == before_inventory, "a drifted world was applied to"
    assert world.repo.is_dir() and not world.new_repo.exists(), "containers moved on a stale plan"
    assert report.failures, "the divergence was not reported"


def test_apply_names_the_edits_it_is_about_to_make(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """12a-4 (R13): the apply path must SHOW what it will change, not just where.

    The consent prompt named only `<repo> -> <new>`. The edit list was printed on the
    dry-run path only, so the run that actually mutates the world was the one that never
    said what it would touch.
    """
    world = World(ccw_env, tmp_path)
    result = world.apply()
    assert result.code == 0, result.err
    shown = result.out + result.err
    assert world.memory_md.name in shown, "the apply run never named the file it rewrote"
    assert str(world.new_repo) in shown


def test_skipped_entries_are_named_but_never_counted_as_changes(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """12a-5 (R10/F6): a SKIPPED entry is something the run refused to touch.

    Both counters treated skips as work: the dry-run's "N edits planned" and the success
    line's "(N changes)" each included every entry the run had explicitly declined to
    repair. That inflates the apparent blast radius before consent and overstates what
    happened after it, which is the guarantee-drift class F6 names. Skips must stay in the
    report, by name (R10), and out of the totals.

    The pin is a BASELINE COMPARISON rather than a hard-coded total: the count is taken
    before the skip exists and must not move when it does. A test asserting the count
    equals some derived expression could agree with the bug.
    """
    world = World(ccw_env, tmp_path)

    def planned(out: str) -> int:
        match = re.search(r"(\d+) edits planned", out)
        assert match, f"no plan count in output: {out}"
        return int(match.group(1))

    dry_args = ["relocate", str(world.repo), "--to", str(world.new_repo)]
    baseline = run_ccw(dry_args, ccw_env)
    assert baseline.code == 0, baseline.err
    before = planned(baseline.out)

    outside = tmp_path / "outside.md"
    outside.write_text(f"outside ref {world.repo}\n")
    (world.inventory / "linked.md").symlink_to(outside)

    with_skip = run_ccw(dry_args, ccw_env)
    assert with_skip.code == 0, with_skip.err
    assert "linked.md" in with_skip.out, "the skipped entry was not named in the plan"
    assert "SKIPPED:" in with_skip.out
    assert planned(with_skip.out) == before, "a SKIPPED entry was counted as a planned edit"

    result = world.apply()
    assert result.code == 0, result.err
    assert "linked.md" in result.out + result.err, "the skipped entry was not named on apply"

    # Enumerate the real changes INDEPENDENTLY, from the filesystem and the catalog, so
    # the expected total comes from observed facts rather than from re-deriving the
    # counter's own arithmetic. The plan count above is deliberately NOT reused: DESIGN 11
    # enumerates external-world REPAIRS, so the repo move is the header, not a plan edit.
    from conftest import catalog_rows

    assert str(world.new_repo) in world.memory_md.read_text()  # 1 rewritten
    assert str(world.new_repo) in world.state_json.read_text()  # 2 rewritten
    assert world.new_repo.is_dir() and not world.repo.exists()  # 3 moved
    assert world.encoded_dir(world.new_repo).is_dir()  # 4 renamed
    assert not world.encoded_dir(world.repo).exists()
    alias_paths = {
        cast(tuple[str], row)[0]
        for row in cast(
            list[tuple[object, ...]], catalog_rows(ccw_env, "SELECT path FROM project_alias")
        )
    }
    assert str(world.new_repo) in alias_paths  # 5 alias
    assert (world.inventory / "linked.md").is_symlink()  # the skip changed nothing

    changed = re.search(r"\((\d+) changes\)", result.out)
    assert changed, f"no change count in output: {result.out}"
    assert int(changed.group(1)) == 5, "a SKIPPED entry was counted as a change"


# --------------------------------------------------------------------------------------
# Ticket 12b finding 1: byte fidelity of the pre-image and the rewrite.
# --------------------------------------------------------------------------------------


def _latin1_locale() -> str | None:
    """A latin-1 locale this machine actually has, or None.

    Rows B and C of the finding need a non-UTF-8 locale to reproduce, which not every
    machine provides. The CRLF row (A) needs no locale at all, so the coverage that pins
    the fix survives even where these skip.
    """
    try:
        out = subprocess.run(
            ["locale", "-a"], capture_output=True, text=True, timeout=10, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for name in out.split():
        if "8859-1" in name:
            return name
    return None


def _backup_of(world: World, name: str) -> Path | None:
    found = sorted((world.root / "backups").rglob(name))
    return found[0] if found else None


def test_crlf_line_endings_survive_a_rewrite(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """12b-1 row A (R2/F9): only the path may change. Nothing else in the bytes.

    `Path.read_text()` translates universal newlines, so every `\\r\\n` in a file authored
    on Windows became `\\n` the moment relocate repaired a path in it. No unusual locale is
    needed; this fires on a default UTF-8 machine, and the run exits 0.
    """
    world = World(ccw_env, tmp_path)
    target = world.inventory / "windows.md"
    original = f"# notes\r\n\r\nproject at {world.repo}\r\ndone\r\n".encode()
    target.write_bytes(original)

    assert world.apply().code == 0
    # The expectation is defined independently: the old path bytes become the new path
    # bytes, and every other byte is untouched.
    expected = original.replace(str(world.repo).encode(), str(world.new_repo).encode())
    assert target.read_bytes() == expected, "a rewrite changed bytes other than the path"


def test_the_backup_is_a_byte_exact_pre_image(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """12b-1 (R2/F9): a backup that is not the original bytes is not a backup.

    The pre-image was a decoded STRING re-encoded to UTF-8, so every transform the decode
    applied was baked into the stored copy. A file damaged by the rewrite was therefore
    damaged identically in its own backup, leaving nothing to restore from.
    """
    world = World(ccw_env, tmp_path)
    target = world.inventory / "windows.md"
    original = f"# notes\r\n\r\nproject at {world.repo}\r\ndone\r\n".encode()
    target.write_bytes(original)

    assert world.apply().code == 0
    backup = _backup_of(world, "windows.md")
    assert backup is not None, "no backup was written for a rewritten file"
    assert backup.read_bytes() == original, "the backup is not a faithful pre-image"


def test_every_rewritten_file_has_a_byte_exact_backup(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """12b-1 / N1: the invariant, across the shapes that break naive text round-trips.

    Nothing may be mutated unless a byte-identical pre-image was stored first, so the
    worst outcome of any future defect here is a refusal rather than a loss.
    """
    world = World(ccw_env, tmp_path)
    shapes: dict[str, bytes] = {
        "crlf.md": f"a\r\nb {world.repo}\r\n".encode(),
        "lone-cr.md": f"a\rb {world.repo}\r".encode(),
        "accents.md": f"café naïve {world.repo}\n".encode(),
        "no-trailing-newline.md": f"{world.repo}".encode(),
        "nul-and-tabs.md": f"a\tb\x0bc {world.repo}\n".encode(),
        "bom.md": "﻿".encode() + f"{world.repo}\n".encode(),
    }
    for name, body in shapes.items():
        (world.inventory / name).write_bytes(body)

    assert world.apply().code == 0
    for name, body in shapes.items():
        backup = _backup_of(world, name)
        assert backup is not None, f"{name}: rewritten with no backup"
        assert backup.read_bytes() == body, f"{name}: backup is not the original bytes"
        expected = body.replace(str(world.repo).encode(), str(world.new_repo).encode())
        got = (world.inventory / name).read_bytes()
        assert got == expected, f"{name}: bytes beyond the path changed"


def test_non_ascii_survives_a_latin1_locale(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """12b-1 row B (R2/F9): the ambient locale must not reach the pre-image.

    A latin-1 codec never fails, so a UTF-8 file read through it silently becomes
    mojibake, which was then written over the user's file AND stored as the backup, with
    the run exiting 0.
    """
    locale_name = _latin1_locale()
    if locale_name is None:
        # A loud skip, not a silent pass: this machine cannot exercise the row at all.
        print("SKIP-LOUD: no latin-1 locale on this machine; row B unexercised here")
        return
    world = World(ccw_env, tmp_path)
    target = world.inventory / "accents.md"
    original = f"# Café notes\nnaïve résumé\nproject at {world.repo}\n".encode()
    target.write_bytes(original)

    env = {**ccw_env, "LC_ALL": locale_name, "LANG": locale_name, "PYTHONUTF8": "0"}
    result = run_ccw(
        ["relocate", str(world.repo), "--to", str(world.new_repo), "--apply", "--yes"], env
    )
    assert result.code == 0, result.err
    expected = original.replace(str(world.repo).encode(), str(world.new_repo).encode())
    assert target.read_bytes() == expected, "a latin-1 locale corrupted the file"
    backup = _backup_of(world, "accents.md")
    assert backup is not None and backup.read_bytes() == original, "the backup was corrupted too"


def test_non_ascii_is_repaired_under_the_c_locale(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """12b-1 row C (R5): LC_ALL=C is normal under cron and launchd.

    An ASCII codec DOES fail, so relocate refused to run at all on any accented file. That
    is safe but wrong: a legitimate repair was blocked by the ambient locale.
    """
    world = World(ccw_env, tmp_path)
    target = world.inventory / "accents.md"
    original = f"# Café notes\nproject at {world.repo}\n".encode()
    target.write_bytes(original)

    env = {**ccw_env, "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0"}
    result = run_ccw(
        ["relocate", str(world.repo), "--to", str(world.new_repo), "--apply", "--yes"], env
    )
    assert result.code == 0, f"the C locale blocked a legitimate repair: {result.err}"
    expected = original.replace(str(world.repo).encode(), str(world.new_repo).encode())
    assert target.read_bytes() == expected


def test_an_undecodable_file_is_a_named_skip_and_the_run_continues(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """12b-1 (R5/R10): a file we cannot decode is reported, never rewritten, never fatal."""
    world = World(ccw_env, tmp_path)
    broken = world.inventory / "binary.md"
    original = b"\xff\xfe\x00garbage " + str(world.repo).encode() + b"\n"
    broken.write_bytes(original)
    good = world.inventory / "fine.md"
    good.write_bytes(f"project at {world.repo}\n".encode())

    result = world.apply()
    assert result.code == 0, result.err
    assert broken.read_bytes() == original, "an undecodable file was rewritten"
    assert "binary.md" in result.out + result.err, "the undecodable file was not named"
    assert str(world.new_repo).encode() in good.read_bytes(), "the batch did not continue"


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
