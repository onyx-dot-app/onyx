import json
from typing import Any

from agents import function_tool
from agents import RunContextWrapper

from onyx.chat.turn.models import ChatTurnContext
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting
from onyx.utils.logger import setup_logger

logger = setup_logger()


@tool_accounting
def _okta_profile_core(
    run_context: RunContextWrapper[ChatTurnContext],
    okta_profile_tool_instance: Any,
) -> dict[str, Any]:
    """Core Okta profile logic that can be tested with dependency injection"""
    if okta_profile_tool_instance is None:
        raise RuntimeError("Okta profile tool not available in context")

    index = run_context.context.current_run_step
    emitter = run_context.context.run_dependencies.emitter  # type: ignore[union-attr]

    # Emit start event
    emitter.emit(  # type: ignore[union-attr]
        Packet(
            ind=index,
            obj=CustomToolStart(type="custom_tool_start", tool_name="Okta Profile"),
        )
    )

    # Emit delta event for fetching profile
    emitter.emit(  # type: ignore[union-attr]
        Packet(
            ind=index,
            obj=CustomToolDelta(
                type="custom_tool_delta",
                tool_name="Okta Profile",
                response_type="text",
                data="Fetching profile information...",
            ),
        )
    )

    # Run the actual Okta profile tool
    profile_data = None
    for tool_response in okta_profile_tool_instance.run():
        if tool_response.id == "okta_profile":
            profile_data = tool_response.response
            break

    if profile_data is None:
        raise RuntimeError("No profile data was retrieved from Okta")

    # Emit final result
    emitter.emit(  # type: ignore[union-attr]
        Packet(
            ind=index,
            obj=CustomToolDelta(
                type="custom_tool_delta",
                tool_name="Okta Profile",
                response_type="json",
                data=profile_data,
            ),
        )
    )

    return profile_data


@function_tool
def okta_profile(run_context: RunContextWrapper[ChatTurnContext]) -> str:
    """
    Retrieve the current user's profile information from Okta.

    This tool fetches user profile details including name, email, department,
    location, title, manager, and other profile information from the Okta identity provider.
    """
    # Get the Okta profile tool from context
    okta_profile_tool_instance = run_context.context.run_dependencies.okta_profile_tool

    # Call the core function
    profile_data = _okta_profile_core(run_context, okta_profile_tool_instance)

    return json.dumps(profile_data)
