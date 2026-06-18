# ABOUTME: Tier-1 read-only tool handlers for the ArgoCD MCP server
# ABOUTME: Handlers import server-level accessors lazily to avoid circular imports

"""Tier-1 (read-only) MCP tool handlers.

All tools in this module are safe to call without any configuration changes:
they never mutate cluster state. They are rate-limited only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import Context

from argocd_mcp.tools.params import (
    DiagnoseSyncFailureParams,
    GetApplicationDiffParams,
    GetApplicationHistoryParams,
    GetApplicationLogsParams,
    GetApplicationParams,
    GetApplicationStatusParams,
    ListApplicationsParams,
    ListClustersParams,
    ListProjectsParams,
)
from argocd_mcp.utils.client import ArgocdError
from argocd_mcp.utils.logging import set_correlation_id

# MCPContext is aliased at runtime (not under TYPE_CHECKING) because the MCP SDK
# resolves tool parameter annotations via get_type_hints() at registration time;
# if the name is missing from module globals, registration raises
# InvalidSignature. server.py applies the same pattern.
MCPContext = Context[Any, Any]

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcp.server.fastmcp import FastMCP

    from argocd_mcp.utils.client import ArgocdClient
    from argocd_mcp.utils.logging import AuditLogger
    from argocd_mcp.utils.safety import SafetyGuard

    GetClient = Callable[[str], ArgocdClient]
    GetSafetyGuard = Callable[[], SafetyGuard]
    GetAuditLogger = Callable[[], AuditLogger]


def _deps() -> tuple[GetClient, GetSafetyGuard, GetAuditLogger]:
    """Lazy resolve server-level accessors to avoid a circular import."""
    # Intentional local import: server.py imports this module during its own load,
    # so a top-level import would deadlock. Resolved at first call, well after
    # both modules have finished loading.
    from argocd_mcp.server import (  # noqa: PLC0415
        get_audit_logger,
        get_client,
        get_safety_guard,
    )

    return get_client, get_safety_guard, get_audit_logger


async def list_applications(params: ListApplicationsParams, ctx: MCPContext) -> str:
    """
    List ArgoCD applications with optional filtering.

    Returns applications matching the specified filters. Use this to get
    an overview of applications in a project or find unhealthy/out-of-sync apps.
    """
    get_client, get_safety_guard, get_audit_logger = _deps()
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_read_operation("list_applications")
    if blocked:
        get_audit_logger().log_blocked("list_applications", "all", blocked.reason)
        return blocked.format_message()

    try:
        client = get_client(params.instance)
        apps = await client.list_applications(project=params.project)

        if params.health_status:
            apps = [a for a in apps if a.health_status == params.health_status]
        if params.sync_status:
            apps = [a for a in apps if a.sync_status == params.sync_status]

        get_audit_logger().log_read("list_applications", f"project={params.project}")

        if not apps:
            return "No applications found matching the specified filters."

        lines = [f"Found {len(apps)} application(s):", ""]
        for app in apps:
            health_marker = "[OK]" if app.health_status == "Healthy" else "[!]"
            sync_marker = "[OK]" if app.sync_status == "Synced" else "[!]"
            lines.append(
                f"- {app.name} [{app.project}] "
                f"health={app.health_status} {health_marker} "
                f"sync={app.sync_status} {sync_marker} "
                f"dest={app.destination_namespace}@{app.destination_server[:30]}..."
            )

        return "\n".join(lines)

    except ArgocdError as e:
        get_audit_logger().log_error("list_applications", "all", str(e))
        return str(e)


async def get_application(params: GetApplicationParams, ctx: MCPContext) -> str:
    """
    Get detailed information about a specific ArgoCD application.

    Returns comprehensive application details including source repo, sync status,
    health status, deployment destination, and any conditions or errors.
    """
    get_client, get_safety_guard, get_audit_logger = _deps()
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_read_operation("get_application")
    if blocked:
        get_audit_logger().log_blocked("get_application", params.name, blocked.reason)
        return blocked.format_message()

    try:
        client = get_client(params.instance)
        app = await client.get_application(params.name)

        get_audit_logger().log_read("get_application", params.name)

        lines = [
            f"Application: {app.name}",
            f"Project: {app.project}",
            f"Namespace: {app.namespace}",
            "",
            "Source:",
            f"  Repository: {app.repo_url}",
            f"  Path: {app.path}",
            f"  Target Revision: {app.target_revision}",
            "",
            "Destination:",
            f"  Server: {app.destination_server}",
            f"  Namespace: {app.destination_namespace}",
            "",
            "Status:",
            f"  Sync: {app.sync_status}",
            f"  Health: {app.health_status}",
        ]

        if app.operation_state:
            op = app.operation_state
            lines.extend(
                [
                    "",
                    "Last Operation:",
                    f"  Phase: {op.get('phase', 'Unknown')}",
                    f"  Message: {op.get('message', 'N/A')}",
                ]
            )

        if app.conditions:
            lines.extend(["", "Conditions:"])
            for cond in app.conditions:
                lines.append(f"  - [{cond.get('type')}] {cond.get('message', 'N/A')}")

        return "\n".join(lines)

    except ArgocdError as e:
        get_audit_logger().log_error("get_application", params.name, str(e))
        return str(e)


async def get_application_status(params: GetApplicationStatusParams, ctx: MCPContext) -> str:
    """
    Get condensed health and sync status for quick checks.

    Use this for a quick status check when you don't need full application details.
    """
    get_client, get_safety_guard, get_audit_logger = _deps()
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_read_operation("get_application_status")
    if blocked:
        get_audit_logger().log_blocked("get_application_status", params.name, blocked.reason)
        return blocked.format_message()

    try:
        client = get_client(params.instance)
        app = await client.get_application(params.name)

        get_audit_logger().log_read("get_application_status", params.name)

        health_marker = "[OK]" if app.health_status == "Healthy" else "[!]"
        sync_marker = "[OK]" if app.sync_status == "Synced" else "[!]"

        return (
            f"Application: {app.name}\n"
            f"Health: {app.health_status} {health_marker}\n"
            f"Sync: {app.sync_status} {sync_marker}"
        )

    except ArgocdError as e:
        get_audit_logger().log_error("get_application_status", params.name, str(e))
        return str(e)


async def get_application_diff(params: GetApplicationDiffParams, ctx: MCPContext) -> str:
    """
    Preview what would change on sync (dry-run diff).

    Shows resources that would be created, updated, or deleted if sync
    were triggered. Use this before syncing to understand the impact.
    """
    get_client, get_safety_guard, get_audit_logger = _deps()
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_read_operation("get_application_diff")
    if blocked:
        get_audit_logger().log_blocked("get_application_diff", params.name, blocked.reason)
        return blocked.format_message()

    await ctx.report_progress(0, 2, "Fetching managed resources")

    try:
        client = get_client(params.instance)
        diff_data = await client.get_application_diff(params.name, params.revision)

        get_audit_logger().log_read("get_application_diff", params.name)

        await ctx.report_progress(1, 2, "Analyzing differences")

        resources = diff_data.get("items", [])
        if not resources:
            return f"No managed resources found for application '{params.name}'"

        live_only: list[dict[str, Any]] = []
        target_only: list[dict[str, Any]] = []
        modified: list[dict[str, Any]] = []
        synced: list[dict[str, Any]] = []

        for res in resources:
            live = res.get("liveState")
            target = res.get("targetState")

            if live and not target:
                live_only.append(res)
            elif target and not live:
                target_only.append(res)
            elif live != target:
                modified.append(res)
            else:
                synced.append(res)

        await ctx.report_progress(2, 2, "Complete")

        lines = [f"Diff for application '{params.name}':", ""]

        if target_only:
            lines.append(f"Resources to CREATE ({len(target_only)}):")
            for r in target_only:
                lines.append(f"  + {r.get('kind', 'Unknown')}/{r.get('name', 'unknown')}")
            lines.append("")

        if modified:
            lines.append(f"Resources to UPDATE ({len(modified)}):")
            for r in modified:
                lines.append(f"  ~ {r.get('kind', 'Unknown')}/{r.get('name', 'unknown')}")
            lines.append("")

        if live_only:
            lines.append(f"Resources to DELETE (with prune) ({len(live_only)}):")
            for r in live_only:
                lines.append(f"  - {r.get('kind', 'Unknown')}/{r.get('name', 'unknown')}")
            lines.append("")

        lines.append(f"Resources in sync: {len(synced)}")

        if not target_only and not modified and not live_only:
            lines.append("\nApplication is fully synced. No changes needed.")

        return "\n".join(lines)

    except ArgocdError as e:
        get_audit_logger().log_error("get_application_diff", params.name, str(e))
        return str(e)


async def get_application_history(params: GetApplicationHistoryParams, ctx: MCPContext) -> str:
    """
    View deployment history with commit info and timestamps.

    Shows recent deployments including revision, timestamp, and initiator.
    Useful for understanding recent changes and finding rollback targets.
    """
    get_client, get_safety_guard, get_audit_logger = _deps()
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_read_operation("get_application_history")
    if blocked:
        get_audit_logger().log_blocked("get_application_history", params.name, blocked.reason)
        return blocked.format_message()

    try:
        client = get_client(params.instance)
        history = await client.get_application_history(params.name, params.limit)

        get_audit_logger().log_read("get_application_history", params.name)

        if not history:
            return f"No deployment history found for application '{params.name}'"

        lines = [f"Deployment history for '{params.name}' (last {len(history)} entries):", ""]
        for i, entry in enumerate(reversed(history), 1):
            revision = entry.get("revision", "unknown")[:8]
            deployed_at = entry.get("deployedAt", "unknown")
            initiator = entry.get("initiatedBy", {}).get("username", "unknown")
            lines.append(f"{i}. [{revision}] at {deployed_at} by {initiator}")

        return "\n".join(lines)

    except ArgocdError as e:
        get_audit_logger().log_error("get_application_history", params.name, str(e))
        return str(e)


async def diagnose_sync_failure(params: DiagnoseSyncFailureParams, ctx: MCPContext) -> str:
    """
    Diagnose why an application sync failed.

    Aggregates sync status, resource conditions, events, and recent logs
    to identify root cause. Provides actionable suggestions for resolution.
    """
    get_client, get_safety_guard, get_audit_logger = _deps()
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_read_operation("diagnose_sync_failure")
    if blocked:
        get_audit_logger().log_blocked("diagnose_sync_failure", params.name, blocked.reason)
        return blocked.format_message()

    try:
        client = get_client(params.instance)

        await ctx.report_progress(0, 4, "Fetching application status")
        app = await client.get_application(params.name)

        await ctx.report_progress(1, 4, "Gathering resource conditions")
        tree_data = await client.get_resource_tree(params.name)

        await ctx.report_progress(2, 4, "Collecting events")
        events = await client.get_application_events(params.name)

        await ctx.report_progress(3, 4, "Analyzing diagnosis")

        get_audit_logger().log_read("diagnose_sync_failure", params.name)

        issues: list[str] = []
        suggestions: list[str] = []

        if app.sync_status == "OutOfSync":
            issues.append(f"Application is out of sync (revision: {app.target_revision})")
            suggestions.append("Run get_application_diff to see pending changes")

        if app.health_status == "Degraded":
            issues.append("Application health is Degraded")
        elif app.health_status == "Progressing":
            issues.append("Application is still progressing")
            suggestions.append("Wait for operations to complete or check for stuck resources")
        elif app.health_status == "Missing":
            issues.append("Application resources are missing from cluster")
            suggestions.append("Verify destination cluster connectivity and namespace exists")

        if app.operation_state:
            op_phase = app.operation_state.get("phase", "")
            op_message = app.operation_state.get("message", "")
            if op_phase == "Failed":
                issues.append(f"Last operation failed: {op_message}")
            elif op_phase == "Running":
                issues.append("Sync operation currently running")

        if app.conditions:
            for cond in app.conditions:
                cond_type = cond.get("type", "")
                cond_msg = cond.get("message", "")
                if cond_type in ("ComparisonError", "InvalidSpecError", "SyncError"):
                    issues.append(f"[{cond_type}] {cond_msg}")

        # Heuristic substring matching on Kubernetes event messages. The
        # patterns below are stable across recent k8s versions but localized
        # or upgraded messages may slip past — treat this as best-effort
        # triage, not exhaustive root-cause analysis. Each branch has a
        # corresponding test in tests/unit/test_server.py
        # (TestDiagnoseSyncFailureTool); when adding a new branch, add a
        # matching test so future renames are caught.
        for event in events[:20]:
            msg = event.get("message", "")
            reason = event.get("reason", "")

            if "ImagePullBackOff" in msg or "ErrImagePull" in msg:
                issues.append(f"Image pull failed: {msg[:100]}")
                suggestions.append("Verify image exists and registry credentials are configured")
            elif "CrashLoopBackOff" in msg:
                issues.append(f"Container crashing: {msg[:100]}")
                suggestions.append("Check pod logs for application startup errors")
            elif "Forbidden" in msg or "unauthorized" in msg.lower():
                issues.append(f"RBAC permission denied: {msg[:100]}")
                suggestions.append("Review ServiceAccount permissions in destination cluster")
            elif "OOMKilled" in msg:
                issues.append("Container killed due to memory limit")
                suggestions.append("Increase memory limits or optimize application memory usage")
            elif "PodUnschedulable" in reason or "Insufficient" in msg:
                issues.append(f"Scheduling failed: {msg[:100]}")
                suggestions.append("Check cluster capacity and node availability")

        nodes = tree_data.get("nodes", [])
        unhealthy_resources = [
            n for n in nodes if n.get("health", {}).get("status") in ("Degraded", "Missing")
        ]
        if unhealthy_resources:
            issues.append(f"Found {len(unhealthy_resources)} unhealthy resources in resource tree")
            for r in unhealthy_resources[:5]:
                issues.append(
                    f"  - {r.get('kind', 'Unknown')}/{r.get('name', 'unknown')}: "
                    f"{r.get('health', {}).get('message', 'N/A')}"
                )

        await ctx.report_progress(4, 4, "Diagnosis complete")

        lines = [f"Diagnosis for '{params.name}':", ""]

        if not issues:
            lines.append("No issues detected. Application appears healthy.")
            lines.append(f"Health: {app.health_status}, Sync: {app.sync_status}")
        else:
            lines.append(f"Found {len(issues)} issue(s):")
            for issue in issues:
                lines.append(f"  - {issue}")

        if suggestions:
            lines.extend(["", "Suggestions:"])
            for suggestion in list(set(suggestions)):
                lines.append(f"  - {suggestion}")

        return "\n".join(lines)

    except ArgocdError as e:
        get_audit_logger().log_error("diagnose_sync_failure", params.name, str(e))
        return str(e)


async def get_application_logs(params: GetApplicationLogsParams, ctx: MCPContext) -> str:
    """
    Get pod logs for an application.

    Retrieves logs from pods managed by the application. Useful for
    debugging application issues, checking startup errors, or
    monitoring runtime behavior.
    """
    get_client, get_safety_guard, get_audit_logger = _deps()
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_read_operation("get_application_logs")
    if blocked:
        get_audit_logger().log_blocked("get_application_logs", params.name, blocked.reason)
        return blocked.format_message()

    try:
        client = get_client(params.instance)

        await ctx.report_progress(0, 1, f"Fetching logs for {params.name}")

        logs = await client.get_logs(
            name=params.name,
            pod_name=params.pod_name,
            container=params.container,
            tail_lines=params.tail_lines,
            since_seconds=params.since_seconds,
        )

        get_audit_logger().log_read("get_application_logs", params.name)

        await ctx.report_progress(1, 1, "Complete")

        if not logs:
            return f"No logs found for application '{params.name}'"

        header = f"Logs for '{params.name}'"
        if params.pod_name:
            header += f" (pod: {params.pod_name})"
        if params.container:
            header += f" (container: {params.container})"
        header += f" (last {params.tail_lines} lines):"

        return f"{header}\n\n{logs}"

    except ArgocdError as e:
        get_audit_logger().log_error("get_application_logs", params.name, str(e))
        return str(e)


async def list_clusters(params: ListClustersParams, ctx: MCPContext) -> str:
    """
    List registered Kubernetes clusters with health status.

    Shows all clusters registered with ArgoCD and their connection status.
    """
    get_client, get_safety_guard, get_audit_logger = _deps()
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_read_operation("list_clusters")
    if blocked:
        get_audit_logger().log_blocked("list_clusters", "all", blocked.reason)
        return blocked.format_message()

    try:
        client = get_client(params.instance)
        clusters = await client.list_clusters()

        get_audit_logger().log_read("list_clusters", "all")

        if not clusters:
            return "No clusters registered"

        lines = [f"Found {len(clusters)} cluster(s):", ""]
        for cluster in clusters:
            name = cluster.get("name", "unknown")
            server = cluster.get("server", "unknown")
            status = cluster.get("connectionState", {}).get("status", "Unknown")
            lines.append(f"- {name}: {server[:50]}... [{status}]")

        return "\n".join(lines)

    except ArgocdError as e:
        get_audit_logger().log_error("list_clusters", "all", str(e))
        return str(e)


async def list_projects(params: ListProjectsParams, ctx: MCPContext) -> str:
    """
    List ArgoCD projects.

    Shows all projects which organize and control application access.
    """
    get_client, get_safety_guard, get_audit_logger = _deps()
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_read_operation("list_projects")
    if blocked:
        get_audit_logger().log_blocked("list_projects", "all", blocked.reason)
        return blocked.format_message()

    try:
        client = get_client(params.instance)
        projects = await client.list_projects()

        get_audit_logger().log_read("list_projects", "all")

        if not projects:
            return "No projects found"

        lines = [f"Found {len(projects)} project(s):", ""]
        for proj in projects:
            name = proj.get("metadata", {}).get("name", "unknown")
            description = proj.get("spec", {}).get("description", "No description")
            lines.append(f"- {name}: {description[:60]}")

        return "\n".join(lines)

    except ArgocdError as e:
        get_audit_logger().log_error("list_projects", "all", str(e))
        return str(e)


def register_read_tools(mcp: FastMCP) -> None:
    """Register all Tier-1 read tools with the given FastMCP instance."""
    mcp.tool()(list_applications)
    mcp.tool()(get_application)
    mcp.tool()(get_application_status)
    mcp.tool()(get_application_diff)
    mcp.tool()(get_application_history)
    mcp.tool()(diagnose_sync_failure)
    mcp.tool()(get_application_logs)
    mcp.tool()(list_clusters)
    mcp.tool()(list_projects)


__all__ = [
    "diagnose_sync_failure",
    "get_application",
    "get_application_diff",
    "get_application_history",
    "get_application_logs",
    "get_application_status",
    "list_applications",
    "list_clusters",
    "list_projects",
    "register_read_tools",
]
