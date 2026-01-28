# ABOUTME: Pytest fixtures and configuration for ArgoCD MCP Server tests
# ABOUTME: Provides shared fixtures for unit and integration tests

import os
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr

from argocd_mcp.config import ArgocdInstance, SecuritySettings, ServerSettings
from argocd_mcp.utils.client import Application, ArgocdClient
from argocd_mcp.utils.safety import SafetyGuard


@pytest.fixture
def mock_argocd_instance() -> ArgocdInstance:
    """Create a mock ArgoCD instance configuration."""
    return ArgocdInstance(
        url="https://argocd.example.com",
        token=SecretStr("test-token"),
        name="test",
        insecure=True,
    )


@pytest.fixture
def mock_security_settings() -> SecuritySettings:
    """Create security settings for testing."""
    return SecuritySettings(
        read_only=False,
        disable_destructive=False,
        single_cluster=False,
        audit_log=None,
        mask_secrets=True,
        rate_limit_calls=100,
        rate_limit_window=60,
    )


@pytest.fixture
def read_only_security_settings() -> SecuritySettings:
    """Create read-only security settings for testing."""
    return SecuritySettings(
        read_only=True,
        disable_destructive=True,
        single_cluster=False,
        audit_log=None,
        mask_secrets=True,
        rate_limit_calls=100,
        rate_limit_window=60,
    )


@pytest.fixture
def mock_server_settings(
    mock_argocd_instance: ArgocdInstance,
    mock_security_settings: SecuritySettings,
) -> ServerSettings:
    """Create mock server settings."""
    settings = ServerSettings(
        argocd_url=mock_argocd_instance.url,
        argocd_token=mock_argocd_instance.token,
        argocd_insecure=mock_argocd_instance.insecure,
        security=mock_security_settings,
    )
    return settings


@pytest.fixture
def safety_guard(mock_security_settings: SecuritySettings) -> SafetyGuard:
    """Create a safety guard for testing."""
    return SafetyGuard(mock_security_settings)


@pytest.fixture
def read_only_safety_guard(read_only_security_settings: SecuritySettings) -> SafetyGuard:
    """Create a read-only safety guard for testing."""
    return SafetyGuard(read_only_security_settings)


@pytest.fixture
def sample_application() -> Application:
    """Create a sample application for testing."""
    return Application(
        name="test-app",
        namespace="argocd",
        project="default",
        repo_url="https://github.com/example/repo.git",
        path="manifests",
        target_revision="HEAD",
        destination_server="https://kubernetes.default.svc",
        destination_namespace="default",
        sync_status="Synced",
        health_status="Healthy",
        operation_state=None,
        conditions=None,
        resources=None,
    )


@pytest.fixture
def degraded_application() -> Application:
    """Create a degraded application for testing."""
    return Application(
        name="failing-app",
        namespace="argocd",
        project="default",
        repo_url="https://github.com/example/repo.git",
        path="manifests",
        target_revision="HEAD",
        destination_server="https://kubernetes.default.svc",
        destination_namespace="default",
        sync_status="OutOfSync",
        health_status="Degraded",
        operation_state={
            "phase": "Failed",
            "message": "Sync failed: container image not found",
        },
        conditions=[
            {"type": "SyncError", "message": "Failed to sync"},
        ],
        resources=None,
    )


@pytest.fixture
def mock_argocd_client(
    mock_argocd_instance: ArgocdInstance,
    sample_application: Application,
) -> AsyncMock:
    """Create a mock ArgoCD client."""
    client = AsyncMock(spec=ArgocdClient)
    client._instance = mock_argocd_instance

    # Configure default responses
    client.list_applications.return_value = [sample_application]
    client.get_application.return_value = sample_application
    client.get_application_diff.return_value = {"items": []}
    client.get_application_history.return_value = []
    client.get_application_events.return_value = []
    client.get_resource_tree.return_value = {"nodes": []}
    client.list_clusters.return_value = [
        {"name": "in-cluster", "server": "https://kubernetes.default.svc", "connectionState": {"status": "Successful"}}
    ]
    client.list_projects.return_value = [
        {"metadata": {"name": "default"}, "spec": {"description": "Default project"}}
    ]

    return client


@pytest.fixture
def mock_context() -> MagicMock:
    """Create a mock MCP context."""
    ctx = MagicMock()
    ctx.request_id = "test-request-123"
    ctx.report_progress = AsyncMock()
    return ctx


# Integration test fixtures


@pytest.fixture
def argocd_url() -> str | None:
    """Get ArgoCD URL from environment."""
    return os.environ.get("ARGOCD_URL")


@pytest.fixture
def argocd_token() -> str | None:
    """Get ArgoCD token from environment."""
    return os.environ.get("ARGOCD_TOKEN")


@pytest.fixture
def argocd_insecure() -> bool:
    """Get ArgoCD insecure setting from environment."""
    return os.environ.get("ARGOCD_INSECURE", "false").lower() == "true"


@pytest.fixture
async def live_argocd_client(
    argocd_url: str | None,
    argocd_token: str | None,
    argocd_insecure: bool,
) -> AsyncIterator[ArgocdClient | None]:
    """Create a live ArgoCD client for integration tests."""
    if not argocd_url or not argocd_token:
        yield None
        return

    instance = ArgocdInstance(
        url=argocd_url,
        token=SecretStr(argocd_token),
        name="integration-test",
        insecure=argocd_insecure,
    )
    client = ArgocdClient(instance)

    async with client:
        yield client
