# ABOUTME: Unit tests for safety utilities
# ABOUTME: Tests confirmation patterns, rate limiting, and operation guards

import pytest

from argocd_mcp.config import SecuritySettings
from argocd_mcp.utils.safety import (
    ConfirmationRequired,
    OperationBlocked,
    RateLimiter,
    SafetyGuard,
)


@pytest.mark.unit
class TestRateLimiter:
    """Tests for RateLimiter class."""

    def test_allows_calls_within_limit(self):
        """Test that calls within limit are allowed."""
        limiter = RateLimiter(max_calls=3, window_seconds=60)

        assert limiter.check("test") is True
        assert limiter.check("test") is True
        assert limiter.check("test") is True

    def test_blocks_calls_exceeding_limit(self):
        """Test that calls exceeding limit are blocked."""
        limiter = RateLimiter(max_calls=2, window_seconds=60)

        assert limiter.check("test") is True
        assert limiter.check("test") is True
        assert limiter.check("test") is False

    def test_independent_keys(self):
        """Test that different keys have independent limits."""
        limiter = RateLimiter(max_calls=1, window_seconds=60)

        assert limiter.check("key1") is True
        assert limiter.check("key2") is True
        assert limiter.check("key1") is False
        assert limiter.check("key2") is False

    def test_reset_specific_key(self):
        """Test resetting a specific key."""
        limiter = RateLimiter(max_calls=1, window_seconds=60)

        assert limiter.check("key1") is True
        assert limiter.check("key1") is False

        limiter.reset("key1")
        assert limiter.check("key1") is True

    def test_reset_all_keys(self):
        """Test resetting all keys."""
        limiter = RateLimiter(max_calls=1, window_seconds=60)

        limiter.check("key1")
        limiter.check("key2")

        limiter.reset()

        assert limiter.check("key1") is True
        assert limiter.check("key2") is True


@pytest.mark.unit
class TestSafetyGuard:
    """Tests for SafetyGuard class."""

    def test_read_operation_allowed(self, safety_guard: SafetyGuard):
        """Test that read operations are allowed."""
        result = safety_guard.check_read_operation("list_applications")
        assert result is None

    def test_read_operation_rate_limited(self):
        """Test that read operations can be rate limited."""
        settings = SecuritySettings(rate_limit_calls=1, rate_limit_window=60)
        guard = SafetyGuard(settings)

        assert guard.check_read_operation("test") is None
        result = guard.check_read_operation("test")
        assert isinstance(result, OperationBlocked)
        assert "Rate limit" in result.reason

    def test_write_operation_blocked_read_only(self, read_only_safety_guard: SafetyGuard):
        """Test that write operations are blocked in read-only mode."""
        result = read_only_safety_guard.check_write_operation("sync_application")
        assert isinstance(result, OperationBlocked)
        assert "read-only" in result.reason

    def test_write_operation_allowed(self, safety_guard: SafetyGuard):
        """Test that write operations are allowed when not read-only."""
        result = safety_guard.check_write_operation("sync_application")
        assert result is None

    def test_destructive_operation_blocked_read_only(self, read_only_safety_guard: SafetyGuard):
        """Test that destructive operations are blocked in read-only mode."""
        result = read_only_safety_guard.check_destructive_operation(
            "delete_application",
            "test-app",
            confirmed=True,
            confirm_name="test-app",
        )
        assert isinstance(result, OperationBlocked)

    def test_destructive_operation_requires_confirmation(self, safety_guard: SafetyGuard):
        """Test that destructive operations require confirmation."""
        result = safety_guard.check_destructive_operation(
            "delete_application",
            "test-app",
            confirmed=False,
        )
        assert isinstance(result, ConfirmationRequired)
        assert "test-app" in result.confirmation_instructions

    def test_destructive_operation_requires_name_match(self, safety_guard: SafetyGuard):
        """Test that destructive operations require name confirmation match."""
        result = safety_guard.check_destructive_operation(
            "delete_application",
            "test-app",
            confirmed=True,
            confirm_name="wrong-name",
        )
        assert isinstance(result, ConfirmationRequired)

    def test_destructive_operation_allowed_with_confirmation(self, safety_guard: SafetyGuard):
        """Test that destructive operations allowed with proper confirmation."""
        result = safety_guard.check_destructive_operation(
            "delete_application",
            "test-app",
            confirmed=True,
            confirm_name="test-app",
        )
        assert result is None

    def test_cluster_operation_blocked_single_cluster(self):
        """Test that non-default cluster blocked in single-cluster mode."""
        settings = SecuritySettings(single_cluster=True)
        guard = SafetyGuard(settings)

        result = guard.check_cluster_operation("sync", "remote-cluster")
        assert isinstance(result, OperationBlocked)
        assert "single-cluster" in result.reason

    def test_cluster_operation_allowed_in_cluster(self):
        """Test that in-cluster operations allowed in single-cluster mode."""
        settings = SecuritySettings(single_cluster=True)
        guard = SafetyGuard(settings)

        result = guard.check_cluster_operation("sync", "in-cluster")
        assert result is None


@pytest.mark.unit
class TestOperationBlocked:
    """Tests for OperationBlocked class."""

    def test_format_message(self):
        """Test message formatting."""
        blocked = OperationBlocked(
            operation="sync_application",
            reason="Server is read-only",
            setting="MCP_READ_ONLY",
        )

        message = blocked.format_message()
        assert "OPERATION BLOCKED" in message
        assert "sync_application" in message
        assert "MCP_READ_ONLY" in message


@pytest.mark.unit
class TestConfirmationRequired:
    """Tests for ConfirmationRequired class."""

    def test_format_message(self):
        """Test message formatting."""
        confirmation = ConfirmationRequired(
            operation="delete_application",
            target="my-app",
            impact="Application will be deleted",
            confirmation_instructions="Set confirm=true",
        )

        message = confirmation.format_message()
        assert "CONFIRMATION REQUIRED" in message
        assert "delete_application" in message
        assert "my-app" in message
        assert "confirm=true" in message

    def test_format_message_with_details(self):
        """Test message formatting with details."""
        confirmation = ConfirmationRequired(
            operation="delete_application",
            target="my-app",
            impact="Permanent deletion",
            confirmation_instructions="Set confirm=true",
            details={"namespace": "production", "resources": 5},
        )

        message = confirmation.format_message()
        assert "namespace: production" in message
        assert "resources: 5" in message
