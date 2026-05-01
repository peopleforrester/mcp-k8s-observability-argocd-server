# ABOUTME: Shared safety helpers used by write and destructive tool handlers
# ABOUTME: Single-cluster enforcement gate, looked up via the app's destination_server

"""Shared safety helpers for tool handlers.

`check_destination_cluster_allowed` enforces single-cluster mode (Layer 4 of
the security model documented in docs/SECURITY.md). It fetches the
application's destination cluster from ArgoCD and asks the SafetyGuard to gate
the operation.

Returns:
    None when the operation is allowed (single-cluster off, or destination is
    the in-cluster URL). A formatted error message when blocked. The caller
    handles the audit log + return.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from argocd_mcp.utils.client import ArgocdError

if TYPE_CHECKING:
    from argocd_mcp.utils.client import ArgocdClient
    from argocd_mcp.utils.logging import AuditLogger
    from argocd_mcp.utils.safety import SafetyGuard


async def check_destination_cluster_allowed(
    *,
    client: ArgocdClient,
    app_name: str,
    operation: str,
    safety_guard: SafetyGuard,
    audit_logger: AuditLogger,
) -> str | None:
    """Gate an operation against the application's destination cluster.

    Always permits when MCP_SINGLE_CLUSTER is false (the default). When true,
    blocks any operation whose target Application points at a destination other
    than the in-cluster server.

    If the application cannot be fetched (e.g. it does not exist), returns None
    so the caller's downstream API call can surface the actual error rather
    than a confusing single-cluster denial. Logs the audit event on block.
    """
    try:
        app = await client.get_application(app_name)
    except ArgocdError:
        return None

    blocked = safety_guard.check_cluster_operation(operation, app.destination_server)
    if blocked is None:
        return None

    audit_logger.log_blocked(operation, app_name, blocked.reason)
    return blocked.format_message()
