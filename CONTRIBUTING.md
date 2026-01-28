# Contributing to ArgoCD MCP Server

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) (recommended package manager)
- Docker (for container builds and testing)
- Kind (for local Kubernetes testing)
- An ArgoCD instance for integration testing

### Getting Started

```bash
# Clone the repository
git clone https://github.com/peopleforrester/mcp-k8s-observability-argocd-server
cd mcp-k8s-observability-argocd-server

# Install dependencies including dev tools
uv sync --dev

# Install pre-commit hooks
uv run pre-commit install
```

## Development Workflow

### Running Tests

```bash
# Run all tests
uv run pytest

# Run unit tests only
uv run pytest -m unit

# Run integration tests (requires ArgoCD)
uv run pytest -m integration

# Run with coverage
uv run pytest --cov=src/argocd_mcp --cov-report=html
```

### Code Quality

```bash
# Format and lint
uv run ruff check --fix src tests
uv run ruff format src tests

# Type checking
uv run mypy src
```

### Local Testing with Kind

```bash
# Create test cluster
kind create cluster --name argocd-mcp-test

# Install ArgoCD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for ArgoCD to be ready
kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd

# Get credentials
ARGOCD_PASSWORD=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)

# Port forward (in background)
kubectl port-forward svc/argocd-server -n argocd 8080:443 &

# Set environment for testing
export ARGOCD_URL=https://localhost:8080
export ARGOCD_TOKEN=$ARGOCD_PASSWORD
export ARGOCD_INSECURE=true
export MCP_READ_ONLY=false

# Run tests
uv run pytest -m integration
```

## Code Guidelines

### Style

- Follow PEP 8 with 100-character line limit
- Use type hints for all function signatures
- Write docstrings in Google style
- Keep functions small and focused

### File Headers

All Python files should start with a two-line ABOUTME comment:

```python
# ABOUTME: Brief description of what this file does
# ABOUTME: Additional context about its purpose
```

### Tool Implementation Guidelines

When adding new tools:

1. **Categorize by tier**: Read (Tier 1), Write (Tier 2), Destructive (Tier 3)
2. **Use dry-run defaults**: Write operations should default to preview mode
3. **Implement confirmation patterns**: Destructive operations require explicit confirmation
4. **Write agent-friendly messages**: Error messages should be actionable
5. **Add audit logging**: All operations should be logged

Example tool structure:

```python
class MyToolParams(BaseModel):
    """Parameters for my_tool."""
    name: str = Field(description="Resource name")
    dry_run: bool = Field(default=True, description="Preview mode")

@mcp.tool()
async def my_tool(params: MyToolParams, ctx: Context) -> str:
    """Tool description for LLM consumption.

    Detailed explanation of what this tool does and when to use it.
    """
    # 1. Check safety guards
    blocked = get_safety_guard().check_write_operation("my_tool")
    if blocked:
        return blocked.format_message()

    # 2. Execute operation
    # 3. Log result
    # 4. Return agent-friendly response
```

### Testing Guidelines

- Write tests before implementation (TDD)
- Cover happy path, error cases, and edge cases
- Use fixtures for common test data
- Mock external dependencies in unit tests

```python
@pytest.mark.unit
async def test_my_tool_dry_run():
    """Test my_tool in dry-run mode."""
    # Arrange
    # Act
    # Assert

@pytest.mark.integration
async def test_my_tool_live():
    """Test my_tool against real ArgoCD."""
    # Requires ARGOCD_URL and ARGOCD_TOKEN
```

## Pull Request Process

1. **Create a branch**: `git checkout -b feature/my-feature`
2. **Make changes**: Follow the code guidelines
3. **Write tests**: Ensure adequate coverage
4. **Run checks**: `uv run pytest && uv run ruff check && uv run mypy src`
5. **Commit**: Use clear, descriptive commit messages
6. **Push**: `git push origin feature/my-feature`
7. **Open PR**: Fill out the PR template

### Commit Messages

- Use imperative mood: "Add feature" not "Added feature"
- Keep first line under 72 characters
- Reference issues: "Fix #123: Resolve sync timeout"

### PR Requirements

- All tests pass
- Code coverage maintained or improved
- Linting passes
- Type checking passes
- Documentation updated if needed

## Security

- Never commit secrets or credentials
- Use environment variables for configuration
- Report security issues privately to maintainers
- Follow the principle of least privilege

## Questions?

Open an issue for questions or discussions about contributing.
