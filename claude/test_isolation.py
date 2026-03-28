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
        "PLAN_API_TOKEN": "test-plan-token",
        "TESTER_API_TOKEN": "test-tester-token",
        "CLAUDE_API_TOKEN": "test-claude-token",
        "ANTHROPIC_BASE_URL": "https://proxy:4000",
    }


@pytest.fixture
def clean_env_proxy():
    """Env vars that a correctly configured proxy would have."""
    return {
        "ANTHROPIC_API_KEY": "sk-ant-real-key",
        "DYNAMIC_AGENT_KEY": "test-dynamic-key",
    }


@pytest.fixture
def clean_env_mcp_server():
    """Env vars that a correctly configured mcp-server would have."""
    return {
        "MCP_API_TOKEN": "test-mcp-token",
    }


@pytest.fixture
def clean_env_caddy():
    """Env vars that a correctly configured caddy would have."""
    return {
    }


# --- Helpers for filesystem mocking ---

# Required paths per role — exists() returns True for these
ROLE_REQUIRED_PATHS = {
    "claude-server": {
        "/app/server.py", "/app/files_mcp.py",
        "/app/verify_isolation.py", "/home/appuser/sandbox/.mcp.json",
    },
    "mcp-server": {"/workspace"},
    "proxy": {"/app/certs/proxy.crt", "/app/certs/proxy.key"},
    "caddy": {
        "/etc/caddy/certs/caddy.crt", "/etc/caddy/certs/caddy.key",
        "/etc/caddy/certs/ca.crt",
    },
}


def _make_exists(role):
    """Return an os.path.exists side_effect that passes required paths and fails forbidden."""
    required = ROLE_REQUIRED_PATHS.get(role, set())
    return lambda p: p in required


# --- Env var tests ---

class TestForbiddenEnvVars:
    """Containers must never see env vars that belong to other containers."""

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

    def test_proxy_rejects_mcp_token(self, clean_env_proxy):
        env = {**clean_env_proxy, "MCP_API_TOKEN": "leaked"}
        with patch.dict(os.environ, env, clear=True), \
             patch("os.path.exists", side_effect=_make_exists("proxy")), \
             patch("verify_isolation.find_env_files", return_value=[]):
            with pytest.raises(SystemExit):
                vi.verify_all("proxy")

    def test_proxy_rejects_claude_api_token(self, clean_env_proxy):
        env = {**clean_env_proxy, "CLAUDE_API_TOKEN": "leaked"}
        with patch.dict(os.environ, env, clear=True), \
             patch("os.path.exists", side_effect=_make_exists("proxy")), \
             patch("verify_isolation.find_env_files", return_value=[]):
            with pytest.raises(SystemExit):
                vi.verify_all("proxy")

    def test_proxy_rejects_plan_api_token(self, clean_env_proxy):
        env = {**clean_env_proxy, "PLAN_API_TOKEN": "leaked"}
        with patch.dict(os.environ, env, clear=True), \
             patch("os.path.exists", side_effect=_make_exists("proxy")), \
             patch("verify_isolation.find_env_files", return_value=[]):
            with pytest.raises(SystemExit):
                vi.verify_all("proxy")

    def test_proxy_rejects_tester_api_token(self, clean_env_proxy):
        env = {**clean_env_proxy, "TESTER_API_TOKEN": "leaked"}
        with patch.dict(os.environ, env, clear=True), \
             patch("os.path.exists", side_effect=_make_exists("proxy")), \
             patch("verify_isolation.find_env_files", return_value=[]):
            with pytest.raises(SystemExit):
                vi.verify_all("proxy")

    def test_proxy_allows_real_api_key(self, clean_env_proxy):
        """Proxy is the one container that SHOULD have the real key."""
        with patch.dict(os.environ, clean_env_proxy, clear=True), \
             patch("os.path.exists", side_effect=_make_exists("proxy")), \
             patch("verify_isolation.find_env_files", return_value=[]):
            vi.verify_all("proxy")

    def test_caddy_rejects_all_backend_tokens(self, clean_env_caddy):
        for var in ["ANTHROPIC_API_KEY", "DYNAMIC_AGENT_KEY", "MCP_API_TOKEN", "PLAN_API_TOKEN", "TESTER_API_TOKEN", "CLAUDE_API_TOKEN"]:
            env = {**clean_env_caddy, var: "leaked"}
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(SystemExit):
                    vi.verify_all("caddy")


class TestRequiredEnvVars:
    """Each container must have its required env vars or fail."""

    def test_claude_server_missing_dynamic_key(self):
        env = {"MCP_API_TOKEN": "t", "PLAN_API_TOKEN": "t", "TESTER_API_TOKEN": "t", "CLAUDE_API_TOKEN": "t", "ANTHROPIC_BASE_URL": "t"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("claude-server")

    def test_claude_server_missing_mcp_token(self):
        env = {"DYNAMIC_AGENT_KEY": "t", "PLAN_API_TOKEN": "t", "TESTER_API_TOKEN": "t", "CLAUDE_API_TOKEN": "t", "ANTHROPIC_BASE_URL": "t"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("claude-server")

    def test_claude_server_missing_claude_api_token(self):
        env = {"DYNAMIC_AGENT_KEY": "t", "MCP_API_TOKEN": "t", "PLAN_API_TOKEN": "t", "TESTER_API_TOKEN": "t", "ANTHROPIC_BASE_URL": "t"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("claude-server")

    def test_claude_server_missing_base_url(self):
        env = {"DYNAMIC_AGENT_KEY": "t", "MCP_API_TOKEN": "t", "PLAN_API_TOKEN": "t", "TESTER_API_TOKEN": "t", "CLAUDE_API_TOKEN": "t"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("claude-server")

    def test_plan_server_rejects_mcp_token(self):
        env = {"PLAN_API_TOKEN": "t", "MCP_API_TOKEN": "leaked"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("plan-server")

    def test_tester_server_rejects_mcp_token(self):
        env = {"TESTER_API_TOKEN": "t", "MCP_API_TOKEN": "leaked"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("tester-server")

    def test_plan_server_rejects_tester_token(self):
        env = {"PLAN_API_TOKEN": "t", "TESTER_API_TOKEN": "leaked"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("plan-server")

    def test_tester_server_rejects_plan_token(self):
        env = {"TESTER_API_TOKEN": "t", "PLAN_API_TOKEN": "leaked"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("tester-server")

    def test_plan_server_missing_plan_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("plan-server")

    def test_tester_server_missing_tester_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(SystemExit):
                vi.verify_all("tester-server")

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
        required = ROLE_REQUIRED_PATHS["claude-server"]
        with patch.dict(os.environ, clean_env_claude_server, clear=True), \
             patch("os.path.exists", side_effect=lambda p: p == forbidden_path or p in required):
            with pytest.raises(SystemExit):
                vi.verify_all("claude-server")

    @pytest.mark.parametrize("forbidden_path", [
        "/app/server.py",
        "/app/files_mcp.py",
        "/workspace",
    ])
    def test_proxy_rejects_forbidden_path(self, clean_env_proxy, forbidden_path):
        required = ROLE_REQUIRED_PATHS["proxy"]
        with patch.dict(os.environ, clean_env_proxy, clear=True), \
             patch("os.path.exists", side_effect=lambda p: p == forbidden_path or p in required), \
             patch("verify_isolation.find_env_files", return_value=[]):
            with pytest.raises(SystemExit):
                vi.verify_all("proxy")

    @pytest.mark.parametrize("forbidden_path", [
        "/app",
        "/workspace",
    ])
    def test_caddy_rejects_forbidden_path(self, clean_env_caddy, forbidden_path):
        required = ROLE_REQUIRED_PATHS["caddy"]
        with patch.dict(os.environ, clean_env_caddy, clear=True), \
             patch("os.path.exists", side_effect=lambda p: p == forbidden_path or p in required), \
             patch("verify_isolation.find_env_files", return_value=[]):
            with pytest.raises(SystemExit):
                vi.verify_all("caddy")


class TestWorkspaceEntries:
    """
    /workspace must only contain the allowed entries (mcp-server only).
    """

    def test_clean_workspace_passes(self, clean_env_mcp_server):
        clean_entries = ["claude", "fileserver", ".git", ".gitignore"]
        with patch.dict(os.environ, clean_env_mcp_server, clear=True), \
             patch("os.path.exists", side_effect=_make_exists("mcp-server")), \
             patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=clean_entries), \
             patch("verify_isolation.find_env_files", return_value=[]), \
             patch("verify_isolation.check_git_no_parent_leak", return_value=[]):
            vi.verify_all("mcp-server")

    def test_workspace_with_docker_compose_fails(self, clean_env_mcp_server):
        leaked_entries = ["claude", "fileserver", ".git", "docker-compose.yml"]
        with patch.dict(os.environ, clean_env_mcp_server, clear=True), \
             patch("os.path.exists", side_effect=_make_exists("mcp-server")), \
             patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=leaked_entries), \
             patch("verify_isolation.find_env_files", return_value=[]), \
             patch("verify_isolation.check_git_no_parent_leak", return_value=[]):
            with pytest.raises(SystemExit):
                vi.verify_all("mcp-server")

    def test_workspace_with_secrets_dir_fails(self, clean_env_mcp_server):
        leaked_entries = ["claude", "fileserver", "certs", ".secrets.env"]
        with patch.dict(os.environ, clean_env_mcp_server, clear=True), \
             patch("os.path.exists", side_effect=_make_exists("mcp-server")), \
             patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=leaked_entries), \
             patch("verify_isolation.find_env_files", return_value=[]), \
             patch("verify_isolation.check_git_no_parent_leak", return_value=[]):
            with pytest.raises(SystemExit):
                vi.verify_all("mcp-server")


# --- .env file scanner tests ---

class TestEnvFileScanner:
    """Detect .env files that shouldn't be in the image."""

    def test_finds_env_files(self, tmp_path):
        (tmp_path / ".secrets.env").touch()
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / ".env").touch()
        (tmp_path / "sub" / "config.yaml").touch()

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

    def test_proxy_clean_passes(self, clean_env_proxy):
        with patch.dict(os.environ, clean_env_proxy, clear=True), \
             patch("os.path.exists", side_effect=_make_exists("proxy")), \
             patch("verify_isolation.find_env_files", return_value=[]):
            vi.verify_all("proxy")

    def test_mcp_server_clean_passes(self, clean_env_mcp_server):
        with patch.dict(os.environ, clean_env_mcp_server, clear=True), \
             patch("os.path.exists", side_effect=_make_exists("mcp-server")), \
             patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=["claude", "fileserver", ".git"]), \
             patch("verify_isolation.find_env_files", return_value=[]), \
             patch("verify_isolation.check_git_no_parent_leak", return_value=[]):
            vi.verify_all("mcp-server")

    def test_caddy_clean_passes(self, clean_env_caddy):
        with patch.dict(os.environ, clean_env_caddy, clear=True), \
             patch("os.path.exists", side_effect=_make_exists("caddy")), \
             patch("verify_isolation.find_env_files", return_value=[]):
            vi.verify_all("caddy")

    def test_plan_server_clean_passes(self):
        env = {"PLAN_API_TOKEN": "test-plan-token"}
        with patch.dict(os.environ, env, clear=True):
            vi.verify_all("plan-server")

    def test_tester_server_clean_passes(self):
        env = {"TESTER_API_TOKEN": "test-tester-token"}
        with patch.dict(os.environ, env, clear=True):
            vi.verify_all("tester-server")


# --- Unknown role test ---

class TestUnknownRole:
    def test_unknown_role_exits(self):
        with pytest.raises(SystemExit):
            vi.verify_all("unknown-role")
