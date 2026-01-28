# ABOUTME: Tools package initialization for ArgoCD MCP Server
# ABOUTME: Contains all MCP tool implementations organized by category

"""
ArgoCD MCP Tools Package

Tools are organized into tiers following progressive disclosure principles:

Tier 1 (Essential Read): Always available
    - applications.py: list, get, status, diff, history, logs, events, tree

Tier 2 (Write Operations): Require --enable-writes
    - sync.py: sync, rollback, refresh, terminate

Tier 3 (Destructive): Require explicit confirmation
    - delete.py: delete with cascade options

Tier 4 (Admin): Separate toolset
    - admin.py: create, update, project management
"""
