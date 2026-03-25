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
