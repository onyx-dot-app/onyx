from collections import defaultdict
from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from sqlalchemy.orm import Session

from onyx.configs.app_configs import MAX_FEDERATED_CHUNKS
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FederatedConnectorSource
from onyx.context.search.federated.slack_search import slack_retrieval
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import SearchQuery
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.federated import (
    get_federated_connector_document_set_mappings_by_document_set_names,
)
from onyx.db.federated import list_federated_connector_oauth_tokens
from onyx.db.models import FederatedConnector__DocumentSet
from onyx.db.slack_bot import fetch_slack_bots
from onyx.federated_connectors.factory import get_federated_connector
from onyx.utils.logger import setup_logger

logger = setup_logger()


class FederatedRetrievalInfo(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    retrieval_function: Callable[[SearchQuery], list[InferenceChunk]]
    source: FederatedConnectorSource


def get_federated_retrieval_functions(
    db_session: Session,
    user_id: UUID | None,
    source_types: list[DocumentSource] | None,
    document_set_names: list[str] | None,
    slack_context: dict[str, str] | None = None,  # Add Slack context parameter
) -> list[FederatedRetrievalInfo]:
    logger.info(
        f"get_federated_retrieval_functions called with document_set_names: {document_set_names}"
    )

    # Log Slack context received
    if slack_context:
        logger.info(
            f"get_federated_retrieval_functions: Received Slack context: {slack_context}"
        )
    else:
        logger.info("get_federated_retrieval_functions: No Slack context received")

    # Check for Slack bot context first (regardless of user_id)
    if slack_context:
        logger.info("Slack context detected, checking for Slack bot setup...")

        try:
            logger.info("Fetching Slack bots...")
            slack_bots = fetch_slack_bots(db_session)
            tenant_slack_bot = next((bot for bot in slack_bots if bot.enabled), None)

            if tenant_slack_bot and tenant_slack_bot.user_token:
                # For Slack bot context, we'll determine search scope in slack_retrieval
                # based on the current Slack event context

                federated_retrieval_infos_slack = []

                # Create a wrapper that properly handles session and context
                def slack_wrapper(query: SearchQuery) -> list[InferenceChunk]:
                    logger.info(
                        f"WRAPPER DEBUG: slack_wrapper called with query: {query.query}"
                    )
                    logger.info(
                        f"WRAPPER DEBUG: slack_context captured value: {slack_context}"
                    )
                    logger.info(
                        f"WRAPPER DEBUG: About to call slack_retrieval with slack_event_context={slack_context}"
                    )

                    result = slack_retrieval(
                        query=query,
                        access_token=tenant_slack_bot.user_token or "",
                        db_session=get_session_with_current_tenant().__enter__(),
                        limit=MAX_FEDERATED_CHUNKS,
                        slack_event_context=slack_context,  # Captured from outer scope
                        bot_token=tenant_slack_bot.bot_token,
                    )

                    logger.info(
                        f"WRAPPER DEBUG: slack_retrieval returned {len(result)} chunks"
                    )
                    return result

                slack_retrieval_function = slack_wrapper

                federated_retrieval_infos_slack.append(
                    FederatedRetrievalInfo(
                        retrieval_function=slack_retrieval_function,
                        source=FederatedConnectorSource.FEDERATED_SLACK,
                    )
                )
                logger.info(
                    f"Added Slack federated search for bot, returning {len(federated_retrieval_infos_slack)} retrieval functions"
                )
                return federated_retrieval_infos_slack

        except Exception as e:
            logger.warning(f"Could not setup Slack bot federated search: {e}")
            # Fall through to regular federated connector logic

    if user_id is None:
        # No user ID provided and no Slack context, return empty
        logger.warning(
            "No user ID provided and no Slack context, returning empty retrieval functions"
        )
        return []

    # Scenario 3: Regular OAuth Federated Connectors (user_id provided, check for OAuth tokens)
    logger.info(
        f"🔍 FEDERATED TRACE: user_id provided ({user_id}), checking OAuth federated connectors..."
    )

    federated_connector__document_set_pairs = (
        (
            get_federated_connector_document_set_mappings_by_document_set_names(
                db_session, document_set_names
            )
        )
        if document_set_names
        else []
    )
    federated_connector_id_to_document_sets: dict[
        int, list[FederatedConnector__DocumentSet]
    ] = defaultdict(list)
    for pair in federated_connector__document_set_pairs:
        federated_connector_id_to_document_sets[pair.federated_connector_id].append(
            pair
        )

    # At this point, user_id is guaranteed to be not None since we're in the else branch
    assert user_id is not None

    federated_retrieval_infos: list[FederatedRetrievalInfo] = []
    federated_oauth_tokens = list_federated_connector_oauth_tokens(db_session, user_id)
    for oauth_token in federated_oauth_tokens:
        if (
            source_types is not None
            and oauth_token.federated_connector.source.to_non_federated_source()
            not in source_types
        ):
            continue

        document_set_associations = federated_connector_id_to_document_sets[
            oauth_token.federated_connector_id
        ]
        if document_set_associations:
            entities = document_set_associations[0].entities
        else:
            entities = {}

        logger.info(
            f"🔍 FEDERATED TRACE: Creating federated connector for {oauth_token.federated_connector.source}"
        )
        connector = get_federated_connector(
            oauth_token.federated_connector.source,
            oauth_token.federated_connector.credentials,
        )
        logger.info(
            f"🔍 FEDERATED TRACE: Adding federated retrieval function for {oauth_token.federated_connector.source}"
        )
        federated_retrieval_infos.append(
            FederatedRetrievalInfo(
                retrieval_function=lambda query: connector.search(
                    query,
                    entities,
                    access_token=oauth_token.token,
                    limit=MAX_FEDERATED_CHUNKS,
                ),
                source=oauth_token.federated_connector.source,
            )
        )

    logger.info(
        f"🔍 FEDERATED TRACE: Returning {len(federated_retrieval_infos)} federated retrieval functions"
    )
    return federated_retrieval_infos
