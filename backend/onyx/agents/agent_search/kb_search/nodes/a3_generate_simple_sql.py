from datetime import datetime
from typing import Any
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter
from sqlalchemy import text

from onyx.agents.agent_search.kb_search.graph_utils import get_near_empty_step_results
from onyx.agents.agent_search.kb_search.states import KGAnswerStrategy
from onyx.agents.agent_search.kb_search.states import KGRelationshipDetection
from onyx.agents.agent_search.kb_search.states import KGSearchType
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.kb_search.states import SQLSimpleGenerationUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.utils import create_question_prompt
from onyx.configs.kg_configs import KG_MAX_DEEP_SEARCH_RESULTS
from onyx.configs.kg_configs import KG_SQL_GENERATION_MAX_TOKENS
from onyx.configs.kg_configs import KG_SQL_GENERATION_TIMEOUT
from onyx.configs.kg_configs import KG_SQL_GENERATION_TIMEOUT_OVERRIDE
from onyx.configs.kg_configs import KG_TEMP_ALLOWED_DOCS_VIEW_NAME_PREFIX
from onyx.configs.kg_configs import KG_TEMP_KG_ENTITIES_VIEW_NAME_PREFIX
from onyx.configs.kg_configs import KG_TEMP_KG_RELATIONSHIPS_VIEW_NAME_PREFIX
from onyx.db.engine.sql_engine import get_db_readonly_user_session_with_current_tenant
from onyx.db.kg_temp_view import drop_views
from onyx.llm.interfaces import LLM
from onyx.prompts.kg_prompts import ENTITY_SOURCE_DETECTION_PROMPT
from onyx.prompts.kg_prompts import ENTITY_TABLE_DESCRIPTION
from onyx.prompts.kg_prompts import RELATIONSHIP_TABLE_DESCRIPTION
from onyx.prompts.kg_prompts import SIMPLE_ENTITY_SQL_PROMPT
from onyx.prompts.kg_prompts import SIMPLE_SQL_ERROR_FIX_PROMPT
from onyx.prompts.kg_prompts import SIMPLE_SQL_PROMPT
from onyx.prompts.kg_prompts import SOURCE_DETECTION_PROMPT
from onyx.prompts.kg_prompts import SQL_INSTRUCTIONS_ENTITY_PROMPT
from onyx.prompts.kg_prompts import SQL_INSTRUCTIONS_RELATIONSHIP_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout


logger = setup_logger()


def _raise_error_if_sql_fails_problem_test(
    sql_statement: str, relationship_view_name: str, entity_view_name: str | None
) -> bool:
    """
    Check if the SQL statement is valid.
    """

    if entity_view_name is None:
        raise ValueError("entity_view_name is not set for sql_statement")

    authorized_user_specification = relationship_view_name[
        len(KG_TEMP_KG_RELATIONSHIPS_VIEW_NAME_PREFIX) :
    ]

    # remove the proper relationship and entity view names
    base_sql_statement = sql_statement.replace(relationship_view_name, " ").replace(
        entity_view_name, " "
    )

    # check whether other non-authorized relationship or entity viewnames are in sql_statement
    if any(
        view_name in base_sql_statement
        for view_name in [
            KG_TEMP_ALLOWED_DOCS_VIEW_NAME_PREFIX,
            KG_TEMP_KG_RELATIONSHIPS_VIEW_NAME_PREFIX,
            KG_TEMP_KG_ENTITIES_VIEW_NAME_PREFIX,
        ]
    ):
        raise ValueError(
            f"SQL statement would attempt to access unauthorized views: {sql_statement} for \
user specification {authorized_user_specification}"
        )

    # check whether the sql statement would attempt to do unauthorized operations
    # (the restrivtive db priviledges would preclude this anyway, but we check for safety and reporting)
    UNAUTHORIZED_SQL_OPERATIONS = [
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "CREATE ",
        "DROP ",
        "ALTER ",
        "TRUNCATE ",
        "RENAME ",
        "GRANT ",
        "REVOKE ",
        "DENY ",
    ]

    if any(
        operation.upper() in base_sql_statement.upper()
        for operation in UNAUTHORIZED_SQL_OPERATIONS
    ):
        raise ValueError(
            f"SQL statement would attempt to do unauthorized operations: {sql_statement}"
        )

    return True


def _build_entity_explanation_str(entity_normalization_map: dict[str, str]) -> str:
    """
    Build a string of contextualized entities to avoid the model not being aware of
    what eg ACCOUNT::SF_8254Hs means as a normalized entity
    """
    entity_explanation_components = []
    for entity, normalized_entity in entity_normalization_map.items():
        entity_explanation_components.append(f"  - {entity} -> {normalized_entity}")
    return "\n".join(entity_explanation_components)


def _sql_is_aggregate_query(sql_statement: str) -> bool:
    return any(
        agg_func in sql_statement.upper()
        for agg_func in ["COUNT(", "MAX(", "MIN(", "AVG(", "SUM(", "GROUP BY"]
    )


def _run_sql(
    sql_statement: str, rel_temp_view: str, ent_temp_view: str
) -> list[dict[str, Any]]:
    # check sql, just in case
    _raise_error_if_sql_fails_problem_test(sql_statement, rel_temp_view, ent_temp_view)
    with get_db_readonly_user_session_with_current_tenant() as db_session:
        result = db_session.execute(text(sql_statement))
        # Handle scalar results (like COUNT)
        if sql_statement.upper().startswith("SELECT COUNT"):
            scalar_result = result.scalar()
            return [{"count": int(scalar_result)}] if scalar_result is not None else []
        # Handle regular row results
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]


def _get_source_documents(
    sql_statement: str,
    llm: LLM,
    focus: str | None,
    allowed_docs_view_name: str,
    kg_relationships_view_name: str,
) -> str | None:
    """
    Generate SQL to retrieve source documents based on the input sql statement.
    """

    base_prompt = (
        SOURCE_DETECTION_PROMPT
        if (focus == KGRelationshipDetection.RELATIONSHIPS.value or focus is None)
        else ENTITY_SOURCE_DETECTION_PROMPT
    )

    source_detection_prompt = base_prompt.replace(
        "---original_sql_statement---", sql_statement
    )

    msg = [
        HumanMessage(
            content=source_detection_prompt,
        )
    ]

    cleaned_response: str | None = None
    try:
        llm_response = run_with_timeout(
            KG_SQL_GENERATION_TIMEOUT,
            llm.invoke,
            prompt=msg,
            timeout_override=KG_SQL_GENERATION_TIMEOUT_OVERRIDE,
            max_tokens=KG_SQL_GENERATION_MAX_TOKENS,
        )

        cleaned_response = (
            str(llm_response.content).replace("```json\n", "").replace("\n```", "")
        )
        sql_statement = cleaned_response.split("<sql>")[1].strip()
        sql_statement = sql_statement.split("</sql>")[0].strip()

    except Exception as e:
        error_msg = f"Could not generate source documents SQL: {e}"
        if cleaned_response:
            error_msg += f". Original model response: {cleaned_response}"

        logger.error(error_msg)

        return None

    return sql_statement


def generate_simple_sql(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> SQLSimpleGenerationUpdate:
    """
    LangGraph node to start the agentic search process.
    """

    _KG_STEP_NR = 3

    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = state.question
    entities_types_str = state.entities_types_str
    relationship_types_str = state.relationship_types_str

    single_doc_id = state.single_doc_id

    if state.kg_doc_temp_view_name is None:
        raise ValueError("kg_doc_temp_view_name is not set")
    if state.kg_rel_temp_view_name is None:
        raise ValueError("kg_rel_temp_view_name is not set")
    if state.kg_entity_temp_view_name is None:
        raise ValueError("kg_entity_temp_view_name is not set")

    sql_statement_display: str | None = None

    ## STEP 3 - articulate goals

    if graph_config.tooling.search_tool is None:
        raise ValueError("Search tool is not set")
    elif graph_config.tooling.search_tool.user is None:
        raise ValueError("User is not set")
    else:
        user_email = graph_config.tooling.search_tool.user.email
        user_name = user_email.split("@")[0]

    if state.search_type == KGSearchType.SQL and single_doc_id:

        # If single doc id already identified, we do not need to go through the KG
        # query cycle, saving a lot of time.

        main_sql_statement: str | None = None
        query_results: list[dict[str, Any]] | None = None
        source_documents_sql: str | None = None
        source_document_results: list[str] | None = [single_doc_id]
        reasoning: str | None = (
            f"A KG query was not required as the source document was already identified: {single_doc_id}"
        )

        step_answer = f"Source document already identified: {single_doc_id}"

    elif state.search_type == KGSearchType.SEARCH:
        # If we do a filtered search, then we do not need to go through the SQL
        # generation process.

        main_sql_statement = None
        query_results = None
        source_documents_sql = None
        source_document_results = None
        reasoning = "A KG query was not required as we will use a filtered search."

        step_answer = "Filtered search will be used."

    else:
        # If no single doc id already identified, we need to go through the KG
        # query cycle, including generating the SQL for the answer and the sources

        # Build prompt

        # First, create string of contextualized entities to avoid the model not
        # being aware of what eg ACCOUNT::SF_8254Hs means as a normalized entity

        # TODO: restructure with broader node rework

        entity_explanation_str = _build_entity_explanation_str(
            state.entity_normalization_map
        )

        doc_temp_view = state.kg_doc_temp_view_name
        rel_temp_view = state.kg_rel_temp_view_name
        ent_temp_view = state.kg_entity_temp_view_name

        if state.query_type == KGRelationshipDetection.NO_RELATIONSHIPS.value:
            simple_sql_prompt = (
                SIMPLE_ENTITY_SQL_PROMPT.replace(
                    "---entity_types---", entities_types_str
                )
                .replace("---question---", question)
                .replace("---entity_explanation_string---", entity_explanation_str)
                .replace(
                    "---query_entities_with_attributes---",
                    "\n".join(state.query_graph_entities_w_attributes),
                )
                .replace("---today_date---", datetime.now().strftime("%Y-%m-%d"))
                .replace("---user_name---", f"EMPLOYEE:{user_name}")
            )

            additional_sql_instruction_prompt = SQL_INSTRUCTIONS_ENTITY_PROMPT
        else:
            simple_sql_prompt = (
                SIMPLE_SQL_PROMPT.replace("---entity_types---", entities_types_str)
                .replace("---relationship_types---", relationship_types_str)
                .replace("---question---", question)
                .replace("---entity_explanation_string---", entity_explanation_str)
                .replace(
                    "---query_entities_with_attributes---",
                    "\n".join(state.query_graph_entities_w_attributes),
                )
                .replace(
                    "---query_relationships---",
                    "\n".join(state.query_graph_relationships),
                )
                .replace("---today_date---", datetime.now().strftime("%Y-%m-%d"))
                .replace("---user_name---", f"EMPLOYEE:{user_name}")
            )

            additional_sql_instruction_prompt = SQL_INSTRUCTIONS_RELATIONSHIP_PROMPT

        msg = create_question_prompt(
            additional_sql_instruction_prompt,
            simple_sql_prompt,
        )

        primary_llm = graph_config.tooling.primary_llm
        try:
            llm_response = run_with_timeout(
                KG_SQL_GENERATION_TIMEOUT,
                primary_llm.invoke,
                prompt=msg,
                timeout_override=KG_SQL_GENERATION_TIMEOUT_OVERRIDE,
                max_tokens=KG_SQL_GENERATION_MAX_TOKENS,
            )

            cleaned_response = (
                str(llm_response.content).replace("```json\n", "").replace("\n```", "")
            )
            sql_statement = (
                cleaned_response.split("<sql>")[1].split("</sql>")[0].strip()
            )
            sql_statement = sql_statement.split(";")[0].strip() + ";"
            sql_statement = sql_statement.replace("sql", "").strip()
            sql_statement = sql_statement.replace("relationship_table", rel_temp_view)
            sql_statement = sql_statement.replace("entity_table", ent_temp_view)

            reasoning = (
                cleaned_response.split("<reasoning>")[1]
                .strip()
                .split("</reasoning>")[0]
            )

        except Exception as e:
            # TODO: restructure with broader node rework
            logger.error(f"Error in SQL generation: {e}")

            drop_views(
                allowed_docs_view_name=doc_temp_view,
                kg_relationships_view_name=rel_temp_view,
                kg_entity_view_name=ent_temp_view,
            )
            raise e

        # display sql statement with view names replaced by general view names
        sql_statement_display = sql_statement.replace(
            state.kg_doc_temp_view_name, "<your_allowed_docs_view_name>"
        )
        sql_statement_display = sql_statement_display.replace(
            state.kg_rel_temp_view_name, "<your_relationship_view_name>"
        )
        sql_statement_display = sql_statement_display.replace(
            state.kg_entity_temp_view_name, "<your_entity_view_name>"
        )

        logger.debug(f"A3 - sql_statement after correction: {sql_statement_display}")

        # Get SQL for source documents

        source_documents_sql = None

        if (
            state.query_type == KGRelationshipDetection.RELATIONSHIPS.value
            or _sql_is_aggregate_query(sql_statement)
        ):
            source_documents_sql = _get_source_documents(
                sql_statement,
                llm=primary_llm,
                focus=state.query_type,
                allowed_docs_view_name=doc_temp_view,
                kg_relationships_view_name=rel_temp_view,
            )

            if source_documents_sql and ent_temp_view:
                source_documents_sql = source_documents_sql.replace(
                    "entity_table", ent_temp_view
                )

            if source_documents_sql and rel_temp_view:
                source_documents_sql = source_documents_sql.replace(
                    "relationship_table", rel_temp_view
                )

            if source_documents_sql:
                source_documents_sql_display = source_documents_sql.replace(
                    state.kg_doc_temp_view_name, "<your_allowed_docs_view_name>"
                )
                source_documents_sql_display = source_documents_sql_display.replace(
                    state.kg_rel_temp_view_name, "<your_relationship_view_name>"
                )
                source_documents_sql_display = source_documents_sql_display.replace(
                    state.kg_entity_temp_view_name, "<your_entity_view_name>"
                )
            else:
                source_documents_sql_display = "(No source documents SQL generated)"

            logger.debug(f"A3 source_documents_sql: {source_documents_sql_display}")

        query_results = []  # if no results, will be empty (not None)
        query_generation_error = None

        # run sql
        try:
            query_results = _run_sql(sql_statement, rel_temp_view, ent_temp_view)
            if not query_results:
                query_generation_error = "SQL query returned no results"
                logger.warning(f"{query_generation_error}, retrying...")
        except Exception as e:
            query_generation_error = str(e)
            logger.warning(f"Error executing SQL query: {e}, retrying...")

        # TODO: exclude the case where the verification failed
        # fix sql and try one more time if sql query didn't work out
        # if the result is still empty after this, the kg probably doesn't have the answer,
        # so we update the strategy to simple and address this in the answer generation
        if query_generation_error is not None:
            sql_fix_prompt = (
                SIMPLE_SQL_ERROR_FIX_PROMPT.replace(
                    "---table_description---",
                    (
                        ENTITY_TABLE_DESCRIPTION
                        if state.query_type
                        == KGRelationshipDetection.NO_RELATIONSHIPS.value
                        else RELATIONSHIP_TABLE_DESCRIPTION
                    ),
                )
                .replace("---entity_types---", entities_types_str)
                .replace("---relationship_types---", relationship_types_str)
                .replace("---question---", question)
                .replace("---sql_statement---", sql_statement)
                .replace("---error_message---", query_generation_error)
                .replace("---today_date---", datetime.now().strftime("%Y-%m-%d"))
                .replace("---user_name---", f"EMPLOYEE:{user_name}")
            )
            msg = [HumanMessage(content=sql_fix_prompt)]
            primary_llm = graph_config.tooling.primary_llm

            try:
                llm_response = run_with_timeout(
                    KG_SQL_GENERATION_TIMEOUT,
                    primary_llm.invoke,
                    prompt=msg,
                    timeout_override=KG_SQL_GENERATION_TIMEOUT_OVERRIDE,
                    max_tokens=KG_SQL_GENERATION_MAX_TOKENS,
                )

                cleaned_response = (
                    str(llm_response.content)
                    .replace("```json\n", "")
                    .replace("\n```", "")
                )
                sql_statement = (
                    cleaned_response.split("<sql>")[1].split("</sql>")[0].strip()
                )
                sql_statement = sql_statement.split(";")[0].strip() + ";"
                sql_statement = sql_statement.replace("sql", "").strip()
                sql_statement = sql_statement.replace(
                    "relationship_table", rel_temp_view
                )
                sql_statement = sql_statement.replace("entity_table", ent_temp_view)

                reasoning = (
                    cleaned_response.split("<reasoning>")[1]
                    .strip()
                    .split("</reasoning>")[0]
                )

                query_results = _run_sql(sql_statement, rel_temp_view, ent_temp_view)
            except Exception as e:
                logger.error(f"Error executing SQL query even after retry: {e}")
                # TODO: raise error on frontend
                drop_views(
                    allowed_docs_view_name=doc_temp_view,
                    kg_relationships_view_name=rel_temp_view,
                    kg_entity_view_name=ent_temp_view,
                )
                raise

        source_document_results = None
        if source_documents_sql is not None and source_documents_sql != sql_statement:
            # check source document sql, just in case
            try:
                _raise_error_if_sql_fails_problem_test(
                    source_documents_sql, rel_temp_view, ent_temp_view
                )
            except ValueError as e:
                logger.error(f"Error in source document sql: {e}")
                # TODO: raise error on frontend
                drop_views(
                    allowed_docs_view_name=doc_temp_view,
                    kg_relationships_view_name=rel_temp_view,
                    kg_entity_view_name=ent_temp_view,
                )
                raise

            with get_db_readonly_user_session_with_current_tenant() as db_session:
                try:
                    result = db_session.execute(text(source_documents_sql))
                    rows = result.fetchall()
                    query_source_document_results = [dict(row._mapping) for row in rows]
                    source_document_results = [
                        source_document_result["source_document"]
                        for source_document_result in query_source_document_results
                    ]
                except Exception as e:
                    # TODO: raise warning on frontend
                    logger.error(f"Error executing Individualized SQL query: {e}")

        elif state.query_type == KGRelationshipDetection.NO_RELATIONSHIPS.value:
            # source documents should be returned for entity queries
            source_document_results = [
                x["source_document"] for x in query_results if "source_document" in x
            ]
        else:
            source_document_results = None

        drop_views(
            allowed_docs_view_name=doc_temp_view,
            kg_relationships_view_name=rel_temp_view,
            kg_entity_view_name=ent_temp_view,
        )

        logger.debug(f"A3 - Number of query_results: {len(query_results)}")

        # Stream out reasoning and SQL query

        step_answer = f"Reasoning: {reasoning} \n \n SQL Query: {sql_statement}"

        main_sql_statement = sql_statement

    # Update path if too many, or no results were retrieved from sql
    if main_sql_statement and (
        not query_results or len(query_results) > KG_MAX_DEEP_SEARCH_RESULTS
    ):
        updated_strategy = KGAnswerStrategy.SIMPLE
    else:
        updated_strategy = None

    return SQLSimpleGenerationUpdate(
        sql_query=main_sql_statement,
        sql_query_results=query_results,
        individualized_sql_query=None,
        individualized_query_results=None,
        source_documents_sql=source_documents_sql,
        source_document_results=source_document_results or [],
        updated_strategy=updated_strategy,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="generate simple sql",
                node_start_time=node_start_time,
            )
        ],
        step_results=[
            get_near_empty_step_results(
                step_number=_KG_STEP_NR,
                step_answer=step_answer,
                verified_reranked_documents=[],
            )
        ],
    )
