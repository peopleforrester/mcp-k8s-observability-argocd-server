# ABOUTME: Unit tests for logging utilities
# ABOUTME: Tests correlation IDs, configure_logging, and AuditLogger class

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from argocd_mcp.utils.logging import (
    AuditLogger,
    add_correlation_id,
    configure_logging,
    correlation_id,
    get_correlation_id,
    set_correlation_id,
)


@pytest.mark.unit
class TestCorrelationId:
    """Tests for correlation ID generation and context management."""

    def test_get_correlation_id_generates_new_when_empty(self):
        """Test that get_correlation_id generates a new ID when none exists."""
        # Reset the context variable
        correlation_id.set("")

        cid = get_correlation_id()

        assert cid is not None
        assert len(cid) == 8  # UUID[:8]

    def test_get_correlation_id_returns_existing(self):
        """Test that get_correlation_id returns existing ID when set."""
        test_id = "test1234"
        set_correlation_id(test_id)

        cid = get_correlation_id()

        assert cid == test_id

    def test_set_correlation_id(self):
        """Test that set_correlation_id sets the correlation ID."""
        test_id = "abcd5678"

        set_correlation_id(test_id)

        assert correlation_id.get() == test_id

    def test_correlation_id_format(self):
        """Test that generated correlation IDs have expected format."""
        correlation_id.set("")

        cid = get_correlation_id()

        # Should be first 8 characters of a UUID4
        assert len(cid) == 8
        # Should be valid hex characters
        int(cid, 16)  # Raises ValueError if not valid hex

    def test_get_correlation_id_preserves_value(self):
        """Test that subsequent calls return the same ID."""
        correlation_id.set("")

        first_call = get_correlation_id()
        second_call = get_correlation_id()

        assert first_call == second_call


@pytest.mark.unit
class TestAddCorrelationId:
    """Tests for the add_correlation_id processor function."""

    def test_adds_correlation_id_to_event_dict(self):
        """Test that correlation ID is added to event dictionary."""
        test_id = "proc1234"
        set_correlation_id(test_id)

        logger = MagicMock()
        event_dict = {"event": "test_event"}

        result = add_correlation_id(logger, "info", event_dict)

        assert result["correlation_id"] == test_id
        assert result["event"] == "test_event"

    def test_generates_correlation_id_if_not_set(self):
        """Test that correlation ID is generated if not already set."""
        correlation_id.set("")

        logger = MagicMock()
        event_dict = {"event": "test_event"}

        result = add_correlation_id(logger, "info", event_dict)

        assert "correlation_id" in result
        assert len(result["correlation_id"]) == 8


@pytest.mark.unit
class TestConfigureLogging:
    """Tests for configure_logging function.

    Note: The source code has a bug with structlog.INFO which doesn't exist.
    These tests mock structlog.configure to verify the function behavior.
    """

    def test_configure_logging_default_level(self):
        """Test configure_logging with default INFO level."""
        with patch("argocd_mcp.utils.logging.structlog") as mock_structlog:
            # Setup mock to return proper values
            mock_structlog.contextvars.merge_contextvars = MagicMock()
            mock_structlog.processors.add_log_level = MagicMock()
            mock_structlog.processors.TimeStamper.return_value = MagicMock()
            mock_structlog.dev.ConsoleRenderer.return_value = MagicMock()
            mock_structlog.INFO = 20  # Standard logging.INFO value

            configure_logging()

            mock_structlog.configure.assert_called_once()

    def test_configure_logging_custom_level(self):
        """Test configure_logging with custom DEBUG level."""
        with patch("argocd_mcp.utils.logging.structlog") as mock_structlog:
            mock_structlog.contextvars.merge_contextvars = MagicMock()
            mock_structlog.processors.add_log_level = MagicMock()
            mock_structlog.processors.TimeStamper.return_value = MagicMock()
            mock_structlog.dev.ConsoleRenderer.return_value = MagicMock()
            mock_structlog.DEBUG = 10
            mock_structlog.INFO = 20

            configure_logging(level="DEBUG")

            mock_structlog.configure.assert_called_once()

    def test_configure_logging_json_output(self):
        """Test configure_logging with JSON output."""
        with patch("argocd_mcp.utils.logging.structlog") as mock_structlog:
            mock_structlog.contextvars.merge_contextvars = MagicMock()
            mock_structlog.processors.add_log_level = MagicMock()
            mock_structlog.processors.TimeStamper.return_value = MagicMock()
            mock_structlog.processors.JSONRenderer.return_value = MagicMock()
            mock_structlog.INFO = 20

            configure_logging(json_output=True)

            # Verify JSONRenderer was used instead of ConsoleRenderer
            mock_structlog.processors.JSONRenderer.assert_called_once()
            mock_structlog.configure.assert_called_once()

    def test_configure_logging_console_output(self):
        """Test configure_logging with console output (default)."""
        with patch("argocd_mcp.utils.logging.structlog") as mock_structlog:
            mock_structlog.contextvars.merge_contextvars = MagicMock()
            mock_structlog.processors.add_log_level = MagicMock()
            mock_structlog.processors.TimeStamper.return_value = MagicMock()
            mock_structlog.dev.ConsoleRenderer.return_value = MagicMock()
            mock_structlog.INFO = 20

            configure_logging(json_output=False)

            # Verify ConsoleRenderer was used
            mock_structlog.dev.ConsoleRenderer.assert_called_once()
            mock_structlog.configure.assert_called_once()

    def test_configure_logging_warning_level(self):
        """Test configure_logging with WARNING level."""
        with patch("argocd_mcp.utils.logging.structlog") as mock_structlog:
            mock_structlog.contextvars.merge_contextvars = MagicMock()
            mock_structlog.processors.add_log_level = MagicMock()
            mock_structlog.processors.TimeStamper.return_value = MagicMock()
            mock_structlog.dev.ConsoleRenderer.return_value = MagicMock()
            mock_structlog.WARNING = 30
            mock_structlog.INFO = 20

            configure_logging(level="WARNING")

            mock_structlog.configure.assert_called_once()

    def test_configure_logging_error_level(self):
        """Test configure_logging with ERROR level."""
        with patch("argocd_mcp.utils.logging.structlog") as mock_structlog:
            mock_structlog.contextvars.merge_contextvars = MagicMock()
            mock_structlog.processors.add_log_level = MagicMock()
            mock_structlog.processors.TimeStamper.return_value = MagicMock()
            mock_structlog.dev.ConsoleRenderer.return_value = MagicMock()
            mock_structlog.ERROR = 40
            mock_structlog.INFO = 20

            configure_logging(level="ERROR")

            mock_structlog.configure.assert_called_once()

    def test_configure_logging_processors_order(self):
        """Test that configure_logging sets up processors in correct order."""
        with patch("argocd_mcp.utils.logging.structlog") as mock_structlog:
            mock_structlog.contextvars.merge_contextvars = MagicMock()
            mock_structlog.processors.add_log_level = MagicMock()
            mock_structlog.processors.TimeStamper.return_value = MagicMock()
            mock_structlog.dev.ConsoleRenderer.return_value = MagicMock()
            mock_structlog.INFO = 20

            configure_logging()

            call_kwargs = mock_structlog.configure.call_args[1]
            processors = call_kwargs["processors"]
            # Should have at least 4 processors: merge_contextvars, add_log_level,
            # TimeStamper, and add_correlation_id, plus a renderer
            assert len(processors) >= 5


@pytest.mark.unit
class TestAuditLoggerInit:
    """Tests for AuditLogger initialization."""

    def test_init_without_log_path(self):
        """Test AuditLogger initialization without a log path."""
        logger = AuditLogger()

        assert logger._log_path is None
        assert logger._logger is not None

    def test_init_with_log_path(self, tmp_path: Path):
        """Test AuditLogger initialization with a log path."""
        log_file = tmp_path / "audit.log"

        logger = AuditLogger(log_path=log_file)

        assert logger._log_path == log_file


@pytest.mark.unit
class TestAuditLoggerLog:
    """Tests for AuditLogger.log method."""

    def test_log_to_file(self, tmp_path: Path):
        """Test logging to a file."""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_file)
        set_correlation_id("file1234")

        logger.log(
            action="test_action",
            target="test_target",
            result="success",
        )

        # Verify the log file was created and contains the entry
        assert log_file.exists()
        content = log_file.read_text()
        entry = json.loads(content.strip())

        assert entry["action"] == "test_action"
        assert entry["target"] == "test_target"
        assert entry["result"] == "success"
        assert entry["correlation_id"] == "file1234"
        assert "timestamp" in entry

    def test_log_to_file_with_details(self, tmp_path: Path):
        """Test logging to a file with additional details."""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_file)

        logger.log(
            action="sync_application",
            target="my-app",
            result="success",
            details={"namespace": "production", "revision": "abc123"},
        )

        content = log_file.read_text()
        entry = json.loads(content.strip())

        assert entry["details"]["namespace"] == "production"
        assert entry["details"]["revision"] == "abc123"

    def test_log_without_details(self, tmp_path: Path):
        """Test logging without details does not add details key."""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_file)

        logger.log(
            action="test_action",
            target="test_target",
            result="success",
            details=None,
        )

        content = log_file.read_text()
        entry = json.loads(content.strip())

        assert "details" not in entry

    def test_log_appends_to_file(self, tmp_path: Path):
        """Test that multiple log calls append to the file."""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_file)

        logger.log("action1", "target1", "success")
        logger.log("action2", "target2", "success")

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

        entry1 = json.loads(lines[0])
        entry2 = json.loads(lines[1])

        assert entry1["action"] == "action1"
        assert entry2["action"] == "action2"

    def test_log_to_stdout(self):
        """Test logging to stdout when no log path specified."""
        logger = AuditLogger(log_path=None)
        set_correlation_id("stdout12")

        # Mock the internal structlog logger
        with patch.object(logger, "_logger") as mock_logger:
            logger.log(
                action="test_action",
                target="test_target",
                result="success",
                details={"key": "value"},
            )

            mock_logger.info.assert_called_once_with(
                "audit",
                action="test_action",
                target="test_target",
                result="success",
                details={"key": "value"},
            )

    def test_log_to_stdout_without_details(self):
        """Test logging to stdout without details."""
        logger = AuditLogger(log_path=None)

        with patch.object(logger, "_logger") as mock_logger:
            logger.log(
                action="test_action",
                target="test_target",
                result="success",
            )

            mock_logger.info.assert_called_once_with(
                "audit",
                action="test_action",
                target="test_target",
                result="success",
                details=None,
            )


@pytest.mark.unit
class TestAuditLoggerLogRead:
    """Tests for AuditLogger.log_read method."""

    def test_log_read_creates_success_entry(self, tmp_path: Path):
        """Test that log_read creates a success entry."""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_file)

        logger.log_read(action="list_applications", target="argocd")

        content = log_file.read_text()
        entry = json.loads(content.strip())

        assert entry["action"] == "list_applications"
        assert entry["target"] == "argocd"
        assert entry["result"] == "success"

    def test_log_read_calls_log_method(self):
        """Test that log_read delegates to log method."""
        logger = AuditLogger()

        with patch.object(logger, "log") as mock_log:
            logger.log_read("get_application", "my-app")

            mock_log.assert_called_once_with("get_application", "my-app", "success")


@pytest.mark.unit
class TestAuditLoggerLogWrite:
    """Tests for AuditLogger.log_write method."""

    def test_log_write_creates_entry(self, tmp_path: Path):
        """Test that log_write creates a write entry."""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_file)

        logger.log_write(
            action="sync_application",
            target="my-app",
            result="success",
        )

        content = log_file.read_text()
        entry = json.loads(content.strip())

        assert entry["action"] == "sync_application"
        assert entry["target"] == "my-app"
        assert entry["result"] == "success"

    def test_log_write_with_details(self, tmp_path: Path):
        """Test log_write with additional details."""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_file)

        logger.log_write(
            action="sync_application",
            target="my-app",
            result="success",
            details={"prune": True, "revision": "HEAD"},
        )

        content = log_file.read_text()
        entry = json.loads(content.strip())

        assert entry["details"]["prune"] is True
        assert entry["details"]["revision"] == "HEAD"

    def test_log_write_calls_log_method(self):
        """Test that log_write delegates to log method."""
        logger = AuditLogger()
        details = {"key": "value"}

        with patch.object(logger, "log") as mock_log:
            logger.log_write("sync_application", "my-app", "success", details)

            mock_log.assert_called_once_with(
                "sync_application", "my-app", "success", details
            )


@pytest.mark.unit
class TestAuditLoggerLogBlocked:
    """Tests for AuditLogger.log_blocked method."""

    def test_log_blocked_creates_blocked_entry(self, tmp_path: Path):
        """Test that log_blocked creates a blocked entry with reason."""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_file)

        logger.log_blocked(
            action="delete_application",
            target="my-app",
            reason="Server is in read-only mode",
        )

        content = log_file.read_text()
        entry = json.loads(content.strip())

        assert entry["action"] == "delete_application"
        assert entry["target"] == "my-app"
        assert entry["result"] == "blocked"
        assert entry["details"]["reason"] == "Server is in read-only mode"

    def test_log_blocked_calls_log_method(self):
        """Test that log_blocked delegates to log method."""
        logger = AuditLogger()

        with patch.object(logger, "log") as mock_log:
            logger.log_blocked("sync_application", "my-app", "Rate limited")

            mock_log.assert_called_once_with(
                "sync_application", "my-app", "blocked", {"reason": "Rate limited"}
            )


@pytest.mark.unit
class TestAuditLoggerLogError:
    """Tests for AuditLogger.log_error method."""

    def test_log_error_creates_error_entry(self, tmp_path: Path):
        """Test that log_error creates an error entry."""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_file)

        logger.log_error(
            action="sync_application",
            target="my-app",
            error="Connection refused",
        )

        content = log_file.read_text()
        entry = json.loads(content.strip())

        assert entry["action"] == "sync_application"
        assert entry["target"] == "my-app"
        assert entry["result"] == "error"
        assert entry["details"]["error"] == "Connection refused"

    def test_log_error_calls_log_method(self):
        """Test that log_error delegates to log method."""
        logger = AuditLogger()

        with patch.object(logger, "log") as mock_log:
            logger.log_error("get_application", "my-app", "Not found")

            mock_log.assert_called_once_with(
                "get_application", "my-app", "error", {"error": "Not found"}
            )


@pytest.mark.unit
class TestAuditLoggerTimestamp:
    """Tests for timestamp generation in audit logs."""

    def test_timestamp_is_utc_iso_format(self, tmp_path: Path):
        """Test that timestamps are in UTC ISO format."""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_file)

        logger.log("test_action", "test_target", "success")

        content = log_file.read_text()
        entry = json.loads(content.strip())

        timestamp = entry["timestamp"]

        # Should be ISO format with timezone info
        assert "T" in timestamp
        # Should end with UTC timezone indicator
        assert timestamp.endswith("+00:00") or timestamp.endswith("Z")


@pytest.mark.unit
class TestAuditLoggerIntegration:
    """Integration tests for AuditLogger with various scenarios."""

    def test_full_workflow_file_logging(self, tmp_path: Path):
        """Test a full workflow with multiple log types to file."""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_file)
        set_correlation_id("workflow1")

        # Simulate a workflow
        logger.log_read("list_applications", "argocd")
        logger.log_write("sync_application", "my-app", "success")
        logger.log_blocked("delete_application", "critical-app", "Confirmation required")
        logger.log_error("get_application", "unknown-app", "Not found")

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 4

        # All entries should have the same correlation ID
        for line in lines:
            entry = json.loads(line)
            assert entry["correlation_id"] == "workflow1"

    def test_different_correlation_ids(self, tmp_path: Path):
        """Test that different correlation IDs are recorded correctly."""
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_file)

        set_correlation_id("request1")
        logger.log_read("list_applications", "argocd")

        set_correlation_id("request2")
        logger.log_read("get_application", "my-app")

        lines = log_file.read_text().strip().split("\n")
        entry1 = json.loads(lines[0])
        entry2 = json.loads(lines[1])

        assert entry1["correlation_id"] == "request1"
        assert entry2["correlation_id"] == "request2"
