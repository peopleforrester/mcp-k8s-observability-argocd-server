# ABOUTME: Integration tests for ArgoCD API client against a live ArgoCD instance
# ABOUTME: Requires a Kind cluster with ArgoCD installed (kind-argocd-mcp-test context)

"""Integration tests for ArgoCD client against live ArgoCD on Kind cluster.

These tests require:
- Kind cluster with context 'kind-argocd-mcp-test'
- ArgoCD installed in 'argocd' namespace
- kubectl available in PATH

The tests create a temporary nginx application, run various API operations,
and clean up after themselves.
"""

from __future__ import annotations

import base64
import os
import signal
import socket
import subprocess
import time
from typing import TYPE_CHECKING, Iterator

import pytest
from pydantic import SecretStr

from argocd_mcp.config import ArgocdInstance
from argocd_mcp.utils.client import Application, ArgocdClient, ArgocdError

if TYPE_CHECKING:
    pass


# Test application manifest for ArgoCD
TEST_APP_NAME = "integration-test-nginx"
TEST_APP_NAMESPACE = "argocd"
TEST_APP_DEST_NAMESPACE = "default"

TEST_APP_MANIFEST = f"""
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {TEST_APP_NAME}
  namespace: {TEST_APP_NAMESPACE}
spec:
  project: default
  source:
    repoURL: https://github.com/argoproj/argocd-example-apps.git
    targetRevision: HEAD
    path: guestbook
  destination:
    server: https://kubernetes.default.svc
    namespace: {TEST_APP_DEST_NAMESPACE}
  syncPolicy:
    automated: null
"""


def _kubectl_context() -> str:
    """Return the kubectl context to use for tests."""
    return os.environ.get("TEST_K8S_CONTEXT", "kind-argocd-mcp-test")


def _is_argocd_available() -> bool:
    """Check if ArgoCD is available on the Kind cluster."""
    ctx = _kubectl_context()
    try:
        result = subprocess.run(
            [
                "kubectl", "--context", ctx, "get", "pods", "-n", "argocd",
                "-l", "app.kubernetes.io/name=argocd-server",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and "Running" in result.stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def _get_argocd_password() -> str | None:
    """Get ArgoCD admin password from the cluster."""
    ctx = _kubectl_context()
    try:
        result = subprocess.run(
            [
                "kubectl", "--context", ctx, "-n", "argocd",
                "get", "secret", "argocd-initial-admin-secret",
                "-o", "jsonpath={.data.password}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        return base64.b64decode(result.stdout).decode("utf-8")
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def _get_argocd_token(url: str, username: str, password: str) -> str | None:
    """Get ArgoCD API token by authenticating with username/password.

    Args:
        url: ArgoCD server URL
        username: ArgoCD username (usually 'admin')
        password: ArgoCD password

    Returns:
        JWT token or None if authentication fails
    """
    import httpx

    try:
        with httpx.Client(verify=False, timeout=30.0) as client:
            response = client.post(
                f"{url}/api/v1/session",
                json={"username": username, "password": password},
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("token")
            print(f"ArgoCD auth failed: {response.status_code} - {response.text[:200]}")
            return None
    except Exception as e:
        print(f"ArgoCD auth error: {e}")
        return None


class PortForwardProcess:
    """Manages a kubectl port-forward process in the background."""

    def __init__(
        self,
        context: str,
        namespace: str,
        service: str,
        local_port: int,
        remote_port: int,
    ):
        self.context = context
        self.namespace = namespace
        self.service = service
        self.local_port = local_port
        self.remote_port = remote_port
        self._process: subprocess.Popen | None = None

    def start(self) -> bool:
        """Start port-forward process. Returns True if successful."""
        cmd = [
            "kubectl", "--context", self.context,
            "-n", self.namespace,
            "port-forward",
            f"svc/{self.service}",
            f"{self.local_port}:{self.remote_port}",
        ]

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid,
            )

            # Wait a bit and check if process is still running
            time.sleep(2)
            if self._process.poll() is not None:
                stderr = self._process.stderr.read().decode() if self._process.stderr else ""
                print(f"Port-forward failed to start: {stderr}")
                return False

            return self._verify_port_listening()
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            print(f"Failed to start port-forward: {e}")
            return False

    def _verify_port_listening(self) -> bool:
        """Verify that the port is actually listening."""
        max_attempts = 10
        for _ in range(max_attempts):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(("localhost", self.local_port))
                sock.close()
                if result == 0:
                    return True
            except socket.error:
                pass
            time.sleep(0.5)
        return False

    def stop(self) -> None:
        """Stop the port-forward process."""
        if self._process is not None:
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
                self._process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            finally:
                self._process = None


# Module-level state for port-forward (shared across tests)
_port_forward: PortForwardProcess | None = None
_port_forward_port: int | None = None


@pytest.fixture(scope="module")
def argocd_port_forward() -> Iterator[int | None]:
    """Set up port-forward to ArgoCD server and return the local port.

    This fixture creates a kubectl port-forward to the ArgoCD server
    running in the Kind cluster. It yields the local port number or
    None if the port-forward could not be established.
    """
    global _port_forward, _port_forward_port

    if not _is_argocd_available():
        yield None
        return

    local_port = 18080
    port_forward = PortForwardProcess(
        context=_kubectl_context(),
        namespace="argocd",
        service="argocd-server",
        local_port=local_port,
        remote_port=443,
    )

    if not port_forward.start():
        yield None
        return

    _port_forward = port_forward
    _port_forward_port = local_port

    print(f"\nPort-forward established: localhost:{local_port} -> argocd-server:443")

    try:
        yield local_port
    finally:
        print("\nStopping port-forward...")
        port_forward.stop()
        _port_forward = None
        _port_forward_port = None


@pytest.fixture(scope="module")
def argocd_connection(argocd_port_forward: int | None) -> tuple[str, str] | None:
    """Get ArgoCD URL and token for integration tests.

    Returns a tuple of (url, token) or None if ArgoCD is not available.
    """
    if argocd_port_forward is None:
        return None

    password = _get_argocd_password()
    if password is None:
        print("Could not get ArgoCD admin password")
        return None

    url = f"https://localhost:{argocd_port_forward}"

    # Authenticate with ArgoCD to get a JWT token
    token = _get_argocd_token(url, "admin", password)
    if token is None:
        print("Could not get ArgoCD API token")
        return None

    print(f"\nArgoCD authentication successful, got API token")
    return (url, token)


@pytest.fixture(scope="module")
def argocd_instance(argocd_connection: tuple[str, str] | None) -> ArgocdInstance | None:
    """Create ArgoCD instance configuration.

    Returns an ArgocdInstance or None if ArgoCD is not available.
    """
    if argocd_connection is None:
        return None

    url, token = argocd_connection
    return ArgocdInstance(
        url=url,
        token=SecretStr(token),
        name="integration-test",
        insecure=True,
    )


@pytest.fixture(scope="module")
def test_application(argocd_connection: tuple[str, str] | None) -> Iterator[str | None]:
    """Create a test ArgoCD application and clean it up after tests.

    This fixture creates an nginx-based test application using kubectl,
    yields the application name, and cleans up after all tests complete.
    """
    if argocd_connection is None:
        yield None
        return

    ctx = _kubectl_context()

    print(f"\nCreating test application: {TEST_APP_NAME}")
    try:
        result = subprocess.run(
            ["kubectl", "--context", ctx, "apply", "-f", "-"],
            input=TEST_APP_MANIFEST,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"Failed to create test application: {result.stderr}")
            yield None
            return
        print(f"Test application created: {TEST_APP_NAME}")
    except subprocess.SubprocessError as e:
        print(f"Error creating test application: {e}")
        yield None
        return

    # Wait for application to be registered in ArgoCD
    time.sleep(3)

    try:
        yield TEST_APP_NAME
    finally:
        print(f"\nCleaning up test application: {TEST_APP_NAME}")
        try:
            subprocess.run(
                [
                    "kubectl", "--context", ctx, "-n", TEST_APP_NAMESPACE,
                    "delete", "application", TEST_APP_NAME,
                    "--ignore-not-found",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            print(f"Test application deleted: {TEST_APP_NAME}")
        except subprocess.SubprocessError as e:
            print(f"Warning: Failed to delete test application: {e}")


# Skip marker for tests that require ArgoCD
requires_argocd = pytest.mark.skipif(
    not _is_argocd_available(),
    reason="ArgoCD not available on Kind cluster",
)


@pytest.mark.integration
class TestArgocdClientIntegration:
    """Integration tests for ArgoCD client against live ArgoCD."""

    @requires_argocd
    async def test_client_connection(
        self,
        argocd_instance: ArgocdInstance | None,
    ):
        """Test that we can establish a connection to ArgoCD."""
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")

        async with ArgocdClient(argocd_instance) as client:
            settings = await client.get_settings()
            assert isinstance(settings, dict)

    @requires_argocd
    async def test_list_applications_empty_or_with_test(
        self,
        argocd_instance: ArgocdInstance | None,
    ):
        """Test listing applications from live ArgoCD."""
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")

        async with ArgocdClient(argocd_instance) as client:
            apps = await client.list_applications()

            assert isinstance(apps, list)
            for app in apps:
                assert isinstance(app, Application)
                assert app.name

    @requires_argocd
    async def test_list_applications_with_test_app(
        self,
        argocd_instance: ArgocdInstance | None,
        test_application: str | None,
    ):
        """Test listing applications includes our test application."""
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")
        if test_application is None:
            pytest.skip("Test application not created")

        async with ArgocdClient(argocd_instance) as client:
            apps = await client.list_applications()

            app_names = [app.name for app in apps]
            assert test_application in app_names, (
                f"Test app '{test_application}' not found in {app_names}"
            )

    @requires_argocd
    async def test_get_application(
        self,
        argocd_instance: ArgocdInstance | None,
        test_application: str | None,
    ):
        """Test getting a specific application by name."""
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")
        if test_application is None:
            pytest.skip("Test application not created")

        async with ArgocdClient(argocd_instance) as client:
            app = await client.get_application(test_application)

            assert isinstance(app, Application)
            assert app.name == test_application
            assert app.project == "default"
            assert app.repo_url == "https://github.com/argoproj/argocd-example-apps.git"
            assert app.path == "guestbook"
            assert app.destination_namespace == TEST_APP_DEST_NAMESPACE

    @requires_argocd
    async def test_get_application_not_found(
        self,
        argocd_instance: ArgocdInstance | None,
    ):
        """Test getting a non-existent application raises an error.

        Note: ArgoCD returns 403 (permission denied) for non-existent apps
        as a security measure to prevent enumeration attacks.
        """
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")

        async with ArgocdClient(argocd_instance) as client:
            with pytest.raises(ArgocdError) as exc_info:
                await client.get_application("nonexistent-app-12345")

            # ArgoCD returns 403 or 404 for non-existent apps
            assert exc_info.value.code in (403, 404)

    @requires_argocd
    async def test_get_application_diff(
        self,
        argocd_instance: ArgocdInstance | None,
        test_application: str | None,
    ):
        """Test getting application diff/managed-resources."""
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")
        if test_application is None:
            pytest.skip("Test application not created")

        async with ArgocdClient(argocd_instance) as client:
            diff = await client.get_application_diff(test_application)

            assert isinstance(diff, dict)
            if "items" in diff:
                assert isinstance(diff["items"], list)

    @requires_argocd
    async def test_get_resource_tree(
        self,
        argocd_instance: ArgocdInstance | None,
        test_application: str | None,
    ):
        """Test getting application resource tree."""
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")
        if test_application is None:
            pytest.skip("Test application not created")

        async with ArgocdClient(argocd_instance) as client:
            tree = await client.get_resource_tree(test_application)

            assert isinstance(tree, dict)
            assert "nodes" in tree or "orphanedNodes" in tree

    @requires_argocd
    async def test_sync_application_dry_run(
        self,
        argocd_instance: ArgocdInstance | None,
        test_application: str | None,
    ):
        """Test syncing application with dry_run=True."""
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")
        if test_application is None:
            pytest.skip("Test application not created")

        async with ArgocdClient(argocd_instance) as client:
            result = await client.sync_application(
                test_application,
                dry_run=True,
                prune=False,
            )

            assert isinstance(result, dict)

    @requires_argocd
    async def test_refresh_application(
        self,
        argocd_instance: ArgocdInstance | None,
        test_application: str | None,
    ):
        """Test refreshing application manifest from Git."""
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")
        if test_application is None:
            pytest.skip("Test application not created")

        async with ArgocdClient(argocd_instance) as client:
            app = await client.refresh_application(test_application)

            assert isinstance(app, Application)
            assert app.name == test_application

    @requires_argocd
    async def test_get_application_history(
        self,
        argocd_instance: ArgocdInstance | None,
        test_application: str | None,
    ):
        """Test getting application deployment history."""
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")
        if test_application is None:
            pytest.skip("Test application not created")

        async with ArgocdClient(argocd_instance) as client:
            history = await client.get_application_history(test_application)

            assert isinstance(history, list)

    @requires_argocd
    async def test_get_application_events(
        self,
        argocd_instance: ArgocdInstance | None,
        test_application: str | None,
    ):
        """Test getting Kubernetes events for application."""
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")
        if test_application is None:
            pytest.skip("Test application not created")

        async with ArgocdClient(argocd_instance) as client:
            events = await client.get_application_events(test_application)

            assert isinstance(events, list)

    @requires_argocd
    async def test_list_clusters(
        self,
        argocd_instance: ArgocdInstance | None,
    ):
        """Test listing clusters from live ArgoCD."""
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")

        async with ArgocdClient(argocd_instance) as client:
            clusters = await client.list_clusters()

            assert isinstance(clusters, list)
            assert len(clusters) >= 1

            cluster_servers = [c.get("server", "") for c in clusters]
            assert any(
                "kubernetes.default" in s for s in cluster_servers
            ), f"No in-cluster endpoint found in {cluster_servers}"

    @requires_argocd
    async def test_list_projects(
        self,
        argocd_instance: ArgocdInstance | None,
    ):
        """Test listing projects from live ArgoCD."""
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")

        async with ArgocdClient(argocd_instance) as client:
            projects = await client.list_projects()

            assert isinstance(projects, list)
            assert len(projects) >= 1

            project_names = [p.get("metadata", {}).get("name", "") for p in projects]
            assert "default" in project_names, (
                f"Default project not found in {project_names}"
            )

    @requires_argocd
    async def test_get_settings(
        self,
        argocd_instance: ArgocdInstance | None,
    ):
        """Test getting ArgoCD settings."""
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")

        async with ArgocdClient(argocd_instance) as client:
            settings = await client.get_settings()

            assert isinstance(settings, dict)


@pytest.mark.integration
class TestArgocdClientErrorHandling:
    """Test error handling in ArgoCD client.

    Note: ArgoCD returns 403 (permission denied) for non-existent apps
    as a security measure to prevent enumeration attacks.
    """

    @requires_argocd
    async def test_invalid_application_name(
        self,
        argocd_instance: ArgocdInstance | None,
    ):
        """Test that invalid application names return proper errors."""
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")

        async with ArgocdClient(argocd_instance) as client:
            with pytest.raises(ArgocdError) as exc_info:
                await client.get_application("this-app-does-not-exist-xyz")

            error = exc_info.value
            # ArgoCD returns 403 or 404 for non-existent apps
            assert error.code in (403, 404)
            assert (
                "not found" in error.message.lower()
                or "permission denied" in error.message.lower()
                or "not found" in (error.details or "").lower()
                or "permission denied" in (error.details or "").lower()
            )

    @requires_argocd
    async def test_sync_nonexistent_app(
        self,
        argocd_instance: ArgocdInstance | None,
    ):
        """Test syncing a non-existent application."""
        if argocd_instance is None:
            pytest.skip("ArgoCD connection not available")

        async with ArgocdClient(argocd_instance) as client:
            with pytest.raises(ArgocdError) as exc_info:
                await client.sync_application(
                    "nonexistent-sync-app-12345",
                    dry_run=True,
                )

            # ArgoCD returns 403 or 404 for non-existent apps
            assert exc_info.value.code in (403, 404)
