"""Root conftest — shared fixtures available to all test directories."""

import os

# LiteLLM downloads its model cost map at import time unless this is set, so
# capability and pricing assertions would otherwise depend on upstream data
# that changes without notice. Pin the bundled copy to keep tests hermetic.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from collections.abc import Generator  # noqa: E402
from contextlib import contextmanager  # noqa: E402

import pytest  # noqa: E402

from onyx.utils.variable_functionality import (  # noqa: E402
    fetch_versioned_implementation,
    global_version,
)


@contextmanager
def _ee_enabled() -> Generator[None, None, None]:
    """Enables EE mode, then restores the previous EE state and clears the
    versioned-implementation cache so state doesn't leak between tests."""
    was_ee = global_version.is_ee_version()
    global_version.set_ee()
    fetch_versioned_implementation.cache_clear()
    try:
        yield
    finally:
        if not was_ee:
            global_version.unset_ee()
        fetch_versioned_implementation.cache_clear()


@pytest.fixture()
def enable_ee() -> Generator[None, None, None]:
    """Temporarily enable EE mode for a single test."""
    with _ee_enabled():
        yield


@pytest.fixture()
def enterprise_audit(
    enable_ee: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Enable EE and resolve every tenant to the Enterprise tier, so the audit
    stream writes events. Clears the audit tier cache before and after."""
    from ee.onyx.utils import audit as ee_audit
    from ee.onyx.utils import tier
    from onyx.server.settings.models import Tier

    monkeypatch.setattr(tier, "get_tier", lambda tenant_id=None: Tier.ENTERPRISE)  # noqa: ARG005
    ee_audit._tier_cache.clear()
    try:
        yield
    finally:
        ee_audit._tier_cache.clear()


@pytest.fixture(scope="module")
def enable_ee_module() -> Generator[None, None, None]:
    """Enable EE mode for a module, e.g. for a module-scoped fixture, which
    runs before the function-scoped ``enable_ee``."""
    with _ee_enabled():
        yield
