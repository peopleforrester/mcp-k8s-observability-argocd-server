# ABOUTME: ArgoCD API client wrapper with retry logic and error handling
# ABOUTME: Provides async interface to ArgoCD REST API with structured responses

"""ArgoCD API client with retry logic and structured error handling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

if TYPE_CHECKING:
    from argocd_mcp.config import ArgocdInstance

logger = structlog.get_logger(__name__)


# Regex patterns for masking sensitive data in string responses
SECRET_PATTERNS = [
    (re.compile(r"(token[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+", re.I), r"\1***MASKED***"),
    (re.compile(r"(password[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+", re.I), r"\1***MASKED***"),
    (re.compile(r"(secret[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+", re.I), r"\1***MASKED***"),
    (re.compile(r"(api[_-]?key[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+", re.I), r"\1***MASKED***"),
    (re.compile(r"(bearer\s+)[^\s\"']+", re.I), r"\1***MASKED***"),
]

# Keys that should have their values masked in dicts
SENSITIVE_KEYS = frozenset([
    "token", "password", "secret", "api_key", "apikey", "api-key",
    "authorization", "auth", "credential", "credentials", "key",
])


class ArgocdError(Exception):
    """Structured ArgoCD API error that can be raised and caught."""

    def __init__(self, code: int, message: str, details: str | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details
        super().__init__(str(self))

    def __str__(self) -> str:
        """Format error for agent consumption."""
        base = f"ArgoCD API error ({self.code}): {self.message}"
        if self.details:
            base += f" - {self.details}"
        return base


@dataclass
class Application:
    """ArgoCD Application representation."""

    name: str
    namespace: str
    project: str
    repo_url: str
    path: str
    target_revision: str
    destination_server: str
    destination_namespace: str
    sync_status: str
    health_status: str
    operation_state: dict[str, Any] | None = None
    conditions: list[dict[str, Any]] | None = None
    resources: list[dict[str, Any]] | None = None

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> Application:
        """Create Application from ArgoCD API response."""
        metadata = data.get("metadata", {})
        spec = data.get("spec", {})
        status = data.get("status", {})
        source = spec.get("source", {})
        destination = spec.get("destination", {})

        return cls(
            name=metadata.get("name", ""),
            namespace=metadata.get("namespace", "argocd"),
            project=spec.get("project", "default"),
            repo_url=source.get("repoURL", ""),
            path=source.get("path", ""),
            target_revision=source.get("targetRevision", "HEAD"),
            destination_server=destination.get("server", ""),
            destination_namespace=destination.get("namespace", ""),
            sync_status=status.get("sync", {}).get("status", "Unknown"),
            health_status=status.get("health", {}).get("status", "Unknown"),
            operation_state=status.get("operationState"),
            conditions=status.get("conditions"),
            resources=status.get("resources"),
        )


class ArgocdClient:
    """Async ArgoCD API client with retry logic."""

    def __init__(
        self,
        instance: ArgocdInstance,
        timeout: float = 30.0,
        mask_secrets: bool = True,
    ) -> None:
        """Initialize ArgoCD client.

        Args:
            instance: ArgoCD instance configuration
            timeout: HTTP request timeout in seconds
            mask_secrets: Whether to mask sensitive data in responses
        """
        self._instance = instance
        self._timeout = timeout
        self._mask_secrets = mask_secrets
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> ArgocdClient:
        """Enter async context and create HTTP client."""
        self._client = httpx.AsyncClient(
            base_url=f"{self._instance.url}/api/v1",
            headers={
                "Authorization": f"Bearer {self._instance.token.get_secret_value()}",
                "Content-Type": "application/json",
            },
            timeout=self._timeout,
            verify=not self._instance.insecure,
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit async context and close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _mask_response(self, data: Any) -> Any:
        """Mask sensitive values in response data."""
        if not self._mask_secrets:
            return data

        if isinstance(data, str):
            result = data
            for pattern, replacement in SECRET_PATTERNS:
                result = pattern.sub(replacement, result)
            return result
        if isinstance(data, dict):
            result = {}
            for k, v in data.items():
                # Mask values of keys that look sensitive
                if k.lower() in SENSITIVE_KEYS:
                    result[k] = "***MASKED***"
                else:
                    result[k] = self._mask_response(v)
            return result
        if isinstance(data, list):
            return [self._mask_response(item) for item in data]
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
        """Make HTTP request to ArgoCD API.

        Args:
            method: HTTP method
            path: API path
            params: Query parameters
            json_data: Request body

        Returns:
            API response as dictionary

        Raises:
            ArgocdError: On API error
            httpx.TimeoutException: On request timeout (after retries)
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        log = logger.bind(method=method, path=path, instance=self._instance.name)
        log.debug("Making ArgoCD API request")

        response = await self._client.request(
            method,
            path,
            params=params,
            json=json_data,
        )

        if response.status_code >= 400:
            error_body = response.text
            log.warning("ArgoCD API error", status=response.status_code, body=error_body[:200])

            # Parse ArgoCD error format
            message = f"HTTP {response.status_code}"
            details = None
            try:
                error_json = response.json()
                message = error_json.get("message", message)
                details = error_json.get("error")
            except Exception:
                details = error_body[:200] if error_body else None

            raise ArgocdError(
                code=response.status_code,
                message=message,
                details=details,
            )

        result = response.json() if response.content else {}
        return self._mask_response(result)

    async def list_applications(
        self,
        project: str | None = None,
        selector: str | None = None,
    ) -> list[Application]:
        """List ArgoCD applications.

        Args:
            project: Filter by project name
            selector: Label selector

        Returns:
            List of Application objects
        """
        params: dict[str, str] = {}
        if project:
            params["project"] = project
        if selector:
            params["selector"] = selector

        data = await self._request("GET", "/applications", params=params or None)
        items = data.get("items") or []
        return [Application.from_api_response(item) for item in items]

    async def get_application(self, name: str) -> Application:
        """Get application by name.

        Args:
            name: Application name

        Returns:
            Application object

        Raises:
            ArgocdError: If application not found
        """
        data = await self._request("GET", f"/applications/{name}")
        return Application.from_api_response(data)

    async def get_application_diff(
        self,
        name: str,
        revision: str | None = None,
    ) -> dict[str, Any]:
        """Get diff for application sync.

        Args:
            name: Application name
            revision: Target revision (optional)

        Returns:
            Diff information including changed resources
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
        """Get application deployment history.

        Args:
            name: Application name
            limit: Maximum number of entries

        Returns:
            List of history entries
        """
        app_data = await self._request("GET", f"/applications/{name}")
        history = app_data.get("status", {}).get("history", [])
        return history[-limit:] if history else []

    async def get_application_events(
        self,
        name: str,
        resource_name: str | None = None,
        resource_kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get Kubernetes events for application resources.

        Args:
            name: Application name
            resource_name: Filter by resource name
            resource_kind: Filter by resource kind

        Returns:
            List of Kubernetes events
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
        return data.get("items", [])

    async def get_resource_tree(self, name: str) -> dict[str, Any]:
        """Get resource tree for application.

        Args:
            name: Application name

        Returns:
            Resource tree structure
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
        """Get pod logs for application.

        Args:
            name: Application name
            pod_name: Specific pod name
            container: Container name
            tail_lines: Number of lines to return
            since_seconds: Only return logs newer than this

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
        # Logs endpoint returns streaming content; aggregate
        return data.get("content", "") if isinstance(data, dict) else str(data)

    async def sync_application(
        self,
        name: str,
        dry_run: bool = True,
        prune: bool = False,
        force: bool = False,
        revision: str | None = None,
    ) -> dict[str, Any]:
        """Trigger application sync.

        Args:
            name: Application name
            dry_run: Preview changes without applying
            prune: Delete resources not in Git
            force: Force sync even if already synced
            revision: Target revision

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
        """Rollback application to previous revision.

        Args:
            name: Application name
            revision_id: History revision ID to rollback to
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
        """Refresh application manifest from Git.

        Args:
            name: Application name
            hard: Force hard refresh

        Returns:
            Updated Application object
        """
        params = {"refresh": "hard" if hard else "normal"}
        data = await self._request("GET", f"/applications/{name}", params=params)
        return Application.from_api_response(data)

    async def terminate_sync(self, name: str) -> dict[str, Any]:
        """Terminate ongoing sync operation.

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
        """Delete application.

        Args:
            name: Application name
            cascade: Delete resources from cluster

        Returns:
            Deletion result
        """
        params = {"cascade": str(cascade).lower()}
        return await self._request("DELETE", f"/applications/{name}", params=params)

    async def list_clusters(self) -> list[dict[str, Any]]:
        """List registered clusters.

        Returns:
            List of cluster information
        """
        data = await self._request("GET", "/clusters")
        return data.get("items", [])

    async def list_projects(self) -> list[dict[str, Any]]:
        """List ArgoCD projects.

        Returns:
            List of project information
        """
        data = await self._request("GET", "/projects")
        return data.get("items", [])

    async def get_settings(self) -> dict[str, Any]:
        """Get ArgoCD server settings.

        Returns:
            Server settings and capabilities
        """
        return await self._request("GET", "/settings")
