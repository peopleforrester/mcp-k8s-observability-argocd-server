# ABOUTME: FastMCP server initialization and main entry point
# ABOUTME: Configures MCP server with tools, resources, and lifecycle management

"""ArgoCD MCP Server - Safety-first GitOps operations."""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog
from mcp.server.fastmcp import Context, FastMCP

from argocd_mcp.config import ServerSettings, load_settings

# MCP resource handlers re-exported for backwards compatibility with existing test imports.
from argocd_mcp.resources.applications import (
    get_instances_resource,
    get_security_resource,
    register_resources,
)

# Tier-3 handlers re-exported for backwards compatibility with existing test imports.
from argocd_mcp.tools.destructive import (
    delete_application,
    register_destructive_tools,
    sync_application_with_prune,
)

# Param classes re-exported for backwards compatibility with existing test imports.
from argocd_mcp.tools.params import (
    DeleteApplicationParams,
    DiagnoseSyncFailureParams,
    GetApplicationDiffParams,
    GetApplicationHistoryParams,
    GetApplicationLogsParams,
    GetApplicationParams,
    GetApplicationStatusParams,
    ListApplicationsParams,
    ListClustersParams,
    ListProjectsParams,
    RefreshApplicationParams,
    RollbackApplicationParams,
    SyncApplicationParams,
    SyncApplicationWithPruneParams,
    TerminateSyncParams,
)

# Tier-1 handlers re-exported for backwards compatibility with existing test imports.
from argocd_mcp.tools.read import (
    diagnose_sync_failure,
    get_application,
    get_application_diff,
    get_application_history,
    get_application_logs,
    get_application_status,
    list_applications,
    list_clusters,
    list_projects,
    register_read_tools,
)

# Tier-2 handlers re-exported for backwards compatibility with existing test imports.
from argocd_mcp.tools.write import (
    refresh_application,
    register_write_tools,
    rollback_application,
    sync_application,
    terminate_sync,
)
from argocd_mcp.utils.client import ArgocdClient
from argocd_mcp.utils.logging import AuditLogger, configure_logging
from argocd_mcp.utils.safety import SafetyGuard

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

MCPContext = Context[Any, Any]
logger = structlog.get_logger(__name__)

# Public re-exports — kept stable so test modules can keep importing from
# argocd_mcp.server. Declaring them in __all__ also tells ruff these are
# intentional re-exports (prevents F401 from auto-removing them).
__all__ = [
    "DeleteApplicationParams",
    "DiagnoseSyncFailureParams",
    "GetApplicationDiffParams",
    "GetApplicationHistoryParams",
    "GetApplicationLogsParams",
    "GetApplicationParams",
    "GetApplicationStatusParams",
    "ListApplicationsParams",
    "ListClustersParams",
    "ListProjectsParams",
    "RefreshApplicationParams",
    "RollbackApplicationParams",
    "ServerContext",
    "SyncApplicationParams",
    "SyncApplicationWithPruneParams",
    "TerminateSyncParams",
    "delete_application",
    "diagnose_sync_failure",
    "get_application",
    "get_application_diff",
    "get_application_history",
    "get_application_logs",
    "get_application_status",
    "get_instances_resource",
    "get_security_resource",
    "list_applications",
    "list_clusters",
    "list_projects",
    "main",
    "mcp",
    "refresh_application",
    "rollback_application",
    "sync_application",
    "sync_application_with_prune",
    "terminate_sync",
]

@dataclass(slots=True)
class ServerContext:
    """Bundle of long-lived server state populated at lifespan startup.

    Single source of truth for handlers and resources, replacing the prior set
    of four module-level globals. The dataclass is intentionally NOT frozen:
    `clients` is a mutable dict so tests and lifespan teardown can repopulate
    or clear it without rebuilding the entire context.
    """

    settings: ServerSettings
    safety_guard: SafetyGuard
    audit_logger: AuditLogger
    clients: dict[str, ArgocdClient] = field(default_factory=dict)


# Single module-level handle, populated in lifespan() and read via the get_*
# accessors below. Tests inject mocks by replacing _context wholesale.
_context: ServerContext | None = None


@asynccontextmanager
async def lifespan(_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Manage server lifecycle: load config, connect clients, cleanup on shutdown."""
    global _context

    logger.info("Starting ArgoCD MCP Server")

    settings = load_settings()
    configure_logging(level=settings.log_level)
    ctx = ServerContext(
        settings=settings,
        safety_guard=SafetyGuard(settings.security),
        audit_logger=AuditLogger(settings.security.audit_log),
    )

    for instance in settings.all_instances:
        client = ArgocdClient(instance=instance, mask_secrets=settings.security.mask_secrets)
        await client.__aenter__()
        ctx.clients[instance.name] = client
        logger.info("Connected to ArgoCD instance", instance=instance.name, url=instance.url)

    _context = ctx
    yield {"settings": ctx.settings, "clients": ctx.clients}

    for name, client in ctx.clients.items():
        await client.__aexit__(None, None, None)
        logger.info("Disconnected from ArgoCD instance", instance=name)

    ctx.clients.clear()
    _context = None
    logger.info("ArgoCD MCP Server stopped")


mcp = FastMCP("argocd-mcp", lifespan=lifespan)
register_read_tools(mcp)
register_write_tools(mcp)
register_destructive_tools(mcp)
register_resources(mcp)


def get_context() -> ServerContext:
    """Return the active ServerContext, raising if the server has not started."""
    if _context is None:
        raise RuntimeError("Server not initialized")
    return _context


def get_client(instance: str = "primary") -> ArgocdClient:
    """Get ArgoCD client for specified instance."""
    clients = get_context().clients
    if instance not in clients:
        available = list(clients.keys())
        raise ValueError(f"Unknown instance '{instance}'. Available: {available}")
    return clients[instance]


def get_settings() -> ServerSettings:
    """Get server settings."""
    return get_context().settings


def get_safety_guard() -> SafetyGuard:
    """Get safety guard for permission checking."""
    return get_context().safety_guard


def get_audit_logger() -> AuditLogger:
    """Get audit logger for recording operations."""
    return get_context().audit_logger





# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main() -> None:
    """Run the ArgoCD MCP server."""
    configure_logging(level="INFO")
    logger.info("ArgoCD MCP Server starting")

    try:
        mcp.run()
    except KeyboardInterrupt:
        logger.info("Server interrupted")
        sys.exit(0)
    except Exception as e:
        logger.error("Server error", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
