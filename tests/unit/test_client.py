# ABOUTME: Unit tests for ArgoCD API client
# ABOUTME: Tests client initialization, request handling, and response parsing

import httpx
import pytest
import respx
from pydantic import SecretStr

from argocd_mcp.config import ArgocdInstance
from argocd_mcp.utils.client import Application, ArgocdClient, ArgocdError

BASE_URL = "https://argocd.example.com/api/v1"


@pytest.fixture
def instance() -> ArgocdInstance:
    """Create an ArgoCD instance for respx-based tests."""
    return ArgocdInstance(
        url="https://argocd.example.com",
        token=SecretStr("test-token"),
        name="test",
        insecure=True,
    )


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

    def test_from_api_response_empty_data(self):
        """Test creating Application from completely empty data."""
        app = Application.from_api_response({})

        assert app.name == ""
        assert app.namespace == "argocd"
        assert app.project == "default"
        assert app.repo_url == ""
        assert app.path == ""
        assert app.target_revision == "HEAD"
        assert app.destination_server == ""
        assert app.destination_namespace == ""
        assert app.sync_status == "Unknown"
        assert app.health_status == "Unknown"

    def test_from_api_response_with_resources(self):
        """Test creating Application with resources list."""
        response = {
            "metadata": {"name": "test-app"},
            "spec": {},
            "status": {
                "sync": {"status": "Synced"},
                "health": {"status": "Healthy"},
                "resources": [
                    {"kind": "Deployment", "name": "web", "status": "Synced"},
                ],
            },
        }

        app = Application.from_api_response(response)

        assert app.resources is not None
        assert len(app.resources) == 1
        assert app.resources[0]["kind"] == "Deployment"


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

    def test_inherits_from_exception(self):
        """Test ArgocdError is a proper Exception subclass."""
        error = ArgocdError(code=500, message="Internal server error")
        assert isinstance(error, Exception)
        assert error.code == 500
        assert error.message == "Internal server error"
        assert error.details is None


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

    def test_mask_response_disabled_returns_unchanged(self, mock_argocd_instance: ArgocdInstance):
        """Test masking returns data unchanged when disabled."""
        client = ArgocdClient(mock_argocd_instance, mask_secrets=False)

        data = {"token": "visible-secret", "name": "app"}
        result = client._mask_response(data)

        assert result["token"] == "visible-secret"

    def test_mask_response_bearer_token(self, mock_argocd_instance: ArgocdInstance):
        """Test masking Bearer tokens in strings."""
        client = ArgocdClient(mock_argocd_instance)

        input_str = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.secret"
        result = client._mask_response(input_str)

        assert "eyJhbGciOiJIUzI1NiJ9" not in result
        assert "***MASKED***" in result

    def test_mask_response_api_key(self, mock_argocd_instance: ArgocdInstance):
        """Test masking api_key in dicts."""
        client = ArgocdClient(mock_argocd_instance)

        data = {"api_key": "sk-12345", "name": "app"}
        result = client._mask_response(data)

        assert result["api_key"] == "***MASKED***"
        assert result["name"] == "app"

    def test_context_manager_not_entered(self, mock_argocd_instance: ArgocdInstance):
        """Test that client raises when not in context manager."""
        client = ArgocdClient(mock_argocd_instance)

        with pytest.raises(RuntimeError, match="not initialized"):
            import asyncio

            asyncio.get_event_loop().run_until_complete(client._request("GET", "/applications"))


@pytest.mark.unit
class TestArgocdClientContextManager:
    """Tests for ArgocdClient async context manager."""

    async def test_context_manager_creates_and_closes_client(self, instance: ArgocdInstance):
        """Test async with creates httpx client and closes it on exit."""
        client = ArgocdClient(instance)
        assert client._client is None

        async with client:
            assert client._client is not None
            assert isinstance(client._client, httpx.AsyncClient)

        assert client._client is None

    async def test_context_manager_returns_self(self, instance: ArgocdInstance):
        """Test async with returns the client instance."""
        client = ArgocdClient(instance)

        async with client as c:
            assert c is client


@pytest.mark.unit
class TestArgocdClientRequest:
    """Tests for ArgocdClient._request method."""

    @respx.mock
    async def test_request_get_success(self, instance: ArgocdInstance):
        """Test successful GET request."""
        respx.get(f"{BASE_URL}/applications").mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        async with ArgocdClient(instance) as client:
            result = await client._request("GET", "/applications")

        assert result == {"items": []}

    @respx.mock
    async def test_request_post_success(self, instance: ArgocdInstance):
        """Test successful POST request with JSON body."""
        respx.post(f"{BASE_URL}/applications/my-app/sync").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )

        async with ArgocdClient(instance) as client:
            result = await client._request(
                "POST", "/applications/my-app/sync", json_data={"dryRun": True}
            )

        assert result == {"status": "ok"}

    @respx.mock
    async def test_request_raises_argocd_error_on_404(self, instance: ArgocdInstance):
        """Test _request raises ArgocdError on 404."""
        respx.get(f"{BASE_URL}/applications/nonexistent").mock(
            return_value=httpx.Response(
                404, json={"message": "application 'nonexistent' not found"}
            )
        )

        async with ArgocdClient(instance) as client:
            with pytest.raises(ArgocdError) as exc_info:
                await client._request("GET", "/applications/nonexistent")

        assert exc_info.value.code == 404
        assert "nonexistent" in exc_info.value.message

    @respx.mock
    async def test_request_raises_argocd_error_on_500(self, instance: ArgocdInstance):
        """Test _request raises ArgocdError on server error."""
        respx.get(f"{BASE_URL}/applications").mock(
            return_value=httpx.Response(500, json={"message": "internal error"})
        )

        async with ArgocdClient(instance) as client:
            with pytest.raises(ArgocdError) as exc_info:
                await client._request("GET", "/applications")

        assert exc_info.value.code == 500

    @respx.mock
    async def test_request_handles_non_json_error_body(self, instance: ArgocdInstance):
        """Test _request handles non-JSON error responses."""
        respx.get(f"{BASE_URL}/applications").mock(
            return_value=httpx.Response(502, text="Bad Gateway")
        )

        async with ArgocdClient(instance) as client:
            with pytest.raises(ArgocdError) as exc_info:
                await client._request("GET", "/applications")

        assert exc_info.value.code == 502
        assert exc_info.value.details is not None

    @respx.mock
    async def test_request_handles_error_with_details(self, instance: ArgocdInstance):
        """Test _request extracts error details from JSON response."""
        respx.get(f"{BASE_URL}/applications/my-app").mock(
            return_value=httpx.Response(
                403, json={"message": "permission denied", "error": "RBAC: access denied"}
            )
        )

        async with ArgocdClient(instance) as client:
            with pytest.raises(ArgocdError) as exc_info:
                await client._request("GET", "/applications/my-app")

        assert exc_info.value.code == 403
        assert exc_info.value.message == "permission denied"
        assert exc_info.value.details == "RBAC: access denied"

    @respx.mock
    async def test_request_masks_response(self, instance: ArgocdInstance):
        """Test _request masks secrets in successful responses."""
        respx.get(f"{BASE_URL}/settings").mock(
            return_value=httpx.Response(200, json={"token": "super-secret", "version": "2.8"})
        )

        async with ArgocdClient(instance) as client:
            result = await client._request("GET", "/settings")

        assert result["token"] == "***MASKED***"
        assert result["version"] == "2.8"

    @respx.mock
    async def test_request_with_query_params(self, instance: ArgocdInstance):
        """Test _request passes query parameters."""
        route = respx.get(f"{BASE_URL}/applications").mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        async with ArgocdClient(instance) as client:
            await client._request("GET", "/applications", params={"project": "default"})

        assert route.called
        assert "project=default" in str(route.calls[0].request.url)

    @respx.mock
    async def test_request_returns_empty_dict_for_empty_body(self, instance: ArgocdInstance):
        """Test _request returns empty dict when response has no content."""
        respx.delete(f"{BASE_URL}/applications/my-app/operation").mock(
            return_value=httpx.Response(200, content=b"")
        )

        async with ArgocdClient(instance) as client:
            result = await client._request("DELETE", "/applications/my-app/operation")

        assert result == {}

    @respx.mock
    async def test_request_returns_empty_dict_for_non_dict_response(self, instance: ArgocdInstance):
        """Test _request returns empty dict when masked response is not a dict."""
        respx.get(f"{BASE_URL}/applications").mock(
            return_value=httpx.Response(200, json=["item1", "item2"])
        )

        async with ArgocdClient(instance) as client:
            result = await client._request("GET", "/applications")

        assert result == {}


@pytest.mark.unit
class TestArgocdClientListApplications:
    """Tests for ArgocdClient.list_applications method."""

    @respx.mock
    async def test_list_applications_returns_apps(self, instance: ArgocdInstance):
        """Test list_applications returns Application objects."""
        respx.get(f"{BASE_URL}/applications").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "metadata": {"name": "app-1"},
                            "spec": {},
                            "status": {
                                "sync": {"status": "Synced"},
                                "health": {"status": "Healthy"},
                            },
                        },
                        {
                            "metadata": {"name": "app-2"},
                            "spec": {},
                            "status": {
                                "sync": {"status": "OutOfSync"},
                                "health": {"status": "Degraded"},
                            },
                        },
                    ]
                },
            )
        )

        async with ArgocdClient(instance) as client:
            apps = await client.list_applications()

        assert len(apps) == 2
        assert apps[0].name == "app-1"
        assert apps[1].name == "app-2"
        assert isinstance(apps[0], Application)

    @respx.mock
    async def test_list_applications_empty(self, instance: ArgocdInstance):
        """Test list_applications with no items."""
        respx.get(f"{BASE_URL}/applications").mock(
            return_value=httpx.Response(200, json={"items": None})
        )

        async with ArgocdClient(instance) as client:
            apps = await client.list_applications()

        assert apps == []

    @respx.mock
    async def test_list_applications_with_project_filter(self, instance: ArgocdInstance):
        """Test list_applications passes project filter."""
        route = respx.get(f"{BASE_URL}/applications").mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        async with ArgocdClient(instance) as client:
            await client.list_applications(project="production")

        assert "project=production" in str(route.calls[0].request.url)

    @respx.mock
    async def test_list_applications_with_selector(self, instance: ArgocdInstance):
        """Test list_applications passes label selector."""
        route = respx.get(f"{BASE_URL}/applications").mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        async with ArgocdClient(instance) as client:
            await client.list_applications(selector="team=backend")

        assert "selector=team" in str(route.calls[0].request.url)

    @respx.mock
    async def test_list_applications_no_params_when_none(self, instance: ArgocdInstance):
        """Test list_applications passes no params when none provided."""
        route = respx.get(f"{BASE_URL}/applications").mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        async with ArgocdClient(instance) as client:
            await client.list_applications()

        assert "?" not in str(route.calls[0].request.url)


@pytest.mark.unit
class TestArgocdClientGetApplication:
    """Tests for ArgocdClient.get_application method."""

    @respx.mock
    async def test_get_application_returns_app(self, instance: ArgocdInstance):
        """Test get_application returns Application object."""
        respx.get(f"{BASE_URL}/applications/my-app").mock(
            return_value=httpx.Response(
                200,
                json={
                    "metadata": {"name": "my-app", "namespace": "argocd"},
                    "spec": {"project": "default", "source": {}, "destination": {}},
                    "status": {
                        "sync": {"status": "Synced"},
                        "health": {"status": "Healthy"},
                    },
                },
            )
        )

        async with ArgocdClient(instance) as client:
            app = await client.get_application("my-app")

        assert isinstance(app, Application)
        assert app.name == "my-app"
        assert app.sync_status == "Synced"

    @respx.mock
    async def test_get_application_not_found(self, instance: ArgocdInstance):
        """Test get_application raises on 404."""
        respx.get(f"{BASE_URL}/applications/nonexistent").mock(
            return_value=httpx.Response(
                404, json={"message": "application 'nonexistent' not found"}
            )
        )

        async with ArgocdClient(instance) as client:
            with pytest.raises(ArgocdError) as exc_info:
                await client.get_application("nonexistent")

        assert exc_info.value.code == 404


@pytest.mark.unit
class TestArgocdClientGetApplicationDiff:
    """Tests for ArgocdClient.get_application_diff method."""

    @respx.mock
    async def test_get_application_diff(self, instance: ArgocdInstance):
        """Test get_application_diff returns diff data."""
        diff_data = {
            "items": [{"kind": "Deployment", "name": "web", "liveState": "{}", "targetState": "{}"}]
        }
        respx.get(f"{BASE_URL}/applications/my-app/managed-resources").mock(
            return_value=httpx.Response(200, json=diff_data)
        )

        async with ArgocdClient(instance) as client:
            result = await client.get_application_diff("my-app")

        assert "items" in result
        assert len(result["items"]) == 1

    @respx.mock
    async def test_get_application_diff_with_revision(self, instance: ArgocdInstance):
        """Test get_application_diff passes revision param."""
        route = respx.get(f"{BASE_URL}/applications/my-app/managed-resources").mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        async with ArgocdClient(instance) as client:
            await client.get_application_diff("my-app", revision="abc123")

        assert "revision=abc123" in str(route.calls[0].request.url)

    @respx.mock
    async def test_get_application_diff_no_revision(self, instance: ArgocdInstance):
        """Test get_application_diff without revision has no params."""
        route = respx.get(f"{BASE_URL}/applications/my-app/managed-resources").mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        async with ArgocdClient(instance) as client:
            await client.get_application_diff("my-app")

        assert "?" not in str(route.calls[0].request.url)


@pytest.mark.unit
class TestArgocdClientGetApplicationHistory:
    """Tests for ArgocdClient.get_application_history method."""

    @respx.mock
    async def test_get_application_history_returns_entries(self, instance: ArgocdInstance):
        """Test get_application_history returns history entries."""
        respx.get(f"{BASE_URL}/applications/my-app").mock(
            return_value=httpx.Response(
                200,
                json={
                    "metadata": {"name": "my-app"},
                    "spec": {},
                    "status": {
                        "history": [
                            {"id": 1, "revision": "abc123", "deployedAt": "2025-01-01T00:00:00Z"},
                            {"id": 2, "revision": "def456", "deployedAt": "2025-01-02T00:00:00Z"},
                        ]
                    },
                },
            )
        )

        async with ArgocdClient(instance) as client:
            history = await client.get_application_history("my-app")

        assert len(history) == 2
        assert history[0]["revision"] == "abc123"
        assert history[1]["revision"] == "def456"

    @respx.mock
    async def test_get_application_history_with_limit(self, instance: ArgocdInstance):
        """Test get_application_history respects limit."""
        entries = [{"id": i, "revision": f"rev{i}"} for i in range(20)]
        respx.get(f"{BASE_URL}/applications/my-app").mock(
            return_value=httpx.Response(
                200,
                json={
                    "metadata": {"name": "my-app"},
                    "spec": {},
                    "status": {"history": entries},
                },
            )
        )

        async with ArgocdClient(instance) as client:
            history = await client.get_application_history("my-app", limit=5)

        assert len(history) == 5
        # Should return the most recent (last 5)
        assert history[0]["id"] == 15

    @respx.mock
    async def test_get_application_history_empty(self, instance: ArgocdInstance):
        """Test get_application_history with no history."""
        respx.get(f"{BASE_URL}/applications/my-app").mock(
            return_value=httpx.Response(
                200,
                json={
                    "metadata": {"name": "my-app"},
                    "spec": {},
                    "status": {},
                },
            )
        )

        async with ArgocdClient(instance) as client:
            history = await client.get_application_history("my-app")

        assert history == []


@pytest.mark.unit
class TestArgocdClientGetApplicationEvents:
    """Tests for ArgocdClient.get_application_events method."""

    @respx.mock
    async def test_get_application_events(self, instance: ArgocdInstance):
        """Test get_application_events returns event list."""
        respx.get(f"{BASE_URL}/applications/my-app/events").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"type": "Warning", "reason": "ImagePullBackOff", "message": "pull err"},
                    ]
                },
            )
        )

        async with ArgocdClient(instance) as client:
            events = await client.get_application_events("my-app")

        assert len(events) == 1
        assert events[0]["reason"] == "ImagePullBackOff"

    @respx.mock
    async def test_get_application_events_with_filters(self, instance: ArgocdInstance):
        """Test get_application_events passes resource filters."""
        route = respx.get(f"{BASE_URL}/applications/my-app/events").mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        async with ArgocdClient(instance) as client:
            await client.get_application_events(
                "my-app", resource_name="web-pod", resource_kind="Pod"
            )

        url = str(route.calls[0].request.url)
        assert "resourceName=web-pod" in url
        assert "resourceKind=Pod" in url

    @respx.mock
    async def test_get_application_events_empty(self, instance: ArgocdInstance):
        """Test get_application_events with no events."""
        respx.get(f"{BASE_URL}/applications/my-app/events").mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        async with ArgocdClient(instance) as client:
            events = await client.get_application_events("my-app")

        assert events == []

    @respx.mock
    async def test_get_application_events_no_params_when_none(self, instance: ArgocdInstance):
        """Test get_application_events passes no params when no filters."""
        route = respx.get(f"{BASE_URL}/applications/my-app/events").mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        async with ArgocdClient(instance) as client:
            await client.get_application_events("my-app")

        assert "?" not in str(route.calls[0].request.url)

    @respx.mock
    async def test_get_application_events_handles_non_list_items(self, instance: ArgocdInstance):
        """Test get_application_events handles non-list items gracefully."""
        respx.get(f"{BASE_URL}/applications/my-app/events").mock(
            return_value=httpx.Response(200, json={"items": "not a list"})
        )

        async with ArgocdClient(instance) as client:
            events = await client.get_application_events("my-app")

        assert events == []


@pytest.mark.unit
class TestArgocdClientGetResourceTree:
    """Tests for ArgocdClient.get_resource_tree method."""

    @respx.mock
    async def test_get_resource_tree(self, instance: ArgocdInstance):
        """Test get_resource_tree returns tree data."""
        tree_data = {
            "nodes": [
                {"kind": "Deployment", "name": "web", "health": {"status": "Healthy"}},
                {"kind": "ReplicaSet", "name": "web-abc", "health": {"status": "Healthy"}},
            ]
        }
        respx.get(f"{BASE_URL}/applications/my-app/resource-tree").mock(
            return_value=httpx.Response(200, json=tree_data)
        )

        async with ArgocdClient(instance) as client:
            result = await client.get_resource_tree("my-app")

        assert "nodes" in result
        assert len(result["nodes"]) == 2


@pytest.mark.unit
class TestArgocdClientGetLogs:
    """Tests for ArgocdClient.get_logs method."""

    @respx.mock
    async def test_get_logs_returns_content(self, instance: ArgocdInstance):
        """Test get_logs returns log content."""
        respx.get(f"{BASE_URL}/applications/my-app/logs").mock(
            return_value=httpx.Response(200, json={"content": "log line 1\nlog line 2"})
        )

        async with ArgocdClient(instance) as client:
            logs = await client.get_logs("my-app")

        assert "log line 1" in logs
        assert "log line 2" in logs

    @respx.mock
    async def test_get_logs_with_all_params(self, instance: ArgocdInstance):
        """Test get_logs passes all parameters."""
        route = respx.get(f"{BASE_URL}/applications/my-app/logs").mock(
            return_value=httpx.Response(200, json={"content": ""})
        )

        async with ArgocdClient(instance) as client:
            await client.get_logs(
                "my-app",
                pod_name="web-pod-123",
                container="web",
                tail_lines=50,
                since_seconds=3600,
            )

        url = str(route.calls[0].request.url)
        assert "podName=web-pod-123" in url
        assert "container=web" in url
        assert "tailLines=50" in url
        assert "sinceSeconds=3600" in url

    @respx.mock
    async def test_get_logs_empty_content(self, instance: ArgocdInstance):
        """Test get_logs with empty content field."""
        respx.get(f"{BASE_URL}/applications/my-app/logs").mock(
            return_value=httpx.Response(200, json={"content": ""})
        )

        async with ArgocdClient(instance) as client:
            logs = await client.get_logs("my-app")

        assert logs == ""

    @respx.mock
    async def test_get_logs_missing_content_field(self, instance: ArgocdInstance):
        """Test get_logs when content field is missing."""
        respx.get(f"{BASE_URL}/applications/my-app/logs").mock(
            return_value=httpx.Response(200, json={"other": "data"})
        )

        async with ArgocdClient(instance) as client:
            logs = await client.get_logs("my-app")

        assert logs == ""


@pytest.mark.unit
class TestArgocdClientSyncApplication:
    """Tests for ArgocdClient.sync_application method."""

    @respx.mock
    async def test_sync_application_dry_run(self, instance: ArgocdInstance):
        """Test sync_application with dry_run=True (default)."""
        route = respx.post(f"{BASE_URL}/applications/my-app/sync").mock(
            return_value=httpx.Response(200, json={"status": "dryRun"})
        )

        async with ArgocdClient(instance) as client:
            result = await client.sync_application("my-app")

        assert result["status"] == "dryRun"
        request_body = route.calls[0].request.content
        assert b'"dryRun": true' in request_body or b'"dryRun":true' in request_body

    @respx.mock
    async def test_sync_application_actual_sync(self, instance: ArgocdInstance):
        """Test sync_application with dry_run=False."""
        respx.post(f"{BASE_URL}/applications/my-app/sync").mock(
            return_value=httpx.Response(200, json={"status": "syncing"})
        )

        async with ArgocdClient(instance) as client:
            result = await client.sync_application("my-app", dry_run=False)

        assert result["status"] == "syncing"

    @respx.mock
    async def test_sync_application_with_revision(self, instance: ArgocdInstance):
        """Test sync_application with specific revision."""
        route = respx.post(f"{BASE_URL}/applications/my-app/sync").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )

        async with ArgocdClient(instance) as client:
            await client.sync_application("my-app", revision="abc123")

        body = route.calls[0].request.content.decode()
        assert "abc123" in body

    @respx.mock
    async def test_sync_application_with_force(self, instance: ArgocdInstance):
        """Test sync_application with force=True adds strategy."""
        route = respx.post(f"{BASE_URL}/applications/my-app/sync").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )

        async with ArgocdClient(instance) as client:
            await client.sync_application("my-app", force=True)

        body = route.calls[0].request.content.decode()
        assert "strategy" in body
        assert "force" in body

    @respx.mock
    async def test_sync_application_with_prune(self, instance: ArgocdInstance):
        """Test sync_application with prune=True."""
        route = respx.post(f"{BASE_URL}/applications/my-app/sync").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )

        async with ArgocdClient(instance) as client:
            await client.sync_application("my-app", prune=True)

        body = route.calls[0].request.content.decode()
        assert '"prune": true' in body or '"prune":true' in body


@pytest.mark.unit
class TestArgocdClientRollbackApplication:
    """Tests for ArgocdClient.rollback_application method."""

    @respx.mock
    async def test_rollback_application_dry_run(self, instance: ArgocdInstance):
        """Test rollback_application with dry_run=True (default)."""
        route = respx.post(f"{BASE_URL}/applications/my-app/rollback").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )

        async with ArgocdClient(instance) as client:
            result = await client.rollback_application("my-app", revision_id=3)

        assert result["status"] == "ok"
        body = route.calls[0].request.content.decode()
        assert '"id": 3' in body or '"id":3' in body

    @respx.mock
    async def test_rollback_application_actual(self, instance: ArgocdInstance):
        """Test rollback_application with dry_run=False."""
        respx.post(f"{BASE_URL}/applications/my-app/rollback").mock(
            return_value=httpx.Response(200, json={"status": "rolling back"})
        )

        async with ArgocdClient(instance) as client:
            result = await client.rollback_application("my-app", revision_id=5, dry_run=False)

        assert result["status"] == "rolling back"


@pytest.mark.unit
class TestArgocdClientRefreshApplication:
    """Tests for ArgocdClient.refresh_application method."""

    @respx.mock
    async def test_refresh_application_normal(self, instance: ArgocdInstance):
        """Test refresh_application with normal refresh."""
        route = respx.get(f"{BASE_URL}/applications/my-app").mock(
            return_value=httpx.Response(
                200,
                json={
                    "metadata": {"name": "my-app"},
                    "spec": {},
                    "status": {
                        "sync": {"status": "Synced"},
                        "health": {"status": "Healthy"},
                    },
                },
            )
        )

        async with ArgocdClient(instance) as client:
            app = await client.refresh_application("my-app")

        assert isinstance(app, Application)
        assert app.name == "my-app"
        assert "refresh=normal" in str(route.calls[0].request.url)

    @respx.mock
    async def test_refresh_application_hard(self, instance: ArgocdInstance):
        """Test refresh_application with hard refresh."""
        route = respx.get(f"{BASE_URL}/applications/my-app").mock(
            return_value=httpx.Response(
                200,
                json={
                    "metadata": {"name": "my-app"},
                    "spec": {},
                    "status": {
                        "sync": {"status": "Synced"},
                        "health": {"status": "Healthy"},
                    },
                },
            )
        )

        async with ArgocdClient(instance) as client:
            await client.refresh_application("my-app", hard=True)

        assert "refresh=hard" in str(route.calls[0].request.url)


@pytest.mark.unit
class TestArgocdClientTerminateSync:
    """Tests for ArgocdClient.terminate_sync method."""

    @respx.mock
    async def test_terminate_sync(self, instance: ArgocdInstance):
        """Test terminate_sync sends DELETE to operation endpoint."""
        respx.delete(f"{BASE_URL}/applications/my-app/operation").mock(
            return_value=httpx.Response(200, json={})
        )

        async with ArgocdClient(instance) as client:
            result = await client.terminate_sync("my-app")

        assert result == {}


@pytest.mark.unit
class TestArgocdClientDeleteApplication:
    """Tests for ArgocdClient.delete_application method."""

    @respx.mock
    async def test_delete_application_cascade(self, instance: ArgocdInstance):
        """Test delete_application with cascade=True (default)."""
        route = respx.delete(f"{BASE_URL}/applications/my-app").mock(
            return_value=httpx.Response(200, json={})
        )

        async with ArgocdClient(instance) as client:
            result = await client.delete_application("my-app")

        assert result == {}
        assert "cascade=true" in str(route.calls[0].request.url)

    @respx.mock
    async def test_delete_application_no_cascade(self, instance: ArgocdInstance):
        """Test delete_application with cascade=False."""
        route = respx.delete(f"{BASE_URL}/applications/my-app").mock(
            return_value=httpx.Response(200, json={})
        )

        async with ArgocdClient(instance) as client:
            await client.delete_application("my-app", cascade=False)

        assert "cascade=false" in str(route.calls[0].request.url)


@pytest.mark.unit
class TestArgocdClientListClusters:
    """Tests for ArgocdClient.list_clusters method."""

    @respx.mock
    async def test_list_clusters(self, instance: ArgocdInstance):
        """Test list_clusters returns cluster list."""
        respx.get(f"{BASE_URL}/clusters").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "name": "in-cluster",
                            "server": "https://kubernetes.default.svc",
                            "connectionState": {"status": "Successful"},
                        }
                    ]
                },
            )
        )

        async with ArgocdClient(instance) as client:
            clusters = await client.list_clusters()

        assert len(clusters) == 1
        assert clusters[0]["name"] == "in-cluster"

    @respx.mock
    async def test_list_clusters_empty(self, instance: ArgocdInstance):
        """Test list_clusters with no clusters."""
        respx.get(f"{BASE_URL}/clusters").mock(return_value=httpx.Response(200, json={"items": []}))

        async with ArgocdClient(instance) as client:
            clusters = await client.list_clusters()

        assert clusters == []

    @respx.mock
    async def test_list_clusters_handles_non_list_items(self, instance: ArgocdInstance):
        """Test list_clusters handles non-list items gracefully."""
        respx.get(f"{BASE_URL}/clusters").mock(
            return_value=httpx.Response(200, json={"items": "not a list"})
        )

        async with ArgocdClient(instance) as client:
            clusters = await client.list_clusters()

        assert clusters == []


@pytest.mark.unit
class TestArgocdClientListProjects:
    """Tests for ArgocdClient.list_projects method."""

    @respx.mock
    async def test_list_projects(self, instance: ArgocdInstance):
        """Test list_projects returns project list."""
        respx.get(f"{BASE_URL}/projects").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"metadata": {"name": "default"}, "spec": {"description": "Default"}},
                    ]
                },
            )
        )

        async with ArgocdClient(instance) as client:
            projects = await client.list_projects()

        assert len(projects) == 1
        assert projects[0]["metadata"]["name"] == "default"

    @respx.mock
    async def test_list_projects_empty(self, instance: ArgocdInstance):
        """Test list_projects with no projects."""
        respx.get(f"{BASE_URL}/projects").mock(return_value=httpx.Response(200, json={"items": []}))

        async with ArgocdClient(instance) as client:
            projects = await client.list_projects()

        assert projects == []


@pytest.mark.unit
class TestArgocdClientGetSettings:
    """Tests for ArgocdClient.get_settings method."""

    @respx.mock
    async def test_get_settings(self, instance: ArgocdInstance):
        """Test get_settings returns server settings."""
        respx.get(f"{BASE_URL}/settings").mock(
            return_value=httpx.Response(
                200, json={"appLabelKey": "app.kubernetes.io/instance", "url": "https://argocd.io"}
            )
        )

        async with ArgocdClient(instance) as client:
            settings = await client.get_settings()

        assert settings["appLabelKey"] == "app.kubernetes.io/instance"
