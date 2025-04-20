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
    get_langgraph_node_log_string,
)
from onyx.db.engine import get_session_with_current_tenant
from onyx.llm.interfaces import LLM
from onyx.prompts.kg_prompts import SIMPLE_SQL_PROMPT
from onyx.prompts.kg_prompts import SQL_AGGREGATION_REMOVAL_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def _sql_is_aggregate_query(sql_statement: str) -> bool:
    return any(
        agg_func in sql_statement.upper()
        for agg_func in ["COUNT(", "MAX(", "MIN(", "AVG(", "SUM("]
    )


def _remove_aggregation(sql_statement: str, llm: LLM) -> str:
    """
    Remove aggregate functions from the SQL statement.
    """

    sql_aggregation_removal_prompt = SQL_AGGREGATION_REMOVAL_PROMPT.replace(
        "---sql_statement---", sql_statement
    )

    msg = [
        HumanMessage(
            content=sql_aggregation_removal_prompt,
        )
    ]

    # Grader
    try:
        llm_response = run_with_timeout(
            15,
            llm.invoke,
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

    except Exception as e:
        logger.error(f"Error in strategy generation: {e}")
        raise e

    return sql_statement


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
    state.strategy
    state.output_format

    simple_sql_prompt = (
        SIMPLE_SQL_PROMPT.replace("---entities_types---", entities_types_str)
        .replace("---question---", question)
        .replace("---query_entities---", "\n".join(state.query_graph_entities))
        .replace(
            "---query_relationships---", "\n".join(state.query_graph_relationships)
        )
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

        # reasoning = cleaned_response.split("SQL:")[0].strip()

    except Exception as e:
        logger.error(f"Error in strategy generation: {e}")
        raise e

    if _sql_is_aggregate_query(sql_statement):
        individualized_sql_query = _remove_aggregation(sql_statement, llm=fast_llm)
    else:
        individualized_sql_query = None

    # write_custom_event(
    #     "initial_agent_answer",
    #     AgentAnswerPiece(
    #         answer_piece=reasoning,
    #         level=0,
    #         level_question_num=0,
    #         answer_type="agent_level_answer",
    #     ),
    #     writer,
    # )

    # write_custom_event(
    #     "initial_agent_answer",
    #     AgentAnswerPiece(
    #         answer_piece=cleaned_response,
    #         level=0,
    #         level_question_num=0,
    #         answer_type="agent_level_answer",
    #     ),
    #     writer,
    # )

    # CRITICAL: EXECUTION OF SQL NEEDS TO ME MADE SAFE FOR PRODUCTION
    with get_session_with_current_tenant() as db_session:
        try:
            result = db_session.execute(text(sql_statement))
            # Handle scalar results (like COUNT)
            if sql_statement.upper().startswith("SELECT COUNT"):
                scalar_result = result.scalar()
                query_results = (
                    [{"count": int(scalar_result) - 1}]
                    if scalar_result is not None
                    else []
                )
            else:
                # Handle regular row results
                rows = result.fetchall()
                query_results = [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.error(f"Error executing SQL query: {e}")

            raise e

    if (
        individualized_sql_query is not None
        and individualized_sql_query != sql_statement
    ):
        with get_session_with_current_tenant() as db_session:
            try:
                result = db_session.execute(text(individualized_sql_query))
                # Handle scalar results (like COUNT)
                if individualized_sql_query.upper().startswith("SELECT COUNT"):
                    scalar_result = result.scalar()
                    individualized_query_results = (
                        [{"count": int(scalar_result) - 1}]
                        if scalar_result is not None
                        else []
                    )
                else:
                    # Handle regular row results
                    rows = result.fetchall()
                    individualized_query_results = [dict(row._mapping) for row in rows]
            except Exception as e:
                # No stopping here, the individualized SQL query is not mandatory
                logger.error(f"Error executing Individualized SQL query: {e}")
                individualized_query_results = None

    else:
        individualized_query_results = None

    # write_custom_event(
    #     "initial_agent_answer",
    #     AgentAnswerPiece(
    #         answer_piece=str(query_results),
    #         level=0,
    #         answer_type="agent_level_answer",
    #     ),
    #     writer,
    # )

    # dispatch_main_answer_stop_info(0, writer)

    logger.info(f"query_results: {query_results}")

    return SQLSimpleGenerationUpdate(
        sql_query=sql_statement,
        query_results=query_results,
        individualized_sql_query=individualized_sql_query,
        individualized_query_results=individualized_query_results,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="generate simple sql",
                node_start_time=node_start_time,
            )
        ],
    )
