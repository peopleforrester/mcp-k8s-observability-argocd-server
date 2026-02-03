# ABOUTME: Configuration management for ArgoCD MCP Server
# ABOUTME: Handles environment variables, security modes, and multi-instance settings

"""
Configuration management using pydantic-settings.

=============================================================================
WHAT IS THIS FILE?
=============================================================================

This module handles all configuration for the MCP server. It:

1. READS environment variables (like ARGOCD_URL, MCP_READ_ONLY)
2. VALIDATES them (ensures URLs are valid, booleans are booleans, etc.)
3. PROVIDES typed access to settings throughout the application

=============================================================================
WHY PYDANTIC-SETTINGS?
=============================================================================

Pydantic is a Python library for data validation using type hints.
Pydantic-settings extends it for configuration management.

Benefits over plain environment variables:

1. TYPE SAFETY: If MCP_READ_ONLY should be boolean, it ensures it IS boolean
2. DEFAULT VALUES: Sensible defaults if environment variable not set
3. VALIDATION: Catches configuration errors at startup, not at runtime
4. DOCUMENTATION: Field descriptions explain what each setting does
5. IDE SUPPORT: Autocomplete and type checking in editors

Example without Pydantic:
    read_only = os.environ.get("MCP_READ_ONLY", "true").lower() == "true"
    # What if someone sets it to "yes"? Or "1"? Or "TRUE"?

Example with Pydantic:
    read_only: bool = Field(default=True)
    # Automatically handles "true", "True", "TRUE", "1", "yes", "on", etc.

=============================================================================
ARCHITECTURE: THREE CONFIGURATION CLASSES
=============================================================================

1. ArgocdInstance: Configuration for ONE ArgoCD server
   - URL, token, name, TLS settings
   - Used when connecting to multiple ArgoCD instances

2. SecuritySettings: Security-related settings (MCP_* prefix)
   - Read-only mode, destructive ops, rate limiting
   - Controls what operations the AI can perform

3. ServerSettings: Main configuration container
   - Primary ArgoCD instance from environment
   - Additional instances for multi-cluster
   - Log level, server name
   - Contains SecuritySettings as nested object

=============================================================================
ENVIRONMENT VARIABLE MAPPING
=============================================================================

Primary ArgoCD instance:
    ARGOCD_URL          -> Primary server URL
    ARGOCD_TOKEN        -> API authentication token
    ARGOCD_INSECURE     -> Skip TLS certificate verification

Security settings (MCP_ prefix):
    MCP_READ_ONLY           -> Block all write operations (default: true)
    MCP_DISABLE_DESTRUCTIVE -> Block delete/prune operations (default: true)
    MCP_SINGLE_CLUSTER      -> Restrict to default cluster only
    MCP_AUDIT_LOG           -> Path to audit log file
    MCP_MASK_SECRETS        -> Mask sensitive data in output (default: true)
    MCP_RATE_LIMIT_CALLS    -> Max API calls per window (default: 100)
    MCP_RATE_LIMIT_WINDOW   -> Rate limit window in seconds (default: 60)
"""

# =============================================================================
# IMPORTS
# =============================================================================
#
# Import explanations:
# - __future__.annotations: Enables modern type hint syntax (e.g., 'X | None')
#   in Python 3.9+ and improves performance by deferring type evaluation.
# - os: Read optional .env file path from environment variables.
# - Path: Cross-platform filesystem path handling (needed at runtime for Pydantic).
# - Annotated: Attach metadata to types for validation/documentation.
# - BaseModel: Pydantic base class for data models with automatic validation.
# - Field: Add metadata (description, defaults, constraints) to model fields.
# - SecretStr: Special type that hides sensitive values in logs/repr.
# - field_validator: Decorator to add custom validation logic to fields.
# - BaseSettings: Like BaseModel, but reads values from environment variables.
# - SettingsConfigDict: Type-safe configuration for settings behavior.
# =============================================================================

from __future__ import annotations

import os
from pathlib import Path  # noqa: TC003 - Required at runtime for Pydantic
from typing import Annotated

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# =============================================================================
# ARGOCD INSTANCE CONFIGURATION
# =============================================================================


class ArgocdInstance(BaseModel):
    """
    Configuration for a single ArgoCD instance.

    WHY A SEPARATE CLASS?
    ---------------------
    This server supports connecting to MULTIPLE ArgoCD instances simultaneously.
    For example, you might have:
    - "primary" -> Production ArgoCD at https://argocd.prod.company.com
    - "staging" -> Staging ArgoCD at https://argocd.staging.company.com

    Each instance needs its own URL, token, and settings.

    WHY BaseModel NOT BaseSettings?
    -------------------------------
    This is a BaseModel (not BaseSettings) because instances are created
    programmatically from a list, not directly from environment variables.
    The primary instance IS read from env vars, but through ServerSettings.

    USAGE EXAMPLE:
    --------------
        instance = ArgocdInstance(
            url="https://argocd.example.com",
            token=SecretStr("my-api-token"),
            name="production",
            insecure=False
        )
    """

    # model_config is Pydantic V2's way to configure model behavior.
    # "extra": "ignore" means if you pass unknown fields, they're silently dropped
    # instead of raising an error. This makes the API more forgiving.
    model_config = {"extra": "ignore"}

    # -------------------------------------------------------------------------
    # INSTANCE FIELDS
    # -------------------------------------------------------------------------

    url: str = Field(description="ArgoCD server URL")
    # The base URL of the ArgoCD server, e.g., "https://argocd.example.com"
    # This gets combined with API paths like "/api/v1/applications"

    token: SecretStr = Field(description="ArgoCD API token")
    # The authentication token for ArgoCD API access.
    # SecretStr ensures the token is never accidentally logged or printed.
    # When you print a SecretStr, you see "**********" instead of the value.
    # To get the actual value: token.get_secret_value()

    name: str = Field(default="default", description="Instance identifier")
    # Human-readable name for this instance, used in logs and tool parameters.
    # Defaults to "default" for simple single-instance setups.

    insecure: bool = Field(default=False, description="Skip TLS verification")
    # If True, don't verify TLS certificates. DANGEROUS in production!
    # Only use this for:
    # - Local development with self-signed certificates
    # - Clusters with custom CAs you can't configure
    # Default is False (secure) because security should be opt-out, not opt-in.

    # -------------------------------------------------------------------------
    # CUSTOM VALIDATORS
    # -------------------------------------------------------------------------

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """
        Ensure URL has proper scheme and no trailing slash.

        WHY THIS VALIDATION?
        --------------------
        1. ADDS HTTPS if missing: Users often forget to include the scheme
           "argocd.example.com" becomes "https://argocd.example.com"

        2. REMOVES trailing slash: API paths start with "/" so we'd get
           double slashes if the base URL ends with one
           "https://example.com/" + "/api/v1" = "https://example.com//api/v1" (bad)
           "https://example.com" + "/api/v1" = "https://example.com/api/v1" (good)

        HOW field_validator WORKS:
        --------------------------
        - @classmethod because validators are called before instance exists
        - 'v' is the raw value passed by the user
        - Returns the validated/transformed value
        - Raising ValueError here would cause Pydantic ValidationError
        """
        # Check if URL starts with http:// or https://
        if not v.startswith(("http://", "https://")):
            # Default to secure HTTPS
            v = f"https://{v}"
        # Remove any trailing slashes
        return v.rstrip("/")


# =============================================================================
# SECURITY SETTINGS
# =============================================================================


class SecuritySettings(BaseSettings):
    """
    Security-related configuration.

    WHY SEPARATE SECURITY SETTINGS?
    -------------------------------
    Security settings deserve special attention:
    1. They have security-focused defaults (read-only=True)
    2. They use a different env prefix (MCP_ not ARGOCD_)
    3. They're reused by SafetyGuard for runtime checks

    DEFENSE IN DEPTH:
    -----------------
    This server implements "defense in depth" - multiple layers of protection:

    Layer 1: MCP_READ_ONLY=true (default)
        - Blocks ALL write operations
        - AI can only read/view data

    Layer 2: MCP_DISABLE_DESTRUCTIVE=true (default)
        - Even if writes are enabled, blocks delete/prune
        - Prevents permanent data loss

    Layer 3: Rate limiting (MCP_RATE_LIMIT_*)
        - Prevents runaway AI loops from overwhelming ArgoCD
        - Limits API calls per time window

    Layer 4: Confirmation patterns (in SafetyGuard)
        - Destructive operations require explicit confirmation
        - Must set confirm=true AND confirm_name matching target
    """

    # SettingsConfigDict configures how BaseSettings reads environment variables
    model_config = SettingsConfigDict(env_prefix="MCP_")
    # env_prefix="MCP_" means:
    # - Field "read_only" reads from "MCP_READ_ONLY" environment variable
    # - Field "disable_destructive" reads from "MCP_DISABLE_DESTRUCTIVE"
    # This namespacing prevents conflicts with other tools' env vars

    # -------------------------------------------------------------------------
    # PERMISSION CONTROLS
    # -------------------------------------------------------------------------

    read_only: bool = Field(
        default=True,  # SAFE DEFAULT: Start in read-only mode
        description="Block all write operations when true",
    )
    # When True, any operation that modifies state is blocked:
    # - sync_application (even dry-run requires write permission)
    # - refresh_application
    # - delete_application
    #
    # To enable writes: MCP_READ_ONLY=false
    # SECURITY PRINCIPLE: Fail-safe defaults

    disable_destructive: bool = Field(
        default=True,  # SAFE DEFAULT: No destructive operations
        description="Block delete and prune operations when true",
    )
    # Even when read_only=false, this STILL blocks:
    # - delete_application
    # - sync_application with prune=true
    #
    # This is a second layer of protection:
    # You might want AI to sync apps but not delete them.
    # To enable: MCP_DISABLE_DESTRUCTIVE=false

    single_cluster: bool = Field(
        default=False,  # Multi-cluster by default
        description="Restrict operations to default cluster only",
    )
    # When True, blocks operations targeting clusters other than "in-cluster".
    # Useful when you want to limit AI to only the cluster ArgoCD is in,
    # preventing it from affecting remote clusters.

    # -------------------------------------------------------------------------
    # AUDIT AND OBSERVABILITY
    # -------------------------------------------------------------------------

    audit_log: Path | None = Field(
        default=None,
        description="Path to audit log file",
    )
    # If set, writes JSON audit logs to this file path.
    # Each line is a JSON object with: timestamp, action, target, result, details
    #
    # Example: MCP_AUDIT_LOG=/var/log/argocd-mcp-audit.json
    #
    # When None (default), audit logs go to stdout with structured logging.

    mask_secrets: bool = Field(
        default=True,  # SAFE DEFAULT: Don't expose secrets
        description="Mask sensitive values in output",
    )
    # When True, sensitive data is replaced with "***MASKED***" in responses.
    # This includes: passwords, tokens, API keys, secrets
    #
    # This prevents the AI from accidentally exposing secrets to users
    # or including them in conversation history.

    # -------------------------------------------------------------------------
    # RATE LIMITING
    # -------------------------------------------------------------------------

    rate_limit_calls: int = Field(
        default=100,
        description="Maximum API calls per minute",
    )
    # Maximum number of ArgoCD API calls allowed in the rate limit window.
    # If exceeded, operations return "Rate limit exceeded" error.
    #
    # WHY RATE LIMITING?
    # - Protects ArgoCD server from being overwhelmed
    # - Prevents infinite loops where AI keeps retrying failed operations
    # - Ensures fair resource sharing if multiple clients use same ArgoCD

    rate_limit_window: int = Field(
        default=60,
        description="Rate limit window in seconds",
    )
    # The time window for rate limiting.
    # Default: 100 calls per 60 seconds = ~1.67 calls/second average
    #
    # After the window expires, the counter resets.


# =============================================================================
# MAIN SERVER SETTINGS
# =============================================================================


class ServerSettings(BaseSettings):
    """
    Main server configuration.

    This is the top-level configuration container that:
    1. Reads the primary ArgoCD instance from environment variables
    2. Supports additional instances for multi-cluster setups
    3. Contains nested SecuritySettings
    4. Configures logging and server metadata

    USAGE:
    ------
        settings = load_settings()  # Reads from environment
        print(settings.argocd_url)  # Primary ArgoCD URL
        print(settings.security.read_only)  # Security setting
    """

    model_config = SettingsConfigDict(
        env_prefix="ARGOCD_MCP_",
        # Most settings read from ARGOCD_MCP_* environment variables
        # Exception: argocd_url uses validation_alias for ARGOCD_URL
        env_nested_delimiter="__",
        # Allows setting nested fields via environment variables.
        # Use double underscore to access nested settings like security.read_only
        extra="ignore",
        # Unknown fields are silently ignored, not errors
        populate_by_name=True,
        # Allows using field name OR alias when creating instances
        # This enables both ARGOCD_URL and argocd_url to work
    )

    # -------------------------------------------------------------------------
    # PRIMARY ARGOCD INSTANCE (from environment)
    # -------------------------------------------------------------------------

    argocd_url: str = Field(
        default="",  # Empty string = not configured
        validation_alias="ARGOCD_URL",
        # validation_alias allows this field to read from ARGOCD_URL
        # instead of the default ARGOCD_MCP_ARGOCD_URL
        description="Primary ArgoCD server URL",
    )

    argocd_token: SecretStr = Field(
        default=SecretStr(""),  # Empty SecretStr = not configured
        validation_alias="ARGOCD_TOKEN",
        description="Primary ArgoCD API token",
    )
    # HOW TO GET AN ARGOCD TOKEN:
    # 1. Via ArgoCD CLI:
    #    argocd account generate-token --account <account-name>
    #
    # 2. Via Kubernetes secret (for admin):
    #    kubectl -n argocd get secret argocd-initial-admin-secret \
    #      -o jsonpath="{.data.password}" | base64 -d

    argocd_insecure: bool = Field(
        default=False,
        validation_alias="ARGOCD_INSECURE",
        description="Skip TLS verification for primary instance",
    )

    # -------------------------------------------------------------------------
    # MULTI-CLUSTER SUPPORT
    # -------------------------------------------------------------------------

    additional_instances: list[ArgocdInstance] = Field(
        default_factory=list,
        # default_factory=list means each Settings instance gets its own
        # empty list, not a shared mutable default (a common Python gotcha)
        description="Additional ArgoCD instances for multi-cluster support",
    )
    # Additional ArgoCD instances can be configured via JSON in environment
    # using the ARGOCD_MCP_ADDITIONAL_INSTANCES variable with a JSON array.
    # Or configure programmatically when creating settings in Python.

    # -------------------------------------------------------------------------
    # SERVER METADATA
    # -------------------------------------------------------------------------

    server_name: str = Field(
        default="argocd-mcp",
        description="MCP server name",
    )
    # Name reported in MCP protocol. Clients see this as the server identifier.

    server_version: str = Field(
        default="0.1.0",
        description="MCP server version",
    )
    # Version reported in MCP protocol.

    log_level: Annotated[str, Field(pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")] = Field(
        default="INFO",
        description="Logging level",
    )
    # Log level for the server. Uses standard Python logging levels.
    # The pattern validation ensures only valid levels are accepted.
    #
    # Annotated[str, Field(pattern=...)] combines:
    # - str: The base type
    # - Field(pattern=...): Regex validation
    #
    # DEBUG: Very verbose, includes HTTP request/response details
    # INFO: Normal operation, startup/shutdown, successful operations
    # WARNING: Unexpected situations that aren't errors
    # ERROR: Operation failures, exceptions
    # CRITICAL: Server cannot continue

    # -------------------------------------------------------------------------
    # NESTED SECURITY SETTINGS
    # -------------------------------------------------------------------------

    security: SecuritySettings = Field(default_factory=SecuritySettings)
    # Nested security settings. default_factory creates a new SecuritySettings
    # instance with its own defaults, which will read from MCP_* env vars.

    # -------------------------------------------------------------------------
    # COMPUTED PROPERTIES
    # -------------------------------------------------------------------------

    @property
    def primary_instance(self) -> ArgocdInstance | None:
        """
        Get primary ArgoCD instance from environment variables.

        WHAT IS A @property?
        --------------------
        Properties look like attributes but compute their value dynamically.

            settings.primary_instance  # Looks like attribute access
            # But actually calls this method

        This is useful when:
        1. The value depends on other fields
        2. You want validation or transformation logic
        3. The value should be computed fresh each time

        Returns None if ARGOCD_URL is not set, indicating no primary
        instance is configured.
        """
        if not self.argocd_url:
            return None
        return ArgocdInstance(
            url=self.argocd_url,
            token=self.argocd_token,
            name="primary",  # Convention: primary instance is named "primary"
            insecure=self.argocd_insecure,
        )

    @property
    def all_instances(self) -> list[ArgocdInstance]:
        """
        Get all configured ArgoCD instances.

        Returns a list combining:
        1. Primary instance (if configured)
        2. All additional_instances

        This provides a unified interface for code that needs to work
        with all instances, regardless of how they were configured.
        """
        instances = []
        if self.primary_instance:
            instances.append(self.primary_instance)
        instances.extend(self.additional_instances)
        return instances

    def get_instance(self, name: str = "primary") -> ArgocdInstance | None:
        """
        Get ArgoCD instance by name.

        This method enables multi-cluster operations by allowing tools
        to specify which ArgoCD instance they want to use.

        Example:
            client = get_client("staging")  # Get staging instance's client

        Args:
            name: Instance name to find. Defaults to "primary".

        Returns:
            ArgocdInstance if found, None otherwise.
        """
        for instance in self.all_instances:
            if instance.name == name:
                return instance
        return None


# =============================================================================
# SETTINGS LOADER
# =============================================================================


def load_settings() -> ServerSettings:
    """
    Load settings from environment with validation.

    This is the main entry point for loading configuration. It:
    1. Creates a ServerSettings instance
    2. Which automatically reads from environment variables
    3. Validates all values according to field definitions
    4. Raises ValidationError if anything is invalid

    WHY A SEPARATE FUNCTION?
    ------------------------
    - Encapsulates the loading logic
    - Makes testing easier (can mock this function)
    - Supports optional .env file loading
    - Provides a clear "entry point" for configuration

    OPTIONAL .env FILE:
    -------------------
    If ARGOCD_MCP_ENV_FILE environment variable is set, it reads
    additional variables from that file. Useful for local development.

    Example .env file:
        ARGOCD_URL=https://localhost:8443
        ARGOCD_TOKEN=my-dev-token
        ARGOCD_INSECURE=true
        MCP_READ_ONLY=false

    Returns:
        Fully validated ServerSettings instance.

    Raises:
        pydantic.ValidationError: If configuration is invalid.
    """
    return ServerSettings(
        # _env_file is a special Pydantic-settings parameter
        # It loads additional environment variables from a file
        _env_file=os.environ.get("ARGOCD_MCP_ENV_FILE"),
    )
