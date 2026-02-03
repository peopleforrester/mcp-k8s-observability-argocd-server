# ABOUTME: ArgoCD MCP Server package initialization
# ABOUTME: Exposes main server components and version information

"""
ArgoCD MCP Server - Safety-first GitOps operations via Model Context Protocol.

=============================================================================
WHAT IS THIS FILE?
=============================================================================

This is the package initialization file (__init__.py) for the argocd_mcp package.
In Python, __init__.py files serve several purposes:

1. PACKAGE MARKER: They mark a directory as a Python package, allowing other
   code to import modules from this directory using `import argocd_mcp`

2. NAMESPACE CONTROL: They define what symbols (functions, classes, variables)
   are exposed when someone does `from argocd_mcp import *`

3. INITIALIZATION: Code here runs when the package is first imported, useful
   for setting up package-level state or configuration

=============================================================================
WHAT IS MCP (MODEL CONTEXT PROTOCOL)?
=============================================================================

MCP is a standard protocol that allows AI assistants (like Claude) to interact
with external tools and data sources. Think of it like a USB standard for AI:

- Just as USB defines how keyboards/mice/drives communicate with computers
- MCP defines how AI models communicate with external tools

An MCP Server provides:
- TOOLS: Actions the AI can take (e.g., "sync_application", "list_clusters")
- RESOURCES: Data the AI can read (e.g., "argocd://instances")
- PROMPTS: Pre-defined conversation starters (not used here)

=============================================================================
WHAT IS ARGO CD?
=============================================================================

ArgoCD is a GitOps continuous delivery tool for Kubernetes. It:

1. WATCHES Git repositories containing Kubernetes manifests (YAML files)
2. COMPARES the desired state (Git) with the actual state (cluster)
3. SYNCHRONIZES the cluster to match Git when differences are found

This makes deployments:
- DECLARATIVE: You describe what you want, not how to get there
- VERSION CONTROLLED: All changes tracked in Git history
- AUDITABLE: Who changed what and when is recorded

=============================================================================
PACKAGE STRUCTURE OVERVIEW
=============================================================================

argocd_mcp/
├── __init__.py          <- YOU ARE HERE: Package entry point
├── config.py            <- Configuration management (env vars, settings)
├── server.py            <- Main MCP server with all tools defined
├── utils/
│   ├── __init__.py      <- Utils subpackage marker
│   ├── client.py        <- HTTP client for ArgoCD REST API
│   ├── logging.py       <- Structured logging with audit trails
│   └── safety.py        <- Security guards and rate limiting
├── tools/
│   └── __init__.py      <- Placeholder for tool modules
└── resources/
    └── __init__.py      <- Placeholder for resource modules
"""

# =============================================================================
# VERSION INFORMATION
# =============================================================================

# __version__ is a Python convention for declaring package version.
# This follows Semantic Versioning (SemVer): MAJOR.MINOR.PATCH
#
# - MAJOR: Breaking changes that require users to update their code
# - MINOR: New features that are backwards-compatible
# - PATCH: Bug fixes that are backwards-compatible
#
# Version 0.x.x indicates the package is in initial development phase
# and the API may change without warning.

__version__ = "0.1.0"

# =============================================================================
# PUBLIC API DEFINITION
# =============================================================================

# __all__ defines what gets exported when someone does `from argocd_mcp import *`
# This is called "explicit re-exporting" and is a Python best practice.
#
# By keeping this list minimal, we:
# 1. REDUCE namespace pollution in the importing module
# 2. SIGNAL to users what the intended public API is
# 3. ALLOW internal refactoring without breaking external code
#
# Currently, we only export __version__ because:
# - The server is run via CLI command, not by importing
# - Internal modules should be imported directly if needed
#
# Example usage:
#   >>> import argocd_mcp
#   >>> print(argocd_mcp.__version__)
#   '0.1.0'

__all__ = ["__version__"]
