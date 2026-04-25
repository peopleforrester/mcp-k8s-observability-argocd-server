# ABOUTME: MCP resource package exposing read-only views of server state
# ABOUTME: applications submodule registers argocd:// resources with FastMCP

"""ArgoCD MCP resource definitions.

Modules:
    applications — argocd://instances and argocd://security text resources

server.py calls `register_resources(mcp)` to bind these to the FastMCP instance.
"""
