"""Oracle tests for the external-store locator (ticket 39, slice 39b).

WHAT THIS IS FOR. Ticket 38 archived what sits INSIDE a session's directory.
This covers the stores that sit BESIDE `projects/`, keyed by session id rather
than by location: `~/.claude/file-history/<uuid>/` and `~/.claude/todos/`.

MEASURED 2026-09-08 on the live tree, and it corrects the plan on two points:

  file-history   1,056 directories, 929,845,225 bytes. ALL 1,056 are bare session
                 uuids - the plan expected about 5% not to be, and today none are
                 (control: the same regex matched 1,056 of 1,056). They are FLAT,
                 no nesting, holding `<hash>@vN` snapshots. 1,014 match a session
                 the archive already holds; 42 do not.
  todos          3 files, 2 bytes each, named `<uuid>-agent-<uuid>.json`. The plan
                 called this "trivial, rides along free" and that is generous: it
                 is six bytes of empty JSON arrays from June. It is archived anyway,
                 because a KNOWN store with no copier is the exact "parses, is
                 tested, does nothing" shape ticket 38's fence exists to forbid.

THE BYTES ARE NOT IN THE TRANSCRIPT, sampled independently of the plan's own
check: 23 snapshots from 12 sessions, first 200 bytes each, found in the session's
own JSONL 0 times. So this is the only copy.

Contract: DESIGN 14 R1/R9, FINDINGS F4 (a name is a filter, never an identity),
F5 (a locator opens no file); ticket 39's constraint that `~/.claude` is read-only.
"""

import ast
from pathlib import Path

from cc_warehouse import external
from conftest import SRC_ROOT, record_opens

UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
UUID_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"


def claude_home(tmp_path: Path) -> Path:
    home = tmp_path / ".claude"
    (home / "file-history").mkdir(parents=True, exist_ok=True)
    (home / "todos").mkdir(parents=True, exist_ok=True)
    return home


def plant_history(home: Path, uuid: str, *names: str) -> Path:
    where = home / "file-history" / uuid
    where.mkdir(parents=True, exist_ok=True)
    for name in names or ("23527e7c@v1",):
        (where / name).write_bytes(f"snapshot {name}\n".encode())
    return where


def plant_todo(home: Path, uuid: str) -> Path:
    path = home / "todos" / f"{uuid}-agent-{uuid}.json"
    path.write_bytes(b"[]")
    return path


# ---------------------------------------------------------------------------
# The list of stores, and the fence around it
# ---------------------------------------------------------------------------


def test_the_two_session_keyed_stores_are_the_ones_measured() -> None:
    """The product decision, asserted rather than left implicit. `paste-cache/`
    is deliberately absent: it is reachable only by joining through
    `history.jsonl`, which is slice 39e's job, not this one's."""
    assert external.SESSION_STORES == frozenset({"file-history", "todos"})


def test_the_module_imports_no_peer_so_everything_can_share_it() -> None:
    """Same argument as `sidecars.py`: `archive`, `capture` and `sweep` all need
    this answer, so a module that imported any of them could not be imported by
    all of them (R9)."""
    tree = ast.parse((SRC_ROOT / "external.py").read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("cc_warehouse"):
            imported.append(node.module or "")
        if isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names if a.name.startswith("cc_warehouse"))
    assert not imported, f"external.py must stay a leaf module, imports: {imported}"


def test_the_module_never_calls_the_jsonl_walker() -> None:
    """THE KNOWN TRAP, from the plan's own section of that name. `import_tree.py`
    walks `*.jsonl` via `migrate.walk_jsonl`; pointed anywhere near `~/.claude` it
    swallows `history.jsonl`, fails `is_session`, and dumps 18,295 prompts into
    `_not-sessions/imported/` as one unattributable blob. A fence, because the
    mistake is one import away and its damage is silent."""
    text = (SRC_ROOT / "external.py").read_text(encoding="utf-8")
    assert "walk_jsonl" not in text


# ---------------------------------------------------------------------------
# Per-session lookup: what the capture hook needs
# ---------------------------------------------------------------------------


def test_a_sessions_file_history_dir_is_found_by_its_uuid(tmp_path: Path) -> None:
    home = claude_home(tmp_path)
    planted = plant_history(home, UUID_A)
    assert external.file_history_dir(home, UUID_A) == planted


def test_a_session_with_no_file_history_finds_nothing(tmp_path: Path) -> None:
    assert external.file_history_dir(claude_home(tmp_path), UUID_A) is None


def test_a_session_with_no_uuid_finds_nothing(tmp_path: Path) -> None:
    """A payload whose content carries no session id cannot be joined to anything
    here, and must not fall back to a path (F4)."""
    home = claude_home(tmp_path)
    plant_history(home, UUID_A)
    assert external.file_history_dir(home, None) is None


def test_a_sessions_todo_files_are_found_by_their_uuid_prefix(tmp_path: Path) -> None:
    home = claude_home(tmp_path)
    planted = plant_todo(home, UUID_A)
    plant_todo(home, UUID_B)
    assert external.todo_files(home, UUID_A) == (planted,)


def test_a_lookup_opens_no_file(tmp_path: Path) -> None:
    """F5. This runs on the capture hook's critical path. Directory entries
    answer the question; reading anything here would be a cost paid on every
    session end to learn nothing extra."""
    home = claude_home(tmp_path)
    plant_history(home, UUID_A, "23527e7c@v1", "23527e7c@v2")
    plant_todo(home, UUID_A)
    with record_opens(home) as opened:
        external.file_history_dir(home, UUID_A)
        external.todo_files(home, UUID_A)
    assert opened == []


def test_an_unreadable_store_yields_nothing_rather_than_raising(tmp_path: Path) -> None:
    """DESIGN 12: a locator must never be the thing that fails a capture."""
    home = claude_home(tmp_path)
    (home / "todos").chmod(0o000)
    try:
        assert external.todo_files(home, UUID_A) == ()
    finally:
        (home / "todos").chmod(0o700)


def test_a_missing_claude_home_is_not_an_error(tmp_path: Path) -> None:
    absent = tmp_path / "nothing-here"
    assert external.file_history_dir(absent, UUID_A) is None
    assert external.todo_files(absent, UUID_A) == ()


# ---------------------------------------------------------------------------
# Bulk maps: what the sweep needs, and the stranded question only they can answer
# ---------------------------------------------------------------------------


def test_the_bulk_map_lists_every_session_keyed_file_history_dir(tmp_path: Path) -> None:
    """ONE scandir for the whole store, not one stat per catalogued session. The
    plan asked for catalog-driven discovery to keep a directory NAME from becoming
    an identity (F4). Scanning first and joining second reaches the same join from
    the other end: the name is still only a filter, and what decides where bytes
    land is the archive folder that uuid resolves to."""
    home = claude_home(tmp_path)
    a = plant_history(home, UUID_A)
    b = plant_history(home, UUID_B)
    assert external.file_history_by_session(home) == {UUID_A: a, UUID_B: b}


def test_a_non_uuid_directory_is_reported_as_an_anomaly_not_silently_skipped(
    tmp_path: Path,
) -> None:
    """The plan's own risk table requires this, and it is the reason the bulk map
    exists at all: iterating the CATALOG and stat-ing each uuid can only ever find
    directories it already knows about, so a stranger is invisible to it by
    construction. Scanning the store finds it."""
    home = claude_home(tmp_path)
    plant_history(home, UUID_A)
    (home / "file-history" / "not-a-session-id").mkdir()
    assert external.unknown_children(home, "file-history") == ("not-a-session-id",)


def test_ds_store_is_not_an_anomaly(tmp_path: Path) -> None:
    """One exists in the live `file-history/` right now. Finder writes them into
    any folder a human browses, and flagging it would be permanent noise."""
    home = claude_home(tmp_path)
    (home / "file-history" / ".DS_Store").write_bytes(b"\x00")
    assert external.unknown_children(home, "file-history") == ()


def test_a_file_history_dir_whose_session_is_not_archived_is_named(tmp_path: Path) -> None:
    """42 of the live 1,056 are in this state. They must be reported and landed
    somewhere, never dropped and never used to invent a session folder (F4)."""
    home = claude_home(tmp_path)
    plant_history(home, UUID_A)
    plant_history(home, UUID_B)
    stranded = external.stranded_file_history(home, {UUID_A})
    assert [p.name for p in stranded] == [UUID_B]


def test_the_bulk_todo_map_groups_files_by_their_session(tmp_path: Path) -> None:
    home = claude_home(tmp_path)
    a = plant_todo(home, UUID_A)
    b = plant_todo(home, UUID_B)
    assert external.todos_by_session(home) == {UUID_A: (a,), UUID_B: (b,)}


def test_a_todo_file_with_no_uuid_prefix_is_an_anomaly(tmp_path: Path) -> None:
    home = claude_home(tmp_path)
    plant_todo(home, UUID_A)
    (home / "todos" / "leftover.json").write_bytes(b"[]")
    assert external.unknown_children(home, "todos") == ("leftover.json",)


def test_the_bulk_maps_open_no_file(tmp_path: Path) -> None:
    home = claude_home(tmp_path)
    plant_history(home, UUID_A, "23527e7c@v1")
    plant_todo(home, UUID_A)
    with record_opens(home) as opened:
        external.file_history_by_session(home)
        external.todos_by_session(home)
        external.unknown_children(home, "file-history")
    assert opened == []
