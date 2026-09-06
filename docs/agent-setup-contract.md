# Agent setup contract

**Audience: an AI coding agent (e.g. a Claude Code session), not a human reader.**

## The boundary this document sits behind (ruled 2026-09-06)

The dotfiles installer that provisions this machine owns the deterministic parts of
`ccw`'s lifecycle and does them itself, every run, with no AI involved:

- Installing `ccw` if it's missing (`uv tool install cc-warehouse`).
- Upgrading it if it's behind the latest PyPI release (`uv tool upgrade cc-warehouse`).
- Installing and enabling the `cc-capture` plugin if it isn't present at all yet
  (`claude plugin marketplace add` + `claude plugin install` - a first-time install has
  no existing command to change, so there's nothing here that needs a human review).

**You are being invoked because something was found that the installer deliberately does
not resolve on its own** - it needs a decision, not automation. The installer's own
trigger for handing off to you is **whether `~/.config/cc-warehouse/config.toml`
exists**, not whether `ccw doctor` exits cleanly - `doctor` treats a missing config as
fine by design (see Step 2), so exit-code-only detection would have called one of this
project's own real machines perfectly healthy for a month while it sat on a legacy
layout nobody had chosen on purpose. If you land here, treat that as the operator caring
whether this machine is *configured the way they intend*, not just whether capture
happens to work.

Read this whole file before doing anything. Don't assume the prompt that brought you
here told you everything that's wrong - re-run the checks below yourself, since machine
state can drift between the installer running and you starting.

Schema version 2, written 2026-09-06 (revised same day after the installer/agent
boundary above was settled - version 1 had the AI doing the installer's job too). If this
file looks older than a couple of months relative to today, sanity-check the config key
names in the "Configuration" step against `src/cc_warehouse/config.py`'s own docstring -
this project's config schema has changed shape twice already (2026-08-01, 2026-08-02).

## Rules that override everything below

- **Never delete, move, or modify anything under a warehouse's `objects/`, `projections/`,
  or archive folders, or any existing session data anywhere.** This document only ever
  adds missing setup. If a fix would require touching existing session data, stop and
  ask the human instead of proceeding.
- If a config file already exists, **merge in only the missing keys**. Never overwrite an
  existing `config.toml` wholesale - you could erase a per-project override or a setting
  the operator chose on purpose.
- Anything marked **ASK FIRST** below means: use your question tool (e.g. `AskUserQuestion`)
  and wait for an answer before making that specific change. Don't batch it in with
  anything else.
- When you're done, tell the human plainly: what you checked, what was already fine, what
  you changed, and what you asked them versus decided yourself. Don't say something is
  "fixed" unless you re-ran the check and saw it pass.

## Step 1: confirm what the installer should already have handled

These are the installer's job, not yours - but confirm them, since you were handed this
prompt and shouldn't assume anything:

```
command -v ccw && ccw --version
```

If `ccw` is genuinely missing, or its version is behind the latest PyPI release of
`cc-warehouse`, the installer's own mechanical step didn't run or failed. Tell the human
that plainly rather than quietly doing the installer's job yourself - it's worth them
knowing the installer itself needs attention, not just this machine's `ccw` config.

```
ccw doctor
```

Read the full output. `hook` should read `ok` and name `cc-capture@cc-warehouse` as the
registered SessionEnd hook - if it doesn't, or if it names something that clearly isn't
the capture hook (a stale-doctor-version symptom described in CHANGELOG 0.1.2), the
plugin install step also didn't complete. Same as above: say so, don't silently redo it.

## Step 2: the actual reason you're here - configuration

The installer handed off to you specifically because `~/.config/cc-warehouse/config.toml`
doesn't exist (or, less commonly, exists but looks incomplete or wrong). This step is
your real job.

No config file means `ccw` is running on built-in defaults: everything gets written to
`~/cc-warehouse-data/objects/` and `~/cc-warehouse-data/projections/` (the old "vault"
layout), with no second copy anywhere and no scheduled catch-up. This is **not an error
and `ccw doctor` will not flag it** - it's a deliberate silent fallback, by design, so a
missing config never blocks a capture (see `config.py`'s own comment on `archive_root`).
Vault-only is a fully supported, working mode - it's what one of this project's own
machines runs today - so don't treat "no config" as broken. It just means nobody has told
`ccw` what this operator actually wants yet, and that's what you're here to find out.

**ASK FIRST**, since this is a real decision about where months of future data will live:

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

- If they say no (or you're not sure), leave the file absent or unchanged, and tell the
  human that's a supported choice, not a gap.

## Step 3: a plugin update that needs a human on the accept

If `ccw doctor` or the installer flagged the plugin as installed but many commits behind
this project's GitHub `master`, that update is your job specifically, not the installer's
- because updating an *existing* install is different from a fresh one:

```
claude plugin update cc-capture@cc-warehouse
```

**Do not add `-y` / `--yes` here unless you are certain you want to.** That flag accepts
whatever install command the marketplace declares *at update time*, not just "yes to this
update" - it's a supply-chain-relevant confirmation, not a convenience skip. This is
exactly why this step isn't the installer's to automate. Run it without `-y` and read what
it shows before confirming, or ASK FIRST if you can't read the prompt output directly.

Also: **the update needs a restart to take effect.** If you check `ccw doctor` again
immediately in this same session, it may still report the pre-update state. Tell the human
a restart is needed to confirm the update took, rather than declaring it done.

## Step 4: scheduled catch-up jobs (optional, ASK FIRST)

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
- Whether the installer's own steps (ccw present and current, plugin installed) had
  actually completed correctly, or whether you found and flagged a gap there instead.
- Whether a config file existed, what (if anything) you added, and what you asked the
  operator versus decided yourself.
- Anything you found but deliberately did not touch, and why (usually: it needs a human
  decision, or it's outside this document's scope).
