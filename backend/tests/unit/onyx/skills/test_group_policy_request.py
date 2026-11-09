import pytest
from pydantic import ValidationError

from onyx.server.features.skill.models import SkillShareRequest


@pytest.mark.parametrize("policy", ["NOT_AVAILABLE"])
def test_not_available_group_policy_is_rejected(
    policy: str | None,
) -> None:
    with pytest.raises(ValidationError) as rejected:
        SkillShareRequest.model_validate(
            {
                "group_shares": [
                    {
                        "group_id": 1,
                        "permission": "VIEWER",
                        "installation_policy": policy,
                    }
                ]
            }
        )
    assert [(error["loc"], error["type"]) for error in rejected.value.errors()] == [
        (("group_shares", 0, "installation_policy"), "literal_error")
    ]


def test_group_share_without_policy_remains_supported() -> None:
    request = SkillShareRequest.model_validate(
        {"group_shares": [{"group_id": 1, "permission": "VIEWER"}]}
    )
    assert request.model_dump(mode="json", exclude_unset=True)["group_shares"] == [
        {"group_id": 1, "permission": "VIEWER"}
    ]
