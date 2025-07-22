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
        logger.warning(
            "No user ID provided, skipping federated retrieval. Federated retrieval not "
            "supported with AUTH_TYPE=disabled."
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

    federated_retrieval_infos: list[FederatedRetrievalInfo] = []
    federated_oauth_tokens = list_federated_connector_oauth_tokens(db_session, user_id)
    for oauth_token in federated_oauth_tokens:
        # if source filters are specified by the user, skip federated connectors that are
        # not in the source_types
        if (
            source_types is not None
            and oauth_token.federated_connector.source.to_non_federated_source()
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
