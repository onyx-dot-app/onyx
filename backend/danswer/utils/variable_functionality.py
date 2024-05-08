import functools
import importlib
from typing import Any

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


@functools.lru_cache(maxsize=128)
def fetch_versioned_implementation(module: str, attribute: str) -> Any:
    logger.debug("Fetching versioned implementation for %s.%s", module, attribute)
    module_full = f"ee.{module}" if global_version.get_is_ee_version() else module
    return getattr(importlib.import_module(module_full), attribute)
