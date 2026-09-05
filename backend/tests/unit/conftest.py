"""Unit-suite conftest.

Unit tests assume OSS resolution unless they opt into EE via the shared
``enable_ee`` fixture (see ``backend/tests/conftest.py``).
"""

from collections.abc import Generator

import pytest

from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)


@pytest.fixture(autouse=True)
def _reset_leaked_ee_state() -> Generator[None, None, None]:
    """Undoes EE state leaked into the process by import side effects.

    ``set_is_ee_based_on_env_variable()`` runs at module level in ``onyx.main``
    and every ``background/celery/versioned_apps`` module, and flips the
    process-global EE flag whenever license enforcement is on (its default). A
    unit test whose import chain reaches one of those modules therefore silently
    switches every later test in the worker to EE resolution, breaking
    OSS-asserting tests order-dependently. Runs before ``enable_ee`` (autouse
    fixtures are instantiated first), so opting in still works.
    """
    if global_version.is_ee_version():
        global_version.unset_ee()
        # Entries resolved while the flag was flipped point at EE
        # implementations; drop them along with the flag.
        fetch_versioned_implementation.cache_clear()
    yield
