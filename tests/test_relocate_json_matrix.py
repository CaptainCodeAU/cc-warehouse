"""Deterministic JSON-rewrite matrix for ccw relocate (ticket 12b finding 2).

Contract-derived, from DESIGN section 11 ("JSON-aware editing rewrites every string in
the decoded document, KEYS INCLUDED") and FINDINGS F6 (a run must not claim more, or
less, than it did).

WHY A MATRIX RATHER THAN AN EXAMPLE. A single worked example is a lower bound on
coverage, not a census. Rewriting path references inside JSON has one obvious axis (does
the path get repaired) and several non-obvious ones that only appear at specific shapes:
a path can be a KEY as well as a value; it can be spelled in an escaped form that is
invisible to raw-text matching and only becomes the real path once decoded (the slice-11
B1 lesson); re-encoding a document silently normalises number formats, duplicate keys and
unicode escapes; and a file may already be invalid JSON before relocate ever sees it.
Enumerating the shapes is the only way to know which of those a change touches.

THE POLICY THIS PINS (principal ruling 2026-07-23, "option 5"). Rewrite as TEXT so a
hand-maintained file keeps its layout, then DECODE THE RESULT and check no old-path
reference survives. If one does, redo that file through the decode path and NAME it in the
report as reformatted. A file that was already unparseable before the run is rewritten as
text and is never blamed on us.

Every case runs through the real `ccw relocate --apply` in ONE subprocess invocation; the
per-case assertions then inspect what landed on disk. The seam is the CLI and the files,
never a private helper.
"""

import json
import re
from dataclasses import dataclass

import pytest

from conftest import CliResult, run_ccw


def encode(path: str) -> str:
    return re.sub(r"[/_.]", "-", path)


@dataclass(frozen=True)
class Case:
    cid: str
    description: str
    body: str
    reformats: bool  # True when the decode fallback is expected to fire


def _cases(old: str, new: str) -> list[Case]:
    """The enumerated shapes. `old` and `new` differ only in their last component, and
    are the SAME LENGTH, so "layout preserved" can be asserted as an exact byte count.

    Bodies are written as templates with a `<P>` placeholder rather than f-strings,
    because every one of them is dense with the braces JSON is made of.
    """
    esc = old.replace("/", "\\/")
    uni = old.replace("/", "\\u002f")

    def case(cid: str, description: str, template: str, value: str, reformats: bool) -> Case:
        return Case(cid, description, template.replace("<P>", value), reformats)

    return [
        case("C01", "path as a top-level KEY", '{"<P>": 1}', old, False),
        case("C02", "path as a VALUE", '{"root": "<P>"}', old, False),
        case("C03", "path nested three deep", '{"a": {"b": {"c": "<P>"}}}', old, False),
        case("C04", "path inside an array", '{"paths": ["<P>", "/other"]}', old, False),
        case("C05", "path as a key inside an array", '[{"<P>": {"x": 1}}]', old, False),
        case("C06", "encoded form", '{"d": "<P>"}', encode(old), False),
        case("C07", "hyphen sibling must not change", '{"p": "<P>-two"}', old, False),
        case("C08", "dotted sibling must not change", '{"p": "<P>.bak"}', old, False),
        case("C09", "bare word must not change", '{"p": "widget"}', old, False),
        case("C10", "path inside a longer string", '{"cmd": "cd <P> && make"}', old, False),
        case("C11", "path with a trailing slash", '{"p": "<P>/"}', old, False),
        case("C12", "subdirectory under the path", '{"p": "<P>/src/main.py"}', old, False),
        case("C13", "duplicate keys", '{"a": 1, "a": 2, "p": "<P>"}', old, False),
        case("C14", "number formats", '{"a": 1.10, "b": 1e5, "p": "<P>"}', old, False),
        case("C15", "big integer", '{"n": 12345678901234567890, "p": "<P>"}', old, False),
        case("C16", "non-ASCII as escapes", '{"note": "caf\\u00e9", "p": "<P>"}', old, False),
        case("C17", "raw non-ASCII", '{"note": "café", "p": "<P>"}', old, False),
        case("C18", "embedded newline and tab", '{"p": "<P>", "t": "a\\nb\\tc"}', old, False),
        case("C19", "top level is an array", '["<P>"]', old, False),
        case("C20", "top level is a bare string", '"<P>"', old, False),
        case("C21", "empty containers alongside", '{"e": {}, "l": [], "p": "<P>"}', old, False),
        case("C22", "null and booleans", '{"n": null, "t": true, "p": "<P>"}', old, False),
        case("C23", "pretty-printed, trailing newline", '{\n  "p": "<P>"\n}\n', old, False),
        case("C24", "no match anywhere", '{"p": "/somewhere/else"}', old, False),
        case("C25", "already invalid JSON", '{"p": "<P>",}', old, False),
        case(
            "C26",
            "deeply pretty-printed, several matches",
            '{\n  "projects": {\n    "<P>": {\n      "tools": []\n    }\n  },\n'
            '  "last": "<P>"\n}\n',
            old,
            False,
        ),
        # The escaped shapes: legal JSON that decodes to the real path and is invisible to
        # raw-text matching. These are what the decode fallback exists for.
        case("C27", "escaped slashes", '{"p": "<P>"}', esc, True),
        case("C28", "unicode-escaped slashes", '{"p": "<P>"}', uni, True),
        case("C29", "escaped slashes, pretty-printed", '{\n  "p": "<P>"\n}\n', esc, True),
    ]


@dataclass(frozen=True)
class MatrixRun:
    cases: dict[str, Case]
    before: dict[str, str]
    after: dict[str, str]
    result: CliResult
    old: str
    new: str


@pytest.fixture(scope="module")
def matrix(tmp_path_factory: pytest.TempPathFactory) -> MatrixRun:
    """Write every case into one inventory root and relocate ONCE, then inspect."""
    tmp = tmp_path_factory.mktemp("json-matrix")
    home = tmp / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    root = tmp / "warehouse"
    root.mkdir()
    env = {"HOME": str(home), "USER": "alice", "PATH": "", "CCW_ROOT": str(root)}

    repo = home / "CODE" / "widget"
    repo.mkdir(parents=True)
    new_repo = home / "CODE" / "gadget"  # same length as "widget": byte counts stay comparable
    inventory = tmp / "inventory"
    inventory.mkdir()
    (root / "config.toml").write_text(f'[relocate]\nroots = ["{inventory}"]\n')

    cases = _cases(str(repo), str(new_repo))
    before: dict[str, str] = {}
    for case in cases:
        (inventory / f"{case.cid}.json").write_text(case.body)
        before[case.cid] = case.body

    result = run_ccw(
        ["relocate", str(repo), "--to", str(new_repo), "--apply", "--yes"], env
    )
    after = {c.cid: (inventory / f"{c.cid}.json").read_text() for c in cases}
    return MatrixRun({c.cid: c for c in cases}, before, after, result, str(repo), str(new_repo))


def _decoded_mentions(text: str, needle: str) -> bool:
    """Does `needle` survive as a whole path component in the DECODED document?

    Decoded, because that is what any consumer of the file reads. A raw-text search
    cannot see a path that is only spelled in escaped form.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return bool(re.search(re.escape(needle) + r"(?![A-Za-z0-9_.-])", text))
    flat = json.dumps(data)  # normalises every escape into its real character
    return bool(re.search(re.escape(needle) + r"(?![A-Za-z0-9_.-])", flat))


CASE_IDS = [c.cid for c in _cases("/x/widget", "/x/gadget")]


def test_the_relocate_run_itself_succeeded(matrix: MatrixRun) -> None:
    assert matrix.result.code == 0, matrix.result.err


@pytest.mark.parametrize("cid", CASE_IDS)
def test_no_old_path_survives_in_the_decoded_document(cid: str, matrix: MatrixRun) -> None:
    """The repair itself, on every shape: nothing may still point at the old path."""
    if cid == "C24":  # nothing to repair in this one
        return
    assert not _decoded_mentions(matrix.after[cid], matrix.old), (
        f"{matrix.cases[cid].description}: an old-path reference survived"
    )


@pytest.mark.parametrize("cid", CASE_IDS)
def test_the_file_still_parses_unless_it_never_did(cid: str, matrix: MatrixRun) -> None:
    """A rewrite must never leave a document less valid than it found it."""
    was_valid = True
    try:
        json.loads(matrix.before[cid])
    except json.JSONDecodeError:
        was_valid = False
    if not was_valid:
        return  # C25 arrived broken; we do not claim to fix it, only not to blame us
    json.loads(matrix.after[cid])  # raises and fails the test if the rewrite corrupted it


@pytest.mark.parametrize("cid", CASE_IDS)
def test_layout_is_preserved_unless_the_decode_fallback_fired(
    cid: str, matrix: MatrixRun
) -> None:
    """The plan promises "rewrite path refs". Reformatting a hand-maintained file is a
    second, unconsented mutation riding along, so it happens only where correctness
    requires it - and where it does, the report has to say so (see the report test)."""
    case, before, after = matrix.cases[cid], matrix.before[cid], matrix.after[cid]
    if case.reformats:
        return
    assert after.count("\n") == before.count("\n"), f"{case.description}: line count changed"
    # old and new differ only in a same-length final component, so a pure path swap
    # cannot change the byte count at all.
    assert len(after) == len(before), f"{case.description}: byte count changed"


@pytest.mark.parametrize("cid", CASE_IDS)
def test_a_reformatted_file_is_named_in_the_report(cid: str, matrix: MatrixRun) -> None:
    """F6/R10: where layout could not be preserved, the run says which file and why."""
    if not matrix.cases[cid].reformats:
        return
    shown = matrix.result.out + matrix.result.err
    assert f"{cid}.json" in shown, "a reformatted file was not named"
    assert "reformat" in shown.lower(), "the reason for reformatting was not given"


def test_siblings_and_bare_words_are_never_touched(matrix: MatrixRun) -> None:
    """F4: the boundary guard is what keeps a relocate from capturing its neighbours."""
    assert matrix.old + "-two" in matrix.after["C07"], "the -two sibling was rewritten"
    assert matrix.old + ".bak" in matrix.after["C08"], "the .bak sibling was rewritten"
    assert json.loads(matrix.after["C09"])["p"] == "widget", "the bare word was rewritten"
    assert json.loads(matrix.after["C24"])["p"] == "/somewhere/else", "an unrelated path moved"


def test_non_path_content_is_carried_through_unchanged(matrix: MatrixRun) -> None:
    """Repairing a path must not quietly normalise the rest of the document."""
    assert json.loads(matrix.after["C13"])["a"] == 2  # duplicate keys still resolve
    assert '1.10' in matrix.after["C14"], "a number format was normalised"
    assert '12345678901234567890' in matrix.after["C15"], "a big integer lost precision"
    assert 'caf\\u00e9' in matrix.after["C16"], "a unicode escape was normalised"
    assert 'café' in matrix.after["C17"], "raw non-ASCII was re-escaped"
    assert json.loads(matrix.after["C18"])["t"] == "a\nb\tc"
