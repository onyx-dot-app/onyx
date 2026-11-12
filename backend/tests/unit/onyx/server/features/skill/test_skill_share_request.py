"""The skills API takes the legacy three-value install setting, so it cannot
store NOT_AVAILABLE on a plugin until group install settings ship."""

import pytest
from pydantic import ValidationError

from onyx.server.features.skill.models import SkillShareRequest


def test_share_request_refuses_not_available() -> None:
    with pytest.raises(ValidationError):
        SkillShareRequest.model_validate({"installation_policy": "NOT_AVAILABLE"})
