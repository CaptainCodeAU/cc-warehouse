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

---

## ADDENDUM 2026-09-07: a THIRD question sits before the other two, and it is a live false green

Filed after the `fifty-shades-of-dotfiles` session red-teamed its own narrowed watcher and
found that a `true` in `enabledPlugins` plus a registry entry are not evidence the code is
present, because the plugin runs from a cached clone at a recorded `installPath` that can
simply be gone. Handed over as an observation about their side. It is also true of ours,
and PROVED here by execution rather than accepted on report.

### The chain, in order

1. Is a hook REGISTERED? Doctor answers this.
2. Is the file it names still THERE? **Doctor does not reliably answer this.**
3. Can that file EXECUTE? Doctor does not answer this (the original body of this proposal).

### The measurement

`_mentions_ccw` (doctor.py:121) has two paths and only the second checks the filesystem:

```python
if any(name in command for name in _OUR_COMMANDS):   # ("ccw", "cc-warehouse")
    return True                                       # <- no file check at all
for token in command.split():
    ...
    if candidate.suffix not in {".py", ".sh", ".ts", ".js"} or not candidate.is_file():
        continue                                      # <- this path DOES check
```

Our own registered command is `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/ccw-hook.py`. The
substring `ccw` appears in the FILENAME, so the first path fires and returns before the
second is ever reached. Run directly on 2026-09-07:

```
_OUR_COMMANDS = ('ccw', 'cc-warehouse')
string-match path fires on our command? True ['ccw']
_mentions_ccw(cmd, Path('/nonexistent/plugin/root')) -> True
```

So `ccw doctor` reports `ok  hook  SessionEnd capture hook found via
cc-capture@cc-warehouse: ...` for a plugin root that does not exist. Delete the cache
folder and the `hook` line stays green. That is a false green of exactly the shape 0.1.2
fixed one instance of, and the wrapper-following path this proposal's own machinery would
build on is the half that already gets it right.

### Why this is NOT a one-line fix, which is why it is filed rather than shipped

Requiring a file unconditionally would BREAK a legitimate registration. A hook registered
as a bare `ccw hook` in settings.json names no script path at all, because the command is
resolved from PATH. The string-match path exists precisely to accept that form. The
correct rule is
narrower than "always require a file":

> if the command contains a token that LOOKS like a script path (one of the known script
> suffixes), that file must exist, whatever else the command string mentions.

That is a real behaviour change to a check two external tools have depended on, so it
needs the principal's scoping, not a session's judgment. Note also that it converts a
current false `ok` into a real FAIL, which changes `ccw doctor`'s exit code on an affected
machine, and that exit code is the signal `ccw-freshness-check.py` escalates on.

### Cheap and separate

The registry already records `installPath`. Doctor already reads that registry to name the
live plugin in its `hook` line (the `enabledPlugins` gate added 2026-08-23). Reporting
whether that recorded path still exists is a third field using machinery doctor already
has, and it answers question 2 without touching `_mentions_ccw` at all.
