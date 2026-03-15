"""Root conftest — shared fixtures available to all test directories."""

from collections.abc import Generator

import pytest

from onyx.utils.variable_functionality import fetch_versioned_implementation
from onyx.utils.variable_functionality import global_version


@pytest.fixture()
def enable_ee() -> Generator[None, None, None]:
    """Temporarily enable EE mode for a single test.

    Restores the previous EE state and clears the versioned-implementation
    cache on teardown so state doesn't leak between tests.
    """
    was_ee = global_version.is_ee_version()
    global_version.set_ee()
    fetch_versioned_implementation.cache_clear()
    yield
    if not was_ee:
        global_version.unset_ee()
    fetch_versioned_implementation.cache_clear()
