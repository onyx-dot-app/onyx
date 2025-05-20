import json
from pathlib import Path
from typing import Optional

from langgraph.types import StreamWriter
from pydantic import BaseModel
from pydantic import ValidationError

from onyx.agents.agent_search.basic.utils import process_llm_stream
from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.chat.prompt_builder.answer_prompt_builder import default_build_system_message
from onyx.chat.prompt_builder.answer_prompt_builder import default_build_user_message
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.persona import get_persona_by_id
from onyx.llm.factory import get_llms_for_persona
from onyx.llm.interfaces import LLM
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.utils import explicit_tool_calling_supported
from onyx.utils.logger import setup_logger

logger = setup_logger()


class GroundTruth(BaseModel):
    doc_source: str
    doc_link: str


class TestQuery(BaseModel):
    question: str
    question_search: Optional[str] = None
    ground_truth: list[GroundTruth] = []
    categories: list[str] = []


def load_test_queries() -> list[TestQuery]:
    """
    Loads the test queries from the test_queries.json file.
    If `question_search` is missing, it will use the tool-calling LLM to generate it.
    """
    # open test queries file
    current_dir = Path(__file__).parent
    test_queries_path = current_dir / "test_queries.json"
    logger.info(f"Loading test queries from {test_queries_path}")
    if not test_queries_path.exists():
        raise FileNotFoundError(f"Test queries file not found at {test_queries_path}")
    with test_queries_path.open("r") as f:
        test_queries_raw: list[dict] = json.load(f)

    # setup llm for question_search generation
    with get_session_with_current_tenant() as db_session:
        persona = get_persona_by_id(DEFAULT_PERSONA_ID, None, db_session)
        llm, _ = get_llms_for_persona(persona)
        prompt_config = PromptConfig.from_model(persona.prompts[0])
        tool_definition = SearchToolOverride().tool_definition()

        tool_call_supported = explicit_tool_calling_supported(
            llm.config.model_provider, llm.config.model_name
        )
        if not tool_call_supported:
            logger.warning(
                "Tool calling is not supported for the current LLM. "
                "The original question will be used as the question_search."
            )

    # validate keys and generate question_search if missing
    test_queries: list[TestQuery] = []
    for query_raw in test_queries_raw:
        try:
            test_query = TestQuery(**query_raw)
        except ValidationError as e:
            logger.error(f"Incorrectly formatted query: {e}")
            continue

        if test_query.question_search is None:
            if tool_call_supported:
                test_query.question_search = _modify_one_query(
                    query=test_query.question,
                    llm=llm,
                    prompt_config=prompt_config,
                    tool_definition=tool_definition,
                )
            else:
                test_query.question_search = test_query.question
        test_queries.append(test_query)

    return test_queries


def export_test_queries(test_queries: list[TestQuery], export_path: Path) -> None:
    """Exports the test queries to a JSON file."""
    logger.info(f"Exporting test queries to {export_path}")
    with export_path.open("w") as f:
        json.dump(
            [query.model_dump() for query in test_queries],
            f,
            indent=4,
        )


class SearchToolOverride(SearchTool):
    def __init__(self) -> None:
        # do nothing, the tool_definition function doesn't require variables to be initialized
        pass


warned = False


def _modify_one_query(
    query: str,
    llm: LLM,
    prompt_config: PromptConfig,
    tool_definition: dict,
    writer: StreamWriter = lambda _: None,
) -> str:
    global warned
    if not warned:
        logger.warning(
            "Generating question_search. If you do not save the question_search, "
            "it will be generated again on the next run, potentially altering the search results."
        )
        warned = True

    prompt_builder = AnswerPromptBuilder(
        user_message=default_build_user_message(
            user_query=query,
            prompt_config=prompt_config,
            files=[],
            single_message_history=None,
        ),
        system_message=default_build_system_message(prompt_config, llm.config),
        message_history=[],
        llm_config=llm.config,
        raw_user_query=query,
        raw_user_uploaded_files=[],
        single_message_history=None,
    )
    prompt = prompt_builder.build()

    stream = llm.stream(
        prompt=prompt,
        tools=[tool_definition],
        tool_choice="required",
        structured_response_format=None,
    )
    tool_message = process_llm_stream(
        messages=stream,
        should_stream_answer=False,
        writer=writer,
    )
    return (
        tool_message.tool_calls[0]["args"]["query"]
        if tool_message.tool_calls
        else query
    )
