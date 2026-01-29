# ABOUTME: Safety utilities for ArgoCD MCP Server
# ABOUTME: Implements confirmation patterns, rate limiting, and destructive operation guards

"""Safety utilities implementing defense-in-depth patterns."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

    from argocd_mcp.config import SecuritySettings

logger = structlog.get_logger(__name__)

T = TypeVar("T")


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
    """Rate limiter for API operations."""

    def __init__(self, max_calls: int = 100, window_seconds: int = 60) -> None:
        """Initialize rate limiter.

        Args:
            max_calls: Maximum calls allowed in window
            window_seconds: Window size in seconds
        """
        self._max_calls = max_calls
        self._window = window_seconds
        self._calls: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> bool:
        """Check if operation is allowed.

        Args:
            key: Rate limit key (e.g., "sync:my-app")

        Returns:
            True if allowed, False if rate limited
        """
        now = time.time()
        # Clean expired entries
        self._calls[key] = [t for t in self._calls[key] if now - t < self._window]

        if len(self._calls[key]) >= self._max_calls:
            logger.warning("Rate limit exceeded", key=key, calls=len(self._calls[key]))
            return False

        self._calls[key].append(now)
        return True

    def reset(self, key: str | None = None) -> None:
        """Reset rate limit counters.

        Args:
            key: Specific key to reset, or None for all
        """
        if key:
            self._calls.pop(key, None)
        else:
            self._calls.clear()


class SafetyGuard:
    """Safety guard implementing defense-in-depth patterns."""

    def __init__(self, settings: SecuritySettings) -> None:
        """Initialize safety guard.

        Args:
            settings: Security settings
        """
        self._settings = settings
        self._rate_limiter = RateLimiter(
            max_calls=settings.rate_limit_calls,
            window_seconds=settings.rate_limit_window,
        )

    def check_read_operation(self, operation: str) -> OperationBlocked | None:
        """Check if read operation is allowed.

        Args:
            operation: Operation name

        Returns:
            OperationBlocked if blocked, None if allowed
        """
        # Read operations are always allowed
        if not self._rate_limiter.check(f"read:{operation}"):
            return OperationBlocked(
                operation=operation,
                reason="Rate limit exceeded",
                setting="MCP_RATE_LIMIT_CALLS",
            )
        return None

    def check_write_operation(self, operation: str) -> OperationBlocked | None:
        """Check if write operation is allowed.

        Args:
            operation: Operation name

        Returns:
            OperationBlocked if blocked, None if allowed
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
        """Check if destructive operation is allowed.

        Args:
            operation: Operation name
            target: Target resource name
            confirmed: Whether user has confirmed
            confirm_name: Name confirmation (must match target)

        Returns:
            OperationBlocked if blocked, ConfirmationRequired if needs confirmation,
            None if allowed
        """
        # Check read-only mode first
        write_check = self.check_write_operation(operation)
        if write_check:
            return write_check

        # Check destructive operations disabled
        if self._settings.disable_destructive:
            return OperationBlocked(
                operation=operation,
                reason="Destructive operations are disabled",
                setting="MCP_DISABLE_DESTRUCTIVE",
            )

        # Require explicit confirmation
        if not confirmed or confirm_name != target:
            return ConfirmationRequired(
                operation=operation,
                target=target,
                impact=self._get_impact_description(operation),
                confirmation_instructions=(
                    f"To proceed, set confirm=true AND confirm_name='{target}'"
                ),
            )

        return None

    def check_cluster_operation(
        self,
        operation: str,
        cluster: str,
    ) -> OperationBlocked | None:
        """Check if operation on specific cluster is allowed.

        Args:
            operation: Operation name
            cluster: Target cluster

        Returns:
            OperationBlocked if blocked, None if allowed
        """
        if self._settings.single_cluster and cluster != "in-cluster":
            return OperationBlocked(
                operation=operation,
                reason=f"Operation on cluster '{cluster}' blocked in single-cluster mode",
                setting="MCP_SINGLE_CLUSTER",
            )
        return None

    @staticmethod
    def _get_impact_description(operation: str) -> str:
        """Get human-readable impact description for operation."""
        impacts = {
            "delete_application": "Application and all managed resources will be PERMANENTLY DELETED",
            "sync_with_prune": "Resources not in Git will be DELETED from cluster",
            "sync_with_force": "Resources will be replaced, potentially causing downtime",
            "rollback": "Application will revert to previous state, may cause service disruption",
        }
        return impacts.get(operation, "This operation may have significant impact")


def require_write(
    func: Callable[..., T],
) -> Callable[..., T]:
    """Decorator to mark function as requiring write permissions.

    This is a marker decorator for documentation; actual checking
    is done by SafetyGuard.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        return func(*args, **kwargs)

    wrapper._requires_write = True  # type: ignore[attr-defined]
    return wrapper


def require_confirmation(
    operation: str,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to mark function as requiring confirmation.

    This is a marker decorator for documentation; actual checking
    is done by SafetyGuard.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            return func(*args, **kwargs)

        wrapper._requires_confirmation = operation  # type: ignore[attr-defined]
        return wrapper

    return decorator
