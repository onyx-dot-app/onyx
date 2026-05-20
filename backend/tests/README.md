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

Real Postgres, Redis, MinIO, and Vespa available. Real OpenAI key when set. Real
Kubernetes cluster when configured (`SANDBOX_BACKEND=kubernetes`) — gated by
file-level `pytest.mark.skipif`. Onyx application processes (API server, Celery
workers) are **not** running. Tests import and call functions directly and can
mock selectively.

Conditional external dependencies (K8s, OpenAI) are gated by `skipif` at the
top of the test file so the suite stays runnable in environments that lack
those dependencies. Tests that need them only execute when the relevant env
var or credential is present.

There is no separate K8s integration layer. K8s-requiring tests live in
`external_dependency_unit/` with a `skipif` gate. CI runs them in a dedicated
job ([pr-craft-k8s-tests.yml](../../.github/workflows/pr-craft-k8s-tests.yml)).

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

## Running Tests Repeatedly (`pytest-repeat`)

Use `pytest-repeat` to catch flaky tests by running them multiple times:

```bash
# Run a specific test 50 times
pytest --count=50 backend/tests/unit/path/to/test.py::test_name

# Stop on first failure with -x
pytest --count=50 -x backend/tests/unit/path/to/test.py::test_name

# Repeat an entire test file
pytest --count=10 backend/tests/unit/path/to/test_file.py
```

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
