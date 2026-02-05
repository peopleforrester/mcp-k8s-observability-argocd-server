# ABOUTME: ArgoCD MCP Server package initialization
# ABOUTME: Exposes version information from package metadata

"""ArgoCD MCP Server - Safety-first GitOps operations via Model Context Protocol."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("argocd-mcp-server")
except PackageNotFoundError:
    # Package not installed (running from source without install)
    __version__ = "0.0.0.dev"

__all__ = ["__version__"]
