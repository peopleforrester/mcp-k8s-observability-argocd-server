# Example Configurations

This directory contains example Claude Desktop configurations for various use cases.

## Files

| File | Use Case | Write Access | Destructive Access |
|------|----------|--------------|-------------------|
| `claude-desktop-basic.json` | Default read-only monitoring | No | No |
| `claude-desktop-write-enabled.json` | Sync and refresh operations | Yes | No |
| `claude-desktop-full-access.json` | Complete access (use carefully!) | Yes | Yes |
| `claude-desktop-multi-env.json` | Separate prod/staging instances | Mixed | No |
| `claude-desktop-docker.json` | Using Docker instead of uvx | No | No |
| `claude-desktop-local-dev.json` | Local Kind cluster development | Yes | Yes |

## Usage

1. Copy the appropriate example to your Claude Desktop config location:
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **Linux**: `~/.config/Claude/claude_desktop_config.json`

2. Replace placeholder values:
   - `https://argocd.example.com` -> Your ArgoCD URL
   - `your-api-token-here` -> Your ArgoCD API token

3. Restart Claude Desktop

## Getting an ArgoCD API Token

### Method 1: ArgoCD CLI

```bash
# Login to ArgoCD
argocd login argocd.example.com

# Generate API token
argocd account generate-token --account admin
```

### Method 2: ArgoCD UI

1. Go to Settings -> Accounts
2. Select your account
3. Click "Generate New Token"

### Method 3: Kubernetes Secret

```bash
# Get the initial admin password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d
```

## Security Recommendations

### Production

Use `claude-desktop-basic.json` or `claude-desktop-multi-env.json` with:
- `MCP_READ_ONLY=true`
- `MCP_DISABLE_DESTRUCTIVE=true`
- `MCP_AUDIT_LOG` enabled

### Staging

Use `claude-desktop-write-enabled.json` with:
- `MCP_READ_ONLY=false`
- `MCP_DISABLE_DESTRUCTIVE=true`
- `MCP_AUDIT_LOG` enabled

### Development

Use `claude-desktop-local-dev.json` with full access for rapid iteration.

## Multi-Instance Setup

There are two ways to talk to more than one ArgoCD instance from Claude. Pick whichever matches your operational model.

### Option A: One MCP server per instance (recommended)

The `claude-desktop-multi-env.json` example uses this pattern. Each instance appears as a separate MCP server entry in Claude, so each carries its own credentials and security profile:

- `argocd-prod` - Read-only access to production
- `argocd-staging` - Write access to staging

Claude lists both servers and can query either based on context. This is the simplest operational model and the right default — separate processes, separate environment variables, separate audit logs.

### Option B: A single MCP server backed by multiple instances

If you prefer one process that fans out to several ArgoCD endpoints, set `ARGOCD_URL` / `ARGOCD_TOKEN` for the primary instance and add `ARGOCD_MCP_ADDITIONAL_INSTANCES__N__*` for each extra one (Pydantic-settings nested-env syntax with `__` as the delimiter):

```json
{
  "mcpServers": {
    "argocd": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/argocd-mcp-server", "argocd-mcp"],
      "env": {
        "ARGOCD_URL": "https://argocd-prod.example.com",
        "ARGOCD_TOKEN": "prod-token",

        "ARGOCD_MCP_ADDITIONAL_INSTANCES__0__URL": "https://argocd-dr.example.com",
        "ARGOCD_MCP_ADDITIONAL_INSTANCES__0__TOKEN": "dr-token",
        "ARGOCD_MCP_ADDITIONAL_INSTANCES__0__NAME": "dr",

        "ARGOCD_MCP_ADDITIONAL_INSTANCES__1__URL": "https://argocd-dev.example.com",
        "ARGOCD_MCP_ADDITIONAL_INSTANCES__1__TOKEN": "dev-token",
        "ARGOCD_MCP_ADDITIONAL_INSTANCES__1__NAME": "dev"
      }
    }
  }
}
```

Tools accept an `instance` parameter (defaults to `"primary"`) to pick which ArgoCD to talk to. The names you set in `__NAME` are what the agent passes (e.g. `list_applications(instance="dr")`).

Caveats:
- All instances share one set of `MCP_READ_ONLY` / `MCP_DISABLE_DESTRUCTIVE` / `MCP_SINGLE_CLUSTER` settings. If you need different security postures per instance, use Option A.
- Audit logs land in a single file. If you need per-instance audit trails, use Option A.

## Troubleshooting

### "Server not responding"

1. Check that ArgoCD URL is accessible
2. Verify token is valid: `curl -H "Authorization: Bearer $TOKEN" $ARGOCD_URL/api/v1/applications`
3. Check for TLS issues: try `ARGOCD_INSECURE=true` temporarily

### "Permission denied"

1. Verify token has required permissions
2. Check ArgoCD RBAC policies
3. Ensure `MCP_READ_ONLY=false` for write operations

### "Rate limit exceeded"

Increase rate limits:
```json
"env": {
  "MCP_RATE_LIMIT_CALLS": "200",
  "MCP_RATE_LIMIT_WINDOW": "60"
}
```
