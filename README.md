# cc-warehouse

[![PyPI](https://img.shields.io/pypi/v/cc-warehouse.svg)](https://pypi.org/project/cc-warehouse/)
[![Python](https://img.shields.io/pypi/pyversions/cc-warehouse.svg)](https://pypi.org/project/cc-warehouse/)
[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue.svg)](https://github.com/CaptainCodeAU/cc-warehouse/blob/master/LICENSE)

Turn your Claude Code sessions into a readable, permanent archive.

`cc-warehouse` captures every session as it ends, stores the original JSONL
untouched, and renders it into markdown and HTML you can actually read, search
and share. The result is a plain folder tree: no database to keep alive, no
service to run, nothing that stops working when the tool does.

```
ccw doctor        # is capture working, and if not, since when?
ccw archive --to ~/my-archive
```

## Why

Claude Code writes each session to `~/.claude/projects/<project>/<uuid>.jsonl`
and does not promise to keep it. The file is newline-delimited JSON built for a
program to replay, not for a person to read: tool calls, thinking blocks, system
reminders and prose all interleaved.

`cc-warehouse` solves both halves of that:

- **Durability.** Sessions are copied out on capture and never modified or
  deleted afterwards. Every write is atomic (temp file plus `os.replace`), so an
  interrupted run cannot leave a half-written file.
- **Readability.** Each session becomes four rendered files beside its raw
  JSONL, in a folder named so it sorts chronologically and means the same thing
  on any machine.

## Install

```bash
uv tool install cc-warehouse
```

or with pipx:

```bash
pipx install cc-warehouse
```

Requires Python 3.12+. The runtime uses **only the standard library**: no
third-party packages are pulled in, at install time or at run time.

Both `ccw` and `cc-warehouse` are installed as entry points; `ccw` is used
throughout this document.

## Quick start

Import everything Claude Code has written so far, then build the archive:

```bash
ccw sweep --dry-run          # show what would be imported; writes nothing
ccw sweep                    # import it
ccw archive --to ~/my-archive
ccw archive --to ~/my-archive --verify
```

Every command that writes accepts `--dry-run`, and it is enforced centrally
rather than per-command, so a dry run cannot quietly modify anything.

To capture new sessions automatically, register `ccw hook` as a **SessionEnd**
hook in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionEnd": [
      { "hooks": [ { "type": "command", "command": "ccw hook", "timeout": 45 } ] }
    ]
  }
}
```

Then confirm it is actually running:

```bash
ccw doctor
```

`ccw doctor` exists because a hook that never fires produces no error, and silence
and idleness look identical. It reports whether a capture hook is registered,
when the last capture happened, and how the tool is installed.

## What you get

```
my-archive/
└── myuser-my-project/
    └── 20260608-171250+1000_e27cb3f8-99fe-4144-98eb-04bcac53c956/
        ├── e27cb3f8-99fe-4144-98eb-04bcac53c956.jsonl   original, byte for byte
        ├── transcript.md                                 full conversation
        ├── transcript.compact.md                         prose only
        ├── conversation.html                             full, self-contained
        ├── conversation.compact.html                     prose only, self-contained
        └── manifest.json                                 what produced these files
```

The folder name is `<YYYYMMDD-HHMMSS><offset>_<session-uuid>`. The UTC instant is
converted using a timezone pinned in config rather than read from the machine
clock, so the same session produces the same folder name anywhere. The offset is
part of the name because zones with daylight saving make a bare local timestamp
ambiguous once the tool that wrote it is gone.

`manifest.json` records `config`, `counts`, `source_hash`, `subagents`, and three
separate accounting keys that are deliberately not merged:

| Key | Means |
|---|---|
| `loss` | content the renderer dropped |
| `unrecognised` | entry types this parser does not name yet |
| `withheld` | content that never arrived from Claude Code |

Keeping them apart matters: an entry that rendered as a marker is not a lost one,
and a new Claude Code entry type increments `unrecognised` instead of vanishing
silently.

## Commands

| Command | Purpose |
|---|---|
| `ccw hook` | capture a session from a SessionEnd payload on stdin |
| `ccw sweep` | import transcripts the hook missed (`--source DIR`) |
| `ccw archive` | build, or `--verify`, the archive tree at `--to DIR` |
| `ccw render` | rebuild one session's files, or render an ad-hoc transcript |
| `ccw build` | rebuild projections from the catalog |
| `ccw share` | build a sanitized static site for chosen sessions |
| `ccw status` | recent captures, counts, store size, last errors |
| `ccw doctor` | is capture working, and if not, since when |
| `ccw verify` | re-hash stored objects and cross-check the catalog |
| `ccw reindex` | rebuild the catalog from the archive tree alone |
| `ccw project` | list / show / rename / move / merge projects |
| `ccw import` | adopt a foreign transcript tree (`--from DIR`) |
| `ccw migrate` | one-shot import of a legacy archive |
| `ccw relocate` | repair paths after a project directory moves |
| `ccw version` | print the version |

Run `ccw <verb> -h` for a command's options.

## Sharing

`ccw share` builds a static site for chosen sessions, scrubbing secret-shaped
content first. API keys, tokens and private key blocks are detected and
replaced before anything is written.

```bash
ccw share s:a1b2c3d4 --out ./public-site
```

Shared pages inline their own syntax highlighting and make **no third-party
requests**, so opening one does not tell anyone else that you did. Publishing
unscrubbed content is possible but requires an explicit flag whose name is meant
to be uncomfortable to type.

See [docs/sharing-and-redaction.md](https://github.com/CaptainCodeAU/cc-warehouse/blob/master/docs/sharing-and-redaction.md) for what is
detected and what is not.

## Configuration

Configuration is TOML, read from two locations, lowest precedence first:

1. `~/.config/cc-warehouse/config.toml` (or `$XDG_CONFIG_HOME`)
2. `<data-root>/config.toml`

Per-project overrides go in a `[project.<id>]` section. Environment variables
(`CCW_ROOT`, `CCW_SKIP_HOOK`, `CCW_VOICE_URL`, `CCW_VOICE_ID`, `CCW_OPEN_FOLDER`,
`CCW_WEBHOOKS`) override files, and command-line flags override everything.

The data root defaults to `~/cc-warehouse-data` and can be moved with `CCW_ROOT`
or the `root` key.

An invalid value is never silently replaced by a default: it is recorded as a
config error and the default is kept, so a typo is visible rather than merely
survivable.

## Design notes

A few properties are structural rather than incidental:

- **Sessions are never deleted or modified.** Sources and stored objects are
  read-only to this tool.
- **Every write is atomic**, so a crash or a full disk cannot corrupt a file that
  was already good.
- **Batch operations name what failed and continue** rather than aborting on the
  first bad item, so one malformed session cannot hide the other 10,000.
- **Identity is content, not path.** Moving or renaming a project directory does
  not create duplicates or orphans.

## Development

```bash
git clone https://github.com/CaptainCodeAU/cc-warehouse
cd cc-warehouse
uv sync

uv run pytest          # oracle suite
uv run pyright         # strict mode
uv run ruff check
```

`pyright` in strict mode and `ruff` are merge gates. Tests may import `pytest`;
nothing else third-party is permitted anywhere in the project.

New to uv? `curl -LsSf https://astral.sh/uv/install.sh | sh` and nothing else is
needed. **Installing cc-warehouse from PyPI requires no special setup at all** and
is unaffected by everything in the next paragraph, which applies only if you
clone this repository.

### The pinned resolution cutoff

`pyproject.toml` sets `[tool.uv] exclude-newer` to a fixed date. uv refuses to
resolve any package published after it, and records the cutoff in `uv.lock`, so a
clone resolves the same dependency versions today as it did months ago rather than
whatever is newest.

Two consequences worth knowing before it surprises you:

- **`uv add <package>` resolves against the index as of that date**, so a recent
  release will look missing. That is the pin working. Move the date in the same
  commit, and run `uv lock` so the recorded cutoff matches.
- **An exported `UV_EXCLUDE_NEWER` overrides the pin**, because the environment
  outranks project configuration in uv. If your shell sets one (some
  supply-chain-hygiene setups export a rolling value), your `uv.lock` will show a
  different cutoff than the pin and appear permanently modified. Unset it for this
  repository, or leave the lock alone.

The full precedence, measured on uv 0.12.1 rather than assumed, is recorded in the
comment above the setting in `pyproject.toml`.

### Releasing

`RELEASING.md` carries the checklist, the versioning rules, and the one-time
Trusted Publishing setup. The rule most easily missed: **a change to the default
rendered output is a breaking change**, because a user's archive is something they
read and link to. `tests/golden/matrix-anchor` enforces it mechanically.

## Status

Capture, rendering, the archive tree, sharing, and the integrity and diagnostic
commands are implemented and in daily use. Full-text search (`ccw search`) and an
MCP server (`ccw mcp`) are planned.

Changes are recorded in [CHANGELOG.md](https://github.com/CaptainCodeAU/cc-warehouse/blob/master/CHANGELOG.md).

## License

[PolyForm Noncommercial 1.0.0](https://github.com/CaptainCodeAU/cc-warehouse/blob/master/LICENSE). Free for noncommercial use: personal
projects, research, and evaluation. **Commercial use requires a separate
license.** This is a source-available license, not an OSI-approved open source
one; please read it before depending on this in a business context.
