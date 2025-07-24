from sqlalchemy import and_
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.model_configs import DEFAULT_DOCUMENT_ENCODER_MODEL
from onyx.configs.model_configs import DOCUMENT_ENCODER_MODEL
from onyx.context.search.models import SavedSearchSettings
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.llm import fetch_embedding_provider
from onyx.db.models import CloudEmbeddingProvider
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexModelStatus
from onyx.db.models import SearchSettings
from onyx.natural_language_processing.search_nlp_models import warm_up_cross_encoder
from onyx.server.manage.embedding.models import (
    CloudEmbeddingProvider as ServerCloudEmbeddingProvider,
)
from onyx.utils.logger import setup_logger
from shared_configs.configs import PRESERVED_SEARCH_FIELDS
from shared_configs.enums import EmbeddingProvider


logger = setup_logger()


class ActiveSearchSettings:
    primary: SearchSettings
    secondary: SearchSettings | None

    def __init__(
        self, primary: SearchSettings, secondary: SearchSettings | None
    ) -> None:
        self.primary = primary
        self.secondary = secondary


def create_search_settings(
    search_settings: SavedSearchSettings,
    db_session: Session,
    status: IndexModelStatus = IndexModelStatus.FUTURE,
) -> SearchSettings:
    embedding_model = SearchSettings(
        model_name=search_settings.model_name,
        model_dim=search_settings.model_dim,
        normalize=search_settings.normalize,
        query_prefix=search_settings.query_prefix,
        passage_prefix=search_settings.passage_prefix,
        status=status,
        index_name=search_settings.index_name,
        provider_type=search_settings.provider_type,
        multipass_indexing=search_settings.multipass_indexing,
        embedding_precision=search_settings.embedding_precision,
        reduced_dimension=search_settings.reduced_dimension,
        enable_contextual_rag=search_settings.enable_contextual_rag,
        contextual_rag_llm_name=search_settings.contextual_rag_llm_name,
        contextual_rag_llm_provider=search_settings.contextual_rag_llm_provider,
        multilingual_expansion=search_settings.multilingual_expansion,
        disable_rerank_for_streaming=search_settings.disable_rerank_for_streaming,
        rerank_model_name=search_settings.rerank_model_name,
        rerank_provider_type=search_settings.rerank_provider_type,
        rerank_api_key=search_settings.rerank_api_key,
        num_rerank=search_settings.num_rerank,
        background_reindex_enabled=search_settings.background_reindex_enabled,
    )

    db_session.add(embedding_model)
    db_session.commit()

    return embedding_model


def get_embedding_provider_from_provider_type(
    db_session: Session, provider_type: EmbeddingProvider
) -> CloudEmbeddingProvider | None:
    query = select(CloudEmbeddingProvider).where(
        CloudEmbeddingProvider.provider_type == provider_type
    )
    provider = db_session.execute(query).scalars().first()
    return provider if provider else None


def get_current_db_embedding_provider(
    db_session: Session,
) -> ServerCloudEmbeddingProvider | None:
    search_settings = get_current_search_settings(db_session=db_session)

    if search_settings.provider_type is None:
        return None

    embedding_provider = fetch_embedding_provider(
        db_session=db_session,
        provider_type=search_settings.provider_type,
    )
    if embedding_provider is None:
        raise RuntimeError("No embedding provider exists for this model.")

    current_embedding_provider = ServerCloudEmbeddingProvider.from_request(
        cloud_provider_model=embedding_provider
    )

    return current_embedding_provider


def delete_search_settings(db_session: Session, search_settings_id: int) -> None:
    current_settings = get_current_search_settings(db_session)

    if current_settings.id == search_settings_id:
        raise ValueError("Cannot delete currently active search settings")

    # First, delete associated index attempts
    index_attempts_query = delete(IndexAttempt).where(
        IndexAttempt.search_settings_id == search_settings_id
    )
    db_session.execute(index_attempts_query)

    # Then, delete the search settings
    search_settings_query = delete(SearchSettings).where(
        and_(
            SearchSettings.id == search_settings_id,
            SearchSettings.status != IndexModelStatus.PRESENT,
        )
    )

    db_session.execute(search_settings_query)
    db_session.commit()


def get_current_search_settings(db_session: Session) -> SearchSettings:
    query = (
        select(SearchSettings)
        .where(SearchSettings.status == IndexModelStatus.PRESENT)
        .order_by(SearchSettings.id.desc())
    )
    result = db_session.execute(query)
    latest_settings = result.scalars().first()

    if not latest_settings:
        raise RuntimeError("No search settings specified, DB is not in a valid state")
    return latest_settings


def get_secondary_search_settings(db_session: Session) -> SearchSettings | None:
    query = (
        select(SearchSettings)
        .where(SearchSettings.status == IndexModelStatus.FUTURE)
        .order_by(SearchSettings.id.desc())
    )
    result = db_session.execute(query)
    latest_settings = result.scalars().first()

    return latest_settings


def get_active_search_settings(db_session: Session) -> ActiveSearchSettings:
    """Returns active search settings. Secondary search settings may be None."""

    # Get the primary and secondary search settings
    primary_search_settings = get_current_search_settings(db_session)
    secondary_search_settings = get_secondary_search_settings(db_session)
    return ActiveSearchSettings(
        primary=primary_search_settings, secondary=secondary_search_settings
    )


def get_active_search_settings_list(db_session: Session) -> list[SearchSettings]:
    """Returns active search settings as a list. Primary settings are the first element,
    and if secondary search settings exist, they will be the second element."""

    search_settings_list: list[SearchSettings] = []

    active_search_settings = get_active_search_settings(db_session)
    search_settings_list.append(active_search_settings.primary)
    if active_search_settings.secondary:
        search_settings_list.append(active_search_settings.secondary)

    return search_settings_list


def get_all_search_settings(db_session: Session) -> list[SearchSettings]:
    query = select(SearchSettings).order_by(SearchSettings.id.desc())
    result = db_session.execute(query)
    all_settings = result.scalars().all()
    return list(all_settings)


def get_multilingual_expansion(db_session: Session | None = None) -> list[str]:
    if db_session is None:
        with get_session_with_current_tenant() as db_session:
            search_settings = get_current_search_settings(db_session)
    else:
        search_settings = get_current_search_settings(db_session)
    if not search_settings:
        return []
    return search_settings.multilingual_expansion


def update_search_settings(
    current_settings: SearchSettings,
    updated_settings: SavedSearchSettings,
    preserved_fields: list[str],
) -> None:
    for field, value in updated_settings.dict().items():
        if field not in preserved_fields:
            setattr(current_settings, field, value)


def update_current_search_settings(
    db_session: Session,
    search_settings: SavedSearchSettings,
    preserved_fields: list[str] = PRESERVED_SEARCH_FIELDS,
) -> None:
    current_settings = get_current_search_settings(db_session)
    if not current_settings:
        logger.warning("No current search settings found to update")
        return

    # Whenever we update the current search settings, we should ensure that the local reranking model is warmed up.
    if (
        search_settings.rerank_provider_type is None
        and search_settings.rerank_model_name is not None
        and current_settings.rerank_model_name != search_settings.rerank_model_name
    ):
        warm_up_cross_encoder(search_settings.rerank_model_name)

    update_search_settings(current_settings, search_settings, preserved_fields)
    db_session.commit()
    logger.info("Current search settings updated successfully")


def update_secondary_search_settings(
    db_session: Session,
    search_settings: SavedSearchSettings,
    preserved_fields: list[str] = PRESERVED_SEARCH_FIELDS,
) -> None:
    secondary_settings = get_secondary_search_settings(db_session)
    if not secondary_settings:
        logger.warning("No secondary search settings found to update")
        return

    preserved_fields = PRESERVED_SEARCH_FIELDS
    update_search_settings(secondary_settings, search_settings, preserved_fields)

    db_session.commit()
    logger.info("Secondary search settings updated successfully")


def update_search_settings_status(
    search_settings: SearchSettings, new_status: IndexModelStatus, db_session: Session
) -> None:
    search_settings.status = new_status
    db_session.commit()


def user_has_overridden_embedding_model() -> bool:
    return DOCUMENT_ENCODER_MODEL != DEFAULT_DOCUMENT_ENCODER_MODEL
