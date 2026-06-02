"""Pure unit tests for the matching engine. The DB-driven ``match_action``
path is covered in ``external_dependency_unit/craft/test_action_matching.py``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from onyx.external_apps.matching.engine import RequestMatch


def test_request_match_rejects_empty_actions() -> None:
    """A RequestMatch with no actions is a programmer error — every gate
    consumer reads ``actions[0]``."""
    with pytest.raises(ValidationError, match="actions must be non-empty"):
        RequestMatch(actions=(), app_name="X", external_app_id=1)
