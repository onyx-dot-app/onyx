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
Docker daemon when a Docker-backend test opts into it. Onyx application
processes (API server, Celery workers) are **not** running. Tests import and
call functions directly and can mock selectively.

Conditional external dependencies such as OpenAI are gated by `skipif` at the
top of the test file so the suite stays runnable in environments that lack the
relevant env var or credential.

Use when you need a real database or real API calls but want control over setup.

```bash
python -m dotenv -f .vscode/.env run -- pytest backend/tests/external_dependency_unit
```

### Integration Tests (`tests/integration/`)

Full Onyx deployment running. No mocking. Prefer this over other test types when
possible. Most integration tests exercise the product through HTTP API manager
helpers under `tests/integration/common_utils`.

Craft Kubernetes coverage lives in `tests/integration/tests/craft/k8s/` and
runs in the dedicated Helm-installed kind job
([pr-craft-k8s-tests.yml](../../.github/workflows/pr-craft-k8s-tests.yml)).
That suite is a full deployed Craft integration lane: the chart provides
Postgres, Redis, MinIO, OpenSearch, api_server, web_server, Celery workers,
sandbox-proxy, and real sandbox pods in kind. API-facing setup goes through the
deployed api_server; direct manager calls are reserved for low-level Kubernetes
contracts that do not have an HTTP API. Direct task/stub checks belong in
`tests/external_dependency_unit/craft/`.

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
