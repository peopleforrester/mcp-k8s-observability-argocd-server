# ABOUTME: Safety utilities for ArgoCD MCP Server
# ABOUTME: Implements confirmation patterns, rate limiting, and destructive operation guards

"""Safety utilities implementing defense-in-depth patterns."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from argocd_mcp.config import SecuritySettings

logger = structlog.get_logger(__name__)


@dataclass
class ConfirmationRequired:
    """Response indicating confirmation is required for destructive operation."""

    operation: str
    target: str
    impact: str
    confirmation_instructions: str
    details: dict[str, Any] = field(default_factory=dict)

    def format_message(self) -> str:
        """Format confirmation request for agent consumption."""
        lines = [
            f"CONFIRMATION REQUIRED: {self.operation}",
            "",
            f"Target: {self.target}",
            f"Impact: {self.impact}",
        ]
        if self.details:
            lines.append("")
            lines.append("Details:")
            for key, value in self.details.items():
                lines.append(f"  {key}: {value}")
        lines.extend(["", self.confirmation_instructions])
        return "\n".join(lines)


@dataclass
class OperationBlocked:
    """Response indicating operation is blocked by security settings."""

    operation: str
    reason: str
    setting: str

    def format_message(self) -> str:
        """Format blocked message for agent consumption."""
        return (
            f"OPERATION BLOCKED: {self.operation}\n"
            f"Reason: {self.reason}\n"
            f"Setting: {self.setting}\n"
            f"To enable: Set {self.setting}=false in server configuration"
        )


class RateLimiter:
    """Sliding window rate limiter for API operations."""

    def __init__(self, max_calls: int = 100, window_seconds: int = 60) -> None:
        """
        Initialize rate limiter.

        Args:
            max_calls: Maximum calls allowed in window (default 100)
            window_seconds: Window size in seconds (default 60)
        """
        self._max_calls = max_calls
        self._window = window_seconds
        # Per-key call timestamps. Keys are operation names like
        # "read:list_applications" — a small fixed cardinality dictated by
        # the registered MCP tools, so the dict never grows unbounded. If
        # callers ever start passing per-target keys (e.g. including the
        # application name), revisit this and add explicit eviction.
        self._calls: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> bool:
        """
        Check if operation is allowed.

        Args:
            key: Rate limit key (e.g., "read:list_apps")

        Returns:
            True if allowed, False if rate limited.
        """
        now = time.time()
        self._calls[key] = [t for t in self._calls[key] if now - t < self._window]

        if len(self._calls[key]) >= self._max_calls:
            logger.warning("Rate limit exceeded", key=key, calls=len(self._calls[key]))
            return False

        self._calls[key].append(now)
        return True

    def reset(self, key: str | None = None) -> None:
        """Reset rate limit counters for key or all keys."""
        if key:
            self._calls.pop(key, None)
        else:
            self._calls.clear()


class SafetyGuard:
    """Safety guard implementing defense-in-depth patterns."""

    def __init__(self, settings: SecuritySettings) -> None:
        """
        Initialize safety guard.

        Args:
            settings: Security settings from configuration.
        """
        self._settings = settings
        self._rate_limiter = RateLimiter(
            max_calls=settings.rate_limit_calls,
            window_seconds=settings.rate_limit_window,
        )

    def check_read_operation(self, operation: str) -> OperationBlocked | None:
        """
        Check if read operation is allowed. Reads are allowed but rate-limited.

        Returns:
            OperationBlocked if rate limited, None if allowed.
        """
        if not self._rate_limiter.check(f"read:{operation}"):
            return OperationBlocked(
                operation=operation,
                reason="Rate limit exceeded",
                setting="MCP_RATE_LIMIT_CALLS",
            )
        return None

    def check_write_operation(self, operation: str) -> OperationBlocked | None:
        """
        Check if write operation is allowed. Requires MCP_READ_ONLY=false.

        Returns:
            OperationBlocked if blocked, None if allowed.
        """
        if self._settings.read_only:
            return OperationBlocked(
                operation=operation,
                reason="Server is running in read-only mode",
                setting="MCP_READ_ONLY",
            )

        if not self._rate_limiter.check(f"write:{operation}"):
            return OperationBlocked(
                operation=operation,
                reason="Rate limit exceeded",
                setting="MCP_RATE_LIMIT_CALLS",
            )

        return None

    def check_destructive_operation(
        self,
        operation: str,
        target: str,
        confirmed: bool = False,
        confirm_name: str | None = None,
    ) -> OperationBlocked | ConfirmationRequired | None:
        """
        Check if destructive operation is allowed.

        Requires: MCP_READ_ONLY=false, MCP_DISABLE_DESTRUCTIVE=false,
        and explicit confirmation (confirm=true AND confirm_name=target).

        Returns:
            OperationBlocked if blocked by settings,
            ConfirmationRequired if needs confirmation,
            None if allowed.
        """
        write_check = self.check_write_operation(operation)
        if write_check:
            return write_check

        if self._settings.disable_destructive:
            return OperationBlocked(
                operation=operation,
                reason="Destructive operations are disabled",
                setting="MCP_DISABLE_DESTRUCTIVE",
            )

        if not confirmed:
            instructions = f"To proceed, set confirm=true AND confirm_name='{target}'"
        elif confirm_name is None:
            instructions = (
                f"confirm=true was provided but confirm_name is missing. "
                f"Set confirm_name='{target}' (must match exactly, including case and whitespace)."
            )
        elif confirm_name != target:
            instructions = (
                f"confirm_name={confirm_name!r} does not match the target {target!r}. "
                f"Matching is exact — case and whitespace are significant. "
                f"Set confirm_name='{target}' to proceed."
            )
        else:
            return None

        return ConfirmationRequired(
            operation=operation,
            target=target,
            impact=self._get_impact_description(operation),
            confirmation_instructions=instructions,
        )

    # ArgoCD identifies the cluster ArgoCD itself runs in by either the
    # canonical Kubernetes API URL or the friendly name "in-cluster". Both
    # appear in real Application destinations, depending on installation.
    _IN_CLUSTER_IDENTIFIERS: frozenset[str] = frozenset(
        {"in-cluster", "https://kubernetes.default.svc"}
    )

    def check_cluster_operation(
        self,
        operation: str,
        cluster: str,
    ) -> OperationBlocked | None:
        """
        Check if operation on specific cluster is allowed.

        When MCP_SINGLE_CLUSTER=true, only operations whose destination is the
        cluster ArgoCD itself runs in are allowed. Accepts both the canonical
        URL form (`https://kubernetes.default.svc`) and the friendly name
        (`in-cluster`) since ArgoCD emits whichever was configured.
        """
        if self._settings.single_cluster and cluster not in self._IN_CLUSTER_IDENTIFIERS:
            return OperationBlocked(
                operation=operation,
                reason=f"Operation on cluster '{cluster}' blocked in single-cluster mode",
                setting="MCP_SINGLE_CLUSTER",
            )
        return None

    @staticmethod
    def _get_impact_description(operation: str) -> str:
        """Get human-readable impact description for destructive operation."""
        impacts = {
            "delete_application": (
                "Application and all managed resources will be PERMANENTLY DELETED"
            ),
            "sync_with_prune": "Resources not in Git will be DELETED from cluster",
            "sync_with_force": "Resources will be replaced, potentially causing downtime",
            "rollback": "Application will revert to previous state, may cause service disruption",
        }
        return impacts.get(operation, "This operation may have significant impact")
