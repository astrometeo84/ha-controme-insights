---
name: release
description: Prepare a release (version bump, changelog, release PR). Use when the user asks to prepare, cut or plan a release. Claude never tags or publishes – the user does.
---

# Preparing a release

Claude prepares, the user releases. Claude has no right to create tags, change workflows or
publish to PyPI/HACS – and must not try.

1. Make sure `main` is up to date locally and all tests/lint/type checks pass.
2. Propose the next version (SemVer: fix → patch, feature → minor, breaking → major) and wait for
   the user's confirmation.
3. On a branch `release/vX.Y.Z`:
   - bump the version (`pyproject.toml` for aiocontrome; `manifest.json` for the integration)
   - for the integration: raise the `aiocontrome` requirement if a new library version is needed
   - update `CHANGELOG.md` (Keep a Changelog format, date in ISO)
4. Commit (`chore(release): vX.Y.Z`), push the branch, open a PR with `ghb pr create`.
5. Tell the user the remaining manual steps:
   - review and merge the PR
   - create the tag `vX.Y.Z` and the GitHub release (protected – only the user can)
   - aiocontrome: approve the `pypi` environment in GitHub Actions
   - integration: check that HACS shows the new version on the test system
