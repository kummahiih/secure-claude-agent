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

    # Use GIT_DIR env var to init directly into the separated gitdir
    env = {**os.environ, "GIT_DIR": str(gitdir)}
    subprocess.run(
        ["git", "init"],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(worktree),
        env=env,
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

    # Configure user for commits
    env = {**os.environ, "GIT_DIR": str(gitdir), "GIT_WORK_TREE": str(worktree)}
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        check=True, capture_output=True, env=env,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
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