# ABOUTME: Unit tests for Tier-3 destructive tool handlers
# ABOUTME: Covers delete and sync-with-prune, including the two-parameter confirmation

"""Unit tests for the Tier-3 destructive handlers in argocd_mcp.tools.destructive."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from argocd_mcp.config import SecuritySettings
from argocd_mcp.utils.client import Application, ArgocdError
from argocd_mcp.utils.logging import AuditLogger
from argocd_mcp.utils.safety import SafetyGuard
from tests.unit.conftest import _make_server_context


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

        original_context = server._context

        server._context = _make_server_context(
            safety_guard=guard,
            audit_logger=MagicMock(spec=AuditLogger),
            clients={"primary": mock_argocd_client},
        )

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
            server._context = original_context

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
class TestSyncApplicationWithPruneTool:
    """Tests for sync_application_with_prune MCP tool (Tier 3)."""

    @pytest.mark.asyncio
    async def test_dry_run_no_confirmation_needed(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Dry-run preview must execute without confirm/confirm_name."""
        from argocd_mcp.server import (
            SyncApplicationWithPruneParams,
            sync_application_with_prune,
        )

        mocks = server_with_mocks
        mocks["client"].sync_application.return_value = {"status": "ok"}

        params = SyncApplicationWithPruneParams(name="test-app", dry_run=True, instance="primary")
        result = await sync_application_with_prune(params, mocks["ctx"])

        assert "Dry-run sync-with-prune complete" in result
        assert "confirm=true" in result
        mocks["client"].sync_application.assert_called_once_with(
            name="test-app",
            dry_run=True,
            prune=True,
            force=False,
            revision=None,
        )

    @pytest.mark.asyncio
    async def test_live_without_confirm_is_blocked(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Live prune without confirm=true must return ConfirmationRequired."""
        from argocd_mcp.server import (
            SyncApplicationWithPruneParams,
            sync_application_with_prune,
        )

        mocks = server_with_mocks

        params = SyncApplicationWithPruneParams(name="test-app", dry_run=False, instance="primary")
        result = await sync_application_with_prune(params, mocks["ctx"])

        assert "CONFIRMATION REQUIRED" in result
        mocks["client"].sync_application.assert_not_called()
        mocks["logger"].log_blocked.assert_called()

    @pytest.mark.asyncio
    async def test_live_with_name_mismatch_is_blocked(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """confirm_name must match target exactly; mismatch returns helpful error."""
        from argocd_mcp.server import (
            SyncApplicationWithPruneParams,
            sync_application_with_prune,
        )

        mocks = server_with_mocks

        params = SyncApplicationWithPruneParams(
            name="test-app",
            dry_run=False,
            confirm=True,
            confirm_name="Test-App",  # wrong case
            instance="primary",
        )
        result = await sync_application_with_prune(params, mocks["ctx"])

        assert "CONFIRMATION REQUIRED" in result
        assert "case and whitespace are significant" in result
        mocks["client"].sync_application.assert_not_called()

    @pytest.mark.asyncio
    async def test_live_with_confirmation_executes(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """Full confirmation path executes the sync with prune=true."""
        from argocd_mcp.server import (
            SyncApplicationWithPruneParams,
            sync_application_with_prune,
        )

        mocks = server_with_mocks
        mocks["client"].sync_application.return_value = {"status": "ok"}

        params = SyncApplicationWithPruneParams(
            name="test-app",
            dry_run=False,
            confirm=True,
            confirm_name="test-app",
            revision="main",
            instance="primary",
        )
        result = await sync_application_with_prune(params, mocks["ctx"])

        assert "Sync-with-prune initiated" in result
        assert "Revision: main" in result
        assert "Prune: true" in result
        mocks["client"].sync_application.assert_called_once_with(
            name="test-app",
            dry_run=False,
            prune=True,
            force=False,
            revision="main",
        )

    @pytest.mark.asyncio
    async def test_live_blocked_read_only(
        self,
        server_read_only: dict[str, Any],
    ):
        """Read-only mode blocks the destructive Tier-3 operation."""
        from argocd_mcp.server import (
            SyncApplicationWithPruneParams,
            sync_application_with_prune,
        )

        mocks = server_read_only

        params = SyncApplicationWithPruneParams(
            name="test-app",
            dry_run=False,
            confirm=True,
            confirm_name="test-app",
            instance="primary",
        )
        result = await sync_application_with_prune(params, mocks["ctx"])

        assert "OPERATION BLOCKED" in result
        assert "read-only" in result

    @pytest.mark.asyncio
    async def test_live_blocked_destructive_disabled(
        self,
        mock_argocd_client: AsyncMock,
        mock_ctx: MagicMock,
    ):
        """MCP_DISABLE_DESTRUCTIVE=true blocks live sync-with-prune."""
        from argocd_mcp import server
        from argocd_mcp.server import (
            SyncApplicationWithPruneParams,
            sync_application_with_prune,
        )

        settings = SecuritySettings(read_only=False, disable_destructive=True)
        guard = SafetyGuard(settings)

        original_context = server._context

        server._context = _make_server_context(
            safety_guard=guard,
            audit_logger=MagicMock(spec=AuditLogger),
            clients={"primary": mock_argocd_client},
        )

        try:
            params = SyncApplicationWithPruneParams(
                name="test-app",
                dry_run=False,
                confirm=True,
                confirm_name="test-app",
                instance="primary",
            )
            result = await sync_application_with_prune(params, mock_ctx)

            assert "OPERATION BLOCKED" in result
            assert "Destructive operations" in result
            mock_argocd_client.sync_application.assert_not_called()
        finally:
            server._context = original_context

    @pytest.mark.asyncio
    async def test_handles_api_error(
        self,
        server_with_mocks: dict[str, Any],
    ):
        """ArgocdError on the API call surfaces as the tool return value."""
        from argocd_mcp.server import (
            SyncApplicationWithPruneParams,
            sync_application_with_prune,
        )

        mocks = server_with_mocks
        error = ArgocdError(code=500, message="Sync failed")
        mocks["client"].sync_application.side_effect = error

        params = SyncApplicationWithPruneParams(
            name="test-app",
            dry_run=False,
            confirm=True,
            confirm_name="test-app",
            instance="primary",
        )
        result = await sync_application_with_prune(params, mocks["ctx"])

        assert "ArgoCD API error" in result
        assert "500" in result
