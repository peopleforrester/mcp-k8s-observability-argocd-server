# ABOUTME: Unit tests for ArgoCD MCP Server main module
# ABOUTME: Tests MCP tools, safety guard integration, and error handling

"""Unit tests for server.py covering all MCP tools and safety integration."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Create proper mocks for MCP module before importing server
# The tool decorator needs to return the function unchanged for testing


class MockFastMCP:
    """Mock FastMCP class that passes through decorated functions."""

    def __init__(self, *args, **kwargs):
        self.tools = {}
        self.resources = {}

    def tool(self):
        """Decorator that passes through the function."""

        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator

    def resource(self, name):
        """Decorator for resources."""

        def decorator(func):
            self.resources[name] = func
            return func

        return decorator

    def run(self):
        """Mock run method."""
        pass


class MockContext:
    """Mock MCP Context class."""

    def __init__(self, request_id: str = "test-request-123") -> None:
        self.request_id = request_id

    def __class_getitem__(cls, params: Any) -> type:
        """Support generic subscripting like Context[Any, Any]."""
        return cls

    async def report_progress(self, *args: Any, **kwargs: Any) -> None:
        pass


# Setup mocks before importing server
mock_fastmcp_module = MagicMock()
mock_fastmcp_module.FastMCP = MockFastMCP
mock_fastmcp_module.Context = MockContext

sys.modules["mcp"] = MagicMock()
sys.modules["mcp.server"] = MagicMock()
sys.modules["mcp.server.fastmcp"] = mock_fastmcp_module

from argocd_mcp.config import SecuritySettings, ServerSettings
from argocd_mcp.utils.client import Application, ArgocdError
from argocd_mcp.utils.logging import AuditLogger
from argocd_mcp.utils.safety import SafetyGuard


@pytest.mark.unit
class TestGetClientAndHelpers:
    """Tests for helper functions."""

    def test_get_client_returns_client(self):
        """Test get_client returns correct client instance."""
        from argocd_mcp import server

        mock_client = MagicMock()
        original = server._clients
        server._clients = {"primary": mock_client, "secondary": MagicMock()}

        try:
            result = server.get_client("primary")
            assert result is mock_client
        finally:
            server._clients = original

    def test_get_client_unknown_instance_raises(self):
        """Test get_client raises for unknown instance."""
        from argocd_mcp import server

        original = server._clients
        server._clients = {"primary": MagicMock()}

        try:
            with pytest.raises(ValueError, match="Unknown instance 'unknown'"):
                server.get_client("unknown")
        finally:
            server._clients = original

    def test_get_settings_returns_settings(self, mock_server_settings: ServerSettings):
        """Test get_settings returns server settings."""
        from argocd_mcp import server

        original = server._settings
        server._settings = mock_server_settings

        try:
            result = server.get_settings()
            assert result is mock_server_settings
        finally:
            server._settings = original

    def test_get_settings_raises_if_not_initialized(self):
        """Test get_settings raises if server not initialized."""
        from argocd_mcp import server

        original = server._settings
        server._settings = None

        try:
            with pytest.raises(RuntimeError, match="Server not initialized"):
                server.get_settings()
        finally:
            server._settings = original

    def test_get_safety_guard_returns_guard(self, safety_guard: SafetyGuard):
        """Test get_safety_guard returns safety guard."""
        from argocd_mcp import server

        original = server._safety_guard
        server._safety_guard = safety_guard

        try:
            result = server.get_safety_guard()
            assert result is safety_guard
        finally:
            server._safety_guard = original

    def test_get_safety_guard_raises_if_not_initialized(self):
        """Test get_safety_guard raises if server not initialized."""
        from argocd_mcp import server

        original = server._safety_guard
        server._safety_guard = None

        try:
            with pytest.raises(RuntimeError, match="Server not initialized"):
                server.get_safety_guard()
        finally:
            server._safety_guard = original

    def test_get_audit_logger_returns_logger(self):
        """Test get_audit_logger returns audit logger."""
        from argocd_mcp import server

        mock_logger = MagicMock()
        original = server._audit_logger
        server._audit_logger = mock_logger

        try:
            result = server.get_audit_logger()
            assert result is mock_logger
        finally:
            server._audit_logger = original

    def test_get_audit_logger_raises_if_not_initialized(self):
        """Test get_audit_logger raises if server not initialized."""
        from argocd_mcp import server

        original = server._audit_logger
        server._audit_logger = None

        try:
            with pytest.raises(RuntimeError, match="Server not initialized"):
                server.get_audit_logger()
        finally:
            server._audit_logger = original


@pytest.fixture
def mock_ctx():
    """Create a mock MCP context with async report_progress."""
    ctx = MagicMock()
    ctx.request_id = "test-request-123"
    ctx.report_progress = AsyncMock()
    return ctx


@pytest.fixture
def server_with_mocks(
    mock_argocd_client: AsyncMock,
    safety_guard: SafetyGuard,
    mock_ctx: MagicMock,
):
    """Setup server module with mocks for testing tools."""
    from argocd_mcp import server

    # Store original values
    original_clients = server._clients
    original_guard = server._safety_guard
    original_logger = server._audit_logger

    # Setup mocks
    server._clients = {"primary": mock_argocd_client}
    server._safety_guard = safety_guard
    server._audit_logger = MagicMock(spec=AuditLogger)

    yield {
        "client": mock_argocd_client,
        "guard": safety_guard,
        "logger": server._audit_logger,
        "ctx": mock_ctx,
    }

    # Restore originals
    server._clients = original_clients
    server._safety_guard = original_guard
    server._audit_logger = original_logger


@pytest.fixture
def server_read_only(
    mock_argocd_client: AsyncMock,
    read_only_safety_guard: SafetyGuard,
    mock_ctx: MagicMock,
):
    """Setup server module with read-only safety guard."""
    from argocd_mcp import server

    original_clients = server._clients
    original_guard = server._safety_guard
    original_logger = server._audit_logger

    server._clients = {"primary": mock_argocd_client}
    server._safety_guard = read_only_safety_guard
    server._audit_logger = MagicMock(spec=AuditLogger)

    yield {
        "client": mock_argocd_client,
        "guard": read_only_safety_guard,
        "logger": server._audit_logger,
        "ctx": mock_ctx,
    }

    server._clients = original_clients
    server._safety_guard = original_guard
    server._audit_logger = original_logger


@pytest.mark.unit
class TestListApplicationsTool:
    """Tests for list_applications MCP tool."""

    @pytest.mark.asyncio
    async def test_list_applications_returns_apps(
        self,
        server_with_mocks: dict[str, Any],
        sample_application: Application,
    ):
        """Test list_applications returns formatted list."""
        from argocd_mcp.server import ListApplicationsParams, list_applications

        mocks = server_with_mocks
        mocks["client"].list_applications.return_value = [sample_application]

        params = ListApplicationsParams(instance="primary")
        result = await list_applications(params, mocks["ctx"])

        assert "Found 1 application(s)" in result
        assert "test-app" in result
        assert "Healthy" in result
        assert "Synced" in result
        mocks["logger"].log_read.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_applications_filters_by_health_status(
        self,
        server_with_mocks: dict[str, Any],
        sample_application: Application,
        degraded_application: Application,
    ):
        """Test filtering by health status."""
        from argocd_mcp.server import ListApplicationsParams, list_applications

        mocks = server_with_mocks
        mocks["client"].list_applications.return_value = [
            sample_application,
            degraded_application,
        ]

        params = ListApplicationsParams(health_status="Degraded", instance="primary")
        result = await list_applications(params, mocks["ctx"])

        assert "Found 1 application(s)" in result
        assert "failing-app" in result
        assert "test-app" not in result

    @pytest.mark.asyncio
    async def test_list_applications_filters_by_sync_status(
        self,
        server_with_mocks: dict[str, Any],
        sample_application: Application,
        degraded_application: Application,
    ):
        """Test filtering by sync status."""
        from argocd_mcp.server import ListApplicationsParams, list_applications

        mocks = server_with_mocks
        mocks["client"].list_applications.return_value = [
            sample_application,
            degraded_application,
        ]

        params = ListApplicationsParams(sync_status="OutOfSync", instance="primary")
        result = await list_applications(params, mocks["ctx"])

        assert "Found 1 application(s)" in result
        assert "failing-app" in result

    @pytest.mark.asyncio
    async def test_list_applications_no_matches(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test when no apps match filters."""
        from argocd_mcp.server import ListApplicationsParams, list_applications

        mocks = server_with_mocks
        mocks["client"].list_applications.return_value = []

        params = ListApplicationsParams(project="nonexistent", instance="primary")
        result = await list_applications(params, mocks["ctx"])

        assert "No applications found" in result

    @pytest.mark.asyncio
    async def test_list_applications_handles_argocd_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test error handling for ArgoCD API errors."""
        from argocd_mcp.server import ListApplicationsParams, list_applications

        mocks = server_with_mocks
        error = ArgocdError(code=500, message="Internal server error")
        mocks["client"].list_applications.side_effect = error

        params = ListApplicationsParams(instance="primary")
        result = await list_applications(params, mocks["ctx"])

        assert "ArgoCD API error" in result
        assert "500" in result
        mocks["logger"].log_error.assert_called_once()


@pytest.mark.unit
class TestGetApplicationTool:
    """Tests for get_application MCP tool."""

    @pytest.mark.asyncio
    async def test_get_application_returns_details(
        self,
        server_with_mocks: dict[str, Any],
        sample_application: Application,
    ):
        """Test get_application returns formatted details."""
        from argocd_mcp.server import GetApplicationParams, get_application

        mocks = server_with_mocks
        mocks["client"].get_application.return_value = sample_application

        params = GetApplicationParams(name="test-app", instance="primary")
        result = await get_application(params, mocks["ctx"])

        assert "Application: test-app" in result
        assert "Project: default" in result
        assert "Repository: https://github.com/example/repo.git" in result
        assert "Sync: Synced" in result
        assert "Health: Healthy" in result

    @pytest.mark.asyncio
    async def test_get_application_with_operation_state(
        self,
        server_with_mocks: dict[str, Any],
        degraded_application: Application,
    ):
        """Test get_application includes operation state."""
        from argocd_mcp.server import GetApplicationParams, get_application

        mocks = server_with_mocks
        mocks["client"].get_application.return_value = degraded_application

        params = GetApplicationParams(name="failing-app", instance="primary")
        result = await get_application(params, mocks["ctx"])

        assert "Last Operation:" in result
        assert "Phase: Failed" in result

    @pytest.mark.asyncio
    async def test_get_application_with_conditions(
        self,
        server_with_mocks: dict[str, Any],
        degraded_application: Application,
    ):
        """Test get_application includes conditions."""
        from argocd_mcp.server import GetApplicationParams, get_application

        mocks = server_with_mocks
        mocks["client"].get_application.return_value = degraded_application

        params = GetApplicationParams(name="failing-app", instance="primary")
        result = await get_application(params, mocks["ctx"])

        assert "Conditions:" in result
        assert "SyncError" in result

    @pytest.mark.asyncio
    async def test_get_application_handles_argocd_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test error handling for missing application."""
        from argocd_mcp.server import GetApplicationParams, get_application

        mocks = server_with_mocks
        error = ArgocdError(code=404, message="Application not found")
        mocks["client"].get_application.side_effect = error

        params = GetApplicationParams(name="nonexistent", instance="primary")
        result = await get_application(params, mocks["ctx"])

        assert "ArgoCD API error" in result
        assert "404" in result


@pytest.mark.unit
class TestGetApplicationStatusTool:
    """Tests for get_application_status MCP tool."""

    @pytest.mark.asyncio
    async def test_get_application_status_returns_condensed(
        self,
        server_with_mocks: dict[str, Any],
        sample_application: Application,
    ):
        """Test get_application_status returns condensed status."""
        from argocd_mcp.server import GetApplicationStatusParams, get_application_status

        mocks = server_with_mocks
        mocks["client"].get_application.return_value = sample_application

        params = GetApplicationStatusParams(name="test-app", instance="primary")
        result = await get_application_status(params, mocks["ctx"])

        assert "Application: test-app" in result
        assert "Health: Healthy" in result
        assert "Sync: Synced" in result

    @pytest.mark.asyncio
    async def test_get_application_status_unhealthy_app(
        self,
        server_with_mocks: dict[str, Any],
        degraded_application: Application,
    ):
        """Test get_application_status shows unhealthy icons."""
        from argocd_mcp.server import GetApplicationStatusParams, get_application_status

        mocks = server_with_mocks
        mocks["client"].get_application.return_value = degraded_application

        params = GetApplicationStatusParams(name="failing-app", instance="primary")
        result = await get_application_status(params, mocks["ctx"])

        assert "Health: Degraded" in result
        assert "Sync: OutOfSync" in result

    @pytest.mark.asyncio
    async def test_get_application_status_handles_argocd_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test error handling for get_application_status."""
        from argocd_mcp.server import GetApplicationStatusParams, get_application_status

        mocks = server_with_mocks
        error = ArgocdError(code=404, message="Application not found")
        mocks["client"].get_application.side_effect = error

        params = GetApplicationStatusParams(name="nonexistent", instance="primary")
        result = await get_application_status(params, mocks["ctx"])

        assert "ArgoCD API error" in result
        assert "404" in result


@pytest.mark.unit
class TestGetApplicationDiffTool:
    """Tests for get_application_diff MCP tool."""

    @pytest.mark.asyncio
    async def test_get_application_diff_no_resources(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test diff with no managed resources."""
        from argocd_mcp.server import GetApplicationDiffParams, get_application_diff

        mocks = server_with_mocks
        mocks["client"].get_application_diff.return_value = {"items": []}

        params = GetApplicationDiffParams(name="test-app", instance="primary")
        result = await get_application_diff(params, mocks["ctx"])

        assert "No managed resources found" in result

    @pytest.mark.asyncio
    async def test_get_application_diff_with_changes(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test diff showing resources to create, update, delete."""
        from argocd_mcp.server import GetApplicationDiffParams, get_application_diff

        mocks = server_with_mocks
        mocks["client"].get_application_diff.return_value = {
            "items": [
                {
                    "kind": "Deployment",
                    "name": "new-deploy",
                    "liveState": None,
                    "targetState": "{}",
                },
                {"kind": "ConfigMap", "name": "config", "liveState": "{}", "targetState": "{}v2"},
                {"kind": "Service", "name": "old-svc", "liveState": "{}", "targetState": None},
                {"kind": "Secret", "name": "synced", "liveState": "{}", "targetState": "{}"},
            ]
        }

        params = GetApplicationDiffParams(name="test-app", instance="primary")
        result = await get_application_diff(params, mocks["ctx"])

        assert "Resources to CREATE (1)" in result
        assert "+ Deployment/new-deploy" in result
        assert "Resources to UPDATE (1)" in result
        assert "~ ConfigMap/config" in result
        assert "Resources to DELETE (with prune) (1)" in result
        assert "- Service/old-svc" in result
        assert "Resources in sync: 1" in result
        mocks["ctx"].report_progress.assert_called()

    @pytest.mark.asyncio
    async def test_get_application_diff_fully_synced(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test diff when app is fully synced."""
        from argocd_mcp.server import GetApplicationDiffParams, get_application_diff

        mocks = server_with_mocks
        mocks["client"].get_application_diff.return_value = {
            "items": [
                {"kind": "Deployment", "name": "app", "liveState": "{}", "targetState": "{}"},
            ]
        }

        params = GetApplicationDiffParams(name="test-app", instance="primary")
        result = await get_application_diff(params, mocks["ctx"])

        assert "Application is fully synced" in result

    @pytest.mark.asyncio
    async def test_get_application_diff_handles_argocd_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test error handling for get_application_diff."""
        from argocd_mcp.server import GetApplicationDiffParams, get_application_diff

        mocks = server_with_mocks
        error = ArgocdError(code=500, message="Server error")
        mocks["client"].get_application_diff.side_effect = error

        params = GetApplicationDiffParams(name="test-app", instance="primary")
        result = await get_application_diff(params, mocks["ctx"])

        assert "ArgoCD API error" in result


@pytest.mark.unit
class TestGetApplicationHistoryTool:
    """Tests for get_application_history MCP tool."""

    @pytest.mark.asyncio
    async def test_get_application_history_returns_entries(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test get_application_history returns formatted history."""
        from argocd_mcp.server import GetApplicationHistoryParams, get_application_history

        mocks = server_with_mocks
        mocks["client"].get_application_history.return_value = [
            {
                "revision": "abc123def456",
                "deployedAt": "2024-01-15T10:30:00Z",
                "initiatedBy": {"username": "admin"},
            },
            {
                "revision": "xyz789ghi012",
                "deployedAt": "2024-01-14T09:00:00Z",
                "initiatedBy": {"username": "ci-bot"},
            },
        ]

        params = GetApplicationHistoryParams(name="test-app", limit=10, instance="primary")
        result = await get_application_history(params, mocks["ctx"])

        assert "Deployment history" in result
        assert "abc123de" in result
        assert "admin" in result

    @pytest.mark.asyncio
    async def test_get_application_history_empty(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test history when no deployments exist."""
        from argocd_mcp.server import GetApplicationHistoryParams, get_application_history

        mocks = server_with_mocks
        mocks["client"].get_application_history.return_value = []

        params = GetApplicationHistoryParams(name="test-app", instance="primary")
        result = await get_application_history(params, mocks["ctx"])

        assert "No deployment history found" in result

    @pytest.mark.asyncio
    async def test_get_application_history_handles_argocd_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test error handling for get_application_history."""
        from argocd_mcp.server import GetApplicationHistoryParams, get_application_history

        mocks = server_with_mocks
        error = ArgocdError(code=404, message="Application not found")
        mocks["client"].get_application_history.side_effect = error

        params = GetApplicationHistoryParams(name="nonexistent", instance="primary")
        result = await get_application_history(params, mocks["ctx"])

        assert "ArgoCD API error" in result


@pytest.mark.unit
class TestDiagnoseSyncFailureTool:
    """Tests for diagnose_sync_failure MCP tool."""

    @pytest.mark.asyncio
    async def test_diagnose_healthy_app(
        self,
        server_with_mocks: dict[str, Any],
        sample_application: Application,
    ):
        """Test diagnosis of healthy application."""
        from argocd_mcp.server import DiagnoseSyncFailureParams, diagnose_sync_failure

        mocks = server_with_mocks
        mocks["client"].get_application.return_value = sample_application
        mocks["client"].get_resource_tree.return_value = {"nodes": []}
        mocks["client"].get_application_events.return_value = []

        params = DiagnoseSyncFailureParams(name="test-app", instance="primary")
        result = await diagnose_sync_failure(params, mocks["ctx"])

        assert "No issues detected" in result
        assert "Application appears healthy" in result

    @pytest.mark.asyncio
    async def test_diagnose_out_of_sync_app(
        self,
        server_with_mocks: dict[str, Any],
        degraded_application: Application,
    ):
        """Test diagnosis of out-of-sync application."""
        from argocd_mcp.server import DiagnoseSyncFailureParams, diagnose_sync_failure

        mocks = server_with_mocks
        mocks["client"].get_application.return_value = degraded_application
        mocks["client"].get_resource_tree.return_value = {"nodes": []}
        mocks["client"].get_application_events.return_value = []

        params = DiagnoseSyncFailureParams(name="failing-app", instance="primary")
        result = await diagnose_sync_failure(params, mocks["ctx"])

        assert "issue(s)" in result
        assert "out of sync" in result
        assert "Degraded" in result
        assert "Suggestions:" in result

    @pytest.mark.asyncio
    async def test_diagnose_image_pull_error(
        self,
        server_with_mocks: dict[str, Any],
        degraded_application: Application,
    ):
        """Test diagnosis detects ImagePullBackOff."""
        from argocd_mcp.server import DiagnoseSyncFailureParams, diagnose_sync_failure

        mocks = server_with_mocks
        mocks["client"].get_application.return_value = degraded_application
        mocks["client"].get_resource_tree.return_value = {"nodes": []}
        mocks["client"].get_application_events.return_value = [
            {"reason": "Failed", "message": "Failed to pull image: ImagePullBackOff"},
        ]

        params = DiagnoseSyncFailureParams(name="failing-app", instance="primary")
        result = await diagnose_sync_failure(params, mocks["ctx"])

        assert "Image pull failed" in result
        assert "registry credentials" in result

    @pytest.mark.asyncio
    async def test_diagnose_crash_loop(
        self,
        server_with_mocks: dict[str, Any],
        degraded_application: Application,
    ):
        """Test diagnosis detects CrashLoopBackOff."""
        from argocd_mcp.server import DiagnoseSyncFailureParams, diagnose_sync_failure

        mocks = server_with_mocks
        mocks["client"].get_application.return_value = degraded_application
        mocks["client"].get_resource_tree.return_value = {"nodes": []}
        mocks["client"].get_application_events.return_value = [
            {
                "reason": "BackOff",
                "message": "Back-off restarting failed container: CrashLoopBackOff",
            },
        ]

        params = DiagnoseSyncFailureParams(name="failing-app", instance="primary")
        result = await diagnose_sync_failure(params, mocks["ctx"])

        assert "Container crashing" in result
        assert "pod logs" in result

    @pytest.mark.asyncio
    async def test_diagnose_rbac_error(
        self,
        server_with_mocks: dict[str, Any],
        degraded_application: Application,
    ):
        """Test diagnosis detects RBAC issues."""
        from argocd_mcp.server import DiagnoseSyncFailureParams, diagnose_sync_failure

        mocks = server_with_mocks
        mocks["client"].get_application.return_value = degraded_application
        mocks["client"].get_resource_tree.return_value = {"nodes": []}
        mocks["client"].get_application_events.return_value = [
            {"reason": "FailedCreate", "message": "Forbidden: cannot create resource"},
        ]

        params = DiagnoseSyncFailureParams(name="failing-app", instance="primary")
        result = await diagnose_sync_failure(params, mocks["ctx"])

        assert "RBAC permission denied" in result
        assert "ServiceAccount" in result

    @pytest.mark.asyncio
    async def test_diagnose_oom_killed(
        self,
        server_with_mocks: dict[str, Any],
        degraded_application: Application,
    ):
        """Test diagnosis detects OOMKilled."""
        from argocd_mcp.server import DiagnoseSyncFailureParams, diagnose_sync_failure

        mocks = server_with_mocks
        mocks["client"].get_application.return_value = degraded_application
        mocks["client"].get_resource_tree.return_value = {"nodes": []}
        mocks["client"].get_application_events.return_value = [
            {"reason": "OOMKilled", "message": "Container killed: OOMKilled"},
        ]

        params = DiagnoseSyncFailureParams(name="failing-app", instance="primary")
        result = await diagnose_sync_failure(params, mocks["ctx"])

        assert "memory limit" in result
        assert "memory usage" in result

    @pytest.mark.asyncio
    async def test_diagnose_scheduling_failure(
        self,
        server_with_mocks: dict[str, Any],
        degraded_application: Application,
    ):
        """Test diagnosis detects scheduling failures."""
        from argocd_mcp.server import DiagnoseSyncFailureParams, diagnose_sync_failure

        mocks = server_with_mocks
        mocks["client"].get_application.return_value = degraded_application
        mocks["client"].get_resource_tree.return_value = {"nodes": []}
        mocks["client"].get_application_events.return_value = [
            {"reason": "PodUnschedulable", "message": "0/3 nodes available: Insufficient cpu"},
        ]

        params = DiagnoseSyncFailureParams(name="failing-app", instance="primary")
        result = await diagnose_sync_failure(params, mocks["ctx"])

        assert "Scheduling failed" in result
        assert "cluster capacity" in result

    @pytest.mark.asyncio
    async def test_diagnose_unhealthy_resources(
        self,
        server_with_mocks: dict[str, Any],
        degraded_application: Application,
    ):
        """Test diagnosis detects unhealthy resources in tree."""
        from argocd_mcp.server import DiagnoseSyncFailureParams, diagnose_sync_failure

        mocks = server_with_mocks
        mocks["client"].get_application.return_value = degraded_application
        mocks["client"].get_resource_tree.return_value = {
            "nodes": [
                {
                    "kind": "Pod",
                    "name": "app-pod",
                    "health": {"status": "Degraded", "message": "Unhealthy"},
                },
                {"kind": "Deployment", "name": "app", "health": {"status": "Healthy"}},
            ]
        }
        mocks["client"].get_application_events.return_value = []

        params = DiagnoseSyncFailureParams(name="failing-app", instance="primary")
        result = await diagnose_sync_failure(params, mocks["ctx"])

        assert "unhealthy resources" in result
        assert "Pod/app-pod" in result

    @pytest.mark.asyncio
    async def test_diagnose_progressing_app(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test diagnosis of progressing application."""
        from argocd_mcp.server import DiagnoseSyncFailureParams, diagnose_sync_failure

        mocks = server_with_mocks
        progressing_app = Application(
            name="progressing-app",
            namespace="argocd",
            project="default",
            repo_url="https://github.com/example/repo.git",
            path="manifests",
            target_revision="HEAD",
            destination_server="https://kubernetes.default.svc",
            destination_namespace="default",
            sync_status="Synced",
            health_status="Progressing",
            operation_state={"phase": "Running"},
            conditions=None,
            resources=None,
        )
        mocks["client"].get_application.return_value = progressing_app
        mocks["client"].get_resource_tree.return_value = {"nodes": []}
        mocks["client"].get_application_events.return_value = []

        params = DiagnoseSyncFailureParams(name="progressing-app", instance="primary")
        result = await diagnose_sync_failure(params, mocks["ctx"])

        assert "still progressing" in result
        assert "Wait for operations" in result

    @pytest.mark.asyncio
    async def test_diagnose_missing_health_app(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test diagnosis of application with Missing health status."""
        from argocd_mcp.server import DiagnoseSyncFailureParams, diagnose_sync_failure

        mocks = server_with_mocks
        missing_app = Application(
            name="missing-app",
            namespace="argocd",
            project="default",
            repo_url="https://github.com/example/repo.git",
            path="manifests",
            target_revision="HEAD",
            destination_server="https://kubernetes.default.svc",
            destination_namespace="default",
            sync_status="OutOfSync",
            health_status="Missing",
            operation_state=None,
            conditions=None,
            resources=None,
        )
        mocks["client"].get_application.return_value = missing_app
        mocks["client"].get_resource_tree.return_value = {"nodes": []}
        mocks["client"].get_application_events.return_value = []

        params = DiagnoseSyncFailureParams(name="missing-app", instance="primary")
        result = await diagnose_sync_failure(params, mocks["ctx"])

        assert "resources are missing" in result
        assert "Verify destination cluster" in result

    @pytest.mark.asyncio
    async def test_diagnose_sync_error_condition(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test diagnosis detects sync error conditions."""
        from argocd_mcp.server import DiagnoseSyncFailureParams, diagnose_sync_failure

        mocks = server_with_mocks
        app_with_conditions = Application(
            name="condition-app",
            namespace="argocd",
            project="default",
            repo_url="https://github.com/example/repo.git",
            path="manifests",
            target_revision="HEAD",
            destination_server="https://kubernetes.default.svc",
            destination_namespace="default",
            sync_status="OutOfSync",
            health_status="Degraded",
            operation_state=None,
            conditions=[
                {"type": "ComparisonError", "message": "Failed to compare with target"},
                {"type": "InvalidSpecError", "message": "Invalid spec field"},
            ],
            resources=None,
        )
        mocks["client"].get_application.return_value = app_with_conditions
        mocks["client"].get_resource_tree.return_value = {"nodes": []}
        mocks["client"].get_application_events.return_value = []

        params = DiagnoseSyncFailureParams(name="condition-app", instance="primary")
        result = await diagnose_sync_failure(params, mocks["ctx"])

        assert "ComparisonError" in result
        assert "InvalidSpecError" in result

    @pytest.mark.asyncio
    async def test_diagnose_handles_argocd_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test error handling for diagnose_sync_failure."""
        from argocd_mcp.server import DiagnoseSyncFailureParams, diagnose_sync_failure

        mocks = server_with_mocks
        error = ArgocdError(code=404, message="Application not found")
        mocks["client"].get_application.side_effect = error

        params = DiagnoseSyncFailureParams(name="nonexistent", instance="primary")
        result = await diagnose_sync_failure(params, mocks["ctx"])

        assert "ArgoCD API error" in result


@pytest.mark.unit
class TestListClustersTool:
    """Tests for list_clusters MCP tool."""

    @pytest.mark.asyncio
    async def test_list_clusters_returns_clusters(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test list_clusters returns formatted cluster list."""
        from argocd_mcp.server import ListClustersParams, list_clusters

        mocks = server_with_mocks
        mocks["client"].list_clusters.return_value = [
            {
                "name": "in-cluster",
                "server": "https://kubernetes.default.svc",
                "connectionState": {"status": "Successful"},
            },
            {
                "name": "prod",
                "server": "https://prod.example.com",
                "connectionState": {"status": "Successful"},
            },
        ]

        params = ListClustersParams(instance="primary")
        result = await list_clusters(params, mocks["ctx"])

        assert "Found 2 cluster(s)" in result
        assert "in-cluster" in result
        assert "prod" in result

    @pytest.mark.asyncio
    async def test_list_clusters_empty(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test list_clusters with no clusters."""
        from argocd_mcp.server import ListClustersParams, list_clusters

        mocks = server_with_mocks
        mocks["client"].list_clusters.return_value = []

        params = ListClustersParams(instance="primary")
        result = await list_clusters(params, mocks["ctx"])

        assert "No clusters registered" in result

    @pytest.mark.asyncio
    async def test_list_clusters_handles_argocd_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test error handling for list_clusters."""
        from argocd_mcp.server import ListClustersParams, list_clusters

        mocks = server_with_mocks
        error = ArgocdError(code=403, message="Forbidden")
        mocks["client"].list_clusters.side_effect = error

        params = ListClustersParams(instance="primary")
        result = await list_clusters(params, mocks["ctx"])

        assert "ArgoCD API error" in result


@pytest.mark.unit
class TestListProjectsTool:
    """Tests for list_projects MCP tool."""

    @pytest.mark.asyncio
    async def test_list_projects_returns_projects(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test list_projects returns formatted project list."""
        from argocd_mcp.server import ListProjectsParams, list_projects

        mocks = server_with_mocks
        mocks["client"].list_projects.return_value = [
            {"metadata": {"name": "default"}, "spec": {"description": "Default project"}},
            {"metadata": {"name": "production"}, "spec": {"description": "Production apps"}},
        ]

        params = ListProjectsParams(instance="primary")
        result = await list_projects(params, mocks["ctx"])

        assert "Found 2 project(s)" in result
        assert "default" in result
        assert "production" in result

    @pytest.mark.asyncio
    async def test_list_projects_empty(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test list_projects with no projects."""
        from argocd_mcp.server import ListProjectsParams, list_projects

        mocks = server_with_mocks
        mocks["client"].list_projects.return_value = []

        params = ListProjectsParams(instance="primary")
        result = await list_projects(params, mocks["ctx"])

        assert "No projects found" in result

    @pytest.mark.asyncio
    async def test_list_projects_handles_argocd_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test error handling for list_projects."""
        from argocd_mcp.server import ListProjectsParams, list_projects

        mocks = server_with_mocks
        error = ArgocdError(code=500, message="Server error")
        mocks["client"].list_projects.side_effect = error

        params = ListProjectsParams(instance="primary")
        result = await list_projects(params, mocks["ctx"])

        assert "ArgoCD API error" in result


@pytest.mark.unit
class TestSyncApplicationTool:
    """Tests for sync_application MCP tool."""

    @pytest.mark.asyncio
    async def test_sync_application_dry_run(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test sync_application in dry-run mode."""
        from argocd_mcp.server import SyncApplicationParams, sync_application

        mocks = server_with_mocks
        mocks["client"].sync_application.return_value = {"status": "ok"}

        params = SyncApplicationParams(name="test-app", dry_run=True, instance="primary")
        result = await sync_application(params, mocks["ctx"])

        assert "Dry-run sync complete" in result
        assert "To apply:" in result
        mocks["client"].sync_application.assert_called_once_with(
            name="test-app",
            dry_run=True,
            prune=False,
            force=False,
            revision=None,
        )

    @pytest.mark.asyncio
    async def test_sync_application_actual_sync(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test sync_application with actual sync."""
        from argocd_mcp.server import SyncApplicationParams, sync_application

        mocks = server_with_mocks
        mocks["client"].sync_application.return_value = {"status": "ok"}

        params = SyncApplicationParams(
            name="test-app",
            dry_run=False,
            revision="main",
            instance="primary",
        )
        result = await sync_application(params, mocks["ctx"])

        assert "Sync initiated" in result
        assert "Revision: main" in result
        assert "get_application_status" in result

    @pytest.mark.asyncio
    async def test_sync_application_blocked_read_only(
        self,
        server_read_only: dict[str, Any],
    ):
        """Test sync_application blocked in read-only mode."""
        from argocd_mcp.server import SyncApplicationParams, sync_application

        mocks = server_read_only

        params = SyncApplicationParams(name="test-app", dry_run=False, instance="primary")
        result = await sync_application(params, mocks["ctx"])

        assert "OPERATION BLOCKED" in result
        assert "read-only" in result
        mocks["logger"].log_blocked.assert_called()

    @pytest.mark.asyncio
    async def test_sync_application_prune_requires_confirmation(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test sync with prune requires confirmation."""
        from argocd_mcp.server import SyncApplicationParams, sync_application

        mocks = server_with_mocks

        params = SyncApplicationParams(
            name="test-app",
            dry_run=False,
            prune=True,
            instance="primary",
        )
        result = await sync_application(params, mocks["ctx"])

        assert "PRUNE REQUIRES CONFIRMATION" in result
        assert "DELETE resources" in result

    @pytest.mark.asyncio
    async def test_sync_application_handles_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test sync_application error handling."""
        from argocd_mcp.server import SyncApplicationParams, sync_application

        mocks = server_with_mocks
        error = ArgocdError(code=400, message="Invalid revision")
        mocks["client"].sync_application.side_effect = error

        params = SyncApplicationParams(name="test-app", dry_run=True, instance="primary")
        result = await sync_application(params, mocks["ctx"])

        assert "ArgoCD API error" in result
        assert "400" in result


@pytest.mark.unit
class TestRefreshApplicationTool:
    """Tests for refresh_application MCP tool."""

    @pytest.mark.asyncio
    async def test_refresh_application_normal(
        self,
        server_with_mocks: dict[str, Any],
        sample_application: Application,
    ):
        """Test normal refresh."""
        from argocd_mcp.server import RefreshApplicationParams, refresh_application

        mocks = server_with_mocks
        mocks["client"].refresh_application.return_value = sample_application

        params = RefreshApplicationParams(name="test-app", hard=False, instance="primary")
        result = await refresh_application(params, mocks["ctx"])

        assert "Refresh triggered" in result
        assert "normal" in result
        assert "health=Healthy" in result

    @pytest.mark.asyncio
    async def test_refresh_application_hard(
        self,
        server_with_mocks: dict[str, Any],
        sample_application: Application,
    ):
        """Test hard refresh."""
        from argocd_mcp.server import RefreshApplicationParams, refresh_application

        mocks = server_with_mocks
        mocks["client"].refresh_application.return_value = sample_application

        params = RefreshApplicationParams(name="test-app", hard=True, instance="primary")
        result = await refresh_application(params, mocks["ctx"])

        assert "Refresh triggered" in result
        assert "hard" in result
        mocks["client"].refresh_application.assert_called_once_with("test-app", True)

    @pytest.mark.asyncio
    async def test_refresh_application_blocked_read_only(
        self,
        server_read_only: dict[str, Any],
    ):
        """Test refresh blocked in read-only mode."""
        from argocd_mcp.server import RefreshApplicationParams, refresh_application

        mocks = server_read_only

        params = RefreshApplicationParams(name="test-app", instance="primary")
        result = await refresh_application(params, mocks["ctx"])

        assert "OPERATION BLOCKED" in result
        assert "read-only" in result

    @pytest.mark.asyncio
    async def test_refresh_application_handles_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test refresh_application error handling."""
        from argocd_mcp.server import RefreshApplicationParams, refresh_application

        mocks = server_with_mocks
        error = ArgocdError(code=404, message="Application not found")
        mocks["client"].refresh_application.side_effect = error

        params = RefreshApplicationParams(name="nonexistent", instance="primary")
        result = await refresh_application(params, mocks["ctx"])

        assert "ArgoCD API error" in result


@pytest.mark.unit
class TestDeleteApplicationTool:
    """Tests for delete_application MCP tool."""

    @pytest.mark.asyncio
    async def test_delete_application_requires_confirmation(
        self,
        server_with_mocks: dict[str, Any],
        sample_application: Application,
    ):
        """Test delete requires confirmation."""
        from argocd_mcp.server import DeleteApplicationParams, delete_application

        mocks = server_with_mocks
        mocks["client"].get_application.return_value = sample_application

        params = DeleteApplicationParams(
            name="test-app",
            confirm=False,
            instance="primary",
        )
        result = await delete_application(params, mocks["ctx"])

        assert "CONFIRMATION REQUIRED" in result
        assert "test-app" in result
        mocks["logger"].log_blocked.assert_called()

    @pytest.mark.asyncio
    async def test_delete_application_requires_name_match(
        self,
        server_with_mocks: dict[str, Any],
        sample_application: Application,
    ):
        """Test delete requires name confirmation match."""
        from argocd_mcp.server import DeleteApplicationParams, delete_application

        mocks = server_with_mocks
        mocks["client"].get_application.return_value = sample_application

        params = DeleteApplicationParams(
            name="test-app",
            confirm=True,
            confirm_name="wrong-name",
            instance="primary",
        )
        result = await delete_application(params, mocks["ctx"])

        assert "CONFIRMATION REQUIRED" in result

    @pytest.mark.asyncio
    async def test_delete_application_succeeds_with_confirmation(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test delete succeeds with proper confirmation."""
        from argocd_mcp.server import DeleteApplicationParams, delete_application

        mocks = server_with_mocks
        mocks["client"].delete_application.return_value = {"status": "ok"}

        params = DeleteApplicationParams(
            name="test-app",
            cascade=True,
            confirm=True,
            confirm_name="test-app",
            instance="primary",
        )
        result = await delete_application(params, mocks["ctx"])

        assert "deleted successfully" in result
        assert "Cascade: True" in result
        mocks["client"].delete_application.assert_called_once_with("test-app", True)

    @pytest.mark.asyncio
    async def test_delete_application_blocked_read_only(
        self,
        server_read_only: dict[str, Any],
    ):
        """Test delete blocked in read-only mode."""
        from argocd_mcp.server import DeleteApplicationParams, delete_application

        mocks = server_read_only

        params = DeleteApplicationParams(
            name="test-app",
            confirm=True,
            confirm_name="test-app",
            instance="primary",
        )
        result = await delete_application(params, mocks["ctx"])

        assert "OPERATION BLOCKED" in result

    @pytest.mark.asyncio
    async def test_delete_application_blocked_destructive_disabled(
        self,
        mock_argocd_client: AsyncMock,
        mock_ctx: MagicMock,
    ):
        """Test delete blocked when destructive ops disabled."""
        from argocd_mcp import server
        from argocd_mcp.server import DeleteApplicationParams, delete_application

        settings = SecuritySettings(
            read_only=False,
            disable_destructive=True,
        )
        guard = SafetyGuard(settings)

        original_clients = server._clients
        original_guard = server._safety_guard
        original_logger = server._audit_logger

        server._clients = {"primary": mock_argocd_client}
        server._safety_guard = guard
        server._audit_logger = MagicMock(spec=AuditLogger)

        try:
            params = DeleteApplicationParams(
                name="test-app",
                confirm=True,
                confirm_name="test-app",
                instance="primary",
            )
            result = await delete_application(params, mock_ctx)

            assert "OPERATION BLOCKED" in result
            assert "Destructive operations" in result
        finally:
            server._clients = original_clients
            server._safety_guard = original_guard
            server._audit_logger = original_logger

    @pytest.mark.asyncio
    async def test_delete_application_handles_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test delete error handling."""
        from argocd_mcp.server import DeleteApplicationParams, delete_application

        mocks = server_with_mocks
        error = ArgocdError(code=500, message="Internal error")
        mocks["client"].delete_application.side_effect = error

        params = DeleteApplicationParams(
            name="test-app",
            confirm=True,
            confirm_name="test-app",
            instance="primary",
        )
        result = await delete_application(params, mocks["ctx"])

        assert "ArgoCD API error" in result
        assert "500" in result

    @pytest.mark.asyncio
    async def test_delete_application_confirmation_get_app_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test delete handles error when getting app for confirmation details."""
        from argocd_mcp.server import DeleteApplicationParams, delete_application

        mocks = server_with_mocks
        # get_application fails during confirmation flow
        error = ArgocdError(code=404, message="Not found")
        mocks["client"].get_application.side_effect = error

        params = DeleteApplicationParams(
            name="test-app",
            confirm=False,
            instance="primary",
        )
        result = await delete_application(params, mocks["ctx"])

        # Should still show confirmation required even if get_application fails
        assert "CONFIRMATION REQUIRED" in result


@pytest.mark.unit
class TestGetApplicationLogsTool:
    """Tests for get_application_logs MCP tool."""

    @pytest.mark.asyncio
    async def test_get_application_logs_returns_logs(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test get_application_logs returns formatted logs."""
        from argocd_mcp.server import GetApplicationLogsParams, get_application_logs

        mocks = server_with_mocks
        mocks[
            "client"
        ].get_logs.return_value = "2025-01-01 INFO Starting app\n2025-01-01 INFO Ready"

        params = GetApplicationLogsParams(name="test-app", instance="primary")
        result = await get_application_logs(params, mocks["ctx"])

        assert "Logs for 'test-app'" in result
        assert "Starting app" in result
        assert "Ready" in result
        mocks["client"].get_logs.assert_called_once_with(
            name="test-app",
            pod_name=None,
            container=None,
            tail_lines=100,
            since_seconds=None,
        )

    @pytest.mark.asyncio
    async def test_get_application_logs_with_filters(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test get_application_logs passes pod and container filters."""
        from argocd_mcp.server import GetApplicationLogsParams, get_application_logs

        mocks = server_with_mocks
        mocks["client"].get_logs.return_value = "log data"

        params = GetApplicationLogsParams(
            name="test-app",
            pod_name="web-pod-123",
            container="web",
            tail_lines=50,
            since_seconds=3600,
            instance="primary",
        )
        result = await get_application_logs(params, mocks["ctx"])

        assert "pod: web-pod-123" in result
        assert "container: web" in result
        mocks["client"].get_logs.assert_called_once_with(
            name="test-app",
            pod_name="web-pod-123",
            container="web",
            tail_lines=50,
            since_seconds=3600,
        )

    @pytest.mark.asyncio
    async def test_get_application_logs_empty(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test get_application_logs with empty logs."""
        from argocd_mcp.server import GetApplicationLogsParams, get_application_logs

        mocks = server_with_mocks
        mocks["client"].get_logs.return_value = ""

        params = GetApplicationLogsParams(name="test-app", instance="primary")
        result = await get_application_logs(params, mocks["ctx"])

        assert "No logs found" in result

    @pytest.mark.asyncio
    async def test_get_application_logs_handles_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test get_application_logs error handling."""
        from argocd_mcp.server import GetApplicationLogsParams, get_application_logs

        mocks = server_with_mocks
        error = ArgocdError(code=404, message="Application not found")
        mocks["client"].get_logs.side_effect = error

        params = GetApplicationLogsParams(name="nonexistent", instance="primary")
        result = await get_application_logs(params, mocks["ctx"])

        assert "ArgoCD API error" in result


@pytest.mark.unit
class TestRollbackApplicationTool:
    """Tests for rollback_application MCP tool."""

    @pytest.mark.asyncio
    async def test_rollback_application_dry_run(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test rollback with dry_run=True (default)."""
        from argocd_mcp.server import RollbackApplicationParams, rollback_application

        mocks = server_with_mocks
        mocks["client"].rollback_application.return_value = {"status": "ok"}

        params = RollbackApplicationParams(name="test-app", revision_id=3, instance="primary")
        result = await rollback_application(params, mocks["ctx"])

        assert "Dry-run rollback" in result
        assert "revision 3" in result
        assert "dry_run=false" in result
        mocks["client"].rollback_application.assert_called_once_with(
            name="test-app", revision_id=3, dry_run=True
        )

    @pytest.mark.asyncio
    async def test_rollback_application_actual(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test rollback with dry_run=False."""
        from argocd_mcp.server import RollbackApplicationParams, rollback_application

        mocks = server_with_mocks
        mocks["client"].rollback_application.return_value = {"status": "ok"}

        params = RollbackApplicationParams(
            name="test-app", revision_id=5, dry_run=False, instance="primary"
        )
        result = await rollback_application(params, mocks["ctx"])

        assert "Rollback initiated" in result
        assert "revision 5" in result
        assert "get_application_status" in result

    @pytest.mark.asyncio
    async def test_rollback_application_blocked_read_only(
        self,
        server_read_only: dict[str, Any],
    ):
        """Test rollback blocked in read-only mode."""
        from argocd_mcp.server import RollbackApplicationParams, rollback_application

        mocks = server_read_only

        params = RollbackApplicationParams(name="test-app", revision_id=1, instance="primary")
        result = await rollback_application(params, mocks["ctx"])

        assert "OPERATION BLOCKED" in result
        assert "read-only" in result

    @pytest.mark.asyncio
    async def test_rollback_application_handles_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test rollback error handling."""
        from argocd_mcp.server import RollbackApplicationParams, rollback_application

        mocks = server_with_mocks
        error = ArgocdError(code=404, message="Application not found")
        mocks["client"].rollback_application.side_effect = error

        params = RollbackApplicationParams(name="nonexistent", revision_id=1, instance="primary")
        result = await rollback_application(params, mocks["ctx"])

        assert "ArgoCD API error" in result


@pytest.mark.unit
class TestTerminateSyncTool:
    """Tests for terminate_sync MCP tool."""

    @pytest.mark.asyncio
    async def test_terminate_sync_success(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test terminate_sync succeeds."""
        from argocd_mcp.server import TerminateSyncParams, terminate_sync

        mocks = server_with_mocks
        mocks["client"].terminate_sync.return_value = {}

        params = TerminateSyncParams(name="test-app", instance="primary")
        result = await terminate_sync(params, mocks["ctx"])

        assert "terminated" in result
        assert "test-app" in result
        mocks["client"].terminate_sync.assert_called_once_with("test-app")

    @pytest.mark.asyncio
    async def test_terminate_sync_blocked_read_only(
        self,
        server_read_only: dict[str, Any],
    ):
        """Test terminate_sync blocked in read-only mode."""
        from argocd_mcp.server import TerminateSyncParams, terminate_sync

        mocks = server_read_only

        params = TerminateSyncParams(name="test-app", instance="primary")
        result = await terminate_sync(params, mocks["ctx"])

        assert "OPERATION BLOCKED" in result
        assert "read-only" in result

    @pytest.mark.asyncio
    async def test_terminate_sync_handles_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Test terminate_sync error handling."""
        from argocd_mcp.server import TerminateSyncParams, terminate_sync

        mocks = server_with_mocks
        error = ArgocdError(code=404, message="No operation running")
        mocks["client"].terminate_sync.side_effect = error

        params = TerminateSyncParams(name="test-app", instance="primary")
        result = await terminate_sync(params, mocks["ctx"])

        assert "ArgoCD API error" in result


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

        original_clients = server._clients
        original_guard = server._safety_guard
        original_logger = server._audit_logger

        server._clients = {"primary": mock_argocd_client}
        server._safety_guard = guard
        server._audit_logger = MagicMock(spec=AuditLogger)

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
            server._clients = original_clients
            server._safety_guard = original_guard
            server._audit_logger = original_logger

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

        original_clients = server._clients
        original_guard = server._safety_guard
        original_logger = server._audit_logger

        mock_logger = MagicMock(spec=AuditLogger)
        server._clients = {"primary": mock_argocd_client}
        server._safety_guard = guard
        server._audit_logger = mock_logger

        try:
            params = ListApplicationsParams(instance="primary")
            # First call to exhaust rate limit
            await list_applications(params, mock_ctx)
            # Second call should be blocked
            await list_applications(params, mock_ctx)

            mock_logger.log_blocked.assert_called()
        finally:
            server._clients = original_clients
            server._safety_guard = original_guard
            server._audit_logger = original_logger


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

        original = server._settings
        server._settings = mock_server_settings

        try:
            result = await get_instances_resource()

            assert "Configured ArgoCD Instances" in result
            assert "primary" in result or "test" in result
        finally:
            server._settings = original

    @pytest.mark.asyncio
    async def test_get_instances_resource_no_instances(self):
        """Test instances resource when no instances configured."""
        from argocd_mcp import server
        from argocd_mcp.server import get_instances_resource

        original = server._settings
        mock_settings = MagicMock()
        mock_settings.all_instances = []
        server._settings = mock_settings

        try:
            result = await get_instances_resource()
            assert "No ArgoCD instances configured" in result
        finally:
            server._settings = original

    @pytest.mark.asyncio
    async def test_get_security_resource(
        self,
        mock_server_settings: ServerSettings,
    ):
        """Test security resource returns security settings."""
        from argocd_mcp import server
        from argocd_mcp.server import get_security_resource

        original = server._settings
        server._settings = mock_server_settings

        try:
            result = await get_security_resource()

            assert "Security Settings" in result
            assert "Read-only mode" in result
            assert "Destructive operations" in result
            assert "Rate limit" in result
        finally:
            server._settings = original


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
