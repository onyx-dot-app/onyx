from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.api_token import peek_api_token_value
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
from onyx.natural_language_processing.embedding_auth import (
    CloudEmbeddingAuth,
    build_embedding_auth,
)
from onyx.natural_language_processing.vertex_auth import VertexEmbeddingConfig
from onyx.server.manage.api_token.models import ExistingApiToken
from onyx.server.manage.embedding.models import (
    CloudEmbeddingProvider,
    CloudEmbeddingProviderCreationRequest,
    TestEmbeddingRequest,
    TestEmbeddingResponse,
)
from onyx.server.manage.embedding.probe import probe_embedding_dimension
from onyx.utils.logger import setup_logger
from shared_configs.enums import EmbeddingProvider

logger = setup_logger()


admin_router = APIRouter(prefix="/admin/embedding")
basic_router = APIRouter(prefix="/embedding")


def _build_request_auth(
    provider_type: EmbeddingProvider,
    api_key: str | None,
    vertex_config: VertexEmbeddingConfig | None,
) -> CloudEmbeddingAuth:
    try:
        return build_embedding_auth(provider_type, api_key, vertex_config)
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e)) from e


@admin_router.post("/test-embedding")
def test_embedding_configuration(
    test_llm_request: TestEmbeddingRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> TestEmbeddingResponse:
    current_token_id: int | None = None
    if isinstance(test_llm_request.api_key, ExistingApiToken):
        existing = fetch_embedding_provider(db_session, test_llm_request.provider_type)
        current_token_id = existing.api_token_id if existing is not None else None
    api_key = peek_api_token_value(
        db_session,
        test_llm_request.api_key,
        platform=test_llm_request.provider_type.value,
        base_url=test_llm_request.api_url,
        current_token_id=current_token_id,
    )
    auth = _build_request_auth(
        test_llm_request.provider_type, api_key, test_llm_request.vertex_config
    )
    dimension: int = probe_embedding_dimension(
        provider_type=test_llm_request.provider_type,
        api_key=api_key,
        api_url=test_llm_request.api_url,
        model_name=test_llm_request.model_name,
        auth=auth,
        api_version=test_llm_request.api_version,
        deployment_name=test_llm_request.deployment_name,
    )
    return TestEmbeddingResponse(dimension=dimension)


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
    auth = _build_request_auth(provider.provider_type, None, provider.vertex_config)
    if not auth.uses_api_key:
        provider = provider.model_copy(update={"api_key": None})
    return upsert_cloud_embedding_provider(db_session, provider)
