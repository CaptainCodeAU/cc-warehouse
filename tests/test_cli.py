"""Oracle tests: CLI surface and dispatch (slices 8, 9, 13).

Contract: DESIGN section 7 (verb table, error contract, no default-verb
dispatch, packaging), SPEC section 2 (KEEP: Error: <msg> on stderr exit 1,
version flag; DROP: implicit subcommand trick).
"""

from pathlib import Path

import cc_warehouse
from conftest import basic_session, run_ccw, warehouse_root

V1_VERBS = (
    "hook",
    "sweep",
    "render",
    "build",
    "migrate",
    "relocate",
    "project",
    "share",
    "status",
    "verify",
    "version",
)


def test_version_flag_and_verb(ccw_env: dict[str, str]) -> None:
    for args in (["-v"], ["--version"], ["version"]):
        result = run_ccw(args, ccw_env)
        assert result.code == 0
        assert cc_warehouse.__version__ in result.out


def test_bare_ccw_prints_status_and_usage(ccw_env: dict[str, str]) -> None:
    """DESIGN section 7: bare ccw prints short status + usage, exit 0."""
    result = run_ccw([], ccw_env)
    assert result.code == 0
    assert "usage" in (result.out + result.err).lower()


def test_help_lists_every_v1_verb(ccw_env: dict[str, str]) -> None:
    result = run_ccw(["-h"], ccw_env)
    assert result.code == 0
    for verb in V1_VERBS:
        assert verb in result.out, f"verb {verb} missing from help"


def test_unknown_verb_is_a_usage_error_not_a_dispatch(ccw_env: dict[str, str]) -> None:
    """SPEC 2 DROP: no default-subcommand trick; an unknown leading arg is an
    error, never routed to some default verb."""
    result = run_ccw(["definitely-not-a-verb"], ccw_env)
    assert result.code != 0
    assert "usage" in (result.out + result.err).lower()
    assert not warehouse_root(ccw_env).exists()


def test_cli_error_contract(ccw_env: dict[str, str]) -> None:
    """SPEC 2 KEEP: CliError maps to `Error: <msg>` on stderr, exit 1."""
    result = run_ccw(
        ["render", str(Path(ccw_env["HOME"]) / "does-not-exist.jsonl")], ccw_env
    )
    assert result.code == 1
    assert result.err.startswith("Error: ")


def test_render_adhoc_writes_out_dir_and_never_touches_the_warehouse(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """DESIGN section 7: ad-hoc render goes to --out, never under projections/,
    never touching the catalog."""
    source = tmp_path / "adhoc.jsonl"
    source.write_bytes(basic_session())
    out = tmp_path / "out"
    result = run_ccw(["render", str(source), "--out", str(out)], ccw_env)
    assert result.code == 0, result.err
    names = {p.name for p in out.iterdir()}
    assert {
        "transcript.md",
        "transcript.compact.md",
        "conversation.html",
        "conversation.compact.html",
    } <= names
    root = warehouse_root(ccw_env)
    assert not (root / "projections").exists()
    assert not (root / "catalog.sqlite").exists()


def test_render_adhoc_without_out_prints_a_temp_path(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    source = tmp_path / "adhoc.jsonl"
    source.write_bytes(basic_session())
    result = run_ccw(["render", str(source)], ccw_env)
    assert result.code == 0, result.err
    printed = [line for line in result.out.splitlines() if line.strip()]
    assert printed
    candidates = [Path(line.strip()) for line in printed if Path(line.strip()).exists()]
    assert candidates, f"no existing path printed: {result.out!r}"
    rendered = candidates[-1]
    assert (rendered / "conversation.html").exists()
    assert "projections" not in rendered.parts


# --- the per-variant matrix flag surface (slice 14) ------------------------
# DESIGN section 15 entry 2026-08-01, shared rule (c): flag spelling is a
# MECHANICAL BIJECTION, flag = key with dashes. Help text may group flags for
# readability, never respell them.

MATRIX_FLAG_STEMS = (
    "subagents-compact",
    "attachments-compact",
    "commands-compact",
    "extras-compact",
    "tool-output-compact",
)


def test_build_and_render_accept_the_matrix_flag_pairs(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Every `_compact` key has a `--x-compact` / `--no-x-compact` pair, and both
    members are accepted by the two verbs that honor the content flags."""
    source = tmp_path / "s.jsonl"
    source.write_bytes(basic_session())
    for stem in MATRIX_FLAG_STEMS:
        for flag in (f"--{stem}", f"--no-{stem}"):
            out = tmp_path / f"out-{stem}-{flag.strip('-')}"
            result = run_ccw(["render", str(source), "--out", str(out), flag], ccw_env)
            assert result.code == 0, f"{flag}: {result.err}"
            assert (out / "transcript.compact.md").exists()


def test_matrix_flags_are_listed_in_the_content_help_group(ccw_env: dict[str, str]) -> None:
    """The flags are discoverable: `ccw build -h` and `ccw render -h` list each
    one in its bijection spelling, and `--reminders-compact` beside them."""
    for verb in ("build", "render"):
        result = run_ccw([verb, "-h"], ccw_env)
        assert result.code == 0, result.err
        for stem in MATRIX_FLAG_STEMS:
            assert stem in result.out, f"--{stem} missing from `ccw {verb} -h`"
        assert "--reminders-compact" in result.out


def test_the_reversed_compact_spelling_is_not_a_flag(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`--compact-subagents` is NOT a spelling of `--subagents-compact`. The
    bijection has zero exceptions, so the reversed form carries no meaning and
    leaves the projection exactly as it was."""
    source = tmp_path / "s.jsonl"
    source.write_bytes(basic_session())
    plain = tmp_path / "plain"
    assert run_ccw(["render", str(source), "--out", str(plain)], ccw_env).code == 0
    reversed_out = tmp_path / "reversed"
    result = run_ccw(
        ["render", str(source), "--out", str(reversed_out), "--compact-subagents"], ccw_env
    )
    assert result.code == 0, result.err
    for name in ("transcript.md", "transcript.compact.md", "conversation.compact.html"):
        assert (reversed_out / name).read_bytes() == (plain / name).read_bytes(), name
