from collections import defaultdict
from collections.abc import Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource, FederatedConnectorSource
from onyx.context.search.models import ChunkIndexRequest, InferenceChunk
from onyx.db.federated import (
    get_federated_connector_document_set_mappings_by_document_set_names,
    list_federated_connector_oauth_tokens,
)
from onyx.db.models import FederatedConnector__DocumentSet
from onyx.federated_connectors.factory import get_federated_connector
from onyx.federated_connectors.interfaces import FederatedConnector
from onyx.utils.logger import setup_logger

logger = setup_logger()


class FederatedRetrievalInfo(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    retrieval_function: Callable[[ChunkIndexRequest], list[InferenceChunk]]
    source: FederatedConnectorSource


def get_federated_retrieval_functions(
    db_session: Session,
    user_id: UUID | None,
    source_types: list[DocumentSource] | None,
    document_set_names: list[str] | None,
) -> list[FederatedRetrievalInfo]:
    if user_id is None:
        logger.warning("No user ID provided, returning empty retrieval functions")
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
        logger.debug("No source types specified, skipping all federated connectors")
        return []

    federated_retrieval_infos: list[FederatedRetrievalInfo] = []
    federated_oauth_tokens = list_federated_connector_oauth_tokens(db_session, user_id)
    for oauth_token in federated_oauth_tokens:
        # Slack is handled separately inside SearchTool
        if (
            oauth_token.federated_connector.source
            == FederatedConnectorSource.FEDERATED_SLACK
        ):
            logger.debug(
                "Skipping Slack federated connector in user OAuth path - handled by SearchTool"
            )
            continue

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

        # Only use connector-level config (no junction table entities)
        entities = oauth_token.federated_connector.config or {}

        connector = get_federated_connector(
            oauth_token.federated_connector.source,
            oauth_token.federated_connector.credentials.get_value(apply_mask=False),
        )

        # Capture variables by value to avoid lambda closure issues
        access_token = oauth_token.token.get_value(apply_mask=False)

        def create_retrieval_function(
            conn: FederatedConnector,
            ent: dict[str, Any],
            token: str,
        ) -> Callable[[ChunkIndexRequest], list[InferenceChunk]]:
            return (
                lambda query: conn.search(
                    query,
                    ent,
                    access_token=token,
                    limit=None,  # Let connector use its own max_messages_per_query config
                )
            )

        federated_retrieval_infos.append(
            FederatedRetrievalInfo(
                retrieval_function=create_retrieval_function(
                    connector, entities, access_token
                ),
                source=oauth_token.federated_connector.source,
            )
        )
    return federated_retrieval_infos
