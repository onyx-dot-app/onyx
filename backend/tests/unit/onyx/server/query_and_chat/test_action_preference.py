"""Validate the public preference contract before chat admission."""

import pytest
from pydantic import ValidationError

from onyx.server.query_and_chat.models import SendMessageRequest


def test_preference_request_does_not_claim_forcing() -> None:
    request = SendMessageRequest.model_validate(
        {"message": "Question", "preferred_tool_id": 7}
    )
    assert request.preferred_tool_id == 7
    assert "forced_tool_id" not in request.model_dump()
    assert (
        SendMessageRequest.model_validate(
            {"message": "Question", "forced_tool_id": None}
        ).preferred_tool_id
        is None
    )


@pytest.mark.parametrize(
    "data,reason",
    [
        ({"forced_tool_id": 7}, "forced_tool_id is no longer supported"),
        (
            {"preferred_tool_id": 7, "forced_tool_id": 7},
            "forced_tool_id is no longer supported",
        ),
        (
            {"preferred_tool_id": 7, "deep_research": True},
            "not supported with deep_research",
        ),
    ],
)
def test_invalid_preference_contract_is_rejected(
    data: dict[str, object], reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        SendMessageRequest.model_validate({"message": "Question", **data})
