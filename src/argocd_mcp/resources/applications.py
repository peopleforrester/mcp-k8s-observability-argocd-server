# ABOUTME: MCP resource endpoints exposing configured instances and security settings
# ABOUTME: Resources are lightweight text read-only views; callable by any MCP client

"""MCP resource definitions (argocd://instances, argocd://security)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from argocd_mcp.config import ServerSettings


def _get_settings() -> ServerSettings:
    """Lazy resolve server-level settings accessor to avoid a circular import."""
    from argocd_mcp.server import get_settings  # noqa: PLC0415

    return get_settings()


async def get_instances_resource() -> str:
    """Get information about configured ArgoCD instances."""
    settings = _get_settings()
    instances = settings.all_instances

    if not instances:
        return "No ArgoCD instances configured"

    lines = ["Configured ArgoCD Instances:", ""]
    for inst in instances:
        lines.append(f"- {inst.name}: {inst.url}")

    return "\n".join(lines)


async def get_security_resource() -> str:
    """Get current security settings."""
    settings = _get_settings()
    sec = settings.security

    return (
        "Security Settings:\n"
        f"  Read-only mode: {sec.read_only}\n"
        f"  Destructive operations disabled: {sec.disable_destructive}\n"
        f"  Single cluster mode: {sec.single_cluster}\n"
        f"  Secret masking: {sec.mask_secrets}\n"
        f"  Rate limit: {sec.rate_limit_calls} calls per {sec.rate_limit_window}s"
    )


def register_resources(mcp: FastMCP) -> None:
    """Register all MCP resources with the given FastMCP instance."""
    mcp.resource("argocd://instances")(get_instances_resource)
    mcp.resource("argocd://security")(get_security_resource)


__all__ = [
    "get_instances_resource",
    "get_security_resource",
    "register_resources",
]
