# Backend Tests

## Test Types

There are four test categories, ordered by increasing scope:

### Unit Tests (`tests/unit/`)

No external services. Mock all I/O with `unittest.mock`. Use for complex, isolated
logic (e.g. citation processing, encryption).

```bash
pytest -xv backend/tests/unit
```

### External Dependency Unit Tests (`tests/external_dependency_unit/`)

External services (Postgres, Redis, Vespa, OpenAI, etc.) are running, but Onyx
application containers are not. Tests call functions directly and can mock selectively.

Use when you need a real database or real API calls but want control over setup.

```bash
python -m dotenv -f .vscode/.env run -- pytest backend/tests/external_dependency_unit
```

### Integration Tests (`tests/integration/`)

Full Onyx deployment running. No mocking. Prefer this over other test types when possible.

```bash
python -m dotenv -f .vscode/.env run -- pytest backend/tests/integration
```

### Playwright / E2E Tests (`web/tests/e2e/`)

Full stack including web server. Use for frontend-backend coordination.

```bash
npx playwright test <TEST_NAME>
```

## Shared Fixtures

Shared fixtures live in `backend/tests/conftest.py`. Test subdirectories can define
their own `conftest.py` for directory-scoped fixtures.

## Best Practices

### Use `enable_ee` fixture instead of inlining

Enables EE mode for a test, with proper teardown and cache clearing.

```python
# Whole file (in a test module, NOT in conftest.py)
pytestmark = pytest.mark.usefixtures("enable_ee")

# Whole directory — add an autouse wrapper to the directory's conftest.py
@pytest.fixture(autouse=True)
def _enable_ee_for_directory(enable_ee: None) -> None:  
    """Wraps the shared enable_ee fixture with autouse for this directory."""

# Single test
def test_something(enable_ee: None) -> None: ...
```

**Note:** `pytestmark` in a `conftest.py` does NOT apply markers to tests in that
directory — it only affects tests defined in the conftest itself (which is none).
Use the autouse fixture wrapper pattern shown above instead.

Do NOT inline `global_version.set_ee()` — always use the fixture.
