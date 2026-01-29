# ABOUTME: Structured logging with correlation IDs for ArgoCD MCP Server
# ABOUTME: Implements audit logging and observability patterns

"""Structured logging with correlation IDs and audit trails."""

from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

# Context variable for correlation ID
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Get current correlation ID or generate new one."""
    cid = correlation_id.get()
    if not cid:
        cid = str(uuid.uuid4())[:8]
        correlation_id.set(cid)
    return cid


def set_correlation_id(cid: str) -> None:
    """Set correlation ID for current context."""
    correlation_id.set(cid)


def add_correlation_id(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add correlation ID to log events."""
    event_dict["correlation_id"] = get_correlation_id()
    return event_dict


def configure_logging(
    level: str = "INFO",
    json_output: bool = False,
) -> None:
    """Configure structured logging.

    Args:
        level: Logging level
        json_output: Output as JSON instead of human-readable
    """
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        add_correlation_id,
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


class AuditLogger:
    """Audit logger for recording all operations."""

    def __init__(self, log_path: Path | None = None) -> None:
        """Initialize audit logger.

        Args:
            log_path: Path to audit log file, or None for stdout
        """
        self._log_path = log_path
        self._logger = structlog.get_logger("audit")

    def log(
        self,
        action: str,
        target: str,
        result: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log an auditable action.

        Args:
            action: Action performed (e.g., "sync_application")
            target: Target resource
            result: Result (e.g., "success", "blocked", "error")
            details: Additional details
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": get_correlation_id(),
            "action": action,
            "target": target,
            "result": result,
        }
        if details:
            entry["details"] = details

        if self._log_path:
            with self._log_path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        else:
            self._logger.info(
                "audit",
                action=action,
                target=target,
                result=result,
                details=details,
            )

    def log_read(self, action: str, target: str) -> None:
        """Log a read operation."""
        self.log(action, target, "success")

    def log_write(
        self,
        action: str,
        target: str,
        result: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log a write operation."""
        self.log(action, target, result, details)

    def log_blocked(
        self,
        action: str,
        target: str,
        reason: str,
    ) -> None:
        """Log a blocked operation."""
        self.log(action, target, "blocked", {"reason": reason})

    def log_error(
        self,
        action: str,
        target: str,
        error: str,
    ) -> None:
        """Log an error."""
        self.log(action, target, "error", {"error": error})
