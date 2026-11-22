"""Check and sync the files shared between aiocontrome and ha-controme-insights.

The list of shared files lives in ``.claude/shared-files.txt`` of the current repository
(one glob per line, relative to the repo root, ``#`` starts a comment). The list of the
current repository is authoritative.

Usage::

    uv run python scripts/shared_sync.py --other ../ha-controme-insights           # report
    uv run python scripts/shared_sync.py --other ../ha-controme-insights --diff    # + diffs
    uv run python scripts/shared_sync.py --other ../ha-controme-insights --apply   # copy

``--apply`` copies DIFFERS and MISSING THERE from the current repository into the other
one. It never deletes, commits or pushes anything.

Exit codes: 0 = all shared files are identical (or became identical through ``--apply``),
1 = differences remain, 2 = usage or precondition error.

Standard library only: this file is shared with ha-controme-insights.
"""

from __future__ import annotations

import argparse
import difflib
import glob
import os
import re
import shutil
import subprocess
import sys
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath

LIST_FILE = PurePosixPath(".claude/shared-files.txt")
PROTECTED_BRANCH = "main"
# Set inside git hooks; they would redirect "git -C <repo>" to a different repository.
_GIT_ENV_OVERRIDES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")


class SyncError(Exception):
    """A usage or precondition error (exit code 2)."""


class Status(StrEnum):
    """Comparison result for one shared file."""

    SAME = "same"
    DIFFERS = "DIFFERS"
    MISSING_THERE = "MISSING THERE"
    ONLY_THERE = "ONLY THERE"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git in ``repo`` without raising on a non-zero exit code."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env={k: v for k, v in os.environ.items() if k not in _GIT_ENV_OVERRIDES},
    )


def repo_root(path: Path) -> Path:
    """Return the resolved top-level directory of the git repository containing ``path``."""
    if not path.is_dir():
        raise SyncError(f"{path} is not a git repository")
    result = _git(path, "rev-parse", "--show-toplevel")
    if result.returncode != 0 or not result.stdout.strip():
        raise SyncError(f"{path} is not a git repository")
    return Path(result.stdout.strip()).resolve()


def validate_pattern(pattern: str) -> None:
    """Reject absolute patterns and patterns that leave the repository."""
    if (
        pattern.startswith(("/", "\\"))
        or PurePosixPath(pattern).is_absolute()
        or PureWindowsPath(pattern).is_absolute()
        or PureWindowsPath(pattern).drive
    ):
        raise SyncError(f"pattern must be relative to the repo root: {pattern!r}")
    if ".." in PureWindowsPath(pattern).parts:
        raise SyncError(f"pattern must not contain '..': {pattern!r}")


def read_patterns(root: Path) -> list[str]:
    """Read and validate the glob patterns from the shared-files list of ``root``."""
    list_path = root / LIST_FILE
    if not list_path.is_file():
        raise SyncError(f"list of shared files not found: {list_path}")
    patterns: list[str] = []
    for raw in list_path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        validate_pattern(line)
        patterns.append(line)
    if not patterns:
        raise SyncError(f"list of shared files is empty: {list_path}")
    return patterns


def list_files(root: Path) -> set[str]:
    """Return tracked and untracked, not ignored files of ``root`` that exist on disk.

    Files that git still knows about but that were deleted without committing are
    treated as not present.
    """
    result = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if result.returncode != 0:
        raise SyncError(f"git ls-files failed in {root}: {result.stderr.strip()}")
    return {name for name in result.stdout.split("\0") if name and (root / name).is_file()}


def select_files(patterns: list[str], here: set[str], there: set[str]) -> set[str]:
    """Return all files of both repositories matched by ``patterns``.

    Every pattern must match at least one file in at least one repository.
    """
    selected: set[str] = set()
    for pattern in patterns:
        regex = re.compile(glob.translate(pattern, recursive=True, include_hidden=True))
        hits = {name for name in here | there if regex.fullmatch(name)}
        if not hits:
            raise SyncError(f"pattern matches no file in either repository: {pattern!r}")
        selected |= hits
    return selected


def compare(here: Path, there: Path, patterns: list[str]) -> list[tuple[str, Status]]:
    """Compare the shared files of both repositories byte by byte."""
    files_here = list_files(here)
    files_there = list_files(there)
    results: list[tuple[str, Status]] = []
    for name in sorted(select_files(patterns, files_here, files_there)):
        if name not in files_there:
            status = Status.MISSING_THERE
        elif name not in files_here:
            status = Status.ONLY_THERE
        elif (here / name).read_bytes() == (there / name).read_bytes():
            status = Status.SAME
        else:
            status = Status.DIFFERS
        results.append((name, status))
    return results


def diff_lines(here: Path, there: Path, name: str) -> list[str]:
    """Return a unified diff from the other repository's file to this one's.

    The direction matches ``--apply``: applying turns the ``other`` side into ``this``.
    Files that are not valid UTF-8 yield ``["binary differs\\n"]``.
    """
    try:
        new = (here / name).read_bytes().decode("utf-8")
        old = (there / name).read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return ["binary differs\n"]
    lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"other/{name}",
        tofile=f"this/{name}",
    )
    return [line if line.endswith("\n") else line + "\n" for line in lines]


def check_apply_target(there: Path) -> None:
    """Refuse ``--apply`` into a dirty repository or onto the protected branch."""
    status = _git(there, "status", "--porcelain")
    if status.returncode != 0:
        raise SyncError(f"git status failed in {there}: {status.stderr.strip()}")
    if status.stdout.strip():
        raise SyncError(f"{there} has uncommitted changes; commit or stash them first")
    branch = _git(there, "symbolic-ref", "--short", "-q", "HEAD").stdout.strip()
    if branch == PROTECTED_BRANCH:
        raise SyncError(
            f"{there} has '{PROTECTED_BRANCH}' checked out; "
            "create a branch first (e.g. chore/sync-shared from origin/main)"
        )


def check_copy_targets(there: Path, results: list[tuple[str, Status]]) -> None:
    """Refuse to write through symlinks or outside the other repository."""
    for name, status in results:
        if status not in (Status.DIFFERS, Status.MISSING_THERE):
            continue
        target = there / name
        if target.is_symlink() or not target.resolve().is_relative_to(there):
            raise SyncError(f"refusing to write through a symlink or outside {there}: {name}")


def apply(here: Path, there: Path, results: list[tuple[str, Status]]) -> None:
    """Copy DIFFERS and MISSING THERE into the other repository; never delete anything."""
    for name, status in results:
        if status in (Status.DIFFERS, Status.MISSING_THERE):
            target = there / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(here / name, target)
            print(f"copied        {name}")
        elif status is Status.ONLY_THERE:
            print(f"note: {name} exists only in {there}; not deleted, check it by hand")


def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Check (and optionally sync) the files shared with another repository."
    )
    parser.add_argument("--other", required=True, help="path to the other repository")
    parser.add_argument("--diff", action="store_true", help="show a unified diff per file")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="copy DIFFERS and MISSING THERE from this repository into the other one",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the check; return the exit code."""
    args = build_parser().parse_args(argv)
    try:
        here = repo_root(Path.cwd())
        there = repo_root(Path(args.other))
        if here == there:
            raise SyncError("--other points to the current repository")
        patterns = read_patterns(here)
        if args.apply:
            check_apply_target(there)
        results = compare(here, there, patterns)
        if args.apply:
            check_copy_targets(there, results)
    except SyncError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2

    for name, status in results:
        print(f"{status:<13} {name}")
        if args.diff and status is Status.DIFFERS:
            sys.stdout.writelines(diff_lines(here, there, name))

    if args.apply:
        apply(here, there, results)
        results = compare(here, there, patterns)

    return 0 if all(status is Status.SAME for _, status in results) else 1


if __name__ == "__main__":
    sys.exit(main())
