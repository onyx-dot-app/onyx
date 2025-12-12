import re
from datetime import datetime
from typing import Any
from typing import cast

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter
from sqlalchemy.orm import Session

from onyx.agents.agent_search.exploration.constants import AVERAGE_TOOL_COSTS
from onyx.agents.agent_search.exploration.constants import MAX_CHAT_HISTORY_MESSAGES
from onyx.agents.agent_search.exploration.dr_experimentation_prompts import (
    BASE_SYSTEM_MESSAGE_TEMPLATE,
)
from onyx.agents.agent_search.exploration.dr_experimentation_prompts import (
    PLAN_PROMPT_TEMPLATE,
)
from onyx.agents.agent_search.exploration.enums import DRPath
from onyx.agents.agent_search.exploration.enums import ResearchAnswerPurpose
from onyx.agents.agent_search.exploration.hackathon_functions import get_notifications
from onyx.agents.agent_search.exploration.hackathon_functions import (
    process_notifications,
)
from onyx.agents.agent_search.exploration.models import OrchestrationClarificationInfo
from onyx.agents.agent_search.exploration.models import OrchestrationPlan
from onyx.agents.agent_search.exploration.models import OrchestratorTool
from onyx.agents.agent_search.exploration.states import MainState
from onyx.agents.agent_search.exploration.states import OrchestrationSetup
from onyx.agents.agent_search.exploration.utils import get_chat_history_string
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.chat_utils import build_citation_map_from_numbers
from onyx.chat.chat_utils import saved_search_docs_from_llm_docs
from onyx.chat.memories import get_memories
from onyx.configs.agent_configs import TF_DR_TIMEOUT_SHORT
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import DocumentSourceDescription
from onyx.configs.constants import TMP_DRALPHA_PERSONA_NAME
from onyx.configs.exploration_research_configs import (
    EXPLORATION_TEST_USE_CALRIFIER_DEFAULT,
)
from onyx.configs.exploration_research_configs import (
    EXPLORATION_TEST_USE_CORPUS_HISTORY_DEFAULT,
)
from onyx.configs.exploration_research_configs import EXPLORATION_TEST_USE_PLAN_DEFAULT
from onyx.configs.exploration_research_configs import (
    EXPLORATION_TEST_USE_PLAN_UPDATES_DEFAULT,
)
from onyx.configs.exploration_research_configs import (
    EXPLORATION_TEST_USE_THINKING_DEFAULT,
)
from onyx.db.chat import create_search_doc_from_saved_search_doc
from onyx.db.connector import fetch_unique_document_sources
from onyx.db.models import SearchDoc
from onyx.db.models import Tool
from onyx.db.tools import get_tools
from onyx.db.users import get_user_cheat_sheet_context
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import InMemoryChatFile
from onyx.llm.utils import check_number_of_tokens
from onyx.llm.utils import get_max_input_tokens
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.prompts.chat_prompts import PROJECT_INSTRUCTIONS_SEPARATOR
from onyx.prompts.dr_prompts import DEFAULT_DR_SYSTEM_PROMPT
from onyx.prompts.dr_prompts import TOOL_DESCRIPTION
from onyx.prompts.prompt_template import PromptTemplate
from onyx.prompts.prompt_utils import handle_company_awareness
from onyx.prompts.prompt_utils import handle_memories
from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
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


_PLAN_INSTRUCTION_INSERTION = """   - Early on, the user MAY ask you to create a plan for the answer process. \
Think about the tools you have available and how you can use them, and then \
create a HIGH-LEVEL PLAN of how you want to approach the answer process."""


def _get_available_tools(
    db_session: Session,
    graph_config: GraphConfig,
    kg_enabled: bool,
    active_source_types: list[DocumentSource],
    use_clarifier: bool = False,
    use_thinking: bool = False,
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

    if use_thinking:
        available_tools[DRPath.THINKING.value] = OrchestratorTool(
            tool_id=102,
            name=DRPath.THINKING.value,
            llm_path=DRPath.THINKING.value,
            path=DRPath.THINKING,
            description="""This tool should be used if the next step is not particularly clear, \
or if you think you need to think through the original question and the questions and answers \
you have received so far in order to make a decision about what to do next AMONGST THE TOOLS AVAILABLE TO YOU \
IN THIS REQUEST! (Note: some tools described earlier may be excluded!).
If in doubt, use this tool. No action will be taken, just some reasoning will be done.""",
            metadata={},
            cost=0.0,
            tool_object=None,
        )

    if use_clarifier:
        available_tools[DRPath.CLARIFIER.value] = OrchestratorTool(
            tool_id=103,
            name=DRPath.CLARIFIER.value,
            llm_path=DRPath.CLARIFIER.value,
            path=DRPath.CLARIFIER,
            description="""This tool should be used ONLY if you need to have clarification on something IMPORTANT FROM \
the user. This can pertain to the original question or something you found out during the process so far.""",
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

    _EXPLORATION_TEST_USE_CALRIFIER = EXPLORATION_TEST_USE_CALRIFIER_DEFAULT
    _EXPLORATION_TEST_USE_PLAN = EXPLORATION_TEST_USE_PLAN_DEFAULT
    _EXPLORATION_TEST_USE_PLAN_UPDATES = EXPLORATION_TEST_USE_PLAN_UPDATES_DEFAULT
    _EXPLORATION_TEST_USE_CORPUS_HISTORY = EXPLORATION_TEST_USE_CORPUS_HISTORY_DEFAULT
    _EXPLORATION_TEST_USE_THINKING = EXPLORATION_TEST_USE_THINKING_DEFAULT

    _EXPLORATION_TEST_USE_PLAN = False

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

    db_session = graph_config.persistence.db_session

    original_question = graph_config.inputs.prompt_builder.raw_user_query

    # Perform a commit to ensure the message_id is set and saved
    db_session.commit()

    # get the connected tools and format for the Deep Research flow
    kg_enabled = graph_config.behavior.kg_config_settings.KG_ENABLED
    active_source_types = fetch_unique_document_sources(db_session)

    available_tools = _get_available_tools(
        db_session,
        graph_config,
        kg_enabled,
        active_source_types,
        use_clarifier=_EXPLORATION_TEST_USE_CALRIFIER,
        use_thinking=_EXPLORATION_TEST_USE_THINKING,
    )

    available_tool_descriptions_str = "\n -" + "\n -".join(
        [
            tool.name + ": " + tool.description
            for tool in available_tools.values()
            if tool.path != DRPath.CLOSER
        ]
    )

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

    continue_to_answer = True
    if original_question == "process_notifications" and user:
        process_notifications(db_session, llm=graph_config.tooling.fast_llm, user=user)
        continue_to_answer = False

        # Stream the notifications message
        write_custom_event(
            current_step_nr,
            MessageStart(content="", final_documents=None),
            writer,
        )
        write_custom_event(
            current_step_nr,
            MessageDelta(content="Done!"),
            writer,
        )
        write_custom_event(current_step_nr, SectionEnd(), writer)

    elif original_question == "get_notifications" and user:
        notifications = get_notifications(db_session, user)
        if notifications:
            # Stream the notifications message
            write_custom_event(
                current_step_nr,
                MessageStart(content="", final_documents=None),
                writer,
            )
            write_custom_event(
                current_step_nr,
                MessageDelta(content=notifications),
                writer,
            )
            write_custom_event(current_step_nr, SectionEnd(), writer)
        continue_to_answer = False

    if not continue_to_answer:
        return OrchestrationSetup(
            original_question=original_question,
            chat_history_string="",
            tools_used=[DRPath.END.value],
            query_list=[],
            iteration_nr=0,
            current_step_nr=current_step_nr,
        )

    memories = get_memories(user, db_session)
    assistant_system_prompt = handle_company_awareness(assistant_system_prompt)
    assistant_system_prompt = handle_memories(assistant_system_prompt, memories)

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

    current_step_nr += 1

    clarification = None

    message_history_for_continuation: list[SystemMessage | HumanMessage | AIMessage] = (
        []
    )

    if user is not None:
        original_cheat_sheet_context = get_user_cheat_sheet_context(
            user=user, db_session=db_session
        )

    if original_cheat_sheet_context:
        cheat_sheet_string = f"""\n\nHere is additional context learned that may inform the \
process (plan generation if applicable, reasoning, tool calls, etc.):\n{str(original_cheat_sheet_context)}\n###\n\n"""
    else:
        cheat_sheet_string = ""

    if _EXPLORATION_TEST_USE_PLAN:
        plan_instruction_insertion = _PLAN_INSTRUCTION_INSERTION
    else:
        plan_instruction_insertion = ""

    system_message = (
        BASE_SYSTEM_MESSAGE_TEMPLATE.replace(
            "---user_prompt---", assistant_system_prompt
        )
        .replace("---current_date---", datetime.now().strftime("%Y-%m-%d"))
        .replace(
            "---available_tool_descriptions_str---", available_tool_descriptions_str
        )
        .replace(
            "---active_source_types_descriptions_str---",
            active_source_type_descriptions_str,
        )
        .replace(
            "---cheat_sheet_string---",
            cheat_sheet_string,
        )
        .replace("---plan_instruction_insertion---", plan_instruction_insertion)
    )

    message_history_for_continuation.append(SystemMessage(content=system_message))
    message_history_for_continuation.append(
        HumanMessage(
            content=f"""Here is the questions to answer:\n{original_question}"""
        )
    )
    message_history_for_continuation.append(
        AIMessage(content="""How should I proceed to answer the question?""")
    )

    if _EXPLORATION_TEST_USE_PLAN:

        user_plan_instructions_prompt = """Think carefully how you want to address the question. You may use multiple iterations \
of tool calls, reasoning, etc.

Note:

    - the plan should be HIGH-LEVEL! Do not specify any specific tools, but think about what you want to learn in each iteration.
    - if the question is simple, one iteration may be enough.
    - DO NOT close with 'summarize...' etc as the last steps. Just focus on the information gathering steps.

"""

        plan_prompt = PLAN_PROMPT_TEMPLATE.replace(
            "---user_plan_instructions_prompt---", user_plan_instructions_prompt
        )

        message_history_for_continuation.append(HumanMessage(content=plan_prompt))

        plan_of_record = invoke_llm_json(
            llm=graph_config.tooling.primary_llm,
            prompt=message_history_for_continuation,
            schema=OrchestrationPlan,
            timeout_override=TF_DR_TIMEOUT_SHORT,
            # max_tokens=3000,
        )

        plan_string = f"""Here is how the answer process should be broken down: {plan_of_record.plan}"""

        message_history_for_continuation.append(AIMessage(content=plan_string))

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
        message_history_for_continuation=message_history_for_continuation,
        cheat_sheet_context=original_cheat_sheet_context,
        use_clarifier=_EXPLORATION_TEST_USE_CALRIFIER,
        use_thinking=_EXPLORATION_TEST_USE_THINKING,
        use_plan=_EXPLORATION_TEST_USE_PLAN,
        use_plan_updates=_EXPLORATION_TEST_USE_PLAN_UPDATES,
        use_corpus_history=_EXPLORATION_TEST_USE_CORPUS_HISTORY,
    )
