"""Fixtures for networking checks against an existing Kubernetes deployment."""

import os

import pytest

from tests.common.craft.deployment_fixtures import (
    _module_reset_and_seed as _module_reset_and_seed,
)
from tests.common.craft.deployment_fixtures import (
    _reap_module_sandboxes as _reap_module_sandboxes,
)
from tests.common.craft.deployment_fixtures import (
    _run_migrations as _run_migrations,
)
from tests.common.craft.deployment_fixtures import (
    _start_celery_workers as _start_celery_workers,
)
from tests.common.craft.deployment_fixtures import (
    _test_client as _test_client,
)
from tests.common.craft.deployment_fixtures import (
    deployed_frontend as deployed_frontend,
)
from tests.common.craft.deployment_fixtures import (
    initialize_db as initialize_db,
)
from tests.common.craft.deployment_fixtures import (
    seed_dev_license_for_session as seed_dev_license_for_session,
)


@pytest.fixture(scope="session", autouse=True)
def _kubernetes_context(deployed_frontend: str) -> None:
    if deployed_frontend and not os.environ.get("SANDBOX_TEST_KUBE_CONTEXT"):
        pytest.fail("SANDBOX_TEST_KUBE_CONTEXT is required")


@pytest.fixture(scope="module", autouse=True)
def _reap_module_pods() -> None:
    pass


@pytest.fixture(scope="module", autouse=True)
def _sandbox_push_key() -> None:
    pass
