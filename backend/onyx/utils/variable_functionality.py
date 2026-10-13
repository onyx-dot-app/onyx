import functools
import importlib
import importlib.util
import inspect
from importlib.machinery import ModuleSpec
from typing import Any, TypeVar

from onyx.configs.app_configs import (
    API_SERVER_HOST,
    API_SERVER_PROTOCOL,
    API_SERVER_URL_OVERRIDE_FOR_HTTP_REQUESTS,
    APP_API_PREFIX,
    APP_PORT,
    DEV_MODE,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


class OnyxVersion:
    def __init__(self) -> None:
        self._is_ee = False

    def set_ee(self) -> None:
        self._is_ee = True

    def unset_ee(self) -> None:
        self._is_ee = False

    def is_ee_version(self) -> bool:
        return self._is_ee


global_version = OnyxVersion()


def is_ee_available() -> bool:
    """Whether this build ships the Enterprise Edition code. The MIT-only mirror
    strips `ee.onyx` and keeps a bare `ee` package."""
    try:
        spec: ModuleSpec | None = importlib.util.find_spec("ee.onyx")
    except ModuleNotFoundError:
        # No `ee` package at all.
        return False
    # A leftover directory with no `__init__.py` resolves as a namespace
    # package, which has no origin.
    return spec is not None and spec.origin is not None


def set_is_ee_if_available() -> None:
    """Loads the Enterprise Edition code when the build ships it. Loading
    unlocks nothing: every paid feature is gated on the license, so a
    deployment with no license behaves as Community Edition."""
    if global_version.is_ee_version() or not is_ee_available():
        return

    logger.notice(
        "Enterprise Edition code is loaded. Paid features stay locked until a "
        "valid license is applied."
    )
    global_version.set_ee()


@functools.lru_cache(maxsize=128)
def fetch_versioned_implementation(module: str, attribute: str) -> Any:
    """
    Fetches a versioned implementation of a specified attribute from a given module.
    This function first checks if the application is running in an Enterprise Edition (EE)
    context. If so, it attempts to import the attribute from the EE-specific module.
    If the module or attribute is not found, it falls back to the default module or
    raises the appropriate exception depending on the context.

    Args:
        module (str): The name of the module from which to fetch the attribute.
        attribute (str): The name of the attribute to fetch from the module.

    Returns:
        Any: The fetched implementation of the attribute.

    Raises:
        ModuleNotFoundError: If the module cannot be found and the error is not related to
                             the Enterprise Edition fallback logic.

    Logs:
        Logs debug information about the fetching process and warnings if the versioned
        implementation cannot be found or loaded.
    """
    logger.debug("Fetching versioned implementation for %s.%s", module, attribute)
    is_ee = global_version.is_ee_version()

    module_full = f"ee.{module}" if is_ee else module
    try:
        return getattr(  # ods: ignore[getattr]
            importlib.import_module(module_full), attribute
        )
    except ModuleNotFoundError as e:
        logger.warning(
            "Failed to fetch versioned implementation for %s.%s: %s",
            module_full,
            attribute,
            e,
        )

        if is_ee:
            if "ee.onyx" not in str(e):
                # If it's a non Onyx related import failure, this is likely because
                # a dependent library has not been installed. Should raise this failure
                # instead of letting the server start up
                raise e

            # Use the MIT version as a fallback, this allows us to develop MIT
            # versions independently and later add additional EE functionality
            # similar to feature flagging
            return getattr(  # ods: ignore[getattr]
                importlib.import_module(module), attribute
            )

        raise


T = TypeVar("T")


def fetch_versioned_implementation_with_fallback(
    module: str, attribute: str, fallback: T
) -> T:
    """
    Attempts to fetch a versioned implementation of a specified attribute from a given module.
    If the attempt fails (e.g., due to an import error or missing attribute), the function logs
    a warning and returns the provided fallback implementation.

    Args:
        module (str): The name of the module from which to fetch the attribute.
        attribute (str): The name of the attribute to fetch from the module.
        fallback (T): The fallback implementation to return if fetching the attribute fails.

    Returns:
        T: The fetched implementation if successful, otherwise the provided fallback.
    """
    try:
        return fetch_versioned_implementation(module, attribute)
    except Exception:
        return fallback


def noop_fallback(*args: Any, **kwargs: Any) -> None:
    """
    A no-op (no operation) fallback function that accepts any arguments but does nothing.
    This is often used as a default or placeholder callback function.

    Args:
        *args (Any): Positional arguments, which are ignored.
        **kwargs (Any): Keyword arguments, which are ignored.

    Returns:
        None
    """


def fetch_ee_implementation_or_noop(
    module: str, attribute: str, noop_return_value: Any = None
) -> Any:
    """
    Fetches an EE implementation if EE is enabled, otherwise returns a no-op function.
    Raises an exception if EE is enabled but the fetch fails.

    Args:
        module (str): The name of the module from which to fetch the attribute.
        attribute (str): The name of the attribute to fetch from the module.

    Returns:
        Any: The fetched EE implementation if successful and EE is enabled, otherwise a no-op function.

    Raises:
        Exception: If EE is enabled but the fetch fails.
    """
    if not global_version.is_ee_version():
        if inspect.iscoroutinefunction(noop_return_value):

            async def async_noop(*args: Any, **kwargs: Any) -> Any:
                return await noop_return_value(*args, **kwargs)

            return async_noop

        else:

            def sync_noop(*args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
                return noop_return_value

            return sync_noop
    try:
        return fetch_versioned_implementation(module, attribute)
    except Exception as e:
        logger.error(
            "Failed to fetch implementation for %s.%s: %s", module, attribute, e
        )
        raise


def build_api_server_url_for_http_requests(
    respect_env_override_if_set: bool = False,
) -> str:
    """
    Builds the API server URL for HTTP requests.
    """
    if DEV_MODE:
        url = f"http://127.0.0.1:{APP_PORT}"
    elif respect_env_override_if_set and API_SERVER_URL_OVERRIDE_FOR_HTTP_REQUESTS:
        url = API_SERVER_URL_OVERRIDE_FOR_HTTP_REQUESTS.rstrip("/")
    else:
        url = f"{API_SERVER_PROTOCOL}://{API_SERVER_HOST}:{APP_PORT}"

    if APP_API_PREFIX:
        url += f"/{APP_API_PREFIX.strip('/')}"

    return url
