# cc-warehouse-architecture - the code-architecture review board

This folder is the durable home of **cc-warehouse's architecture-review board**: the deepening
candidates surfaced by architecture reviews, their verdicts and evidence, and the findings each
review verified as healthy. It replaces the ephemeral scratchpad report files - the board lives
in-repo, versioned, at a stable path.

**Scope guard:** this is cc-warehouse's CODE architecture - modules, seams, depth, testability.
The product/system contract (BRAINSTORM, SPEC, DESIGN, FINDINGS, HARNESS) is LOCKED and lives in
`docs/`; this board never edits it and never relitigates its decisions. A candidate that needs a
contract change says so on its card and waits for the principal's ruling.

| File | What it is |
|---|---|
| **`SOURCE.md`** | **The truth.** The canonical board record - every candidate with its state (`PROPOSED` / `GRILLING` / `TICKETED-<nn>` / `BUILT` / `REJECTED`), strength, evidence tier (`VERIFIED` at a named commit / `CONTRACT` / `AGENT-REPORTED`), contract and ticket ties, and the cleared-healthy list. Edit THIS when the board changes. |
| **`index.html`** | The human-facing VIEW, **rendered from `SOURCE.md`** by the `/architecture` command. Dark-first, Tailwind + Mermaid, per-candidate cards with plain-English boxes. Never hand-edit findings here. |
| `README.md` | This file. |

## How it stays current

- A fresh review runs via **`/mattpocock-skills:improve-codebase-architecture`** (Explore agents,
  then first-hand verification of every load-bearing claim before anything enters the board).
- Verified findings are folded into **`SOURCE.md` first** (`/architecture add`), then the HTML is
  regenerated (`/architecture` - its confirm-gate checks ticket/contract drift and line-ref decay
  before rendering).
- Candidate STATE only advances through the project's own discipline: grilling before any build,
  work landing through harness tickets, closures proven by tests and the HARNESS changelog.
- Single ownership: `/architecture` owns this folder's currency. `/refresh`'s docs slice
  enumerates CLAUDE.md, README, the docs/ status tier, and harness/tickets; this folder is
  deliberately outside that scope, and staleness here is caught by the `/architecture` gate.

## Open the report

`index.html` is a standalone file - open it in a browser (it loads Tailwind + Mermaid from CDNs,
so it needs network for styling; the content is complete without it). It is NOT published
anywhere by default; publishing (the `/architecture artifact` variant) is the operator's call.
