"""Pytest plugin for declaring and batch-fetching test secrets.

Exposes a ``secrets`` marker and a session-scoped ``test_secrets`` fixture
that resolves the union of ``TestSecret`` values declared across the
collected tests in a single AWS call.

To opt a test suite in, re-export the hooks and fixture from that suite's
conftest.py using the PEP 484 explicit re-export form (``name as name``)
so linters recognize the imports as intentional re-exports:

    from tests.utils.pytest_secrets import (
        pytest_collection_modifyitems as pytest_collection_modifyitems,
    )
    from tests.utils.pytest_secrets import pytest_configure as pytest_configure
    from tests.utils.pytest_secrets import test_secrets as test_secrets

Then in tests:

    @pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
    def test_something(test_secrets: dict[TestSecret, str]) -> None:
        ...
"""

import pytest

from tests.utils.aws_secrets import get_secrets
from tests.utils.secret_names import TestSecret

_NEEDED_SECRETS_KEY = "_onyx_test_secrets_needed"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "secrets(*secrets: TestSecret): declare which test secrets this test needs. "
        "All declared secrets across collected tests are batch-fetched once per "
        "session by the `test_secrets` fixture.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Collect the union of `@pytest.mark.secrets(...)` args across all items."""
    needed: set[TestSecret] = set()
    for item in items:
        for marker in item.iter_markers(name="secrets"):
            for arg in marker.args:
                if not isinstance(arg, TestSecret):
                    raise TypeError(
                        f"@pytest.mark.secrets expects TestSecret members, "
                        f"got {arg!r} on {item.nodeid}"
                    )
                needed.add(arg)
    setattr(config, _NEEDED_SECRETS_KEY, needed)


@pytest.fixture(scope="session")
def test_secrets(request: pytest.FixtureRequest) -> dict[TestSecret, str]:
    """Resolve only the secrets declared by collected tests, in one batch."""
    needed: set[TestSecret] = getattr(request.config, _NEEDED_SECRETS_KEY, set())
    return get_secrets(sorted(needed, key=lambda s: s.value))
