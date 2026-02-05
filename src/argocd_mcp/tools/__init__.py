# ABOUTME: Tools package placeholder for ArgoCD MCP Server
# ABOUTME: Reserved for future modularization of tool implementations

"""
ArgoCD MCP Tools Package (placeholder).

All MCP tool implementations currently reside in server.py, organized by tier:

Tier 1 (Essential Read): list_applications, get_application, get_application_status,
    get_application_diff, get_application_history, get_application_logs,
    diagnose_sync_failure, list_clusters, list_projects
Tier 2 (Write Operations): sync_application, refresh_application,
    rollback_application, terminate_sync
Tier 3 (Destructive): delete_application

This package is reserved for future modularization if server.py grows too large.
"""
