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
) -> list[FederatedRetrievalInfo]:
    if user_id is None:
        # No user ID provided, checking for Slack bot context...
        logger.warning("No user ID provided, checking for Slack bot context...")

        try:
            logger.info("Fetching Slack bots...")
            slack_bots = fetch_slack_bots(db_session)
            logger.info(f"Found {len(slack_bots)} Slack bots")

            tenant_slack_bot = next((bot for bot in slack_bots if bot.enabled), None)
            logger.info(f"Tenant Slack bot found: {tenant_slack_bot is not None}")

            if tenant_slack_bot:
                logger.info(
                    f"Bot enabled: {tenant_slack_bot.enabled}, has user_token: {bool(tenant_slack_bot.user_token)}"
                )

            if tenant_slack_bot and tenant_slack_bot.user_token:
                logger.info(
                    "Found Slack bot with user_token, adding Slack federated search"
                )
                logger.info(
                    f"Token type check - user_token starts with: "
                    f"{tenant_slack_bot.user_token[:10] if tenant_slack_bot.user_token else 'None'}..."
                )
                logger.info(
                    f"Bot token starts with: {tenant_slack_bot.bot_token[:10] if tenant_slack_bot.bot_token else 'None'}..."
                )

                federated_retrieval_infos_slack = []
                federated_retrieval_infos_slack.append(
                    FederatedRetrievalInfo(
                        retrieval_function=lambda query: slack_retrieval(
                            query=query,
                            access_token=tenant_slack_bot.user_token or "",
                            db_session=get_session_with_current_tenant().__enter__(),
                            limit=MAX_FEDERATED_CHUNKS,
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
