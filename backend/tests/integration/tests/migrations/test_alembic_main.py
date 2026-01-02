"""
pytest-alembic tests for the main schema migrations.

These tests use pytest-alembic to verify that alembic migrations are correct.
The tests cover:
- Single head revision (no diverged migration history)
- Upgrade path from base to head
- Up/down consistency (all downgrades succeed)

Usage:
    pytest tests/integration/tests/migrations/test_alembic_main.py -v

See: https://github.com/schireson/pytest-alembic
"""

from pytest_alembic.tests import test_single_head_revision  # type: ignore[import-not-found,unused-ignore]
from pytest_alembic.tests import test_up_down_consistency  # type: ignore[import-not-found,unused-ignore]
from pytest_alembic.tests import test_upgrade  # type: ignore[import-not-found,unused-ignore]

__all__ = [
    "test_single_head_revision",
    "test_up_down_consistency",
    "test_upgrade",
]
