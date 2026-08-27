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
