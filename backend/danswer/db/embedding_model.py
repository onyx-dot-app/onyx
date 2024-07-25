from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.configs.model_configs import ASYM_PASSAGE_PREFIX
from danswer.configs.model_configs import ASYM_QUERY_PREFIX
from danswer.configs.model_configs import DEFAULT_DOCUMENT_ENCODER_MODEL
from danswer.configs.model_configs import DOC_EMBEDDING_DIM
from danswer.configs.model_configs import DOCUMENT_ENCODER_MODEL
from danswer.configs.model_configs import NORMALIZE_EMBEDDINGS
from danswer.configs.model_configs import OLD_DEFAULT_DOCUMENT_ENCODER_MODEL
from danswer.configs.model_configs import OLD_DEFAULT_MODEL_DOC_EMBEDDING_DIM
from danswer.configs.model_configs import OLD_DEFAULT_MODEL_NORMALIZE_EMBEDDINGS
from danswer.db.llm import fetch_embedding_provider
from danswer.db.models import CloudEmbeddingProvider
from danswer.db.models import EmbeddingModel
from danswer.db.models import IndexModelStatus
from danswer.indexing.models import EmbeddingModelDetail
from danswer.natural_language_processing.search_nlp_models import clean_model_name
from danswer.server.manage.embedding.models import (
    CloudEmbeddingProvider as ServerCloudEmbeddingProvider,
)
from danswer.utils.logger import setup_logger

logger = setup_logger()


def create_embedding_model(
    model_details: EmbeddingModelDetail,
    db_session: Session,
    status: IndexModelStatus = IndexModelStatus.FUTURE,
) -> EmbeddingModel:
    embedding_model = EmbeddingModel(
        model_name=model_details.model_name,
        model_dim=model_details.model_dim,
        normalize=model_details.normalize,
        query_prefix=model_details.query_prefix,
        passage_prefix=model_details.passage_prefix,
        status=status,
        cloud_provider_id=model_details.cloud_provider_id,
        # Every single embedding model except the initial one from migrations has this name
        # The initial one from migration is called "danswer_chunk"
        index_name=f"danswer_chunk_{clean_model_name(model_details.model_name)}",
    )

    db_session.add(embedding_model)
    db_session.commit()

    return embedding_model


def get_model_id_from_name(
    db_session: Session, embedding_provider_name: str
) -> int | None:
    query = select(CloudEmbeddingProvider).where(
        CloudEmbeddingProvider.name == embedding_provider_name
    )
    provider = db_session.execute(query).scalars().first()
    return provider.id if provider else None


def get_current_db_embedding_provider(
    db_session: Session,
) -> ServerCloudEmbeddingProvider | None:
    current_embedding_model = EmbeddingModelDetail.from_model(
        get_current_db_embedding_model(db_session=db_session)
    )

    if (
        current_embedding_model is None
        or current_embedding_model.cloud_provider_id is None
    ):
        return None

    embedding_provider = fetch_embedding_provider(
        db_session=db_session, provider_id=current_embedding_model.cloud_provider_id
    )
    if embedding_provider is None:
        raise RuntimeError("No embedding provider exists for this model.")

    current_embedding_provider = ServerCloudEmbeddingProvider.from_request(
        cloud_provider_model=embedding_provider
    )

    return current_embedding_provider


def get_current_db_embedding_model(db_session: Session) -> EmbeddingModel:
    query = (
        select(EmbeddingModel)
        .where(EmbeddingModel.status == IndexModelStatus.PRESENT)
        .order_by(EmbeddingModel.id.desc())
    )
    result = db_session.execute(query)
    latest_model = result.scalars().first()

    if not latest_model:
        raise RuntimeError("No embedding model selected, DB is not in a valid state")

    return latest_model


def get_secondary_db_embedding_model(db_session: Session) -> EmbeddingModel | None:
    query = (
        select(EmbeddingModel)
        .where(EmbeddingModel.status == IndexModelStatus.FUTURE)
        .order_by(EmbeddingModel.id.desc())
    )
    result = db_session.execute(query)
    latest_model = result.scalars().first()

    return latest_model


def update_embedding_model_status(
    embedding_model: EmbeddingModel, new_status: IndexModelStatus, db_session: Session
) -> None:
    embedding_model.status = new_status
    db_session.commit()


def user_has_overridden_embedding_model() -> bool:
    return DOCUMENT_ENCODER_MODEL != DEFAULT_DOCUMENT_ENCODER_MODEL


def get_old_default_embedding_model() -> EmbeddingModel:
    is_overridden = user_has_overridden_embedding_model()
    return EmbeddingModel(
        model_name=(
            DOCUMENT_ENCODER_MODEL
            if is_overridden
            else OLD_DEFAULT_DOCUMENT_ENCODER_MODEL
        ),
        model_dim=(
            DOC_EMBEDDING_DIM if is_overridden else OLD_DEFAULT_MODEL_DOC_EMBEDDING_DIM
        ),
        normalize=(
            NORMALIZE_EMBEDDINGS
            if is_overridden
            else OLD_DEFAULT_MODEL_NORMALIZE_EMBEDDINGS
        ),
        query_prefix=(ASYM_QUERY_PREFIX if is_overridden else ""),
        passage_prefix=(ASYM_PASSAGE_PREFIX if is_overridden else ""),
        status=IndexModelStatus.PRESENT,
        index_name="danswer_chunk",
    )


def get_new_default_embedding_model(is_present: bool) -> EmbeddingModel:
    return EmbeddingModel(
        model_name=DOCUMENT_ENCODER_MODEL,
        model_dim=DOC_EMBEDDING_DIM,
        normalize=NORMALIZE_EMBEDDINGS,
        query_prefix=ASYM_QUERY_PREFIX,
        passage_prefix=ASYM_PASSAGE_PREFIX,
        status=IndexModelStatus.PRESENT if is_present else IndexModelStatus.FUTURE,
        index_name=f"danswer_chunk_{clean_model_name(DOCUMENT_ENCODER_MODEL)}",
    )
