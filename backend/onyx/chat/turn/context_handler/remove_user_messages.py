"""Remove user messages context handler for cleaning up agent turn messages."""

from collections.abc import Sequence

from onyx.agents.agent_sdk.message_types import AgentSDKMessage


def remove_middle_user_messages(
    agent_turn_messages: Sequence[AgentSDKMessage],
) -> list[AgentSDKMessage]:
    """Remove all user messages from agent_turn_messages.

    During agent loop iterations, user messages are added for reminders,
    custom instructions, and other context. This function removes all
    user messages to leave only the clean tool call + tool response pairs
    from the agent's interactions.

    Args:
        agent_turn_messages: Messages from the current agent turn iteration

    Returns:
        Filtered list with only system, assistant, tool, and function call messages
    """
    return [msg for msg in agent_turn_messages if msg.get("role") != "user"]
