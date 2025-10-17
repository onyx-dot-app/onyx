import re
from datetime import datetime
from typing import Any
from typing import cast

from braintrust import traced
from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_content
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter
from sqlalchemy.orm import Session

from onyx.agents.agent_search.dr.constants import AVERAGE_TOOL_COSTS
from onyx.agents.agent_search.dr.constants import MAX_CHAT_HISTORY_MESSAGES
from onyx.agents.agent_search.dr.dr_prompt_builder import (
    get_dr_prompt_orchestration_templates,
)
from onyx.agents.agent_search.dr.enums import DRPath
from onyx.agents.agent_search.dr.enums import ResearchAnswerPurpose
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import ClarificationGenerationResponse
from onyx.agents.agent_search.dr.models import DecisionResponse
from onyx.agents.agent_search.dr.models import DRPromptPurpose
from onyx.agents.agent_search.dr.models import OrchestrationClarificationInfo
from onyx.agents.agent_search.dr.models import OrchestratorTool
from onyx.agents.agent_search.dr.process_llm_stream import (
    BasicSearchProcessedStreamResults,
)
from onyx.agents.agent_search.dr.process_llm_stream import process_llm_stream
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.states import OrchestrationSetup
from onyx.agents.agent_search.dr.utils import get_chat_history_string
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.llm import stream_llm_answer
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import run_with_timeout
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.agents.agent_search.utils import create_question_prompt
from onyx.chat.chat_utils import build_citation_map_from_numbers
from onyx.chat.chat_utils import saved_search_docs_from_llm_docs
from onyx.chat.memories import make_memories_callback
from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.citations_prompt import build_citations_system_message
from onyx.chat.prompt_builder.citations_prompt import build_citations_user_message
from onyx.chat.stream_processing.citation_processing import (
    normalize_square_bracket_citations_to_double_with_links,
)
from onyx.configs.agent_configs import TF_DR_TIMEOUT_LONG
from onyx.configs.agent_configs import TF_DR_TIMEOUT_SHORT
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import DocumentSourceDescription
from onyx.configs.constants import TMP_DRALPHA_PERSONA_NAME
from onyx.db.chat import create_search_doc_from_saved_search_doc
from onyx.db.chat import update_db_session_with_messages
from onyx.db.connector import fetch_unique_document_sources
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.models import SearchDoc
from onyx.db.models import Tool
from onyx.db.tools import get_tools
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import InMemoryChatFile
from onyx.kg.utils.extraction_utils import get_entity_types_str
from onyx.kg.utils.extraction_utils import get_relationship_types_str
from onyx.llm.utils import check_number_of_tokens
from onyx.llm.utils import get_max_input_tokens
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.prompts.chat_prompts import PROJECT_INSTRUCTIONS_SEPARATOR
from onyx.prompts.dr_prompts import ANSWER_PROMPT_WO_TOOL_CALLING
from onyx.prompts.dr_prompts import DECISION_PROMPT_W_TOOL_CALLING
from onyx.prompts.dr_prompts import DECISION_PROMPT_WO_TOOL_CALLING
from onyx.prompts.dr_prompts import DEFAULT_DR_SYSTEM_PROMPT
from onyx.prompts.dr_prompts import REPEAT_PROMPT
from onyx.prompts.dr_prompts import TOOL_DESCRIPTION
from onyx.prompts.prompt_template import PromptTemplate
from onyx.prompts.prompt_utils import handle_company_awareness
from onyx.prompts.prompt_utils import handle_memories
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.server.query_and_chat.streaming_models import StreamingType
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.knowledge_graph.knowledge_graph_tool import (
    KnowledgeGraphTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import (
    WebSearchTool,
)
from onyx.utils.b64 import get_image_type
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _format_tool_name(tool_name: str) -> str:
    """Convert tool name to LLM-friendly format."""
    name = tool_name.replace(" ", "_")
    # take care of camel case like GetAPIKey -> GET_API_KEY for LLM readability
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name)
    return name.upper()


def _get_available_tools(
    db_session: Session,
    graph_config: GraphConfig,
    kg_enabled: bool,
    active_source_types: list[DocumentSource],
) -> dict[str, OrchestratorTool]:

    available_tools: dict[str, OrchestratorTool] = {}

    kg_enabled = graph_config.behavior.kg_config_settings.KG_ENABLED
    persona = graph_config.inputs.persona

    if persona:
        include_kg = persona.name == TMP_DRALPHA_PERSONA_NAME and kg_enabled
    else:
        include_kg = False

    tool_dict: dict[int, Tool] = {
        tool.id: tool for tool in get_tools(db_session, only_enabled=True)
    }

    for tool in graph_config.tooling.tools:

        if not tool.is_available(db_session):
            logger.info(f"Tool {tool.name} is not available, skipping")
            continue

        tool_db_info = tool_dict.get(tool.id)
        if tool_db_info:
            incode_tool_id = tool_db_info.in_code_tool_id
        else:
            raise ValueError(f"Tool {tool.name} is not found in the database")

        if isinstance(tool, WebSearchTool):
            llm_path = DRPath.WEB_SEARCH.value
            path = DRPath.WEB_SEARCH
        elif isinstance(tool, SearchTool):
            llm_path = DRPath.INTERNAL_SEARCH.value
            path = DRPath.INTERNAL_SEARCH
        elif isinstance(tool, KnowledgeGraphTool) and include_kg:
            # TODO (chris): move this into the `is_available` check
            if len(active_source_types) == 0:
                logger.error(
                    "No active source types found, skipping Knowledge Graph tool"
                )
                continue
            llm_path = DRPath.KNOWLEDGE_GRAPH.value
            path = DRPath.KNOWLEDGE_GRAPH
        elif isinstance(tool, ImageGenerationTool):
            llm_path = DRPath.IMAGE_GENERATION.value
            path = DRPath.IMAGE_GENERATION
        elif incode_tool_id:
            # if incode tool id is found, it is a generic internal tool
            llm_path = DRPath.GENERIC_INTERNAL_TOOL.value
            path = DRPath.GENERIC_INTERNAL_TOOL
        else:
            # otherwise it is a custom tool
            llm_path = DRPath.GENERIC_TOOL.value
            path = DRPath.GENERIC_TOOL

        if path not in {DRPath.GENERIC_INTERNAL_TOOL, DRPath.GENERIC_TOOL}:
            description = TOOL_DESCRIPTION.get(path, tool.description)
            cost = AVERAGE_TOOL_COSTS[path]
        else:
            description = tool.description
            cost = 1.0

        tool_info = OrchestratorTool(
            tool_id=tool.id,
            name=tool.llm_name,
            llm_path=llm_path,
            path=path,
            description=description,
            metadata={},
            cost=cost,
            tool_object=tool,
        )

        # TODO: handle custom tools with same name as other tools (e.g., CLOSER)
        available_tools[tool.llm_name] = tool_info

    available_tool_paths = [tool.path for tool in available_tools.values()]

    # make sure KG isn't enabled without internal search
    if (
        DRPath.KNOWLEDGE_GRAPH in available_tool_paths
        and DRPath.INTERNAL_SEARCH not in available_tool_paths
    ):
        raise ValueError(
            "The Knowledge Graph is not supported without internal search tool"
        )

    # add CLOSER tool, which is always available
    available_tools[DRPath.CLOSER.value] = OrchestratorTool(
        tool_id=-1,
        name=DRPath.CLOSER.value,
        llm_path=DRPath.CLOSER.value,
        path=DRPath.CLOSER,
        description=TOOL_DESCRIPTION[DRPath.CLOSER],
        metadata={},
        cost=0.0,
        tool_object=None,
    )

    return available_tools


def _construct_uploaded_text_context(files: list[InMemoryChatFile]) -> str:
    """Construct the uploaded context from the files."""
    file_contents = []
    for file in files:
        if file.file_type in (
            ChatFileType.DOC,
            ChatFileType.PLAIN_TEXT,
            ChatFileType.CSV,
        ):
            file_contents.append(file.content.decode("utf-8"))
    if len(file_contents) > 0:
        return "Uploaded context:\n\n\n" + "\n\n".join(file_contents)
    return ""


def _construct_uploaded_image_context(
    files: list[InMemoryChatFile] | None = None,
    img_urls: list[str] | None = None,
    b64_imgs: list[str] | None = None,
) -> list[dict[str, Any]] | None:
    """Construct the uploaded image context from the files."""
    # Only include image files for user messages
    if files is None:
        return None

    img_files = [file for file in files if file.file_type == ChatFileType.IMAGE]

    img_urls = img_urls or []
    b64_imgs = b64_imgs or []

    if not (img_files or img_urls or b64_imgs):
        return None

    return cast(
        list[dict[str, Any]],
        [
            {
                "type": "image_url",
                "image_url": {
                    "url": (
                        f"data:{get_image_type_from_bytes(file.content)};"
                        f"base64,{file.to_base64()}"
                    ),
                },
            }
            for file in img_files
        ]
        + [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{get_image_type(b64_img)};base64,{b64_img}",
                },
            }
            for b64_img in b64_imgs
        ]
        + [
            {
                "type": "image_url",
                "image_url": {
                    "url": url,
                },
            }
            for url in img_urls
        ],
    )


def _get_existing_clarification_request(
    graph_config: GraphConfig,
) -> tuple[OrchestrationClarificationInfo, str, str] | None:
    """
    Returns the clarification info, original question, and updated chat history if
    a clarification request and response exists, otherwise returns None.
    """
    # check for clarification request and response in message history
    previous_raw_messages = graph_config.inputs.prompt_builder.raw_message_history

    if len(previous_raw_messages) == 0 or (
        previous_raw_messages[-1].research_answer_purpose
        != ResearchAnswerPurpose.CLARIFICATION_REQUEST
    ):
        return None

    # get the clarification request and response
    previous_messages = graph_config.inputs.prompt_builder.message_history
    last_message = previous_raw_messages[-1].message

    clarification = OrchestrationClarificationInfo(
        clarification_question=last_message.strip(),
        clarification_response=graph_config.inputs.prompt_builder.raw_user_query,
    )
    original_question = graph_config.inputs.prompt_builder.raw_user_query
    chat_history_string = "(No chat history yet available)"

    # get the original user query and chat history string before the original query
    # e.g., if history = [user query, assistant clarification request, user clarification response],
    # previous_messages = [user query, assistant clarification request], we want the user query
    for i, message in enumerate(reversed(previous_messages), 1):
        if (
            isinstance(message, HumanMessage)
            and message.content
            and isinstance(message.content, str)
        ):
            original_question = message.content
            chat_history_string = (
                get_chat_history_string(
                    graph_config.inputs.prompt_builder.message_history[:-i],
                    MAX_CHAT_HISTORY_MESSAGES,
                )
                or "(No chat history yet available)"
            )
            break

    return clarification, original_question, chat_history_string


def _persist_final_docs_and_citations(
    db_session: Session,
    context_llm_docs: list[Any] | None,
    full_answer: str | None,
) -> tuple[list[SearchDoc], dict[int, int] | None]:
    """Persist final documents from in-context docs and derive citation mapping.

    Returns the list of persisted `SearchDoc` records and an optional
    citation map translating inline [[n]] references to DB doc indices.
    """
    final_documents_db: list[SearchDoc] = []
    citations_map: dict[int, int] | None = None

    if not context_llm_docs:
        return final_documents_db, citations_map

    saved_search_docs = saved_search_docs_from_llm_docs(context_llm_docs)
    for saved_doc in saved_search_docs:
        db_doc = create_search_doc_from_saved_search_doc(saved_doc)
        db_session.add(db_doc)
        final_documents_db.append(db_doc)
    db_session.flush()

    cited_numbers: set[int] = set()
    try:
        # Match [[1]] or [[1, 2]] optionally followed by a link like ([[1]](http...))
        matches = re.findall(
            r"\[\[(\d+(?:,\s*\d+)*)\]\](?:\([^)]*\))?", full_answer or ""
        )
        for match in matches:
            for num_str in match.split(","):
                num = int(num_str.strip())
                cited_numbers.add(num)
    except Exception:
        cited_numbers = set()

    if cited_numbers and final_documents_db:
        translations = build_citation_map_from_numbers(
            cited_numbers=cited_numbers,
            db_docs=final_documents_db,
        )
        citations_map = translations or None

    return final_documents_db, citations_map


_ARTIFICIAL_ALL_ENCOMPASSING_TOOL = {
    "type": "function",
    "function": {
        "name": "run_any_knowledge_retrieval_and_any_action_tool",
        "description": "Use this tool to get ANY external information \
that is relevant to the question, or for any action to be taken, including image generation. In fact, \
ANY tool mentioned can be accessed through this generic tool. If in doubt, use this tool.",
        "parameters": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "The request to be made to the tool",
                },
            },
            "required": ["request"],
        },
    },
}


def clarifier(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> OrchestrationSetup:
    """
    Perform a quick search on the question as is and see whether a set of clarification
    questions is needed. For now this is based on the models
    """

    node_start_time = datetime.now()
    current_step_nr = 0

    graph_config = cast(GraphConfig, config["metadata"]["config"])

    llm_provider = graph_config.tooling.primary_llm.config.model_provider
    llm_model_name = graph_config.tooling.primary_llm.config.model_name

    llm_tokenizer = get_tokenizer(
        model_name=llm_model_name,
        provider_type=llm_provider,
    )

    max_input_tokens = get_max_input_tokens(
        model_name=llm_model_name,
        model_provider=llm_provider,
    )

    use_tool_calling_llm = graph_config.tooling.using_tool_calling_llm
    db_session = graph_config.persistence.db_session

    original_question = graph_config.inputs.prompt_builder.raw_user_query
    research_type = graph_config.behavior.research_type

    force_use_tool = graph_config.tooling.force_use_tool

    message_id = graph_config.persistence.message_id

    # Perform a commit to ensure the message_id is set and saved
    db_session.commit()

    # get the connected tools and format for the Deep Research flow
    kg_enabled = graph_config.behavior.kg_config_settings.KG_ENABLED
    db_session = graph_config.persistence.db_session
    active_source_types = fetch_unique_document_sources(db_session)

    available_tools = _get_available_tools(
        db_session, graph_config, kg_enabled, active_source_types
    )

    available_tool_descriptions_str = "\n -" + "\n -".join(
        [tool.description for tool in available_tools.values()]
    )

    kg_config = get_kg_config_settings()
    if kg_config.KG_ENABLED and kg_config.KG_EXPOSED:
        all_entity_types = get_entity_types_str(active=True)
        all_relationship_types = get_relationship_types_str(active=True)
    else:
        all_entity_types = ""
        all_relationship_types = ""

    # if not active_source_types:
    #    raise ValueError("No active source types found")

    active_source_types_descriptions = [
        DocumentSourceDescription[source_type] for source_type in active_source_types
    ]

    if len(active_source_types_descriptions) > 0:
        active_source_type_descriptions_str = "\n -" + "\n -".join(
            active_source_types_descriptions
        )
    else:
        active_source_type_descriptions_str = ""

    if graph_config.inputs.persona:
        assistant_system_prompt = PromptTemplate(
            graph_config.inputs.persona.system_prompt or DEFAULT_DR_SYSTEM_PROMPT
        ).build()
        if graph_config.inputs.persona.task_prompt:
            assistant_task_prompt = (
                "\n\nHere are more specifications from the user:\n\n"
                + PromptTemplate(graph_config.inputs.persona.task_prompt).build()
            )
        else:
            assistant_task_prompt = ""

    else:
        assistant_system_prompt = PromptTemplate(DEFAULT_DR_SYSTEM_PROMPT).build()
        assistant_task_prompt = ""

    if graph_config.inputs.project_instructions:
        assistant_system_prompt = (
            assistant_system_prompt
            + PROJECT_INSTRUCTIONS_SEPARATOR
            + graph_config.inputs.project_instructions
        )
    user = (
        graph_config.tooling.search_tool.user
        if graph_config.tooling.search_tool
        else None
    )
    memories_callback = make_memories_callback(user, db_session)
    assistant_system_prompt = handle_company_awareness(assistant_system_prompt)
    assistant_system_prompt = handle_memories(
        assistant_system_prompt, memories_callback
    )

    chat_history_string = (
        get_chat_history_string(
            graph_config.inputs.prompt_builder.message_history,
            MAX_CHAT_HISTORY_MESSAGES,
        )
        or "(No chat history yet available)"
    )

    uploaded_text_context = (
        _construct_uploaded_text_context(graph_config.inputs.files)
        if graph_config.inputs.files
        else ""
    )

    uploaded_context_tokens = check_number_of_tokens(
        uploaded_text_context, llm_tokenizer.encode
    )

    if uploaded_context_tokens > 0.5 * max_input_tokens:
        raise ValueError(
            f"Uploaded context is too long. {uploaded_context_tokens} tokens, "
            f"but for this model we only allow {0.5 * max_input_tokens} tokens for uploaded context"
        )

    uploaded_image_context = _construct_uploaded_image_context(
        graph_config.inputs.files
    )

    # Use project/search context docs if available to enable citation mapping
    context_llm_docs = getattr(
        graph_config.inputs.prompt_builder, "context_llm_docs", None
    )

    if not (force_use_tool and force_use_tool.force_use):

        if not use_tool_calling_llm or len(available_tools) == 1:
            if len(available_tools) > 1:
                decision_prompt = DECISION_PROMPT_WO_TOOL_CALLING.build(
                    question=original_question,
                    chat_history_string=chat_history_string,
                    uploaded_context=uploaded_text_context or "",
                    active_source_type_descriptions_str=active_source_type_descriptions_str,
                    available_tool_descriptions_str=available_tool_descriptions_str,
                )

                llm_decision = invoke_llm_json(
                    llm=graph_config.tooling.primary_llm,
                    prompt=create_question_prompt(
                        assistant_system_prompt,
                        decision_prompt,
                        uploaded_image_context=uploaded_image_context,
                    ),
                    schema=DecisionResponse,
                )
            else:
                # if there is only one tool (Closer), we don't need to decide. It's an LLM answer
                llm_decision = DecisionResponse(decision="LLM", reasoning="")

            if llm_decision.decision == "LLM":

                write_custom_event(
                    current_step_nr,
                    MessageStart(
                        content="",
                        final_documents=[],
                    ),
                    writer,
                )

                answer_prompt = ANSWER_PROMPT_WO_TOOL_CALLING.build(
                    question=original_question,
                    chat_history_string=chat_history_string,
                    uploaded_context=uploaded_text_context or "",
                    active_source_type_descriptions_str=active_source_type_descriptions_str,
                    available_tool_descriptions_str=available_tool_descriptions_str,
                )

                answer_tokens, _, _ = run_with_timeout(
                    TF_DR_TIMEOUT_LONG,
                    lambda: stream_llm_answer(
                        llm=graph_config.tooling.primary_llm,
                        prompt=create_question_prompt(
                            assistant_system_prompt,
                            answer_prompt + assistant_task_prompt,
                            uploaded_image_context=uploaded_image_context,
                        ),
                        event_name="basic_response",
                        writer=writer,
                        answer_piece=StreamingType.MESSAGE_DELTA.value,
                        agent_answer_level=0,
                        agent_answer_question_num=0,
                        agent_answer_type="agent_level_answer",
                        timeout_override=TF_DR_TIMEOUT_LONG,
                        ind=current_step_nr,
                        context_docs=None,
                        replace_citations=True,
                        max_tokens=None,
                    ),
                )

                write_custom_event(
                    current_step_nr,
                    SectionEnd(
                        type="section_end",
                    ),
                    writer,
                )
                current_step_nr += 1

                answer_str = cast(str, merge_content(*answer_tokens))

                write_custom_event(
                    current_step_nr,
                    OverallStop(),
                    writer,
                )

                update_db_session_with_messages(
                    db_session=db_session,
                    chat_message_id=message_id,
                    chat_session_id=graph_config.persistence.chat_session_id,
                    is_agentic=graph_config.behavior.use_agentic_search,
                    message=answer_str,
                    update_parent_message=True,
                    research_answer_purpose=ResearchAnswerPurpose.ANSWER,
                )
                db_session.commit()

                return OrchestrationSetup(
                    original_question=original_question,
                    chat_history_string="",
                    tools_used=[DRPath.END.value],
                    available_tools=available_tools,
                    query_list=[],
                    assistant_system_prompt=assistant_system_prompt,
                    assistant_task_prompt=assistant_task_prompt,
                )

        else:

            decision_prompt = DECISION_PROMPT_W_TOOL_CALLING.build(
                question=original_question,
                chat_history_string=chat_history_string,
                uploaded_context=uploaded_text_context or "",
                active_source_type_descriptions_str=active_source_type_descriptions_str,
            )

            if context_llm_docs:
                persona = graph_config.inputs.persona
                if persona is not None:
                    prompt_config = PromptConfig.from_model(persona)
                else:
                    prompt_config = PromptConfig(
                        system_prompt=assistant_system_prompt,
                        task_prompt="",
                        datetime_aware=True,
                    )

                system_prompt_to_use_content = build_citations_system_message(
                    prompt_config
                ).content
                system_prompt_to_use: str = cast(str, system_prompt_to_use_content)
                if graph_config.inputs.project_instructions:
                    system_prompt_to_use = (
                        system_prompt_to_use
                        + PROJECT_INSTRUCTIONS_SEPARATOR
                        + graph_config.inputs.project_instructions
                    )
                user_prompt_to_use = build_citations_user_message(
                    user_query=original_question,
                    files=[],
                    prompt_config=prompt_config,
                    context_docs=context_llm_docs,
                    all_doc_useful=False,
                    history_message=chat_history_string,
                    context_type="user files",
                ).content
            else:
                system_prompt_to_use = assistant_system_prompt
                user_prompt_to_use = decision_prompt + assistant_task_prompt

            @traced(name="clarifier stream and process", type="llm")
            def stream_and_process() -> BasicSearchProcessedStreamResults:
                stream = graph_config.tooling.primary_llm.stream(
                    prompt=create_question_prompt(
                        cast(str, system_prompt_to_use),
                        cast(str, user_prompt_to_use),
                        uploaded_image_context=uploaded_image_context,
                    ),
                    tools=([_ARTIFICIAL_ALL_ENCOMPASSING_TOOL]),
                    tool_choice=(None),
                    structured_response_format=graph_config.inputs.structured_response_format,
                )
                return process_llm_stream(
                    messages=stream,
                    should_stream_answer=True,
                    writer=writer,
                    ind=0,
                    final_search_results=context_llm_docs,
                    displayed_search_results=context_llm_docs,
                    generate_final_answer=True,
                    chat_message_id=str(graph_config.persistence.chat_session_id),
                )

            full_response = stream_and_process()
            if len(full_response.ai_message_chunk.tool_calls) == 0:

                if isinstance(full_response.full_answer, str):
                    full_answer = (
                        normalize_square_bracket_citations_to_double_with_links(
                            full_response.full_answer
                        )
                    )
                else:
                    full_answer = None

                # Persist final documents and derive citations when using in-context docs
                final_documents_db, citations_map = _persist_final_docs_and_citations(
                    db_session=db_session,
                    context_llm_docs=context_llm_docs,
                    full_answer=full_answer,
                )

                update_db_session_with_messages(
                    db_session=db_session,
                    chat_message_id=message_id,
                    chat_session_id=graph_config.persistence.chat_session_id,
                    is_agentic=graph_config.behavior.use_agentic_search,
                    message=full_answer,
                    token_count=len(llm_tokenizer.encode(full_answer or "")),
                    citations=citations_map,
                    final_documents=final_documents_db or None,
                    update_parent_message=True,
                    research_answer_purpose=ResearchAnswerPurpose.ANSWER,
                )

                db_session.commit()

                return OrchestrationSetup(
                    original_question=original_question,
                    chat_history_string="",
                    tools_used=[DRPath.END.value],
                    query_list=[],
                    available_tools=available_tools,
                    assistant_system_prompt=assistant_system_prompt,
                    assistant_task_prompt=assistant_task_prompt,
                )

        # Continue, as external knowledge is required.

    current_step_nr += 1

    clarification = None

    if research_type == ResearchType.DEEP:
        result = _get_existing_clarification_request(graph_config)
        if result is not None:
            clarification, original_question, chat_history_string = result
        else:
            # generate clarification questions if needed
            chat_history_string = (
                get_chat_history_string(
                    graph_config.inputs.prompt_builder.message_history,
                    MAX_CHAT_HISTORY_MESSAGES,
                )
                or "(No chat history yet available)"
            )

            base_clarification_prompt = get_dr_prompt_orchestration_templates(
                DRPromptPurpose.CLARIFICATION,
                research_type,
                entity_types_string=all_entity_types,
                relationship_types_string=all_relationship_types,
                available_tools=available_tools,
            )
            clarification_prompt = base_clarification_prompt.build(
                question=original_question,
                chat_history_string=chat_history_string,
            )

            try:
                clarification_response = invoke_llm_json(
                    llm=graph_config.tooling.primary_llm,
                    prompt=create_question_prompt(
                        assistant_system_prompt,
                        clarification_prompt,
                        uploaded_image_context=uploaded_image_context,
                    ),
                    schema=ClarificationGenerationResponse,
                    timeout_override=TF_DR_TIMEOUT_SHORT,
                    # max_tokens=1500,
                )
            except Exception as e:
                logger.error(f"Error in clarification generation: {e}")
                raise e

            if (
                clarification_response.clarification_needed
                and clarification_response.clarification_question
            ):
                clarification = OrchestrationClarificationInfo(
                    clarification_question=clarification_response.clarification_question,
                    clarification_response=None,
                )
                write_custom_event(
                    current_step_nr,
                    MessageStart(
                        content="",
                        final_documents=None,
                    ),
                    writer,
                )

                repeat_prompt = REPEAT_PROMPT.build(
                    original_information=clarification_response.clarification_question
                )

                _, _, _ = run_with_timeout(
                    TF_DR_TIMEOUT_LONG,
                    lambda: stream_llm_answer(
                        llm=graph_config.tooling.primary_llm,
                        prompt=repeat_prompt,
                        event_name="basic_response",
                        writer=writer,
                        agent_answer_level=0,
                        agent_answer_question_num=0,
                        agent_answer_type="agent_level_answer",
                        timeout_override=TF_DR_TIMEOUT_LONG,
                        answer_piece=StreamingType.MESSAGE_DELTA.value,
                        ind=current_step_nr,
                        # max_tokens=None,
                    ),
                )

                write_custom_event(
                    current_step_nr,
                    SectionEnd(
                        type="section_end",
                    ),
                    writer,
                )

                write_custom_event(
                    1,
                    OverallStop(),
                    writer,
                )

                update_db_session_with_messages(
                    db_session=db_session,
                    chat_message_id=message_id,
                    chat_session_id=graph_config.persistence.chat_session_id,
                    is_agentic=graph_config.behavior.use_agentic_search,
                    message=clarification_response.clarification_question,
                    update_parent_message=True,
                    research_type=research_type,
                    research_answer_purpose=ResearchAnswerPurpose.CLARIFICATION_REQUEST,
                )

                db_session.commit()

    else:
        chat_history_string = (
            get_chat_history_string(
                graph_config.inputs.prompt_builder.message_history,
                MAX_CHAT_HISTORY_MESSAGES,
            )
            or "(No chat history yet available)"
        )

    if (
        clarification
        and clarification.clarification_question
        and clarification.clarification_response is None
    ):

        update_db_session_with_messages(
            db_session=db_session,
            chat_message_id=message_id,
            chat_session_id=graph_config.persistence.chat_session_id,
            is_agentic=graph_config.behavior.use_agentic_search,
            message=clarification.clarification_question,
            update_parent_message=True,
            research_type=research_type,
            research_answer_purpose=ResearchAnswerPurpose.CLARIFICATION_REQUEST,
        )

        db_session.commit()

        next_tool = DRPath.END.value
    else:
        next_tool = DRPath.ORCHESTRATOR.value

    return OrchestrationSetup(
        original_question=original_question,
        chat_history_string=chat_history_string,
        tools_used=[next_tool],
        query_list=[],
        iteration_nr=0,
        current_step_nr=current_step_nr,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="clarifier",
                node_start_time=node_start_time,
            )
        ],
        clarification=clarification,
        available_tools=available_tools,
        active_source_types=active_source_types,
        active_source_types_descriptions="\n".join(active_source_types_descriptions),
        assistant_system_prompt=assistant_system_prompt,
        assistant_task_prompt=assistant_task_prompt,
        uploaded_test_context=uploaded_text_context,
        uploaded_image_context=uploaded_image_context,
    )
