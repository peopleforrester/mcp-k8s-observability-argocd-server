# ABOUTME: Integration tests for ArgoCD API client
# ABOUTME: Tests against live ArgoCD instance (requires ARGOCD_URL and ARGOCD_TOKEN)

import pytest

from argocd_mcp.utils.client import ArgocdClient


@pytest.mark.integration
class TestArgocdClientIntegration:
    """Integration tests for ArgoCD client."""

    async def test_list_applications(self, live_argocd_client: ArgocdClient | None):
        """Test listing applications from live ArgoCD."""
        if live_argocd_client is None:
            pytest.skip("No ArgoCD connection configured")

        apps = await live_argocd_client.list_applications()

        # Should return a list (may be empty)
        assert isinstance(apps, list)

    async def test_list_clusters(self, live_argocd_client: ArgocdClient | None):
        """Test listing clusters from live ArgoCD."""
        if live_argocd_client is None:
            pytest.skip("No ArgoCD connection configured")

        clusters = await live_argocd_client.list_clusters()

        # Should have at least in-cluster
        assert isinstance(clusters, list)
        assert len(clusters) >= 1

    async def test_list_projects(self, live_argocd_client: ArgocdClient | None):
        """Test listing projects from live ArgoCD."""
        if live_argocd_client is None:
            pytest.skip("No ArgoCD connection configured")

        projects = await live_argocd_client.list_projects()

        # Should have at least default project
        assert isinstance(projects, list)
        assert len(projects) >= 1

    async def test_get_settings(self, live_argocd_client: ArgocdClient | None):
        """Test getting ArgoCD settings."""
        if live_argocd_client is None:
            pytest.skip("No ArgoCD connection configured")

        settings = await live_argocd_client.get_settings()

        assert isinstance(settings, dict)
