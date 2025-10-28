import json
from typing import Any

from agents import function_tool
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.chat.answer import Answer
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import CitationConfig
from onyx.chat.models import DocumentPruningConfig
from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.chat.prompt_builder.answer_prompt_builder import default_build_system_message
from onyx.chat.prompt_builder.answer_prompt_builder import default_build_user_message
from onyx.chat.turn.models import ChatTurnContext
from onyx.context.search.enums import OptionalSearchSetting
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import RetrievalDetails
from onyx.db.persona import get_persona_by_id
from onyx.llm.factory import get_llms_for_persona
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.tools.force import ForceUseTool
from onyx.tools.tool_constructor import construct_tools
from onyx.tools.tool_constructor import CustomToolConfig
from onyx.tools.tool_constructor import ImageGenerationToolConfig
from onyx.tools.tool_constructor import SearchToolConfig
from onyx.tools.tool_constructor import WebSearchToolConfig
from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting
from onyx.utils.logger import setup_logger

logger = setup_logger()


@tool_accounting
def _agent_tool_core(
    run_context: RunContextWrapper[ChatTurnContext],
    query: str,
    target_persona_id: int,
    agent_tool_id: int,
) -> dict[str, Any]:
    """
    Core agent tool logic that delegates to a subagent.

    This function:
    1. Gets the target persona and its configured tools
    2. Creates a system prompt with available tools
    3. Uses the LLM to decide which tools to call
    4. Executes those tools with calling_agent_name set
    5. Returns the aggregated results
    """
    logger.info(f"bruh run_context: {run_context}")
    logger.info(f"bruh target_persona_id: {target_persona_id}")
    index = run_context.context.current_run_step

    # Get the target persona
    target_persona = get_persona_by_id(
        persona_id=target_persona_id,
        user=None,  # Bypass auth for subagent calls
        db_session=run_context.context.run_dependencies.db_session,
        include_deleted=False,
        is_for_edit=False,
    )

    # Emit start event
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            ind=index,
            obj=SearchToolStart(
                type="internal_search_tool_start", is_internet_search=False
            ),
        )
    )

    # Add iteration instructions
    run_context.context.iteration_instructions.append(
        IterationInstructions(
            iteration_nr=index,
            plan="plan",
            purpose=f"Delegating to subagent: {target_persona.name}",
            reasoning=f"I am now delegating this task to the {target_persona.name} agent: {query}",
        )
    )

    # Get the LLM for the subagent persona
    llm, fast_llm = get_llms_for_persona(
        persona=target_persona,
        llm_override=None,
        additional_headers=None,
    )

    # Build the prompt config for the subagent
    prompt_config = PromptConfig.from_model(target_persona)

    # Construct tool configs similar to stream_chat_message_objects
    answer_style_config = AnswerStyleConfig(
        citation_config=CitationConfig(all_docs_useful=False),
        structured_response_format=None,
    )

    document_pruning_config = DocumentPruningConfig(
        max_chunks=int(
            target_persona.num_chunks if target_persona.num_chunks is not None else 10
        ),
        max_window_percentage=0.5,
    )

    tool_dict = construct_tools(
        persona=target_persona,
        prompt_config=prompt_config,
        db_session=run_context.context.run_dependencies.db_session,
        user=None,  # No user context for subagent
        llm=llm,
        fast_llm=fast_llm,
        run_search_setting=OptionalSearchSetting.AUTO,
        search_tool_config=SearchToolConfig(
            answer_style_config=answer_style_config,
            document_pruning_config=document_pruning_config,
            retrieval_options=RetrievalDetails(),
            rerank_settings=None,
            selected_sections=None,
            chunks_above=0,
            chunks_below=0,
            full_doc=False,
            latest_query_files=[],
            bypass_acl=False,
        ),
        internet_search_tool_config=WebSearchToolConfig(
            answer_style_config=answer_style_config,
            document_pruning_config=document_pruning_config,
        ),
        image_generation_tool_config=ImageGenerationToolConfig(
            additional_headers=None,
        ),
        custom_tool_config=CustomToolConfig(
            chat_session_id=run_context.context.chat_session_id,
            message_id=run_context.context.message_id,
            additional_headers=None,
        ),
        allowed_tool_ids=None,  # Subagent can use all its configured tools
        slack_context=None,  # Subagents don't have Slack context
    )

    # Flatten tool_dict to get list of tools
    subagent_tools = []
    for tool_list in tool_dict.values():
        subagent_tools.extend(tool_list)

    # Track how many iteration answers existed before we start
    num_iteration_answers_before = len(
        run_context.context.aggregated_context.global_iteration_responses
    )

    # Use Answer infrastructure for robust LLM orchestration
    final_response = ""
    num_tool_calls = 0

    try:
        # Build system message for the subagent
        system_message = default_build_system_message(
            prompt_config=prompt_config,
            llm_config=llm.config,
            mem_callback=None,  # No memory callback for subagent
        )

        # Build user message
        user_message = default_build_user_message(
            user_query=query,
            prompt_config=prompt_config,
            files=[],
        )

        # Build prompt builder with empty history (subagent starts fresh)
        prompt_builder = AnswerPromptBuilder(
            user_message=user_message,
            system_message=system_message,
            message_history=[],  # Subagent has no conversation history
            llm_config=llm.config,
            raw_user_query=query,
            raw_user_uploaded_files=[],
        )

        # Create Answer instance to handle the subagent's response
        answer = Answer(
            prompt_builder=prompt_builder,
            answer_style_config=answer_style_config,
            llm=llm,
            fast_llm=fast_llm,
            force_use_tool=ForceUseTool(force_use=False, tool_name=""),
            persona=target_persona,
            rerank_settings=None,
            chat_session_id=run_context.context.chat_session_id,
            current_agent_message_id=run_context.context.message_id,
            tools=subagent_tools,
            db_session=run_context.context.run_dependencies.db_session,
            latest_query_files=[],
            is_connected=None,
            use_agentic_search=False,  # Subagent doesn't use agentic search
        )

        # Process the answer stream
        for stream_part in answer.processed_streamed_output:
            # Collect text content from the answer
            if hasattr(stream_part, "answer_piece") and stream_part.answer_piece:
                final_response += stream_part.answer_piece

        # Count tool calls by checking how many new iteration answers were added
        num_tool_calls = (
            len(run_context.context.aggregated_context.global_iteration_responses)
            - num_iteration_answers_before
        )

        # Now retroactively mark all IterationAnswers created during this subagent's
        # execution with the calling_agent_name
        for i in range(
            num_iteration_answers_before,
            len(run_context.context.aggregated_context.global_iteration_responses),
        ):
            iteration_answer = (
                run_context.context.aggregated_context.global_iteration_responses[i]
            )
            # Mark this as called by the subagent
            iteration_answer.calling_agent_name = target_persona.name

        # Generate final response if none was collected
        if not final_response:
            final_response = (
                f"Subagent {target_persona.name} completed {num_tool_calls} tool calls"
            )

    except Exception as e:
        logger.exception(f"Error executing subagent {target_persona.name}")
        final_response = f"Error executing subagent: {str(e)}"
        num_tool_calls = 0

    # Add the subagent delegation itself as an iteration answer
    run_context.context.aggregated_context.global_iteration_responses.append(
        IterationAnswer(
            tool=f"AgentTool_{target_persona.name}",
            tool_id=agent_tool_id,
            iteration_nr=index,
            parallelization_nr=0,
            question=query,
            reasoning=f"Delegated to {target_persona.name}: {query}",
            answer=final_response,
            cited_documents={},
            calling_agent_name=None,  # Primary agent is calling this
        )
    )

    return {
        "agent": target_persona.name,
        "status": "completed",
        "query": query,
        "tool_calls": num_tool_calls,
        "result": final_response,
    }


@function_tool
def call_agent(
    run_context: RunContextWrapper[ChatTurnContext],
    query: str,
    agent_persona_id: int,
) -> str:
    """
    Tool for delegating tasks to specialized subagents.

    Use this tool when you need to delegate a specific task to another agent
    that has specialized knowledge or capabilities. The subagent will have
    access to its own set of tools and will handle the task independently.

    Each tool call made by the subagent will be tracked with the subagent's
    name in the calling_agent_name field of the IterationAnswer.

    Args:
        query: The question or task to delegate to the subagent
        agent_persona_id: The ID of the persona/agent to call

    Returns:
        JSON string containing the delegation status and results
    """
    # Look up the agent tool from run_dependencies.tools
    agent_tool_id = -1  # Default fallback

    # Try to find the tool ID from available tools
    for tool in run_context.context.run_dependencies.tools:
        if hasattr(tool, "id") and hasattr(tool, "name"):
            # Check if this is an agent tool for the target persona
            if f"agent_{agent_persona_id}" in tool.name.lower():
                agent_tool_id = tool.id
                break

    result = _agent_tool_core(
        run_context=run_context,
        query=query,
        target_persona_id=agent_persona_id,
        agent_tool_id=agent_tool_id,
    )
    return json.dumps(result)


# Helper function to create IterationAnswers for subagent tool calls
def create_subagent_iteration_answer(
    run_context: RunContextWrapper[ChatTurnContext],
    calling_agent_name: str,
    tool_name: str,
    tool_id: int,
    iteration_nr: int,
    parallelization_nr: int,
    question: str,
    reasoning: str | None,
    answer: str,
    cited_documents: dict[int, InferenceSection] | None = None,
    claims: list[str] | None = None,
    is_web_fetch: bool = False,
    queries: list[str] | None = None,
    generated_images: list[Any] | None = None,
    additional_data: dict[str, str] | None = None,
) -> IterationAnswer:
    """
    Helper function to create an IterationAnswer for a tool call made by a subagent.

    This function should be called by tool implementations when they are being
    executed on behalf of a subagent (as indicated by context or parameters).
    """
    iteration_answer = IterationAnswer(
        tool=tool_name,
        tool_id=tool_id,
        iteration_nr=iteration_nr,
        parallelization_nr=parallelization_nr,
        question=question,
        reasoning=reasoning,
        answer=answer,
        cited_documents=cited_documents or {},
        claims=claims,
        is_web_fetch=is_web_fetch,
        queries=queries,
        generated_images=generated_images,
        additional_data=additional_data,
        calling_agent_name=calling_agent_name,  # Mark who called this tool
    )

    # Add to the global iteration responses
    run_context.context.aggregated_context.global_iteration_responses.append(
        iteration_answer
    )

    return iteration_answer


# Long description for the LLM to understand when to use this tool
AGENT_TOOL_LONG_DESCRIPTION = """
### Decision boundary
- Use this tool when you need to delegate a task to a specialized agent
- The subagent will have its own tools and capabilities
- Each subagent is designed for specific types of tasks
- The subagent's tool calls will be tracked separately in the iteration history

### When NOT to use
- For simple questions that you can answer directly
- When no specialized agent is available for the task
- For tasks that require coordination across multiple domains

### Usage hints
- Be specific in your query to the subagent
- The subagent will make its own tool calls which will be visible in the iteration history
- Each tool call made by the subagent will be marked with the subagent's name
- Review the subagent's work before incorporating it into your final answer
"""
