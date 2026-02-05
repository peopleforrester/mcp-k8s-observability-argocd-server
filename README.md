```
     _____                  _____ ____    __  __  _____ _____
    /  _  \_______ _____   / ____|  _ \  |  \/  |/ ____| __ \
   /  /_\  \_  __ \_  __ \| |    | | | | | \  / | |    |  _) |
  /    |    \  | \/ | | | | |    | |_| | | |\/| | |    |  __/
  \____|____/__|    |_| |_|\_____|____/  |_|  |_|\_____|_|

         ╔═══════════════════════════════════════╗
         ║  S A F E T Y   F I R S T   G I T O P S ║
         ╚═══════════════════════════════════════╝
```

# ArgoCD MCP Server

**Safety-first GitOps operations for ArgoCD via the Model Context Protocol.**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-1.26%2B-green.svg)](https://modelcontextprotocol.io/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](https://mypy-lang.org/)
[![Pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

---

## Why This Exists

> *"95% of MCP servers are garbage."*

We built this because we were tired of:

**The Empty Error Message Problem.** You sync an app. It fails. The error? "Sync failed." Thanks, very helpful. Meanwhile, the actual cause is buried across three different Kubernetes events, two pod logs, and a misconfigured HPA that nobody told you about. Our `diagnose_sync_failure` tool aggregates all of that into one coherent analysis.

**The "Oops, I Deleted Production" Problem.** Most MCP servers treat every operation the same. Read a deployment? Same as deleting a namespace! We implement **defense-in-depth**: read-only by default, writes require explicit opt-in, destructive operations require typing the resource name twice. Because at 3 AM, you don't need an LLM with root access to your production cluster.

**The YAML Fatigue Problem.** When you have 47 applications across 12 clusters, the ArgoCD UI becomes a slideshow. We built this for SREs who live in terminals and need answers fast: "What's broken in prod?" should return an answer, not a loading spinner.

**The Context Window Problem.** MCP servers that dump entire manifests into the context are doing it wrong. We use **progressive disclosure**: simple status first, details on request, full manifests only when you explicitly ask. Your context window is precious real estate.

---

## Quick Demo

Here's what a conversation looks like:

```
You: What applications are failing in production?

Claude: Let me check the production applications for you.

[calls list_applications(health_status="Degraded", project="prod")]

Found 2 application(s):

- payment-service [prod] health=Degraded sync=OutOfSync dest=payments@https://prod.k8s...
- notification-api [prod] health=Degraded sync=Synced dest=notifications@https://prod.k8s...

The payment-service is both unhealthy AND out of sync. Want me to diagnose what's wrong?
```

```
You: Why is payment-service broken?

Claude: I'll run a full diagnosis.

[calls diagnose_sync_failure(name="payment-service")]

Diagnosis for 'payment-service':

Found 4 issue(s):
  - Application is out of sync (revision: abc123f)
  - [SyncError] Failed to sync: resource payment-deployment: container crashed
  - Image pull failed: ImagePullBackOff for payments:v2.3.1
  - Found 2 unhealthy resources in resource tree
    - Deployment/payment-deployment: Container crashloopbackoff
    - Pod/payment-deployment-7f8b9-x2k4j: CrashLoopBackOff

Suggestions:
  - Verify image exists and registry credentials are configured
  - Check pod logs for application startup errors
  - Run get_application_diff to see pending changes

The image tag v2.3.1 doesn't seem to exist. Can you verify it was pushed to the registry?
```

```
You: Show me what would change if I sync it

Claude: [calls get_application_diff(name="payment-service")]

Diff for application 'payment-service':

Resources to UPDATE (3):
  ~ Deployment/payment-deployment
  ~ ConfigMap/payment-config
  ~ Service/payment-service

Resources in sync: 12

The sync would update the deployment (probably the image tag fix), update the
config, and touch the service. Want me to run the sync?
```

```
You: Yes, sync it

Claude: [calls sync_application(name="payment-service", dry_run=false)]

Sync initiated for 'payment-service'
Revision: HEAD
Prune: false

Use get_application_status to monitor progress.

I'll check the status in a moment to confirm it's progressing.
```

---

## Philosophy

### Progressive Disclosure

Not everything needs to be visible all the time. We tier our tools:

| Tier | Access | Examples |
|------|--------|----------|
| **Tier 1** | Always available | `list_applications`, `get_application_status`, `diagnose_sync_failure` |
| **Tier 2** | Requires `MCP_READ_ONLY=false` | `sync_application`, `refresh_application` |
| **Tier 3** | Requires confirmation + typing name | `delete_application` |

This isn't bureaucracy. This is respecting that production systems deserve more friction than `rm -rf /`.

### Dry-Run by Default

Every write operation defaults to preview mode. You have to explicitly say "yes, really do this" before anything changes. We learned this lesson from too many "I thought that was staging" incidents.

### Agent-Friendly Error Messages

```
# Bad (what most tools return)
Error: exit status 1

# Good (what we return)
ArgoCD API error (403): Application payment-service not found in project 'default'

Suggestions:
  - Check if application exists: list_applications(project="prod")
  - Verify you have access to the target project
```

Errors should tell you what went wrong AND what to try next.

---

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/peopleforrester/mcp-k8s-observability-argocd-server
cd mcp-k8s-observability-argocd-server

# Install with uv
uv sync
```

### Claude Desktop / Claude Code Configuration

Add to your Claude configuration (`~/.claude.json` for Claude Code):

```json
{
  "mcpServers": {
    "argocd": {
      "type": "stdio",
      "command": "/path/to/uv",
      "args": [
        "run",
        "--directory",
        "/path/to/mcp-k8s-observability-argocd-server",
        "argocd-mcp"
      ],
      "env": {
        "ARGOCD_URL": "https://argocd.example.com",
        "ARGOCD_TOKEN": "your-api-token",
        "ARGOCD_INSECURE": "false"
      }
    }
  }
}
```

**Note:** Replace `/path/to/uv` with the full path to your `uv` binary (run `which uv` to find it).

See [examples/](examples/) for more configuration options including multi-cluster setups.

### Docker

```bash
# Build the image
docker build -t argocd-mcp-server .

# Run with environment variables
docker run -e ARGOCD_URL=https://argocd.example.com \
           -e ARGOCD_TOKEN=your-token \
           argocd-mcp-server:latest
```

### Running Directly

```bash
# Set environment variables
export ARGOCD_URL=https://argocd.example.com
export ARGOCD_TOKEN=your-token

# Run the server
uv run argocd-mcp
```

---

## Security Model

We don't just check permissions. We make it hard to do the wrong thing.

| Layer | Environment Variable | Default | What It Does |
|-------|---------------------|---------|--------------|
| Read-only Mode | `MCP_READ_ONLY` | `true` | Blocks ALL write operations. You can look, but you cannot touch. |
| Non-destructive Mode | `MCP_DISABLE_DESTRUCTIVE` | `true` | Blocks delete/prune even if writes enabled. Deletes require this AND read-only off. |
| Single-cluster Mode | `MCP_SINGLE_CLUSTER` | `false` | Restricts operations to the default cluster. For when multi-cluster access is too scary. |
| Audit Logging | `MCP_AUDIT_LOG` | (disabled) | Logs every operation to a file. For when you need to know who did what. |
| Secret Masking | `MCP_MASK_SECRETS` | `true` | Redacts tokens, passwords, and API keys from output. Always on unless you're debugging. |
| Rate Limiting | `MCP_RATE_LIMIT_CALLS` | `100` | Max API calls per minute. Prevents runaway loops from eating your ArgoCD API. |

### Enabling Write Operations (Carefully)

```bash
# Enable writes (still blocks destructive operations)
export MCP_READ_ONLY=false

# Enable destructive operations (delete, prune) - DANGER ZONE
export MCP_DISABLE_DESTRUCTIVE=false
```

For the full security model deep-dive, see [docs/SECURITY.md](docs/SECURITY.md).

---

## Tool Reference

### Tier 1: Essential Read Operations (Always Available)

| Tool | What It Does |
|------|--------------|
| `list_applications` | List apps with filtering by project, health, or sync status. The "show me what's on fire" tool. |
| `get_application` | Get detailed app info: source, destination, status. The deep dive. |
| `get_application_status` | Quick health/sync check. Fast and cheap. |
| `get_application_diff` | Preview what would change on sync. Look before you leap. |
| `get_application_history` | View deployment history with commits. "What changed and when?" |
| `diagnose_sync_failure` | AI-powered troubleshooting. Aggregates logs, events, status into actionable analysis. |
| `get_application_logs` | Get pod logs for debugging. Filter by pod, container, and time range. |
| `list_clusters` | List registered clusters with connection status. |
| `list_projects` | List ArgoCD projects. |

### Tier 2: Write Operations (Require `MCP_READ_ONLY=false`)

| Tool | What It Does |
|------|--------------|
| `sync_application` | Sync with dry-run default. Set `dry_run=false` to actually apply. |
| `refresh_application` | Force manifest refresh from Git. "Did you push? Let me check again." |
| `rollback_application` | Rollback to a previous deployment. Dry-run by default. |
| `terminate_sync` | Stop a running sync operation. For when syncs get stuck. |

### Tier 3: Destructive Operations (Require explicit confirmation)

| Tool | What It Does |
|------|--------------|
| `delete_application` | Delete application. Requires `confirm=true` AND `confirm_name` matching the app name. We make you type it twice for a reason. |

For detailed parameter documentation, see [docs/TOOLS.md](docs/TOOLS.md).

---

## Example Conversations

**"What applications are failing in production?"**
```
list_applications(health_status="Degraded", project="prod")
```

**"Why is my-app not syncing?"**
```
diagnose_sync_failure(name="my-app")
```

**"Deploy the latest changes to staging"**
```
sync_application(name="my-app", dry_run=false)
```

**"Show me what would change if I sync"**
```
get_application_diff(name="my-app")
```

**"What was deployed last week?"**
```
get_application_history(name="my-app", limit=20)
```

---

## Configuration Reference

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ARGOCD_URL` | ArgoCD server URL | (required) |
| `ARGOCD_TOKEN` | ArgoCD API token | (required) |
| `ARGOCD_INSECURE` | Skip TLS verification (dev only!) | `false` |
| `MCP_READ_ONLY` | Block write operations | `true` |
| `MCP_DISABLE_DESTRUCTIVE` | Block delete/prune | `true` |
| `MCP_SINGLE_CLUSTER` | Restrict to default cluster | `false` |
| `MCP_AUDIT_LOG` | Path to audit log file | (disabled) |
| `MCP_RATE_LIMIT_CALLS` | Max API calls per window | `100` |
| `MCP_RATE_LIMIT_WINDOW` | Rate limit window (seconds) | `60` |
| `ARGOCD_MCP_LOG_LEVEL` | Logging level | `INFO` |

### Multi-Instance Configuration

For managing multiple ArgoCD instances (multi-cluster, multi-environment):

```bash
# Primary instance
export ARGOCD_URL=https://argocd-prod.example.com
export ARGOCD_TOKEN=prod-token

# Additional instances can be configured programmatically
# See examples/multi-cluster.json
```

---

## Development

### Prerequisites

- Python 3.11, 3.12, or 3.13
- uv (recommended) or pip
- Docker (for container builds)
- Kind 0.31+ (for local Kubernetes testing)

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

**Important**: Kubernetes 1.35+ requires cgroups v2. Check your cgroup version:
```bash
docker info | grep "Cgroup Version"
```

- **Cgroup Version: 2** - Use Kubernetes 1.35 (default in Kind 0.31+)
- **Cgroup Version: 1** - Use Kubernetes 1.34.x (WSL2 default, older Docker)

```bash
# Auto-detect cgroup version and create cluster
./scripts/setup-test-cluster.sh

# Or manually with specific version:
# For cgroups v2 (recommended):
kind create cluster --name argocd-mcp-test --image kindest/node:v1.35.0

# For cgroups v1 (WSL2/older Docker):
kind create cluster --name argocd-mcp-test --image kindest/node:v1.34.3

# Install ArgoCD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for ArgoCD to be ready
kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd

# Get ArgoCD admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d

# Port forward
kubectl port-forward svc/argocd-server -n argocd 8080:443
```

---

## Architecture

```
argocd-mcp-server/
├── src/argocd_mcp/
│   ├── server.py           # FastMCP server with all tools and resources
│   ├── config.py           # Configuration management (pydantic-settings)
│   ├── tools/              # Reserved for future tool modularization
│   ├── resources/          # Reserved for future resource modularization
│   └── utils/
│       ├── client.py       # ArgoCD API client with retry logic
│       ├── safety.py       # Confirmation patterns, rate limiting
│       └── logging.py      # Structured logging, audit trail
├── tests/
│   ├── unit/               # Unit tests
│   └── integration/        # Integration tests (Kind cluster)
├── docs/
│   ├── TOOLS.md            # Detailed tool documentation
│   └── SECURITY.md         # Security model deep-dive
├── examples/               # Example configurations
└── Dockerfile              # Multi-stage container build
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

---

## License

Apache 2.0 - See [LICENSE](LICENSE) for details.

---

## Acknowledgments

Built on the shoulders of:
- [MCP Specification](https://modelcontextprotocol.io/) - The protocol that makes this possible
- [containers/kubernetes-mcp-server](https://github.com/containers/kubernetes-mcp-server) - Inspiration for safety patterns
- [argoproj-labs/mcp-for-argocd](https://github.com/argoproj-labs/mcp-for-argocd) - The official (but less opinionated) option

---

*Built by SREs, for SREs. Because production deserves better than "LGTM, ship it."*
