# ABOUTME: Regression test that server.py imports and registers tools against the
# ABOUTME: real MCP SDK, guarding the startup path the rest of the suite mocks away.

"""Server startup regression test.

The rest of the unit suite replaces ``mcp.server.fastmcp`` with a mock whose
``tool()`` decorator returns the function unchanged. That mock never evaluates
tool parameter type hints, so it hid a real defect: handlers annotated their
context parameter with a name (``MCPContext``) that existed only under
``TYPE_CHECKING``. The real SDK resolves annotations via ``get_type_hints()`` at
registration, raising ``InvalidSignature`` — meaning ``uv run argocd-mcp`` could
not start, even though every mocked unit test passed.

This test imports the server in a clean subprocess against the real SDK,
reproducing the exact entry-point path, and asserts every tool registers.
A subprocess is required because the mock above patches ``sys.modules`` at
import time and would otherwise leak into this test.
"""

from __future__ import annotations

import subprocess
import sys

EXPECTED_TOOL_COUNT = 15


def test_server_module_registers_all_tools_with_real_sdk() -> None:
    """Importing the server must register every tool via the real MCP SDK."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import argocd_mcp.server as s; print(len(s.mcp._tool_manager.list_tools()))",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        "Server import failed — `uv run argocd-mcp` would not start:\n" + result.stderr
    )
    assert result.stdout.strip() == str(EXPECTED_TOOL_COUNT), (
        f"Expected {EXPECTED_TOOL_COUNT} registered tools, got {result.stdout.strip()!r}"
    )
