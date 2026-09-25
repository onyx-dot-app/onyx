"""Root conftest — shared fixtures available to all test directories."""

import os

# LiteLLM downloads its model cost map at import time unless this is set, so
# capability and pricing assertions would otherwise depend on upstream data
# that changes without notice. Pin the bundled copy to keep tests hermetic.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from collections.abc import Generator  # noqa: E402

import pytest  # noqa: E402

from onyx.utils.variable_functionality import (  # noqa: E402
    fetch_versioned_implementation,
    global_version,
)


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
