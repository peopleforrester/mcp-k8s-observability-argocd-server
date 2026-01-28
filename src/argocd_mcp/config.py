# ABOUTME: Configuration management for ArgoCD MCP Server
# ABOUTME: Handles environment variables, security modes, and multi-instance settings

"""Configuration management using pydantic-settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ArgocdInstance(BaseModel):
    """Configuration for a single ArgoCD instance.

    Note: This is a BaseModel (not BaseSettings) because instances are
    created programmatically, not from environment variables directly.
    """

    model_config = {"extra": "ignore"}

    url: str = Field(description="ArgoCD server URL")
    token: SecretStr = Field(description="ArgoCD API token")
    name: str = Field(default="default", description="Instance identifier")
    insecure: bool = Field(default=False, description="Skip TLS verification")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Ensure URL has proper scheme and no trailing slash."""
        if not v.startswith(("http://", "https://")):
            v = f"https://{v}"
        return v.rstrip("/")


class SecuritySettings(BaseSettings):
    """Security-related configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_")

    read_only: bool = Field(
        default=True,
        description="Block all write operations when true",
    )
    disable_destructive: bool = Field(
        default=True,
        description="Block delete and prune operations when true",
    )
    single_cluster: bool = Field(
        default=False,
        description="Restrict operations to default cluster only",
    )
    audit_log: Path | None = Field(
        default=None,
        description="Path to audit log file",
    )
    mask_secrets: bool = Field(
        default=True,
        description="Mask sensitive values in output",
    )
    rate_limit_calls: int = Field(
        default=100,
        description="Maximum API calls per minute",
    )
    rate_limit_window: int = Field(
        default=60,
        description="Rate limit window in seconds",
    )


class ServerSettings(BaseSettings):
    """Main server configuration."""

    model_config = SettingsConfigDict(
        env_prefix="ARGOCD_MCP_",
        env_nested_delimiter="__",
        extra="ignore",
        populate_by_name=True,
    )

    # Primary instance configuration (from environment)
    argocd_url: str = Field(
        default="",
        validation_alias="ARGOCD_URL",
        description="Primary ArgoCD server URL",
    )
    argocd_token: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="ARGOCD_TOKEN",
        description="Primary ArgoCD API token",
    )
    argocd_insecure: bool = Field(
        default=False,
        validation_alias="ARGOCD_INSECURE",
        description="Skip TLS verification for primary instance",
    )

    # Additional instances (JSON array in environment)
    additional_instances: list[ArgocdInstance] = Field(
        default_factory=list,
        description="Additional ArgoCD instances for multi-cluster support",
    )

    # Server settings
    server_name: str = Field(
        default="argocd-mcp",
        description="MCP server name",
    )
    server_version: str = Field(
        default="0.1.0",
        description="MCP server version",
    )
    log_level: Annotated[str, Field(pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")] = Field(
        default="INFO",
        description="Logging level",
    )

    # Security settings
    security: SecuritySettings = Field(default_factory=SecuritySettings)

    @property
    def primary_instance(self) -> ArgocdInstance | None:
        """Get primary ArgoCD instance from environment variables."""
        if not self.argocd_url:
            return None
        return ArgocdInstance(
            url=self.argocd_url,
            token=self.argocd_token,
            name="primary",
            insecure=self.argocd_insecure,
        )

    @property
    def all_instances(self) -> list[ArgocdInstance]:
        """Get all configured ArgoCD instances."""
        instances = []
        if self.primary_instance:
            instances.append(self.primary_instance)
        instances.extend(self.additional_instances)
        return instances

    def get_instance(self, name: str = "primary") -> ArgocdInstance | None:
        """Get ArgoCD instance by name."""
        for instance in self.all_instances:
            if instance.name == name:
                return instance
        return None


def load_settings() -> ServerSettings:
    """Load settings from environment with validation."""
    return ServerSettings(
        _env_file=os.environ.get("ARGOCD_MCP_ENV_FILE"),
    )
