from collections import defaultdict
from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from sqlalchemy.orm import Session

from onyx.configs.app_configs import MAX_FEDERATED_CHUNKS
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FederatedConnectorSource
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import SearchQuery
from onyx.db.federated import (
    get_federated_connector_document_set_mappings_by_document_set_names,
)
from onyx.db.federated import list_federated_connector_oauth_tokens
from onyx.db.models import FederatedConnector__DocumentSet
from onyx.db.slack_bot import fetch_slack_bots
from onyx.federated_connectors.factory import get_federated_connector
from onyx.onyxbot.slack.models import SlackContext
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
    slack_context: SlackContext | None = None,
) -> list[FederatedRetrievalInfo]:
    # Check for Slack bot context first (regardless of user_id)
    if slack_context:
        logger.info("Slack context detected, checking for Slack bot setup...")

        try:
            slack_bots = fetch_slack_bots(db_session)
            logger.info(f"Found {len(slack_bots)} Slack bots")

            # First try to find a bot with user token
            tenant_slack_bot = next(
                (bot for bot in slack_bots if bot.enabled and bot.user_token), None
            )
            if tenant_slack_bot:
                logger.info(f"Selected bot with user_token: {tenant_slack_bot.name}")
            else:
                # Fall back to any enabled bot without user token
                tenant_slack_bot = next(
                    (bot for bot in slack_bots if bot.enabled), None
                )
                if tenant_slack_bot:
                    logger.info(
                        f"Selected bot without user_token: {tenant_slack_bot.name} (limited functionality)"
                    )
                else:
                    logger.warning("No enabled Slack bots found")

            if tenant_slack_bot:
                federated_retrieval_infos_slack = []

                # Use user_token if available, otherwise fall back to bot_token
                access_token = tenant_slack_bot.user_token or tenant_slack_bot.bot_token
                if not tenant_slack_bot.user_token:
                    logger.warning(
                        f"Using bot_token for Slack search (limited functionality): {tenant_slack_bot.name}"
                    )

                # For bot context, we don't need real OAuth credentials
                credentials = {
                    "client_id": "bot-context",  # Placeholder for bot context
                    "client_secret": "bot-context",  # Placeholder for bot context
                }

                # Create Slack federated connector
                connector = get_federated_connector(
                    FederatedConnectorSource.FEDERATED_SLACK,
                    credentials,
                )

                federated_retrieval_infos_slack.append(
                    FederatedRetrievalInfo(
                        retrieval_function=lambda query: connector.search(
                            query,
                            {},  # Empty entities for Slack context
                            access_token=access_token,
                            limit=MAX_FEDERATED_CHUNKS,
                            slack_event_context=slack_context,
                            bot_token=tenant_slack_bot.bot_token,
                        ),
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

    # If no source types are specified, don't use any federated connectors
    if source_types is None:
        logger.info("No source types specified, skipping all federated connectors")
        return []

    federated_retrieval_infos: list[FederatedRetrievalInfo] = []
    federated_oauth_tokens = list_federated_connector_oauth_tokens(db_session, user_id)
    for oauth_token in federated_oauth_tokens:
        if (
            oauth_token.federated_connector.source.to_non_federated_source()
            not in source_types
        ):
            continue

        document_set_associations = federated_connector_id_to_document_sets[
            oauth_token.federated_connector_id
        ]

        # if document set names are specified by the user, skip federated connectors that are
        # not associated with any of the document sets
        if document_set_names and not document_set_associations:
            continue

        if document_set_associations:
            entities = document_set_associations[0].entities
        else:
            entities = {}

        connector = get_federated_connector(
            oauth_token.federated_connector.source,
            oauth_token.federated_connector.credentials,
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
    return federated_retrieval_infos
