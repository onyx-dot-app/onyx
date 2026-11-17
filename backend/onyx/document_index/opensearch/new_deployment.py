from typing import Any

from sqlalchemy.orm import Session

from onyx.db.connector import check_connectors_exist, check_user_files_exist
from onyx.db.document import check_docs_exist
from onyx.db.enums import VectorQuantization
from onyx.db.models import SearchSettings
from onyx.db.search_settings import (
    get_secondary_search_settings,
    update_search_settings_vector_quantization,
)
from onyx.document_index.opensearch.client import (
    OpenSearchClient,
    OpenSearchIndexClient,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.constants import LUCENE_SCALAR_QUANTIZATION
from onyx.document_index.opensearch.schema import CONTENT_VECTOR_FIELD_NAME
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

# A new self-hosted deployment starts with this quantization. 7-bit holds the
# vectors in about 1/4 of the memory, with the recall of float32.
NEW_DEPLOYMENT_VECTOR_QUANTIZATION = VectorQuantization.SCALAR_7_BIT


def set_new_deployment_vector_quantization(
    db_session: Session, search_settings: SearchSettings
) -> None:
    """Sets the quantization of search_settings on a new deployment before its
    index is created.

    Call it before every path that can create the first index: startup, and the
    swap that promotes the FUTURE row the migrations create for the default
    model. Quantization is part of the index mapping, so the settings must
    match the index. If an index for these settings already exists, for example
    when Postgres was reset and OpenSearch was not, the settings take the
    quantization of that index. Otherwise they take
    NEW_DEPLOYMENT_VECTOR_QUANTIZATION.

    Any sign of earlier use leaves the settings as they are: documents,
    connectors or user files. Other search settings rows are not a sign:
    migrations leave a PAST row on a new deployment. Multi-tenant, a FUTURE row,
    a cluster that is not reachable, or one that does not report a version that
    supports the quantization also leave them as they are.
    """
    if MULTI_TENANT or search_settings.vector_quantization != VectorQuantization.NONE:
        return
    if get_secondary_search_settings(db_session) is not None:
        return
    if (
        check_docs_exist(db_session)
        or check_connectors_exist(db_session)
        or check_user_files_exist(db_session)
    ):
        return

    min_version = LUCENE_SCALAR_QUANTIZATION[
        NEW_DEPLOYMENT_VECTOR_QUANTIZATION
    ].min_opensearch_version
    try:
        with OpenSearchClient() as client:
            if not wait_for_opensearch_with_timeout(client=client):
                return
            cluster_version = client.get_opensearch_version()
        with OpenSearchIndexClient(index_name=search_settings.index_name) as client:
            if client.index_exists():
                _match_existing_index(
                    db_session,
                    search_settings,
                    client.get_vector_field_encoder(CONTENT_VECTOR_FIELD_NAME),
                )
                return
        if cluster_version is None or cluster_version < min_version:
            return
    except Exception:
        logger.exception(
            "Could not check OpenSearch for a new deployment. Keeping vector "
            "quantization %s.",
            search_settings.vector_quantization.value,
        )
        return

    update_search_settings_vector_quantization(
        search_settings, NEW_DEPLOYMENT_VECTOR_QUANTIZATION, db_session
    )
    logger.notice(
        "New deployment: index %s uses %s vector quantization.",
        search_settings.index_name,
        NEW_DEPLOYMENT_VECTOR_QUANTIZATION.value,
    )


def _match_existing_index(
    db_session: Session,
    search_settings: SearchSettings,
    encoder: dict[str, Any] | None,
) -> None:
    """Saves the quantization of the existing index to search_settings."""
    if encoder is None or encoder.get("name") != "sq":
        return
    bits = encoder.get("parameters", {}).get("bits")
    for vector_quantization, quantization in LUCENE_SCALAR_QUANTIZATION.items():
        if quantization.bits == bits:
            update_search_settings_vector_quantization(
                search_settings, vector_quantization, db_session
            )
            logger.notice(
                "Index %s exists with %s vector quantization. The search "
                "settings now match it.",
                search_settings.index_name,
                vector_quantization.value,
            )
            return
