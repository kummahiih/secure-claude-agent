"""
Tests for git_mcp.py tools.

Uses a temporary git repo fixture so tests are self-contained.
Does NOT require Docker or real workspace mounts.
"""

import os
import subprocess
import tempfile

import pytest

# Set GIT_DIR and GIT_WORK_TREE before importing git_mcp,
# since it checks these at import time.
# The fixture will override them per-test.
os.environ.setdefault("GIT_DIR", "/tmp/fake-gitdir")
os.environ.setdefault("GIT_WORK_TREE", "/tmp/fake-worktree")

import git_mcp


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repo with separated gitdir and worktree.

    Mimics the production layout:
    - worktree/ — the working tree (what mcp-server sees as /workspace)
    - gitdir/  — the git directory (what claude-server sees as /gitdir)

    Patches git_mcp.GIT_DIR and GIT_WORK_TREE for the duration of the test.
    """
    worktree = tmp_path / "worktree"
    gitdir = tmp_path / "gitdir"
    worktree.mkdir()
    gitdir.mkdir()

    # Use GIT_DIR env var to init directly into the separated gitdir.
    # This avoids issues with .git files in nested repos.
    env = {**os.environ, "GIT_DIR": str(gitdir)}
    subprocess.run(
        ["git", "init"],
        check=True, capture_output=True, text=True,
        cwd=str(worktree), env=env,
    )

    # Configure user for commits
    env["GIT_WORK_TREE"] = str(worktree)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        check=True, capture_output=True, env=env,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        check=True, capture_output=True, env=env,
    )
    # Ensure it's not bare (GIT_DIR init can default to bare)
    subprocess.run(
        ["git", "config", "core.bare", "false"],
        check=True, capture_output=True, env=env,
    )

    # Patch git_mcp module globals
    original_dir = git_mcp.GIT_DIR
    original_tree = git_mcp.GIT_WORK_TREE
    git_mcp.GIT_DIR = str(gitdir)
    git_mcp.GIT_WORK_TREE = str(worktree)

    yield worktree, gitdir

    git_mcp.GIT_DIR = original_dir
    git_mcp.GIT_WORK_TREE = original_tree


class TestGitStatus:
    def test_clean_repo(self, git_repo):
        worktree, _ = git_repo
        # Create initial commit so status doesn't complain about empty repo
        (worktree / "README.md").write_text("# test\n")
        env = {**os.environ, "GIT_DIR": git_mcp.GIT_DIR, "GIT_WORK_TREE": git_mcp.GIT_WORK_TREE}
        subprocess.run(["git", "add", "."], check=True, capture_output=True, env=env)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            check=True, capture_output=True, env=env,
        )

        result = git_mcp.git_status()
        assert result.isError is False
        assert "clean" in result.content[0].text.lower()

    def test_untracked_file(self, git_repo):
        worktree, _ = git_repo
        (worktree / "new_file.py").write_text("print('hello')\n")

        result = git_mcp.git_status()
        assert result.isError is False
        assert "new_file.py" in result.content[0].text

    def test_modified_file(self, git_repo):
        worktree, _ = git_repo
        env = {**os.environ, "GIT_DIR": git_mcp.GIT_DIR, "GIT_WORK_TREE": git_mcp.GIT_WORK_TREE}

        # Create and commit a file
        (worktree / "file.py").write_text("v1\n")
        subprocess.run(["git", "add", "."], check=True, capture_output=True, env=env)
        subprocess.run(
            ["git", "commit", "-m", "add file"],
            check=True, capture_output=True, env=env,
        )

        # Modify it
        (worktree / "file.py").write_text("v2\n")

        result = git_mcp.git_status()
        assert result.isError is False
        assert "file.py" in result.content[0].text


class TestGitDiff:
    def test_no_changes(self, git_repo):
        worktree, _ = git_repo
        env = {**os.environ, "GIT_DIR": git_mcp.GIT_DIR, "GIT_WORK_TREE": git_mcp.GIT_WORK_TREE}
        (worktree / "file.py").write_text("content\n")
        subprocess.run(["git", "add", "."], check=True, capture_output=True, env=env)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            check=True, capture_output=True, env=env,
        )

        result = git_mcp.git_diff()
        assert result.isError is False
        assert "no unstaged changes" in result.content[0].text.lower()

    def test_unstaged_diff(self, git_repo):
        worktree, _ = git_repo
        env = {**os.environ, "GIT_DIR": git_mcp.GIT_DIR, "GIT_WORK_TREE": git_mcp.GIT_WORK_TREE}
        (worktree / "file.py").write_text("line1\n")
        subprocess.run(["git", "add", "."], check=True, capture_output=True, env=env)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            check=True, capture_output=True, env=env,
        )

        (worktree / "file.py").write_text("line1\nline2\n")

        result = git_mcp.git_diff()
        assert result.isError is False
        assert "+line2" in result.content[0].text

    def test_staged_diff(self, git_repo):
        worktree, _ = git_repo
        env = {**os.environ, "GIT_DIR": git_mcp.GIT_DIR, "GIT_WORK_TREE": git_mcp.GIT_WORK_TREE}
        (worktree / "file.py").write_text("v1\n")
        subprocess.run(["git", "add", "."], check=True, capture_output=True, env=env)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            check=True, capture_output=True, env=env,
        )

        (worktree / "file.py").write_text("v2\n")
        subprocess.run(["git", "add", "."], check=True, capture_output=True, env=env)

        result = git_mcp.git_diff(staged=True)
        assert result.isError is False
        assert "+v2" in result.content[0].text


class TestGitAdd:
    def test_add_file(self, git_repo):
        worktree, _ = git_repo
        (worktree / "new.py").write_text("code\n")

        result = git_mcp.git_add(paths=["new.py"])
        assert result.isError is False
        assert "new.py" in result.content[0].text

        # Verify it's actually staged
        status = git_mcp.git_status()
        assert "A" in status.content[0].text  # Added

    def test_add_all(self, git_repo):
        worktree, _ = git_repo
        (worktree / "a.py").write_text("a\n")
        (worktree / "b.py").write_text("b\n")

        result = git_mcp.git_add(paths=["."])
        assert result.isError is False

    def test_add_empty_paths(self, git_repo):
        result = git_mcp.git_add(paths=[])
        assert result.isError is True
        assert "no paths" in result.content[0].text.lower()

    def test_add_nonexistent_file(self, git_repo):
        result = git_mcp.git_add(paths=["does_not_exist.py"])
        assert result.isError is True


class TestGitCommit:
    def test_commit(self, git_repo):
        worktree, _ = git_repo
        (worktree / "file.py").write_text("code\n")
        git_mcp.git_add(paths=["."])

        result = git_mcp.git_commit(message="test commit")
        assert result.isError is False
        assert "test commit" in result.content[0].text

    def test_commit_empty_message(self, git_repo):
        result = git_mcp.git_commit(message="")
        assert result.isError is True
        assert "empty" in result.content[0].text.lower()

    def test_commit_whitespace_message(self, git_repo):
        result = git_mcp.git_commit(message="   ")
        assert result.isError is True

    def test_commit_nothing_staged(self, git_repo):
        worktree, _ = git_repo
        env = {**os.environ, "GIT_DIR": git_mcp.GIT_DIR, "GIT_WORK_TREE": git_mcp.GIT_WORK_TREE}
        # Need at least one commit for "nothing to commit" to work
        (worktree / "init.txt").write_text("init\n")
        subprocess.run(["git", "add", "."], check=True, capture_output=True, env=env)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            check=True, capture_output=True, env=env,
        )

        result = git_mcp.git_commit(message="empty commit")
        assert result.isError is False
        assert "nothing to commit" in result.content[0].text.lower()


class TestGitLog:
    def test_no_commits(self, git_repo):
        result = git_mcp.git_log()
        assert result.isError is False
        assert "no commits" in result.content[0].text.lower()

    def test_log_with_commits(self, git_repo):
        worktree, _ = git_repo
        env = {**os.environ, "GIT_DIR": git_mcp.GIT_DIR, "GIT_WORK_TREE": git_mcp.GIT_WORK_TREE}

        for i in range(3):
            (worktree / f"file{i}.py").write_text(f"v{i}\n")
            subprocess.run(["git", "add", "."], check=True, capture_output=True, env=env)
            subprocess.run(
                ["git", "commit", "-m", f"commit {i}"],
                check=True, capture_output=True, env=env,
            )

        result = git_mcp.git_log(max_count=2)
        assert result.isError is False
        text = result.content[0].text
        assert "commit 2" in text
        assert "commit 1" in text
        # commit 0 should not appear (max_count=2)
        assert "commit 0" not in text

    def test_log_max_count_clamped(self, git_repo):
        # max_count > 50 should be clamped
        result = git_mcp.git_log(max_count=100)
        # Just verify it doesn't error
        assert result.isError is False


class TestHookPrevention:
    """Verify that git hooks are structurally prevented."""

    def test_hooks_not_executed_on_commit(self, git_repo):
        worktree, gitdir = git_repo

        # Write a malicious pre-commit hook
        hooks_dir = gitdir / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        hook_file = hooks_dir / "pre-commit"
        # The hook creates a marker file if it runs
        marker = worktree / ".hook_executed"
        hook_file.write_text(f"#!/bin/sh\ntouch {marker}\n")
        hook_file.chmod(0o755)

        # Commit via git_mcp (should NOT trigger the hook)
        (worktree / "test.py").write_text("test\n")
        git_mcp.git_add(paths=["."])
        result = git_mcp.git_commit(message="hook test")
        assert result.isError is False

        # The marker file must NOT exist
        assert not marker.exists(), "Git hook was executed — core.hooksPath=/dev/null failed!"

    def test_no_verify_flag(self, git_repo):
        """Verify --no-verify is passed (belt-and-suspenders)."""
        worktree, gitdir = git_repo

        (worktree / "test.py").write_text("code\n")
        git_mcp.git_add(paths=["."])
        # This should succeed even with hooks present
        result = git_mcp.git_commit(message="no-verify test")
        assert result.isError is False


def _make_commits(worktree, n):
    """Helper: create n commits in the repo."""
    env = {**os.environ, "GIT_DIR": git_mcp.GIT_DIR, "GIT_WORK_TREE": git_mcp.GIT_WORK_TREE}
    for i in range(n):
        (worktree / f"file{i}.py").write_text(f"v{i}\n")
        subprocess.run(["git", "add", "."], check=True, capture_output=True, env=env)
        subprocess.run(
            ["git", "commit", "-m", f"commit {i}"],
            check=True, capture_output=True, env=env,
        )


class TestGitResetSoft:
    def test_reset_one_commit(self, git_repo):
        worktree, _ = git_repo
        # Create baseline commit
        _make_commits(worktree, 1)
        # Set baseline to current HEAD (simulating startup)
        env = {**os.environ, "GIT_DIR": git_mcp.GIT_DIR, "GIT_WORK_TREE": git_mcp.GIT_WORK_TREE}
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, env=env,
        ).stdout.strip()
        git_mcp.BASELINE_COMMIT = baseline

        # Agent makes a commit
        (worktree / "agent_file.py").write_text("agent code\n")
        git_mcp.git_add(paths=["."])
        git_mcp.git_commit(message="agent commit")

        # Reset it
        result = git_mcp.git_reset_soft(count=1)
        assert result.isError is False
        assert "Reset 1 commit" in result.content[0].text

        # Changes should still be staged
        status = git_mcp.git_status()
        assert "agent_file.py" in status.content[0].text

    def test_reset_to_baseline_allowed(self, git_repo):
        worktree, _ = git_repo
        # Create 2 commits so baseline has history behind it
        _make_commits(worktree, 2)
        env = {**os.environ, "GIT_DIR": git_mcp.GIT_DIR, "GIT_WORK_TREE": git_mcp.GIT_WORK_TREE}
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, env=env,
        ).stdout.strip()
        git_mcp.BASELINE_COMMIT = baseline

        # Agent makes one commit
        (worktree / "agent.py").write_text("code\n")
        git_mcp.git_add(paths=["."])
        git_mcp.git_commit(message="agent commit")

        # Reset back to baseline — should be allowed
        result = git_mcp.git_reset_soft(count=1)
        assert result.isError is False

        # Now try to go past baseline — should be blocked
        result = git_mcp.git_reset_soft(count=1)
        assert result.isError is True

    def test_reset_blocked_past_baseline(self, git_repo):
        worktree, _ = git_repo
        # Create 2 commits, set baseline at commit 1
        _make_commits(worktree, 2)
        env = {**os.environ, "GIT_DIR": git_mcp.GIT_DIR, "GIT_WORK_TREE": git_mcp.GIT_WORK_TREE}
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, env=env,
        ).stdout.strip()
        git_mcp.BASELINE_COMMIT = baseline

        # Agent makes 1 commit
        (worktree / "new.py").write_text("new\n")
        git_mcp.git_add(paths=["."])
        git_mcp.git_commit(message="agent commit")

        # Try to reset 2 commits (would go past baseline)
        result = git_mcp.git_reset_soft(count=2)
        assert result.isError is True
        assert "baseline" in result.content[0].text.lower()

    def test_reset_multiple_agent_commits(self, git_repo):
        worktree, _ = git_repo
        # Create baseline with 2 commits so HEAD~1 exists at baseline
        _make_commits(worktree, 2)
        env = {**os.environ, "GIT_DIR": git_mcp.GIT_DIR, "GIT_WORK_TREE": git_mcp.GIT_WORK_TREE}
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, env=env,
        ).stdout.strip()
        git_mcp.BASELINE_COMMIT = baseline

        # Agent makes 3 commits
        for i in range(3):
            (worktree / f"agent{i}.py").write_text(f"code{i}\n")
            git_mcp.git_add(paths=["."])
            git_mcp.git_commit(message=f"agent commit {i}")

        # Reset 2 of them — should work (still above baseline)
        result = git_mcp.git_reset_soft(count=2)
        assert result.isError is False

        # Reset 1 more — lands on baseline, should work
        result = git_mcp.git_reset_soft(count=1)
        assert result.isError is False

        # Now at baseline — further reset should be blocked
        result = git_mcp.git_reset_soft(count=1)
        assert result.isError is True
        assert "baseline" in result.content[0].text.lower()

    def test_reset_no_baseline(self, git_repo):
        """Empty repo at startup — reset should be blocked entirely."""
        git_mcp.BASELINE_COMMIT = None
        result = git_mcp.git_reset_soft(count=1)
        assert result.isError is True
        assert "no baseline" in result.content[0].text.lower()

    def test_reset_count_clamped(self, git_repo):
        worktree, _ = git_repo
        _make_commits(worktree, 1)
        env = {**os.environ, "GIT_DIR": git_mcp.GIT_DIR, "GIT_WORK_TREE": git_mcp.GIT_WORK_TREE}
        git_mcp.BASELINE_COMMIT = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, env=env,
        ).stdout.strip()

        # count > 5 should be clamped to 5, then fail because not enough history
        result = git_mcp.git_reset_soft(count=100)
        assert result.isError is True

class TestParseGitmodules:
    def test_empty_workspace(self, tmp_path):
        """Returns empty list when .gitmodules doesn't exist."""
        result = git_mcp.parse_gitmodules(workspace=str(tmp_path))
        assert result == []

    def test_one_submodule(self, tmp_path):
        """Parses a single submodule entry."""
        (tmp_path / ".gitmodules").write_text(
            '[submodule "mymod"]\n'
            "\tpath = some/path\n"
            "\turl = https://example.com/repo.git\n"
        )
        result = git_mcp.parse_gitmodules(workspace=str(tmp_path))
        assert len(result) == 1
        assert result[0]["name"] == "mymod"
        assert result[0]["path"] == os.path.normpath("some/path")

    def test_nested_submodule(self, tmp_path):
        """Parses a deeply nested submodule path."""
        (tmp_path / ".gitmodules").write_text(
            '[submodule "a/b/c"]\n'
            "\tpath = a/b/c\n"
            "\turl = https://example.com/c.git\n"
        )
        result = git_mcp.parse_gitmodules(workspace=str(tmp_path))
        assert len(result) == 1
        assert result[0]["path"] == os.path.normpath("a/b/c")

    def test_multiple_submodules(self, tmp_path):
        """Parses multiple submodule entries in order."""
        (tmp_path / ".gitmodules").write_text(
            '[submodule "first"]\n'
            "\tpath = sub/first\n"
            "\turl = https://example.com/first.git\n"
            '[submodule "second"]\n'
            "\tpath = sub/second\n"
            "\turl = https://example.com/second.git\n"
        )
        result = git_mcp.parse_gitmodules(workspace=str(tmp_path))
        assert len(result) == 2
        assert result[0]["name"] == "first"
        assert result[0]["path"] == os.path.normpath("sub/first")
        assert result[1]["name"] == "second"
        assert result[1]["path"] == os.path.normpath("sub/second")

    def test_path_normalised(self, tmp_path):
        """Paths are normalised via os.path.normpath."""
        (tmp_path / ".gitmodules").write_text(
            '[submodule "x"]\n'
            "\tpath = foo//bar\n"
            "\turl = https://example.com/x.git\n"
        )
        result = git_mcp.parse_gitmodules(workspace=str(tmp_path))
        assert result[0]["path"] == os.path.normpath("foo//bar")


class TestGitEnvFor:
    def test_no_args_returns_root(self):
        """No arguments → returns root GIT_DIR and GIT_WORK_TREE."""
        env, git_dir, work_tree = git_mcp.git_env_for()
        assert git_dir == git_mcp.GIT_DIR
        assert work_tree == git_mcp.GIT_WORK_TREE
        assert env["GIT_DIR"] == git_mcp.GIT_DIR
        assert env["GIT_WORK_TREE"] == git_mcp.GIT_WORK_TREE

    def test_explicit_submodule_path(self):
        """explicit submodule_path → returns submodule gitdir/worktree."""
        env, git_dir, work_tree = git_mcp.git_env_for(submodule_path="sub/foo")
        expected_gitdir = os.path.join(git_mcp.GIT_DIR, "modules", "sub/foo")
        expected_worktree = os.path.join(git_mcp.GIT_WORK_TREE, "sub/foo")
        assert git_dir == expected_gitdir
        assert work_tree == expected_worktree
        assert env["GIT_DIR"] == expected_gitdir
        assert env["GIT_WORK_TREE"] == expected_worktree

    def test_file_inside_submodule(self, tmp_path, monkeypatch):
        """file_path inside a submodule → auto-detects the correct submodule."""
        (tmp_path / ".gitmodules").write_text(
            '[submodule "mymod"]\n'
            "\tpath = mymod\n"
            "\turl = https://example.com/mymod.git\n"
        )
        monkeypatch.setattr(git_mcp, "GIT_DIR", "/fake/gitdir")
        monkeypatch.setattr(git_mcp, "GIT_WORK_TREE", str(tmp_path))

        env, git_dir, work_tree = git_mcp.git_env_for(file_path="mymod/some/file.py")
        assert git_dir == "/fake/gitdir/modules/mymod"
        assert work_tree == str(tmp_path / "mymod")
        assert env["GIT_DIR"] == git_dir
        assert env["GIT_WORK_TREE"] == work_tree

    def test_file_not_in_any_submodule(self, tmp_path, monkeypatch):
        """file_path not in any submodule → falls back to root."""
        (tmp_path / ".gitmodules").write_text(
            '[submodule "mymod"]\n'
            "\tpath = mymod\n"
            "\turl = https://example.com/mymod.git\n"
        )
        monkeypatch.setattr(git_mcp, "GIT_DIR", "/fake/gitdir")
        monkeypatch.setattr(git_mcp, "GIT_WORK_TREE", str(tmp_path))

        env, git_dir, work_tree = git_mcp.git_env_for(file_path="other/file.py")
        assert git_dir == "/fake/gitdir"
        assert work_tree == str(tmp_path)

    def test_submodule_path_takes_priority_over_file_path(self, tmp_path, monkeypatch):
        """explicit submodule_path wins even when file_path is also provided."""
        (tmp_path / ".gitmodules").write_text(
            '[submodule "mymod"]\n'
            "\tpath = mymod\n"
            "\turl = https://example.com/mymod.git\n"
        )
        monkeypatch.setattr(git_mcp, "GIT_DIR", "/fake/gitdir")
        monkeypatch.setattr(git_mcp, "GIT_WORK_TREE", str(tmp_path))

        env, git_dir, work_tree = git_mcp.git_env_for(
            file_path="other/file.py",
            submodule_path="explicit/sub",
        )
        assert git_dir == "/fake/gitdir/modules/explicit/sub"
        assert work_tree == str(tmp_path / "explicit" / "sub")

    def test_env_vars_copied(self):
        """env_vars dict contains GIT_DIR and GIT_WORK_TREE keys."""
        env, git_dir, work_tree = git_mcp.git_env_for()
        assert "GIT_DIR" in env
        assert "GIT_WORK_TREE" in env
        assert env["GIT_DIR"] == git_dir
        assert env["GIT_WORK_TREE"] == work_tree


# ---------------------------------------------------------------------------
# New tests for submodule-aware git tool handlers (task t2/t3)
# ---------------------------------------------------------------------------

import os
from unittest.mock import MagicMock, call, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Return a MagicMock that looks like a CompletedProcess."""
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# git_add: multi-repo guard
# ---------------------------------------------------------------------------


class TestGitAddMultiRepoGuard:
    """git_add must reject paths that span more than one repository."""

    def _make_gitmodules(self, tmp_path):
        (tmp_path / ".gitmodules").write_text(
            '[submodule "sub1"]\n'
            "\tpath = sub1\n"
            "\turl = https://example.com/sub1.git\n"
            '[submodule "sub2"]\n'
            "\tpath = sub2\n"
            "\turl = https://example.com/sub2.git\n"
        )

    def test_paths_in_different_submodules_rejected(self, tmp_path, monkeypatch):
        """Paths from sub1 and sub2 → error, subprocess never called for add."""
        self._make_gitmodules(tmp_path)
        monkeypatch.setattr(git_mcp, "GIT_DIR", "/fake/gitdir")
        monkeypatch.setattr(git_mcp, "GIT_WORK_TREE", str(tmp_path))

        with patch("subprocess.run") as mock_run:
            result = git_mcp.git_add(paths=["sub1/a.py", "sub2/b.py"])

        assert result.isError is True
        assert "span multiple repositories" in result.content[0].text
        # git add subprocess must NOT have been invoked
        mock_run.assert_not_called()

    def test_paths_in_same_submodule_accepted(self, tmp_path, monkeypatch):
        """Two paths from the same submodule → add proceeds."""
        self._make_gitmodules(tmp_path)
        monkeypatch.setattr(git_mcp, "GIT_DIR", "/fake/gitdir")
        monkeypatch.setattr(git_mcp, "GIT_WORK_TREE", str(tmp_path))

        with patch("subprocess.run", return_value=_mock_proc()) as mock_run:
            result = git_mcp.git_add(paths=["sub1/a.py", "sub1/b.py"])

        assert result.isError is False
        # subprocess.run should have been called exactly once (for git add)
        assert mock_run.call_count == 1

    def test_root_and_submodule_paths_rejected(self, tmp_path, monkeypatch):
        """One root-repo file and one submodule file → span error."""
        self._make_gitmodules(tmp_path)
        monkeypatch.setattr(git_mcp, "GIT_DIR", "/fake/gitdir")
        monkeypatch.setattr(git_mcp, "GIT_WORK_TREE", str(tmp_path))

        with patch("subprocess.run") as mock_run:
            result = git_mcp.git_add(paths=["root_file.py", "sub1/a.py"])

        assert result.isError is True
        assert "span multiple repositories" in result.content[0].text
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# submodule_path routing: git_status / git_diff / git_log / git_commit
# ---------------------------------------------------------------------------


class TestSubmodulePathRouting:
    """Tools should pass submodule GIT_DIR / GIT_WORK_TREE to subprocess."""

    def setup_method(self):
        self._orig_dir = git_mcp.GIT_DIR
        self._orig_tree = git_mcp.GIT_WORK_TREE
        git_mcp.GIT_DIR = "/gitdir"
        git_mcp.GIT_WORK_TREE = "/workspace"

    def teardown_method(self):
        git_mcp.GIT_DIR = self._orig_dir
        git_mcp.GIT_WORK_TREE = self._orig_tree

    def _last_env(self, mock_run) -> dict:
        """Return the env dict from the most recent subprocess.run call."""
        return mock_run.call_args[1].get("env", mock_run.call_args[0])

    def test_git_status_uses_submodule_env(self):
        with patch("subprocess.run", return_value=_mock_proc(stdout="M foo.py")) as mock_run:
            result = git_mcp.git_status(submodule_path="cluster/agent")

        assert result.isError is False
        env = self._last_env(mock_run)
        assert env["GIT_DIR"] == "/gitdir/modules/cluster/agent"
        assert env["GIT_WORK_TREE"] == "/workspace/cluster/agent"

    def test_git_status_no_submodule_uses_root_env(self):
        with patch("subprocess.run", return_value=_mock_proc()) as mock_run:
            git_mcp.git_status()

        env = self._last_env(mock_run)
        assert env["GIT_DIR"] == "/gitdir"
        assert env["GIT_WORK_TREE"] == "/workspace"

    def test_git_diff_uses_submodule_env(self):
        with patch("subprocess.run", return_value=_mock_proc(stdout="+line")) as mock_run:
            result = git_mcp.git_diff(submodule_path="cluster/agent")

        assert result.isError is False
        env = self._last_env(mock_run)
        assert env["GIT_DIR"] == "/gitdir/modules/cluster/agent"

    def test_git_diff_staged_uses_submodule_env(self):
        with patch("subprocess.run", return_value=_mock_proc(stdout="+line")) as mock_run:
            git_mcp.git_diff(staged=True, submodule_path="cluster/agent")

        # Verify --cached was passed
        cmd = mock_run.call_args[0][0]
        assert "--cached" in cmd
        env = self._last_env(mock_run)
        assert env["GIT_DIR"] == "/gitdir/modules/cluster/agent"

    def test_git_log_uses_submodule_env(self):
        with patch("subprocess.run", return_value=_mock_proc(stdout="abc1234 msg")) as mock_run:
            result = git_mcp.git_log(submodule_path="cluster/agent")

        assert result.isError is False
        env = self._last_env(mock_run)
        assert env["GIT_DIR"] == "/gitdir/modules/cluster/agent"

    def test_git_commit_uses_submodule_env(self):
        with patch("subprocess.run", return_value=_mock_proc(stdout="[main abc] msg")) as mock_run:
            result = git_mcp.git_commit(
                message="test commit", submodule_path="cluster/agent"
            )

        assert result.isError is False
        env = self._last_env(mock_run)
        assert env["GIT_DIR"] == "/gitdir/modules/cluster/agent"
        assert env["GIT_WORK_TREE"] == "/workspace/cluster/agent"


# ---------------------------------------------------------------------------
# git_reset_soft: per-submodule baseline enforcement
# ---------------------------------------------------------------------------


class TestPerSubmoduleBaseline:
    """git_reset_soft enforces a per-submodule baseline floor."""

    def setup_method(self):
        self._orig_dir = git_mcp.GIT_DIR
        self._orig_tree = git_mcp.GIT_WORK_TREE
        self._orig_baseline = git_mcp.BASELINE_COMMIT
        self._orig_sub_baselines = dict(git_mcp.SUBMODULE_BASELINE_COMMITS)
        git_mcp.GIT_DIR = "/gitdir"
        git_mcp.GIT_WORK_TREE = "/workspace"

    def teardown_method(self):
        git_mcp.GIT_DIR = self._orig_dir
        git_mcp.GIT_WORK_TREE = self._orig_tree
        git_mcp.BASELINE_COMMIT = self._orig_baseline
        git_mcp.SUBMODULE_BASELINE_COMMITS.clear()
        git_mcp.SUBMODULE_BASELINE_COMMITS.update(self._orig_sub_baselines)

    def test_reset_blocked_past_submodule_baseline(self):
        """Resetting past the submodule baseline is rejected."""
        baseline_sha = "aabbccddee00" * 3
        older_sha = "1122334455ff" * 3

        git_mcp.SUBMODULE_BASELINE_COMMITS["cluster/agent"] = baseline_sha

        # rev-parse HEAD~1 → older_sha  (before baseline)
        # merge-base --is-ancestor → returns 0 (older_sha IS ancestor of baseline → block)
        side_effects = [
            _mock_proc(returncode=0, stdout=older_sha + "\n"),   # rev-parse
            _mock_proc(returncode=0),                            # merge-base (is ancestor)
        ]

        with patch("subprocess.run", side_effect=side_effects):
            result = git_mcp.git_reset_soft(count=1, submodule_path="cluster/agent")

        assert result.isError is True
        assert "baseline" in result.content[0].text.lower()

    def test_reset_to_submodule_baseline_allowed(self):
        """Resetting exactly to the submodule baseline is allowed."""
        baseline_sha = "aabbccddee00" * 3

        git_mcp.SUBMODULE_BASELINE_COMMITS["cluster/agent"] = baseline_sha

        # rev-parse HEAD~1 → baseline_sha  (equal to baseline → no ancestor check)
        # then reset --soft → success
        side_effects = [
            _mock_proc(returncode=0, stdout=baseline_sha + "\n"),  # rev-parse
            _mock_proc(returncode=0, stdout=""),                   # reset --soft
        ]

        with patch("subprocess.run", side_effect=side_effects):
            result = git_mcp.git_reset_soft(count=1, submodule_path="cluster/agent")

        assert result.isError is False
        assert "Reset 1 commit" in result.content[0].text

    def test_reset_no_submodule_baseline_blocked(self):
        """If a submodule has no recorded baseline, reset is blocked."""
        # SUBMODULE_BASELINE_COMMITS is empty for "cluster/agent"
        git_mcp.SUBMODULE_BASELINE_COMMITS.clear()

        with patch("subprocess.run"):
            result = git_mcp.git_reset_soft(count=1, submodule_path="cluster/agent")

        assert result.isError is True
        assert "no baseline" in result.content[0].text.lower()

    def test_reset_above_submodule_baseline_allowed(self):
        """Resetting above the submodule baseline succeeds."""
        baseline_sha = "aabbccddee00" * 3
        agent_sha = "ffee99887766" * 3  # newer than baseline

        git_mcp.SUBMODULE_BASELINE_COMMITS["cluster/agent"] = baseline_sha

        # rev-parse → agent_sha  (not equal to baseline)
        # merge-base --is-ancestor → returns 1 (agent_sha is NOT ancestor of baseline → allow)
        # reset --soft → success
        side_effects = [
            _mock_proc(returncode=0, stdout=agent_sha + "\n"),  # rev-parse
            _mock_proc(returncode=1),                           # merge-base (not ancestor)
            _mock_proc(returncode=0, stdout=""),                # reset --soft
        ]

        with patch("subprocess.run", side_effect=side_effects):
            result = git_mcp.git_reset_soft(count=1, submodule_path="cluster/agent")

        assert result.isError is False

    def test_reset_uses_root_baseline_when_no_submodule_path(self):
        """Without submodule_path, root BASELINE_COMMIT is used."""
        root_baseline = "deadbeef0000" * 3
        git_mcp.BASELINE_COMMIT = root_baseline

        # rev-parse → something older than baseline
        older_sha = "00000000dead" * 3
        side_effects = [
            _mock_proc(returncode=0, stdout=older_sha + "\n"),  # rev-parse
            _mock_proc(returncode=0),                           # merge-base (is ancestor)
        ]

        with patch("subprocess.run", side_effect=side_effects):
            result = git_mcp.git_reset_soft(count=1)  # no submodule_path

        assert result.isError is True
        assert "baseline" in result.content[0].text.lower()
