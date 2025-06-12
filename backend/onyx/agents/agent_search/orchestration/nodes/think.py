from typing import Any, cast

from langchain_core.messages import AIMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.basic.utils import process_llm_stream
from onyx.agents.agent_search.models import GraphConfig
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.configs.constants import MessageType
from onyx.db.chat import create_new_chat_message, get_chat_messages_by_session
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.utils.logger import setup_logger

logger = setup_logger()

_THINKING_INSTRUCTIONS = """
Create a comprehensive, step-by-step plan for responding to the user's query. This is your thinking phase where you analyze the query and plan your approach before taking action.

**Your task is to:**

1. **Analyze the user query** - Understand what the user is asking for, the complexity of the request, and what type of response would be most helpful.

2. **Determine if tools are needed** - Evaluate whether you can answer using only your knowledge, or if you need to use available tools.

3. **Create a detailed execution plan** - If tools are needed, specify:
   - Which specific tools you will use
   - The exact tool parameters you will use
   - The sequence of tool usage (what to do first, second, etc.)
   - How you will combine information from multiple tools
   - How you will synthesize the results into a coherent response

4. **Plan your final response structure** - Outline how you will organize and present the information to best serve the user's needs.

**Important guidelines:**
- Be specific about tool parameters
- Consider multiple approaches if the first might not be sufficient
- Think about potential follow-up questions the user might have
- Plan for how to handle if tools don't return the expected results
- Consider the user's likely expertise level and adjust your planned response accordingly
"""


def think(
    state: Any, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> dict:
    """
    Agentic thinking node.

    This node is responsible for generating a plan for responding to the
    user query. It does not use any tools itself.
    """
    agent_config = cast(GraphConfig, config.get("metadata", {}).get("config"))
    llm = agent_config.tooling.primary_llm
    prompt_builder = agent_config.inputs.prompt_builder
    persistence = agent_config.persistence

    built_prompt = prompt_builder.build(state_instructions=_THINKING_INSTRUCTIONS)
    stream = llm.stream(prompt=built_prompt)
    response_chunk = process_llm_stream(
        stream,
        should_stream_answer=True,
        writer=writer,
        return_text_content=True,
        is_thinking=True,
    )
    response_content = response_chunk.content
    assert isinstance(response_content, str)

    # Update prompt builder history with thinking message
    _update_prompt_builder_with_thinking(prompt_builder, response_content)

    # Save the assistant message to the database
    try:
        chat_messages = get_chat_messages_by_session(
            chat_session_id=persistence.chat_session_id,
            user_id=None,  # We're in an authorized context
            db_session=persistence.db_session,
            skip_permission_check=True,
        )
        final_msg = chat_messages[-1]
        tokenizer = get_tokenizer(
            model_name=llm.config.model_name, provider_type=llm.config.model_provider
        )
        token_count = len(tokenizer.encode(response_content))
        create_new_chat_message(
            chat_session_id=persistence.chat_session_id,
            parent_message=final_msg,
            message=response_content,
            prompt_id=None,
            token_count=token_count,
            message_type=MessageType.ASSISTANT,
            db_session=persistence.db_session,
            commit=True,
        )
    except Exception as e:
        logger.error(f"Failed to save assistant message to database: {e}")
    return {}


def _update_prompt_builder_with_thinking(
    prompt_builder: AnswerPromptBuilder, thinking_content: str
) -> None:
    """Add thinking message to prompt builder history as an AIMessage."""
    try:
        # Create AIMessage with thinking content
        thinking_message = AIMessage(content=thinking_content)

        # Add the message using the proper append_message method
        prompt_builder.append_message(thinking_message)

    except Exception as e:
        logger.error(f"Error updating prompt builder with thinking message: {e}")
        # Don't raise - we can continue without updating prompt history
        # The database persistence still works
        logger.warning("Continuing without updating prompt builder history")
