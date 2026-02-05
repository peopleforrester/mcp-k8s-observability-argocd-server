# ABOUTME: Safety utilities for ArgoCD MCP Server
# ABOUTME: Implements confirmation patterns, rate limiting, and destructive operation guards

"""
Safety utilities implementing defense-in-depth patterns.

=============================================================================
WHAT IS THIS FILE?
=============================================================================

This is the SECURITY HEART of the MCP server. It implements multiple layers
of protection to prevent accidental or malicious damage to your infrastructure.

When an AI assistant has access to production systems, safety is CRITICAL.
This module ensures that even if the AI tries to do something dangerous,
multiple safeguards must be passed.

=============================================================================
DEFENSE IN DEPTH EXPLAINED
=============================================================================

"Defense in depth" is a security principle: don't rely on a single protection.
Like a castle with multiple walls, gates, and moats - if one fails, others
still protect you.

OUR LAYERS:
-----------

LAYER 1: Read-Only Mode (MCP_READ_ONLY=true)
┌─────────────────────────────────────────┐
│ ALL write operations blocked            │
│ AI can only view, not modify            │
│ Safest mode for exploration/debugging   │
└─────────────────────────────────────────┘
                    │
                    ▼ (if MCP_READ_ONLY=false)
LAYER 2: Destructive Operations Disabled (MCP_DISABLE_DESTRUCTIVE=true)
┌─────────────────────────────────────────┐
│ Syncs allowed, but NO deletes           │
│ AI can update, but can't destroy        │
│ Good for normal operations              │
└─────────────────────────────────────────┘
                    │
                    ▼ (if MCP_DISABLE_DESTRUCTIVE=false)
LAYER 3: Confirmation Pattern
┌─────────────────────────────────────────┐
│ Must set confirm=true                   │
│ Must set confirm_name matching target   │
│ Forces explicit intent                  │
└─────────────────────────────────────────┘
                    │
                    ▼ (if both confirmations provided)
LAYER 4: Rate Limiting
┌─────────────────────────────────────────┐
│ Max N operations per time window        │
│ Prevents infinite loops                 │
│ Protects ArgoCD server                  │
└─────────────────────────────────────────┘

=============================================================================
WHY CONFIRMATION PATTERNS?
=============================================================================

Confirmation patterns prevent accidents. Consider:

WITHOUT CONFIRMATION:
    AI: "I'll delete the old deployment to clean up."
    AI: delete_application(name="production-database")  # DISASTER!

WITH CONFIRMATION:
    AI: "I'll delete the old deployment to clean up."
    AI: delete_application(name="production-database")
    Response: "CONFIRMATION REQUIRED: Set confirm=true AND confirm_name='production-database'"
    AI: "Oh wait, that's the production database! I shouldn't delete that."

The extra step forces the AI (and humans reviewing) to consciously acknowledge
what's being deleted.

=============================================================================
RATE LIMITING EXPLAINED
=============================================================================

AI models can get into infinite loops:
    "Sync failed, let me retry... still failed... retry... retry..."

Without rate limiting, this could:
1. Overwhelm the ArgoCD server
2. Trigger rate limits on upstream APIs
3. Consume all available resources
4. Make the problem worse

Rate limiting implements a "sliding window" algorithm:
- Track timestamps of recent operations
- If too many in the window, block new ones
- Old operations "expire" as time passes
"""

# =============================================================================
# IMPORTS
# =============================================================================
#
# Standard library:
# - time: Timestamp tracking for rate limiter sliding window
# - defaultdict: Auto-creates missing keys with default values
# - dataclass/field: Automatic __init__, __repr__ generation for data classes
# - TYPE_CHECKING: Only True during static analysis, not runtime
#
# Third-party:
# - structlog: Structured logging
#
# Type-checking only (not loaded at runtime):
# - SecuritySettings: Configuration for safety features
# =============================================================================

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from argocd_mcp.config import SecuritySettings

# Get a logger for this module
# __name__ becomes "argocd_mcp.utils.safety"
logger = structlog.get_logger(__name__)

# =============================================================================
# CONFIRMATION REQUIRED RESPONSE
# =============================================================================


@dataclass
class ConfirmationRequired:
    """
    Response indicating confirmation is required for destructive operation.

    WHAT IS @dataclass?
    -------------------
    @dataclass is a Python decorator that automatically generates:
    - __init__() method from field definitions
    - __repr__() for nice string representation
    - __eq__() for equality comparison
    - And more (optionally)

    Instead of writing:
        class ConfirmationRequired:
            def __init__(self, operation, target, impact, ...):
                self.operation = operation
                self.target = target
                ...

    You just write field definitions and @dataclass does the rest.

    WHEN IS THIS RETURNED?
    ----------------------
    When someone tries a destructive operation without proper confirmation:

    1. User/AI: delete_application(name="my-app")
    2. SafetyGuard: Returns ConfirmationRequired
    3. Tool: Formats message and returns to AI
    4. AI: Sees instructions, can decide to confirm or abort

    THE CONFIRMATION PATTERN:
    -------------------------
    To proceed with a destructive operation:
    1. Set confirm=true (acknowledging the risk)
    2. Set confirm_name="<target>" (proving you know what you're deleting)

    Both are required to prevent:
    - Accidental confirms (confirm=true alone)
    - Copy-paste errors (wrong target name)
    """

    # The operation being attempted (e.g., "delete_application")
    operation: str

    # The target resource (e.g., "my-production-app")
    target: str

    # Human-readable impact description explaining what will happen
    impact: str

    # Instructions on how to proceed (tells user what params to set)
    confirmation_instructions: str

    # Additional context (namespace, cluster, etc.)
    # default_factory=dict creates a new empty dict for each instance
    # (avoiding the mutable default argument pitfall)
    details: dict[str, Any] = field(default_factory=dict)

    def format_message(self) -> str:
        """
        Format confirmation request for agent consumption.

        This produces a human/AI-readable message explaining:
        1. What confirmation is needed
        2. What will be affected
        3. What the impact will be
        4. How to proceed

        Returns:
            Formatted multi-line string for display.

        Example output:
            CONFIRMATION REQUIRED: delete_application

            Target: my-production-app
            Impact: Application and all managed resources will be PERMANENTLY DELETED

            Details:
              namespace: production
              cluster: https://k8s.example.com
              cascade: True

            To proceed, set confirm=true AND confirm_name='my-production-app'
        """
        # Build output line by line
        lines = [
            f"CONFIRMATION REQUIRED: {self.operation}",
            "",  # Empty line for readability
            f"Target: {self.target}",
            f"Impact: {self.impact}",
        ]

        # Add details section if we have any
        if self.details:
            lines.append("")
            lines.append("Details:")
            for key, value in self.details.items():
                lines.append(f"  {key}: {value}")

        # Add instructions at the end
        lines.extend(["", self.confirmation_instructions])

        return "\n".join(lines)


# =============================================================================
# OPERATION BLOCKED RESPONSE
# =============================================================================


@dataclass
class OperationBlocked:
    """
    Response indicating operation is blocked by security settings.

    WHEN IS THIS RETURNED?
    ----------------------
    When a security setting completely prevents an operation:

    1. MCP_READ_ONLY=true and user tries to sync -> OperationBlocked
    2. MCP_DISABLE_DESTRUCTIVE=true and user tries to delete -> OperationBlocked
    3. Rate limit exceeded -> OperationBlocked

    Unlike ConfirmationRequired, there's no way to proceed without
    changing server configuration.

    THE MESSAGE FORMAT:
    -------------------
    The message tells the user:
    1. What operation was blocked
    2. Why it was blocked
    3. Which setting controls this
    4. How to enable it (if they have access to configuration)

    This is important for debugging - when an AI says "I can't do that",
    administrators need to know WHY and how to change it if needed.
    """

    # The blocked operation (e.g., "sync_application")
    operation: str

    # Human-readable reason (e.g., "Server is running in read-only mode")
    reason: str

    # The configuration setting that caused the block (e.g., "MCP_READ_ONLY")
    setting: str

    def format_message(self) -> str:
        """
        Format blocked message for agent consumption.

        Returns:
            Formatted multi-line string explaining the block.

        Example output:
            OPERATION BLOCKED: sync_application
            Reason: Server is running in read-only mode
            Setting: MCP_READ_ONLY
            To enable: Set MCP_READ_ONLY=false in server configuration
        """
        return (
            f"OPERATION BLOCKED: {self.operation}\n"
            f"Reason: {self.reason}\n"
            f"Setting: {self.setting}\n"
            f"To enable: Set {self.setting}=false in server configuration"
        )


# =============================================================================
# RATE LIMITER
# =============================================================================


class RateLimiter:
    """
    Rate limiter for API operations.

    ALGORITHM: Sliding Window
    -------------------------
    We track the timestamp of each operation. When checking if an operation
    is allowed:

    1. Remove expired timestamps (older than window)
    2. Count remaining timestamps
    3. If count >= max_calls, reject
    4. Otherwise, record new timestamp and allow

    Example with max_calls=3, window=60s:

    Time 0:00 - Operation 1 -> [0:00] -> Allowed (1 < 3)
    Time 0:15 - Operation 2 -> [0:00, 0:15] -> Allowed (2 < 3)
    Time 0:30 - Operation 3 -> [0:00, 0:15, 0:30] -> Allowed (3 = 3, but allows =)
    Time 0:45 - Operation 4 -> [0:00, 0:15, 0:30] -> BLOCKED (3 >= 3)
    Time 1:05 - Operation 5 -> [0:15, 0:30] (0:00 expired) -> Allowed (2 < 3)

    WHY SEPARATE KEYS?
    ------------------
    Different operations have separate rate limits. This prevents:
    - One busy tool from blocking all tools
    - Read operations from consuming write operation budget

    Keys are like "read:list_applications", "write:sync_application"
    """

    def __init__(self, max_calls: int = 100, window_seconds: int = 60) -> None:
        """
        Initialize rate limiter.

        Args:
            max_calls: Maximum calls allowed in window.
                      Default 100 is high enough for normal use,
                      but catches infinite loops.

            window_seconds: Window size in seconds.
                           Default 60 seconds = 1 minute.
                           Combined with max_calls=100, allows ~1.67 calls/sec.
        """
        self._max_calls = max_calls
        self._window = window_seconds
        # defaultdict(list) auto-creates empty lists for new keys
        # self._calls["new_key"] returns [] instead of raising KeyError
        self._calls: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> bool:
        """
        Check if operation is allowed.

        This is the main entry point. Call it before every operation.
        If it returns False, the operation should be blocked.

        Args:
            key: Rate limit key (e.g., "read:list_apps", "write:sync:my-app")
                Keys can be as specific or general as needed.

        Returns:
            True if allowed, False if rate limited.

        Example:
            if not rate_limiter.check("write:sync_application"):
                return OperationBlocked(operation="sync", reason="Rate limit exceeded", ...)
        """
        now = time.time()

        # STEP 1: Clean expired entries
        # List comprehension keeps only timestamps within the window
        # This is the "sliding" part of sliding window
        self._calls[key] = [t for t in self._calls[key] if now - t < self._window]

        # STEP 2: Check if limit reached
        if len(self._calls[key]) >= self._max_calls:
            # Log for debugging - rate limiting is noteworthy
            logger.warning("Rate limit exceeded", key=key, calls=len(self._calls[key]))
            return False

        # STEP 3: Record this call and allow
        self._calls[key].append(now)
        return True

    def reset(self, key: str | None = None) -> None:
        """
        Reset rate limit counters.

        Useful for:
        - Testing
        - Manual intervention after resolving issues
        - Scheduled resets

        Args:
            key: Specific key to reset, or None for all keys.

        Example:
            rate_limiter.reset("write:sync_application")  # Reset one
            rate_limiter.reset()  # Reset all
        """
        if key:
            # Remove specific key (pop returns and removes, or does nothing)
            self._calls.pop(key, None)
        else:
            # Clear all keys
            self._calls.clear()


# =============================================================================
# SAFETY GUARD - THE MAIN SECURITY ENFORCER
# =============================================================================


class SafetyGuard:
    """
    Safety guard implementing defense-in-depth patterns.

    This is the MAIN CLASS for security enforcement. Every operation goes
    through one of its check_* methods before proceeding.

    USAGE PATTERN:
    --------------
    Every tool function follows this pattern:

        async def some_tool(params, ctx):
            # Check if operation is allowed
            blocked = safety_guard.check_write_operation("some_tool")
            if blocked:
                audit_logger.log_blocked(...)
                return blocked.format_message()

            # If we get here, operation is allowed
            # Proceed with the actual work...

    METHOD SELECTION:
    -----------------
    - check_read_operation(): For list/get/view operations
    - check_write_operation(): For sync/refresh operations
    - check_destructive_operation(): For delete/prune operations
    - check_cluster_operation(): For multi-cluster restrictions
    """

    def __init__(self, settings: SecuritySettings) -> None:
        """
        Initialize safety guard.

        Args:
            settings: Security settings from configuration.
                     Contains read_only, disable_destructive, rate limits, etc.
        """
        self._settings = settings

        # Create rate limiter with configured limits
        self._rate_limiter = RateLimiter(
            max_calls=settings.rate_limit_calls,
            window_seconds=settings.rate_limit_window,
        )

    def check_read_operation(self, operation: str) -> OperationBlocked | None:
        """
        Check if read operation is allowed.

        Read operations are ALWAYS allowed from a permission standpoint
        (there's no MCP_DISABLE_READS setting). However, they're still
        subject to rate limiting.

        WHY RATE LIMIT READS?
        ---------------------
        - Prevent DoS on ArgoCD API
        - Catch infinite loops (AI repeatedly checking status)
        - Fair resource sharing

        Args:
            operation: Operation name (e.g., "list_applications")

        Returns:
            OperationBlocked if rate limited, None if allowed.

        Example:
            blocked = safety_guard.check_read_operation("list_applications")
            if blocked:
                return blocked.format_message()
            # Proceed with operation...
        """
        # Read operations are always allowed permission-wise
        # But still check rate limit
        if not self._rate_limiter.check(f"read:{operation}"):
            return OperationBlocked(
                operation=operation,
                reason="Rate limit exceeded",
                setting="MCP_RATE_LIMIT_CALLS",
            )
        return None

    def check_write_operation(self, operation: str) -> OperationBlocked | None:
        """
        Check if write operation is allowed.

        Write operations (sync, refresh) require MCP_READ_ONLY=false.
        They're also subject to rate limiting.

        WHAT'S A "WRITE" vs "DESTRUCTIVE"?
        ----------------------------------
        Write operations modify state but don't destroy data:
        - sync_application: Updates cluster to match Git
        - refresh_application: Refreshes cached manifests

        Destructive operations can cause permanent data loss:
        - delete_application: Removes application (and possibly resources)
        - sync with prune=true: Deletes resources not in Git

        Args:
            operation: Operation name (e.g., "sync_application")

        Returns:
            OperationBlocked if blocked, None if allowed.
        """
        # LAYER 1: Read-only mode
        if self._settings.read_only:
            return OperationBlocked(
                operation=operation,
                reason="Server is running in read-only mode",
                setting="MCP_READ_ONLY",
            )

        # LAYER 4: Rate limiting
        if not self._rate_limiter.check(f"write:{operation}"):
            return OperationBlocked(
                operation=operation,
                reason="Rate limit exceeded",
                setting="MCP_RATE_LIMIT_CALLS",
            )

        # All checks passed!
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

        This is the MOST RESTRICTIVE check. Destructive operations must pass:
        1. Read-only mode check (MCP_READ_ONLY=false)
        2. Destructive operations check (MCP_DISABLE_DESTRUCTIVE=false)
        3. Confirmation pattern (confirm=true AND confirm_name=target)
        4. Rate limiting

        THE CONFIRMATION PATTERN IN DETAIL:
        -----------------------------------
        To delete "my-app", you must provide BOTH:
        - confirm=True  (acknowledging the risk)
        - confirm_name="my-app"  (proving you know what you're deleting)

        This prevents:
        - Accidental deletion (forgot to check what app)
        - Copy-paste errors (pasting wrong app name)
        - AI hallucination (making up app names)

        Args:
            operation: Operation name (e.g., "delete_application")
            target: Target resource name (e.g., "my-app")
            confirmed: Whether user set confirm=true
            confirm_name: Name provided for confirmation

        Returns:
            OperationBlocked if blocked by settings,
            ConfirmationRequired if needs confirmation,
            None if allowed.
        """
        # LAYERS 1 & 4: Check write permissions first
        write_check = self.check_write_operation(operation)
        if write_check:
            return write_check

        # LAYER 2: Destructive operations disabled
        if self._settings.disable_destructive:
            return OperationBlocked(
                operation=operation,
                reason="Destructive operations are disabled",
                setting="MCP_DISABLE_DESTRUCTIVE",
            )

        # LAYER 3: Require explicit confirmation
        # BOTH conditions must be true:
        # - confirmed must be True (not just truthy)
        # - confirm_name must exactly match target
        if not confirmed or confirm_name != target:
            return ConfirmationRequired(
                operation=operation,
                target=target,
                impact=self._get_impact_description(operation),
                confirmation_instructions=(
                    f"To proceed, set confirm=true AND confirm_name='{target}'"
                ),
            )

        # All checks passed! Operation is allowed.
        return None

    def check_cluster_operation(
        self,
        operation: str,
        cluster: str,
    ) -> OperationBlocked | None:
        """
        Check if operation on specific cluster is allowed.

        When MCP_SINGLE_CLUSTER=true, only operations on the "in-cluster"
        cluster (where ArgoCD is running) are allowed.

        WHY SINGLE CLUSTER MODE?
        ------------------------
        In multi-cluster setups, ArgoCD manages multiple Kubernetes clusters.
        You might want to allow AI to work on the local cluster but not
        affect remote production clusters.

        "in-cluster" is the special name for the cluster where ArgoCD itself
        is running.

        Args:
            operation: Operation name
            cluster: Target cluster identifier

        Returns:
            OperationBlocked if cluster access denied, None if allowed.
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
        """
        Get human-readable impact description for operation.

        This provides clear descriptions of what destructive operations do,
        so users/AI can make informed decisions.

        The descriptions are intentionally ALARMING - we WANT people to pause
        and think before confirming.

        Args:
            operation: Operation identifier

        Returns:
            Impact description string
        """
        # Map of operation -> impact description
        impacts = {
            "delete_application": (
                "Application and all managed resources will be PERMANENTLY DELETED"
            ),
            "sync_with_prune": ("Resources not in Git will be DELETED from cluster"),
            "sync_with_force": ("Resources will be replaced, potentially causing downtime"),
            "rollback": ("Application will revert to previous state, may cause service disruption"),
        }
        # Return specific description or generic fallback
        return impacts.get(operation, "This operation may have significant impact")
