# ABOUTME: Integration tests for Tier-3 destructive tool handlers
# ABOUTME: Exercises delete_application and sync_application_with_prune end-to-end

"""Integration tests for the Tier-3 destructive tool handlers.

Covers the tool layer (handler → safety guard → API), not the client layer
(that's test_argocd_client.py). Runs against the same Kind+ArgoCD setup.

Tests are skipped when ArgoCD is not available on the local cluster, so they
silently no-op in environments without the integration harness.
"""

from __future__ import annotations

import subprocess
import time
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from argocd_mcp.config import SecuritySettings, ServerSettings
from argocd_mcp.tools.params import (
    DeleteApplicationParams,
    SyncApplicationWithPruneParams,
)
from argocd_mcp.utils.client import ArgocdClient
from argocd_mcp.utils.logging import AuditLogger
from argocd_mcp.utils.safety import SafetyGuard

# Helpers come from conftest; fixtures (argocd_instance) resolve via pytest auto-discovery.
from tests.integration.conftest import _is_argocd_available, _kubectl_context

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from argocd_mcp.config import ArgocdInstance


pytestmark = pytest.mark.skipif(
    not _is_argocd_available(),
    reason="ArgoCD not available on Kind cluster",
)


PRUNE_APP_NAME = "integration-test-prune"
DELETE_APP_NAME = "integration-test-delete"
TEST_NAMESPACE = "argocd"


def _app_manifest(name: str) -> str:
    """Return an ArgoCD Application manifest pointing at the guestbook example."""
    return f"""
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {name}
  namespace: {TEST_NAMESPACE}
spec:
  project: default
  source:
    repoURL: https://github.com/argoproj/argocd-example-apps.git
    targetRevision: HEAD
    path: guestbook
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated: null
"""


def _kubectl_apply(manifest: str) -> bool:
    """Apply a manifest via kubectl. Returns True on success."""
    ctx = _kubectl_context()
    result = subprocess.run(
        ["kubectl", "--context", ctx, "apply", "-f", "-"],
        input=manifest,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.returncode == 0


def _kubectl_app_exists(name: str) -> bool:
    """Return True if the named ArgoCD Application is present in the cluster."""
    ctx = _kubectl_context()
    result = subprocess.run(
        [
            "kubectl",
            "--context",
            ctx,
            "-n",
            TEST_NAMESPACE,
            "get",
            "application",
            name,
            "--ignore-not-found",
            "-o",
            "name",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() != ""


def _kubectl_delete_app_if_present(name: str) -> None:
    """Best-effort cleanup so a failed test does not leave Apps behind."""
    ctx = _kubectl_context()
    subprocess.run(
        [
            "kubectl",
            "--context",
            ctx,
            "-n",
            TEST_NAMESPACE,
            "delete",
            "application",
            name,
            "--ignore-not-found",
            "--wait=false",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _make_destructive_context(
    client: ArgocdClient,
    *,
    settings: ServerSettings,
    disable_destructive: bool = False,
) -> object:
    """Build a ServerContext wired for destructive ops."""
    from argocd_mcp.server import ServerContext

    security = SecuritySettings(
        read_only=False,
        disable_destructive=disable_destructive,
    )
    return ServerContext(
        settings=settings,
        safety_guard=SafetyGuard(security),
        audit_logger=MagicMock(spec=AuditLogger),
        clients={"primary": client},
    )


@pytest.fixture
def mock_ctx() -> MagicMock:
    """An MCP request context mock with async report_progress."""
    ctx = MagicMock()
    ctx.request_id = "integration-test"
    ctx.report_progress = AsyncMock()
    return ctx


@pytest.fixture
async def open_argocd_client(
    argocd_instance: ArgocdInstance | None,
) -> AsyncIterator[ArgocdClient | None]:
    """Yield an opened ArgocdClient bound to the test ArgoCD."""
    if argocd_instance is None:
        yield None
        return
    client = ArgocdClient(instance=argocd_instance, mask_secrets=True)
    async with client:
        yield client


@pytest.fixture
def deletable_app(argocd_instance: ArgocdInstance | None) -> Iterator[str | None]:
    """Provision an ArgoCD Application meant to be deleted by the test."""
    if argocd_instance is None:
        yield None
        return
    if not _kubectl_apply(_app_manifest(DELETE_APP_NAME)):
        yield None
        return
    time.sleep(3)
    try:
        yield DELETE_APP_NAME
    finally:
        _kubectl_delete_app_if_present(DELETE_APP_NAME)


@pytest.fixture
def prunable_app(argocd_instance: ArgocdInstance | None) -> Iterator[str | None]:
    """Provision an ArgoCD Application meant for sync-with-prune testing."""
    if argocd_instance is None:
        yield None
        return
    if not _kubectl_apply(_app_manifest(PRUNE_APP_NAME)):
        yield None
        return
    time.sleep(3)
    try:
        yield PRUNE_APP_NAME
    finally:
        _kubectl_delete_app_if_present(PRUNE_APP_NAME)


@pytest.mark.integration
class TestDeleteApplicationIntegration:
    """End-to-end coverage for delete_application against a live ArgoCD."""

    async def test_blocks_without_confirmation(
        self,
        open_argocd_client: ArgocdClient | None,
        deletable_app: str | None,
        argocd_instance: ArgocdInstance | None,
        mock_ctx: MagicMock,
    ) -> None:
        if open_argocd_client is None or deletable_app is None or argocd_instance is None:
            pytest.skip("ArgoCD integration harness not available")

        from argocd_mcp import server
        from argocd_mcp.tools.destructive import delete_application

        original = server._context
        server._context = _make_destructive_context(
            open_argocd_client,
            settings=ServerSettings(additional_instances=[argocd_instance]),
        )
        try:
            params = DeleteApplicationParams(
                name=deletable_app, confirm=False, instance="primary"
            )
            result = await delete_application(params, mock_ctx)
            assert "CONFIRMATION REQUIRED" in result
            # Application must still exist — handler should not have called the API.
            assert _kubectl_app_exists(deletable_app), (
                "delete_application performed deletion despite missing confirmation"
            )
        finally:
            server._context = original

    async def test_blocked_when_destructive_disabled(
        self,
        open_argocd_client: ArgocdClient | None,
        deletable_app: str | None,
        argocd_instance: ArgocdInstance | None,
        mock_ctx: MagicMock,
    ) -> None:
        if open_argocd_client is None or deletable_app is None or argocd_instance is None:
            pytest.skip("ArgoCD integration harness not available")

        from argocd_mcp import server
        from argocd_mcp.tools.destructive import delete_application

        original = server._context
        server._context = _make_destructive_context(
            open_argocd_client,
            settings=ServerSettings(additional_instances=[argocd_instance]),
            disable_destructive=True,
        )
        try:
            params = DeleteApplicationParams(
                name=deletable_app,
                confirm=True,
                confirm_name=deletable_app,
                instance="primary",
            )
            result = await delete_application(params, mock_ctx)
            assert "OPERATION BLOCKED" in result
            assert _kubectl_app_exists(deletable_app), (
                "delete_application succeeded despite MCP_DISABLE_DESTRUCTIVE=true"
            )
        finally:
            server._context = original

    async def test_deletes_with_full_confirmation(
        self,
        open_argocd_client: ArgocdClient | None,
        deletable_app: str | None,
        argocd_instance: ArgocdInstance | None,
        mock_ctx: MagicMock,
    ) -> None:
        if open_argocd_client is None or deletable_app is None or argocd_instance is None:
            pytest.skip("ArgoCD integration harness not available")

        from argocd_mcp import server
        from argocd_mcp.tools.destructive import delete_application

        original = server._context
        server._context = _make_destructive_context(
            open_argocd_client,
            settings=ServerSettings(additional_instances=[argocd_instance]),
        )
        try:
            params = DeleteApplicationParams(
                name=deletable_app,
                cascade=True,
                confirm=True,
                confirm_name=deletable_app,
                instance="primary",
            )
            result = await delete_application(params, mock_ctx)
            assert "deleted successfully" in result
            # Wait briefly for ArgoCD to process the delete.
            for _ in range(10):
                if not _kubectl_app_exists(deletable_app):
                    break
                time.sleep(1)
            assert not _kubectl_app_exists(deletable_app), (
                "Application still present after confirmed delete"
            )
        finally:
            server._context = original


@pytest.mark.integration
class TestSyncWithPruneIntegration:
    """End-to-end coverage for sync_application_with_prune against a live ArgoCD."""

    async def test_dry_run_no_confirmation_required(
        self,
        open_argocd_client: ArgocdClient | None,
        prunable_app: str | None,
        argocd_instance: ArgocdInstance | None,
        mock_ctx: MagicMock,
    ) -> None:
        if open_argocd_client is None or prunable_app is None or argocd_instance is None:
            pytest.skip("ArgoCD integration harness not available")

        from argocd_mcp import server
        from argocd_mcp.tools.destructive import sync_application_with_prune

        original = server._context
        server._context = _make_destructive_context(
            open_argocd_client,
            settings=ServerSettings(additional_instances=[argocd_instance]),
        )
        try:
            params = SyncApplicationWithPruneParams(
                name=prunable_app, dry_run=True, instance="primary"
            )
            result = await sync_application_with_prune(params, mock_ctx)
            assert "Dry-run sync-with-prune complete" in result
            # Dry run must not delete the application.
            assert _kubectl_app_exists(prunable_app)
        finally:
            server._context = original

    async def test_live_blocks_without_confirmation(
        self,
        open_argocd_client: ArgocdClient | None,
        prunable_app: str | None,
        argocd_instance: ArgocdInstance | None,
        mock_ctx: MagicMock,
    ) -> None:
        if open_argocd_client is None or prunable_app is None or argocd_instance is None:
            pytest.skip("ArgoCD integration harness not available")

        from argocd_mcp import server
        from argocd_mcp.tools.destructive import sync_application_with_prune

        original = server._context
        server._context = _make_destructive_context(
            open_argocd_client,
            settings=ServerSettings(additional_instances=[argocd_instance]),
        )
        try:
            params = SyncApplicationWithPruneParams(
                name=prunable_app,
                dry_run=False,
                # confirm omitted on purpose
                instance="primary",
            )
            result = await sync_application_with_prune(params, mock_ctx)
            assert "CONFIRMATION REQUIRED" in result
            assert _kubectl_app_exists(prunable_app)
        finally:
            server._context = original

    async def test_live_with_confirmation_initiates_sync(
        self,
        open_argocd_client: ArgocdClient | None,
        prunable_app: str | None,
        argocd_instance: ArgocdInstance | None,
        mock_ctx: MagicMock,
    ) -> None:
        if open_argocd_client is None or prunable_app is None or argocd_instance is None:
            pytest.skip("ArgoCD integration harness not available")

        from argocd_mcp import server
        from argocd_mcp.tools.destructive import sync_application_with_prune

        original = server._context
        server._context = _make_destructive_context(
            open_argocd_client,
            settings=ServerSettings(additional_instances=[argocd_instance]),
        )
        try:
            params = SyncApplicationWithPruneParams(
                name=prunable_app,
                dry_run=False,
                confirm=True,
                confirm_name=prunable_app,
                instance="primary",
            )
            result = await sync_application_with_prune(params, mock_ctx)
            assert "Sync-with-prune initiated" in result
            # The application is still managed by ArgoCD after a sync.
            assert _kubectl_app_exists(prunable_app)
        finally:
            server._context = original
