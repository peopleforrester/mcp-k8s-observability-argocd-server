# ABOUTME: Shared fixtures and mock MCP SDK setup for the unit test suite
# ABOUTME: Imported by pytest before any test module, so the SDK patch lands first

"""Shared unit-test scaffolding.

The mock ``mcp.server.fastmcp`` module installed here is what lets the tool
handlers be called directly. It must be in ``sys.modules`` before any test
module imports ``argocd_mcp``, which is why it lives in conftest rather than in
an individual test file.

That mock is also the reason ``test_server_startup.py`` exists and runs in a
subprocess: a decorator that returns the function unchanged never evaluates the
type hints the real SDK resolves at registration.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Create proper mocks for MCP module before importing server
# The tool decorator needs to return the function unchanged for testing


class MockFastMCP:
    """Mock FastMCP class that passes through decorated functions."""

    def __init__(self, *args, **kwargs):
        self.tools = {}
        self.resources = {}

    def tool(self):
        """Decorator that passes through the function."""

        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator

    def resource(self, name):
        """Decorator for resources."""

        def decorator(func):
            self.resources[name] = func
            return func

        return decorator

    def run(self):
        """Mock run method."""
        pass


class MockContext:
    """Mock MCP Context class."""

    def __init__(self, request_id: str = "test-request-123") -> None:
        self.request_id = request_id

    def __class_getitem__(cls, params: Any) -> type:
        """Support generic subscripting like Context[Any, Any]."""
        return cls

    async def report_progress(self, *args: Any, **kwargs: Any) -> None:
        pass


# Setup mocks before importing server
mock_fastmcp_module = MagicMock()
mock_fastmcp_module.FastMCP = MockFastMCP
mock_fastmcp_module.Context = MockContext

sys.modules["mcp"] = MagicMock()
sys.modules["mcp.server"] = MagicMock()
sys.modules["mcp.server.fastmcp"] = mock_fastmcp_module

from argocd_mcp.config import SecuritySettings, ServerSettings
from argocd_mcp.utils.logging import AuditLogger
from argocd_mcp.utils.safety import SafetyGuard


def _make_server_context(
    *,
    settings: ServerSettings | None = None,
    safety_guard: SafetyGuard | None = None,
    audit_logger: Any | None = None,
    clients: dict[str, Any] | None = None,
):
    """Construct a ServerContext for tests, filling unset fields with mocks."""
    from argocd_mcp.server import ServerContext

    return ServerContext(
        settings=settings if settings is not None else MagicMock(spec=ServerSettings),
        safety_guard=safety_guard if safety_guard is not None else SafetyGuard(SecuritySettings()),
        audit_logger=audit_logger if audit_logger is not None else MagicMock(spec=AuditLogger),
        clients=clients if clients is not None else {},
    )


@pytest.fixture
def reset_server_context():
    """Save and restore server._context around each test that mutates it."""
    from argocd_mcp import server

    original = server._context
    yield
    server._context = original


@pytest.fixture
def mock_ctx():
    """Create a mock MCP context with async report_progress."""
    ctx = MagicMock()
    ctx.request_id = "test-request-123"
    ctx.report_progress = AsyncMock()
    return ctx


@pytest.fixture
def server_with_mocks(
    mock_argocd_client: AsyncMock,
    safety_guard: SafetyGuard,
    mock_ctx: MagicMock,
):
    """Setup server module with mocks for testing tools."""
    from argocd_mcp import server

    original = server._context
    audit_logger = MagicMock(spec=AuditLogger)
    server._context = _make_server_context(
        safety_guard=safety_guard,
        audit_logger=audit_logger,
        clients={"primary": mock_argocd_client},
    )

    yield {
        "client": mock_argocd_client,
        "guard": safety_guard,
        "logger": audit_logger,
        "ctx": mock_ctx,
    }

    server._context = original


@pytest.fixture
def server_read_only(
    mock_argocd_client: AsyncMock,
    read_only_safety_guard: SafetyGuard,
    mock_ctx: MagicMock,
):
    """Setup server module with read-only safety guard."""
    from argocd_mcp import server

    original = server._context
    audit_logger = MagicMock(spec=AuditLogger)
    server._context = _make_server_context(
        safety_guard=read_only_safety_guard,
        audit_logger=audit_logger,
        clients={"primary": mock_argocd_client},
    )

    yield {
        "client": mock_argocd_client,
        "guard": read_only_safety_guard,
        "logger": audit_logger,
        "ctx": mock_ctx,
    }

    server._context = original
