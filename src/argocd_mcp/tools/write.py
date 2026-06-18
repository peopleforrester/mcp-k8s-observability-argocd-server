# ABOUTME: Tier-2 write tool handlers for the ArgoCD MCP server
# ABOUTME: Require MCP_READ_ONLY=false; dry-run by default

"""Tier-2 (write) MCP tool handlers.

These tools mutate cluster state but never delete or prune resources. They are
gated by the read-only switch and default to dry-run mode where applicable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import Context

from argocd_mcp.tools._safety import check_destination_cluster_allowed
from argocd_mcp.tools.params import (
    RefreshApplicationParams,
    RollbackApplicationParams,
    SyncApplicationParams,
    TerminateSyncParams,
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
    from argocd_mcp.server import (  # noqa: PLC0415
        get_audit_logger,
        get_client,
        get_safety_guard,
    )

    return get_client, get_safety_guard, get_audit_logger


async def sync_application(params: SyncApplicationParams, ctx: MCPContext) -> str:
    """
    Synchronize application with Git repository (non-destructive).

    By default runs in dry-run mode showing what would change.
    Set dry_run=false to apply changes. This tool NEVER prunes resources —
    for sync-with-prune (which deletes cluster resources missing from Git),
    use the Tier-3 `sync_application_with_prune` tool, which requires
    explicit confirmation.
    """
    get_client, get_safety_guard, get_audit_logger = _deps()
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_write_operation("sync_application")
    if blocked:
        get_audit_logger().log_blocked("sync_application", params.name, blocked.reason)
        return blocked.format_message()

    client = get_client(params.instance)
    cluster_block = await check_destination_cluster_allowed(
        client=client,
        app_name=params.name,
        operation="sync_application",
        safety_guard=get_safety_guard(),
        audit_logger=get_audit_logger(),
    )
    if cluster_block is not None:
        return cluster_block

    try:
        mode = "[DRY-RUN] " if params.dry_run else ""
        await ctx.report_progress(0, 2, f"{mode}Initiating sync for {params.name}")

        await client.sync_application(
            name=params.name,
            dry_run=params.dry_run,
            prune=False,
            force=params.force,
            revision=params.revision,
        )

        await ctx.report_progress(2, 2, "Sync initiated")

        if params.dry_run:
            get_audit_logger().log_write("sync_application", params.name, "dry_run")
            return (
                f"Dry-run sync complete for '{params.name}'\n\n"
                f"Operation would affect resources. To apply:\n"
                f"  sync_application(name='{params.name}', dry_run=false)"
            )
        get_audit_logger().log_write(
            "sync_application",
            params.name,
            "initiated",
            {"force": params.force},
        )
        return (
            f"Sync initiated for '{params.name}'\n"
            f"Revision: {params.revision or 'HEAD'}\n\n"
            f"Use get_application_status to monitor progress."
        )

    except ArgocdError as e:
        get_audit_logger().log_error("sync_application", params.name, str(e))
        return str(e)


async def refresh_application(params: RefreshApplicationParams, ctx: MCPContext) -> str:
    """
    Force manifest refresh from Git.

    Triggers ArgoCD to re-fetch manifests from the Git repository.
    Use hard=true to invalidate cache and force full refresh.
    """
    get_client, get_safety_guard, get_audit_logger = _deps()
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_write_operation("refresh_application")
    if blocked:
        get_audit_logger().log_blocked("refresh_application", params.name, blocked.reason)
        return blocked.format_message()

    client = get_client(params.instance)
    cluster_block = await check_destination_cluster_allowed(
        client=client,
        app_name=params.name,
        operation="refresh_application",
        safety_guard=get_safety_guard(),
        audit_logger=get_audit_logger(),
    )
    if cluster_block is not None:
        return cluster_block

    try:
        refresh_type = "hard" if params.hard else "normal"
        await ctx.report_progress(0, 1, f"Triggering {refresh_type} refresh")

        app = await client.refresh_application(params.name, params.hard)

        get_audit_logger().log_write(
            "refresh_application", params.name, "success", {"hard": params.hard}
        )

        return (
            f"Refresh triggered for '{params.name}' ({refresh_type})\n"
            f"Current status: health={app.health_status}, sync={app.sync_status}"
        )

    except ArgocdError as e:
        get_audit_logger().log_error("refresh_application", params.name, str(e))
        return str(e)


async def rollback_application(params: RollbackApplicationParams, ctx: MCPContext) -> str:
    """
    Rollback application to a previous deployment revision.

    Use get_application_history to find revision IDs, then rollback
    to a known-good state. Defaults to dry-run mode for safety.
    """
    get_client, get_safety_guard, get_audit_logger = _deps()
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_write_operation("rollback_application")
    if blocked:
        get_audit_logger().log_blocked("rollback_application", params.name, blocked.reason)
        return blocked.format_message()

    client = get_client(params.instance)
    cluster_block = await check_destination_cluster_allowed(
        client=client,
        app_name=params.name,
        operation="rollback_application",
        safety_guard=get_safety_guard(),
        audit_logger=get_audit_logger(),
    )
    if cluster_block is not None:
        return cluster_block

    try:
        mode = "[DRY-RUN] " if params.dry_run else ""
        await ctx.report_progress(0, 1, f"{mode}Rolling back {params.name}")

        await client.rollback_application(
            name=params.name, revision_id=params.revision_id, dry_run=params.dry_run
        )

        if params.dry_run:
            get_audit_logger().log_write("rollback_application", params.name, "dry_run")
            return (
                f"Dry-run rollback complete for '{params.name}' "
                f"to revision {params.revision_id}\n\n"
                f"To apply the rollback:\n"
                f"  rollback_application(name='{params.name}', "
                f"revision_id={params.revision_id}, dry_run=false)"
            )
        get_audit_logger().log_write(
            "rollback_application",
            params.name,
            "initiated",
            {"revision_id": params.revision_id},
        )
        return (
            f"Rollback initiated for '{params.name}' to revision {params.revision_id}\n\n"
            f"Use get_application_status to monitor progress."
        )

    except ArgocdError as e:
        get_audit_logger().log_error("rollback_application", params.name, str(e))
        return str(e)


async def terminate_sync(params: TerminateSyncParams, ctx: MCPContext) -> str:
    """
    Terminate an ongoing sync operation.

    Stops a sync that's currently in progress. Useful when a sync
    is stuck, taking too long, or was triggered by mistake.
    """
    get_client, get_safety_guard, get_audit_logger = _deps()
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_write_operation("terminate_sync")
    if blocked:
        get_audit_logger().log_blocked("terminate_sync", params.name, blocked.reason)
        return blocked.format_message()

    client = get_client(params.instance)
    cluster_block = await check_destination_cluster_allowed(
        client=client,
        app_name=params.name,
        operation="terminate_sync",
        safety_guard=get_safety_guard(),
        audit_logger=get_audit_logger(),
    )
    if cluster_block is not None:
        return cluster_block

    try:
        await ctx.report_progress(0, 1, f"Terminating sync for {params.name}")

        await client.terminate_sync(params.name)

        get_audit_logger().log_write("terminate_sync", params.name, "terminated")

        return (
            f"Sync operation terminated for '{params.name}'\n\n"
            f"Use get_application_status to check current state."
        )

    except ArgocdError as e:
        get_audit_logger().log_error("terminate_sync", params.name, str(e))
        return str(e)


def register_write_tools(mcp: FastMCP) -> None:
    """Register all Tier-2 write tools with the given FastMCP instance."""
    mcp.tool()(sync_application)
    mcp.tool()(refresh_application)
    mcp.tool()(rollback_application)
    mcp.tool()(terminate_sync)


__all__ = [
    "refresh_application",
    "register_write_tools",
    "rollback_application",
    "sync_application",
    "terminate_sync",
]
