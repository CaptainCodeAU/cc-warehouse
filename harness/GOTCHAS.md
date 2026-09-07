# Environment gotchas that will bite

Recurring, task-independent facts about this machine and this repo's dev environment.
Not chronological, not tied to any one ticket - check this file whenever one of these
symptoms shows up, regardless of what else you're working on. (Split out of
`OPENING-PROMPT.md` on 2026-08-27, which used to call this section "Two environment
facts" while actually holding five - fixed here.)

- **`ccw doctor` run from inside this repo reports `editable`, and that is not
  a rule violation.** `.envrc` (tracked 2026-08-21) sources `.venv/bin/activate`,
  so `.venv/bin/ccw` shadows `~/.local/bin/ccw` on PATH and doctor truthfully
  describes the venv copy - not what the hook runs. The install IS frozen.
  Unambiguous check:
  `env -u VIRTUAL_ENV PATH="$HOME/.local/bin:/usr/bin:/bin" ~/.local/bin/ccw doctor`
- **`cp` is INTERACTIVE in this shell, so a `cp` that overwrites an existing
  file blocks forever on `overwrite <path>? (y/n [n])`** instead of finishing
  (2026-09-04). The Bash tool cannot answer that prompt, so the call burns its
  whole timeout and every command after it in the same invocation never runs.
  The dangerous case is a restore-from-backup step: the copy that PUTS the
  backup down is the one that hangs, so the deliberately-modified file is left
  in place looking finished. Both `rm` and `mv` are wrapped the same way (see
  the deletion-safety rule in the global CLAUDE.md), so assume any of the three
  may prompt. Write the backup back with Python instead, which is also the
  project's own R2 write convention:
  `tmp.write_bytes(backup.read_bytes()); os.replace(tmp, target)`, then compare
  sha256 to prove the restore actually landed.
- **The SSH key drops out of the agent** (ticket 28.15, seen more than once).
  `ssh-add -l` reports "no identities" and `git push` fails on access rights.
  Any commits made while this is happening land LOCAL AND UNPUSHED - the operator
  must run `ssh-add` themselves; a session cannot.
- **`file://` navigation is refused by the Chrome browser tool**
  (`mcp__claude-in-chrome__navigate`), even to a brand-new tab -
  "Can't interact with browser-internal or unparseable URLs." To visually
  check any local HTML file, serve its directory over loopback first:
  `uv run python3 -m http.server <port> --bind 127.0.0.1` from that directory,
  navigate to `http://127.0.0.1:<port>/file`, then kill the server when done.
  Worked cleanly every time this has been tried.
- **Testing any ccstats script without touching real data**: set
  `CCSTATS_OUT=<scratch dir>` before running `collect.py`, `dashboard.py`,
  or `/dashboard` (its Step 0 honours the same variable). Everything lands in
  the scratch folder instead of `~/.cc-warehouse/stats`, and `resolve_out`
  still refuses the dangerous roots (this repo, `~/.claude`, the archive, the
  warehouse data root) even for the scratch value.
- **A fresh Claude Code session's numbered-choice UI, driven via Herdr's
  `herdr agent prompt`, does not respond to a literal digit** - sending `"2"`
  does not select option 2; Enter just confirms whichever option is already
  highlighted (the default). Send the option's actual wording as text
  instead, or use `herdr agent send-keys <name> <key>` for real arrow-key
  navigation.
- **`uv_tool_reinstall_current_project` fails from an agent's Bash tool until
  the function file is sourced.** The wrapper is on PATH as a shell function but
  its private helper is not, so the first call dies with
  `uv_tool_reinstall_current_project:19: command not found: _uv_tool_parse_flags`.
  Source the shell function file that defines it first (it lives in the operator's
  dotfiles repo and is not installed into `$HOME`; find it with
  `grep -rl _uv_tool_parse_flags` over the dotfiles checkout), then run
  `uv_tool_reinstall_current_project --no-extras` as normal. Harmless, but it reads
  like the frozen-install rule is broken when it is not; seen 2026-09-08.
  The concrete path is deliberately NOT written here: `test_packaging.py`'s leak
  scan fails on any `/home/<name>` segment, and that dotfiles repo has a literal
  `home/` directory, so naming the path trips the fence with a FALSE positive. The
  fence is right to fail closed; the path simply does not belong in a public repo.
- **This repository had NO push-to-master CI until 2026-09-08.** The only workflow
  fired on a `v*` tag, so the first Linux run of any change was its release run,
  and a Linux-only failure cost a failed release before anyone saw it (see
  `harness/tickets/38-*.md`). `.github/workflows/gates.yml` now runs the same three
  gates on every push to master and every PR. If you are about to tag a release,
  the useful check is that the gates run on the commit you are tagging is already
  green - not that the suite passes on your laptop, which is a different runner
  with different timing.
