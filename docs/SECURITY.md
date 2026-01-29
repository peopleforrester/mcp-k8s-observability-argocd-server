# Security Model

This document explains the defense-in-depth security architecture of the ArgoCD MCP Server.

---

## Design Philosophy

We designed this server with one principle in mind: **make it hard to do the wrong thing**.

In production environments, the cost of a mistake can be catastrophic. An LLM with unrestricted access to your GitOps tooling can:
- Delete production applications
- Sync untested changes
- Expose secrets in context windows
- Overwhelm your ArgoCD API with requests

This server implements multiple layers of protection to prevent these scenarios.

---

## Security Layers

### Layer 1: Read-Only Mode (Default)

**Environment Variable:** `MCP_READ_ONLY=true` (default)

When enabled, the server blocks ALL write operations. This is the default because:

- Most troubleshooting and monitoring tasks are read-only
- It prevents accidental syncs or changes during investigation
- It's the safest default for shared environments

**Blocked Operations:**
- `sync_application`
- `refresh_application`
- `delete_application`
- Any future write operations

**Error Response:**
```
OPERATION BLOCKED: sync_application
Reason: Server is running in read-only mode
Setting: MCP_READ_ONLY
To enable: Set MCP_READ_ONLY=false in server configuration
```

**Recommendation:** Keep read-only mode enabled unless you explicitly need to perform write operations. When you do need writes, consider using a separate MCP server instance with write access.

---

### Layer 2: Non-Destructive Mode (Default)

**Environment Variable:** `MCP_DISABLE_DESTRUCTIVE=true` (default)

Even when write operations are enabled, destructive operations remain blocked by default. This is an additional safety layer because:

- Syncs can be undone; deletes often cannot
- Prune operations can cascade unexpectedly
- These operations warrant extra friction

**Blocked Operations:**
- `delete_application`
- `sync_application` with `prune=true`
- Any operation that removes resources from the cluster

**Error Response:**
```
OPERATION BLOCKED: delete_application
Reason: Destructive operations are disabled
Setting: MCP_DISABLE_DESTRUCTIVE
To enable: Set MCP_DISABLE_DESTRUCTIVE=false in server configuration
```

**Recommendation:** Only disable this in environments where deletion is explicitly required, and even then, consider using the audit log.

---

### Layer 3: Confirmation Patterns

For destructive operations, even when enabled, we require explicit confirmation. This prevents accidental execution.

**Confirmation Requirements:**

1. `confirm=true` - Explicit boolean confirmation
2. `confirm_name` matching the target resource name exactly

**Why two parameters?** This prevents:
- Copy-paste errors where `confirm=true` is accidentally included
- Auto-complete issues
- Fat-finger mistakes

**Example:**
```python
# This will fail
delete_application(name="production-app", confirm=true)

# This will also fail
delete_application(name="production-app", confirm=true, confirm_name="prod-app")

# This will work
delete_application(name="production-app", confirm=true, confirm_name="production-app")
```

**Confirmation Response:**
```
CONFIRMATION REQUIRED: delete_application

Target: production-app
Impact: Application and all managed resources will be PERMANENTLY DELETED

Details:
  namespace: production
  cluster: https://prod.k8s.example.com
  cascade: true
  effect: DELETE cluster resources

To proceed, set confirm=true AND confirm_name='production-app'
```

The response includes details about the impact so users can make informed decisions.

---

### Layer 4: Single-Cluster Mode

**Environment Variable:** `MCP_SINGLE_CLUSTER=false` (default)

When enabled, restricts operations to the default (in-cluster) cluster only. This is useful for:

- Environments where cross-cluster access is not desired
- Reducing blast radius
- Compliance requirements

**Error Response:**
```
OPERATION BLOCKED: sync_application
Reason: Operation on cluster 'prod-external' blocked in single-cluster mode
Setting: MCP_SINGLE_CLUSTER
To enable: Set MCP_SINGLE_CLUSTER=false in server configuration
```

---

### Layer 5: Rate Limiting

**Environment Variables:**
- `MCP_RATE_LIMIT_CALLS=100` (default)
- `MCP_RATE_LIMIT_WINDOW=60` (default, seconds)

Prevents runaway loops or excessive API usage:

- Protects ArgoCD API from overload
- Prevents context window exhaustion from rapid polling
- Limits damage from misconfigured automation

**Implementation:**
- Sliding window rate limiter
- Per-operation tracking
- Separate limits for read and write operations

**Error Response:**
```
OPERATION BLOCKED: list_applications
Reason: Rate limit exceeded
Setting: MCP_RATE_LIMIT_CALLS
To enable: Adjust MCP_RATE_LIMIT_CALLS in server configuration
```

---

### Layer 6: Secret Masking

**Environment Variable:** `MCP_MASK_SECRETS=true` (default)

Automatically redacts sensitive values from all output:

**Masked Patterns:**
- `token`, `password`, `secret`, `api_key` (and variations)
- Bearer tokens
- Authorization headers

**Example:**
```
# Before masking
{"token": "eyJhbGciOiJIUzI1NiIsInR5..."}

# After masking
{"token": "***MASKED***"}
```

**Why this matters:** LLM context windows are often logged, cached, or used for training. Secrets in output can leak.

**Recommendation:** Never disable this in production. Only disable for debugging in isolated environments.

---

### Layer 7: Audit Logging

**Environment Variable:** `MCP_AUDIT_LOG=/path/to/audit.log` (disabled by default)

When enabled, logs every operation to a structured JSON file:

**Logged Information:**
- Timestamp
- Operation name
- Target resource
- User/agent identifier
- Result (success/failure/blocked)
- Additional context (dry_run, parameters)

**Log Format:**
```json
{
  "timestamp": "2024-01-15T14:32:00Z",
  "operation": "sync_application",
  "target": "backend-api",
  "result": "success",
  "dry_run": false,
  "correlation_id": "req-abc123"
}
```

**Use Cases:**
- Compliance auditing
- Incident investigation
- Usage analytics
- Debugging

---

## Security Configuration Matrix

| Use Case | `READ_ONLY` | `DISABLE_DESTRUCTIVE` | Recommended |
|----------|------------|----------------------|-------------|
| Monitoring/Troubleshooting | `true` | `true` | Yes |
| Read + Sync | `false` | `true` | Common |
| Full Access | `false` | `false` | Rare |
| Production | `true` | `true` | Yes |
| Staging | `false` | `true` | Yes |
| Development | `false` | `false` | OK |

---

## Token Security

### Minimal Permissions

Create ArgoCD API tokens with minimal required permissions:

**Read-Only Token:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  accounts.mcp-readonly: apiKey
  accounts.mcp-readonly.enabled: "true"

---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: mcp-readonly
  namespace: argocd
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: argocd-readonly
subjects:
  - kind: ServiceAccount
    name: mcp-readonly
    namespace: argocd
```

**Read + Sync Token:**
```yaml
# Add sync permissions only
policy.csv: |
  p, mcp-sync, applications, get, */*, allow
  p, mcp-sync, applications, sync, */*, allow
  p, mcp-sync, clusters, get, *, allow
  p, mcp-sync, projects, get, *, allow
```

### Token Rotation

- Tokens should be rotated regularly
- Use short-lived tokens where possible
- Consider using Kubernetes ServiceAccount tokens with OIDC

---

## Network Security

### TLS Configuration

**Environment Variable:** `ARGOCD_INSECURE=false` (default)

- Always use TLS in production
- Only set `ARGOCD_INSECURE=true` for local development with self-signed certs
- Consider using a trusted CA or cert-manager

### Network Policies

Consider restricting network access to the MCP server:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: mcp-server-policy
spec:
  podSelector:
    matchLabels:
      app: argocd-mcp-server
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: claude-desktop
  egress:
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: argocd-server
      ports:
        - port: 443
```

---

## Threat Model

### Threats and Mitigations

| Threat | Mitigation |
|--------|------------|
| LLM deletes production app | Read-only default + destructive protection + confirmation pattern |
| Token exposure in context | Secret masking enabled by default |
| API overload | Rate limiting |
| Unintended sync | Dry-run by default |
| Cross-cluster access | Single-cluster mode option |
| Audit trail gap | Audit logging option |
| Prune accident | Prune requires explicit enable + is treated as destructive |

### Residual Risks

Even with all protections, some risks remain:

1. **Valid confirmations**: If a user explicitly confirms a destructive operation with the correct name, it will execute
2. **Compromised tokens**: Token security is outside the scope of this server
3. **ArgoCD vulnerabilities**: This server depends on ArgoCD's security
4. **LLM context sharing**: Masked output may still be processed by the LLM

---

## Best Practices

### For Production

1. **Use read-only mode** for most MCP server instances
2. **Enable audit logging** for compliance and investigation
3. **Use minimal-permission tokens** scoped to required operations
4. **Deploy separate instances** for read-only vs. write access
5. **Monitor rate limits** and adjust based on usage patterns

### For Development

1. **Use `ARGOCD_INSECURE=true`** only with local clusters
2. **Enable write access** but keep destructive protection on
3. **Use test applications** not connected to real workloads

### For Shared Environments

1. **Keep read-only mode enabled** for the shared instance
2. **Create per-team tokens** with scoped permissions
3. **Enable audit logging** for accountability
4. **Consider single-cluster mode** to limit blast radius

---

## Configuration Examples

### Maximum Security (Production)

```bash
export ARGOCD_URL=https://argocd.example.com
export ARGOCD_TOKEN=readonly-token
export MCP_READ_ONLY=true
export MCP_DISABLE_DESTRUCTIVE=true
export MCP_SINGLE_CLUSTER=true
export MCP_MASK_SECRETS=true
export MCP_AUDIT_LOG=/var/log/argocd-mcp/audit.log
export MCP_RATE_LIMIT_CALLS=50
```

### Balanced Security (Staging)

```bash
export ARGOCD_URL=https://argocd-staging.example.com
export ARGOCD_TOKEN=sync-token
export MCP_READ_ONLY=false
export MCP_DISABLE_DESTRUCTIVE=true
export MCP_MASK_SECRETS=true
export MCP_AUDIT_LOG=/var/log/argocd-mcp/audit.log
```

### Development

```bash
export ARGOCD_URL=https://localhost:8080
export ARGOCD_TOKEN=admin-token
export ARGOCD_INSECURE=true
export MCP_READ_ONLY=false
export MCP_DISABLE_DESTRUCTIVE=false
```

---

## Reporting Security Issues

If you discover a security vulnerability, please report it privately to the maintainers rather than opening a public issue.

Email: security@example.com

We will respond within 48 hours and work with you to understand and address the issue.
