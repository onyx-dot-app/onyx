"""Validate the public preference contract before chat admission."""

import pytest
from pydantic import ValidationError

from onyx.context.search.models import BaseFilters
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.tools.models import CapabilityEntry, ToolOptions

PREFERENCE = {"type": "capability", "tool_id": 7}


def test_preference_request_does_not_claim_forcing() -> None:
    request = SendMessageRequest.model_validate(
        {"message": "Question", "tool_options": {"preferred": PREFERENCE}}
    )
    assert request.tool_options is not None
    assert request.tool_options.preferred == CapabilityEntry(tool_id=7)
    assert "forced_tool_id" not in request.model_dump()
    assert (
        SendMessageRequest.model_validate(
            {"message": "Question", "forced_tool_id": None}
        ).tool_options
        is None
    )


def test_top_level_search_filters_move_into_the_tool_options() -> None:
    request = SendMessageRequest.model_validate(
        {
            "message": "Question",
            "internal_search_filters": {"source_type": ["web"]},
            "tool_options": {"preferred": PREFERENCE},
        }
    )
    assert request.tool_options is not None
    assert request.tool_options.preferred == CapabilityEntry(tool_id=7)
    assert request.internal_search_filters == BaseFilters(source_type=["web"])


def test_top_level_search_filters_merge_into_typed_tool_options() -> None:
    request = SendMessageRequest.model_validate(
        {
            "message": "Question",
            "tool_options": ToolOptions(allowed=[]),
            "internal_search_filters": {"source_type": ["web"]},
        }
    )
    assert request.tool_options is not None
    assert request.tool_options.allowed == []
    assert request.internal_search_filters == BaseFilters(source_type=["web"])


@pytest.mark.parametrize(
    "data,reason",
    [
        ({"forced_tool_id": 7}, "forced_tool_id is no longer supported"),
        (
            {"allowed_tool_ids": [7]},
            "allowed_tool_ids is no longer supported. Use tool_options",
        ),
        (
            {"preferred_tool_id": 7},
            "preferred_tool_id is no longer supported. Use tool_options",
        ),
        (
            {"tool_options": {"preferred": PREFERENCE}, "deep_research": True},
            "not supported with deep_research",
        ),
        (
            {
                "tool_options": {
                    "allowed": [{"type": "capability", "tool_id": 7, "x": 1}]
                }
            },
            "Extra inputs are not permitted",
        ),
        (
            {
                "internal_search_filters": {"source_type": ["web"]},
                "tool_options": {"internal_search_filters": {"source_type": ["web"]}},
            },
            "not in both",
        ),
        (
            {"internal_search_filters": {}, "tool_options": True},
            "tool_options must be an object",
        ),
    ],
)
def test_invalid_preference_contract_is_rejected(
    data: dict[str, object], reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        SendMessageRequest.model_validate({"message": "Question", **data})
