"""Fixtures for unit-testing DAL classes with mocked sessions."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from ee.onyx.db.scim import ScimDAL


def model_attrs(obj: object) -> dict[str, Any]:
    """Extract user-set attributes from a SQLAlchemy model instance.

    Filters out SQLAlchemy internal state (``_sa_instance_state``).
    Use this in tests to assert the full set of fields on a model object
    so that adding a new field forces the test to be updated.
    """
    return {k: v for k, v in vars(obj).items() if not k.startswith("_")}


@pytest.fixture
def mock_db_session() -> MagicMock:
    """A MagicMock standing in for a SQLAlchemy Session."""
    return MagicMock(spec=Session)


@pytest.fixture
def scim_dal(mock_db_session: MagicMock) -> ScimDAL:
    """A ScimDAL backed by a mock session."""
    return ScimDAL(mock_db_session)
