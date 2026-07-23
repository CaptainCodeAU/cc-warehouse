# Vendored third-party assets

This directory holds third-party assets shipped inside the package. It is the ONLY
third-party code in the repository.

## highlight.min.js

- **Project:** highlight.js
- **Version:** 11.9.0 (git f47103d4f1)
- **Source:** https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js
- **sha256:** 837a6fa5b0c736b52bbde2b2b6190f305da3fc9ed41681db5321507057b5c846
- **Size:** 118.9 KB
- **License:** BSD-3-Clause, Copyright (c) 2006 Ivan Sagalaev and contributors.
  Full text in `highlight.js-LICENSE`, reproduced verbatim from the 11.9.0 tag.
- **Retrieved:** 2026-07-24

### Why it is here

DESIGN section 15 item 8, ruled by the principal 2026-07-24: SHARED pages inline
highlight.js so a published archive is genuinely self-contained. Personal projections
keep the CDN reference plus its graceful `onerror` fallback (exporter parity), so this
asset is read only when a share is built.

The reason is privacy rather than bytes. `ccw share` exists so that publishing does not
leak: redaction scrubs the CONTENT, but a CDN `<script>` makes every reader's browser
announce its IP and the page URL to a third party. Inlining removes that. It also makes a
shared archive keep working when a pinned CDN URL eventually stops resolving.

The byte cost was measured before the ruling, not assumed: a real `conversation.html` is
about 3.1 MB, so 118.9 KB is roughly 4%.

### This is NOT an R7 exception

R7 bans third-party PYTHON imports in runtime code. This is a static JavaScript asset
copied into an output file; nothing imports it and the runtime stays stdlib-only. The
zero-dependency fence test continues to pass unchanged.

### Updating it

Replace the file, update the version, URL, sha256 and size above, refresh the LICENSE
from the matching tag, and re-run the suite: the emitted payload is asserted to be this
file byte for byte, so a swap that is not recorded here will fail rather than drift.
