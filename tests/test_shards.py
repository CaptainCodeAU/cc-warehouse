"""The --shard split (#8378) never loses or doubles a test.

A stale tests/shard-times.json may only cost balance. These tests are the guard:
every test file lands in exactly one shard, the heavy files share one, and the
real collection under --shard I/N adds up to the unsharded collection.
"""

import subprocess
import sys

import pytest

from conftest import (
    REPO_ROOT,
    TESTS_ROOT,
    load_shard_times,
    parse_shard,
    shard_plan,
    suite_files,
)


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 8])
def test_every_file_lands_in_exactly_one_shard(count: int) -> None:
    files = suite_files()
    seconds, together = load_shard_times()
    plan = shard_plan(files, seconds, together, count)
    assert sorted(plan) == files
    assert set(plan.values()) <= set(range(1, count + 1))


def test_files_named_together_share_a_shard() -> None:
    seconds, together = load_shard_times()
    assert together, "shard-times.json names no group; the heavy archive tests need one (#5840)"
    plan = shard_plan(suite_files(), seconds, together, 4)
    for group in together:
        present = [name for name in group if name in plan]
        assert present, f"no file of {group} exists any more"
        assert len({plan[name] for name in present}) == 1, group


def test_an_unknown_file_still_gets_a_shard() -> None:
    plan = shard_plan(["test_new.py", "test_old.py"], {"test_old.py": 50.0}, [], 2)
    assert plan == {"test_old.py": 1, "test_new.py": 2}


def test_the_deal_balances_by_seconds() -> None:
    seconds = {"test_a.py": 10.0, "test_b.py": 6.0, "test_c.py": 5.0}
    plan = shard_plan(sorted(seconds), seconds, [], 2)
    assert plan == {"test_a.py": 1, "test_b.py": 2, "test_c.py": 2}


@pytest.mark.parametrize("bad", ["0/4", "5/4", "2", "a/b", "2/0"])
def test_a_bad_shard_value_is_refused(bad: str) -> None:
    with pytest.raises(pytest.UsageError):
        parse_shard(bad)


def _collected(*extra: str) -> set[str]:
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         str(TESTS_ROOT), *extra],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    return {line for line in done.stdout.splitlines() if "::" in line}


def test_real_collection_under_shards_adds_up_to_the_whole() -> None:
    whole = _collected()
    parts = [_collected("--shard", f"{index}/3") for index in (1, 2, 3)]
    assert all(parts), "a shard collected nothing"
    union: set[str] = set[str]().union(*parts)
    assert union == whole
    assert sum(len(part) for part in parts) == len(whole), "a test ran in two shards"
