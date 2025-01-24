import os
from collections.abc import Generator

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.engine import get_session_with_tenant
from onyx.db.search_settings import get_current_search_settings
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.managers.user import build_email
from tests.integration.common_utils.managers.user import DEFAULT_PASSWORD
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.reset import reset_all_multitenant
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.vespa import vespa_fixture


def load_env_vars(env_file: str = ".env") -> None:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(current_dir, env_file)
    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    os.environ[key] = value.strip()
        print("Successfully loaded environment variables")
    except FileNotFoundError:
        print(f"File {env_file} not found")


# Load environment variables as a session-scoped fixture to ensure consistent state
@pytest.fixture(scope="session", autouse=True)
def load_test_env() -> None:
    """Load environment variables at session start.
    Session scope ensures variables are loaded once per test process."""
    load_env_vars()


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    # Get worker ID from pytest-xdist, default to '0' for single-process runs
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "0")
    schema_name = f"test_schema_{worker_id}"

    # Set the schema name as the tenant ID for this session
    CURRENT_TENANT_ID_CONTEXTVAR.set(schema_name)

    # Use existing tenant-aware session management
    with get_session_with_tenant(tenant_id=schema_name) as session:
        try:
            yield session
        finally:
            # Clean up schema after tests
            session.execute(text('DROP SCHEMA IF EXISTS "%s" CASCADE' % schema_name))
            session.commit()


@pytest.fixture
def vespa_client(db_session: Session) -> vespa_fixture:
    # Get worker ID for parallel execution
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "0")

    # Get base index name from search settings
    search_settings = get_current_search_settings(db_session)

    # Create worker-specific index name
    index_name = f"{search_settings.index_name}_{worker_id}"

    return vespa_fixture(index_name=index_name)


@pytest.fixture(scope="session")
def reset() -> None:
    """Reset database and search index once per test session.

    Each worker gets its own schema and index, so we only need to reset once per worker.
    """
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "0")
    schema_name = f"test_schema_{worker_id}"
    reset_all(schema_name=schema_name)


@pytest.fixture
def new_admin_user(reset: None) -> DATestUser | None:
    try:
        return UserManager.create(name="admin_user")
    except Exception:
        return None


@pytest.fixture
def admin_user() -> DATestUser | None:
    try:
        return UserManager.create(name="admin_user")
    except Exception:
        pass

    try:
        return UserManager.login_as_user(
            DATestUser(
                id="",
                email=build_email("admin_user"),
                password=DEFAULT_PASSWORD,
                headers=GENERAL_HEADERS,
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
    except Exception:
        pass

    return None


@pytest.fixture(scope="session")
def reset_multitenant() -> None:
    """Reset multitenant database and search indices once per test session.

    Each worker gets its own schemas and indices, so we only need to reset once per worker.
    """
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "0")
    reset_all_multitenant(worker_id=worker_id)
