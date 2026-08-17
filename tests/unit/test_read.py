# ABOUTME: Unit tests for Tier-1 read-only tool handlers
# ABOUTME: Covers listing, status, diff, history, diagnosis, logs, clusters, projects

"""Unit tests for the Tier-1 read handlers in argocd_mcp.tools.read."""

from __future__ import annotations

from typing import Any

import pytest

from argocd_mcp.utils.client import Application, ArgocdError


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
