# Sharing and redaction

Read this before you publish anything.

`ccw share` builds a static site from COPIES of your sessions. Your stored objects and
your personal projections are never modified: they keep full fidelity, and the sanitizing
happens on the way out.

This page states what that sanitizing does, and more importantly **what it does not do**.

```
ccw share s:<key> [s:<key> ...] --out <dir>
```

---

## What gets redacted automatically

Redaction runs on the **decoded** session payload before anything is rendered, so a value
written in the JSON as `secret` is caught as `secret`. It also means the redacted text
is what lands in the HTML copy-as-markdown payloads, not just in the visible page.

Built-in patterns, all derived from the machine you run `share` on:

| Pattern | Source |
|---|---|
| home directory | `$HOME`, matched as a literal path |
| username | `$USER`, matched at word boundaries |
| hostname | the system hostname, matched at word boundaries |
| email addresses | a generic address pattern |

Word boundaries mean a short username such as `bob` is redacted where it stands alone but
is not shredded out of unrelated words.

Add your own in `config.toml`:

```toml
[share]
redact_patterns = ["ACME-INTERNAL-[0-9]+", "my-private-hostname"]
```

These are regular expressions. Two different protections apply, and they work at different
moments:

- a pattern that **fails to compile** is dropped, so one bad entry never breaks the whole
  share;
- a pattern that **can match the empty string** (`x*`, `\b`) is still used, but zero-width
  matches are skipped while substituting, so it cannot insert a token between every
  character and corrupt the content.

---

## What is DETECTED but deliberately NOT redacted

Secret-shaped strings **abort the share**. Nothing is written.

```
share: secret-shaped high-entropy-token in ba5ad8cfe823 line 7; nothing written.
Re-run with --allow-findings to ship it.
```

Detected families: Anthropic keys, OpenAI keys, AWS access keys, GitHub tokens, Slack
tokens, Google API keys, PEM private keys, JWTs, plus a generic high-entropy token
heuristic (40+ characters of base64 or base64url alphabet).

They abort rather than being auto-redacted on purpose: silently mangling a token-shaped
string in a conversation that is ABOUT tokens would corrupt legitimate content, and you
would not know it had happened. An abort makes you look.

Git SHAs and similar hex digests are carved out, so an ordinary commit-heavy session does
not trip the detector.

---

## Limitations you need to know

These are real. None of them is a bug; all of them are places where your judgement is
still required.

**1. Identity comes from THIS machine, not from the session's origin.**
The username, hostname and home directory that get redacted are the ones of the machine
running `ccw share`. If you captured a session on a different machine, under a different
login, or inside a container, that identity will NOT be recognised. Add it to
`redact_patterns` yourself.

**2. JSON keys are not redacted, only values.**
Session payload keys are structural (`type`, `message`, `content`), so this is normally
irrelevant. It stops being irrelevant if a tool wrote data into a session keyed BY
something sensitive.

**3. Redaction finds what it is told to find.**
There is no model, no entropy analysis of prose, and no understanding. A customer name, an
internal project codename, an IP address or a URL with a token in the query string will
pass straight through unless a pattern matches it. **The built-ins are a floor, not a
review.**

**4. A custom pattern is a regular expression you wrote.**
An over-broad one will shred legitimate content; a wrong one silently protects nothing.
There is no timeout on user-supplied patterns, so a pathological one can hang the run.

**5. Detection is not prevention.**
`--allow-findings` and `--EXPOSED` both exist, and both do exactly what they say.

---

## The two override flags

**`--allow-findings`** ships secret-shaped content verbatim instead of aborting. Use it
when the detector is wrong, for example a fake key in a code sample. It does not disable
redaction; the built-in and custom patterns still apply.

**`--EXPOSED`** publishes UNSCRUBBED content. It is the one sanctioned way to bypass
scrubbing and the only irreversible outward-facing action in the tool. It is gated:

- both a scrubbed and an unscrubbed site are rendered into a private staging area first,
  so comparing can never publish the raw one by accident;
- you get a per-session byte-size comparison plus the redaction-hit and secret-finding
  counts;
- you must type the literal word `EXPOSED`. `y` will not do it;
- a non-TTY stdin (a pipe, cron, a here-string) is NEVER consent. It aborts and writes
  nothing;
- on confirming, BOTH `out/EXPOSED/` and `out/SCRUBBED/` land, so you keep the comparison.

---

## Before you publish

1. Run the share and **read the redaction report** (`redaction-report.json` in the output
   directory). It lists every hit: pattern, file, line, replacement.
2. **Grep the output yourself** for the things only you know are sensitive: client names,
   internal hostnames, project codenames, ticket URLs. The tool cannot know these.
3. Check the session was captured **on this machine**. If not, add its identity to
   `redact_patterns` first (limitation 1).
4. If the share aborted on a secret finding, **look at the finding** before reaching for
   `--allow-findings`.
5. Open one of the generated pages and read it. Shared pages are self-contained and make
   no third-party requests, so what you see is what a reader gets.

---

## What shared pages do not do

Shared pages inline highlight.js rather than loading it from a CDN, so **a reader's browser
makes no third-party request** and does not announce their IP or the page URL to anyone.
Personal projections keep the CDN reference for parity with the exporter.

---

Related: `contract/DESIGN.md` section 9 is the locked specification this page describes.
Where the two disagree, the contract is correct and this page is a bug.
