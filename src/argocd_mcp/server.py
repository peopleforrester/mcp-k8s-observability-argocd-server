# ABOUTME: FastMCP server initialization and main entry point
# ABOUTME: Configures MCP server with tools, resources, and lifecycle management

"""
ArgoCD MCP Server - Safety-first GitOps operations.

=============================================================================
WHAT IS THIS FILE?
=============================================================================

This is the MAIN FILE of the ArgoCD MCP server. It:

1. CREATES the MCP server instance
2. DEFINES all the tools (actions the AI can take)
3. MANAGES the server lifecycle (startup, shutdown)
4. CONNECTS all the components together

When you run 'argocd-mcp', this is the code that executes.

=============================================================================
MCP (MODEL CONTEXT PROTOCOL) ARCHITECTURE
=============================================================================

MCP defines how AI assistants communicate with external tools. The flow:

    ┌──────────┐     MCP Protocol      ┌──────────────┐
    │  Claude  │ ◄─────────────────────►│  MCP Server  │
    │(AI Model)│    (JSON-RPC over      │ (This Code)  │
    └──────────┘     stdio or HTTP)     └──────────────┘
                                               │
                                               ▼
                                        ┌──────────────┐
                                        │   ArgoCD     │
                                        │ (REST API)   │
                                        └──────────────┘

The MCP server exposes:
- TOOLS: Actions like "sync_application", "list_clusters"
- RESOURCES: Data like "argocd://instances", "argocd://security"

Claude discovers available tools, chooses which to use, and calls them.

=============================================================================
FASTMCP FRAMEWORK
=============================================================================

FastMCP is a Python framework for building MCP servers quickly.
It provides:

1. SERVER SETUP: FastMCP("name") creates a server
2. TOOL DECORATOR: @mcp.tool() registers a function as a tool
3. RESOURCE DECORATOR: @mcp.resource() registers a data resource
4. LIFECYCLE MANAGEMENT: Startup/shutdown hooks

Example:
    mcp = FastMCP("myserver")

    @mcp.tool()
    async def my_tool(params: MyParams) -> str:
        return "result"

    mcp.run()  # Start the server

=============================================================================
PROGRESSIVE DISCLOSURE (TOOL TIERS)
=============================================================================

Tools are organized into TIERS based on risk level:

TIER 1: Essential Read Operations (Always Available)
├── list_applications    - List apps with filtering
├── get_application      - Get app details
├── get_application_status - Quick status check
├── get_application_diff - Preview sync changes
├── get_application_history - Deployment history
├── get_application_logs - Get pod logs for debugging
├── diagnose_sync_failure - AI-powered troubleshooting
├── list_clusters        - List registered clusters
└── list_projects        - List ArgoCD projects

TIER 2: Write Operations (Require MCP_READ_ONLY=false)
├── sync_application     - Sync with dry-run by default
├── refresh_application  - Refresh manifests from Git
├── rollback_application - Rollback to previous revision
└── terminate_sync       - Stop a running sync operation

TIER 3: Destructive Operations (Require confirmation)
└── delete_application   - Delete with double-confirmation

This progressive disclosure ensures:
- Default setup is safe (read-only)
- Writes require explicit enablement
- Destruction requires multiple confirmations

=============================================================================
PYDANTIC PARAMETER MODELS
=============================================================================

Each tool defines a Pydantic model for its parameters.
This provides:

1. VALIDATION: Invalid inputs rejected with clear errors
2. DOCUMENTATION: Field descriptions become tool documentation
3. TYPE SAFETY: Runtime type checking
4. DEFAULTS: Sensible defaults where appropriate

Example:
    class SyncParams(BaseModel):
        name: str = Field(description="Application name")
        dry_run: bool = Field(default=True, description="Preview only")

FastMCP automatically converts these to tool schemas that Claude can understand.

=============================================================================
GLOBAL STATE
=============================================================================

This module uses global variables for shared state:
- _settings: Server configuration
- _clients: ArgoCD API clients
- _safety_guard: Security enforcer
- _audit_logger: Audit trail logger

WHY GLOBAL?
-----------
MCP tools are regular functions decorated with @mcp.tool().
They can't easily receive injected dependencies. Global state
provides a simple pattern for sharing resources.

The lifespan context manager initializes these at startup
and cleans them up at shutdown.
"""

# =============================================================================
# IMPORTS
# =============================================================================
#
# Standard library:
# - sys: For sys.exit() to return proper exit codes
# - asynccontextmanager: Decorator to create async context managers for lifespan
# - TYPE_CHECKING: Only True during type checking, not runtime
# - Any: Type hint that accepts any type
#
# Third-party:
# - structlog: Structured logging library
# - FastMCP: The MCP server framework
# - Context: Request context passed to tools
# - BaseModel/Field: Pydantic for parameter models with validation
#
# Local:
# - ServerSettings/load_settings: Configuration management
# - ArgocdClient/ArgocdError: HTTP client for ArgoCD API
# - AuditLogger/configure_logging/set_correlation_id: Logging utilities
# - ConfirmationRequired/SafetyGuard: Security policy enforcement
# =============================================================================

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from argocd_mcp.config import ServerSettings, load_settings
from argocd_mcp.utils.client import ArgocdClient, ArgocdError
from argocd_mcp.utils.logging import AuditLogger, configure_logging, set_correlation_id
from argocd_mcp.utils.safety import ConfirmationRequired, SafetyGuard

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# =============================================================================
# TYPE ALIASES
# =============================================================================

# Type alias for FastMCP Context with proper type parameters
# FastMCP's Context is generic: Context[ServerContext, RequestContext]
# We don't use custom context types, so we use Any for both
MCPContext = Context[Any, Any]

# =============================================================================
# MODULE-LEVEL LOGGER
# =============================================================================

# Get a logger for this module
# The logger name becomes "argocd_mcp.server"
logger = structlog.get_logger(__name__)

# =============================================================================
# GLOBAL STATE
# =============================================================================

# Server settings loaded from environment
_settings: ServerSettings | None = None

# ArgoCD clients, keyed by instance name
# Example: {"primary": <ArgocdClient>, "staging": <ArgocdClient>}
_clients: dict[str, ArgocdClient] = {}

# Safety guard for permission checking
_safety_guard: SafetyGuard | None = None

# Audit logger for recording operations
_audit_logger: AuditLogger | None = None


# =============================================================================
# SERVER LIFECYCLE
# =============================================================================


@asynccontextmanager
async def lifespan(_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """
    Manage server lifecycle and client connections.

    WHAT IS A LIFESPAN HANDLER?
    ---------------------------
    FastMCP calls this when the server starts and stops.
    It's an async context manager that:
    1. Runs startup code before 'yield'
    2. Yields state to be available during operation
    3. Runs cleanup code after 'yield'

    WHAT IT DOES:
    -------------
    STARTUP (before yield):
    - Load configuration from environment
    - Configure logging
    - Initialize security components
    - Create and connect ArgoCD clients

    RUNNING (yield):
    - Server handles requests using the global state

    SHUTDOWN (after yield):
    - Close all ArgoCD client connections
    - Clean up resources

    WHY GLOBAL STATE?
    -----------------
    The 'global' keyword allows us to modify module-level variables.
    Without it, assignment would create local variables.

        global _settings  # Now _settings = ... modifies the module variable
        _settings = load_settings()

    Args:
        _server: The FastMCP server instance (unused but required by API)

    Yields:
        Dictionary of state (available as context.state in tools)
    """
    # Declare that we're modifying global variables
    global _settings, _clients, _safety_guard, _audit_logger

    logger.info("Starting ArgoCD MCP Server")

    # -------------------------------------------------------------------------
    # STARTUP: Load configuration and initialize components
    # -------------------------------------------------------------------------

    # Load settings from environment variables
    _settings = load_settings()

    # Configure structured logging with the configured level
    configure_logging(level=_settings.log_level)

    # Initialize safety guard (permission checking) and audit logger
    _safety_guard = SafetyGuard(_settings.security)
    _audit_logger = AuditLogger(_settings.security.audit_log)

    # Create and connect ArgoCD clients for all configured instances
    for instance in _settings.all_instances:
        # Create client
        client = ArgocdClient(
            instance=instance,
            mask_secrets=_settings.security.mask_secrets,
        )
        # Enter the async context (establishes HTTP connection)
        await client.__aenter__()
        # Store in global dict
        _clients[instance.name] = client
        logger.info("Connected to ArgoCD instance", instance=instance.name, url=instance.url)

    # -------------------------------------------------------------------------
    # RUNNING: Yield control to the server
    # -------------------------------------------------------------------------

    # The yielded dict is available as context.state in tools
    # Currently not used, but available for future needs
    yield {"settings": _settings, "clients": _clients}

    # -------------------------------------------------------------------------
    # SHUTDOWN: Clean up resources
    # -------------------------------------------------------------------------

    # Close all ArgoCD client connections
    for name, client in _clients.items():
        await client.__aexit__(None, None, None)
        logger.info("Disconnected from ArgoCD instance", instance=name)

    _clients.clear()
    logger.info("ArgoCD MCP Server stopped")


# =============================================================================
# CREATE FASTMCP SERVER
# =============================================================================

# Create the MCP server instance
# "argocd-mcp" is the server name reported in the MCP protocol
# lifespan hooks into startup/shutdown
mcp = FastMCP(
    "argocd-mcp",
    lifespan=lifespan,
)


# =============================================================================
# ACCESSOR FUNCTIONS
# =============================================================================
# These functions provide safe access to global state with error checking.


def get_client(instance: str = "primary") -> ArgocdClient:
    """
    Get ArgoCD client for specified instance.

    WHY A FUNCTION?
    ---------------
    Direct access to _clients dict could fail silently if the instance
    doesn't exist. This function provides clear error messages.

    Args:
        instance: Instance name (default "primary")

    Returns:
        ArgocdClient for the specified instance

    Raises:
        ValueError: If instance not found, with list of available instances

    Example:
        client = get_client()  # Get primary
        client = get_client("staging")  # Get staging
    """
    if instance not in _clients:
        available = list(_clients.keys())
        raise ValueError(f"Unknown instance '{instance}'. Available: {available}")
    return _clients[instance]


def get_settings() -> ServerSettings:
    """
    Get server settings.

    Returns:
        ServerSettings instance

    Raises:
        RuntimeError: If server not initialized (shouldn't happen in normal use)
    """
    if not _settings:
        raise RuntimeError("Server not initialized")
    return _settings


def get_safety_guard() -> SafetyGuard:
    """
    Get safety guard.

    Returns:
        SafetyGuard instance for permission checking

    Raises:
        RuntimeError: If server not initialized
    """
    if not _safety_guard:
        raise RuntimeError("Server not initialized")
    return _safety_guard


def get_audit_logger() -> AuditLogger:
    """
    Get audit logger.

    Returns:
        AuditLogger instance for recording operations

    Raises:
        RuntimeError: If server not initialized
    """
    if not _audit_logger:
        raise RuntimeError("Server not initialized")
    return _audit_logger


# =============================================================================
# TIER 1: Essential Read Operations (Always Available)
# =============================================================================
# These tools only READ data. They're always available (subject to rate limits).


class ListApplicationsParams(BaseModel):
    """
    Parameters for list_applications tool.

    Pydantic models define:
    - Field names and types
    - Validation rules
    - Descriptions (become tool documentation)
    - Default values
    """

    project: str | None = Field(default=None, description="Filter by ArgoCD project name")
    # None means "no filter" - return apps from all projects

    health_status: str | None = Field(
        default=None,
        description="Filter by health status (Healthy, Degraded, Progressing, Missing, Unknown)",
    )
    # Filter to only apps with this health status

    sync_status: str | None = Field(
        default=None, description="Filter by sync status (Synced, OutOfSync, Unknown)"
    )
    # Filter to only apps with this sync status

    instance: str = Field(default="primary", description="ArgoCD instance name")
    # Which ArgoCD instance to query (for multi-cluster setups)


@mcp.tool()
async def list_applications(params: ListApplicationsParams, ctx: MCPContext) -> str:
    """
    List ArgoCD applications with optional filtering.

    Returns applications matching the specified filters. Use this to get
    an overview of applications in a project or find unhealthy/out-of-sync apps.

    HOW @mcp.tool() WORKS:
    ----------------------
    The @mcp.tool() decorator registers this function as an MCP tool.
    FastMCP automatically:
    1. Extracts the parameter schema from ListApplicationsParams
    2. Generates tool documentation from docstring
    3. Handles JSON-RPC communication
    4. Validates parameters before calling the function

    TOOL FUNCTION PATTERN:
    ----------------------
    Every tool function follows this pattern:

    1. Set correlation ID (for log tracing)
    2. Check permissions with SafetyGuard
    3. If blocked, log and return error message
    4. If allowed, perform the operation
    5. Log the result (success or error)
    6. Return formatted result string
    """
    # Set correlation ID for request tracing
    # This links all logs from this request together
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    # Check safety - is this read operation allowed?
    blocked = get_safety_guard().check_read_operation("list_applications")
    if blocked:
        # Operation blocked (probably rate limited)
        get_audit_logger().log_blocked("list_applications", "all", blocked.reason)
        return blocked.format_message()

    try:
        # Get the ArgoCD client for the specified instance
        client = get_client(params.instance)

        # Fetch applications from ArgoCD
        apps = await client.list_applications(project=params.project)

        # Apply client-side filters (health and sync status)
        # These could be done server-side, but ArgoCD's API doesn't support them directly
        if params.health_status:
            apps = [a for a in apps if a.health_status == params.health_status]
        if params.sync_status:
            apps = [a for a in apps if a.sync_status == params.sync_status]

        # Log successful read
        get_audit_logger().log_read("list_applications", f"project={params.project}")

        # Handle empty results
        if not apps:
            return "No applications found matching the specified filters."

        # Format output for agent consumption
        # We use markers like [OK] and [!] for visual scanning
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
        # Log and return API errors
        get_audit_logger().log_error("list_applications", "all", str(e))
        return str(e)


class GetApplicationParams(BaseModel):
    """Parameters for get_application tool."""

    name: str = Field(description="Application name")
    instance: str = Field(default="primary", description="ArgoCD instance name")


@mcp.tool()
async def get_application(params: GetApplicationParams, ctx: MCPContext) -> str:
    """
    Get detailed information about a specific ArgoCD application.

    Returns comprehensive application details including source repo, sync status,
    health status, deployment destination, and any conditions or errors.
    """
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_read_operation("get_application")
    if blocked:
        get_audit_logger().log_blocked("get_application", params.name, blocked.reason)
        return blocked.format_message()

    try:
        client = get_client(params.instance)
        app = await client.get_application(params.name)

        get_audit_logger().log_read("get_application", params.name)

        # Build detailed output
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

        # Add operation state if present (shows last sync info)
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

        # Add conditions if present (shows warnings/errors)
        if app.conditions:
            lines.extend(["", "Conditions:"])
            for cond in app.conditions:
                lines.append(f"  - [{cond.get('type')}] {cond.get('message', 'N/A')}")

        return "\n".join(lines)

    except ArgocdError as e:
        get_audit_logger().log_error("get_application", params.name, str(e))
        return str(e)


class GetApplicationStatusParams(BaseModel):
    """Parameters for get_application_status tool."""

    name: str = Field(description="Application name")
    instance: str = Field(default="primary", description="ArgoCD instance name")


@mcp.tool()
async def get_application_status(params: GetApplicationStatusParams, ctx: MCPContext) -> str:
    """
    Get condensed health and sync status for quick checks.

    Use this for a quick status check when you don't need full application details.
    """
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_read_operation("get_application_status")
    if blocked:
        get_audit_logger().log_blocked("get_application_status", params.name, blocked.reason)
        return blocked.format_message()

    try:
        client = get_client(params.instance)
        app = await client.get_application(params.name)

        get_audit_logger().log_read("get_application_status", params.name)

        # Quick status markers
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


class GetApplicationDiffParams(BaseModel):
    """Parameters for get_application_diff tool."""

    name: str = Field(description="Application name")
    revision: str | None = Field(default=None, description="Target revision to diff against")
    instance: str = Field(default="primary", description="ArgoCD instance name")


@mcp.tool()
async def get_application_diff(params: GetApplicationDiffParams, ctx: MCPContext) -> str:
    """
    Preview what would change on sync (dry-run diff).

    Shows resources that would be created, updated, or deleted if sync
    were triggered. Use this before syncing to understand the impact.

    PROGRESS REPORTING:
    -------------------
    ctx.report_progress() sends progress updates to the client.
    This is useful for long-running operations to show the AI (and user)
    that work is happening.
    """
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_read_operation("get_application_diff")
    if blocked:
        get_audit_logger().log_blocked("get_application_diff", params.name, blocked.reason)
        return blocked.format_message()

    # Report progress (0 of 2 steps complete)
    await ctx.report_progress(0, 2, "Fetching managed resources")

    try:
        client = get_client(params.instance)
        diff_data = await client.get_application_diff(params.name, params.revision)

        get_audit_logger().log_read("get_application_diff", params.name)

        await ctx.report_progress(1, 2, "Analyzing differences")

        resources = diff_data.get("items", [])
        if not resources:
            return f"No managed resources found for application '{params.name}'"

        # Categorize resources by their state
        live_only: list[
            dict[str, Any]
        ] = []  # In cluster but not in Git (would be deleted with prune)
        target_only: list[dict[str, Any]] = []  # In Git but not in cluster (would be created)
        modified: list[dict[str, Any]] = []  # In both but different (would be updated)
        synced: list[dict[str, Any]] = []  # In both and identical (no change)

        for res in resources:
            live = res.get("liveState")  # Current state in cluster
            target = res.get("targetState")  # Desired state from Git

            if live and not target:
                live_only.append(res)
            elif target and not live:
                target_only.append(res)
            elif live != target:
                modified.append(res)
            else:
                synced.append(res)

        await ctx.report_progress(2, 2, "Complete")

        # Format diff output
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


class GetApplicationHistoryParams(BaseModel):
    """Parameters for get_application_history tool."""

    name: str = Field(description="Application name")
    limit: int = Field(default=10, description="Maximum number of history entries", ge=1, le=50)
    # ge=1: Must be at least 1
    # le=50: Must be at most 50
    instance: str = Field(default="primary", description="ArgoCD instance name")


@mcp.tool()
async def get_application_history(params: GetApplicationHistoryParams, ctx: MCPContext) -> str:
    """
    View deployment history with commit info and timestamps.

    Shows recent deployments including revision, timestamp, and initiator.
    Useful for understanding recent changes and finding rollback targets.
    """
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

        # Format history entries (most recent first)
        lines = [f"Deployment history for '{params.name}' (last {len(history)} entries):", ""]
        for i, entry in enumerate(reversed(history), 1):
            revision = entry.get("revision", "unknown")[:8]  # Short SHA
            deployed_at = entry.get("deployedAt", "unknown")
            initiator = entry.get("initiatedBy", {}).get("username", "unknown")
            lines.append(f"{i}. [{revision}] at {deployed_at} by {initiator}")

        return "\n".join(lines)

    except ArgocdError as e:
        get_audit_logger().log_error("get_application_history", params.name, str(e))
        return str(e)


class DiagnoseSyncFailureParams(BaseModel):
    """Parameters for diagnose_sync_failure tool."""

    name: str = Field(description="Application name")
    instance: str = Field(default="primary", description="ArgoCD instance name")


@mcp.tool()
async def diagnose_sync_failure(params: DiagnoseSyncFailureParams, ctx: MCPContext) -> str:
    """
    Diagnose why an application sync failed.

    Aggregates sync status, resource conditions, events, and recent logs
    to identify root cause. Provides actionable suggestions for resolution.

    AI-POWERED DIAGNOSTICS:
    -----------------------
    This tool gathers multiple data sources and analyzes them:
    1. Application status (sync, health)
    2. Resource tree (for unhealthy children)
    3. Kubernetes events (for detailed errors)

    It looks for common patterns:
    - ImagePullBackOff: Image doesn't exist or registry auth failed
    - CrashLoopBackOff: Application crashing on startup
    - RBAC errors: Missing permissions
    - OOMKilled: Out of memory
    - Scheduling failures: No nodes available
    """
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_read_operation("diagnose_sync_failure")
    if blocked:
        get_audit_logger().log_blocked("diagnose_sync_failure", params.name, blocked.reason)
        return blocked.format_message()

    try:
        client = get_client(params.instance)

        # Gather data from multiple sources
        await ctx.report_progress(0, 4, "Fetching application status")
        app = await client.get_application(params.name)

        await ctx.report_progress(1, 4, "Gathering resource conditions")
        tree_data = await client.get_resource_tree(params.name)

        await ctx.report_progress(2, 4, "Collecting events")
        events = await client.get_application_events(params.name)

        await ctx.report_progress(3, 4, "Analyzing diagnosis")

        get_audit_logger().log_read("diagnose_sync_failure", params.name)

        # Build lists of issues and suggestions
        issues: list[str] = []
        suggestions: list[str] = []

        # Check sync status
        if app.sync_status == "OutOfSync":
            issues.append(f"Application is out of sync (revision: {app.target_revision})")
            suggestions.append("Run get_application_diff to see pending changes")

        # Check health status
        if app.health_status == "Degraded":
            issues.append("Application health is Degraded")
        elif app.health_status == "Progressing":
            issues.append("Application is still progressing")
            suggestions.append("Wait for operations to complete or check for stuck resources")
        elif app.health_status == "Missing":
            issues.append("Application resources are missing from cluster")
            suggestions.append("Verify destination cluster connectivity and namespace exists")

        # Check operation state (last sync result)
        if app.operation_state:
            op_phase = app.operation_state.get("phase", "")
            op_message = app.operation_state.get("message", "")
            if op_phase == "Failed":
                issues.append(f"Last operation failed: {op_message}")
            elif op_phase == "Running":
                issues.append("Sync operation currently running")

        # Check conditions (ArgoCD-level warnings)
        if app.conditions:
            for cond in app.conditions:
                cond_type = cond.get("type", "")
                cond_msg = cond.get("message", "")
                if cond_type in ("ComparisonError", "InvalidSpecError", "SyncError"):
                    issues.append(f"[{cond_type}] {cond_msg}")

        # Analyze events for common patterns
        for event in events[:20]:  # Check recent events
            msg = event.get("message", "")
            reason = event.get("reason", "")

            # Image pull issues
            if "ImagePullBackOff" in msg or "ErrImagePull" in msg:
                issues.append(f"Image pull failed: {msg[:100]}")
                suggestions.append("Verify image exists and registry credentials are configured")

            # Container crashing
            elif "CrashLoopBackOff" in msg:
                issues.append(f"Container crashing: {msg[:100]}")
                suggestions.append("Check pod logs for application startup errors")

            # RBAC/permission issues
            elif "Forbidden" in msg or "unauthorized" in msg.lower():
                issues.append(f"RBAC permission denied: {msg[:100]}")
                suggestions.append("Review ServiceAccount permissions in destination cluster")

            # Memory issues
            elif "OOMKilled" in msg:
                issues.append("Container killed due to memory limit")
                suggestions.append("Increase memory limits or optimize application memory usage")

            # Scheduling issues
            elif "PodUnschedulable" in reason or "Insufficient" in msg:
                issues.append(f"Scheduling failed: {msg[:100]}")
                suggestions.append("Check cluster capacity and node availability")

        # Check resource tree for unhealthy nodes
        nodes = tree_data.get("nodes", [])
        unhealthy_resources = [
            n for n in nodes if n.get("health", {}).get("status") in ("Degraded", "Missing")
        ]
        if unhealthy_resources:
            issues.append(f"Found {len(unhealthy_resources)} unhealthy resources in resource tree")
            for r in unhealthy_resources[:5]:  # Limit to 5
                issues.append(
                    f"  - {r.get('kind', 'Unknown')}/{r.get('name', 'unknown')}: "
                    f"{r.get('health', {}).get('message', 'N/A')}"
                )

        await ctx.report_progress(4, 4, "Diagnosis complete")

        # Format output
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
            for suggestion in list(set(suggestions)):  # Deduplicate
                lines.append(f"  - {suggestion}")

        return "\n".join(lines)

    except ArgocdError as e:
        get_audit_logger().log_error("diagnose_sync_failure", params.name, str(e))
        return str(e)


class GetApplicationLogsParams(BaseModel):
    """Parameters for get_application_logs tool."""

    name: str = Field(description="Application name")
    pod_name: str | None = Field(default=None, description="Specific pod name (optional)")
    container: str | None = Field(
        default=None, description="Container name for multi-container pods (optional)"
    )
    tail_lines: int = Field(default=100, description="Number of log lines to return", ge=1, le=1000)
    since_seconds: int | None = Field(
        default=None, description="Only return logs newer than this many seconds"
    )
    instance: str = Field(default="primary", description="ArgoCD instance name")


@mcp.tool()
async def get_application_logs(params: GetApplicationLogsParams, ctx: MCPContext) -> str:
    """
    Get pod logs for an application.

    Retrieves logs from pods managed by the application. Useful for
    debugging application issues, checking startup errors, or
    monitoring runtime behavior.
    """
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


class ListClustersParams(BaseModel):
    """Parameters for list_clusters tool."""

    instance: str = Field(default="primary", description="ArgoCD instance name")


@mcp.tool()
async def list_clusters(params: ListClustersParams, ctx: MCPContext) -> str:
    """
    List registered Kubernetes clusters with health status.

    Shows all clusters registered with ArgoCD and their connection status.
    """
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


class ListProjectsParams(BaseModel):
    """Parameters for list_projects tool."""

    instance: str = Field(default="primary", description="ArgoCD instance name")


@mcp.tool()
async def list_projects(params: ListProjectsParams, ctx: MCPContext) -> str:
    """
    List ArgoCD projects.

    Shows all projects which organize and control application access.
    """
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


# =============================================================================
# TIER 2: Write Operations (Require MCP_READ_ONLY=false)
# =============================================================================
# These tools MODIFY state. They require write permissions.


class SyncApplicationParams(BaseModel):
    """Parameters for sync_application tool."""

    name: str = Field(description="Application name")
    dry_run: bool = Field(
        default=True, description="Preview changes without applying (default: true)"
    )
    # SAFETY: Default to dry-run to prevent accidental changes
    prune: bool = Field(default=False, description="Delete resources not in Git (destructive)")
    # SAFETY: Default to NOT prune to prevent accidental deletions
    force: bool = Field(default=False, description="Force sync even if already synced")
    revision: str | None = Field(default=None, description="Git revision to sync to")
    instance: str = Field(default="primary", description="ArgoCD instance name")


@mcp.tool()
async def sync_application(params: SyncApplicationParams, ctx: MCPContext) -> str:
    """
    Synchronize application with Git repository.

    By default runs in dry-run mode showing what would change.
    Set dry_run=false to apply changes. Use prune=true to remove
    resources deleted from Git (destructive, requires confirmation).

    DRY-RUN BY DEFAULT:
    -------------------
    Unlike most sync operations, this DEFAULTS to dry_run=true.
    This is a safety measure to prevent accidental changes.
    The AI (or user) must explicitly set dry_run=false to apply changes.
    """
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    # Check if prune requested - this is DESTRUCTIVE
    if params.prune and not params.dry_run:
        # Prune requires destructive operation permissions
        blocked = get_safety_guard().check_destructive_operation(
            "sync_with_prune",
            params.name,
            confirmed=False,  # Prune requires explicit confirmation flow
        )
        if blocked:
            if isinstance(blocked, ConfirmationRequired):
                get_audit_logger().log_blocked(
                    "sync_application", params.name, "prune requires confirmation"
                )
                return (
                    f"PRUNE REQUIRES CONFIRMATION\n\n"
                    f"Syncing '{params.name}' with prune=true will DELETE resources "
                    f"that exist in the cluster but not in Git.\n\n"
                    f"First, run with dry_run=true to preview deletions:\n"
                    f"  sync_application(name='{params.name}', dry_run=true, prune=true)\n\n"
                    f"For pruning, use the destructive sync tool with confirmation."
                )
            return blocked.format_message()
    else:
        # Regular write operation
        blocked = get_safety_guard().check_write_operation("sync_application")
        if blocked:
            get_audit_logger().log_blocked("sync_application", params.name, blocked.reason)
            return blocked.format_message()

    try:
        client = get_client(params.instance)

        # Show mode in progress message
        mode = "[DRY-RUN] " if params.dry_run else ""
        await ctx.report_progress(0, 2, f"{mode}Initiating sync for {params.name}")

        await client.sync_application(
            name=params.name,
            dry_run=params.dry_run,
            prune=params.prune,
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
        else:
            get_audit_logger().log_write(
                "sync_application",
                params.name,
                "initiated",
                {"prune": params.prune, "force": params.force},
            )
            return (
                f"Sync initiated for '{params.name}'\n"
                f"Revision: {params.revision or 'HEAD'}\n"
                f"Prune: {params.prune}\n\n"
                f"Use get_application_status to monitor progress."
            )

    except ArgocdError as e:
        get_audit_logger().log_error("sync_application", params.name, str(e))
        return str(e)


class RefreshApplicationParams(BaseModel):
    """Parameters for refresh_application tool."""

    name: str = Field(description="Application name")
    hard: bool = Field(default=False, description="Force hard refresh (invalidate cache)")
    instance: str = Field(default="primary", description="ArgoCD instance name")


@mcp.tool()
async def refresh_application(params: RefreshApplicationParams, ctx: MCPContext) -> str:
    """
    Force manifest refresh from Git.

    Triggers ArgoCD to re-fetch manifests from the Git repository.
    Use hard=true to invalidate cache and force full refresh.
    """
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_write_operation("refresh_application")
    if blocked:
        get_audit_logger().log_blocked("refresh_application", params.name, blocked.reason)
        return blocked.format_message()

    try:
        client = get_client(params.instance)

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


class RollbackApplicationParams(BaseModel):
    """Parameters for rollback_application tool."""

    name: str = Field(description="Application name")
    revision_id: int = Field(description="History revision ID to rollback to")
    dry_run: bool = Field(
        default=True, description="Preview rollback without applying (default: true)"
    )
    instance: str = Field(default="primary", description="ArgoCD instance name")


@mcp.tool()
async def rollback_application(params: RollbackApplicationParams, ctx: MCPContext) -> str:
    """
    Rollback application to a previous deployment revision.

    Use get_application_history to find revision IDs, then rollback
    to a known-good state. Defaults to dry-run mode for safety.
    """
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_write_operation("rollback_application")
    if blocked:
        get_audit_logger().log_blocked("rollback_application", params.name, blocked.reason)
        return blocked.format_message()

    try:
        client = get_client(params.instance)

        mode = "[DRY-RUN] " if params.dry_run else ""
        await ctx.report_progress(0, 1, f"{mode}Rolling back {params.name}")

        await client.rollback_application(
            name=params.name,
            revision_id=params.revision_id,
            dry_run=params.dry_run,
        )

        if params.dry_run:
            get_audit_logger().log_write("rollback_application", params.name, "dry_run")
            return (
                f"Dry-run rollback complete for '{params.name}' to revision {params.revision_id}\n\n"
                f"To apply the rollback:\n"
                f"  rollback_application(name='{params.name}', "
                f"revision_id={params.revision_id}, dry_run=false)"
            )
        else:
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


class TerminateSyncParams(BaseModel):
    """Parameters for terminate_sync tool."""

    name: str = Field(description="Application name")
    instance: str = Field(default="primary", description="ArgoCD instance name")


@mcp.tool()
async def terminate_sync(params: TerminateSyncParams, ctx: MCPContext) -> str:
    """
    Terminate an ongoing sync operation.

    Stops a sync that's currently in progress. Useful when a sync
    is stuck, taking too long, or was triggered by mistake.
    """
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    blocked = get_safety_guard().check_write_operation("terminate_sync")
    if blocked:
        get_audit_logger().log_blocked("terminate_sync", params.name, blocked.reason)
        return blocked.format_message()

    try:
        client = get_client(params.instance)

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


# =============================================================================
# TIER 3: Destructive Operations (Require explicit confirmation)
# =============================================================================
# These tools can DESTROY data. They require multiple confirmations.


class DeleteApplicationParams(BaseModel):
    """Parameters for delete_application tool."""

    name: str = Field(description="Application name to delete")
    cascade: bool = Field(
        default=True, description="Delete application resources from cluster (default: true)"
    )
    # IMPORTANT: cascade=True is the default because orphaning resources
    # is usually not what users want. But it means deletion is very destructive!
    confirm: bool = Field(default=False, description="Must be true to execute deletion")
    # SAFETY: Must explicitly set confirm=true
    confirm_name: str | None = Field(
        default=None, description="Type application name to confirm deletion"
    )
    # SAFETY: Must type the name to prevent copy-paste errors
    instance: str = Field(default="primary", description="ArgoCD instance name")


@mcp.tool()
async def delete_application(params: DeleteApplicationParams, ctx: MCPContext) -> str:
    """
    Delete an ArgoCD application (DESTRUCTIVE).

    Requires explicit confirmation. Set confirm=true AND confirm_name
    matching the application name to proceed. With cascade=true (default),
    also deletes Kubernetes resources managed by this application.

    DOUBLE-CONFIRMATION PATTERN:
    ----------------------------
    To delete application "myapp", you must:
    1. Set confirm=true
    2. Set confirm_name="myapp"

    This ensures you:
    - Consciously acknowledge the deletion
    - Know exactly what you're deleting
    """
    set_correlation_id(ctx.request_id if hasattr(ctx, "request_id") else "")

    # Check destructive operation permissions
    blocked = get_safety_guard().check_destructive_operation(
        "delete_application",
        params.name,
        confirmed=params.confirm,
        confirm_name=params.confirm_name,
    )

    if blocked:
        if isinstance(blocked, ConfirmationRequired):
            # Get app info to enhance the confirmation message
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
                pass  # If we can't get app info, just use generic message
            get_audit_logger().log_blocked(
                "delete_application", params.name, "confirmation required"
            )
            return blocked.format_message()
        return blocked.format_message()

    try:
        client = get_client(params.instance)

        await ctx.report_progress(0, 1, f"Deleting application {params.name}")

        await client.delete_application(params.name, params.cascade)

        get_audit_logger().log_write(
            "delete_application",
            params.name,
            "deleted",
            {"cascade": params.cascade},
        )

        return f"Application '{params.name}' deleted successfully.\nCascade: {params.cascade}"

    except ArgocdError as e:
        get_audit_logger().log_error("delete_application", params.name, str(e))
        return str(e)


# =============================================================================
# MCP RESOURCES
# =============================================================================
# Resources provide contextual information to AI assistants.
# Unlike tools (which take parameters), resources are identified by URI.


@mcp.resource("argocd://instances")
async def get_instances_resource() -> str:
    """
    Get information about configured ArgoCD instances.

    WHAT ARE MCP RESOURCES?
    -----------------------
    Resources provide data that AI assistants can request.
    They're identified by URIs like "argocd://instances".

    Unlike tools, resources don't take parameters.
    They're for providing context, not performing actions.
    """
    settings = get_settings()
    instances = settings.all_instances

    if not instances:
        return "No ArgoCD instances configured"

    lines = ["Configured ArgoCD Instances:", ""]
    for inst in instances:
        lines.append(f"- {inst.name}: {inst.url}")

    return "\n".join(lines)


@mcp.resource("argocd://security")
async def get_security_resource() -> str:
    """
    Get current security settings.

    Provides the AI with information about what's allowed/blocked.
    Useful for explaining why operations might fail.
    """
    settings = get_settings()
    sec = settings.security

    return (
        "Security Settings:\n"
        f"  Read-only mode: {sec.read_only}\n"
        f"  Destructive operations disabled: {sec.disable_destructive}\n"
        f"  Single cluster mode: {sec.single_cluster}\n"
        f"  Secret masking: {sec.mask_secrets}\n"
        f"  Rate limit: {sec.rate_limit_calls} calls per {sec.rate_limit_window}s"
    )


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main() -> None:
    """
    Run the ArgoCD MCP server.

    This is the entry point when running 'argocd-mcp' command.
    It's defined in pyproject.toml as:

        [project.scripts]
        argocd-mcp = "argocd_mcp.server:main"

    THE SERVER LOOP:
    ----------------
    mcp.run() starts the MCP server which:
    1. Listens for MCP protocol messages (via stdio or HTTP)
    2. Handles tool/resource requests
    3. Runs until interrupted (Ctrl+C) or error
    """
    # Configure initial logging (before lifespan sets the real level)
    configure_logging(level="INFO")
    logger.info("ArgoCD MCP Server starting")

    try:
        # Start the MCP server (blocks until shutdown)
        mcp.run()
    except KeyboardInterrupt:
        # Clean shutdown on Ctrl+C
        logger.info("Server interrupted")
        sys.exit(0)
    except Exception as e:
        # Log unexpected errors
        logger.error("Server error", error=str(e))
        sys.exit(1)


# This allows running the module directly: python -m argocd_mcp.server
if __name__ == "__main__":
    main()
