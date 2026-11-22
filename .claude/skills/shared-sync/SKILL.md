---
name: shared-sync
description: Keep the files shared between aiocontrome and ha-controme-insights byte-identical (agents, shared skills, settings, fixtures, the sync script itself). Use after changing any file listed in .claude/shared-files.txt, when adding a new shared file, or when asked to check or sync the two repositories.
---

# Shared files between aiocontrome and ha-controme-insights

Some files exist in both repositories and must stay **byte-identical**. They are listed in
`.claude/shared-files.txt` (one glob per line, relative to the repo root, `#` = comment).
The list of the repository you run the script from is authoritative.

Not shared: `CLAUDE.md`, `ha-*` skills, `.claude/upstream/`.

## When to sync

After **every** change to a shared file (merged or about to be merged in this repository):

Both repositories are expected side by side (`../aiocontrome`, `../ha-controme-insights`).
Run the script from the repository that has the change; the examples below are for running
it in aiocontrome. In ha-controme-insights use `--other ../aiocontrome` instead.

1. In the **other** repository, start a fresh branch from `origin/main`:
   ```bash
   git -C ../ha-controme-insights fetch origin
   git -C ../ha-controme-insights switch -c chore/sync-shared origin/main
   ```
2. From this repository, check and copy:
   ```bash
   uv run python scripts/shared_sync.py --other ../ha-controme-insights --diff
   uv run python scripts/shared_sync.py --other ../ha-controme-insights --apply
   ```
3. In the other repository: run its checks, commit, and open a **separate PR**
   `chore/sync-shared` (push only after asking the maintainer, as always).

Never sync into the other repository as part of an unrelated PR.

## Commands

Write the commands exactly like this (no extra spaces, flags in this order): the report and
`--diff` forms are allowed in `.claude/settings.json` as exact rules; `--apply` deliberately
is not and always needs the maintainer's confirmation.

From aiocontrome:

```bash
uv run python scripts/shared_sync.py --other ../ha-controme-insights
uv run python scripts/shared_sync.py --other ../ha-controme-insights --diff
uv run python scripts/shared_sync.py --other ../ha-controme-insights --apply
```

From ha-controme-insights:

```bash
uv run python scripts/shared_sync.py --other ../aiocontrome
uv run python scripts/shared_sync.py --other ../aiocontrome --diff
uv run python scripts/shared_sync.py --other ../aiocontrome --apply
```

| Form | Effect |
|---|---|
| `--other <path>` | Report per file: `same`, `DIFFERS`, `MISSING THERE`, `ONLY THERE` |
| `--other <path> --diff` | Additionally a unified diff per differing text file (UTF-8), otherwise `binary differs` |
| `--other <path> --apply` | Copy `DIFFERS` and `MISSING THERE` from this repository into the other one, creating subfolders |

`--apply` never deletes, commits or pushes. For `ONLY THERE` it prints a note; decide by
hand whether the file should be added here or removed there. `--apply` refuses to run if
the other repository has uncommitted changes or has `main` checked out, and it never writes
through a symlink or outside the other repository.

Files that git lists but that were deleted without committing count as not present.
Ignored files (`.gitignore`) never count; untracked, not ignored files do.

Exit codes: `0` all identical (or identical after `--apply`), `1` differences remain
(including `ONLY THERE` after `--apply`), `2` error (list missing or empty, absolute pattern
or `..`, pattern without match in both repositories, `--other` not a git repository or the
same repository, `--apply` preconditions not met).

## Adding a shared file

Add its path or glob to `.claude/shared-files.txt` **in the same PR** that creates the file,
then sync as above (the list itself is shared, so the other repository gets the new entry
too). A pattern that matches nothing in either repository is an error.

`scripts/shared_sync.py` and `tests/test_shared_sync.py` are shared as well: standard
library and pytest only, no imports from `aiocontrome` or Home Assistant.
