# ABOUTME: Tier-3 destructive tool handlers for the ArgoCD MCP server
# ABOUTME: Require two-parameter confirmation (confirm + confirm_name) on live runs

"""Tier-3 (destructive) MCP tool handlers.

These tools permanently delete or prune resources and require the full safety
stack: MCP_READ_ONLY=false, MCP_DISABLE_DESTRUCTIVE=false, confirm=true, and
confirm_name matching the target name exactly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import Context

from argocd_mcp.tools._safety import check_destination_cluster_allowed
from argocd_mcp.tools.params import (
    DeleteApplicationParams,
    SyncApplicationWithPruneParams,
)
from argocd_mcp.utils.client import ArgocdError
from argocd_mcp.utils.logging import set_correlation_id
from argocd_mcp.utils.safety import ConfirmationRequired, OperationBlocked

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


async def delete_application(params: DeleteApplicationParams, ctx: MCPContext) -> str:
    """
    Delete an ArgoCD application (DESTRUCTIVE).

    Requires explicit confirmation. Set confirm=true AND confirm_name
    matching the application name to proceed. With cascade=true (default),
    also deletes Kubernetes resources managed by this application.
    """
    get_client, get_safety_guard, get_audit_logger = _deps()
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_destructive_operation(
        "delete_application",
        params.name,
        confirmed=params.confirm,
        confirm_name=params.confirm_name,
    )

    if blocked:
        if isinstance(blocked, ConfirmationRequired):
            try:
                client = get_client(params.instance)
                app = await client.get_application(params.name)
                blocked.details = {
                    "namespace": app.destination_namespace,
                    "cluster": app.destination_server[:50],
                    "cascade": str(params.cascade),
                    "effect": "DELETE cluster resources"
                    if params.cascade
                    else "ORPHAN cluster resources",
                }
            except ArgocdError:
                pass
            get_audit_logger().log_blocked(
                "delete_application", params.name, "confirmation required"
            )
            return blocked.format_message()
        return blocked.format_message()

    client = get_client(params.instance)
    cluster_block = await check_destination_cluster_allowed(
        client=client,
        app_name=params.name,
        operation="delete_application",
        safety_guard=get_safety_guard(),
        audit_logger=get_audit_logger(),
    )
    if cluster_block is not None:
        return cluster_block

    try:
        await ctx.report_progress(0, 1, f"Deleting application {params.name}")

        await client.delete_application(params.name, params.cascade)

        get_audit_logger().log_write(
            "delete_application", params.name, "deleted", {"cascade": params.cascade}
        )

        return f"Application '{params.name}' deleted successfully.\nCascade: {params.cascade}"

    except ArgocdError as e:
        get_audit_logger().log_error("delete_application", params.name, str(e))
        return str(e)


async def sync_application_with_prune(
    params: SyncApplicationWithPruneParams, ctx: MCPContext
) -> str:
    """
    Synchronize application and PRUNE cluster resources missing from Git (DESTRUCTIVE).

    This always passes prune=true to the ArgoCD API. Resources present in the
    cluster but absent from the desired Git state will be DELETED on a live run.

    - dry_run=true (default): preview which resources would be pruned; no confirmation needed.
    - dry_run=false: requires confirm=true AND confirm_name matching the application name.

    Requires MCP_READ_ONLY=false and MCP_DISABLE_DESTRUCTIVE=false.
    """
    get_client, get_safety_guard, get_audit_logger = _deps()
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    if params.dry_run:
        blocked = get_safety_guard().check_write_operation("sync_application_with_prune")
        if blocked:
            get_audit_logger().log_blocked(
                "sync_application_with_prune", params.name, blocked.reason
            )
            return blocked.format_message()
    else:
        destructive = get_safety_guard().check_destructive_operation(
            "sync_with_prune",
            params.name,
            confirmed=params.confirm,
            confirm_name=params.confirm_name,
        )
        if destructive:
            get_audit_logger().log_blocked(
                "sync_application_with_prune",
                params.name,
                destructive.reason
                if isinstance(destructive, OperationBlocked)
                else "confirmation required",
            )
            return destructive.format_message()

    client = get_client(params.instance)
    cluster_block = await check_destination_cluster_allowed(
        client=client,
        app_name=params.name,
        operation="sync_application_with_prune",
        safety_guard=get_safety_guard(),
        audit_logger=get_audit_logger(),
    )
    if cluster_block is not None:
        return cluster_block

    try:
        mode = "[DRY-RUN] " if params.dry_run else ""
        await ctx.report_progress(0, 2, f"{mode}Initiating sync-with-prune for {params.name}")

        await client.sync_application(
            name=params.name,
            dry_run=params.dry_run,
            prune=True,
            force=params.force,
            revision=params.revision,
        )

        await ctx.report_progress(2, 2, "Sync initiated")

        if params.dry_run:
            get_audit_logger().log_write("sync_application_with_prune", params.name, "dry_run")
            return (
                f"Dry-run sync-with-prune complete for '{params.name}'\n\n"
                f"Review the plan carefully. To apply (will DELETE resources not in Git):\n"
                f"  sync_application_with_prune("
                f"name='{params.name}', dry_run=false, "
                f"confirm=true, confirm_name='{params.name}')"
            )
        get_audit_logger().log_write(
            "sync_application_with_prune",
            params.name,
            "initiated",
            {"force": params.force, "prune": True},
        )
        return (
            f"Sync-with-prune initiated for '{params.name}'\n"
            f"Revision: {params.revision or 'HEAD'}\n"
            f"Prune: true\n\n"
            f"Use get_application_status to monitor progress."
        )

    except ArgocdError as e:
        get_audit_logger().log_error("sync_application_with_prune", params.name, str(e))
        return str(e)


def register_destructive_tools(mcp: FastMCP) -> None:
    """Register all Tier-3 destructive tools with the given FastMCP instance."""
    mcp.tool()(delete_application)
    mcp.tool()(sync_application_with_prune)


__all__ = [
    "delete_application",
    "register_destructive_tools",
    "sync_application_with_prune",
]
