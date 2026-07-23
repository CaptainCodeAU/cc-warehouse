"""The `ccw project` verb surface (DESIGN section 7).

Written at the v1 EXIT REVIEW, 2026-07-24, which found that DESIGN section 7 specifies
`list / show / rename / move OLD NEW / merge A B` while only `rename` existed. No ticket
had ever enumerated the subcommands, so no ticket was incomplete and no oracle test
demanded them: a green suite proves the code matches the tests, never that the tests
cover the contract.

The gap was not cosmetic. DESIGN section 8 keys per-project config on
`[project.<registry-id>]` and says "`ccw project show` prints the ID to use", so the
per-project override feature shipped in slice 13 had no documented way to discover the ID
it requires. `show` is the load-bearing one; the rest close the contract surface.

`move` and `merge` MUTATE the registry, so they carry the heavier edge-case load here:
every refusal path is asserted to change nothing, and `merge` is asserted to SOFT-retire
(R4: catalog rows are never hard-deleted) rather than remove.
"""

import re
from pathlib import Path
from typing import cast

from conftest import (
    basic_session,
    catalog_rows,
    hook_payload,
    run_ccw,
    write_transcript,
)


def encode(path: str) -> str:
    return re.sub(r"[/_.]", "-", path)


def capture_at(env: dict[str, str], cwd: str, session_id: str) -> None:
    """Create a project by capturing one session at `cwd`."""
    data = basic_session(cwd=cwd, session_id=session_id)
    transcript = write_transcript(env, data, session_id=session_id, encoded_dir=encode(cwd))
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, cwd=cwd, session_id=session_id))
    assert result.code == 0, result.err


def projects(env: dict[str, str]) -> dict[str, tuple[int, int]]:
    """{label: (id, retired)} straight from the catalog, the black-box read path."""
    rows = cast(
        list[tuple[object, ...]],
        catalog_rows(env, "SELECT id, label, retired FROM project"),
    )
    return {cast(str, r[1]): (cast(int, r[0]), cast(int, r[2])) for r in rows}


def alias_owner(env: dict[str, str], path: str, kind: str = "cwd") -> int | None:
    rows = cast(
        list[tuple[object, ...]],
        catalog_rows(
            env, "SELECT project_id FROM project_alias WHERE path = ? AND kind = ?", [path, kind]
        ),
    )
    return cast(int, rows[0][0]) if rows else None


# ----------------------------------------------------------------- dispatch surface


def test_no_subcommand_names_every_subcommand(ccw_env: dict[str, str]) -> None:
    result = run_ccw(["project"], ccw_env)
    assert result.code != 0
    for sub in ("list", "show", "rename", "move", "merge"):
        assert sub in result.err, f"the usage error does not name {sub!r}"


def test_unknown_subcommand_names_every_subcommand(ccw_env: dict[str, str]) -> None:
    result = run_ccw(["project", "frobnicate"], ccw_env)
    assert result.code != 0
    assert "frobnicate" in result.err
    for sub in ("list", "show", "rename", "move", "merge"):
        assert sub in result.err


# --------------------------------------------------------------------------- list


def test_list_on_an_empty_warehouse_is_not_an_error(ccw_env: dict[str, str]) -> None:
    """A fresh warehouse has no projects; that is a valid state, not a failure."""
    result = run_ccw(["project", "list"], ccw_env)
    assert result.code == 0, result.err


def test_list_prints_the_id_and_label_of_every_project(ccw_env: dict[str, str]) -> None:
    capture_at(ccw_env, "/home/alice/code/widget", "11111111-1111-1111-1111-111111111111")
    capture_at(ccw_env, "/home/alice/code/gadget", "22222222-2222-2222-2222-222222222222")
    result = run_ccw(["project", "list"], ccw_env)
    assert result.code == 0, result.err
    for label, (pid, _retired) in projects(ccw_env).items():
        assert label in result.out, f"{label} missing from list"
        assert str(pid) in result.out, f"id {pid} missing from list"


def test_list_marks_a_retired_project_rather_than_hiding_it(ccw_env: dict[str, str]) -> None:
    """R4: rows are soft-flagged, never removed. A merged project must not silently
    vanish from the one command whose job is to enumerate projects."""
    capture_at(ccw_env, "/home/alice/code/widget", "11111111-1111-1111-1111-111111111111")
    capture_at(ccw_env, "/home/alice/code/gadget", "22222222-2222-2222-2222-222222222222")
    ids = {label: pid for label, (pid, _) in projects(ccw_env).items()}
    keep, merged = ids["widget"], ids["gadget"]
    assert run_ccw(["project", "merge", str(keep), str(merged)], ccw_env).code == 0

    result = run_ccw(["project", "list"], ccw_env)
    assert result.code == 0, result.err
    assert "gadget" in result.out, "a retired project disappeared from project list"
    assert "retired" in result.out.lower()


# --------------------------------------------------------------------------- show


def test_show_prints_the_registry_id_per_design_8(ccw_env: dict[str, str]) -> None:
    """THE load-bearing case: DESIGN 8 keys per-project config on the registry ID and
    names this command as the way to obtain it."""
    capture_at(ccw_env, "/home/alice/code/widget", "11111111-1111-1111-1111-111111111111")
    pid = projects(ccw_env)["widget"][0]
    result = run_ccw(["project", "show", str(pid)], ccw_env)
    assert result.code == 0, result.err
    assert str(pid) in result.out, "show did not print the registry id"
    assert "widget" in result.out


def test_show_prints_the_path_claims_and_session_count(ccw_env: dict[str, str]) -> None:
    cwd = "/home/alice/code/widget"
    capture_at(ccw_env, cwd, "11111111-1111-1111-1111-111111111111")
    pid = projects(ccw_env)["widget"][0]
    result = run_ccw(["project", "show", str(pid)], ccw_env)
    assert result.code == 0, result.err
    assert cwd in result.out, "show did not print the project's cwd claim"
    assert "1" in result.out, "show did not print a session count"


def test_show_of_an_unknown_id_is_an_error(ccw_env: dict[str, str]) -> None:
    capture_at(ccw_env, "/home/alice/code/widget", "11111111-1111-1111-1111-111111111111")
    result = run_ccw(["project", "show", "9999"], ccw_env)
    assert result.code != 0
    assert "9999" in result.err


def test_show_of_a_non_integer_id_is_an_error(ccw_env: dict[str, str]) -> None:
    capture_at(ccw_env, "/home/alice/code/widget", "11111111-1111-1111-1111-111111111111")
    result = run_ccw(["project", "show", "widget"], ccw_env)
    assert result.code != 0


# --------------------------------------------------------------------------- move


def test_move_records_the_new_claim_and_keeps_the_old_one(ccw_env: dict[str, str]) -> None:
    """DESIGN 2: paths are time-stamped alias CLAIMS and claims are append-only (R4), so
    a move adds the new path without discarding the history of the old one."""
    old = "/home/alice/code/widget"
    new = "/home/alice/work/widget"
    capture_at(ccw_env, old, "11111111-1111-1111-1111-111111111111")
    pid = projects(ccw_env)["widget"][0]

    result = run_ccw(["project", "move", old, new], ccw_env)
    assert result.code == 0, result.err
    assert alias_owner(ccw_env, new) == pid, "the new path was not claimed"
    assert alias_owner(ccw_env, old) == pid, "the old claim was discarded (claims are append-only)"


def test_move_also_claims_the_encoded_form_of_the_new_path(ccw_env: dict[str, str]) -> None:
    """F4: a project first captured without a cwd must not resolve to a stale encoded
    alias after the move, so the encoded form of the new path is claimed too."""
    old = "/home/alice/code/widget"
    new = "/home/alice/work/widget"
    capture_at(ccw_env, old, "11111111-1111-1111-1111-111111111111")
    pid = projects(ccw_env)["widget"][0]
    assert run_ccw(["project", "move", old, new], ccw_env).code == 0
    assert alias_owner(ccw_env, encode(new), "encoded_dir") == pid


def test_move_of_an_unclaimed_path_is_refused_and_changes_nothing(
    ccw_env: dict[str, str],
) -> None:
    """R5: refuse rather than silently record nothing."""
    capture_at(ccw_env, "/home/alice/code/widget", "11111111-1111-1111-1111-111111111111")
    before = catalog_rows(ccw_env, "SELECT path, kind, project_id FROM project_alias")
    result = run_ccw(["project", "move", "/nobody/claims/this", "/somewhere/new"], ccw_env)
    assert result.code != 0
    assert catalog_rows(ccw_env, "SELECT path, kind, project_id FROM project_alias") == before


def test_move_onto_another_projects_claim_is_refused_and_changes_nothing(
    ccw_env: dict[str, str],
) -> None:
    """F4: two projects must never end up sharing one cwd claim."""
    a = "/home/alice/code/widget"
    b = "/home/alice/code/gadget"
    capture_at(ccw_env, a, "11111111-1111-1111-1111-111111111111")
    capture_at(ccw_env, b, "22222222-2222-2222-2222-222222222222")
    before = catalog_rows(ccw_env, "SELECT path, kind, project_id FROM project_alias")
    result = run_ccw(["project", "move", a, b], ccw_env)
    assert result.code != 0
    assert catalog_rows(ccw_env, "SELECT path, kind, project_id FROM project_alias") == before


def test_move_requires_two_paths(ccw_env: dict[str, str]) -> None:
    result = run_ccw(["project", "move", "/only/one"], ccw_env)
    assert result.code != 0


# -------------------------------------------------------------------------- merge


def test_merge_repoints_sessions_and_soft_retires_the_merged_project(
    ccw_env: dict[str, str],
) -> None:
    """R4/F9: nothing is deleted. The merged project is flagged retired and its sessions
    and claims move to keep, so a later capture at a merged path resolves to keep."""
    capture_at(ccw_env, "/home/alice/code/widget", "11111111-1111-1111-1111-111111111111")
    capture_at(ccw_env, "/home/alice/code/gadget", "22222222-2222-2222-2222-222222222222")
    ids = {label: pid for label, (pid, _) in projects(ccw_env).items()}
    keep, merged = ids["widget"], ids["gadget"]

    result = run_ccw(["project", "merge", str(keep), str(merged)], ccw_env)
    assert result.code == 0, result.err

    after = projects(ccw_env)
    assert after["gadget"][1] == 1, "the merged project was not retired"
    assert after["widget"][1] == 0, "the kept project was retired"
    rows = cast(
        list[tuple[object, ...]],
        catalog_rows(ccw_env, "SELECT COUNT(*) FROM session WHERE project_id = ?", [keep]),
    )
    assert cast(int, rows[0][0]) == 2, "sessions were not repointed onto the kept project"
    assert alias_owner(ccw_env, "/home/alice/code/gadget") == keep, "claims did not move"


def test_merge_states_which_project_survives(ccw_env: dict[str, str]) -> None:
    """`merge A B` is ambiguous read cold, so the output must say which way it went."""
    capture_at(ccw_env, "/home/alice/code/widget", "11111111-1111-1111-1111-111111111111")
    capture_at(ccw_env, "/home/alice/code/gadget", "22222222-2222-2222-2222-222222222222")
    ids = {label: pid for label, (pid, _) in projects(ccw_env).items()}
    result = run_ccw(["project", "merge", str(ids["widget"]), str(ids["gadget"])], ccw_env)
    assert result.code == 0, result.err
    assert "widget" in result.out and "gadget" in result.out


def test_merge_into_itself_is_refused(ccw_env: dict[str, str]) -> None:
    capture_at(ccw_env, "/home/alice/code/widget", "11111111-1111-1111-1111-111111111111")
    pid = projects(ccw_env)["widget"][0]
    result = run_ccw(["project", "merge", str(pid), str(pid)], ccw_env)
    assert result.code != 0


def test_merge_with_an_unknown_id_is_refused_and_changes_nothing(
    ccw_env: dict[str, str],
) -> None:
    capture_at(ccw_env, "/home/alice/code/widget", "11111111-1111-1111-1111-111111111111")
    pid = projects(ccw_env)["widget"][0]
    before = projects(ccw_env)
    result = run_ccw(["project", "merge", str(pid), "9999"], ccw_env)
    assert result.code != 0
    assert projects(ccw_env) == before


def test_merge_requires_two_ids(ccw_env: dict[str, str]) -> None:
    capture_at(ccw_env, "/home/alice/code/widget", "11111111-1111-1111-1111-111111111111")
    result = run_ccw(["project", "merge", "1"], ccw_env)
    assert result.code != 0


# -------------------------------------------------------------------------- rename


def test_rename_still_works_unchanged(ccw_env: dict[str, str]) -> None:
    """The one subcommand that already existed must survive the surface expansion."""
    capture_at(ccw_env, "/home/alice/code/widget", "11111111-1111-1111-1111-111111111111")
    pid = projects(ccw_env)["widget"][0]
    assert run_ccw(["project", "rename", str(pid), "renamed"], ccw_env).code == 0
    assert "renamed" in projects(ccw_env)


def test_the_project_verb_never_opens_a_stored_payload(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R6/F5: the catalog is the read path. list and show answer from catalog rows and
    must not open a single object under objects/ to do it."""
    from conftest import record_opens, run_cli, warehouse_root

    capture_at(ccw_env, "/home/alice/code/widget", "11111111-1111-1111-1111-111111111111")
    pid = projects(ccw_env)["widget"][0]
    objects = warehouse_root(ccw_env) / "objects"
    with record_opens(objects) as opened:
        assert run_cli(["project", "list"]).code == 0
        assert run_cli(["project", "show", str(pid)]).code == 0
    assert opened == [], f"the project verb opened {len(opened)} stored payload(s)"
