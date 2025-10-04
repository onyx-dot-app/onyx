import json

from agents import function_tool
from agents import RunContextWrapper

from onyx.chat.turn.models import MyContext
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.utils.logger import setup_logger

logger = setup_logger()


@function_tool
def okta_profile_tool(run_context: RunContextWrapper[MyContext]) -> str:
    """
    Retrieve the current user's profile information from Okta.

    This tool fetches user profile details including name, email, department,
    location, title, manager, and other profile information from the Okta identity provider.
    """
    # Get the Okta profile tool from context
    okta_profile_tool = run_context.context.run_dependencies.okta_profile_tool
    if okta_profile_tool is None:
        raise RuntimeError("Okta profile tool not available in context")

    index = run_context.context.current_run_step + 1
    emitter = run_context.context.run_dependencies.emitter

    # Emit start event
    emitter.emit(
        Packet(
            ind=index,
            obj=CustomToolStart(type="custom_tool_start", tool_name="Okta Profile"),
        )
    )

    # Emit delta event for fetching profile
    emitter.emit(
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
    for tool_response in okta_profile_tool.run():
        if tool_response.id == "okta_profile":
            profile_data = tool_response.response
            break

    if profile_data is None:
        raise RuntimeError("No profile data was retrieved from Okta")

    # Emit final result
    emitter.emit(
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

    # Emit section end
    emitter.emit(
        Packet(
            ind=index,
            obj=SectionEnd(
                type="section_end",
            ),
        )
    )

    run_context.context.current_run_step = index + 1

    return json.dumps(profile_data)
