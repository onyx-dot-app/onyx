# Run Tests

Run the appropriate test suite for the Onyx project with proper environment configuration.

## Steps:
1. Ask the user which type of tests they want to run:
   - **unit**: Unit tests that don't require external services
   - **external-unit**: Tests that require external dependencies (Postgres, Redis, Vespa, etc.)
   - **integration**: Full integration tests against a real Onyx deployment
   - **playwright**: E2E tests including the web frontend
   - **all**: Run all test suites

2. Based on the selection, run the appropriate test command:

### Unit Tests
```bash
python -m dotenv -f .vscode/.env run -- pytest -xv backend/tests/unit
```

### External Dependency Unit Tests
```bash
python -m dotenv -f .vscode/.env run -- pytest -xv backend/tests/external_dependency_unit
```

### Integration Tests
```bash
python -m dotenv -f .vscode/.env run -- pytest -xv backend/tests/integration
```

### Playwright Tests
```bash
cd web && npx playwright test
```

### Specific Test File or Directory
If the user provides a specific path, run:
```bash
python -m dotenv -f .vscode/.env run -- pytest -xv <path>
```

## Important Notes:
- Always use the `.vscode/.env` file for environment variables
- The `-xv` flags provide verbose output and stop on first failure
- Check for OpenAI key in `.env` if tests fail with API errors
- Verify all Onyx services are running for integration/playwright tests
- Check `backend/log/` directory for service logs if tests fail
- Tests are parallelized at directory level for integration tests

## Common Issues:
- Missing dependencies: Run `source backend/.venv/bin/activate` first
- Services not running: Check docker containers with `docker ps`
- Database connection errors: Verify Postgres is accessible
