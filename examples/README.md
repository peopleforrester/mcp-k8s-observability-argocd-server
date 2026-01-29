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

The `claude-desktop-multi-env.json` example shows how to configure multiple ArgoCD instances. Each instance appears as a separate MCP server in Claude:

- `argocd-prod` - Read-only access to production
- `argocd-staging` - Write access to staging

Claude will show both servers and can query either one based on context.

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
