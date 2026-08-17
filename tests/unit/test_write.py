# ABOUTME: Unit tests for Tier-2 write tool handlers
# ABOUTME: Covers sync, refresh, rollback, and terminate, including read-only refusals

"""Unit tests for the Tier-2 write handlers in argocd_mcp.tools.write."""

from __future__ import annotations

from typing import Any

import pytest

from argocd_mcp.utils.client import Application, ArgocdError


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

    def test_sync_application_params_rejects_prune_field(self):
        """prune is no longer a valid parameter on SyncApplicationParams.

        It moved to the dedicated Tier-3 sync_application_with_prune tool.
        """
        from pydantic import ValidationError

        from argocd_mcp.server import SyncApplicationParams

        with pytest.raises(ValidationError):
            SyncApplicationParams.model_validate(
                {"name": "test-app", "dry_run": False, "prune": True}
            )

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
