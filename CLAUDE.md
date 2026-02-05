# ArgoCD MCP Server - Development Instructions

## Build/Run/Test Commands

- **Install dependencies**: `uv sync --dev`
- **Run tests**: `uv run pytest` (excludes integration tests by default)
- **Run all tests**: `uv run pytest -m ""` (includes integration tests)
- **Run integration tests only**: `uv run pytest -m integration`
- **Lint code**: `uv run ruff check src tests`
- **Format code**: `uv run ruff format src tests`
- **Type check**: `uv run mypy src`
- **Run server**: `uv run argocd-mcp`
- **Build Docker**: `docker build -t argocd-mcp-server .`

## Code Style Guidelines

- **Imports**: Standard library first, then third-party, then local modules (grouped and alphabetized)
- **Formatting**: 4-space indentation, 100 character line length
- **Docstrings**: Google-style docstrings with Args, Returns, Raises sections
- **Naming**: snake_case for functions/variables, PascalCase for classes, UPPER_CASE for constants
- **File headers**: All Python files start with two-line ABOUTME comment
- **Type hints**: Required for all function signatures
- **Error handling**: Use specific exceptions, return agent-friendly error messages

## Tool Implementation Guidelines

### Progressive Disclosure Tiers

1. **Tier 1 (Read)**: Always available, no special flags needed
2. **Tier 2 (Write)**: Require `MCP_READ_ONLY=false`
3. **Tier 3 (Destructive)**: Require confirmation parameters

### Safety Patterns

- Dry-run by default for all write operations
- Explicit confirmation for destructive operations
- Audit logging for all operations
- Rate limiting to prevent abuse

### Tool Response Format

- Error messages must be actionable for LLM agents
- Include specific resource names and states
- Provide next-step suggestions when appropriate

## Testing Requirements

- Unit tests for all tools and utilities
- Integration tests against real ArgoCD (via Kind cluster)
- Coverage target: 80% minimum
- Mark tests appropriately: `@pytest.mark.unit`, `@pytest.mark.integration`

## Security Notes

- Never log or echo API tokens
- Mask sensitive values in responses
- Default to read-only mode
- Use environment variables for credentials only
