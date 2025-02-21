import os

import pytest

from onyx.auth.schemas import UserRole
from onyx.db.engine import get_session_context_manager
from onyx.db.search_settings import get_current_search_settings
from tests.integration.common_utils.constants import ADMIN_USER_NAME
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


# Load environment variables at the module level
load_env_vars()


"""NOTE: for some reason using this seems to lead to misc
`sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) server closed the connection unexpectedly`
errors.

Commenting out till we can get to the bottom of it. For now, just using
instantiate the session directly within the test.
"""
# @pytest.fixture
# def db_session() -> Generator[Session, None, None]:
#     with get_session_context_manager() as session:
#         yield session


@pytest.fixture
def vespa_client() -> vespa_fixture:
    with get_session_context_manager() as db_session:
        search_settings = get_current_search_settings(db_session)
        return vespa_fixture(index_name=search_settings.index_name)


@pytest.fixture
def reset() -> None:
    reset_all()


@pytest.fixture
def new_admin_user(reset: None) -> DATestUser | None:
    try:
        return UserManager.create(name=ADMIN_USER_NAME)
    except Exception:
        return None


@pytest.fixture
def admin_user() -> DATestUser:
    try:
        user = UserManager.create(name=ADMIN_USER_NAME, is_first_user=True)

        # if there are other users for some reason, reset and try again
        if not UserManager.is_role(user, UserRole.ADMIN):
            print("Trying to reset")
            reset_all()
            user = UserManager.create(name=ADMIN_USER_NAME)
        return user
    except Exception as e:
        print(f"Failed to create admin user: {e}")

    try:
        user = UserManager.login_as_user(
            DATestUser(
                id="",
                email=build_email("admin_user"),
                password=DEFAULT_PASSWORD,
                headers=GENERAL_HEADERS,
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        if not UserManager.is_role(user, UserRole.ADMIN):
            reset_all()
            user = UserManager.create(name=ADMIN_USER_NAME)
            return user

        return user
    except Exception as e:
        print(f"Failed to create or login as admin user: {e}")

    raise RuntimeError("Failed to create or login as admin user")


@pytest.fixture
def reset_multitenant() -> None:
    reset_all_multitenant()
