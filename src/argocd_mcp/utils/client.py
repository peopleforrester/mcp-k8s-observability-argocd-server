# ABOUTME: ArgoCD API client wrapper with retry logic and error handling
# ABOUTME: Provides async interface to ArgoCD REST API with structured responses

"""
ArgoCD API client with retry logic and structured error handling.

=============================================================================
WHAT IS THIS FILE?
=============================================================================

This module provides the HTTP client for communicating with ArgoCD's REST API.
It handles:

1. HTTP COMMUNICATION: Making requests to ArgoCD endpoints
2. AUTHENTICATION: Attaching Bearer tokens to requests
3. ERROR HANDLING: Converting HTTP errors to structured Python exceptions
4. RETRY LOGIC: Automatically retrying failed requests
5. SECRET MASKING: Hiding sensitive data in API responses

=============================================================================
ARGOCD REST API OVERVIEW
=============================================================================

ArgoCD exposes a REST API at /api/v1/ with endpoints like:

    GET  /api/v1/applications          - List all applications
    GET  /api/v1/applications/{name}   - Get specific application
    POST /api/v1/applications/{name}/sync - Trigger sync
    DELETE /api/v1/applications/{name} - Delete application

Authentication is via Bearer token in the Authorization header:
    Authorization: Bearer <token>

Responses are JSON. Errors include:
    {"message": "error description", "error": "additional details"}

=============================================================================
ASYNC/AWAIT EXPLAINED
=============================================================================

This client uses ASYNC/AWAIT for non-blocking I/O. Here's why it matters:

SYNCHRONOUS (blocking):
    response = requests.get(url)  # Thread WAITS here
    # Nothing else can run until the request completes

ASYNCHRONOUS (non-blocking):
    response = await httpx.get(url)  # Task YIELDS here
    # Other tasks can run while waiting for the network

For an MCP server handling multiple requests:
- Sync: Each request blocks, limiting throughput
- Async: Multiple requests can be "in flight" simultaneously

The 'async def' and 'await' keywords mark this code as asynchronous.
You MUST use 'await' when calling async functions.

=============================================================================
CONTEXT MANAGERS (async with)
=============================================================================

The client uses the "async context manager" pattern:

    async with ArgocdClient(instance) as client:
        apps = await client.list_applications()

This ensures:
1. __aenter__: HTTP connection pool is created
2. (your code runs)
3. __aexit__: HTTP connection pool is cleaned up

Even if your code raises an exception, cleanup happens.
This prevents resource leaks (unclosed connections).

=============================================================================
WHY HTTPX INSTEAD OF REQUESTS?
=============================================================================

httpx is like requests, but supports async:
- requests: Synchronous only
- aiohttp: Async only, different API
- httpx: Both sync and async, familiar requests-like API

We use httpx because:
1. Native async support
2. Familiar API (similar to requests)
3. Better timeout handling
4. Built-in retry support via tenacity
"""

# =============================================================================
# IMPORTS
# =============================================================================

from __future__ import annotations

# Enable modern type annotations
import re

# Regular expressions for secret pattern matching
from dataclasses import dataclass

# Automatic class generation
from typing import TYPE_CHECKING, Any

# TYPE_CHECKING: Conditional imports for type hints
# Any: Accept any type
import httpx

# Async HTTP client library
import structlog

# Structured logging
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Tenacity: Retry library with configurable strategies
# - retry: Decorator to add retry logic
# - retry_if_exception_type: Only retry specific exceptions
# - stop_after_attempt: Maximum retry count
# - wait_exponential: Exponential backoff between retries

if TYPE_CHECKING:
    from argocd_mcp.config import ArgocdInstance
    # ArgocdInstance: Configuration for an ArgoCD server

# Get logger for this module
logger = structlog.get_logger(__name__)


# =============================================================================
# SECRET MASKING PATTERNS
# =============================================================================

# Regular expressions to find and mask sensitive data in STRINGS
# Each tuple is (pattern, replacement)
#
# The patterns look for common secret field names followed by values:
# - token: "..." or token = "..."
# - password: "..." or password = "..."
# etc.
#
# re.I flag makes matching case-insensitive (Token, TOKEN, token all match)

SECRET_PATTERNS = [
    # Match: token: "value" or token = 'value' or token="value"
    (re.compile(r"(token[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+", re.I), r"\1***MASKED***"),
    # Match: password: "value" etc.
    (re.compile(r"(password[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+", re.I), r"\1***MASKED***"),
    # Match: secret: "value" etc.
    (re.compile(r"(secret[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+", re.I), r"\1***MASKED***"),
    # Match: api_key: "value" or api-key: "value" etc.
    (re.compile(r"(api[_-]?key[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+", re.I), r"\1***MASKED***"),
    # Match: Bearer <token> (Authorization header style)
    (re.compile(r"(bearer\s+)[^\s\"']+", re.I), r"\1***MASKED***"),
]

# Keys in dictionaries that should have their values masked
# Using frozenset for O(1) membership testing and immutability
SENSITIVE_KEYS = frozenset(
    [
        "token",
        "password",
        "secret",
        "api_key",
        "apikey",
        "api-key",
        "authorization",
        "auth",
        "credential",
        "credentials",
        "key",
    ]
)


# =============================================================================
# ARGOCD ERROR CLASS
# =============================================================================


class ArgocdError(Exception):
    """
    Structured ArgoCD API error that can be raised and caught.

    WHY A CUSTOM EXCEPTION?
    -----------------------
    HTTP errors from ArgoCD include useful information:
    - Status code (404, 500, etc.)
    - Message from ArgoCD
    - Additional details

    A custom exception preserves all this information so callers can:
    1. Display helpful error messages to users/AI
    2. Make decisions based on error type (404 vs 500)
    3. Log structured error data

    USAGE:
    ------
    try:
        app = await client.get_application("nonexistent")
    except ArgocdError as e:
        print(f"Error {e.code}: {e.message}")  # Error 404: Application not found
    """

    def __init__(self, code: int, message: str, details: str | None = None) -> None:
        """
        Initialize ArgoCD error.

        Args:
            code: HTTP status code (e.g., 404, 500)
            message: Primary error message from ArgoCD
            details: Additional error details (optional)
        """
        self.code = code
        self.message = message
        self.details = details
        # Call parent Exception.__init__ with string representation
        super().__init__(str(self))

    def __str__(self) -> str:
        """
        Format error for agent consumption.

        Returns a human-readable string that includes all available info.
        This is what gets displayed when the exception is printed.

        Example:
            "ArgoCD API error (404): Application not found - no application 'foo' in namespace 'argocd'"
        """
        base = f"ArgoCD API error ({self.code}): {self.message}"
        if self.details:
            base += f" - {self.details}"
        return base


# =============================================================================
# APPLICATION DATA CLASS
# =============================================================================


@dataclass
class Application:
    """
    ArgoCD Application representation.

    This is a CLEAN DATA CLASS that represents an ArgoCD application.
    It extracts the most useful fields from ArgoCD's verbose API response.

    WHY A DATA CLASS?
    -----------------
    ArgoCD's API returns deeply nested JSON with many fields:

        {
            "metadata": {"name": "myapp", "namespace": "argocd", ...},
            "spec": {
                "source": {"repoURL": "...", "path": "...", ...},
                "destination": {"server": "...", "namespace": "..."},
                ...
            },
            "status": {
                "sync": {"status": "Synced", ...},
                "health": {"status": "Healthy", ...},
                ...
            }
        }

    The Application dataclass flattens this into easily accessible fields:
        app.name, app.sync_status, app.health_status, etc.

    FIELDS EXPLAINED:
    -----------------
    - name: Application name (e.g., "myapp")
    - namespace: Kubernetes namespace where ArgoCD resource lives (usually "argocd")
    - project: ArgoCD project (for RBAC grouping)
    - repo_url: Git repository URL
    - path: Path within the repo to manifests
    - target_revision: Git branch/tag/commit to sync to
    - destination_server: Target Kubernetes cluster URL
    - destination_namespace: Target namespace for deployed resources
    - sync_status: "Synced", "OutOfSync", "Unknown"
    - health_status: "Healthy", "Degraded", "Progressing", "Missing", "Unknown"
    - operation_state: Details of last/current operation (sync, rollback)
    - conditions: Error conditions and warnings
    - resources: List of managed Kubernetes resources
    """

    # Core identification
    name: str
    namespace: str
    project: str

    # Source configuration (where manifests come from)
    repo_url: str
    path: str
    target_revision: str

    # Destination configuration (where resources are deployed)
    destination_server: str
    destination_namespace: str

    # Current status
    sync_status: str
    health_status: str

    # Optional detailed status (can be None if not available)
    operation_state: dict[str, Any] | None = None
    conditions: list[dict[str, Any]] | None = None
    resources: list[dict[str, Any]] | None = None

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> Application:
        """
        Create Application from ArgoCD API response.

        This is a FACTORY METHOD - a class method that creates instances.
        It handles the messy work of extracting fields from nested JSON.

        WHY @classmethod?
        -----------------
        Factory methods are useful when:
        1. Instance creation requires complex logic
        2. You want to create instances from different data formats
        3. You need to access the class itself (cls) not an instance

        The @classmethod decorator:
        - First parameter is 'cls' (the class), not 'self' (an instance)
        - Can be called on the class: Application.from_api_response(data)
        - Can also be called on instances (but why would you?)

        DEFENSIVE CODING:
        -----------------
        Notice all the .get() calls with default values:
        - metadata.get("name", "") instead of metadata["name"]
        - This prevents KeyError if fields are missing
        - ArgoCD API might not include empty fields

        Args:
            data: Raw JSON response from ArgoCD API

        Returns:
            Application instance with extracted fields
        """
        # Extract top-level sections with empty dict defaults
        metadata = data.get("metadata", {})
        spec = data.get("spec", {})
        status = data.get("status", {})

        # Extract nested sections
        source = spec.get("source", {})
        destination = spec.get("destination", {})

        return cls(
            # Metadata fields
            name=metadata.get("name", ""),
            namespace=metadata.get("namespace", "argocd"),
            # Spec fields
            project=spec.get("project", "default"),
            repo_url=source.get("repoURL", ""),
            path=source.get("path", ""),
            target_revision=source.get("targetRevision", "HEAD"),
            destination_server=destination.get("server", ""),
            destination_namespace=destination.get("namespace", ""),
            # Status fields (nested further)
            sync_status=status.get("sync", {}).get("status", "Unknown"),
            health_status=status.get("health", {}).get("status", "Unknown"),
            # Optional detailed status
            operation_state=status.get("operationState"),
            conditions=status.get("conditions"),
            resources=status.get("resources"),
        )


# =============================================================================
# ARGOCD CLIENT
# =============================================================================


class ArgocdClient:
    """
    Async ArgoCD API client with retry logic.

    This is the MAIN CLASS for ArgoCD communication. It provides methods
    for all ArgoCD API operations used by the MCP tools.

    LIFECYCLE:
    ----------
    1. Create client: client = ArgocdClient(instance)
    2. Enter context: async with client: ...
    3. Use client: await client.list_applications()
    4. Exit context: HTTP connections cleaned up

    ALWAYS use the context manager pattern:
        async with ArgocdClient(instance) as client:
            apps = await client.list_applications()

    DON'T do this (connections won't be cleaned up):
        client = ArgocdClient(instance)
        apps = await client.list_applications()  # May fail!

    RETRY LOGIC:
    ------------
    Network requests can fail for transient reasons:
    - Temporary network issues
    - Server overload
    - Connection timeouts

    The client automatically retries on timeout with exponential backoff:
    - Attempt 1: Immediate
    - Attempt 2: Wait 1 second
    - Attempt 3: Wait 2 seconds
    - Give up: Raise the exception
    """

    def __init__(
        self,
        instance: ArgocdInstance,
        timeout: float = 30.0,
        mask_secrets: bool = True,
    ) -> None:
        """
        Initialize ArgoCD client.

        NOTE: This only creates the client object. The HTTP connection
        is established later in __aenter__ (when using 'async with').

        Args:
            instance: ArgoCD instance configuration (URL, token, etc.)
            timeout: HTTP request timeout in seconds.
                    30 seconds is generous but handles slow responses.
            mask_secrets: Whether to mask sensitive data in responses.
                         Should almost always be True (default).
        """
        self._instance = instance
        self._timeout = timeout
        self._mask_secrets = mask_secrets
        # HTTP client is created in __aenter__, not here
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> ArgocdClient:
        """
        Enter async context and create HTTP client.

        WHAT IS __aenter__?
        -------------------
        This is the ASYNC CONTEXT MANAGER protocol. When you write:

            async with ArgocdClient(instance) as client:
                ...

        Python calls __aenter__ at 'async with' and __aexit__ when exiting.

        WHY CREATE CLIENT HERE?
        -----------------------
        httpx.AsyncClient manages a connection pool. Creating it:
        - Opens connections to the server
        - Allocates resources

        By creating it here (not in __init__), we ensure it's properly
        cleaned up in __aexit__ even if an exception occurs.

        Returns:
            self (the client) for use in the 'as' clause
        """
        self._client = httpx.AsyncClient(
            # Base URL for all requests
            # e.g., "https://argocd.example.com/api/v1"
            base_url=f"{self._instance.url}/api/v1",
            # Default headers for all requests
            headers={
                # Bearer token authentication
                # get_secret_value() extracts the actual token from SecretStr
                "Authorization": f"Bearer {self._instance.token.get_secret_value()}",
                # We send and receive JSON
                "Content-Type": "application/json",
            },
            # Request timeout
            timeout=self._timeout,
            # TLS verification
            # verify=True: Verify server certificate (default, secure)
            # verify=False: Skip verification (insecure, for self-signed certs)
            # 'not instance.insecure' means: verify unless insecure=True
            verify=not self._instance.insecure,
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        """
        Exit async context and close HTTP client.

        WHAT IS __aexit__?
        ------------------
        Called when exiting the 'async with' block, even if an exception
        was raised. This is where cleanup happens.

        The *args captures exception info (type, value, traceback) if
        an exception occurred, but we don't use them here - we always
        clean up regardless.

        CLEANUP:
        --------
        aclose() properly shuts down the connection pool:
        - Closes open connections
        - Cancels pending requests
        - Releases resources
        """
        if self._client:
            await self._client.aclose()
            self._client = None

    def _mask_response(self, data: Any) -> Any:
        """
        Mask sensitive values in response data.

        RECURSIVE FUNCTION that traverses any data structure and masks
        sensitive values.

        WHY MASK RESPONSES?
        -------------------
        ArgoCD API responses can contain secrets:
        - Application manifests with secret references
        - Error messages including tokens
        - Config values with passwords

        Masking prevents these from:
        1. Being shown to users in tool output
        2. Being logged
        3. Being stored in AI conversation history

        RECURSION EXPLAINED:
        --------------------
        This function calls itself to handle nested structures:

        data = {"config": {"password": "secret123"}}
               ↓ dict, recurse
               {"password": "secret123"}
               ↓ dict, key matches SENSITIVE_KEYS
               {"password": "***MASKED***"}

        Args:
            data: Any data type (dict, list, str, etc.)

        Returns:
            Same structure with sensitive values masked
        """
        # If masking is disabled, return unchanged
        if not self._mask_secrets:
            return data

        # CASE 1: String - apply regex patterns
        if isinstance(data, str):
            masked_str = data
            for pattern, replacement in SECRET_PATTERNS:
                masked_str = pattern.sub(replacement, masked_str)
            return masked_str

        # CASE 2: Dictionary - check keys and recurse into values
        if isinstance(data, dict):
            masked_dict: dict[str, Any] = {}
            for k, v in data.items():
                # Mask values of keys that look sensitive
                if k.lower() in SENSITIVE_KEYS:
                    masked_dict[k] = "***MASKED***"
                else:
                    # Recurse into non-sensitive values
                    masked_dict[k] = self._mask_response(v)
            return masked_dict

        # CASE 3: List - recurse into each item
        if isinstance(data, list):
            return [self._mask_response(item) for item in data]

        # CASE 4: Other types (int, bool, None) - return unchanged
        return data

    @retry(
        retry=retry_if_exception_type(httpx.TimeoutException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Make HTTP request to ArgoCD API.

        This is the CORE REQUEST METHOD. All other methods use this.
        It handles:
        - Retry logic (via @retry decorator)
        - Error conversion to ArgocdError
        - Response masking
        - Logging

        THE @retry DECORATOR EXPLAINED:
        -------------------------------
        @retry(...) from tenacity adds automatic retry logic:

        retry=retry_if_exception_type(httpx.TimeoutException)
            Only retry on timeout errors, not on 404s or other errors

        stop=stop_after_attempt(3)
            Maximum 3 attempts total (1 initial + 2 retries)

        wait=wait_exponential(multiplier=1, min=1, max=10)
            Wait exponentially between retries:
            - Attempt 1 fails -> wait 1 second
            - Attempt 2 fails -> wait 2 seconds
            - Attempt 3 fails -> raise exception

        WHY EXPONENTIAL BACKOFF?
        ------------------------
        If the server is overloaded:
        - Immediate retry makes it worse
        - Waiting helps server recover
        - Exponential growth prevents thundering herd

        Args:
            method: HTTP method ("GET", "POST", "DELETE")
            path: API path (e.g., "/applications", "/applications/myapp")
            params: URL query parameters (optional)
            json_data: JSON request body (optional)

        Returns:
            API response as dictionary

        Raises:
            ArgocdError: On API error (4xx, 5xx)
            httpx.TimeoutException: On request timeout (after retries)
            RuntimeError: If client not initialized (forgot async with)
        """
        # Safety check: ensure client is initialized
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        # Create bound logger with request context
        log = logger.bind(method=method, path=path, instance=self._instance.name)
        log.debug("Making ArgoCD API request")

        # Make the actual HTTP request
        response = await self._client.request(
            method,
            path,
            params=params,
            json=json_data,
        )

        # Handle error responses (4xx, 5xx)
        if response.status_code >= 400:
            error_body = response.text
            log.warning("ArgoCD API error", status=response.status_code, body=error_body[:200])

            # Try to parse ArgoCD's error format
            message = f"HTTP {response.status_code}"
            details = None
            try:
                error_json = response.json()
                message = error_json.get("message", message)
                details = error_json.get("error")
            except Exception:
                # If JSON parsing fails, use raw body
                details = error_body[:200] if error_body else None

            raise ArgocdError(
                code=response.status_code,
                message=message,
                details=details,
            )

        # Parse successful response
        result = response.json() if response.content else {}

        # Mask sensitive data before returning
        masked = self._mask_response(result)
        return masked if isinstance(masked, dict) else {}

    # =========================================================================
    # APPLICATION OPERATIONS
    # =========================================================================

    async def list_applications(
        self,
        project: str | None = None,
        selector: str | None = None,
    ) -> list[Application]:
        """
        List ArgoCD applications.

        ArgoCD API: GET /api/v1/applications

        Args:
            project: Filter by ArgoCD project name (optional)
            selector: Kubernetes label selector (optional)
                     Example: "team=backend,env=production"

        Returns:
            List of Application objects

        Example:
            # List all applications
            apps = await client.list_applications()

            # List applications in 'production' project
            apps = await client.list_applications(project="production")
        """
        params: dict[str, str] = {}
        if project:
            params["project"] = project
        if selector:
            params["selector"] = selector

        # Pass params only if non-empty (avoids ?= in URL)
        data = await self._request("GET", "/applications", params=params or None)

        # API returns {"items": [...]} or empty object
        items = data.get("items") or []

        # Convert each JSON object to Application dataclass
        return [Application.from_api_response(item) for item in items]

    async def get_application(self, name: str) -> Application:
        """
        Get application by name.

        ArgoCD API: GET /api/v1/applications/{name}

        Args:
            name: Application name (e.g., "myapp")

        Returns:
            Application object with full details

        Raises:
            ArgocdError: If application not found (404)

        Example:
            app = await client.get_application("myapp")
            print(f"Health: {app.health_status}")
        """
        data = await self._request("GET", f"/applications/{name}")
        return Application.from_api_response(data)

    async def get_application_diff(
        self,
        name: str,
        revision: str | None = None,
    ) -> dict[str, Any]:
        """
        Get diff for application sync.

        Shows what would change if you synced the application.
        This calls the managed-resources endpoint which returns
        both live state and target state for comparison.

        ArgoCD API: GET /api/v1/applications/{name}/managed-resources

        Args:
            name: Application name
            revision: Target Git revision to diff against (optional)
                     If not specified, uses the app's targetRevision

        Returns:
            Diff information including changed resources.
            Structure: {"items": [{"kind": "...", "liveState": "...", "targetState": "..."}]}
        """
        params = {}
        if revision:
            params["revision"] = revision

        return await self._request(
            "GET",
            f"/applications/{name}/managed-resources",
            params=params or None,
        )

    async def get_application_history(
        self,
        name: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Get application deployment history.

        Returns previous deployments, useful for:
        - Understanding what changed recently
        - Finding rollback targets
        - Auditing who deployed what

        Args:
            name: Application name
            limit: Maximum number of entries to return

        Returns:
            List of history entries, each containing:
            - revision: Git commit SHA
            - deployedAt: Timestamp
            - initiatedBy: Who triggered the deployment
        """
        # History is embedded in the application status
        app_data = await self._request("GET", f"/applications/{name}")
        history = app_data.get("status", {}).get("history", [])

        # Return most recent entries (history is oldest-first)
        return history[-limit:] if history else []

    async def get_application_events(
        self,
        name: str,
        resource_name: str | None = None,
        resource_kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get Kubernetes events for application resources.

        Events provide insight into what's happening with deployments:
        - Image pull failures
        - Pod scheduling issues
        - Container crashes
        - Resource conflicts

        ArgoCD API: GET /api/v1/applications/{name}/events

        Args:
            name: Application name
            resource_name: Filter by specific resource name (optional)
            resource_kind: Filter by resource kind like "Pod", "Deployment" (optional)

        Returns:
            List of Kubernetes Event objects
        """
        params: dict[str, str] = {}
        if resource_name:
            params["resourceName"] = resource_name
        if resource_kind:
            params["resourceKind"] = resource_kind

        data = await self._request(
            "GET",
            f"/applications/{name}/events",
            params=params or None,
        )
        items = data.get("items", [])
        return list(items) if isinstance(items, list) else []

    async def get_resource_tree(self, name: str) -> dict[str, Any]:
        """
        Get resource tree for application.

        The resource tree shows the hierarchy of Kubernetes resources:
        - Application owns Deployments
        - Deployments own ReplicaSets
        - ReplicaSets own Pods

        Useful for understanding resource relationships and finding
        unhealthy nested resources.

        ArgoCD API: GET /api/v1/applications/{name}/resource-tree

        Args:
            name: Application name

        Returns:
            Resource tree structure with nodes and their health status
        """
        return await self._request("GET", f"/applications/{name}/resource-tree")

    async def get_logs(
        self,
        name: str,
        pod_name: str | None = None,
        container: str | None = None,
        tail_lines: int = 100,
        since_seconds: int | None = None,
    ) -> str:
        """
        Get pod logs for application.

        Retrieves logs from pods managed by the application.
        Useful for debugging application issues.

        Args:
            name: Application name
            pod_name: Specific pod name (optional, defaults to first pod)
            container: Container name (optional, for multi-container pods)
            tail_lines: Number of log lines to return (default 100)
            since_seconds: Only return logs newer than this many seconds

        Returns:
            Log content as string
        """
        params: dict[str, Any] = {"tailLines": tail_lines}
        if pod_name:
            params["podName"] = pod_name
        if container:
            params["container"] = container
        if since_seconds:
            params["sinceSeconds"] = since_seconds

        data = await self._request(
            "GET",
            f"/applications/{name}/logs",
            params=params,
        )
        # Logs endpoint might return streaming content
        content = data.get("content", "") if isinstance(data, dict) else str(data)
        return str(content)

    # =========================================================================
    # WRITE OPERATIONS
    # =========================================================================

    async def sync_application(
        self,
        name: str,
        dry_run: bool = True,
        prune: bool = False,
        force: bool = False,
        revision: str | None = None,
    ) -> dict[str, Any]:
        """
        Trigger application sync.

        Synchronizes the application with its Git repository.
        This is the core GitOps operation.

        ArgoCD API: POST /api/v1/applications/{name}/sync

        SYNC OPTIONS EXPLAINED:
        -----------------------
        dry_run: Preview changes without applying
            - True: Show what WOULD change (safe)
            - False: Actually make the changes

        prune: Delete resources not in Git
            - True: Remove orphaned resources (DESTRUCTIVE!)
            - False: Leave orphaned resources alone

        force: Force replacement of resources
            - True: Delete and recreate changed resources
            - False: Apply changes normally

        Args:
            name: Application name
            dry_run: Preview changes without applying (default: True for safety)
            prune: Delete resources not in Git (default: False for safety)
            force: Force sync even if already synced
            revision: Target Git revision (branch, tag, commit SHA)

        Returns:
            Sync operation result
        """
        body: dict[str, Any] = {
            "dryRun": dry_run,
            "prune": prune,
        }
        if revision:
            body["revision"] = revision
        if force:
            body["strategy"] = {"hook": {"force": True}}

        return await self._request("POST", f"/applications/{name}/sync", json_data=body)

    async def rollback_application(
        self,
        name: str,
        revision_id: int,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """
        Rollback application to previous revision.

        Reverts the application to a previous deployment from history.

        Args:
            name: Application name
            revision_id: History revision ID (from get_application_history)
            dry_run: Preview changes without applying

        Returns:
            Rollback operation result
        """
        body = {
            "id": revision_id,
            "dryRun": dry_run,
        }
        return await self._request("POST", f"/applications/{name}/rollback", json_data=body)

    async def refresh_application(
        self,
        name: str,
        hard: bool = False,
    ) -> Application:
        """
        Refresh application manifest from Git.

        Forces ArgoCD to re-read the Git repository and update its
        cached view of the application manifests.

        REFRESH TYPES:
        --------------
        normal (hard=False):
            - Re-fetch manifests from Git
            - Use cached helm charts, kustomize, etc.

        hard (hard=True):
            - Re-fetch everything
            - Invalidate all caches
            - Useful when something seems stuck

        Args:
            name: Application name
            hard: Force hard refresh (invalidate cache)

        Returns:
            Updated Application object
        """
        params = {"refresh": "hard" if hard else "normal"}
        data = await self._request("GET", f"/applications/{name}", params=params)
        return Application.from_api_response(data)

    async def terminate_sync(self, name: str) -> dict[str, Any]:
        """
        Terminate ongoing sync operation.

        Stops a sync that's currently in progress.
        Useful when a sync is stuck or taking too long.

        ArgoCD API: DELETE /api/v1/applications/{name}/operation

        Args:
            name: Application name

        Returns:
            Termination result
        """
        return await self._request("DELETE", f"/applications/{name}/operation")

    async def delete_application(
        self,
        name: str,
        cascade: bool = True,
    ) -> dict[str, Any]:
        """
        Delete application.

        DESTRUCTIVE OPERATION - removes the ArgoCD application.

        CASCADE EXPLAINED:
        ------------------
        cascade=True (default):
            - Delete ArgoCD application record
            - Delete ALL Kubernetes resources it manages
            - Resources are GONE from the cluster

        cascade=False:
            - Delete ArgoCD application record only
            - Kubernetes resources remain ("orphaned")
            - Useful when migrating to different management

        Args:
            name: Application name
            cascade: Delete resources from cluster (default: True)

        Returns:
            Deletion result
        """
        params = {"cascade": str(cascade).lower()}
        return await self._request("DELETE", f"/applications/{name}", params=params)

    # =========================================================================
    # CLUSTER AND PROJECT OPERATIONS
    # =========================================================================

    async def list_clusters(self) -> list[dict[str, Any]]:
        """
        List registered clusters.

        Returns all Kubernetes clusters registered with ArgoCD.

        ArgoCD API: GET /api/v1/clusters

        Returns:
            List of cluster information including:
            - name: Cluster name
            - server: Kubernetes API server URL
            - connectionState: Connection status
        """
        data = await self._request("GET", "/clusters")
        items = data.get("items", [])
        return list(items) if isinstance(items, list) else []

    async def list_projects(self) -> list[dict[str, Any]]:
        """
        List ArgoCD projects.

        Projects organize applications and control RBAC.

        ArgoCD API: GET /api/v1/projects

        Returns:
            List of project information including:
            - metadata.name: Project name
            - spec.description: Project description
            - spec.sourceRepos: Allowed Git repositories
            - spec.destinations: Allowed deployment targets
        """
        data = await self._request("GET", "/projects")
        items = data.get("items", [])
        return list(items) if isinstance(items, list) else []

    async def get_settings(self) -> dict[str, Any]:
        """
        Get ArgoCD server settings.

        Returns server configuration and capabilities.

        ArgoCD API: GET /api/v1/settings

        Returns:
            Server settings including:
            - version info
            - enabled features
            - authentication config
        """
        return await self._request("GET", "/settings")
