# Releasing cc-warehouse

How a version gets from this repository to PyPI, and what "breaking" means here.

Written down because the first two releases were done by hand, and a checklist
carried in one person's head is a checklist that loses a step the day it matters.

## Versioning

cc-warehouse follows semantic versioning, with one project-specific rule that is
easy to get wrong.

| Bump | Means |
|---|---|
| **MAJOR** | a CLI verb or flag is removed or changes meaning; the archive folder layout changes; **the DEFAULT rendered output changes** |
| **MINOR** | a new verb, flag, or output capability; a new entry type is recognised |
| **PATCH** | a fix that leaves the default output byte-identical; metadata, docs, packaging |

**The rendered output is part of the public interface.** A user's archive is a
folder of markdown and HTML they read, diff, and link to. Changing what a default
render produces breaks that as surely as removing a flag would, even though no
signature changed.

This is already enforced mechanically rather than by memory:
`tests/golden/matrix-anchor` pins the four projected files under default options,
so a change to default output **breaks the suite on purpose**. Never regenerate
the anchor to make a change pass. If it breaks, either the change is wrong or the
version needs a MAJOR bump and a recorded ruling.

`0.x` is pre-1.0, so breaking changes may land in a MINOR bump until 1.0. Say so
plainly in the changelog when they do.

## Release checklist

### 1. Confirm the tree is releasable

```bash
uv run ruff check
uv run pyright
uv run pytest
```

All three are merge gates, so this should be a formality. If it is not, stop.

`tests/test_packaging.py` runs inside that suite and is the one that matters most
here: it builds a real sdist and fails if the artifact contains a file git does
not track, a real home directory, a secret shape, or a working-material
directory. It exists because on 2026-08-09 the repository was clean of the
author's account name and the built sdist was not.

### 2. Decide the version and write the changelog first

Add the entry to `CHANGELOG.md` under `## Releases` **before** bumping, so the
version number is chosen with the change list in front of you rather than after.

State plainly what kind of release it is. If nothing under `src/` changed, say so
and prove it:

```bash
git diff --stat <previous-release-commit>..HEAD -- src/
```

### 3. Bump the version

```toml
# pyproject.toml
version = "X.Y.Z"
```

Nothing else carries the version. The README badge reads it from PyPI.

### 4. Commit and tag

```bash
git add pyproject.toml CHANGELOG.md
git commit          # why the version moved, not what changed
git tag -a vX.Y.Z -m "..."
git push origin master
git push origin vX.Y.Z
```

Version tags (`vX.Y.Z`) are releases. They are a different thing from the
build-milestone tags (`slice-*`, `ticket-*`), which record how the software was
made and are not installable. `CHANGELOG.md` keeps the two apart; so should you.

### 5. Publish

Pushing the tag triggers `.github/workflows/release.yml`, which re-runs the gates
and publishes with PyPI Trusted Publishing. **No token is stored anywhere.**

If publishing by hand instead:

```bash
uv build
uvx twine check dist/*
uvx twine upload dist/*
```

`0.1.0` and `0.1.1` were published this way. It works, and it requires a
long-lived token on disk, which is why the workflow exists.

### 6. Verify from the outside

Not from `dist/`. From PyPI:

```bash
curl -s https://pypi.org/pypi/cc-warehouse/json | head
uvx --refresh --from cc-warehouse ccw version
```

Compare the sha256 PyPI reports against your local artifacts. They must match
exactly. A hash comparison is the only check that proves the thing published is
the thing you inspected.

Note the PyPI JSON API is CDN-cached, so the top-level endpoint can lag by a few
minutes while `/pypi/cc-warehouse/<version>/json` and the simple index are already
correct. A stale top-level response is not a failed upload.

## One-time setup for Trusted Publishing

Done once per project, on the PyPI side, by an account with owner rights.

1. Go to **https://pypi.org/manage/project/cc-warehouse/settings/publishing/**
2. Add a GitHub publisher:
   - Owner: `CaptainCodeAU`
   - Repository: `cc-warehouse`
   - Workflow: `release.yml`
   - Environment: `pypi`
3. In GitHub, create an environment named `pypi` under
   *Settings -> Environments*. Add a required reviewer if you want a human gate
   before any upload.

Once that exists, delete the API token from `~/.pypirc`. A credential that is no
longer needed is a credential that can only cost you something.

## Things that cannot be undone

- **A version number is permanent.** Deleting a release from PyPI does not free
  the version; it can never be re-uploaded. A mistake costs a version number.
- **A name is permanent.** `cc-warehouse` is claimed.
- **A published description is frozen into its release.** `0.1.1` exists solely
  because a rewritten README cannot reach the project page without a new version.
