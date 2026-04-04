"""
test_isolation.py — Unit tests for verify_isolation.py

Tests cover:
- FORBIDDEN_ENV_VARS checks per role
- REQUIRED_ENV_VARS checks per role
- FORBIDDEN_PATHS checks per role
- .env file scanner
- Workspace entry whitelist
- .git parent leak check
- MCP config validation
- Unknown role handling
- Full-pass happy paths

RR-19 regression: LOG_API_TOKEN must be forbidden in proxy and caddy.
"""

import os
import sys
import pytest
from unittest.mock import patch

import verify_isolation
from verify_isolation import verify_all


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_env_mcp_server():
    """Env vars that a correctly configured mcp-server would have."""
    return {"MCP_API_TOKEN": "dummy"}


@pytest.fixture
def clean_env_caddy():
    """Env vars that a correctly configured caddy would have."""
    return {}


@pytest.fixture
def clean_env_proxy():
    """Env vars that a correctly configured proxy would have."""
    return {
        "ANTHROPIC_API_KEY": "sk-real-key",
        "DYNAMIC_AGENT_KEY": "dummy-dynamic",
    }


@pytest.fixture
def clean_env_claude_server():
    """Env vars that a correctly configured claude-server would have."""
    return {
        "DYNAMIC_AGENT_KEY": "dummy-dynamic",
        "MCP_API_TOKEN": "dummy-mcp",
        "PLAN_API_TOKEN": "dummy-plan",
        "TESTER_API_TOKEN": "dummy-tester",
        "CLAUDE_API_TOKEN": "dummy-claude",
        "ANTHROPIC_BASE_URL": "https://proxy:4000",
        "GIT_API_TOKEN": "dummy-git",
        "LOG_API_TOKEN": "dummy-log",
    }


def _required_paths_for(role):
    """Return a dict mapping each required path to True (exists) for the role."""
    return {p: True for p in verify_isolation.REQUIRED_PATHS.get(role, [])}


# ---------------------------------------------------------------------------
# TestForbiddenEnvVars
# ---------------------------------------------------------------------------

class TestForbiddenEnvVars:
    """Verify that forbidden env vars are detected and cause exit(1)."""

    def _run_with_env(self, role, extra_env):
        """Run verify_all for role with only the given env vars set."""
        with patch.dict(os.environ, extra_env, clear=True), \
             patch("os.path.exists", return_value=False), \
             patch("verify_isolation.find_env_files", return_value=[]):
            with pytest.raises(SystemExit):
                verify_all(role)

    def test_claude_server_rejects_real_api_key(self):
        self._run_with_env("claude-server", {"ANTHROPIC_API_KEY": "sk-real"})

    def test_mcp_server_rejects_real_api_key(self):
        self._run_with_env("mcp-server", {"ANTHROPIC_API_KEY": "sk-real"})

    def test_proxy_rejects_mcp_token(self):
        self._run_with_env("proxy", {"MCP_API_TOKEN": "tok", "ANTHROPIC_API_KEY": "key", "DYNAMIC_AGENT_KEY": "dkey"})

    def test_proxy_rejects_claude_api_token(self):
        self._run_with_env("proxy", {"CLAUDE_API_TOKEN": "tok", "ANTHROPIC_API_KEY": "key", "DYNAMIC_AGENT_KEY": "dkey"})

    def test_proxy_rejects_git_api_token(self):
        self._run_with_env("proxy", {"GIT_API_TOKEN": "tok", "ANTHROPIC_API_KEY": "key", "DYNAMIC_AGENT_KEY": "dkey"})

    def test_proxy_rejects_log_api_token(self):
        """RR-19: LOG_API_TOKEN must be forbidden in proxy."""
        self._run_with_env("proxy", {"LOG_API_TOKEN": "tok", "ANTHROPIC_API_KEY": "key", "DYNAMIC_AGENT_KEY": "dkey"})

    def test_proxy_allows_real_api_key(self):
        """ANTHROPIC_API_KEY is required (not forbidden) in proxy."""
        assert "ANTHROPIC_API_KEY" not in verify_isolation.FORBIDDEN_ENV_VARS.get("proxy", [])

    def test_caddy_rejects_all_backend_tokens(self):
        for token in ["ANTHROPIC_API_KEY", "MCP_API_TOKEN", "PLAN_API_TOKEN",
                      "TESTER_API_TOKEN", "GIT_API_TOKEN"]:
            self._run_with_env("caddy", {token: "tok"})

    def test_caddy_rejects_log_api_token(self):
        """RR-19: LOG_API_TOKEN must be forbidden in caddy."""
        self._run_with_env("caddy", {"LOG_API_TOKEN": "tok"})

    def test_log_api_token_in_proxy_forbidden_list(self):
        """Structural: LOG_API_TOKEN must appear in FORBIDDEN_ENV_VARS['proxy']."""
        assert "LOG_API_TOKEN" in verify_isolation.FORBIDDEN_ENV_VARS["proxy"], \
            "RR-19 fix missing: LOG_API_TOKEN must be forbidden in proxy"

    def test_log_api_token_in_caddy_forbidden_list(self):
        """Structural: LOG_API_TOKEN must appear in FORBIDDEN_ENV_VARS['caddy']."""
        assert "LOG_API_TOKEN" in verify_isolation.FORBIDDEN_ENV_VARS["caddy"], \
            "RR-19 fix missing: LOG_API_TOKEN must be forbidden in caddy"


# ---------------------------------------------------------------------------
# TestRequiredEnvVars
# ---------------------------------------------------------------------------

class TestRequiredEnvVars:
    """Verify that missing required env vars cause exit(1)."""

    def _run_missing(self, role, env_without):
        """Run verify_all for role with env_without removed."""
        required_vars = verify_isolation.REQUIRED_ENV_VARS.get(role, [])
        env = {k: "dummy" for k in required_vars if k != env_without}
        with patch.dict(os.environ, env, clear=True), \
             patch("os.path.exists", return_value=False), \
             patch("verify_isolation.find_env_files", return_value=[]):
            with pytest.raises(SystemExit):
                verify_all(role)

    def test_claude_server_missing_dynamic_key(self):
        self._run_missing("claude-server", "DYNAMIC_AGENT_KEY")

    def test_claude_server_missing_mcp_token(self):
        self._run_missing("claude-server", "MCP_API_TOKEN")

    def test_claude_server_missing_claude_api_token(self):
        self._run_missing("claude-server", "CLAUDE_API_TOKEN")

    def test_claude_server_missing_base_url(self):
        self._run_missing("claude-server", "ANTHROPIC_BASE_URL")

    def test_claude_server_missing_git_api_token(self):
        self._run_missing("claude-server", "GIT_API_TOKEN")

    def test_claude_server_missing_log_api_token(self):
        self._run_missing("claude-server", "LOG_API_TOKEN")

    def test_mcp_server_missing_mcp_token(self):
        self._run_missing("mcp-server", "MCP_API_TOKEN")

    def test_proxy_missing_api_key(self):
        self._run_missing("proxy", "ANTHROPIC_API_KEY")


# ---------------------------------------------------------------------------
# TestForbiddenPaths
# ---------------------------------------------------------------------------

class TestForbiddenPaths:
    """Verify that forbidden filesystem paths cause exit(1)."""

    @pytest.mark.parametrize("path", [
        "/app/.secrets.env",
        "/app/.cluster_tokens.env",
        "/workspace/.secrets.env",
        "/workspace/docker-compose.yml",
        "/workspace/Dockerfile.claude",
        "/workspace/certs",
        "/workspace/proxy_config.yaml",
    ])
    def test_claude_server_rejects_forbidden_path(self, path):
        def exists(p):
            return p == path
        with patch.dict(os.environ, {}, clear=True), \
             patch("os.path.exists", side_effect=exists), \
             patch("verify_isolation.find_env_files", return_value=[]):
            with pytest.raises(SystemExit):
                verify_all("claude-server")

    @pytest.mark.parametrize("path", [
        "/app/server.py",
        "/app/files_mcp.py",
        "/workspace",
    ])
    def test_proxy_rejects_forbidden_path(self, path):
        def exists(p):
            return p == path
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k", "DYNAMIC_AGENT_KEY": "d"}, clear=True), \
             patch("os.path.exists", side_effect=exists), \
             patch("verify_isolation.find_env_files", return_value=[]):
            with pytest.raises(SystemExit):
                verify_all("proxy")

    @pytest.mark.parametrize("path", ["/app", "/workspace"])
    def test_caddy_rejects_forbidden_path(self, path):
        def exists(p):
            return p == path
        with patch.dict(os.environ, {}, clear=True), \
             patch("os.path.exists", side_effect=exists), \
             patch("verify_isolation.find_env_files", return_value=[]):
            with pytest.raises(SystemExit):
                verify_all("caddy")


# ---------------------------------------------------------------------------
# TestEnvFileScanner
# ---------------------------------------------------------------------------

class TestEnvFileScanner:
    def test_finds_env_files(self, tmp_path):
        env_file = tmp_path / ".secrets.env"
        env_file.write_text("SECRET=bad")
        found = verify_isolation.find_env_files([str(tmp_path)])
        assert str(env_file) in found

    def test_ignores_nonexistent_dirs(self):
        found = verify_isolation.find_env_files(["/nonexistent/path/xyz"])
        assert found == []


# ---------------------------------------------------------------------------
# TestWorkspaceEntries
# ---------------------------------------------------------------------------

class TestWorkspaceEntries:
    def test_clean_workspace_passes(self):
        clean_entries = list(verify_isolation.WORKSPACE_ALLOWED_ENTRIES)
        required = set(verify_isolation.REQUIRED_PATHS.get("mcp-server", []))
        def exists_mcp(p):
            return p in required
        with patch.dict(os.environ, {"MCP_API_TOKEN": "dummy"}, clear=True), \
             patch("os.path.exists", side_effect=exists_mcp), \
             patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=clean_entries), \
             patch("verify_isolation.find_env_files", return_value=[]), \
             patch("verify_isolation.check_git_no_parent_leak", return_value=[]):
            # Should not raise
            try:
                verify_all("mcp-server")
            except SystemExit:
                pytest.fail("verify_all raised SystemExit for clean workspace")

    def test_workspace_with_docker_compose_fails(self):
        dirty_entries = list(verify_isolation.WORKSPACE_ALLOWED_ENTRIES) + ["docker-compose.yml"]
        with patch.dict(os.environ, {"MCP_API_TOKEN": "dummy"}, clear=True), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=dirty_entries), \
             patch("verify_isolation.find_env_files", return_value=[]), \
             patch("verify_isolation.check_git_no_parent_leak", return_value=[]):
            with pytest.raises(SystemExit):
                verify_all("mcp-server")

    def test_workspace_with_secrets_dir_fails(self):
        dirty_entries = list(verify_isolation.WORKSPACE_ALLOWED_ENTRIES) + [".secrets.env"]
        with patch.dict(os.environ, {"MCP_API_TOKEN": "dummy"}, clear=True), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=dirty_entries), \
             patch("verify_isolation.find_env_files", return_value=[]), \
             patch("verify_isolation.check_git_no_parent_leak", return_value=[]):
            with pytest.raises(SystemExit):
                verify_all("mcp-server")


# ---------------------------------------------------------------------------
# TestGitParentLeak
# ---------------------------------------------------------------------------

class TestGitParentLeak:
    def test_no_git_at_all_is_fine(self, tmp_path):
        errors = verify_isolation.check_git_no_parent_leak(str(tmp_path))
        assert errors == []

    def test_git_directory_is_safe(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        errors = verify_isolation.check_git_no_parent_leak(str(tmp_path))
        assert errors == []

    def test_gitfile_inside_workspace_is_safe(self, tmp_path):
        git_file = tmp_path / ".git"
        git_file.write_text(f"gitdir: {tmp_path}/.git/modules/agent")
        errors = verify_isolation.check_git_no_parent_leak(str(tmp_path))
        assert errors == []

    def test_gitfile_outside_workspace_is_violation(self, tmp_path):
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: ../../.git/modules/agent")
        errors = verify_isolation.check_git_no_parent_leak(str(tmp_path))
        assert len(errors) == 1
        assert "outside workspace" in errors[0]


# ---------------------------------------------------------------------------
# TestMcpConfig
# ---------------------------------------------------------------------------

class TestMcpConfig:
    def test_missing_file(self, tmp_path):
        errors = verify_isolation.check_mcp_config(str(tmp_path / "missing.json"))
        assert any("missing" in e for e in errors)

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not json")
        errors = verify_isolation.check_mcp_config(str(f))
        assert any("invalid" in e.lower() for e in errors)

    def test_missing_mcp_servers_key(self, tmp_path):
        f = tmp_path / "cfg.json"
        f.write_text('{"other": {}}')
        errors = verify_isolation.check_mcp_config(str(f))
        assert any("mcpServers" in e for e in errors)

    def test_missing_fileserver_entry(self, tmp_path):
        f = tmp_path / "cfg.json"
        f.write_text('{"mcpServers": {"other": {}}}')
        errors = verify_isolation.check_mcp_config(str(f))
        assert any("fileserver" in e for e in errors)

    def test_valid_config(self, tmp_path):
        f = tmp_path / "cfg.json"
        f.write_text('{"mcpServers": {"fileserver": {"command": "python"}}}')
        errors = verify_isolation.check_mcp_config(str(f))
        assert errors == []


# ---------------------------------------------------------------------------
# TestFullPass
# ---------------------------------------------------------------------------

def _exists_only_required(role):
    """Return a side_effect for os.path.exists: True iff path is required for role."""
    required = set(verify_isolation.REQUIRED_PATHS.get(role, []))
    return lambda p: p in required


class TestFullPass:
    """Happy-path: verify_all must not raise for clean environments."""

    def test_proxy_clean_passes(self, clean_env_proxy):
        with patch.dict(os.environ, clean_env_proxy, clear=True), \
             patch("os.path.exists", side_effect=_exists_only_required("proxy")), \
             patch("verify_isolation.find_env_files", return_value=[]):
            try:
                verify_all("proxy")
            except SystemExit:
                pytest.fail("verify_all raised SystemExit for clean proxy env")

    def test_caddy_clean_passes(self, clean_env_caddy):
        with patch.dict(os.environ, clean_env_caddy, clear=True), \
             patch("os.path.exists", side_effect=_exists_only_required("caddy")), \
             patch("verify_isolation.find_env_files", return_value=[]):
            try:
                verify_all("caddy")
            except SystemExit:
                pytest.fail("verify_all raised SystemExit for clean caddy env")

    def test_mcp_server_clean_passes(self, clean_env_mcp_server):
        required = set(verify_isolation.REQUIRED_PATHS.get("mcp-server", []))
        def exists_mcp(p):
            # Return True for required paths, False for forbidden paths
            return p in required
        with patch.dict(os.environ, clean_env_mcp_server, clear=True), \
             patch("os.path.exists", side_effect=exists_mcp), \
             patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=list(verify_isolation.WORKSPACE_ALLOWED_ENTRIES)), \
             patch("verify_isolation.find_env_files", return_value=[]), \
             patch("verify_isolation.check_git_no_parent_leak", return_value=[]):
            try:
                verify_all("mcp-server")
            except SystemExit:
                pytest.fail("verify_all raised SystemExit for clean mcp-server env")


# ---------------------------------------------------------------------------
# TestUnknownRole
# ---------------------------------------------------------------------------

class TestUnknownRole:
    def test_unknown_role_exits(self):
        with pytest.raises(SystemExit):
            verify_all("unknown-role")
