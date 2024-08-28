import functools
import importlib
from typing import Any
from typing import TypeVar

from danswer.configs.app_configs import ENTERPRISE_EDITION_ENABLED
from danswer.utils.logger import setup_logger

logger = setup_logger()


class DanswerVersion:
    def __init__(self) -> None:
        self._is_ee = False

    def set_ee(self) -> None:
        self._is_ee = True

    def get_is_ee_version(self) -> bool:
        return self._is_ee


global_version = DanswerVersion()


def set_is_ee_based_on_env_variable() -> None:
    if ENTERPRISE_EDITION_ENABLED and not global_version.get_is_ee_version():
        logger.notice("Enterprise Edition enabled")
        global_version.set_ee()


@functools.lru_cache(maxsize=128)
def fetch_versioned_implementation(module: str, attribute: str) -> Any:
    logger.debug("Fetching versioned implementation for %s.%s", module, attribute)
    is_ee = global_version.get_is_ee_version()

    module_full = f"ee.{module}" if is_ee else module
    try:
        return getattr(importlib.import_module(module_full), attribute)
    except ModuleNotFoundError as e:
        logger.warning(
            "Failed to fetch versioned implementation for %s.%s: %s",
            module_full,
            attribute,
            e,
        )

        if is_ee:
            if "ee.danswer" not in str(e):
                # If it's a non Danswer related import failure, this is likely because
                # a dependent library has not been installed. Should raise this failure
                # instead of letting the server start up
                raise e

            # Use the MIT version as a fallback, this allows us to develop MIT
            # versions independently and later add additional EE functionality
            # similar to feature flagging
            return getattr(importlib.import_module(module), attribute)

        raise


T = TypeVar("T")


def fetch_versioned_implementation_with_fallback(
    module: str, attribute: str, fallback: T
) -> T:
    try:
        return fetch_versioned_implementation(module, attribute)
    except Exception as e:
        logger.warning(
            "Failed to fetch versioned implementation for %s.%s: %s",
            module,
            attribute,
            e,
        )
        return fallback


def noop_fallback(*args: Any, **kwargs: Any) -> None:
    pass
