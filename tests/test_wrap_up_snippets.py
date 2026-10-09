"""The /wrap-up command's Step 0 and Step 1 shell snippets, run for real.

Step 0 lists the last few sessions of this project and whether each closed with a
wrap-up. Step 1 finds SESSION_START_REF, the commit HEAD was at when the session
began, from git's HEAD reflog and the session's own transcript. Both read the session
id under either name. Until 2026-10-05 Step 0 read `$CLAUDE_SESSION_ID` alone, so in
an engage session (which sets only `CLAUDE_CODE_SESSION_ID`) its skip pattern became
`**` and skipped every file; and Step 1 needed a "Recent commits" block engage
sessions never get, so read literally it refused every run.

Each test builds a throwaway HOME and git repo and runs the snippet exactly as the
command file prints it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

COMMAND = Path(__file__).resolve().parents[1] / ".claude" / "commands" / "wrap-up.md"
SHELLS = [shell for shell in ("bash", "zsh") if shutil.which(shell)]
SID = "11111111-2222-3333-4444-555555555555"
A_TIME = 1_000_000_000  # 2001-09-09T01:46:40Z
B_TIME = A_TIME + 200


def _snippet(heading: str) -> str:
    text = COMMAND.read_text(encoding="utf-8")
    return text[text.index(heading) :].split("```bash", 1)[1].split("```", 1)[0]


def _env(home: Path, ids: dict[str, str], when: int | None = None) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID") and not key.startswith("GIT_")
    }
    env.update(
        HOME=str(home),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="Test",
        GIT_AUTHOR_EMAIL="test@example.invalid",
        GIT_COMMITTER_NAME="Test",
        GIT_COMMITTER_EMAIL="test@example.invalid",
    )
    if when is not None:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = f"@{when} +0000"
    env.update(ids)
    return env


def _git(repo: Path, env: dict[str, str], *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _run(shell: str, snippet: str, cwd: Path, env: dict[str, str]) -> str:
    done = subprocess.run(
        [shell, "-c", snippet],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _iso(epoch: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, Path, str, str]:
    """A repo with commit A then commit B, 200 s apart, and a HOME beside it."""
    home = tmp_path / "home"
    home.mkdir()
    main = (tmp_path / "repo").resolve()
    main.mkdir()
    _git(main, _env(home, {}, A_TIME), "init", "-q", "-b", "master")
    (main / "f").write_text("a\n")
    _git(main, _env(home, {}, A_TIME), "add", "f")
    _git(main, _env(home, {}, A_TIME), "commit", "-q", "-m", "A")
    commit_a = _git(main, _env(home, {}), "rev-parse", "HEAD")
    (main / "f").write_text("b\n")
    _git(main, _env(home, {}, B_TIME), "commit", "-q", "-am", "B")
    commit_b = _git(main, _env(home, {}), "rev-parse", "HEAD")
    return home, main, commit_a, commit_b


def _transcript(home: Path, began: int) -> None:
    folder = home / ".claude" / "projects" / "some-project"
    folder.mkdir(parents=True, exist_ok=True)
    line = {"type": "user", "timestamp": _iso(began), "sessionId": SID}
    (folder / f"{SID}.jsonl").write_text(json.dumps(line, separators=(",", ":")) + "\n")


def _start_ref(output: str) -> str:
    found = re.search(r"SESSION_START_REF=(.+)$", output.strip())
    assert found, output
    return found.group(1)


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("name", ["CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID"])
def test_step_1_finds_head_as_it_was_when_the_session_began(
    repo: tuple[Path, Path, str, str], shell: str, name: str
) -> None:
    home, main, commit_a, _ = repo
    _transcript(home, A_TIME + 100)
    output = _run(shell, _snippet("## Step 1"), main, _env(home, {name: SID}))
    assert _start_ref(output) == commit_a


@pytest.mark.parametrize("shell", SHELLS)
def test_step_1_from_a_worktree_made_later_uses_the_main_checkout(
    repo: tuple[Path, Path, str, str], shell: str
) -> None:
    home, main, commit_a, _ = repo
    tree = main / ".worktree" / "w"
    _git(main, _env(home, {}, B_TIME + 100), "worktree", "add", "-q", "-b", "w", str(tree))
    _transcript(home, A_TIME + 100)
    output = _run(shell, _snippet("## Step 1"), tree, _env(home, {"CLAUDE_CODE_SESSION_ID": SID}))
    assert _start_ref(output) == commit_a


@pytest.mark.parametrize("shell", SHELLS)
def test_step_1_says_not_measured_when_it_cannot_know(
    repo: tuple[Path, Path, str, str], shell: str
) -> None:
    home, main, _, _ = repo
    snippet = _snippet("## Step 1")
    _transcript(home, A_TIME + 100)
    assert _start_ref(_run(shell, snippet, main, _env(home, {}))) == "NOT MEASURED"
    other = {"CLAUDE_CODE_SESSION_ID": "99999999-0000-0000-0000-000000000000"}
    assert _start_ref(_run(shell, snippet, main, _env(home, other))) == "NOT MEASURED"
    _transcript(home, A_TIME - 86_400)  # began before the reflog does
    ours = {"CLAUDE_CODE_SESSION_ID": SID}
    assert _start_ref(_run(shell, snippet, main, _env(home, ours))) == "NOT MEASURED"


def _typed(command: str) -> str:
    content = (
        f"<command-message>{command}</command-message>\n<command-name>/{command}</command-name>"
    )
    return json.dumps(
        {"type": "user", "message": {"role": "user", "content": content}}, separators=(",", ":")
    )


def _write_session(folder: Path, sid: str, lines: list[str], mtime: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sid}.jsonl"
    filler = [json.dumps({"type": "assistant", "n": n}) for n in range(60)]
    path.write_text("\n".join(filler + lines) + "\n")
    os.utime(path, (mtime, mtime))


@pytest.mark.skipif(sys.platform != "darwin", reason="Step 0 uses macOS stat -f")
@pytest.mark.parametrize("shell", SHELLS)
def test_step_0_counts_both_wrap_ups_and_skips_this_session(
    repo: tuple[Path, Path, str, str], shell: str
) -> None:
    home, main, _, _ = repo
    slug = re.sub(r"[^a-zA-Z0-9]", "-", str(main))
    projects = home / ".claude" / "projects"
    pj_closed = "aaaaaaaa-0000-0000-0000-000000000000"
    typed_alone = "bbbbbbbb-0000-0000-0000-000000000000"
    quote = json.dumps(
        {"type": "user", "message": {"content": "see <command-name>/pj:wrap-up</command-name>"}},
        separators=(",", ":"),
    )
    _write_session(projects / slug, SID, [], B_TIME + 900)
    _write_session(projects / slug, pj_closed, [quote, _typed("pj:wrap-up")], B_TIME + 800)
    _write_session(projects / f"{slug}--worktree-w", typed_alone, [_typed("wrap-up")], B_TIME + 700)
    stub = projects / slug / "cccccccc-0000-0000-0000-000000000000.jsonl"
    stub.write_text(_typed("wrap-up") + "\n")
    os.utime(stub, (B_TIME + 850, B_TIME + 850))
    _write_session(
        projects / "some-other-project", "dddddddd-0000-0000-0000-000000000000", [], B_TIME + 860
    )
    wrapped = home / ".local" / "state" / "pj" / "wrapped"
    wrapped.mkdir(parents=True)
    (wrapped / pj_closed).write_text("")

    rows = _run(shell, _snippet("## Step 0"), main, _env(home, {"CLAUDE_CODE_SESSION_ID": SID}))
    lines = rows.strip().splitlines()
    assert [line[:8] for line in lines] == ["aaaaaaaa", "bbbbbbbb"]
    assert "wrap-up=0 pj:wrap-up=1 marked=yes" in lines[0]
    assert "wrap-up=1 pj:wrap-up=0 marked=no" in lines[1]

    alone = _run(shell, _snippet("## Step 0"), main, _env(home, {}))
    assert "no session id" in alone
    assert [line[:8] for line in alone.strip().splitlines()[1:]] == [
        "11111111",
        "aaaaaaaa",
        "bbbbbbbb",
    ]
