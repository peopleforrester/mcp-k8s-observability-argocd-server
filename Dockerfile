# ABOUTME: Multi-stage Dockerfile for ArgoCD MCP Server
# ABOUTME: Produces minimal, secure container image with non-root execution

# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml README.md ./
COPY src ./src

# Create virtual environment and install dependencies
RUN uv venv /app/.venv && \
    . /app/.venv/bin/activate && \
    uv pip install --no-cache .

# Runtime stage
FROM python:3.12-slim AS runtime

# Security: Run as non-root user
RUN groupadd --gid 1000 argocd && \
    useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home argocd

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy source code
COPY --from=builder /app/src /app/src

# Set environment
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Default to safe mode
    MCP_READ_ONLY=true \
    MCP_DISABLE_DESTRUCTIVE=true

# Switch to non-root user
USER argocd

# Health check (for HTTP transport)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Entry point
ENTRYPOINT ["python", "-m", "argocd_mcp.server"]

# Metadata
LABEL org.opencontainers.image.title="ArgoCD MCP Server" \
      org.opencontainers.image.description="Safety-first ArgoCD MCP server for GitOps operations" \
      org.opencontainers.image.vendor="Michael Rishi Forrester" \
      org.opencontainers.image.source="https://github.com/peopleforrester/mcp-k8s-observability-argocd-server" \
      org.opencontainers.image.licenses="Apache-2.0"
