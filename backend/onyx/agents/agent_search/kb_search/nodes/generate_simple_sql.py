from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter
from sqlalchemy import text

from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.kb_search.states import SQLSimpleGenerationUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    dispatch_main_answer_stop_info,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.db.engine import get_session_with_current_tenant
from onyx.prompts.kg_prompts import SIMPLE_SQL_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def generate_simple_sql(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> SQLSimpleGenerationUpdate:
    """
    LangGraph node to start the agentic search process.
    """
    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.search_request.query
    entities_types_str = state.entities_types_str

    simple_sql_prompt = (
        SIMPLE_SQL_PROMPT.replace("---entities_types---", entities_types_str)
        .replace("---question---", question)
        .replace("---query_entities---", "\n".join(state.normalized_entities))
        .replace("---query_relationships---", "\n".join(state.normalized_relationships))
    )

    msg = [
        HumanMessage(
            content=simple_sql_prompt,
        )
    ]
    fast_llm = graph_config.tooling.primary_llm
    # Grader
    try:
        llm_response = run_with_timeout(
            15,
            fast_llm.invoke,
            prompt=msg,
            timeout_override=25,
            max_tokens=800,
        )

        cleaned_response = (
            str(llm_response.content).replace("```json\n", "").replace("\n```", "")
        )
        sql_statement = cleaned_response.split("SQL:")[1].strip()
        sql_statement = sql_statement.split(";")[0].strip() + ";"
        sql_statement = sql_statement.replace("sql", "").strip()

        reasoning = cleaned_response.split("SQL:")[0].strip()

    except Exception as e:
        logger.error(f"Error in strategy generation: {e}")
        raise e

    write_custom_event(
        "initial_agent_answer",
        AgentAnswerPiece(
            answer_piece=reasoning,
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    write_custom_event(
        "initial_agent_answer",
        AgentAnswerPiece(
            answer_piece=cleaned_response,
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    with get_session_with_current_tenant() as db_session:
        try:
            result = db_session.execute(text(sql_statement))
            # Handle scalar results (like COUNT)
            if sql_statement.upper().startswith("SELECT COUNT"):
                scalar_result = result.scalar()
                results = (
                    [{"count": int(scalar_result) - 1}]
                    if scalar_result is not None
                    else []
                )
            else:
                # Handle regular row results
                rows = result.fetchall()
                results = [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.error(f"Error executing SQL query: {e}")

            raise e

    write_custom_event(
        "initial_agent_answer",
        AgentAnswerPiece(
            answer_piece=str(results),
            level=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    dispatch_main_answer_stop_info(0, writer)

    return SQLSimpleGenerationUpdate(
        sql_query=sql_statement,
        results=results,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="generate simple sql",
                node_start_time=node_start_time,
            )
        ],
    )
