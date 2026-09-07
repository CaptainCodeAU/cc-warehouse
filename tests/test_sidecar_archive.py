"""Oracle tests: sidecar folders inside their session (ticket 38, slice 38b).

    <root>/<label>/<stamp>_<uuid>/
        <uuid>.jsonl   transcript.md  ...  manifest.json
        subagents/          <- ticket 21
        tool-results/       <- this slice, mirrored from the source tree
            hook-<uuid>-stdout.txt
            pdf-<uuid>/page-01.jpg      the real nesting; a flat copy loses it
        workflows/          <- this slice
        sidecars.json       <- written ONLY when something is unarchived

A MIRROR, not a rename. The JSONL's `persistedOutputPath` resolves by basename,
and R12 forbids deriving a `<stamp>_` prefix from an mtime, so the original
relative path is the only layout that both resolves and stays honest.

`sidecars.json` is a NOTICE, deliberately not a manifest key. The manifest is
re-rendered minutes later by `build` or the detached render child, neither of
which can see the source directory, so a manifest key would either freeze at
whatever the copier last saw or need a compare nobody can perform. About 617
hidden sessions have no manifest at all (28,787 JSONL against 28,170 manifests),
and those are exactly the sessions most likely to be forgotten.

Contract: DESIGN 6 (new top-level manifest keys, not a `loss` amendment), 14 R2,
R4 as amended (no deletion primitive), R5, section 15 rulings (c) and (d);
FINDINGS F1, F6.
"""

import ast
import json
from pathlib import Path
from typing import cast

from cc_warehouse import archive, sidecars, store
from cc_warehouse.render import RenderOptions
from conftest import DEFAULT_UUID, SRC_ROOT, basic_session, subagent_meta, subagent_session

ZONE = "Australia/Melbourne"
OPTS = RenderOptions()
LABEL = "widget"
AGENT = "a94d30c1d877f964d"

STDOUT_NAME = "hook-9c2f1a7b-3d4e-5f60-8a91-b2c3d4e5f607-stdout.txt"
STDOUT_BYTES = b"Output too large (132.9KB). Full output saved to: /home/alice/x\n"


def parent_folder(root: Path) -> Path:
    return archive.write_session_folder(
        root, LABEL, basic_session(session_id=DEFAULT_UUID), OPTS, ZONE
    ).directory


def source_tool_results(tmp_path: Path) -> Path:
    """A `tool-results/` dir in the shape the real ones have, nesting included."""
    src = tmp_path / "source" / DEFAULT_UUID / "tool-results"
    (src / "pdf-4f1e").mkdir(parents=True)
    (src / STDOUT_NAME).write_bytes(STDOUT_BYTES)
    (src / "pdf-4f1e" / "page-01.jpg").write_bytes(b"\xff\xd8\xff\xe0JPEGISH")
    (src / ".DS_Store").write_bytes(b"\x00")
    return src


def manifest_of(folder: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads((folder / "manifest.json").read_text("utf-8")))


def listed(folder: Path, key: str) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], manifest_of(folder)[key])


# ---------------------------------------------------------------------------
# The fence: a name without a copier, or a copier without a name, is a bug
# ---------------------------------------------------------------------------


def test_every_known_sidecar_name_has_a_copier_and_every_copier_has_a_name() -> None:
    """THE ONE SWITCH the operator asked for. A config key that acknowledges a
    name without copying it is precisely the F6 shape this project exists to
    remove: something that parses, is tested, and does nothing."""
    assert set(archive.COPIERS) == sidecars.SESSION_SIDECARS


def test_every_named_copier_actually_exists_in_the_archive_module() -> None:
    """The other half. Without it the mapping could name a function that was
    renamed away and the first fence would still pass."""
    missing = [fn for fn in archive.COPIERS.values() if not hasattr(archive, fn)]
    assert missing == [], f"COPIERS names functions that do not exist: {missing}"


# ---------------------------------------------------------------------------
# The copy itself
# ---------------------------------------------------------------------------


def test_a_tool_result_lands_under_the_session_folder_with_its_original_bytes(
    tmp_path: Path,
) -> None:
    folder = parent_folder(tmp_path)
    archive.copy_sidecar_dir(folder, "tool-results", source_tool_results(tmp_path))
    assert (folder / "tool-results" / STDOUT_NAME).read_bytes() == STDOUT_BYTES


def test_nesting_inside_tool_results_is_kept(tmp_path: Path) -> None:
    """`pdf-<uuid>/page-NN.jpg` is the only nesting the real corpus has (72 files
    in 19 dirs) and it is referenced by no JSONL at all, so a flat copy would
    both lose the structure and be the only record of it."""
    folder = parent_folder(tmp_path)
    archive.copy_sidecar_dir(folder, "tool-results", source_tool_results(tmp_path))
    assert (folder / "tool-results" / "pdf-4f1e" / "page-01.jpg").is_file()


def test_ds_store_is_not_copied(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.copy_sidecar_dir(folder, "tool-results", source_tool_results(tmp_path))
    assert not (folder / "tool-results" / ".DS_Store").exists()


def test_a_second_copy_of_the_same_bytes_writes_nothing(tmp_path: Path) -> None:
    """Ticket 37 Part A in its general form. 2,084 files rewritten every daily
    sweep would make every backup tool see the whole archive as changed."""
    folder = parent_folder(tmp_path)
    src = source_tool_results(tmp_path)
    archive.copy_sidecar_dir(folder, "tool-results", src)
    again = archive.copy_sidecar_dir(folder, "tool-results", src)
    assert again.written == 0
    assert again.unchanged == 2


def test_a_same_name_different_bytes_file_is_refused_and_the_original_kept(
    tmp_path: Path,
) -> None:
    """R5. There is no larger-is-better argument for a tool result the way there
    is for a re-captured transcript: two files with one name are two files."""
    folder = parent_folder(tmp_path)
    src = source_tool_results(tmp_path)
    archive.copy_sidecar_dir(folder, "tool-results", src)
    (src / STDOUT_NAME).write_bytes(b"completely different content entirely")
    result = archive.copy_sidecar_dir(folder, "tool-results", src)
    assert result.refused == (STDOUT_NAME,)
    assert (folder / "tool-results" / STDOUT_NAME).read_bytes() == STDOUT_BYTES


def test_writing_a_session_folder_alone_creates_no_sidecar_directory(tmp_path: Path) -> None:
    """The session writer must stay exactly what it was. A folder with an empty
    `tool-results/` in it would make `test_archive_layout`'s five-file promise
    false for every session that never had one."""
    folder = parent_folder(tmp_path)
    assert not (folder / "tool-results").exists()
    assert not (folder / "workflows").exists()


# ---------------------------------------------------------------------------
# Manifest keys (DESIGN 6)
# ---------------------------------------------------------------------------


def test_the_manifest_lists_each_tool_result_with_its_hash_and_size(tmp_path: Path) -> None:
    """Without this a deleted tool result is UNDETECTABLE: five valid files, a
    matching source hash and a correct folder name all still hold. That is the
    most dangerous kind of green, and it is the same argument that put
    `subagents` in the manifest in ticket 21e."""
    folder = parent_folder(tmp_path)
    archive.copy_sidecar_dir(folder, "tool-results", source_tool_results(tmp_path))
    archive.write_session_folder(
        tmp_path, LABEL, basic_session(session_id=DEFAULT_UUID), OPTS, ZONE, rebuild=True
    )
    records = listed(folder, "tool_results")
    assert {r["name"] for r in records} == {STDOUT_NAME, "pdf-4f1e/page-01.jpg"}
    stdout_rec = next(r for r in records if r["name"] == STDOUT_NAME)
    assert stdout_rec["sha256"] == store.sha256_hex(STDOUT_BYTES)
    assert stdout_rec["bytes"] == len(STDOUT_BYTES)


def test_the_manifest_lists_workflow_files_under_their_own_key(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    src = tmp_path / "source" / DEFAULT_UUID / "workflows"
    (src / "scripts").mkdir(parents=True)
    (src / "wf_abc.json").write_bytes(b'{"id":"wf_abc"}\n')
    (src / "scripts" / "review-wf_abc.js").write_bytes(b"export const meta = {}\n")
    archive.copy_sidecar_dir(folder, "workflows", src)
    archive.write_session_folder(
        tmp_path, LABEL, basic_session(session_id=DEFAULT_UUID), OPTS, ZONE, rebuild=True
    )
    records = listed(folder, "workflows")
    assert {r["name"] for r in records} == {"wf_abc.json", "scripts/review-wf_abc.js"}


def test_both_keys_are_empty_lists_when_a_session_has_no_sidecars(tmp_path: Path) -> None:
    """F6: `[]` says "none", a missing key says "this manifest predates the
    feature". A reader that cannot tell those apart cannot audit the corpus."""
    manifest = manifest_of(parent_folder(tmp_path))
    assert manifest["tool_results"] == []
    assert manifest["workflows"] == []


def test_a_folder_stops_being_current_once_a_tool_result_is_added(tmp_path: Path) -> None:
    """Otherwise the new file never reaches the manifest, and its later deletion
    is undetectable forever."""
    folder = parent_folder(tmp_path)
    digest = store.sha256_hex(basic_session(session_id=DEFAULT_UUID))
    assert archive.folder_is_current(folder, digest, OPTS) is True
    archive.copy_sidecar_dir(folder, "tool-results", source_tool_results(tmp_path))
    assert archive.folder_is_current(folder, digest, OPTS) is False


# ---------------------------------------------------------------------------
# verify (ruling (b): `ccw archive --verify` is archive integrity)
# ---------------------------------------------------------------------------


def test_verify_reports_a_tool_result_that_has_been_deleted(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.copy_sidecar_dir(folder, "tool-results", source_tool_results(tmp_path))
    archive.write_session_folder(
        tmp_path, LABEL, basic_session(session_id=DEFAULT_UUID), OPTS, ZONE, rebuild=True
    )
    (folder / "tool-results" / STDOUT_NAME).unlink()
    problems = [p.problem for p in archive.verify_folder(folder, ZONE)]
    assert f"tool-result {STDOUT_NAME} is missing" in problems, problems


def test_verify_reports_a_tool_result_whose_bytes_changed(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.copy_sidecar_dir(folder, "tool-results", source_tool_results(tmp_path))
    archive.write_session_folder(
        tmp_path, LABEL, basic_session(session_id=DEFAULT_UUID), OPTS, ZONE, rebuild=True
    )
    (folder / "tool-results" / STDOUT_NAME).write_bytes(b"tampered")
    problems = [p.problem for p in archive.verify_folder(folder, ZONE)]
    assert any("does not match its hash" in p for p in problems), problems


def test_no_sidecar_problem_string_starts_with_the_word_missing(tmp_path: Path) -> None:
    """doctor.py reclassifies any problem starting with `missing ` as "still
    queued behind a render" (ticket 34). A sidecar problem is never that, and
    borrowing the word would hide a real one as pending forever."""
    folder = parent_folder(tmp_path)
    archive.copy_sidecar_dir(folder, "tool-results", source_tool_results(tmp_path))
    archive.write_session_folder(
        tmp_path, LABEL, basic_session(session_id=DEFAULT_UUID), OPTS, ZONE, rebuild=True
    )
    (folder / "tool-results" / STDOUT_NAME).unlink()
    (folder / "tool-results" / "pdf-4f1e" / "page-01.jpg").write_bytes(b"x")
    sidecar_problems = [
        p.problem
        for p in archive.verify_folder(folder, ZONE)
        if "tool-result" in p.problem or "workflow file" in p.problem
    ]
    assert sidecar_problems
    assert not any(p.startswith("missing ") for p in sidecar_problems)


def test_a_manifest_written_before_this_feature_raises_no_sidecar_problems(
    tmp_path: Path,
) -> None:
    """Every one of ~22,000 existing folders is in this state until the 0.1.3
    rebuild reaches it. A daily `ccw repair` that alarms on all of them meanwhile
    is the crying-wolf failure."""
    folder = parent_folder(tmp_path)
    manifest = manifest_of(folder)
    del manifest["tool_results"]
    del manifest["workflows"]
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    assert archive.verify_folder(folder, ZONE) == []


# ---------------------------------------------------------------------------
# The notice
# ---------------------------------------------------------------------------


def scan_with_unknown(tmp_path: Path, *names: str) -> sidecars.SidecarScan:
    project = tmp_path / "source"
    project.mkdir(exist_ok=True)
    (project / f"{DEFAULT_UUID}.jsonl").write_bytes(b"{}\n")
    for name in names:
        (project / DEFAULT_UUID / name).mkdir(parents=True, exist_ok=True)
    return sidecars.scan(project / f"{DEFAULT_UUID}.jsonl", DEFAULT_UUID)


def test_the_notice_body_carries_exactly_the_four_planned_keys(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_sidecar_notice(folder, scan_with_unknown(tmp_path, "zzz-probe"), ())
    body = json.loads((folder / "sidecars.json").read_text(encoding="utf-8"))
    assert set(body) == {"schema", "unarchived", "unknown_inside_subagents", "refused"}


def test_the_notice_names_the_unarchived_sibling(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_sidecar_notice(folder, scan_with_unknown(tmp_path, "zzz-probe"), ())
    body = json.loads((folder / "sidecars.json").read_text(encoding="utf-8"))
    assert body["unarchived"] == ["zzz-probe"]


def test_the_notice_body_depends_only_on_the_names_it_reports(tmp_path: Path) -> None:
    """A timestamp in here would re-create ticket 37 Part A exactly: the body
    would differ on every run, `write_if_changed` could never skip, and every
    session folder would carry today's mtime whatever day its session happened.
    Proved by rendering the same anomaly twice into two folders rather than by
    reading the code for a clock, because only the bytes are the promise."""
    first = parent_folder(tmp_path)
    archive.write_sidecar_notice(first, scan_with_unknown(tmp_path, "zzz-probe"), ())
    second = tmp_path / "elsewhere"
    second.mkdir()
    archive.write_sidecar_notice(second, scan_with_unknown(tmp_path, "zzz-probe"), ())
    assert (first / "sidecars.json").read_bytes() == (second / "sidecars.json").read_bytes()


def test_a_clean_session_gets_no_notice_file_at_all(tmp_path: Path) -> None:
    """22,000 folders each gaining an empty JSON file is noise, not information."""
    folder = parent_folder(tmp_path)
    archive.write_sidecar_notice(folder, scan_with_unknown(tmp_path), ())
    assert not (folder / "sidecars.json").exists()


def test_an_unchanged_notice_is_not_rewritten(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    scan = scan_with_unknown(tmp_path, "zzz-probe")
    assert archive.write_sidecar_notice(folder, scan, ()) is True
    assert archive.write_sidecar_notice(folder, scan, ()) is False


def test_a_fixed_anomaly_rewrites_the_notice_to_empty_lists_rather_than_deleting_it(
    tmp_path: Path,
) -> None:
    """R4: this module has no deletion primitive, and that is the point rather
    than an inconvenience. An empty notice is also better evidence than a missing
    one: it says "this was checked and is clean now"."""
    folder = parent_folder(tmp_path)
    archive.write_sidecar_notice(folder, scan_with_unknown(tmp_path, "zzz-probe"), ())
    (tmp_path / "source" / DEFAULT_UUID / "zzz-probe").rmdir()
    archive.write_sidecar_notice(folder, scan_with_unknown(tmp_path), ())
    body = json.loads((folder / "sidecars.json").read_text(encoding="utf-8"))
    assert body["unarchived"] == []
    assert (folder / "sidecars.json").is_file()


def test_a_refused_file_is_named_in_the_notice(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_sidecar_notice(
        folder, scan_with_unknown(tmp_path), (f"tool-results/{STDOUT_NAME}",)
    )
    body = json.loads((folder / "sidecars.json").read_text(encoding="utf-8"))
    assert body["refused"] == [f"tool-results/{STDOUT_NAME}"]


def test_the_notice_is_not_a_generated_file(tmp_path: Path) -> None:
    """`GENERATED_NAMES` drives `_current_manifest`'s presence check, verify's
    five-name check and what the rebuild module may delete. A notice in that
    tuple would be regenerable, deletable and required, and it is none of those."""
    assert "sidecars.json" not in archive.GENERATED_NAMES
    assert "stranded.json" not in archive.GENERATED_NAMES


# ---------------------------------------------------------------------------
# Sub-agent companions and stranded dirs
# ---------------------------------------------------------------------------


def test_the_forked_skill_companions_travel_with_their_subagent(tmp_path: Path) -> None:
    """10 of each exist in the live tree and nothing copied them. Same argument
    as `meta.json`: they are the only record of what the agent WAS."""
    parent_folder(tmp_path)
    result = archive.write_subagent(
        tmp_path,
        LABEL,
        subagent_session(agent_id=AGENT),
        ZONE,
        meta=subagent_meta(),
        companions=((f"agent-{AGENT}.forked-skill.json", b'{"skill":"tdd"}\n'),),
    )
    companion = result.directory / f"agent-{AGENT}.forked-skill.json"
    assert companion.read_bytes() == b'{"skill":"tdd"}\n'


def test_an_unchanged_companion_is_not_rewritten(tmp_path: Path) -> None:
    parent_folder(tmp_path)
    data = subagent_session(agent_id=AGENT)
    companions = ((f"agent-{AGENT}.forked-skill.json", b"{}\n"),)
    archive.write_subagent(
        tmp_path, LABEL, data, ZONE, meta=subagent_meta(), companions=companions
    )
    second = archive.write_subagent(
        tmp_path, LABEL, data, ZONE, meta=subagent_meta(), companions=companions
    )
    assert second.wrote is False


def test_a_stranded_sidecar_dir_is_copied_under_not_sessions(tmp_path: Path) -> None:
    """Ruling (d). The dir name is recorded as a LABEL, not claimed as identity:
    the whole reason it is stranded is that the file which would have proved its
    identity is absent (F4)."""
    src = tmp_path / "source" / "99999999-0000-0000-0000-000000000000"
    (src / "tool-results").mkdir(parents=True)
    (src / "tool-results" / STDOUT_NAME).write_bytes(STDOUT_BYTES)
    archive.write_stranded_sidecars(tmp_path, src)
    landed = (
        tmp_path
        / "_not-sessions"
        / "stranded-sidecars"
        / "99999999-0000-0000-0000-000000000000"
        / "tool-results"
        / STDOUT_NAME
    )
    assert landed.read_bytes() == STDOUT_BYTES


def test_a_stranded_copy_records_why_it_is_there(tmp_path: Path) -> None:
    src = tmp_path / "source" / "99999999-0000-0000-0000-000000000000"
    (src / "tool-results").mkdir(parents=True)
    (src / "tool-results" / STDOUT_NAME).write_bytes(STDOUT_BYTES)
    archive.write_stranded_sidecars(tmp_path, src)
    note = json.loads(
        (
            tmp_path
            / "_not-sessions"
            / "stranded-sidecars"
            / "99999999-0000-0000-0000-000000000000"
            / "stranded.json"
        ).read_text(encoding="utf-8")
    )
    assert note["dir_name"] == "99999999-0000-0000-0000-000000000000"
    assert note["reason"] == "no transcript found beside this dir"
    assert note["schema"] == 1


def test_a_second_stranded_copy_writes_nothing(tmp_path: Path) -> None:
    src = tmp_path / "source" / "99999999-0000-0000-0000-000000000000"
    (src / "tool-results").mkdir(parents=True)
    (src / "tool-results" / STDOUT_NAME).write_bytes(STDOUT_BYTES)
    archive.write_stranded_sidecars(tmp_path, src)
    again = archive.write_stranded_sidecars(tmp_path, src)
    assert again.written == 0


# ---------------------------------------------------------------------------
# R4 re-asserted: this slice added three writers and still no deleter
# ---------------------------------------------------------------------------


def test_the_archive_module_has_no_deletion_primitive_at_all() -> None:
    tree = ast.parse((SRC_ROOT / "archive.py").read_text(encoding="utf-8"))
    offenders = [
        f"archive.py:{node.lineno} .{node.func.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"unlink", "rmdir", "rmtree", "remove", "removedirs"}
    ]
    assert not offenders, f"deletion primitives in the archive module (R4): {offenders}"


def test_the_sidecars_module_has_no_deletion_primitive_either() -> None:
    tree = ast.parse((SRC_ROOT / "sidecars.py").read_text(encoding="utf-8"))
    offenders = [
        f"sidecars.py:{node.lineno} .{node.func.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"unlink", "rmdir", "rmtree", "remove", "removedirs"}
    ]
    assert not offenders, f"deletion primitives in the sidecars module (R4): {offenders}"
