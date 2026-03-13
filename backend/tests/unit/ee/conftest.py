"""Auto-enable EE mode for all tests under tests/unit/ee/."""

import pytest


@pytest.fixture(autouse=True)
def _enable_ee_for_directory(enable_ee: None) -> None:  # noqa: W291
    """Wraps the shared enable_ee fixture with autouse for this directory."""
