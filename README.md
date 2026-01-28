# ArgoCD MCP Server

**Safety-first GitOps operations for ArgoCD via the Model Context Protocol.**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

## Overview

A production-grade MCP server for ArgoCD that implements **defense-in-depth security**, **progressive disclosure patterns**, and **AI-powered diagnostics**. Built to address real SRE pain points: sync failures with empty error messages, UI performance degradation at scale, and YAML fatigue.

### Key Differentiators

- **Safety-first**: Dry-run by default, explicit confirmation for destructive operations
- **Progressive disclosure**: Simple tools always available, advanced tools on request
- **Multi-instance support**: Manage multiple ArgoCD instances from a single server
- **SRE-optimized**: Intelligent troubleshooting aggregates logs, events, and status
- **Enterprise security**: Read-only mode, audit logging, rate limiting, secret masking

## Quick Start

### Claude Desktop Configuration

```json
{
  "mcpServers": {
    "argocd": {
      "command": "uvx",
      "args": ["argocd-mcp-server"],
      "env": {
        "ARGOCD_URL": "https://argocd.example.com",
        "ARGOCD_TOKEN": "your-api-token"
      }
    }
  }
}
```

### Docker

```bash
docker run -e ARGOCD_URL=https://argocd.example.com \
           -e ARGOCD_TOKEN=your-token \
           ghcr.io/peopleforrester/argocd-mcp-server:latest
```

### Local Development

```bash
# Clone and install
git clone https://github.com/peopleforrester/mcp-k8s-observability-argocd-server
cd mcp-k8s-observability-argocd-server

# Install with uv
uv sync --dev

# Run with environment variables
export ARGOCD_URL=https://argocd.example.com
export ARGOCD_TOKEN=your-token
uv run argocd-mcp
```

## Security Model

This server implements **defense-in-depth** with four security layers:

| Mode | Environment Variable | Default | Effect |
|------|---------------------|---------|--------|
| Read-only | `MCP_READ_ONLY` | `true` | Blocks all write operations |
| Non-destructive | `MCP_DISABLE_DESTRUCTIVE` | `true` | Blocks delete/prune operations |
| Single-cluster | `MCP_SINGLE_CLUSTER` | `false` | Restricts to default cluster |
| Audit logging | `MCP_AUDIT_LOG` | (disabled) | Logs all operations to file |

### To Enable Write Operations

```bash
# Enable writes (still blocks destructive operations)
export MCP_READ_ONLY=false

# Enable destructive operations (delete, prune)
export MCP_DISABLE_DESTRUCTIVE=false
```

## Tool Reference

### Tier 1: Essential Read Operations (Always Available)

| Tool | Description |
|------|-------------|
| `list_applications` | List applications with filtering by project, health, or sync status |
| `get_application` | Get detailed application info including source, destination, and status |
| `get_application_status` | Quick health and sync status check |
| `get_application_diff` | Preview what would change on sync (dry-run diff) |
| `get_application_history` | View deployment history with commits and timestamps |
| `diagnose_sync_failure` | AI-powered troubleshooting with actionable suggestions |
| `list_clusters` | List registered clusters with connection status |
| `list_projects` | List ArgoCD projects |

### Tier 2: Write Operations (Require `MCP_READ_ONLY=false`)

| Tool | Description |
|------|-------------|
| `sync_application` | Sync with dry-run default; set `dry_run=false` to apply |
| `refresh_application` | Force manifest refresh from Git |

### Tier 3: Destructive Operations (Require confirmation)

| Tool | Description |
|------|-------------|
| `delete_application` | Delete application; requires `confirm=true` and `confirm_name` |

## Example Conversations

**"What applications are failing in production?"**
```
→ list_applications(health_status="Degraded", project="prod")
```

**"Why is my-app not syncing?"**
```
→ diagnose_sync_failure(name="my-app")
```

**"Deploy the latest changes to staging"**
```
→ sync_application(name="my-app", dry_run=false)
```

**"Show me what would change if I sync"**
```
→ get_application_diff(name="my-app")
```

## Configuration Reference

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ARGOCD_URL` | ArgoCD server URL | (required) |
| `ARGOCD_TOKEN` | ArgoCD API token | (required) |
| `ARGOCD_INSECURE` | Skip TLS verification | `false` |
| `MCP_READ_ONLY` | Block write operations | `true` |
| `MCP_DISABLE_DESTRUCTIVE` | Block delete/prune | `true` |
| `MCP_SINGLE_CLUSTER` | Restrict to default cluster | `false` |
| `MCP_AUDIT_LOG` | Path to audit log file | (disabled) |
| `MCP_RATE_LIMIT_CALLS` | Max API calls per window | `100` |
| `MCP_RATE_LIMIT_WINDOW` | Rate limit window (seconds) | `60` |
| `ARGOCD_MCP_LOG_LEVEL` | Logging level | `INFO` |

### Multi-Instance Configuration

For managing multiple ArgoCD instances, configure additional instances via environment:

```bash
# Primary instance
export ARGOCD_URL=https://argocd-prod.example.com
export ARGOCD_TOKEN=prod-token

# Additional instances can be configured programmatically
```

## Development

### Prerequisites

- Python 3.11+
- uv (recommended) or pip
- Docker (for container builds)
- Kind (for local Kubernetes testing)

### Setup

```bash
# Install dependencies
uv sync --dev

# Run tests
uv run pytest

# Run linting
uv run ruff check src tests
uv run mypy src

# Build Docker image
docker build -t argocd-mcp-server .
```

### Testing with Kind

```bash
# Create Kind cluster
kind create cluster --name argocd-mcp-test

# Install ArgoCD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Get ArgoCD admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d

# Port forward
kubectl port-forward svc/argocd-server -n argocd 8080:443
```

## Architecture

```
argocd-mcp-server/
├── src/argocd_mcp/
│   ├── server.py           # FastMCP server with tools and resources
│   ├── config.py           # Configuration management
│   ├── tools/              # Tool implementations by tier
│   ├── resources/          # MCP resources
│   └── utils/
│       ├── client.py       # ArgoCD API client
│       ├── safety.py       # Confirmation patterns
│       └── logging.py      # Structured logging
├── tests/
│   ├── unit/               # Unit tests
│   ├── integration/        # Integration tests
│   └── e2e/                # End-to-end tests
└── Dockerfile              # Multi-stage container build
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

Apache 2.0 - See [LICENSE](LICENSE) for details.

## Acknowledgments

Built following best practices from:
- [MCP Specification](https://modelcontextprotocol.io/)
- [containers/kubernetes-mcp-server](https://github.com/containers/kubernetes-mcp-server)
- [argoproj-labs/mcp-for-argocd](https://github.com/argoproj-labs/mcp-for-argocd)
