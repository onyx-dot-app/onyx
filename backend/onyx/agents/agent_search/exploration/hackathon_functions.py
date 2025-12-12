import json
from collections import defaultdict
from datetime import datetime
from datetime import timedelta

from sqlalchemy.orm import Session

from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_raw
from onyx.context.search.models import IndexFilters
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.db.hackathon_subscriptions import get_document_ids_by_cc_pair_name
from onyx.db.hackathon_subscriptions import get_subscription_registration
from onyx.db.hackathon_subscriptions import get_subscription_result
from onyx.db.hackathon_subscriptions import save_subscription_result
from onyx.db.models import SubscriptionResult
from onyx.db.models import User
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.llm.interfaces import LLM
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def process_notifications(
    db_session: Session,
    llm: LLM,
    user: User | None = None,
) -> None:
    if not user:
        return

    subscription_registration = get_subscription_registration(db_session, str(user.id))
    if not subscription_registration:
        return

    doc_extraction_contexts = subscription_registration.doc_extraction_contexts
    subscription_registration.search_questions

    # Get the document index for retrieval
    search_settings = get_current_search_settings(db_session)
    document_index = get_default_document_index(search_settings, None)

    # Build access control filters for the user
    user_acl_filters = build_access_filters_for_user(user, db_session)

    # Get current tenant ID
    tenant_id = get_current_tenant_id()

    analysis_results = defaultdict(lambda: defaultdict(list))
    invalid_doc_extraction_context_keys = []

    for (
        doc_extraction_context_key,
        doc_extraction_context_value,
    ) in doc_extraction_contexts.items():
        # Get all document IDs and links for this connector credential pair
        # Filter for documents updated after September 18, 2025
        date_threshold = datetime(2025, 9, 19) - timedelta(days=1)
        documents = get_document_ids_by_cc_pair_name(
            db_session, doc_extraction_context_key, date_threshold
        )

        for document_id, document_link in documents:
            # Retrieve all chunks for this specific document with proper access control
            filters = IndexFilters(
                tenant_id=tenant_id,
                access_control_list=user_acl_filters,
            )

            document_chunks = document_index.id_based_retrieval(
                chunk_requests=[VespaChunkRequest(document_id=document_id)],
                filters=filters,
                batch_retrieval=False,
            )

            # Sort chunks by chunk_id and concatenate content
            content_chunks = [
                {chunk.chunk_id: chunk.content} for chunk in document_chunks
            ]
            sorted_content_chunks = sorted(
                content_chunks, key=lambda x: list(x.keys())[0]
            )
            sorted_content_chunks_string = "\n".join(
                [
                    f"{chunk_id}: {content}"
                    for chunk_dict in sorted_content_chunks
                    for chunk_id, content in chunk_dict.items()
                ]
            )

            # Replace placeholder in extraction context with document content
            analysis_prompt = doc_extraction_context_value.replace(
                "---doc_content---", sorted_content_chunks_string
            )

            # Invoke LLM with the analysis prompt
            analysis_response = invoke_llm_raw(
                llm=llm,
                prompt=analysis_prompt,
            )

            # Parse the response content from string to dictionary
            response_content = str(analysis_response.content)

            # Try to extract JSON from the response
            try:
                # First, try to parse the entire response as JSON
                analysis_dict = json.loads(response_content)
            except json.JSONDecodeError:
                # If that fails, try to find JSON within markdown code blocks
                import re

                json_match = re.search(
                    r"```(?:json)?\s*(\{.*?\})\s*```", response_content, re.DOTALL
                )
                if json_match:
                    analysis_dict = json.loads(json_match.group(1))
                else:
                    # Try to find JSON between curly braces
                    json_match = re.search(r"\{.*\}", response_content, re.DOTALL)
                    if json_match:
                        analysis_dict = json.loads(json_match.group(0))
                    else:
                        logger.error(
                            f"Failed to parse LLM response as JSON: {response_content}"
                        )
                        analysis_dict = {}

            for analysis_type, analysis_value in analysis_dict.items():
                if analysis_value:
                    analysis_results[doc_extraction_context_key][analysis_type].append(
                        f"[{document_id}]({document_link}): {analysis_value}"
                    )
                if analysis_type == "type" and analysis_value.lower() != "yes":
                    invalid_doc_extraction_context_keys.append(
                        doc_extraction_context_key
                    )

    # Build the analysis string from all results
    analysis_string_components = []

    for doc_extraction_context_key, analysis_type_dict in analysis_results.items():
        if doc_extraction_context_key in invalid_doc_extraction_context_keys:
            continue
        for analysis_type, analysis_values in analysis_type_dict.items():
            analysis_string_components.append(f"## Calls - {analysis_type}")
            for analysis_value in analysis_values:
                if analysis_value:
                    analysis_string_components.append(analysis_value)
    analysis_string = "\n \n \n ".join(analysis_string_components)

    # Save the results to the subscription_results table
    subscription_result = SubscriptionResult(
        user_id=user.id,
        type="document_analysis",
        notifications={"analysis": analysis_string},
    )
    save_subscription_result(db_session, subscription_result)


def get_notifications(
    db_session: Session,
    user: User,
) -> None:
    subscription_result = get_subscription_result(db_session, str(user.id))
    if not subscription_result:
        return
    return subscription_result.notifications["analysis"]
