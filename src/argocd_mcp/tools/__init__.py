# ABOUTME: MCP tool package grouping handlers by safety tier
# ABOUTME: params/read/write/destructive submodules; server.py wires them to FastMCP

"""ArgoCD MCP tool handlers, split by safety tier.

Modules:
    params      — Pydantic parameter models for every tool
    read        — Tier 1 (always available, read-only)
    write       — Tier 2 (mutating; requires MCP_READ_ONLY=false)
    destructive — Tier 3 (destructive; requires confirmation + name match)

Each tier module exposes a `register_*` function that server.py calls once to
bind the handlers to the FastMCP instance. Handlers themselves use lazy imports
to reach server-level accessors, avoiding a circular import.
"""
