"""
test_isolation.py — Unit tests for verify_isolation.py

These tests mock the filesystem and environment to verify that the
isolation checks correctly detect violations and pass clean states.

Run with: pytest test_isolation.py -v
"""

import os
import pytest
from unittest.mock import patch

import verify_isolation as vi


# --- Fixtures ---

@pytest.fixture
def clean_env_claude_server():
    """Env vars that a correctly configured claude-server would have at entrypoint time."""
    return {
        "DYNAMIC_AGENT_KEY": "test-dynamic-key",
        "MCP_API_TOKEN": "test-mcp-token",
        "CLAUDE_API_TOKEN": "test-claude-token",
        "ANTHROPIC_BASE_URL": "https://proxy:4000",
        # Note: ANTHROPIC_API_KEY is intentionally absent — it only exists
        # inside the Claude Code subprocess, not at entrypoint time.
    }


@pytest.fixture
def clean_env_proxy():
    """Env vars that a correctly configured proxy would have."""
    return {
        "ANTHROPIC_API_KEY": "sk-ant-real-key",
    }


@pytest.fixture
def clean_env_mcp_server():
    """Env vars that a correctly configured mcp-server would have."""
    return {
        "MCP_API_TOKEN": "test-mcp-token",
    }


# --- Helper to mock filesystem for claude-server passing all checks ---

def _mock_claude_server_fs():
    """Return mocks that simulate a clean claude-server filesystem."""
    valid_mcp_json = '{"mcpServers": {"fileserver": {"type": "stdio"}}}'

    def exists_side_effect(p):
        # Required paths exist, forbidden paths don't
        required = {"/app/server.py", "/app/files_mcp.py",
                    "/app/verify_isolation.py", "/home/appuser/sandbox/.mcp.json"}
        return p in required

    return {
        "exists": exists_side_effect,
        "isdir": lambda p: False,  # No /workspace in claude-server
        "mcp_json": valid_mcp_json,
    }


# --- Env var tests ---

class TestForbiddenEnvVars:
    """claude-server and mcp-server must never see ANTHROPIC_API_KEY at entrypoint."""

    def test_claude_server_rejects_real_api_key(self, clean_env_claude_server):
        env = {**clean_env_claude_server, "ANTHROPIC_API_KEY": "sk-ant-real-key"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("claude-server")

    def test_mcp_server_rejects_real_api_key(self, clean_env_mcp_server):
        env = {**clean_env_mcp_server, "ANTHROPIC_API_KEY": "sk-ant-real-key"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("mcp-server")

    def test_proxy_allows_real_api_key(self, clean_env_proxy):
        """Proxy is the one container that SHOULD have the real key."""
        with patch.dict(os.environ, clean_env_proxy, clear=True), \
             patch("verify_isolation.find_env_files", return_value=[]):
            # Should not raise
            vi.verify_all("proxy")


class TestRequiredEnvVars:
    """Each container must have its required env vars or fail."""

    def test_claude_server_missing_dynamic_key(self):
        env = {"MCP_API_TOKEN": "t", "CLAUDE_API_TOKEN": "t", "ANTHROPIC_BASE_URL": "t"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("claude-server")

    def test_claude_server_missing_mcp_token(self):
        env = {"DYNAMIC_AGENT_KEY": "t", "CLAUDE_API_TOKEN": "t", "ANTHROPIC_BASE_URL": "t"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("claude-server")

    def test_claude_server_missing_claude_api_token(self):
        env = {"DYNAMIC_AGENT_KEY": "t", "MCP_API_TOKEN": "t", "ANTHROPIC_BASE_URL": "t"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("claude-server")

    def test_claude_server_missing_base_url(self):
        env = {"DYNAMIC_AGENT_KEY": "t", "MCP_API_TOKEN": "t", "CLAUDE_API_TOKEN": "t"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("claude-server")

    def test_proxy_missing_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("proxy")

    def test_mcp_server_missing_mcp_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("mcp-server")


# --- Filesystem tests ---

class TestForbiddenPaths:
    """Secrets and parent repo artifacts must not exist in agent containers."""

    @pytest.mark.parametrize("forbidden_path", [
        "/app/.secrets.env",
        "/app/.cluster_tokens.env",
        "/workspace/.secrets.env",
        "/workspace/docker-compose.yml",
        "/workspace/proxy_config.yaml",
        "/workspace/Dockerfile.claude",
        "/workspace/certs",
    ])
    def test_claude_server_rejects_forbidden_path(
        self, clean_env_claude_server, forbidden_path
    ):
        with patch.dict(os.environ, clean_env_claude_server, clear=True), \
             patch("os.path.exists") as mock_exists:
            # Only the forbidden path "exists"
            mock_exists.side_effect = lambda p: p == forbidden_path
            with pytest.raises(SystemExit):
                vi.verify_all("claude-server")


class TestWorkspaceEntries:
    """
    /workspace must only contain the allowed entries (mcp-server only).
    """

    def test_clean_workspace_passes(self, clean_env_mcp_server):
        clean_entries = ["claude", "fileserver", ".git", ".gitignore"]
        with patch.dict(os.environ, clean_env_mcp_server, clear=True), \
             patch("os.path.exists") as mock_exists, \
             patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=clean_entries), \
             patch("verify_isolation.find_env_files", return_value=[]), \
             patch("verify_isolation.check_git_no_parent_leak", return_value=[]):
            mock_exists.side_effect = lambda p: p == "/workspace"
            vi.verify_all("mcp-server")

    def test_workspace_with_docker_compose_fails(self, clean_env_mcp_server):
        leaked_entries = ["claude", "fileserver", ".git", "docker-compose.yml"]
        with patch.dict(os.environ, clean_env_mcp_server, clear=True), \
             patch("os.path.exists") as mock_exists, \
             patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=leaked_entries), \
             patch("verify_isolation.find_env_files", return_value=[]), \
             patch("verify_isolation.check_git_no_parent_leak", return_value=[]):
            mock_exists.side_effect = lambda p: p == "/workspace"
            with pytest.raises(SystemExit):
                vi.verify_all("mcp-server")

    def test_workspace_with_secrets_dir_fails(self, clean_env_mcp_server):
        leaked_entries = ["claude", "fileserver", "certs", ".secrets.env"]
        with patch.dict(os.environ, clean_env_mcp_server, clear=True), \
             patch("os.path.exists") as mock_exists, \
             patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=leaked_entries), \
             patch("verify_isolation.find_env_files", return_value=[]), \
             patch("verify_isolation.check_git_no_parent_leak", return_value=[]):
            mock_exists.side_effect = lambda p: p == "/workspace"
            with pytest.raises(SystemExit):
                vi.verify_all("mcp-server")


# --- .env file scanner tests ---

class TestEnvFileScanner:
    """Detect .env files that shouldn't be in the image."""

    def test_finds_env_files(self, tmp_path):
        (tmp_path / ".secrets.env").touch()
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / ".env").touch()
        (tmp_path / "sub" / "config.yaml").touch()  # not .env

        found = vi.find_env_files([str(tmp_path)])
        assert len(found) == 2
        assert any(".secrets.env" in f for f in found)
        assert any(".env" in f and "sub" in f for f in found)

    def test_ignores_nonexistent_dirs(self):
        found = vi.find_env_files(["/nonexistent/path"])
        assert found == []


# --- Git parent leak tests ---

class TestGitParentLeak:
    """Submodule .git must not reference parent repo."""

    def test_git_directory_is_safe(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        errors = vi.check_git_no_parent_leak(str(tmp_path))
        assert errors == []

    def test_gitfile_inside_workspace_is_safe(self, tmp_path):
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: .git-internal/modules/agent")
        (tmp_path / ".git-internal" / "modules" / "agent").mkdir(parents=True)
        errors = vi.check_git_no_parent_leak(str(tmp_path))
        assert errors == []

    def test_gitfile_outside_workspace_is_violation(self, tmp_path):
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: ../../.git/modules/agent")
        errors = vi.check_git_no_parent_leak(str(tmp_path))
        assert len(errors) == 1
        assert "outside workspace" in errors[0]

    def test_no_git_at_all_is_fine(self, tmp_path):
        errors = vi.check_git_no_parent_leak(str(tmp_path))
        assert errors == []


# --- MCP config validation tests ---

class TestMcpConfig:
    """MCP config must exist and have correct structure."""

    def test_valid_config(self, tmp_path):
        config = tmp_path / ".mcp.json"
        config.write_text('{"mcpServers": {"fileserver": {"type": "stdio"}}}')
        errors = vi.check_mcp_config(str(config))
        assert errors == []

    def test_missing_file(self, tmp_path):
        errors = vi.check_mcp_config(str(tmp_path / "nonexistent.json"))
        assert len(errors) == 1
        assert "missing" in errors[0]

    def test_invalid_json(self, tmp_path):
        config = tmp_path / ".mcp.json"
        config.write_text("not json")
        errors = vi.check_mcp_config(str(config))
        assert len(errors) == 1
        assert "invalid" in errors[0].lower()

    def test_missing_mcp_servers_key(self, tmp_path):
        config = tmp_path / ".mcp.json"
        config.write_text('{"other": "stuff"}')
        errors = vi.check_mcp_config(str(config))
        assert len(errors) == 1
        assert "mcpServers" in errors[0]

    def test_missing_fileserver_entry(self, tmp_path):
        config = tmp_path / ".mcp.json"
        config.write_text('{"mcpServers": {"other": {}}}')
        errors = vi.check_mcp_config(str(config))
        assert len(errors) == 1
        assert "fileserver" in errors[0]


# --- Full pass tests ---

class TestFullPass:
    """Verify that clean configurations pass all checks."""

    def test_claude_server_clean_passes(self, clean_env_claude_server):
        fs = _mock_claude_server_fs()
        with patch.dict(os.environ, clean_env_claude_server, clear=True), \
             patch("os.path.exists", side_effect=fs["exists"]), \
             patch("os.path.isdir", side_effect=fs["isdir"]), \
             patch("verify_isolation.find_env_files", return_value=[]), \
             patch("builtins.open", create=True) as mock_open:
            import io
            mock_open.return_value.__enter__ = lambda s: io.StringIO(fs["mcp_json"])
            mock_open.return_value.__exit__ = lambda s, *a: None
            # This should not raise
            vi.verify_all("claude-server")

    def test_proxy_clean_passes(self, clean_env_proxy):
        with patch.dict(os.environ, clean_env_proxy, clear=True), \
             patch("verify_isolation.find_env_files", return_value=[]):
            vi.verify_all("proxy")


# --- Unknown role test ---

class TestUnknownRole:
    def test_unknown_role_exits(self):
        with pytest.raises(SystemExit):
            vi.verify_all("unknown-role")
