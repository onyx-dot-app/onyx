import os
import platform
import shutil
import subprocess
from collections.abc import Callable
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest

# Integration tests rely on this mode to enable mock_llm_response paths.
os.environ["INTEGRATION_TESTS_MODE"] = "true"

# Backend directory (`/workspace/backend`) — root for alembic / craft / etc.
BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
                    # Preserve explicitly pre-set vars (e.g. INTEGRATION_TESTS_MODE).
                    os.environ.setdefault(key, value.strip())
        print("Successfully loaded environment variables")
    except FileNotFoundError:
        print(f"File {env_file} not found")


# Env must be in place before any onyx.* / shared_configs imports below pull
# in module-level constants that read os.environ once.
load_env_vars()

from fastapi.testclient import TestClient  # noqa: E402

# Import `onyx.main` BEFORE calling fetch_versioned_implementation ourselves.
# onyx.main's module body (line 706) already calls fetch_versioned_implementation
# under set_is_ee_based_on_env_variable(). If our fixture is the first to invoke
# the dispatcher, the recursion goes:
#   fixture -> fetch_versioned_implementation -> import ee.onyx.main
#     -> ee.onyx.main line 53 `from onyx.main import get_application`
#     -> onyx.main line 706 calls fetch_versioned_implementation again
#     -> tries to import ee.onyx.main (mid-init), AttributeError on get_application.
# Letting onyx.main load first means ee.onyx.main's back-reference to
# onyx.main.get_application (defined at line 429, before line 706) resolves cleanly.
import onyx.main  # noqa: E402, F401
from onyx.auth.schemas import UserRole  # noqa: E402
from onyx.background.celery.apps.client import celery_app  # noqa: E402
from onyx.configs.constants import DocumentSource  # noqa: E402
from onyx.db.engine.sql_engine import get_session_with_current_tenant  # noqa: E402
from onyx.db.engine.sql_engine import SqlEngine  # noqa: E402
from onyx.db.search_settings import get_current_search_settings  # noqa: E402
from onyx.utils.variable_functionality import (  # noqa: E402
    fetch_versioned_implementation,
)
from shared_configs.configs import MULTI_TENANT  # noqa: E402
from tests.integration.common_utils import http_client  # noqa: E402
from tests.integration.common_utils.constants import ADMIN_USER_NAME  # noqa: E402
from tests.integration.common_utils.constants import GENERAL_HEADERS  # noqa: E402
from tests.integration.common_utils.managers.api_key import APIKeyManager  # noqa: E402
from tests.integration.common_utils.managers.document import (  # noqa: E402
    DocumentManager,
)
from tests.integration.common_utils.managers.image_generation import (  # noqa: E402
    ImageGenerationConfigManager,
)
from tests.integration.common_utils.managers.llm_provider import (  # noqa: E402
    LLMProviderManager,
)
from tests.integration.common_utils.managers.user import build_email  # noqa: E402
from tests.integration.common_utils.managers.user import DEFAULT_PASSWORD  # noqa: E402
from tests.integration.common_utils.managers.user import UserManager  # noqa: E402
from tests.integration.common_utils.reset import _seed_dev_license_if_set  # noqa: E402
from tests.integration.common_utils.reset import reset_all  # noqa: E402
from tests.integration.common_utils.reset import reset_all_multitenant  # noqa: E402
from tests.integration.common_utils.test_models import DATestAPIKey  # noqa: E402
from tests.integration.common_utils.test_models import (  # noqa: E402
    DATestImageGenerationConfig,
)
from tests.integration.common_utils.test_models import DATestLLMProvider  # noqa: E402
from tests.integration.common_utils.test_models import DATestUser  # noqa: E402
from tests.integration.common_utils.test_models import SimpleTestDocument  # noqa: E402
from tests.integration.common_utils.vespa import vespa_fixture  # noqa: E402

BASIC_USER_NAME = "basic_user"

DocumentBuilderType = Callable[[list[str]], list[SimpleTestDocument]]


@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    # Alembic must run before SqlEngine.init_engine / app lifespan so the
    # schema exists when setup_onyx() queries it. Mirrors the script's
    # `alembic upgrade head` / `alembic -n schema_private upgrade head`
    # branch on MULTI_TENANT.
    from alembic import command
    from alembic.config import Config

    ini_path = os.path.join(BACKEND_DIR, "alembic.ini")
    if MULTI_TENANT:
        cfg = Config(ini_path, ini_section="schema_private")
    else:
        cfg = Config(ini_path)
    # Alembic resolves `script_location = alembic` relative to CWD; pin it
    # to BACKEND_DIR so tests work regardless of where pytest was invoked.
    cfg.set_main_option(
        "script_location",
        os.path.join(BACKEND_DIR, cfg.get_main_option("script_location") or "alembic"),
    )
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _install_playwright(_run_migrations: None) -> None:  # noqa: ARG001
    # web_search tests exercise OnyxWebCrawler's Playwright fallback. The
    # devcontainer ships the apt deps; download the chromium binary here so
    # the version tracks the lockfile's playwright-python. Playwright has no
    # ubuntu26.04 build yet, so pin to the binary-compatible 24.04 build.
    # Skipped in onyx-lite (no web_search) and where Playwright isn't on PATH.
    if os.getenv("DISABLE_VECTOR_DB", "false").lower() == "true":
        return

    if shutil.which("playwright") is None:
        return

    machine = platform.machine().lower()
    pw_arch = "x64" if machine in ("x86_64", "amd64") else "arm64"
    env = os.environ.copy()
    env["PLAYWRIGHT_HOST_PLATFORM_OVERRIDE"] = f"ubuntu24.04-{pw_arch}"
    subprocess.run(["playwright", "install", "chromium"], env=env, check=True)


@pytest.fixture(scope="session", autouse=True)
def initialize_db(_run_migrations: None) -> None:  # noqa: ARG001
    # Make sure that the db engine is initialized before any tests are run
    SqlEngine.init_engine(
        pool_size=10,
        max_overflow=5,
    )


_CELERY_WORKER_PROGRAMS: list[tuple[str, str]] = [
    # (versioned_app, queues) — mirrors backend/supervisord.conf.
    ("primary", "celery"),
    (
        "light",
        "vespa_metadata_sync,connector_deletion,doc_permissions_upsert,"
        "checkpoint_cleanup,index_attempt_cleanup,opensearch_migration",
    ),
    (
        "heavy",
        "connector_pruning,connector_doc_permissions_sync,"
        "connector_external_group_sync,csv_generation,sandbox",
    ),
    ("docprocessing", "docprocessing"),
    (
        "user_file_processing",
        "user_file_processing,user_file_project_sync,user_file_delete",
    ),
    ("scheduled_tasks", "scheduled_tasks"),
    ("docfetching", "connector_doc_fetching"),
    ("monitoring", "monitoring"),
]


def _wait_for_celery_workers(expected: int, timeout: float = 90.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    last_count = 0
    while time.monotonic() < deadline:
        try:
            replies = celery_app.control.inspect(timeout=2).ping() or {}
        except Exception:
            replies = {}
        last_count = len(replies)
        if last_count >= expected:
            return
        time.sleep(1)
    raise RuntimeError(
        f"Only {last_count}/{expected} celery workers responded within {timeout}s"
    )


@pytest.fixture(scope="session", autouse=True)
def _start_celery_workers(
    _run_migrations: None,  # noqa: ARG001
    initialize_db: None,  # noqa: ARG001
) -> Generator[None, None, None]:
    # Spawn the same celery worker fleet supervisord used to run. We need
    # real workers (not eager mode) because the indexing pipeline uses
    # `SimpleJobClient`, which spawns docfetching in a fresh `spawn`-context
    # Python process. That subprocess inherits neither in-memory celery
    # config nor any monkey-patches from this conftest, so it dispatches via
    # the broker. Without real consumers, those tasks pile up forever and
    # every wait_for_indexing_completion / pruning / export test times out.
    # Onyx-lite has no vector DB / indexing pipeline, so spawning the fleet
    # there is pure overhead.
    if os.getenv("DISABLE_VECTOR_DB", "false").lower() == "true":
        yield None
        return

    log_dir = os.path.join(BACKEND_DIR, "log")
    os.makedirs(log_dir, exist_ok=True)

    processes: list[tuple[str, subprocess.Popen[bytes]]] = []
    log_handles: list[Any] = []
    for app_name, queues in _CELERY_WORKER_PROGRAMS:
        log_path = os.path.join(log_dir, f"celery_worker_{app_name}_debug.log")
        log_file = open(log_path, "ab")
        log_handles.append(log_file)
        cmd = [
            "celery",
            "-A",
            f"onyx.background.celery.versioned_apps.{app_name}",
            "worker",
            f"--hostname={app_name}@%n",
            "-Q",
            queues,
            "--pool=threads",
        ]
        # start_new_session=True puts the worker in its own process group so
        # we can kill the whole tree on teardown (celery spawns helper procs).
        proc = subprocess.Popen(
            cmd,
            cwd=BACKEND_DIR,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        processes.append((app_name, proc))

    # Celery beat fires the periodic scans (check-for-vespa-sync,
    # check-for-pruning, check-for-connector-deletion, ...) that user
    # group sync / pruning / deletion tests poll on. Without beat the
    # tests time out after 300s.
    beat_log_path = os.path.join(log_dir, "celery_beat_debug.log")
    beat_log_file = open(beat_log_path, "ab")
    log_handles.append(beat_log_file)
    beat_proc = subprocess.Popen(
        [
            "celery",
            "-A",
            "onyx.background.celery.versioned_apps.beat",
            "beat",
            "--loglevel=info",
        ],
        cwd=BACKEND_DIR,
        stdout=beat_log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    processes.append(("beat", beat_proc))

    try:
        # Beat doesn't respond to inspect().ping(); only count workers.
        _wait_for_celery_workers(expected=len(_CELERY_WORKER_PROGRAMS))
        yield None
    finally:
        import signal

        for _, proc in processes:
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for _, proc in processes:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        for log_file in log_handles:
            log_file.close()


@pytest.fixture(scope="session", autouse=True)
def _test_client(
    initialize_db: None,  # noqa: ARG001
    _start_celery_workers: None,  # noqa: ARG001
    _install_playwright: None,  # noqa: ARG001
) -> Generator[TestClient, None, None]:
    # In-process api_server. Use the versioned dispatcher so MT / EE
    # builds get ee.onyx.main.get_application — that's the one that
    # registers add_api_server_tenant_id_middleware (required to populate
    # CURRENT_TENANT_ID_CONTEXTVAR from the auth cookie in cloud mode).
    # `set_is_ee_based_on_env_variable()` already ran at onyx.main module
    # load above; the dispatcher hits the lru_cache and resolves to the
    # right implementation.
    # Patch setup_prometheus_metrics to avoid "Duplicated timeseries" if
    # get_application() is ever called more than once in the same process.
    # Use TestClient as a context manager so the real lifespan runs
    # (setup_onyx / file store init / pool metrics).
    get_application = fetch_versioned_implementation(
        module="onyx.main", attribute="get_application"
    )
    with patch("onyx.main.setup_prometheus_metrics"):
        app = get_application()
    with TestClient(app) as test_client:
        http_client.set_test_client(test_client)
        try:
            yield test_client
        finally:
            http_client.set_test_client(None)


@pytest.fixture(scope="session", autouse=True)
def seed_dev_license_for_session(initialize_db: None) -> None:  # noqa: ARG001
    # ``reset_postgres`` re-seeds the dev license after every wipe, but tests
    # that don't take the ``reset`` fixture would otherwise hit Business-tier
    # endpoints (e.g. /admin/api-key) with no License row and 402. Seed once at
    # session start; no-op when ONYX_DEV_LICENSE is unset. Skip in multi-tenant
    # mode: License rows live in tenant schemas, and the public-schema session
    # here would seed into the wrong place.
    if MULTI_TENANT:
        return
    with get_session_with_current_tenant() as db_session:
        _seed_dev_license_if_set(db_session)


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
def new_admin_user(reset: None) -> DATestUser:  # noqa: ARG001
    return UserManager.create(name=ADMIN_USER_NAME)


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
    admin_user: DATestUser,  # noqa: ARG001
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
def llm_provider(admin_user: DATestUser) -> DATestLLMProvider:
    return LLMProviderManager.create(user_performing_action=admin_user)


@pytest.fixture
def api_key(admin_user: DATestUser) -> DATestAPIKey:
    return APIKeyManager.create(user_performing_action=admin_user)


@pytest.fixture
def image_generation_config(
    admin_user: DATestUser,
) -> DATestImageGenerationConfig:
    """Create a default image generation config for tests."""
    return ImageGenerationConfigManager.create(
        user_performing_action=admin_user,
        is_default=True,
    )


@pytest.fixture
def document_builder(admin_user: DATestUser) -> DocumentBuilderType:
    # HACK: Avoid importing generated OpenAPI client modules unless this fixture is used.
    from tests.integration.common_utils.managers.cc_pair import CCPairManager

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


def pytest_runtest_logstart(
    nodeid: str,
    location: tuple[str, int | None, str],  # noqa: ARG001
) -> None:
    print(f"\nTest start: {nodeid}")


def pytest_runtest_logfinish(
    nodeid: str,
    location: tuple[str, int | None, str],  # noqa: ARG001
) -> None:
    print(f"\nTest end: {nodeid}")
