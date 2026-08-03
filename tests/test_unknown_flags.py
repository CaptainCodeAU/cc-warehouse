"""Oracle tests: an unrecognised flag is a usage error, on every verb.

Contract: DESIGN section 7 ("Errors print `Error: <msg>` to stderr"), R5 (refuse
rather than guess), F6.

WHY THIS FILE EXISTS. On 2026-08-01 `ccw sweep -h` printed no help and imported
13,836 sessions, because eight of ten verbs never checked for the flag. That was
fixed STRUCTURALLY at the dispatcher, so no handler can ever see `-h`.

Unknown flags never got the same treatment. Measured 2026-08-03, before this
file:

    ccw sweep   --totally-bogus-flag   exit 0, root CREATED, "1 items, 1 stored"
    ccw build   --totally-bogus-flag   exit 0, root CREATED
    ccw verify  --totally-bogus-flag   exit 0, root CREATED
    ccw status  --totally-bogus-flag   exit 0, root CREATED

So a typo ran a real import. The trigger for finding it was adding `--dry-run`
to sweep (ticket 23): had unknown flags stayed ignored, `--dry-runn` would have
performed the live sweep the flag exists to rehearse, which is the SAME accident
one level down.

TWO FENCES, and both are needed. Rejecting the unknown is worthless if it also
rejects the known, so `test_every_flag_the_help_lists_is_accepted` walks the help
text and asserts the opposite direction. The verb list and the flag list are both
read from the PUBLIC surface, so a verb or flag added later is covered the day it
is added rather than the day someone remembers this file.
"""

import re

import pytest

from conftest import basic_session, run_ccw, run_cli, warehouse_root, write_transcript

BOGUS = "--totally-bogus-flag"
UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"


def _verbs_from_help() -> tuple[str, ...]:
    """Every verb `ccw -h` lists, read from the help text itself (same source as
    test_help_is_inert, for the same reason)."""
    listing = run_cli(["-h"]).out
    return tuple(
        line.strip().split()[0]
        for line in listing.splitlines()
        if line.startswith("  ") and line.strip() and not line.strip().startswith("-")
    )


def _flags_from_verb_help(verb: str) -> tuple[str, ...]:
    """Every flag spelling `ccw <verb> -h` prints, expanded.

    `--[no-]subagents` is printed as one line but is TWO accepted spellings, so
    it expands to both. A flag that takes a value is returned bare; the caller
    supplies the value.
    """
    listing = run_cli([verb, "-h"]).out
    found: list[str] = []
    for line in listing.splitlines():
        # Option ROWS only. Group HEADINGS end in ":" and contain prose that
        # mentions a flag-shaped placeholder ("default on; --no-X drops it"),
        # which an unfiltered scan reads as a flag named `--no-X`. Corrected
        # after that placeholder showed up as a failure: the fixture was wrong,
        # not the product.
        if not line.startswith("  ") or line.rstrip().endswith(":"):
            continue
        for stem, plain in re.findall(
            r"--\[no-\]([a-z0-9-]+)|(--[A-Za-z][A-Za-z0-9-]*)", line
        ):
            if stem:
                found.extend((f"--{stem}", f"--no-{stem}"))
            elif plain:
                found.append(plain)
    return tuple(dict.fromkeys(found))


VERB_NAMES = _verbs_from_help()


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_unknown_flag_is_a_usage_error(ccw_env: dict[str, str], verb: str) -> None:
    """Exit non-zero and say so on stderr, rather than proceeding as if the
    operator had not typed it."""
    result = run_ccw([verb, BOGUS], ccw_env, stdin="")

    assert result.code != 0, f"{verb} {BOGUS}: exit 0, out={result.out!r}"
    assert "Error" in result.err, f"{verb} {BOGUS}: nothing on stderr: {result.err!r}"
    assert BOGUS in result.err, f"{verb} {BOGUS}: the flag was not named: {result.err!r}"


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_unknown_flag_performs_no_work(ccw_env: dict[str, str], verb: str) -> None:
    """The mechanical proof, and the one that would have caught the 2026-08-01
    sweep: exit code and output are not evidence, so ask whether the world
    changed. Every verb that does anything real opens or creates the warehouse
    root."""
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    root = warehouse_root(ccw_env)
    assert not root.exists(), "fixture precondition: root must not exist yet"

    run_ccw([verb, BOGUS], ccw_env, stdin="")

    assert not root.exists(), (
        f"{verb} {BOGUS} acted: {sorted(p.name for p in root.rglob('*'))}"
    )


@pytest.mark.parametrize("verb", VERB_NAMES)
def test_every_flag_the_help_lists_is_accepted(ccw_env: dict[str, str], verb: str) -> None:
    """THE INVERSE FENCE. A validator that rejects valid flags is worse than none,
    because it breaks working invocations. Every spelling the verb's own help
    prints must survive validation.

    The verb may still fail for its OWN reasons (a missing required argument, an
    absent warehouse); what it must never say is that its own documented flag is
    unrecognised.
    """
    for flag in _flags_from_verb_help(verb):
        result = run_ccw([verb, flag], ccw_env, stdin="")
        assert flag not in result.err or "unrecognised" not in result.err.lower(), (
            f"{verb} rejected its own documented flag {flag}: {result.err!r}"
        )
        assert "totally-bogus" not in result.err


def test_flag_equals_value_form_is_accepted(ccw_env: dict[str, str]) -> None:
    """`--source=DIR` is the same flag as `--source DIR` and must not be read as
    an unknown flag named `--source=DIR`."""
    src = warehouse_root(ccw_env).parent / "elsewhere"
    src.mkdir(parents=True, exist_ok=True)

    result = run_ccw(["sweep", f"--source={src}"], ccw_env)

    assert "unrecognised" not in result.err.lower(), result.err


def test_a_flags_value_is_not_mistaken_for_a_flag(ccw_env: dict[str, str]) -> None:
    """A value that happens to start with `-` belongs to its flag. Sweep already
    refuses a flag-like `--source` value with its own message (R5); the point
    here is that the unknown-flag check must not pre-empt it with a different
    one."""
    result = run_ccw(["sweep", "--source", "-nope"], ccw_env)

    assert result.code != 0
    assert "totally-bogus" not in result.err


def test_unknown_flag_names_the_offender_not_just_the_verb(
    ccw_env: dict[str, str],
) -> None:
    """R10's spirit: name the thing that failed. An operator who typo'd one flag
    among six should not have to bisect."""
    result = run_ccw(["build", "--rebuild", "--rebiuld"], ccw_env)

    assert result.code != 0
    assert "--rebiuld" in result.err, result.err
