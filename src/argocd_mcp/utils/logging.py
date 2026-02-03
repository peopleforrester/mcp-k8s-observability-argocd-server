# ABOUTME: Structured logging with correlation IDs for ArgoCD MCP Server
# ABOUTME: Implements audit logging and observability patterns

"""
Structured logging with correlation IDs and audit trails.

=============================================================================
WHAT IS THIS FILE?
=============================================================================

This module provides two critical observability features:

1. STRUCTURED LOGGING: Logs in machine-readable format (JSON) with consistent
   fields, making it easy to search and analyze logs.

2. CORRELATION IDs: Unique identifiers that link all log entries from a single
   request together, crucial for debugging in async systems.

3. AUDIT LOGGING: Records all operations for security compliance and debugging.

=============================================================================
WHY STRUCTURED LOGGING?
=============================================================================

Traditional logging:
    logger.info(f"User {user} synced app {app} at {time}")
    # Output: "INFO: User alice synced app myapp at 2024-01-15 10:30:00"

Problems:
- Hard to parse programmatically
- Field order varies
- Can't easily filter/search

Structured logging:
    logger.info("app_synced", user="alice", app="myapp")
    # Output: {"event": "app_synced", "user": "alice", "app": "myapp", ...}

Benefits:
- Machine-readable (JSON)
- Consistent fields
- Easy to search: `jq '.user == "alice"'`
- Works with log aggregators (Elasticsearch, Datadog, etc.)

=============================================================================
WHAT ARE CORRELATION IDs?
=============================================================================

When an AI assistant makes a request, many things happen:
1. Request received by MCP server
2. Safety check performed
3. ArgoCD API called (possibly multiple times)
4. Response formatted
5. Audit log written
6. Response sent

Each step might log something. How do you know which logs belong together?

CORRELATION ID: A unique identifier attached to ALL logs from ONE request.

Example logs with correlation IDs:
    {"correlation_id": "a1b2c3", "event": "request_received", "tool": "list_apps"}
    {"correlation_id": "a1b2c3", "event": "safety_check", "result": "allowed"}
    {"correlation_id": "a1b2c3", "event": "api_call", "endpoint": "/applications"}
    {"correlation_id": "a1b2c3", "event": "response_sent", "apps_count": 5}

Now you can filter: `jq 'select(.correlation_id == "a1b2c3")'`

=============================================================================
CONTEXT VARIABLES (contextvars)
=============================================================================

The correlation_id needs to be available throughout the request, but:
- We don't want to pass it through every function
- Global variables don't work with async (multiple concurrent requests)

Python's `contextvars` module solves this:
- Like thread-local storage, but for async tasks
- Each async task gets its own "context"
- Variables set in one task don't affect others

Example:
    async def request_1():
        correlation_id.set("aaa")
        await some_operation()  # Uses "aaa"

    async def request_2():
        correlation_id.set("bbb")
        await some_operation()  # Uses "bbb"

    # Both can run concurrently without interference!
"""

# =============================================================================
# IMPORTS
# =============================================================================
#
# Standard library:
# - json: Serialize audit log entries to JSON format
# - logging: Get log level constants (DEBUG, INFO, etc.) as integers
# - uuid: Generate unique correlation IDs
# - ContextVar: Async-safe context-local storage for correlation IDs
# - UTC/datetime: Timezone-aware timestamps for audit logs
# - TYPE_CHECKING: Only True during static analysis, not runtime
#
# Third-party:
# - structlog: Structured logging with JSON output and processors
#
# Type-checking only:
# - MutableMapping: Type for dict-like objects in processor signatures
# - Path: Type for audit log file path parameter
# =============================================================================

from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import MutableMapping
    from pathlib import Path


# =============================================================================
# CORRELATION ID MANAGEMENT
# =============================================================================

# ContextVar for the correlation ID.
# ContextVar is like a global variable, but each async task sees its own value.
# First parameter is the name (for debugging), second is the default value.
# Use .set() to store a value and .get() to retrieve it.
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """
    Get current correlation ID or generate new one.

    This function is the PRIMARY way to access the correlation ID throughout
    the codebase. It handles the case where no ID has been set yet.

    BEHAVIOR:
    ---------
    1. Check if a correlation ID exists in the current context
    2. If yes, return it
    3. If no, generate a new one, store it, and return it

    WHY GENERATE IF MISSING?
    ------------------------
    Sometimes code runs outside a request context (startup, background tasks).
    Rather than failing or returning None, we generate an ID so logs are
    always correlatable.

    WHY ONLY 8 CHARACTERS?
    ----------------------
    Full UUIDs are 36 characters (550e8400-e29b-41d4-a716-446655440000).
    For correlation IDs, we only need uniqueness within a short timeframe.
    8 characters from UUID4 gives ~4 billion combinations - enough to avoid
    collisions in practical use while keeping logs readable.

    Returns:
        8-character correlation ID string.

    Example:
        >>> get_correlation_id()
        'a3f8c2d1'
    """
    cid = correlation_id.get()
    if not cid:
        # Generate new UUID, take first 8 characters
        # uuid.uuid4() generates a random UUID (version 4)
        cid = str(uuid.uuid4())[:8]
        correlation_id.set(cid)
    return cid


def set_correlation_id(cid: str) -> None:
    """
    Set correlation ID for current context.

    Called at the START of each request to establish the correlation ID.
    All subsequent logs in this async context will include this ID.

    WHEN TO CALL:
    -------------
    1. At the beginning of each MCP tool function
    2. When processing incoming requests
    3. When you want to explicitly link operations together

    Args:
        cid: The correlation ID to set. Can be:
             - Empty string "" (will cause get_correlation_id to generate new one)
             - Request ID from MCP context
             - Custom ID for linking related operations

    Example:
        set_correlation_id(ctx.request_id)  # Use MCP's request ID
        set_correlation_id("")              # Will generate new ID when accessed
    """
    correlation_id.set(cid)


def add_correlation_id(
    logger: structlog.types.WrappedLogger,  # noqa: ARG001 - Required by structlog Processor API
    method_name: str,  # noqa: ARG001 - Required by structlog Processor API
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """
    Add correlation ID to log events.

    This is a STRUCTLOG PROCESSOR - a function that transforms log events
    before they're output.

    WHAT IS A STRUCTLOG PROCESSOR?
    ------------------------------
    Structlog processes logs through a pipeline of functions (processors):

    1. User calls: logger.info("event", key="value")
    2. Processor 1: Adds timestamp
    3. Processor 2: Adds log level
    4. Processor 3: Adds correlation ID (THIS FUNCTION)
    5. Renderer: Converts to JSON or colored text

    Each processor receives the log event dictionary and returns it
    (possibly modified).

    WHY noqa: ARG001?
    -----------------
    The structlog processor API requires these parameters:
    - logger: The underlying logger object
    - method_name: The log method called ("info", "debug", etc.)
    - event_dict: The actual log data

    We don't use logger or method_name, but they're required by the API.
    The noqa comment tells the linter "yes, I know these are unused, it's OK".

    Args:
        logger: The structlog wrapped logger (unused but required by API)
        method_name: The logging method name (unused but required by API)
        event_dict: Dictionary containing log event data to enrich

    Returns:
        The event_dict with "correlation_id" field added.
    """
    event_dict["correlation_id"] = get_correlation_id()
    return event_dict


# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================


def configure_logging(
    level: str = "INFO",
    json_output: bool = False,
) -> None:
    """
    Configure structured logging.

    This function sets up the entire logging system. Call it ONCE at startup.
    Calling it again will reconfigure logging (useful for changing levels).

    HOW STRUCTLOG WORKS:
    --------------------
    Structlog has three main concepts:

    1. PROCESSORS: Functions that transform log events (add fields, format)
    2. WRAPPER CLASS: Configures log levels (DEBUG, INFO, etc.)
    3. RENDERER: Final output format (JSON, colored console, etc.)

    PROCESSOR PIPELINE:
    -------------------
    Our pipeline:
    1. merge_contextvars: Adds any context variables
    2. add_log_level: Adds "level" field ("INFO", "DEBUG", etc.)
    3. TimeStamper: Adds ISO-format timestamp
    4. add_correlation_id: Adds our correlation ID
    5. Renderer: Converts to JSON or colored text

    Args:
        level: Logging level as string. One of:
               - "DEBUG": Very verbose, includes all details
               - "INFO": Normal operation messages
               - "WARNING": Something unexpected happened
               - "ERROR": Operation failed
               - "CRITICAL": Server cannot continue

        json_output: If True, output JSON (for production/log aggregators).
                    If False, output colored text (for development).

    Example:
        # Development setup (readable colored output)
        configure_logging(level="DEBUG", json_output=False)

        # Production setup (JSON for log aggregation)
        configure_logging(level="INFO", json_output=True)
    """
    # Build the processor pipeline
    # Each processor is a function that takes (logger, method, event_dict) -> event_dict
    processors: list[structlog.types.Processor] = [
        # merge_contextvars: Pulls in any context set via structlog.contextvars.bind_contextvars()
        # Useful for binding request-specific data that should appear in all logs
        structlog.contextvars.merge_contextvars,
        # add_log_level: Adds "level" field with the log level name
        # {"event": "hello"} -> {"event": "hello", "level": "info"}
        structlog.processors.add_log_level,
        # TimeStamper: Adds timestamp in ISO 8601 format
        # {"event": "hello"} -> {"event": "hello", "timestamp": "2024-01-15T10:30:00Z"}
        structlog.processors.TimeStamper(fmt="iso"),
        # add_correlation_id: Our custom processor (defined above)
        # Adds the correlation ID for request tracing
        add_correlation_id,
    ]

    # Add the appropriate renderer based on output mode
    if json_output:
        # JSONRenderer: Outputs each log as a single JSON line
        # Perfect for: Production, log aggregators, parsing
        # Output: {"event": "hello", "level": "info", "timestamp": "...", ...}
        processors.append(structlog.processors.JSONRenderer())
    else:
        # ConsoleRenderer: Pretty colored output for terminals
        # Perfect for: Development, debugging
        # Output: 2024-01-15 10:30:00 [info] hello correlation_id=abc123
        processors.append(structlog.dev.ConsoleRenderer())

    # Configure structlog with our settings
    structlog.configure(
        processors=processors,
        # make_filtering_bound_logger: Creates a logger that filters by level
        # getattr(logging, "INFO") returns 20 (the integer level)
        # Logs below this level are dropped
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        # context_class: What type to use for event_dict
        # dict is the default and fastest option
        context_class=dict,
        # logger_factory: Where to output logs
        # PrintLoggerFactory prints to stdout (captured by container orchestrators)
        logger_factory=structlog.PrintLoggerFactory(),
        # cache_logger_on_first_use: Performance optimization
        # Caches the configured logger after first use
        cache_logger_on_first_use=True,
    )


# =============================================================================
# AUDIT LOGGER
# =============================================================================


class AuditLogger:
    """
    Audit logger for recording all operations.

    WHAT IS AUDIT LOGGING?
    ----------------------
    Audit logging creates an immutable record of who did what, when.
    Required for:
    - Security compliance (SOC2, HIPAA, PCI-DSS)
    - Incident investigation
    - Debugging production issues
    - Usage analytics

    WHAT WE LOG:
    ------------
    Every operation records:
    - timestamp: When it happened (UTC ISO 8601)
    - correlation_id: Request identifier
    - action: What operation ("list_applications", "sync_application")
    - target: What resource ("my-app", "production-cluster")
    - result: Outcome ("success", "blocked", "error")
    - details: Additional context (error messages, parameters)

    TWO OUTPUT MODES:
    -----------------
    1. FILE: Append JSON lines to a file
       - Each line is a complete JSON object
       - File can be parsed by tools like jq
       - Easy to ship to log aggregators

    2. STDOUT: Use structlog
       - Integrates with normal logging
       - Good for containerized deployments
       - Captured by orchestrator (Kubernetes, Docker)

    EXAMPLE AUDIT LOG ENTRIES:
    --------------------------
    {"timestamp": "2024-01-15T10:30:00Z", "correlation_id": "abc123",
     "action": "list_applications", "target": "project=default", "result": "success"}

    {"timestamp": "2024-01-15T10:30:05Z", "correlation_id": "def456",
     "action": "sync_application", "target": "my-app", "result": "blocked",
     "details": {"reason": "read-only mode"}}
    """

    def __init__(self, log_path: Path | None = None) -> None:
        """
        Initialize audit logger.

        The choice of file vs stdout is made here and remains for the
        lifetime of the logger.

        Args:
            log_path: Path to audit log file, or None for stdout.

                     If provided:
                     - Must be a valid filesystem path
                     - Parent directory must exist
                     - File will be created if it doesn't exist
                     - Logs are APPENDED (never truncated)

                     If None:
                     - Logs go to stdout via structlog
                     - Integrates with the configured logging system

        Example:
            # Log to file
            logger = AuditLogger(Path("/var/log/audit.json"))

            # Log to stdout
            logger = AuditLogger()  # or AuditLogger(None)
        """
        self._log_path = log_path
        # Get a structlog logger for stdout output
        # The "audit" name helps identify these in mixed log streams
        self._logger = structlog.get_logger("audit")

    def log(
        self,
        action: str,
        target: str,
        result: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Log an auditable action.

        This is the core logging method. All specialized methods (log_read,
        log_write, etc.) delegate to this one.

        AUDIT ENTRY STRUCTURE:
        ----------------------
        {
            "timestamp": "2024-01-15T10:30:00.000000+00:00",
            "correlation_id": "abc12345",
            "action": "sync_application",
            "target": "my-app",
            "result": "success",
            "details": {"prune": false, "force": false}  // optional
        }

        Args:
            action: Action performed. Should be a tool name or operation type.
                   Examples: "list_applications", "sync_application", "delete_application"

            target: Target resource identifier.
                   Examples: "my-app", "project=production", "all"

            result: Result of the operation. Standard values:
                   - "success": Operation completed successfully
                   - "blocked": Operation was prevented by safety checks
                   - "error": Operation failed due to an error

            details: Additional context as a dictionary. Optional.
                    Examples:
                    - {"reason": "read-only mode"}
                    - {"error": "Connection refused"}
                    - {"prune": True, "force": False}
        """
        # Build the audit entry
        entry: dict[str, Any] = {
            # UTC timestamp in ISO 8601 format with timezone
            "timestamp": datetime.now(UTC).isoformat(),
            # Link to other logs from same request
            "correlation_id": get_correlation_id(),
            # What operation was performed
            "action": action,
            # What resource was affected
            "target": target,
            # What happened
            "result": result,
        }

        # Only include details if provided (keeps logs cleaner)
        if details:
            entry["details"] = details

        # Output to file or stdout
        if self._log_path:
            # FILE OUTPUT
            # Open in append mode ("a") - never overwrite existing logs
            # Each entry is written as a single JSON line
            with self._log_path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        else:
            # STDOUT OUTPUT via structlog
            # Uses the configured logging system
            self._logger.info(
                "audit",  # Event name
                action=action,
                target=target,
                result=result,
                details=details,
            )

    # -------------------------------------------------------------------------
    # CONVENIENCE METHODS
    # -------------------------------------------------------------------------
    # These methods provide semantic clarity and ensure consistent result values.

    def log_read(self, action: str, target: str) -> None:
        """
        Log a read operation.

        Read operations are always successful (if they weren't, we'd log an error).
        This method exists for semantic clarity in calling code.

        Args:
            action: The read operation performed (e.g., "list_applications")
            target: What was read (e.g., "project=default")

        Example:
            audit_logger.log_read("list_applications", "project=production")
            audit_logger.log_read("get_application", "my-app")
        """
        self.log(action, target, "success")

    def log_write(
        self,
        action: str,
        target: str,
        result: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Log a write operation.

        Write operations can have various results:
        - "success": Operation completed
        - "dry_run": Preview completed (no actual changes)
        - "initiated": Async operation started

        Args:
            action: The write operation performed (e.g., "sync_application")
            target: What was modified (e.g., "my-app")
            result: Outcome description
            details: Operation parameters or additional context

        Example:
            audit_logger.log_write(
                "sync_application",
                "my-app",
                "initiated",
                {"prune": False, "force": True}
            )
        """
        self.log(action, target, result, details)

    def log_blocked(
        self,
        action: str,
        target: str,
        reason: str,
    ) -> None:
        """
        Log a blocked operation.

        Called when a safety check prevents an operation from proceeding.
        This is IMPORTANT for security auditing - you want to know when
        someone (or an AI) tried to do something they weren't allowed to.

        Args:
            action: The attempted operation (e.g., "delete_application")
            target: What they tried to affect (e.g., "production-app")
            reason: Why it was blocked (e.g., "read-only mode")

        Example:
            audit_logger.log_blocked(
                "sync_application",
                "my-app",
                "Server is running in read-only mode"
            )
        """
        self.log(action, target, "blocked", {"reason": reason})

    def log_error(
        self,
        action: str,
        target: str,
        error: str,
    ) -> None:
        """
        Log an error.

        Called when an operation fails due to an error (not a safety block).
        Examples: network timeouts, API errors, invalid parameters.

        Args:
            action: The failed operation (e.g., "get_application")
            target: What we tried to access (e.g., "nonexistent-app")
            error: Error description (e.g., "Application not found")

        Example:
            audit_logger.log_error(
                "get_application",
                "my-app",
                "ArgoCD API error (404): Application not found"
            )
        """
        self.log(action, target, "error", {"error": error})
