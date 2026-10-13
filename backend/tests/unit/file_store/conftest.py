"""The default file store is built once per process, and these tests pick a
backend and settings per test, so each one starts without a cached store."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest

from onyx.file_store import file_store as file_store_module


@pytest.fixture(autouse=True)
def _fresh_default_file_store() -> Iterator[None]:
    with patch.object(file_store_module, "_DEFAULT_FILE_STORE", None):
        yield
