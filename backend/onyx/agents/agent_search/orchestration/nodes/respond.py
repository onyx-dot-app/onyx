from typing import Any, cast

from langchain_core.messages import AIMessageChunk
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.basic.utils import process_llm_stream
from onyx.agents.agent_search.models import GraphConfig
from onyx.db.chat import create_new_chat_message, get_chat_messages_by_session
from onyx.configs.constants import MessageType
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.utils.logger import setup_logger

logger = setup_logger()


def respond(
    state: Any, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> dict[str, Any]:
    """
    Document chat response generation:
    1. Build the prompt using the prompt builder (which now includes tool results)
    2. Call the LLM to stream the response
    3. Handle streaming and packet emission
    4. Save the assistant message to the database
    """
    agent_config = cast(GraphConfig, config.get("metadata", {}).get("config"))

    # Get the LLM and prompt builder from config
    llm = agent_config.tooling.primary_llm
    prompt_builder = agent_config.inputs.prompt_builder
    structured_response_format = agent_config.inputs.structured_response_format

    # Get persistence info for database operations
    persistence = agent_config.persistence
    if not persistence:
        raise ValueError("GraphPersistence is required for document chat workflow")

    # Get search results from use_tool node if they exist
    final_search_results = getattr(state, "final_search_results", None) or []
    initial_search_results = getattr(state, "initial_search_results", None) or []
    displayed_results = initial_search_results or final_search_results

    # Build the prompt directly from the prompt builder (now includes tool results)
    built_prompt = prompt_builder.build()

    # Initialize response content
    response_content = ""

    # Stream the LLM response
    if not agent_config.behavior.skip_gen_ai_answer_generation:
        stream = llm.stream(
            prompt=built_prompt, structured_response_format=structured_response_format
        )

        # Process the stream and emit packets with search results for citations
        response_chunk = process_llm_stream(
            stream,
            True,  # should_stream_answer
            writer,
            final_search_results=final_search_results,
            displayed_search_results=displayed_results,
            return_text_content=True,
        )

        # Extract the content for database persistence
        response_content = response_chunk.content or ""
        assert isinstance(response_content, str)
    else:
        # If skipping gen AI, create empty response
        response_chunk = AIMessageChunk(content="")
        response_content = ""

    # Save the assistant message to the database
    try:
        # Get the current messages in the chat to find the latest one as parent
        chat_messages = get_chat_messages_by_session(
            chat_session_id=persistence.chat_session_id,
            user_id=None,  # We're in an authorized context
            db_session=persistence.db_session,
            skip_permission_check=True,
        )

        # Get the latest message to use as parent
        final_msg = chat_messages[-1]

        # Calculate token count for the response
        tokenizer = get_tokenizer(
            model_name=llm.config.model_name, provider_type=llm.config.model_provider
        )
        token_count = len(tokenizer.encode(response_content))

        # Create the assistant message
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
        # Don't raise the exception - we still want to return the response
        # The streaming already happened, so the user got the response

    # Return state updates that will be used for the final DocumentChatOutput
    return {
        "response_chunk": response_chunk,
        "edited_document": None,  # No document editing in this basic response flow
        "search_results": None,  # DocumentChatOutput expects string, actual results are in state
        "should_stream_answer": True,
        "tools": [tool.name for tool in (agent_config.tooling.tools or [])],
    }
