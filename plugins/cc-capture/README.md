# cc-capture

Captures each Claude Code session into cc-warehouse when the session ends.

## Install

```
/plugin marketplace add https://github.com/CaptainCodeAU/cc-warehouse.git
/plugin install cc-capture@cc-warehouse
```

It needs `ccw` on `PATH`:

```bash
uv tool install cc-warehouse
```

Then confirm it is actually wired up:

```bash
ccw doctor
```

`ccw doctor` exists because a hook that never fires produces no error. Silence and
idleness look identical, which is how a previous version of this plugin went ten
days without capturing anything.

## What it does

On `SessionEnd`, for any reason, it forwards the hook payload on stdin to
`ccw hook`, which owns everything else: naming, project resolution, the
idempotency skip, the archive folder, sub-agent capture, and rendering.

```
SessionEnd --> ccw-hook.py --> ccw hook --> <archive>/<project>/<stamp>_<uuid>/
```

The wrapper is deliberately thin. It resolves an executable, runs it, and reports.
Everything that could be a decision is a decision in `ccw`, where it is covered by
the oracle suite.

## Why it lives in the cc-warehouse repository

It used to live in a separate marketplace repository, and that separation is what
caused the outage this plugin's own code comments describe: the hook and the CLI
it calls were versioned independently, so a change to one could silently stop
working with the other, and nothing failed loudly enough to notice.

Here, the hook and the tool it invokes move together. A root
`.claude-plugin/marketplace.json` alongside a software project is a documented
shape; Anthropic's own `anthropics/claude-code` repository carries one.

## The two rules in the wrapper, both load-bearing

**1. Never resolve a bare package name.** The wrapper resolves a real executable
(`CCW_BIN`, then `PATH`, then the uv-tool shim) rather than asking an index to
find one. The original reason was that `cc-warehouse` was unregistered, so
`uv tool run cc-warehouse hook` would have run a squatter's code with a session
transcript on stdin. That hole closed when the name was published, but the rule
stays: resolving a name at hook time still means a network lookup, at session end,
unattended, with a transcript on stdin.

**2. A failure must be loud.** The hook always exits 0, because blocking session
end is worse than a missed capture. Every failure is instead written to
`~/.claude/logs/ccw-hook.log` and announced through the operator's notification
channel if one is configured.

## Configuration

None of its own. It reads these from the environment if set:

| Variable | Effect |
|---|---|
| `CCW_BIN` | use this executable instead of searching `PATH` |
| `CCW_VOICE_URL` | endpoint for spoken failure alerts, if you run one |
| `CCW_VOICE_ID` | voice to use at that endpoint |

`CCW_OPEN_FOLDER` is deliberately **not** set here. Set it in the environment if
you want the session's archive folder revealed after each capture.

Everything else is cc-warehouse configuration and belongs in
`~/.config/cc-warehouse/config.toml`.

## Troubleshooting

```bash
ccw doctor                          # is a hook registered, and has it ever fired
tail -5 ~/.claude/logs/ccw-hook.log # what happened on the last few session ends
```

A `hook` line reading FAIL means no capture hook is registered at all. A `fired`
line reading FAIL means one is registered but has never run, which usually means
the session has not ended since you installed it.
