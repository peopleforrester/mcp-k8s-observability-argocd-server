# ABOUTME: Unit tests for ArgoCD API client
# ABOUTME: Tests client initialization, request handling, and response parsing

import pytest

from argocd_mcp.config import ArgocdInstance
from argocd_mcp.utils.client import Application, ArgocdClient, ArgocdError


@pytest.mark.unit
class TestApplication:
    """Tests for Application dataclass."""

    def test_from_api_response(self):
        """Test creating Application from API response."""
        response = {
            "metadata": {
                "name": "test-app",
                "namespace": "argocd",
            },
            "spec": {
                "project": "default",
                "source": {
                    "repoURL": "https://github.com/example/repo.git",
                    "path": "manifests",
                    "targetRevision": "main",
                },
                "destination": {
                    "server": "https://kubernetes.default.svc",
                    "namespace": "production",
                },
            },
            "status": {
                "sync": {"status": "Synced"},
                "health": {"status": "Healthy"},
            },
        }

        app = Application.from_api_response(response)

        assert app.name == "test-app"
        assert app.namespace == "argocd"
        assert app.project == "default"
        assert app.repo_url == "https://github.com/example/repo.git"
        assert app.path == "manifests"
        assert app.target_revision == "main"
        assert app.destination_server == "https://kubernetes.default.svc"
        assert app.destination_namespace == "production"
        assert app.sync_status == "Synced"
        assert app.health_status == "Healthy"

    def test_from_api_response_with_defaults(self):
        """Test creating Application with missing fields uses defaults."""
        response = {
            "metadata": {"name": "minimal-app"},
            "spec": {},
            "status": {},
        }

        app = Application.from_api_response(response)

        assert app.name == "minimal-app"
        assert app.namespace == "argocd"
        assert app.project == "default"
        assert app.sync_status == "Unknown"
        assert app.health_status == "Unknown"

    def test_from_api_response_with_operation_state(self):
        """Test creating Application with operation state."""
        response = {
            "metadata": {"name": "test-app"},
            "spec": {},
            "status": {
                "sync": {"status": "OutOfSync"},
                "health": {"status": "Degraded"},
                "operationState": {
                    "phase": "Failed",
                    "message": "Sync failed",
                },
            },
        }

        app = Application.from_api_response(response)

        assert app.operation_state is not None
        assert app.operation_state["phase"] == "Failed"

    def test_from_api_response_with_conditions(self):
        """Test creating Application with conditions."""
        response = {
            "metadata": {"name": "test-app"},
            "spec": {},
            "status": {
                "sync": {"status": "Unknown"},
                "health": {"status": "Unknown"},
                "conditions": [
                    {"type": "SyncError", "message": "Error during sync"},
                ],
            },
        }

        app = Application.from_api_response(response)

        assert app.conditions is not None
        assert len(app.conditions) == 1
        assert app.conditions[0]["type"] == "SyncError"


@pytest.mark.unit
class TestArgocdError:
    """Tests for ArgocdError class."""

    def test_str_without_details(self):
        """Test string representation without details."""
        error = ArgocdError(code=404, message="Application not found")

        assert str(error) == "ArgoCD API error (404): Application not found"

    def test_str_with_details(self):
        """Test string representation with details."""
        error = ArgocdError(
            code=400,
            message="Bad request",
            details="Invalid application spec",
        )

        result = str(error)
        assert "400" in result
        assert "Bad request" in result
        assert "Invalid application spec" in result


@pytest.mark.unit
class TestArgocdClient:
    """Tests for ArgocdClient class."""

    def test_init(self, mock_argocd_instance: ArgocdInstance):
        """Test client initialization."""
        client = ArgocdClient(mock_argocd_instance)

        assert client._instance == mock_argocd_instance
        assert client._timeout == 30.0
        assert client._mask_secrets is True
        assert client._client is None

    def test_init_custom_timeout(self, mock_argocd_instance: ArgocdInstance):
        """Test client initialization with custom timeout."""
        client = ArgocdClient(mock_argocd_instance, timeout=60.0)

        assert client._timeout == 60.0

    def test_mask_secrets_disabled(self, mock_argocd_instance: ArgocdInstance):
        """Test client with secret masking disabled."""
        client = ArgocdClient(mock_argocd_instance, mask_secrets=False)

        assert client._mask_secrets is False

    def test_mask_response_string(self, mock_argocd_instance: ArgocdInstance):
        """Test masking secrets in string response."""
        client = ArgocdClient(mock_argocd_instance)

        input_str = 'token: "secret123", password: "pass456"'
        result = client._mask_response(input_str)

        assert "secret123" not in result
        assert "pass456" not in result
        assert "***MASKED***" in result

    def test_mask_response_dict(self, mock_argocd_instance: ArgocdInstance):
        """Test masking secrets in dict response."""
        client = ArgocdClient(mock_argocd_instance)

        input_dict = {
            "name": "app",
            "token": "secret123",
            "nested": {"password": "pass456"},
        }
        result = client._mask_response(input_dict)

        assert "secret123" not in str(result)
        assert "pass456" not in str(result)

    def test_mask_response_list(self, mock_argocd_instance: ArgocdInstance):
        """Test masking secrets in list response."""
        client = ArgocdClient(mock_argocd_instance)

        input_list = ["token: secret123", "normal value"]
        result = client._mask_response(input_list)

        assert "secret123" not in str(result)
        assert "normal value" in result

    def test_mask_response_passthrough(self, mock_argocd_instance: ArgocdInstance):
        """Test masking passes through non-string/dict/list values."""
        client = ArgocdClient(mock_argocd_instance)

        assert client._mask_response(123) == 123
        assert client._mask_response(None) is None
        assert client._mask_response(True) is True

    def test_context_manager_not_entered(self, mock_argocd_instance: ArgocdInstance):
        """Test that client raises when not in context manager."""
        client = ArgocdClient(mock_argocd_instance)

        with pytest.raises(RuntimeError, match="not initialized"):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                client._request("GET", "/applications")
            )
