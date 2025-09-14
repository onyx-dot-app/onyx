import os
from collections.abc import Callable

import pytest

from onyx.auth.schemas import UserRole
from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.search_settings import get_current_search_settings
from tests.integration.common_utils.constants import ADMIN_USER_NAME
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import build_email
from tests.integration.common_utils.managers.user import DEFAULT_PASSWORD
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.reset import reset_all_multitenant
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import SimpleTestDocument
from tests.integration.common_utils.vespa import vespa_fixture

BASIC_USER_NAME = "basic_user"

DocumentBuilderType = Callable[[list[str]], list[SimpleTestDocument]]


@pytest.fixture(scope="session", autouse=True)
def initialize_db() -> None:
    # Make sure that the db engine is initialized before any tests are run
    SqlEngine.init_engine(
        pool_size=10,
        max_overflow=5,
    )


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


@pytest.fixture
def vespa_client() -> vespa_fixture:
    with get_session_with_current_tenant() as db_session:
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
        user = UserManager.create(name=ADMIN_USER_NAME)

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
def basic_user(
    # make sure the admin user exists first to ensure this new user
    # gets the BASIC role
    admin_user: DATestUser,
) -> DATestUser:
    try:
        user = UserManager.create(name=BASIC_USER_NAME)

        # Validate that the user has the BASIC role
        if user.role != UserRole.BASIC:
            raise RuntimeError(
                f"Created user {BASIC_USER_NAME} does not have BASIC role"
            )

        return user
    except Exception as e:
        print(f"Failed to create basic user, trying to login as existing user: {e}")

        # Try to login as existing basic user
        user = UserManager.login_as_user(
            DATestUser(
                id="",
                email=build_email(BASIC_USER_NAME),
                password=DEFAULT_PASSWORD,
                headers=GENERAL_HEADERS,
                role=UserRole.BASIC,
                is_active=True,
            )
        )

        # Validate that the logged-in user has the BASIC role
        if not UserManager.is_role(user, UserRole.BASIC):
            raise RuntimeError(f"User {BASIC_USER_NAME} does not have BASIC role")

        return user


@pytest.fixture(scope="session")
def reset_multitenant() -> None:
    """Initialize multi-tenant state once per test session.

    Intentionally avoid per-test resets to speed up the multitenant suite.
    The underlying reset function honors SKIP_RESET to allow CI to disable
    heavy resets entirely.
    """
    reset_all_multitenant()


@pytest.fixture
def llm_provider(admin_user: DATestUser | None) -> DATestLLMProvider:
    return LLMProviderManager.create(user_performing_action=admin_user)


@pytest.fixture
def document_builder(admin_user: DATestUser) -> DocumentBuilderType:
    api_key: DATestAPIKey = APIKeyManager.create(
        user_performing_action=admin_user,
    )

    # create connector
    cc_pair_1 = CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )

    def _document_builder(contents: list[str]) -> list[SimpleTestDocument]:
        # seed documents
        docs: list[SimpleTestDocument] = [
            DocumentManager.seed_doc_with_content(
                cc_pair=cc_pair_1,
                content=content,
                api_key=api_key,
            )
            for content in contents
        ]

        return docs

    return _document_builder


def pytest_runtest_logstart(nodeid: str, location: tuple[str, int | None, str]) -> None:
    print(f"\nTest start: {nodeid}")


def pytest_runtest_logfinish(
    nodeid: str, location: tuple[str, int | None, str]
) -> None:
    print(f"\nTest end: {nodeid}")
