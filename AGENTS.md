# ArgoCD MCP Server

MCP server providing ArgoCD management tools for LLM agents.

**Stack**: Python 3.12, uv, MCP SDK, ArgoCD API, pytest, ruff, mypy

## Commands

- `uv sync --dev` — Install dependencies
- `uv run pytest` — Run tests (excludes integration by default)
- `uv run pytest -m ""` — Run all tests including integration
- `uv run pytest -m integration` — Integration tests only
- `uv run ruff check src tests` / `uv run ruff format src tests` — Lint/format
- `uv run mypy src` — Type check
- `uv run argocd-mcp` — Run server
- `docker build -t argocd-mcp-server .` — Build Docker image

## Tool Implementation Guidelines

### Progressive Disclosure Tiers

1. **Tier 1 (Read)**: Always available, no special flags
2. **Tier 2 (Write)**: Require `MCP_READ_ONLY=false`
3. **Tier 3 (Destructive)**: Require confirmation parameters

### Safety Patterns

- Dry-run by default for all write operations
- Explicit confirmation for destructive operations
- Audit logging for all operations
- Rate limiting to prevent abuse
- Error messages must be actionable for LLM agents with next-step suggestions

## Testing

- Integration tests run against real ArgoCD via Kind cluster
- Coverage target: 80% minimum
- Mark tests: `@pytest.mark.unit`, `@pytest.mark.integration`

## Security Notes

- Never log or echo API tokens
- Mask sensitive values in responses
- Default to read-only mode
- Environment variables for credentials only
