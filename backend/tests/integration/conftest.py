import os
from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.db.engine import get_session_context_manager
from onyx.db.search_settings import get_current_search_settings
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


# Load environment variables at the module level
load_env_vars()


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    with get_session_context_manager() as session:
        yield session


@pytest.fixture
def vespa_client(db_session: Session) -> vespa_fixture:
    search_settings = get_current_search_settings(db_session)
    return vespa_fixture(index_name=search_settings.index_name)


@pytest.fixture
def reset() -> None:
    reset_all()


@pytest.fixture
def new_admin_user(reset: None) -> DATestUser | None:
    try:
        return UserManager.create(name="admin_user")
    except Exception:
        return None


@pytest.fixture
def reset_multitenant() -> None:
    reset_all_multitenant()
