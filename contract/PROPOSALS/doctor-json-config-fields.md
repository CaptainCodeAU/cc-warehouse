# `ccw doctor --json` should expose config-presence separately from the verdict - proposal

**Status: proposal, not a ticket.** Written 2026-09-06 during a cross-session design
exchange with the `fifty-shades-of-dotfiles` project (its own installer is being taught to
provision `ccw` on new machines) while building `docs/agent-setup-contract.md`. Not
scoped or reviewed by this project's own process yet. The point of this document is to
hand over the requirement and the evidence behind it, not a finished design - whoever
picks this up should verify the current `doctor.py` shape before implementing, since it
may have changed since this was filed.

## The requirement

Whenever `ccw doctor` grows a machine-readable (`--json`) output mode - itself a separate,
larger proposal, since today's plain-text output is already a public interface two
external tools regex-parse (`ccw-watch`, this repo's own `ccw-freshness-check.py`) - it
needs at least these two fields exposed **separately from the overall pass/fail verdict**:

- whether a config file (`~/.config/cc-warehouse/config.toml` or the XDG-tier file) is
  present at all
- whether `archive_root` is set

## Why the overall verdict can't carry this

`config.py`'s `load_config()` treats a missing config file, and a missing `archive_root`
specifically, as a fully supported, intentional state (see its own comment on
`archive_root`: `None` means "the capture path behaves exactly as it did before" the
archive-first feature existed). `ccw doctor`'s `uncaptured` line reflects this by design -
it reads `ok` even with no archive configured, just noting "(no archive configured; set
archive_root to track this)" - because a missing config must never look like a health
failure (R5: a config problem can't be allowed to block a capture, and doctor inherits
that posture).

That's correct for doctor's own job. But it means "capture works" and "this machine is
configured the way the operator intended" are different questions with identical
`doctor` output today, and any external tool that wants to ask the second question - "is
this machine on the setup I want, not just a working one" - can't get the answer from
doctor's exit code or its existing lines alone. It has to reach around doctor and check
the file's existence directly, which is exactly the kind of behind-the-back check this
project's own `doctor` line was built to make unnecessary for everything else.

## The real-world case that forced this

`mlbox-ubuntu`, one of this operator's own machines, ran for roughly a month on the old
vault-only layout (no `archive_root`, no config file at all) after the archive-first
redesign shipped elsewhere. `ccw doctor` reported healthy on that machine the entire time
- correctly, by its own contract - because capture genuinely was working. Nothing was
broken; nothing was watching for "configured as intended" as a distinct condition either.

## What this unblocks

The `fifty-shades-of-dotfiles` installer's own provisioning trigger (2026-09-06 ruling,
operator-confirmed on both sides of this exchange) is a config-file-existence check
specifically because of this gap - it can't safely key off `doctor`'s exit code alone.
Exposing these two fields directly would let that installer (and anything similar later)
read a structured answer instead of independently re-deriving "is this machine
configured" by reaching into `~/.config/cc-warehouse/` itself, which is fragile in
exactly the way the `--json` proposal already exists to fix for everything else `doctor`
reports.
