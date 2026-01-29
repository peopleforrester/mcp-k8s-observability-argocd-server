# Tool Reference

Complete documentation for all ArgoCD MCP Server tools.

---

## Tool Tiers Overview

Tools are organized into three tiers based on their potential impact:

| Tier | Access Control | Risk Level | Examples |
|------|---------------|------------|----------|
| **Tier 1: Read** | Always available | None | `list_applications`, `diagnose_sync_failure` |
| **Tier 2: Write** | Requires `MCP_READ_ONLY=false` | Moderate | `sync_application`, `refresh_application` |
| **Tier 3: Destructive** | Requires confirmation + name match | High | `delete_application` |

---

## Tier 1: Read Operations

These tools are always available and never modify cluster state.

### list_applications

List ArgoCD applications with optional filtering.

**When to use:** Get an overview of applications, find unhealthy apps, or check a specific project.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `project` | string | No | None | Filter by ArgoCD project name |
| `health_status` | string | No | None | Filter by health: `Healthy`, `Degraded`, `Progressing`, `Missing`, `Unknown` |
| `sync_status` | string | No | None | Filter by sync: `Synced`, `OutOfSync`, `Unknown` |
| `instance` | string | No | `"primary"` | ArgoCD instance name for multi-instance setups |

**Example Usage:**

```
# List all applications
list_applications()

# Find degraded applications in production
list_applications(project="prod", health_status="Degraded")

# Find applications out of sync
list_applications(sync_status="OutOfSync")
```

**Example Response:**

```
Found 3 application(s):

- frontend [prod] health=Healthy sync=Synced dest=frontend@https://prod.k8s.example.com
- backend-api [prod] health=Degraded sync=OutOfSync dest=backend@https://prod.k8s.example.com
- worker-service [prod] health=Progressing sync=Synced dest=workers@https://prod.k8s.example.com
```

---

### get_application

Get detailed information about a specific ArgoCD application.

**When to use:** Deep dive into a single application's configuration, source, and status.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | Yes | - | Application name |
| `instance` | string | No | `"primary"` | ArgoCD instance name |

**Example Usage:**

```
get_application(name="backend-api")
```

**Example Response:**

```
Application: backend-api
Project: prod
Namespace: argocd

Source:
  Repository: https://github.com/example/backend
  Path: kubernetes/overlays/prod
  Target Revision: main

Destination:
  Server: https://prod.k8s.example.com
  Namespace: backend

Status:
  Sync: OutOfSync
  Health: Degraded

Last Operation:
  Phase: Failed
  Message: one or more objects failed to apply

Conditions:
  - [SyncError] Failed to sync: resource backend-deployment: container crashed
```

---

### get_application_status

Quick health and sync status check.

**When to use:** Fast status check when you don't need full details. Lower overhead than `get_application`.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | Yes | - | Application name |
| `instance` | string | No | `"primary"` | ArgoCD instance name |

**Example Usage:**

```
get_application_status(name="backend-api")
```

**Example Response:**

```
Application: backend-api
Health: Degraded
Sync: OutOfSync
```

---

### get_application_diff

Preview what would change on sync (dry-run diff).

**When to use:** Before syncing, to understand the impact. Essential for change management.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | Yes | - | Application name |
| `revision` | string | No | None | Target revision to diff against (defaults to target revision) |
| `instance` | string | No | `"primary"` | ArgoCD instance name |

**Example Usage:**

```
# Diff against current target revision
get_application_diff(name="backend-api")

# Diff against specific commit
get_application_diff(name="backend-api", revision="abc123f")
```

**Example Response:**

```
Diff for application 'backend-api':

Resources to CREATE (1):
  + ConfigMap/new-feature-flags

Resources to UPDATE (2):
  ~ Deployment/backend-deployment
  ~ Service/backend-service

Resources to DELETE (with prune) (1):
  - ConfigMap/deprecated-config

Resources in sync: 8
```

---

### get_application_history

View deployment history with commit info and timestamps.

**When to use:** Understanding recent changes, finding rollback targets, auditing deployments.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | Yes | - | Application name |
| `limit` | integer | No | `10` | Maximum number of history entries (1-50) |
| `instance` | string | No | `"primary"` | ArgoCD instance name |

**Example Usage:**

```
get_application_history(name="backend-api", limit=5)
```

**Example Response:**

```
Deployment history for 'backend-api' (last 5 entries):

1. [a3f8c21] at 2024-01-15T14:32:00Z by john.doe
2. [b7d9e12] at 2024-01-15T10:15:00Z by jane.smith
3. [c2a4f56] at 2024-01-14T16:45:00Z by deploy-bot
4. [d8b3c78] at 2024-01-14T09:20:00Z by john.doe
5. [e1f5g90] at 2024-01-13T18:00:00Z by jane.smith
```

---

### diagnose_sync_failure

AI-powered troubleshooting with actionable suggestions.

**When to use:** When an application is failing and you need to understand why. This is the "fix my app" tool.

**What it does:**
1. Fetches application status
2. Gathers resource conditions from the resource tree
3. Collects Kubernetes events
4. Analyzes for common failure patterns
5. Provides actionable suggestions

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | Yes | - | Application name |
| `instance` | string | No | `"primary"` | ArgoCD instance name |

**Example Usage:**

```
diagnose_sync_failure(name="backend-api")
```

**Example Response:**

```
Diagnosis for 'backend-api':

Found 5 issue(s):
  - Application is out of sync (revision: main)
  - Application health is Degraded
  - Last operation failed: one or more objects failed to apply
  - [SyncError] Failed to sync: resource backend-deployment: container crashed
  - Image pull failed: ImagePullBackOff for backend:v2.0.1

Suggestions:
  - Verify image exists and registry credentials are configured
  - Check pod logs for application startup errors
  - Run get_application_diff to see pending changes
```

**Detected Patterns:**

| Pattern | Detection | Suggestion |
|---------|-----------|------------|
| `ImagePullBackOff` | Image pull failure events | Verify image exists and credentials |
| `CrashLoopBackOff` | Container crashing repeatedly | Check pod logs for startup errors |
| `Forbidden/unauthorized` | RBAC issues | Review ServiceAccount permissions |
| `OOMKilled` | Memory limit exceeded | Increase limits or optimize app |
| `PodUnschedulable` | No available nodes | Check cluster capacity |

---

### list_clusters

List registered Kubernetes clusters with health status.

**When to use:** Understanding the ArgoCD environment, troubleshooting connectivity issues.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `instance` | string | No | `"primary"` | ArgoCD instance name |

**Example Usage:**

```
list_clusters()
```

**Example Response:**

```
Found 3 cluster(s):

- in-cluster: https://kubernetes.default.svc... [Successful]
- prod-us-east: https://prod-east.k8s.example.com:6443... [Successful]
- prod-eu-west: https://prod-west.k8s.example.com:6443... [Failed]
```

---

### list_projects

List ArgoCD projects.

**When to use:** Understanding project organization, finding project names for filtering.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `instance` | string | No | `"primary"` | ArgoCD instance name |

**Example Usage:**

```
list_projects()
```

**Example Response:**

```
Found 4 project(s):

- default: Default project for all applications
- prod: Production environment applications
- staging: Staging and QA applications
- infrastructure: Cluster infrastructure components
```

---

## Tier 2: Write Operations

These tools modify cluster state. Requires `MCP_READ_ONLY=false`.

### sync_application

Synchronize application with Git repository.

**When to use:** Deploying changes, forcing a resync, applying updates.

**Safety Features:**
- **Dry-run by default**: Set `dry_run=false` to actually apply
- **Prune protection**: Using `prune=true` triggers additional confirmation requirements
- **Audit logging**: All sync operations are logged

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | Yes | - | Application name |
| `dry_run` | boolean | No | `true` | Preview changes without applying |
| `prune` | boolean | No | `false` | Delete resources not in Git (destructive!) |
| `force` | boolean | No | `false` | Force sync even if already synced |
| `revision` | string | No | None | Git revision to sync to |
| `instance` | string | No | `"primary"` | ArgoCD instance name |

**Example Usage:**

```
# Preview sync (default behavior)
sync_application(name="backend-api")

# Actually sync
sync_application(name="backend-api", dry_run=false)

# Sync to specific revision
sync_application(name="backend-api", dry_run=false, revision="abc123f")

# Force sync even if already synced
sync_application(name="backend-api", dry_run=false, force=true)
```

**Example Response (dry-run):**

```
Dry-run sync complete for 'backend-api'

Operation would affect resources. To apply:
  sync_application(name='backend-api', dry_run=false)
```

**Example Response (actual sync):**

```
Sync initiated for 'backend-api'
Revision: HEAD
Prune: false

Use get_application_status to monitor progress.
```

**Note on Prune:** Using `prune=true` is considered a destructive operation because it DELETES resources from the cluster that are not present in Git. This requires:
1. `MCP_READ_ONLY=false`
2. `MCP_DISABLE_DESTRUCTIVE=false`
3. Running the operation through the destructive confirmation flow

---

### refresh_application

Force manifest refresh from Git.

**When to use:** When you've pushed changes to Git and want ArgoCD to pick them up immediately.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | Yes | - | Application name |
| `hard` | boolean | No | `false` | Force hard refresh (invalidate cache) |
| `instance` | string | No | `"primary"` | ArgoCD instance name |

**Example Usage:**

```
# Normal refresh
refresh_application(name="backend-api")

# Hard refresh (invalidate cache)
refresh_application(name="backend-api", hard=true)
```

**Example Response:**

```
Refresh triggered for 'backend-api' (normal)
Current status: health=Healthy, sync=OutOfSync
```

---

## Tier 3: Destructive Operations

These tools can cause data loss. Requires `MCP_DISABLE_DESTRUCTIVE=false` AND explicit confirmation.

### delete_application

Delete an ArgoCD application (DESTRUCTIVE).

**When to use:** Removing an application from ArgoCD management. Use with extreme caution.

**Safety Features:**
- Requires `MCP_READ_ONLY=false`
- Requires `MCP_DISABLE_DESTRUCTIVE=false`
- Requires `confirm=true`
- Requires `confirm_name` matching the application name exactly

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | Yes | - | Application name to delete |
| `cascade` | boolean | No | `true` | Delete application resources from cluster |
| `confirm` | boolean | No | `false` | Must be `true` to execute |
| `confirm_name` | string | No | None | Must match `name` exactly |
| `instance` | string | No | `"primary"` | ArgoCD instance name |

**Example Usage:**

```
# This will fail (no confirmation)
delete_application(name="old-app")

# This will also fail (confirm_name doesn't match)
delete_application(name="old-app", confirm=true, confirm_name="wrong-name")

# This will work
delete_application(name="old-app", confirm=true, confirm_name="old-app")

# Orphan resources (don't delete from cluster)
delete_application(name="old-app", confirm=true, confirm_name="old-app", cascade=false)
```

**Example Response (no confirmation):**

```
CONFIRMATION REQUIRED: delete_application

Target: old-app
Impact: Application and all managed resources will be PERMANENTLY DELETED

Details:
  namespace: backend
  cluster: https://prod.k8s.example.com
  cascade: true
  effect: DELETE cluster resources

To proceed, set confirm=true AND confirm_name='old-app'
```

**Example Response (confirmed):**

```
Application 'old-app' deleted successfully.
Cascade: true
```

---

## MCP Resources

In addition to tools, the server exposes MCP resources for context.

### argocd://instances

Returns information about configured ArgoCD instances.

**Example:**

```
Configured ArgoCD Instances:

- primary: https://argocd-prod.example.com
- staging: https://argocd-staging.example.com
```

### argocd://security

Returns current security settings.

**Example:**

```
Security Settings:
  Read-only mode: true
  Destructive operations disabled: true
  Single cluster mode: false
  Secret masking: true
  Rate limit: 100 calls per 60s
```

---

## Error Handling

All tools return structured error messages when operations fail:

```
ArgoCD API error (404): Application 'nonexistent-app' not found

Suggestions:
  - Check application name spelling
  - Use list_applications() to see available applications
  - Verify you have access to the target project
```

### Common Error Codes

| Code | Meaning | Common Cause |
|------|---------|--------------|
| 401 | Unauthorized | Token expired or invalid |
| 403 | Forbidden | Insufficient RBAC permissions |
| 404 | Not Found | Application or resource doesn't exist |
| 409 | Conflict | Operation already in progress |
| 500 | Server Error | ArgoCD internal error |

### Rate Limiting

If you exceed the rate limit:

```
OPERATION BLOCKED: list_applications
Reason: Rate limit exceeded
Setting: MCP_RATE_LIMIT_CALLS
To enable: Adjust MCP_RATE_LIMIT_CALLS in server configuration
```

---

## Best Practices

1. **Always check status before syncing**
   ```
   get_application_status(name="app") -> sync_application(name="app", dry_run=false)
   ```

2. **Preview changes before applying**
   ```
   get_application_diff(name="app") -> sync_application(name="app", dry_run=false)
   ```

3. **Use diagnose_sync_failure for troubleshooting**
   Instead of manually checking logs, events, and conditions.

4. **Specify project filters when listing**
   Reduces noise and improves response times for large installations.

5. **Use history for rollback decisions**
   ```
   get_application_history(name="app") -> rollback to known-good revision
   ```
