# ABOUTME: Pydantic parameter models for all ArgoCD MCP tools
# ABOUTME: Centralized to keep tool handlers focused on logic, not schema

"""Tool parameter models grouped by tier (read / write / destructive)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Tier 1: Read parameter models
# =============================================================================


class ListApplicationsParams(BaseModel):
    """Parameters for list_applications tool."""

    project: str | None = Field(default=None, description="Filter by ArgoCD project name")
    health_status: str | None = Field(
        default=None,
        description="Filter by health status (Healthy, Degraded, Progressing, Missing, Unknown)",
    )
    sync_status: str | None = Field(
        default=None, description="Filter by sync status (Synced, OutOfSync, Unknown)"
    )
    instance: str = Field(default="primary", description="ArgoCD instance name")


class GetApplicationParams(BaseModel):
    """Parameters for get_application tool."""

    name: str = Field(description="Application name")
    instance: str = Field(default="primary", description="ArgoCD instance name")


class GetApplicationStatusParams(BaseModel):
    """Parameters for get_application_status tool."""

    name: str = Field(description="Application name")
    instance: str = Field(default="primary", description="ArgoCD instance name")


class GetApplicationDiffParams(BaseModel):
    """Parameters for get_application_diff tool."""

    name: str = Field(description="Application name")
    revision: str | None = Field(default=None, description="Target revision to diff against")
    instance: str = Field(default="primary", description="ArgoCD instance name")


class GetApplicationHistoryParams(BaseModel):
    """Parameters for get_application_history tool."""

    name: str = Field(description="Application name")
    limit: int = Field(default=10, description="Maximum number of history entries", ge=1, le=50)
    instance: str = Field(default="primary", description="ArgoCD instance name")


class DiagnoseSyncFailureParams(BaseModel):
    """Parameters for diagnose_sync_failure tool."""

    name: str = Field(description="Application name")
    instance: str = Field(default="primary", description="ArgoCD instance name")


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


class ListClustersParams(BaseModel):
    """Parameters for list_clusters tool."""

    instance: str = Field(default="primary", description="ArgoCD instance name")


class ListProjectsParams(BaseModel):
    """Parameters for list_projects tool."""

    instance: str = Field(default="primary", description="ArgoCD instance name")


# =============================================================================
# Tier 2: Write parameter models
# =============================================================================


class SyncApplicationParams(BaseModel):
    """Parameters for sync_application tool (non-destructive sync only)."""

    # Reject unknown fields so agents get a clear error if they pass legacy `prune`
    # or mistype a field name, rather than having the typo silently dropped.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Application name")
    dry_run: bool = Field(
        default=True, description="Preview changes without applying (default: true)"
    )
    force: bool = Field(default=False, description="Force sync even if already synced")
    revision: str | None = Field(default=None, description="Git revision to sync to")
    instance: str = Field(default="primary", description="ArgoCD instance name")


class RefreshApplicationParams(BaseModel):
    """Parameters for refresh_application tool."""

    name: str = Field(description="Application name")
    hard: bool = Field(default=False, description="Force hard refresh (invalidate cache)")
    instance: str = Field(default="primary", description="ArgoCD instance name")


class RollbackApplicationParams(BaseModel):
    """Parameters for rollback_application tool."""

    name: str = Field(description="Application name")
    revision_id: int = Field(description="History revision ID to rollback to")
    dry_run: bool = Field(
        default=True, description="Preview rollback without applying (default: true)"
    )
    instance: str = Field(default="primary", description="ArgoCD instance name")


class TerminateSyncParams(BaseModel):
    """Parameters for terminate_sync tool."""

    name: str = Field(description="Application name")
    instance: str = Field(default="primary", description="ArgoCD instance name")


# =============================================================================
# Tier 3: Destructive parameter models
# =============================================================================


class DeleteApplicationParams(BaseModel):
    """Parameters for delete_application tool."""

    name: str = Field(description="Application name to delete")
    cascade: bool = Field(
        default=True, description="Delete application resources from cluster (default: true)"
    )
    confirm: bool = Field(default=False, description="Must be true to execute deletion")
    confirm_name: str | None = Field(
        default=None, description="Type application name to confirm deletion"
    )
    instance: str = Field(default="primary", description="ArgoCD instance name")


class SyncApplicationWithPruneParams(BaseModel):
    """Parameters for sync_application_with_prune tool (Tier 3 — destructive)."""

    name: str = Field(description="Application name")
    dry_run: bool = Field(
        default=True, description="Preview deletions without applying (default: true)"
    )
    force: bool = Field(default=False, description="Force sync even if already synced")
    revision: str | None = Field(default=None, description="Git revision to sync to")
    confirm: bool = Field(
        default=False, description="Must be true to execute live prune (dry_run=false)"
    )
    confirm_name: str | None = Field(
        default=None,
        description="Type application name to confirm live prune (exact match, case-sensitive)",
    )
    instance: str = Field(default="primary", description="ArgoCD instance name")


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
    "SyncApplicationParams",
    "SyncApplicationWithPruneParams",
    "TerminateSyncParams",
]
