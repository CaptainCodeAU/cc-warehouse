"""Oracle tests: relocate never rewrites the archive or the session stores (W-20260929-A102).

THE HOLE. `ccw relocate --apply` string-edits every file under the configured
`[relocate].roots` that names the old path, excluding only the warehouse root
and `~/.claude/projects`. A root that reaches `archive_root`, or `~/.claude`
itself, therefore rewrote archived transcripts (source-class data, R4 as amended)
and the other session stores ccw archives: `history.jsonl`, `file-history/`,
`todos/` and `paste-cache/`. The rule "session data is NEVER mutated by
anything, ever" (CLAUDE.md) and DESIGN 11's "sources are read-only forever".

THE SCOPE KEPT. DESIGN 11 names what relocate edits: memory and inventory files
under the configured roots. Those still are, including ones that live under
`~/.claude` (the control below); only the session stores are declined, and each
decline is NAMED in the plan, as every other exclusion already is (ticket 12b).

Contract: R4, R5, F9, DESIGN 11.
"""

import json
from pathlib import Path

from test_relocate_regressions import World

from conftest import basic_session, mark_archive, run_ccw, warehouse_root

UUID = "0a102000-1111-4222-8333-444444444444"


def _world(ccw_env: dict[str, str], tmp_path: Path) -> tuple[World, Path, dict[str, Path], Path]:
    home = Path(ccw_env["HOME"])
    claude = home / ".claude"
    archive_root = tmp_path / "archive"
    world = World(ccw_env, tmp_path, roots=[str(claude), str(archive_root)])
    mark_archive(archive_root, "UTC")
    root = warehouse_root(ccw_env)
    (root / "config.toml").write_text(
        f'archive_root = "{archive_root}"\narchive_timezone = "UTC"\n'
        f'[relocate]\nroots = ["{claude}", "{archive_root}"]\n'
    )
    mention = f"cwd {world.repo}\n".encode()
    folder = archive_root / "widget" / f"20260105-100000+0000_{UUID}"
    folder.mkdir(parents=True)
    protected = {
        "archived transcript": folder / f"{UUID}.jsonl",
        "archived prompts": folder / "prompts.jsonl",
        "history.jsonl": claude / "history.jsonl",
        "file-history": claude / "file-history" / UUID / "0123abcd@v1",
        "todos": claude / "todos" / f"{UUID}-agent-{UUID}.json",
        "paste-cache": claude / "paste-cache" / "hash0.txt",
    }
    protected["archived transcript"].write_bytes(
        basic_session(cwd=str(world.repo), session_id=UUID)
    )
    for name, path in protected.items():
        if name != "archived transcript":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                json.dumps({"cwd": str(world.repo)}).encode() + b"\n"
                if path.suffix in {".jsonl", ".json"}
                else mention
            )
    control = claude / "MEMORY" / "notes.md"
    control.parent.mkdir(parents=True)
    control.write_bytes(mention)
    return world, archive_root, protected, control


def test_relocate_never_rewrites_the_archive_or_the_session_stores(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    world, _archive_root, protected, control = _world(ccw_env, tmp_path)
    before = {name: path.read_bytes() for name, path in protected.items()}

    result = world.apply()

    changed = [name for name, path in protected.items() if path.read_bytes() != before[name]]
    assert changed == [], f"relocate rewrote session data: {changed}"
    # The control: in-scope content under ~/.claude is still repaired, so the scan
    # really reached these roots and the guard is not simply "skip ~/.claude".
    assert str(world.new_repo) in control.read_text(), result.err
    assert result.code == 0, result.err


def test_every_declined_store_is_named_in_the_plan(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    world, archive_root, protected, _control = _world(ccw_env, tmp_path)

    result = run_ccw(["relocate", str(world.repo), "--to", str(world.new_repo)], ccw_env)

    assert result.code == 0, result.err
    lines = (result.out + result.err).splitlines()
    for path in (
        archive_root,
        protected["history.jsonl"],
        protected["file-history"].parent.parent,
        protected["todos"].parent,
        protected["paste-cache"].parent,
    ):
        named = [line for line in lines if str(path) in line]
        assert named, f"{path} is not in the plan at all"
        assert all("not scanned" in line for line in named), named
