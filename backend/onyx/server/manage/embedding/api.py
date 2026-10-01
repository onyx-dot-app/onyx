from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.llm import (
    fetch_embedding_provider,
    fetch_existing_embedding_providers,
    remove_embedding_provider,
    upsert_cloud_embedding_provider,
)
from onyx.db.models import User
from onyx.db.search_settings import (
    get_all_search_settings,
    get_current_db_embedding_provider,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.indexing.models import EmbeddingModelDetail
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.natural_language_processing.vertex_auth import (
    VertexEmbeddingConfig,
    validate_vertex_embedding_config,
)
from onyx.server.manage.embedding.models import (
    CloudEmbeddingProvider,
    CloudEmbeddingProviderCreationRequest,
    TestEmbeddingRequest,
)
from onyx.utils.logger import setup_logger
from shared_configs.configs import MODEL_SERVER_HOST, MODEL_SERVER_PORT
from shared_configs.enums import EmbeddingProvider, EmbedTextType

logger = setup_logger()


admin_router = APIRouter(prefix="/admin/embedding")
basic_router = APIRouter(prefix="/embedding")


def _validate_vertex_config(
    provider_type: EmbeddingProvider, config: VertexEmbeddingConfig | None
) -> None:
    try:
        if config is not None and provider_type != EmbeddingProvider.GOOGLE:
            raise ValueError(
                "Vertex configuration is only supported for Google embeddings."
            )
        validate_vertex_embedding_config(config)
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e)) from e


@admin_router.post("/test-embedding")
def test_embedding_configuration(
    test_llm_request: TestEmbeddingRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    _validate_vertex_config(
        test_llm_request.provider_type, test_llm_request.vertex_config
    )
    api_key = test_llm_request.api_key
    uses_workload_identity = (
        test_llm_request.vertex_config is not None
        and test_llm_request.vertex_config.auth_method == "workload_identity"
    )
    if (
        api_key is None
        and test_llm_request.provider_type == EmbeddingProvider.GOOGLE
        and not uses_workload_identity
    ):
        existing = fetch_embedding_provider(db_session, EmbeddingProvider.GOOGLE)
        if existing is not None and existing.api_key is not None:
            api_key = existing.api_key.get_value(apply_mask=False)
    try:
        test_model = EmbeddingModel(
            server_host=MODEL_SERVER_HOST,
            server_port=MODEL_SERVER_PORT,
            api_key=api_key,
            api_url=test_llm_request.api_url,
            provider_type=test_llm_request.provider_type,
            model_name=test_llm_request.model_name,
            api_version=test_llm_request.api_version,
            deployment_name=test_llm_request.deployment_name,
            vertex_config=test_llm_request.vertex_config,
            normalize=False,
            query_prefix=None,
            passage_prefix=None,
        )
        test_model.encode(["Testing Embedding"], text_type=EmbedTextType.QUERY)

    except ValueError as e:
        error_msg = f"Not a valid embedding model. Exception thrown: {e}"
        logger.error(error_msg)
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, error_msg) from e

    except Exception as e:
        error_msg = "An error occurred while testing your embedding model. Please check your configuration."
        logger.error("%s Error message: %s", error_msg, e, exc_info=True)
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, error_msg)


@admin_router.get("", response_model=list[EmbeddingModelDetail])
def list_embedding_models(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[EmbeddingModelDetail]:
    search_settings = get_all_search_settings(db_session)
    return [EmbeddingModelDetail.from_db_model(setting) for setting in search_settings]


@admin_router.get("/embedding-provider")
def list_embedding_providers(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[CloudEmbeddingProvider]:
    return [
        CloudEmbeddingProvider.from_request(embedding_provider_model)
        for embedding_provider_model in fetch_existing_embedding_providers(db_session)
    ]


@admin_router.get("/embedding-provider/{provider_type}")
def get_embedding_provider(
    provider_type: EmbeddingProvider,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> CloudEmbeddingProvider:
    embedding_provider = fetch_embedding_provider(db_session, provider_type)
    if embedding_provider is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"Embedding provider '{provider_type.value}' is not configured",
        )
    return CloudEmbeddingProvider.from_request(embedding_provider)


@admin_router.delete("/embedding-provider/{provider_type}")
def delete_embedding_provider(
    provider_type: EmbeddingProvider,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    embedding_provider = get_current_db_embedding_provider(db_session=db_session)
    if (
        embedding_provider is not None
        and provider_type == embedding_provider.provider_type
    ):
        raise OnyxError(
            OnyxErrorCode.RESOURCE_IN_USE,
            "You can't delete the embedding provider the current search settings "
            "use. Point search settings at another provider first.",
        )

    remove_embedding_provider(db_session, provider_type=provider_type)


@admin_router.put("/embedding-provider")
def put_cloud_embedding_provider(
    provider: CloudEmbeddingProviderCreationRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> CloudEmbeddingProvider:
    _validate_vertex_config(provider.provider_type, provider.vertex_config)
    if (
        provider.vertex_config
        and provider.vertex_config.auth_method == "workload_identity"
    ):
        provider = provider.model_copy(
            update={"api_key": None, "api_key_changed": True}
        )
    return upsert_cloud_embedding_provider(db_session, provider)
