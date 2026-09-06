# Agent setup contract

**Audience: an AI coding agent (e.g. a Claude Code session), not a human reader.**
A human was told to paste a prompt into a session like this one, pointing at this file,
because a detection script found this machine's `cc-warehouse` setup incomplete or stale.
Your job is to read this whole file, check the real state of this machine against it,
fix what's missing, and report back to the human in plain language what you found and
changed. Don't skip sections. Don't assume the detection script's prompt told you which
checks failed - re-run the checks yourself, because state can change between the script
running and you starting.

Schema version 1, written 2026-09-06. If this file looks older than a couple of months
relative to today, sanity-check the config key names below against
`src/cc_warehouse/config.py`'s own docstring before trusting them - this project's config
schema has changed shape twice already (2026-08-01, 2026-08-02) and this file could be
behind.

## Rules that override everything below

- **Never delete, move, or modify anything under a warehouse's `objects/`, `projections/`,
  or archive folders, or any existing session data anywhere.** This document only ever
  adds missing setup. If a fix would require touching existing session data, stop and
  ask the human instead of proceeding.
- If a config file already exists, **merge in only the missing keys**. Never overwrite an
  existing `config.toml` wholesale - you could erase a per-project override or a setting
  the operator chose on purpose.
- Anything marked **ASK FIRST** below means: use your question tool (e.g. `AskUserQuestion`)
  and wait for an answer before making that specific change. Don't batch it in with the
  safe fixes.
- When you're done, tell the human plainly: what you checked, what was already fine, what
  you changed, and what you asked them versus decided yourself. Don't say something is
  "fixed" unless you re-ran the check and saw it pass.

## Step 0: is `ccw` even installed?

```
command -v ccw
```

If this fails, `cc-warehouse` isn't installed on this machine at all. Install it:

```
uv tool install cc-warehouse
```

(Confirm `uv` itself exists first - `command -v uv` - and if not, that's outside this
document's scope; tell the human `uv` needs installing before you can continue.)

Once installed, re-run `command -v ccw` to confirm, then continue to Step 1.

## Step 1: run the real health check

```
ccw doctor
```

This one command already checks most of what matters: whether the SessionEnd capture
hook is registered (via the `cc-capture` plugin), whether it has actually fired, whether
recent captures rendered without errors, what version is running, and what the current
config resolves to. Read its full output before doing anything else - don't act on a
guess about what it says.

A healthy result ends with `doctor: capture is working` and every line reads `ok`. If you
see that, capture itself is fine; skip to Step 3 (config) since `doctor` does not treat a
missing archive setup as a failure (see below) - that's the one thing it stays quiet
about on purpose.

## Step 2: fix whatever `doctor` flagged as not-ok

| `doctor` line reads | Meaning | Fix |
|---|---|---|
| `hook` FAIL | No SessionEnd capture hook registered at all | See "Installing the plugin" below |
| `hook` ok but names something that isn't `ccw-hook.py` | A stale doctor version may be misreporting - see CHANGELOG 0.1.2. Check `ccw --version`; if it's below 0.1.2, upgrade (Step 4) and re-check before assuming the hook itself is broken |
| `fired` FAIL | Hook is registered but has never run | Usually means no session has ended since install - not a bug, just wait for one, or tell the human |
| `desync` reports problems | Some captured sessions failed to render | Run `ccw repair` (safe, idempotent, only touches its own generated files) and re-check |
| `install` reports anything other than `frozen: running from ...` | The install is "editable" - a live view of a working source tree, which means a half-finished code change could run in production | Flag this to the human; don't try to fix it yourself, since fixing it means knowing which source tree it should be frozen from, which you can't guess |

### Installing the plugin (if `hook` reads FAIL)

Use the real CLI commands, not a hand-edited settings file - `enabledPlugins` alone
doesn't install anything; it just flags something Claude Code otherwise already has:

```
claude plugin marketplace add https://github.com/CaptainCodeAU/cc-warehouse.git
claude plugin install cc-capture@cc-warehouse
```

Both are ordinary CLI commands and work outside an interactive session too.

### Updating a stale plugin

If `~/.claude/plugins/marketplaces/cc-warehouse` exists but is many commits behind this
project's GitHub `master` (check with `git -C <that path> log -1`, compare against the
repo), update it:

```
claude plugin update cc-capture@cc-warehouse
```

**Do not add `-y` / `--yes` here unless you are certain you want to.** That flag accepts
whatever install command the marketplace declares *at update time*, not just "yes to this
update" - it's a supply-chain-relevant confirmation, not a convenience skip. Run it without
`-y` and read what it shows before confirming, or ASK FIRST if you can't read the prompt
output directly.

Also: **the update needs a restart to take effect.** If you check `ccw doctor` again
immediately in this same session, it may still report the pre-update state. Tell the human
a restart is needed to confirm the update took, rather than declaring it done.

## Step 3: warehouse configuration

Check whether a config file exists:

```
cat ~/.config/cc-warehouse/config.toml
```

If this file doesn't exist, `ccw` is running on built-in defaults: everything gets
written to `~/cc-warehouse-data/objects/` and `~/cc-warehouse-data/projections/` (the
old "vault" layout), with no second copy anywhere and no scheduled catch-up. This is
**not an error and `ccw doctor` will not flag it** - it's a deliberate silent fallback, by
design, so a missing config never blocks a capture (see `config.py`'s own comment on
`archive_root`). That means "running on defaults" and "configured the way the operator
wants" look identical from `doctor`'s output alone - you have to check the file yourself.

**ASK FIRST, before creating or changing this file**, since it's a real decision about
where months of future data will live:

- Does the operator want an archive-first layout (a second, human-readable copy of every
  session, kept current automatically) on this machine? If yes, ask what path
  (`~/cc-warehouse-archive` is this project's own convention on its other machines, but
  don't assume - ask).
- If they say yes, write (creating the file and its parent directory if needed, merging
  rather than overwriting if the file already exists):

  ```toml
  archive_root = "/home/<user>/cc-warehouse-archive"   # or the path they gave you
  ```

  Leave `root`, `keep_objects`, and `keep_projections` at their defaults (unset). Do
  **not** set `keep_objects = false` or `keep_projections = false` on a fresh setup -
  those are meant to be flipped only after the archive has been proven correct over time
  on that specific machine (this project's own history calls this a two-stage migration,
  not a first-day setting). If the operator specifically asks to reclaim the duplicate
  space immediately, ASK FIRST again before setting either to false, and only do it if
  `archive_root` is already set and confirmed working.

- If they say no (or you're not sure), leave the file absent or unchanged. Vault-only is
  a fully supported, working mode - it's what one of this project's own machines runs
  today.

## Step 4: version currency

```
ccw --version
```

Compare against the latest release on PyPI (`cc-warehouse` - that is this project's real,
confirmed published name; don't confuse it with `claude-code-transcripts`, an unrelated
tool with a history of name-collision problems that has nothing to do with this project).
This project auto-publishes to PyPI on every version bump, so PyPI's latest is a reliable
target - a git tag is not, because the machine that develops this project intentionally
runs a different build (a frozen local install, not PyPI) than every other machine should.

If behind:

```
uv tool upgrade cc-warehouse
```

Then re-run `ccw doctor` to confirm the new version is what's actually running.

## Step 5: scheduled catch-up jobs (optional, ASK FIRST)

The live SessionEnd hook is enough on its own for capture to work - this is proven: one
of this project's own machines runs with no scheduled jobs at all and captures fine.
Scheduled jobs only add a safety net (catching a session the live hook somehow missed)
and, if `archive_root` is set, keep that second copy current without manual runs.

This project has only written and tested the **macOS (`launchd`)** version of this
automation - see `docs/operations.md` for the exact four jobs, schedules, and commands.
There is currently **no tested Linux/systemd or cron equivalent in this project.** If
you're setting this up on Linux or WSL and the operator wants the same safety net, ASK
FIRST whether they want you to improvise a `systemd --user` timer or cron entry
translating `docs/operations.md`'s schedule - don't invent one silently, since it hasn't
been tested here.

## Reporting back

Close with a plain summary covering, at minimum:
- Whether `ccw` was already installed, and what version is running now.
- Whether the capture hook was already working, and anything you had to install or fix.
- Whether a config file existed, what (if anything) you added, and what you asked the
  operator versus decided yourself.
- Anything you found but deliberately did not touch, and why (usually: it needs a human
  decision, or it's outside this document's scope).
