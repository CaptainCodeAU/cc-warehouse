# `ccw doctor` should check the hook can EXECUTE, not just that it is registered - proposal

**Status: proposal, not a ticket.** Filed 2026-09-07 during a cross-session exchange with
the `fifty-shades-of-dotfiles` project, whose installer is being taught to provision `ccw`
on new machines. Offered by that session as a proposal explicitly, not a demand, and filed
here rather than built because `doctor`'s behaviour is this project's to scope. Not
reviewed by this project's own process. Whoever picks it up should re-verify the current
`doctor.py` shape first.

## The gap

`ccw doctor`'s `hook` check answers one question: is a SessionEnd capture hook REGISTERED,
and by which plugin. It does not answer whether that hook can RUN. Those are different
questions, and the second one has a real failure mode today.

Both hooks in `plugins/cc-capture/hooks/` require Python 3.10 or newer. `hooks.json`
invokes them as a bare `python3`, so the interpreter is whatever the hook process's PATH
resolves, which no shell the operator can see necessarily shares.

## The evidence, measured 2026-09-07

`/usr/bin/python3` on the author's own Mac is **3.9.6**. Running either hook under it dies
immediately:

```
TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
```

That is PEP 604 (`str | None`) evaluated at import time, at `find_ccw`'s signature, which
sits above every one of the hook's own guards. Verified against the COMMITTED copy at
HEAD, not a working-tree edit, so it is long-standing rather than caused by a recent
change. Confirmed independently the same day by the `fifty-shades-of-dotfiles` session on
the same machine.

## Why it is worth a check rather than a docstring

The failure is silent on both sides at once:

- The hook dies before any of its own error handling can log or speak. `report()` is never
  reached, so nothing lands in `~/.claude/logs/ccw-hook.log` and nothing is said aloud.
- `ccw doctor` still reports the `hook` line as ok, because registration is intact.

So a machine in this state captures nothing and reports healthy. That is the exact shape
FINDINGS calls a false green, and `doctor` exists to make it impossible.

This Mac is currently safe only because its PATH puts a newer `python3` ahead of
`/usr/bin`. That is a property of one machine's PATH ordering. An installer provisioning a
fresh box cannot assume it.

## What it would take

Two things doctor does not do today:

1. Resolve `python3` the way the hook process would, rather than the way doctor's own
   parent shell does. Doctor cannot see the hook's environment directly, so this is the
   hard half and needs design rather than a one-liner.
2. Compare against the floor the hooks actually require, which is 3.10.

The hooks' own docstrings claim they are "kept portable by hand" for Ubuntu 22.04's 3.10.
That claim is true for 3.10 and false for 3.9, and nothing enforces it.

## The cheaper half, if the above is too invasive

The hooks cannot run at all under 3.9, so every successful line already in
`~/.claude/logs/ccw-hook.log` is proof by execution that the interpreter was 3.10+ at that
moment. Doctor already reads that log for its `fired` check. A hook that has never
successfully logged on a machine that has had sessions is the signal, and it needs no new
environment probing at all.

A hook that RECORDED its own `sys.version` in the `ok` record would make this exact and
permanent, at the cost of one field. That is a change to the hook rather than to doctor,
and it is the smaller of the two.

## Note for whoever picks this up

`ccw doctor`'s text output is a public interface that at least two external tools regex
parse (`ccw-watch`, and this repo's own `ccw-freshness-check.py`). Adding a line is
lower risk than changing one, but neither is free. See
`contract/PROPOSALS/doctor-json-config-fields.md`, which is blocked behind the same
constraint.
