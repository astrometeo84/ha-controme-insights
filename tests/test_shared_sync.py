"""Tests for scripts/shared_sync.py.

Standard library and pytest only: this file is shared with ha-controme-insights.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "shared_sync.py"

DEFAULT_LIST = """\
# shared files
.claude/shared-files.txt
docs/**   # recursive

top.txt
"""


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("shared_sync", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sync = _load_script()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return result.stdout


def _init(path: Path, branch: str = "chore/test") -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", branch)
    # CI has no git identity; set one per repository.
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "user.email", "test@example.invalid")
    _git(path, "config", "commit.gpgsign", "false")
    return path


def _write(repo: Path, name: str, content: str | bytes) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8", newline="")


def _commit(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "test")


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the developer's git config and environment (hooks, signing …) out of the tests."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    # Never search for a repository above tmp_path (TMPDIR could live inside one).
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    # Set when pytest runs inside a git hook; would redirect git to the real repository.
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)


def _symlink(link: Path, target: Path, *, is_dir: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=is_dir)
    except OSError:  # pragma: no cover - Windows without symlink privilege
        pytest.skip("symlinks not available")


@pytest.fixture
def repos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Path, Path]]:
    """Two repositories with an identical, committed set of shared files; cwd = here."""
    here = _init(tmp_path / "here")
    there = _init(tmp_path / "there")
    for repo in (here, there):
        _write(repo, ".claude/shared-files.txt", DEFAULT_LIST)
        _write(repo, "top.txt", "top\n")
        _write(repo, "docs/a.md", "alpha\n")
        _write(repo, "docs/sub/b.md", "beta\n")
        _write(repo, "unshared.txt", f"only in {repo.name}\n")
        _commit(repo)
    monkeypatch.chdir(here)
    yield here, there


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = sync.main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


def _report(out: str) -> dict[str, str]:
    """Parse the report lines into {path: status}."""
    report: dict[str, str] = {}
    for status in ("same", "DIFFERS", "MISSING THERE", "ONLY THERE"):
        for line in out.splitlines():
            if line.startswith(status + " "):
                report[line[len(status) :].strip()] = status
    return report


# --- report / statuses -------------------------------------------------------------------


def test_all_same_exit_0(repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    _, there = repos
    code, out, err = _run(capsys, "--other", str(there))
    assert code == 0
    assert err == ""
    assert _report(out) == {
        ".claude/shared-files.txt": "same",
        "docs/a.md": "same",
        "docs/sub/b.md": "same",
        "top.txt": "same",
    }


def test_unlisted_files_are_ignored(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, there = repos
    _, out, _ = _run(capsys, "--other", str(there))
    assert "unshared.txt" not in out


def test_differs_exit_1(repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    here, there = repos
    _write(here, "docs/sub/b.md", "beta changed\n")
    code, out, _ = _run(capsys, "--other", str(there))
    assert code == 1
    assert _report(out)["docs/sub/b.md"] == "DIFFERS"
    assert _report(out)["docs/a.md"] == "same"


def test_differs_is_byte_exact(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    _write(here, "top.txt", "top\r\n")
    code, out, _ = _run(capsys, "--other", str(there))
    assert code == 1
    assert _report(out)["top.txt"] == "DIFFERS"


def test_missing_there_exit_1(repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    here, there = repos
    _write(here, "docs/new/c.md", "gamma\n")
    code, out, _ = _run(capsys, "--other", str(there))
    assert code == 1
    assert _report(out)["docs/new/c.md"] == "MISSING THERE"


def test_only_there_exit_1(repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    _, there = repos
    _write(there, "docs/extra.md", "extra\n")
    code, out, _ = _run(capsys, "--other", str(there))
    assert code == 1
    assert _report(out)["docs/extra.md"] == "ONLY THERE"


def test_list_of_current_repo_is_authoritative(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, there = repos
    _write(there, ".claude/shared-files.txt", DEFAULT_LIST + "unshared.txt\n")
    _commit(there)
    code, out, _ = _run(capsys, "--other", str(there))
    assert code == 1
    assert _report(out)[".claude/shared-files.txt"] == "DIFFERS"
    assert "unshared.txt" not in out


def test_untracked_files_count(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    _write(here, "docs/untracked.md", "new\n")  # not added to git
    _, out, _ = _run(capsys, "--other", str(there))
    assert _report(out)["docs/untracked.md"] == "MISSING THERE"


def test_ignored_files_do_not_count(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    for repo in (here, there):
        _write(repo, ".gitignore", "__pycache__/\n")
        _commit(repo)
    _write(here, "docs/__pycache__/x.pyc", b"\x00\x01")
    code, out, _ = _run(capsys, "--other", str(there))
    assert code == 0
    assert "__pycache__" not in out


def test_hidden_files_match_double_star(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    _write(here, "docs/.hidden", "h\n")
    _write(here, "docs/.dir/x.md", "x\n")
    _, out, _ = _run(capsys, "--other", str(there))
    assert _report(out)["docs/.hidden"] == "MISSING THERE"
    assert _report(out)["docs/.dir/x.md"] == "MISSING THERE"


def test_single_star_does_not_cross_directories(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    _write(here, ".claude/shared-files.txt", "docs/*\n")
    _write(here, "docs/sub/b.md", "changed\n")
    code, out, _ = _run(capsys, "--other", str(there))
    assert code == 0
    assert _report(out) == {"docs/a.md": "same"}


def test_deleted_uncommitted_counts_as_missing_there(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, there = repos
    (there / "docs/a.md").unlink()  # git ls-files still reports it
    assert "docs/a.md" in _git(there, "ls-files")
    code, out, _ = _run(capsys, "--other", str(there))
    assert code == 1
    assert _report(out)["docs/a.md"] == "MISSING THERE"


def test_deleted_uncommitted_counts_as_only_there(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    (here / "docs/a.md").unlink()
    code, out, _ = _run(capsys, "--other", str(there))
    assert code == 1
    assert _report(out)["docs/a.md"] == "ONLY THERE"


def test_deleted_uncommitted_in_both_is_no_match(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    for repo in (here, there):
        (repo / "top.txt").unlink()
    code, _, err = _run(capsys, "--other", str(there))
    assert code == 2
    assert "'top.txt'" in err


# --- --diff ------------------------------------------------------------------------------


def test_no_diff_without_flag(repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    here, there = repos
    _write(here, "top.txt", "top changed\n")
    _, out, _ = _run(capsys, "--other", str(there))
    assert "@@" not in out


def test_diff_text(repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    here, there = repos
    _write(here, "top.txt", "top changed\nsecond")  # no trailing newline
    code, out, _ = _run(capsys, "--other", str(there), "--diff")
    assert code == 1
    assert "--- other/top.txt\n" in out
    assert "+++ this/top.txt\n" in out
    assert "\n-top\n" in out
    assert "\n+top changed\n" in out
    assert "\n+second\n" in out


def test_diff_utf8_with_umlauts(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    _write(here, "docs/a.md", "Küche\n")
    _write(there, "docs/a.md", "Kueche\n")
    _, out, _ = _run(capsys, "--other", str(there), "--diff")
    assert "\n+Küche\n" in out
    assert "\n-Kueche\n" in out
    assert "binary differs" not in out


def test_diff_binary(repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    here, there = repos
    _write(here, "docs/img.bin", b"\xff\xfe\x00")
    _write(there, "docs/img.bin", b"\xff\xfe\x01")
    code, out, _ = _run(capsys, "--other", str(there), "--diff")
    assert code == 1
    assert "DIFFERS       docs/img.bin\nbinary differs\n" in out


def test_diff_only_for_differs(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    _write(here, "docs/new.md", "new\n")
    _, out, _ = _run(capsys, "--other", str(there), "--diff")
    assert "@@" not in out
    assert "binary differs" not in out


# --- --apply -----------------------------------------------------------------------------


def test_apply_copies_and_creates_subdirs(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    _write(here, "top.txt", "top changed\n")
    _write(here, "docs/deep/er/c.bin", b"\x00\xff")
    _commit(here)
    head_here, head_there = _head(here), _head(there)

    code, out, _ = _run(capsys, "--other", str(there), "--apply")

    assert code == 0
    assert (there / "top.txt").read_bytes() == b"top changed\n"
    assert (there / "docs/deep/er/c.bin").read_bytes() == b"\x00\xff"
    assert "copied        top.txt" in out
    assert "copied        docs/deep/er/c.bin" in out
    # Nothing committed, nothing changed in the current repository.
    assert _head(there) == head_there
    assert _head(here) == head_here
    assert _git(here, "status", "--porcelain") == ""
    assert " M top.txt" in _git(there, "status", "--porcelain")
    # A second run reports everything as same.
    assert _run(capsys, "--other", str(there))[0] == 0


def test_apply_never_deletes(repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    here, there = repos
    _write(there, "docs/extra.md", "extra\n")
    _commit(there)
    _write(here, "top.txt", "top changed\n")
    _commit(here)

    code, out, _ = _run(capsys, "--other", str(there), "--apply")

    assert code == 1  # ONLY THERE remains
    assert (there / "docs/extra.md").read_text(encoding="utf-8") == "extra\n"
    assert (there / "unshared.txt").is_file()
    assert (there / "top.txt").read_bytes() == b"top changed\n"
    assert "note: docs/extra.md exists only in" in out


def test_apply_when_all_same(repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    _, there = repos
    code, out, _ = _run(capsys, "--other", str(there), "--apply")
    assert code == 0
    assert "copied" not in out


def test_apply_with_diff_shows_diff_then_copies(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    _write(here, "top.txt", "top changed\n")
    _commit(here)
    code, out, _ = _run(capsys, "--other", str(there), "--diff", "--apply")
    assert code == 0
    assert out.index("+top changed") < out.index("copied        top.txt")


# --- errors (exit 2) ---------------------------------------------------------------------


def _assert_error(capsys: pytest.CaptureFixture[str], args: list[str], message: str) -> None:
    code, out, err = _run(capsys, *args)
    assert code == 2
    assert out == ""
    assert err.startswith("error: ")
    assert message in err


def test_error_list_missing(repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    here, there = repos
    (here / ".claude/shared-files.txt").unlink()
    _assert_error(capsys, ["--other", str(there)], "list of shared files not found")


def test_error_list_empty(repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    here, there = repos
    _write(here, ".claude/shared-files.txt", "# only a comment\n\n   \n")
    _assert_error(capsys, ["--other", str(there)], "list of shared files is empty")


@pytest.mark.parametrize("pattern", ["/etc/passwd", "\\top.txt", "C:/top.txt", "C:top.txt"])
def test_error_absolute_pattern(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str], pattern: str
) -> None:
    here, there = repos
    _write(here, ".claude/shared-files.txt", f"top.txt\n{pattern}\n")
    _assert_error(capsys, ["--other", str(there)], "must be relative")


@pytest.mark.parametrize("pattern", ["../there/top.txt", "docs/../../x", "docs\\..\\top.txt"])
def test_error_dotdot_pattern(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str], pattern: str
) -> None:
    here, there = repos
    _write(here, ".claude/shared-files.txt", f"top.txt\n{pattern}\n")
    _assert_error(capsys, ["--other", str(there)], "must not contain '..'")


def test_error_pattern_without_match(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    _write(here, ".claude/shared-files.txt", DEFAULT_LIST + "nothing/**\n")
    _assert_error(capsys, ["--other", str(there)], "matches no file in either repository")


def test_pattern_matching_only_there_is_fine(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    _write(here, ".claude/shared-files.txt", DEFAULT_LIST + "extra/**\n")
    _write(there, "extra/x.txt", "x\n")
    code, out, _ = _run(capsys, "--other", str(there))
    assert code == 1
    assert _report(out)["extra/x.txt"] == "ONLY THERE"


def test_error_other_not_a_repo(
    repos: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    _assert_error(capsys, ["--other", str(plain)], "is not a git repository")


def test_error_other_does_not_exist(
    repos: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _assert_error(capsys, ["--other", str(tmp_path / "nope")], "is not a git repository")


def test_error_current_dir_not_a_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    there = _init(tmp_path / "there")
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    _assert_error(capsys, ["--other", str(there)], "is not a git repository")


@pytest.mark.parametrize("other", [".", "docs"])
def test_error_same_repo(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str], other: str
) -> None:
    _assert_error(capsys, ["--other", other], "points to the current repository")


def test_error_other_missing_argument(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        sync.main([])
    assert exc.value.code == 2
    assert "--other" in capsys.readouterr().err


@pytest.mark.parametrize(
    "dirty",
    [
        pytest.param(lambda r: _write(r, "unshared.txt", "modified\n"), id="modified"),
        pytest.param(lambda r: _write(r, "scratch.txt", "new\n"), id="untracked"),
    ],
)
def test_error_apply_dirty_target(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str], dirty: Callable[[Path], None]
) -> None:
    here, there = repos
    _write(here, "top.txt", "top changed\n")
    _commit(here)
    dirty(there)
    _assert_error(capsys, ["--other", str(there), "--apply"], "uncommitted changes")
    assert (there / "top.txt").read_bytes() == b"top\n"  # nothing copied


def test_dirty_target_is_fine_without_apply(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, there = repos
    _write(there, "scratch.txt", "new\n")
    assert _run(capsys, "--other", str(there))[0] == 0


def test_error_apply_on_main(repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    here, there = repos
    _git(there, "branch", "-m", "main")
    _write(here, "top.txt", "top changed\n")
    _commit(here)
    _assert_error(capsys, ["--other", str(there), "--apply"], "'main' checked out")
    assert (there / "top.txt").read_bytes() == b"top\n"  # nothing copied


def test_main_is_fine_without_apply(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, there = repos
    _git(there, "branch", "-m", "main")
    assert _run(capsys, "--other", str(there))[0] == 0


def test_error_apply_through_file_symlink(
    repos: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (there / "top.txt").unlink()
    _symlink(there / "top.txt", outside)
    _commit(there)
    _write(here, "top.txt", "top changed\n")
    _commit(here)
    _assert_error(capsys, ["--other", str(there), "--apply"], "refusing to write")
    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_error_apply_through_dir_symlink(
    repos: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    outside = tmp_path / "outside"
    outside.mkdir()
    _symlink(there / "docs/link", outside, is_dir=True)
    _commit(there)
    _write(here, "docs/link/x.md", "x\n")
    _commit(here)
    _assert_error(capsys, ["--other", str(there), "--apply"], "refusing to write")
    assert list(outside.iterdir()) == []


def test_apply_on_detached_head(
    repos: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = repos
    _git(there, "checkout", "-q", "--detach")
    _write(here, "top.txt", "top changed\n")
    _commit(here)
    assert _run(capsys, "--other", str(there), "--apply")[0] == 0


# --- command line ------------------------------------------------------------------------


def test_runs_as_script(repos: tuple[Path, Path]) -> None:
    here, there = repos
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--other", str(there)],
        cwd=here,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "same          top.txt" in result.stdout
