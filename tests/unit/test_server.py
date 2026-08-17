# ABOUTME: Unit tests for server-level wiring rather than individual tools
# ABOUTME: Context accessors, single-cluster enforcement, resources, lifespan

"""Unit tests for server.py: context accessors, safety integration, resources.

Per-tier tool tests live in test_read.py, test_write.py, and test_destructive.py.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argocd_mcp.config import SecuritySettings, ServerSettings
from argocd_mcp.utils.client import Application
from argocd_mcp.utils.logging import AuditLogger
from argocd_mcp.utils.safety import SafetyGuard
from tests.unit.conftest import _make_server_context


@pytest.mark.unit
class TestGetClientAndHelpers:
    """Tests for the get_* accessors and ServerContext lifecycle."""

    def test_get_client_returns_client(self, reset_server_context):
        from argocd_mcp import server

        mock_client = MagicMock()
        server._context = _make_server_context(
            clients={"primary": mock_client, "secondary": MagicMock()},
        )

        assert server.get_client("primary") is mock_client

    def test_get_client_unknown_instance_raises(self, reset_server_context):
        from argocd_mcp import server

        server._context = _make_server_context(clients={"primary": MagicMock()})

        with pytest.raises(ValueError, match="Unknown instance 'unknown'"):
            server.get_client("unknown")

    def test_get_settings_returns_settings(
        self, reset_server_context, mock_server_settings: ServerSettings
    ):
        from argocd_mcp import server

        server._context = _make_server_context(settings=mock_server_settings)

        assert server.get_settings() is mock_server_settings

    def test_get_settings_raises_if_not_initialized(self, reset_server_context):
        from argocd_mcp import server

        server._context = None

        with pytest.raises(RuntimeError, match="Server not initialized"):
            server.get_settings()

    def test_get_safety_guard_returns_guard(self, reset_server_context, safety_guard: SafetyGuard):
        from argocd_mcp import server

        server._context = _make_server_context(safety_guard=safety_guard)

        assert server.get_safety_guard() is safety_guard

    def test_get_safety_guard_raises_if_not_initialized(self, reset_server_context):
        from argocd_mcp import server

        server._context = None

        with pytest.raises(RuntimeError, match="Server not initialized"):
            server.get_safety_guard()

    def test_get_audit_logger_returns_logger(self, reset_server_context):
        from argocd_mcp import server

        mock_logger = MagicMock()
        server._context = _make_server_context(audit_logger=mock_logger)

        assert server.get_audit_logger() is mock_logger

    def test_get_audit_logger_raises_if_not_initialized(self, reset_server_context):
        from argocd_mcp import server

        server._context = None

        with pytest.raises(RuntimeError, match="Server not initialized"):
            server.get_audit_logger()

    def test_get_context_returns_context(self, reset_server_context):
        """get_context() exposes the ServerContext directly for advanced use."""
        from argocd_mcp import server

        ctx = _make_server_context()
        server._context = ctx

        assert server.get_context() is ctx

    def test_get_context_raises_if_not_initialized(self, reset_server_context):
        from argocd_mcp import server

        server._context = None

        with pytest.raises(RuntimeError, match="Server not initialized"):
            server.get_context()


@pytest.mark.unit
class TestSingleClusterEnforcement:
    """Tier-2/3 handlers must consult check_cluster_operation when single_cluster=true."""

    @pytest.fixture
    def remote_app(self) -> Application:
        """An Application whose destination is a non-in-cluster server."""
        return Application(
            name="remote-app",
            namespace="argocd",
            project="default",
            repo_url="https://github.com/example/repo.git",
            path="manifests",
            target_revision="main",
            destination_server="https://prod-east.k8s.example.com",
            destination_namespace="prod",
            sync_status="Synced",
            health_status="Healthy",
        )

    @pytest.fixture
    def server_single_cluster(
        self,
        mock_argocd_client: AsyncMock,
        remote_app: Application,
        mock_ctx: MagicMock,
    ):
        """Server context with single_cluster=true and a remote-targeted app."""
        from argocd_mcp import server

        original = server._context
        guard = SafetyGuard(
            SecuritySettings(
                read_only=False,
                disable_destructive=False,
                single_cluster=True,
            )
        )
        audit_logger = MagicMock(spec=AuditLogger)
        mock_argocd_client.get_application.return_value = remote_app
        server._context = _make_server_context(
            safety_guard=guard,
            audit_logger=audit_logger,
            clients={"primary": mock_argocd_client},
        )
        yield {
            "client": mock_argocd_client,
            "logger": audit_logger,
            "ctx": mock_ctx,
        }
        server._context = original

    @pytest.mark.asyncio
    async def test_sync_application_blocked_for_remote_cluster(
        self, server_single_cluster: dict[str, Any]
    ):
        from argocd_mcp.server import SyncApplicationParams, sync_application

        mocks = server_single_cluster
        params = SyncApplicationParams(name="remote-app", dry_run=False, instance="primary")
        result = await sync_application(params, mocks["ctx"])

        assert "OPERATION BLOCKED" in result
        assert "single-cluster" in result
        assert "prod-east.k8s.example.com" in result
        mocks["client"].sync_application.assert_not_called()
        mocks["logger"].log_blocked.assert_called()

    @pytest.mark.asyncio
    async def test_delete_application_blocked_for_remote_cluster(
        self, server_single_cluster: dict[str, Any]
    ):
        from argocd_mcp.server import DeleteApplicationParams, delete_application

        mocks = server_single_cluster
        params = DeleteApplicationParams(
            name="remote-app",
            confirm=True,
            confirm_name="remote-app",
            instance="primary",
        )
        result = await delete_application(params, mocks["ctx"])

        assert "OPERATION BLOCKED" in result
        assert "single-cluster" in result
        mocks["client"].delete_application.assert_not_called()


@pytest.mark.unit
class TestSafetyGuardIntegration:
    """Tests for safety guard integration with tools."""

    @pytest.mark.asyncio
    async def test_read_operation_blocked_with_rate_limit(
        self,
        mock_argocd_client: AsyncMock,
        mock_ctx: MagicMock,
    ):
        """Test read operations can be rate limited."""
        from argocd_mcp import server
        from argocd_mcp.server import ListApplicationsParams, list_applications

        settings = SecuritySettings(rate_limit_calls=1, rate_limit_window=60)
        guard = SafetyGuard(settings)

        original_context = server._context

        server._context = _make_server_context(
            safety_guard=guard,
            audit_logger=MagicMock(spec=AuditLogger),
            clients={"primary": mock_argocd_client},
        )

        try:
            params = ListApplicationsParams(instance="primary")

            # First call should succeed
            result1 = await list_applications(params, mock_ctx)
            assert "OPERATION BLOCKED" not in result1

            # Second call should be rate limited
            result2 = await list_applications(params, mock_ctx)
            assert "OPERATION BLOCKED" in result2
            assert "Rate limit" in result2
        finally:
            server._context = original_context

    @pytest.mark.asyncio
    async def test_read_blocked_logs_blocked_operation(
        self,
        mock_argocd_client: AsyncMock,
        mock_ctx: MagicMock,
    ):
        """Test that blocked read operations are logged."""
        from argocd_mcp import server
        from argocd_mcp.server import ListApplicationsParams, list_applications

        settings = SecuritySettings(rate_limit_calls=1, rate_limit_window=60)
        guard = SafetyGuard(settings)

        original_context = server._context
        mock_logger = MagicMock(spec=AuditLogger)
        server._context = _make_server_context(
            safety_guard=guard,
            audit_logger=mock_logger,
            clients={"primary": mock_argocd_client},
        )

        try:
            params = ListApplicationsParams(instance="primary")
            # First call to exhaust rate limit
            await list_applications(params, mock_ctx)
            # Second call should be blocked
            await list_applications(params, mock_ctx)

            mock_logger.log_blocked.assert_called()
        finally:
            server._context = original_context


@pytest.mark.unit
class TestMCPResources:
    """Tests for MCP resources."""

    @pytest.mark.asyncio
    async def test_get_instances_resource(
        self,
        mock_server_settings: ServerSettings,
    ):
        """Test instances resource returns instance info."""
        from argocd_mcp import server
        from argocd_mcp.server import get_instances_resource

        original = server._context
        server._context = _make_server_context(settings=mock_server_settings)

        try:
            result = await get_instances_resource()

            assert "Configured ArgoCD Instances" in result
            assert "primary" in result or "test" in result
        finally:
            server._context = original

    @pytest.mark.asyncio
    async def test_get_instances_resource_no_instances(self):
        """Test instances resource when no instances configured."""
        from argocd_mcp import server
        from argocd_mcp.server import get_instances_resource

        original = server._context
        mock_settings = MagicMock()
        mock_settings.all_instances = []
        server._context = _make_server_context(settings=mock_settings)

        try:
            result = await get_instances_resource()
            assert "No ArgoCD instances configured" in result
        finally:
            server._context = original

    @pytest.mark.asyncio
    async def test_get_security_resource(
        self,
        mock_server_settings: ServerSettings,
    ):
        """Test security resource returns security settings."""
        from argocd_mcp import server
        from argocd_mcp.server import get_security_resource

        original = server._context
        server._context = _make_server_context(settings=mock_server_settings)

        try:
            result = await get_security_resource()

            assert "Security Settings" in result
            assert "Read-only mode" in result
            assert "Destructive operations" in result
            assert "Rate limit" in result
        finally:
            server._context = original


@pytest.mark.unit
class TestLifespanAndMain:
    """Tests for lifespan context manager and main entry point."""

    @pytest.mark.asyncio
    async def test_lifespan_initializes_clients(
        self,
        mock_argocd_instance,
    ):
        """Test lifespan initializes clients for all instances."""
        from argocd_mcp import server
        from argocd_mcp.server import lifespan, mcp

        with patch.object(server, "load_settings") as mock_load:
            mock_settings = MagicMock()
            mock_settings.log_level = "INFO"
            mock_settings.security = SecuritySettings()
            mock_settings.all_instances = [mock_argocd_instance]
            mock_load.return_value = mock_settings

            with patch.object(server, "ArgocdClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value = mock_client

                async with lifespan(mcp) as ctx:
                    assert "settings" in ctx
                    assert "clients" in ctx
                    mock_client.__aenter__.assert_called_once()

                mock_client.__aexit__.assert_called_once()

    def test_main_runs_server(self):
        """Test main entry point runs the server."""
        from argocd_mcp.server import main

        with patch("argocd_mcp.server.mcp") as mock_mcp:
            with patch("argocd_mcp.server.configure_logging"):
                main()
                mock_mcp.run.assert_called_once()

    def test_main_handles_keyboard_interrupt(self):
        """Test main handles keyboard interrupt gracefully."""
        from argocd_mcp.server import main

        with patch("argocd_mcp.server.mcp") as mock_mcp:
            with patch("argocd_mcp.server.configure_logging"):
                mock_mcp.run.side_effect = KeyboardInterrupt()

                with pytest.raises(SystemExit) as exc_info:
                    main()

                assert exc_info.value.code == 0

    def test_main_handles_exception(self):
        """Test main handles exceptions with proper exit code."""
        from argocd_mcp.server import main

        with patch("argocd_mcp.server.mcp") as mock_mcp:
            with patch("argocd_mcp.server.configure_logging"):
                mock_mcp.run.side_effect = Exception("Test error")

                with pytest.raises(SystemExit) as exc_info:
                    main()

                assert exc_info.value.code == 1
