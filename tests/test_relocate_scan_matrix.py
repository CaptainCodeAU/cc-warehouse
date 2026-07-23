"""Filesystem-shape matrix for relocate's content scan (ticket 12b findings 3/4/6).

Contract-derived from DESIGN section 11 (the scan scope), FINDINGS F5 (no full-corpus
work to answer a small question), F7/R5 (errors take the conservative branch and are
reported), R10 (batch operations name every item) and F6/R8 (prose must not promise more
than the code enforces).

WHY A MATRIX. `_scan_content` claimed in its own docstring that it "never silently drops a
file it cannot handle". A census of fifteen shapes found EIGHT dropped with no mention at
all: files under a symlinked directory, files under `.git`, files under an excluded tree,
FIFOs and sockets, files under a directory it could not read, and every file under a
configured root that does not exist. Each of those is a file the operator believes was
repaired. Enumerating the shapes is the only way to know which are covered.

THE POLICY THIS PINS. Every path the scan declines is NAMED, exactly once, with a reason.
Pruning happens at DIRECTORY level, so an excluded subtree is never descended and its
files are never even opened - which is also what makes the scan cheap (one resolve per
directory rather than one per file). A configured root that does not exist is a NAMED skip
and the run proceeds (principal ruling 2026-07-24): the operator sees it before consenting,
because the apply path prints the plan, and one config.toml shared across machines may
legitimately name a root that is absent here.

Nothing blocking is ever opened: a FIFO is classified by stat, never by reading it (the
slice-10 trap).
"""

import os
import re
import socket
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from conftest import CliResult, record_opens, run_ccw, run_cli

REF_TEMPLATE = "see <P>\n"


@dataclass(frozen=True)
class ScanWorld:
    tmp: Path
    env: dict[str, str]
    repo: Path
    new_repo: Path
    inventory: Path
    warehouse: Path
    projects: Path
    dry: CliResult
    applied: CliResult
    before: dict[str, bytes]
    shapes: dict[str, Path]


def _plan_details(out: str) -> dict[str, str]:
    """Parse `  <kind>: <path>: <detail>` plan lines into {path: detail}."""
    found: dict[str, str] = {}
    for line in out.splitlines():
        match = re.match(r"^  (\w+): (.+?): (.*)$", line)
        if match:
            found[match.group(2)] = match.group(3)
    return found


@pytest.fixture(scope="module")
def scan(tmp_path_factory: pytest.TempPathFactory):
    tmp = tmp_path_factory.mktemp("scan-matrix")
    home = tmp / "home"
    projects = home / ".claude" / "projects"
    projects.mkdir(parents=True)
    warehouse = tmp / "warehouse"
    (warehouse / "objects" / "aa").mkdir(parents=True)
    repo = home / "CODE" / "widget"
    repo.mkdir(parents=True)
    new_repo = home / "CODE" / "gadget"
    inv = tmp / "inventory"
    inv.mkdir()
    (warehouse / "config.toml").write_text(f'[relocate]\nroots = ["{inv}"]\n')
    ref = REF_TEMPLATE.replace("<P>", str(repo))

    shapes: dict[str, Path] = {}

    # E01-E03 ordinary
    shapes["plain"] = inv / "plain.md"
    shapes["plain"].write_text(ref)
    shapes["nomatch"] = inv / "nomatch.md"
    shapes["nomatch"].write_text("nothing here\n")
    (inv / "sub").mkdir()
    shapes["nested"] = inv / "sub" / "nested.md"
    shapes["nested"].write_text(ref)

    # E04-E06 symlinks
    outside = tmp / "outside.md"
    outside.write_text(ref)
    shapes["symlinked_file"] = inv / "link.md"
    shapes["symlinked_file"].symlink_to(outside)
    shapes["dangling"] = inv / "dangling.md"
    shapes["dangling"].symlink_to(tmp / "nowhere")
    linked_real = tmp / "linked-real"
    linked_real.mkdir()
    (linked_real / "inside.md").write_text(ref)
    shapes["symlinked_dir"] = inv / "linked-dir"
    shapes["symlinked_dir"].symlink_to(linked_real)

    # E07-E09 excluded trees, reached through symlinks
    gitdir = inv / ".git"
    gitdir.mkdir()
    shapes["git_file"] = gitdir / "config"
    shapes["git_file"].write_text(ref)
    shapes["warehouse_link"] = inv / "warehouse-link"
    shapes["warehouse_link"].symlink_to(warehouse)
    shapes["stored_object"] = warehouse / "objects" / "aa" / "deadbeef.jsonl"
    shapes["stored_object"].write_text(ref)
    shapes["projects_link"] = inv / "projects-link"
    shapes["projects_link"].symlink_to(projects)
    (projects / "encoded-dir").mkdir()
    shapes["transcript"] = projects / "encoded-dir" / "sess.jsonl"
    shapes["transcript"].write_text(ref)

    # E10-E11 non-regular files
    shapes["fifo"] = inv / "pipe.md"
    os.mkfifo(shapes["fifo"])
    shapes["socket"] = inv / "sock.md"
    # AF_UNIX paths are capped near 104 bytes and pytest's tmp paths are longer than
    # that, so bind somewhere short and rename the socket inode into place.
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    short = Path(tempfile.mkdtemp(dir="/tmp"))  # noqa: S108 - required by the AF_UNIX limit
    srv.bind(str(short / "s"))
    os.rename(short / "s", shapes["socket"])

    # E12-E13 permissions
    shapes["noread_file"] = inv / "noread.md"
    shapes["noread_file"].write_text(ref)
    shapes["noread_file"].chmod(0)
    shapes["noread_dir"] = inv / "noread-dir"
    shapes["noread_dir"].mkdir()
    (shapes["noread_dir"] / "hidden.md").write_text(ref)
    shapes["noread_dir"].chmod(0)

    # E14 oversized
    shapes["oversized"] = inv / "big.md"
    shapes["oversized"].write_bytes(b"x" * (8 * 1024 * 1024 + 10) + ref.encode())

    # E20 hardlink to a stored object
    shapes["hardlink"] = inv / "hardlink.jsonl"
    os.link(shapes["stored_object"], shapes["hardlink"])

    env = {"HOME": str(home), "USER": "alice", "PATH": "", "CCW_ROOT": str(warehouse)}
    before = {
        name: p.read_bytes()
        for name, p in shapes.items()
        if name in ("stored_object", "transcript", "git_file")
    }
    args = ["relocate", str(repo), "--to", str(new_repo)]
    dry = run_ccw(args, env)
    applied = run_ccw([*args, "--apply", "--yes"], env)

    yield ScanWorld(
        tmp, env, repo, new_repo, inv, warehouse, projects, dry, applied, before, shapes
    )

    shapes["noread_dir"].chmod(stat.S_IRWXU)
    shapes["noread_file"].chmod(stat.S_IRUSR | stat.S_IWUSR)
    srv.close()


# ------------------------------------------------------------------ E01-E03 ordinary


def test_e01_a_plain_matching_file_is_a_target(scan: ScanWorld) -> None:
    assert str(scan.shapes["plain"]) in _plan_details(scan.dry.out)
    assert str(scan.new_repo).encode() in scan.shapes["plain"].read_bytes()


def test_e02_a_file_with_no_match_is_neither_target_nor_noise(scan: ScanWorld) -> None:
    """Not every unlisted file is a silent drop: a file with nothing to repair is
    correctly absent from the plan, and reporting it would bury the real entries."""
    assert str(scan.shapes["nomatch"]) not in _plan_details(scan.dry.out)


def test_e03_a_file_in_a_nested_directory_is_a_target(scan: ScanWorld) -> None:
    assert str(scan.new_repo).encode() in scan.shapes["nested"].read_bytes()


# ------------------------------------------------------------------ E04-E06 symlinks


@pytest.mark.parametrize("shape", ["symlinked_file", "dangling"])
def test_e04_e05_symlinked_files_are_named(shape: str, scan: ScanWorld) -> None:
    detail = _plan_details(scan.dry.out).get(str(scan.shapes[shape]), "")
    assert "SKIPPED" in detail, f"{shape} was not named in the plan"


def test_e06_a_file_under_a_symlinked_directory_is_named_not_dropped(scan: ScanWorld) -> None:
    """A symlinked directory is not descended (correctly: it can leave the root, and
    could be a cycle). The operator must still learn the subtree went unrepaired."""
    details = _plan_details(scan.dry.out)
    assert str(scan.shapes["symlinked_dir"]) in details, "the symlinked directory was dropped"
    assert "SKIPPED" in details[str(scan.shapes["symlinked_dir"])]


# ------------------------------------------------------------------ E07-E09 exclusions


def test_e07_dot_git_is_named_not_dropped(scan: ScanWorld) -> None:
    details = _plan_details(scan.dry.out)
    assert str(scan.inventory / ".git") in details, ".git was excluded with no mention"


def test_e08_the_warehouse_is_named_and_never_rewritten(scan: ScanWorld) -> None:
    """R4/F9: a stored object must not be touched, AND the operator must be told the
    warehouse subtree was skipped rather than left to assume it was covered."""
    details = _plan_details(scan.dry.out)
    assert str(scan.shapes["warehouse_link"]) in details, "the warehouse link was dropped"
    assert scan.shapes["stored_object"].read_bytes() == scan.before["stored_object"]


def test_e09_captured_transcripts_are_named_and_never_rewritten(scan: ScanWorld) -> None:
    details = _plan_details(scan.dry.out)
    assert str(scan.shapes["projects_link"]) in details, "the projects link was dropped"
    assert scan.shapes["transcript"].read_bytes() == scan.before["transcript"]


# ------------------------------------------------------- E10-E11 non-regular files


@pytest.mark.parametrize("shape", ["fifo", "socket"])
def test_e10_e11_non_regular_files_are_named_and_never_opened(
    shape: str, scan: ScanWorld
) -> None:
    """R10: a FIFO named *.md is not a file we can repair, and reading one would block
    forever (the slice-10 trap). It is classified by stat and reported, never opened."""
    details = _plan_details(scan.dry.out)
    assert str(scan.shapes[shape]) in details, f"a {shape} was dropped with no mention"


# ------------------------------------------------------------- E12-E13 permissions


def test_e12_an_unreadable_file_is_named(scan: ScanWorld) -> None:
    detail = _plan_details(scan.dry.out).get(str(scan.shapes["noread_file"]), "")
    assert "SKIPPED" in detail


def test_e13_an_unreadable_directory_is_named(scan: ScanWorld) -> None:
    """F7/R5, the slice-05 lesson: a directory the walk cannot list is an under-capture.
    Silently returning fewer files reports a clean sweep over an incomplete one."""
    details = _plan_details(scan.dry.out)
    assert str(scan.shapes["noread_dir"]) in details, "an unreadable directory was swallowed"


# ------------------------------------------------------------------------ E14 size


def test_e14_an_oversized_file_is_named(scan: ScanWorld) -> None:
    detail = _plan_details(scan.dry.out).get(str(scan.shapes["oversized"]), "")
    assert "too large" in detail


# -------------------------------------------------------------------- E20 hardlink


def test_e20_a_hardlink_to_a_stored_object_leaves_the_object_intact(scan: ScanWorld) -> None:
    """R2 is load-bearing for R4 here, which is worth pinning explicitly.

    A hardlink to a stored object inside a root has a different PATH, so the path-based
    exclusion cannot see it, and the link is rewritten. The stored object survives only
    because atomic_write writes a temp file and renames it over the target, breaking the
    link instead of writing through it. Anyone who ever changed atomic_write to write in
    place would turn this into silent store corruption; this test is the tripwire.
    """
    assert scan.shapes["stored_object"].read_bytes() == scan.before["stored_object"]
    assert str(scan.new_repo).encode() in scan.shapes["hardlink"].read_bytes()


# --------------------------------------------------- E15-E19, E21-E22 root handling


def _mini(tmp_path: Path, roots: list[str]) -> tuple[dict[str, str], Path, Path, Path]:
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    warehouse = tmp_path / "warehouse"
    warehouse.mkdir()
    repo = home / "CODE" / "widget"
    repo.mkdir(parents=True)
    new_repo = home / "CODE" / "gadget"
    joined = ", ".join(f'"{r}"' for r in roots)
    (warehouse / "config.toml").write_text(f"[relocate]\nroots = [{joined}]\n")
    env = {"HOME": str(home), "USER": "alice", "PATH": "", "CCW_ROOT": str(warehouse)}
    return env, repo, new_repo, warehouse


def test_e15_a_configured_root_that_does_not_exist_is_named(tmp_path: Path) -> None:
    """Principal ruling 2026-07-24: named, and the run proceeds. A typo silently
    repairing nothing is the failure mode; the operator sees this before consenting."""
    missing = tmp_path / "not-here"
    env, repo, new_repo, _ = _mini(tmp_path, [str(missing)])
    result = run_ccw(["relocate", str(repo), "--to", str(new_repo)], env)
    assert result.code == 0, result.err
    assert str(missing) in result.out, "a nonexistent configured root was silently ignored"


def test_e16_a_configured_root_that_is_a_regular_file_is_named(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "a-file"
    not_a_dir.write_text("i am not a directory\n")
    env, repo, new_repo, _ = _mini(tmp_path, [str(not_a_dir)])
    result = run_ccw(["relocate", str(repo), "--to", str(new_repo)], env)
    assert result.code == 0, result.err
    assert str(not_a_dir) in result.out, "a non-directory root was silently ignored"


def test_e17_an_empty_root_is_not_an_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    env, repo, new_repo, _ = _mini(tmp_path, [str(empty)])
    result = run_ccw(["relocate", str(repo), "--to", str(new_repo)], env)
    assert result.code == 0, result.err


def test_e18_nested_roots_do_not_plan_a_file_twice(tmp_path: Path) -> None:
    """A file reachable through two configured roots must be repaired once. Twice means
    two backups of the same path, the second of which is a post-rewrite image."""
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    env, repo, new_repo, _ = _mini(tmp_path, [str(outer), str(inner)])
    target = inner / "m.md"
    target.write_text(REF_TEMPLATE.replace("<P>", str(repo)))
    result = run_ccw(["relocate", str(repo), "--to", str(new_repo)], env)
    assert result.code == 0, result.err
    assert result.out.count(f"memory_file: {target}:") == 1, "the file was planned twice"


def test_e19_a_duplicated_root_does_not_plan_a_file_twice(tmp_path: Path) -> None:
    root_dir = tmp_path / "r"
    root_dir.mkdir()
    env, repo, new_repo, _ = _mini(tmp_path, [str(root_dir), str(root_dir)])
    target = root_dir / "m.md"
    target.write_text(REF_TEMPLATE.replace("<P>", str(repo)))
    result = run_ccw(["relocate", str(repo), "--to", str(new_repo)], env)
    assert result.code == 0, result.err
    assert result.out.count(f"memory_file: {target}:") == 1, "the file was planned twice"


def test_e21_the_plan_order_is_deterministic(tmp_path: Path) -> None:
    """Slice D compares the plan against the point-of-action recompute as ORDERED tuples,
    so a nondeterministic walk order would make every apply refuse as drifted."""
    root_dir = tmp_path / "r"
    (root_dir / "b" / "c").mkdir(parents=True)
    env, repo, new_repo, _ = _mini(tmp_path, [str(root_dir)])
    ref = REF_TEMPLATE.replace("<P>", str(repo))
    for name in ("z.md", "a.md", "m.md"):
        (root_dir / name).write_text(ref)
        (root_dir / "b" / name).write_text(ref)
        (root_dir / "b" / "c" / name).write_text(ref)
    args = ["relocate", str(repo), "--to", str(new_repo)]
    first = run_ccw(args, env)
    second = run_ccw(args, env)
    assert first.code == 0 and second.code == 0
    assert first.out == second.out, "two identical dry runs produced different plans"


def test_e22_a_root_that_is_the_warehouse_rewrites_nothing(tmp_path: Path) -> None:
    env, repo, new_repo, warehouse = _mini(tmp_path, [])
    (warehouse / "config.toml").write_text(f'[relocate]\nroots = ["{warehouse}"]\n')
    (warehouse / "objects" / "aa").mkdir(parents=True)
    obj = warehouse / "objects" / "aa" / "deadbeef.jsonl"
    body = REF_TEMPLATE.replace("<P>", str(repo)).encode()
    obj.write_bytes(body)
    result = run_ccw(["relocate", str(repo), "--to", str(new_repo), "--apply", "--yes"], env)
    assert result.code == 0, result.err
    assert obj.read_bytes() == body, "a stored object was rewritten"


# ------------------------------------------------------------- E23-E24 cost pinning


def test_e23_a_pruned_subtree_is_never_opened(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The cost win, pinned by behaviour rather than by a flaky timing assertion.

    Directory-level pruning is what makes the scan cheap; if it is real, not one file
    under an excluded subtree is ever opened. Uses the same audit-hook machinery the F5
    zero-JSONL-opens oracle test established.
    """
    home = Path(ccw_env["HOME"])
    warehouse = Path(ccw_env["CCW_ROOT"])
    warehouse.mkdir(parents=True, exist_ok=True)
    repo = home / "CODE" / "widget"
    repo.mkdir(parents=True)
    new_repo = home / "CODE" / "gadget"
    inv = tmp_path / "inv"
    inv.mkdir()
    (warehouse / "config.toml").write_text(f'[relocate]\nroots = ["{inv}"]\n')

    ref = REF_TEMPLATE.replace("<P>", str(repo))
    (inv / "keep.md").write_text(ref)
    gitdir = inv / ".git"
    (gitdir / "deep" / "deeper").mkdir(parents=True)
    for i in range(20):
        (gitdir / "deep" / "deeper" / f"obj{i}.md").write_text(ref)

    with record_opens(gitdir) as opened:
        result = run_cli(["relocate", str(repo), "--to", str(new_repo)])
    assert result.code == 0, result.err
    assert opened == [], f"pruning is not real: {len(opened)} files opened under .git"


def test_e24_a_plan_opens_one_catalog_connection_not_one_per_candidate(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F5: the catalog is the read path, and re-opening it per candidate is the
    full-corpus-work-for-a-small-question shape the contract bans."""
    from cc_warehouse import catalog, relocate
    from cc_warehouse.config import load_config

    home = Path(ccw_env["HOME"])
    warehouse = Path(ccw_env["CCW_ROOT"])
    warehouse.mkdir(parents=True, exist_ok=True)
    repo = home / "CODE" / "widget"
    repo.mkdir(parents=True)
    new_repo = home / "CODE" / "gadget"
    (warehouse / "config.toml").write_text("[relocate]\nroots = []\n")
    catalog.open_catalog(warehouse).close()

    encoded = re.sub(r"[/_.]", "-", str(repo))
    projects = home / ".claude" / "projects"
    for i in range(12):
        (projects / f"{encoded}-cand{i:02d}").mkdir(parents=True)

    opened = {"n": 0}
    real_open = catalog.open_catalog

    def counting(*args: object, **kwargs: object):
        opened["n"] += 1
        return real_open(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(catalog, "open_catalog", counting)
    relocate.plan_relocate(load_config(), repo, new_repo)
    assert opened["n"] <= 2, (
        f"one connection per candidate: {opened['n']} opened for 12 candidates"
    )
