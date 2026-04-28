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

import subprocess
import time
from typing import TYPE_CHECKING

import pytest

from argocd_mcp.utils.client import Application, ArgocdClient, ArgocdError
from tests.integration.conftest import _is_argocd_available, _kubectl_context

if TYPE_CHECKING:
    from collections.abc import Iterator

    from argocd_mcp.config import ArgocdInstance

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
                    "kubectl",
                    "--context",
                    ctx,
                    "-n",
                    TEST_APP_NAMESPACE,
                    "delete",
                    "application",
                    TEST_APP_NAME,
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
            assert any("kubernetes.default" in s for s in cluster_servers), (
                f"No in-cluster endpoint found in {cluster_servers}"
            )

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
            assert "default" in project_names, f"Default project not found in {project_names}"

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
