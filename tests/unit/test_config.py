# ABOUTME: Unit tests for configuration management
# ABOUTME: Tests settings loading, validation, and instance management

import os
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from argocd_mcp.config import ArgocdInstance, SecuritySettings, ServerSettings


@pytest.mark.unit
class TestArgocdInstance:
    """Tests for ArgocdInstance configuration."""

    def test_url_validation_adds_https(self):
        """Test that URL without scheme gets https added."""
        instance = ArgocdInstance(
            url="argocd.example.com",
            token=SecretStr("test"),
        )
        assert instance.url == "https://argocd.example.com"

    def test_url_validation_preserves_http(self):
        """Test that explicit http scheme is preserved."""
        instance = ArgocdInstance(
            url="http://argocd.local",
            token=SecretStr("test"),
        )
        assert instance.url == "http://argocd.local"

    def test_url_validation_removes_trailing_slash(self):
        """Test that trailing slash is removed from URL."""
        instance = ArgocdInstance(
            url="https://argocd.example.com/",
            token=SecretStr("test"),
        )
        assert instance.url == "https://argocd.example.com"

    def test_default_name(self):
        """Test default instance name."""
        instance = ArgocdInstance(
            url="https://argocd.example.com",
            token=SecretStr("test"),
        )
        assert instance.name == "default"

    def test_insecure_default_false(self):
        """Test insecure defaults to False."""
        instance = ArgocdInstance(
            url="https://argocd.example.com",
            token=SecretStr("test"),
        )
        assert instance.insecure is False


@pytest.mark.unit
class TestSecuritySettings:
    """Tests for SecuritySettings configuration."""

    def test_defaults(self):
        """Test default security settings."""
        settings = SecuritySettings()

        assert settings.read_only is True
        assert settings.disable_destructive is True
        assert settings.single_cluster is False
        assert settings.audit_log is None
        assert settings.mask_secrets is True
        assert settings.rate_limit_calls == 100
        assert settings.rate_limit_window == 60

    def test_env_prefix(self):
        """Test environment variable prefix."""
        with patch.dict(os.environ, {"MCP_READ_ONLY": "false"}):
            settings = SecuritySettings()
            assert settings.read_only is False


@pytest.mark.unit
class TestSecuritySettingsEnvBinding:
    """Verify every documented MCP_* env var actually binds to SecuritySettings.

    Guards against silent regressions if pydantic-settings or the env_prefix is
    ever changed — currently no test proves these wires exist end-to-end.
    """

    def test_mcp_read_only_binds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_READ_ONLY", "false")
        assert SecuritySettings().read_only is False

    def test_mcp_mask_secrets_binds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_MASK_SECRETS", "false")
        assert SecuritySettings().mask_secrets is False

    def test_mcp_disable_destructive_binds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_DISABLE_DESTRUCTIVE", "false")
        assert SecuritySettings().disable_destructive is False

    def test_mcp_single_cluster_binds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_SINGLE_CLUSTER", "true")
        assert SecuritySettings().single_cluster is True

    def test_mcp_rate_limit_calls_binds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_RATE_LIMIT_CALLS", "250")
        assert SecuritySettings().rate_limit_calls == 250

    def test_mcp_rate_limit_window_binds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_RATE_LIMIT_WINDOW", "30")
        assert SecuritySettings().rate_limit_window == 30

    def test_mcp_audit_log_binds(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        audit_path = tmp_path / "audit.log"
        monkeypatch.setenv("MCP_AUDIT_LOG", str(audit_path))
        assert SecuritySettings().audit_log == audit_path


@pytest.mark.unit
class TestServerSettings:
    """Tests for ServerSettings configuration."""

    def test_primary_instance_from_env(self):
        """Test primary instance created from environment variables."""
        settings = ServerSettings(
            argocd_url="https://argocd.example.com",
            argocd_token=SecretStr("test-token"),
        )

        primary = settings.primary_instance
        assert primary is not None
        assert primary.url == "https://argocd.example.com"
        assert primary.name == "primary"

    def test_primary_instance_none_when_no_url(self):
        """Test primary instance is None when URL not set."""
        settings = ServerSettings()
        assert settings.primary_instance is None

    def test_all_instances(self):
        """Test all_instances property."""
        additional = ArgocdInstance(
            url="https://argocd-dr.example.com",
            token=SecretStr("dr-token"),
            name="dr",
        )
        settings = ServerSettings(
            argocd_url="https://argocd.example.com",
            argocd_token=SecretStr("test-token"),
            additional_instances=[additional],
        )

        instances = settings.all_instances
        assert len(instances) == 2
        assert instances[0].name == "primary"
        assert instances[1].name == "dr"

    def test_get_instance_by_name(self):
        """Test getting instance by name."""
        settings = ServerSettings(
            argocd_url="https://argocd.example.com",
            argocd_token=SecretStr("test-token"),
        )

        instance = settings.get_instance("primary")
        assert instance is not None
        assert instance.name == "primary"

    def test_get_instance_not_found(self):
        """Test getting non-existent instance."""
        settings = ServerSettings()
        instance = settings.get_instance("nonexistent")
        assert instance is None

    def test_default_log_level(self):
        """Test default log level."""
        settings = ServerSettings()
        assert settings.log_level == "INFO"

    def test_default_server_name(self):
        """Test default server name."""
        settings = ServerSettings()
        assert settings.server_name == "argocd-mcp"
