from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from danswer.auth.users import current_admin_user
from danswer.db.embedding_model import get_current_db_embedding_provider
from danswer.db.engine import get_session
from danswer.db.llm import fetch_existing_embedding_providers
from danswer.db.llm import remove_embedding_provider
from danswer.db.llm import upsert_cloud_embedding_provider
from danswer.db.models import User
from danswer.natural_language_processing.search_nlp_models import EmbeddingModel
from danswer.server.manage.embedding.models import CloudEmbeddingProvider
from danswer.server.manage.embedding.models import CloudEmbeddingProviderCreationRequest
from danswer.server.manage.embedding.models import TestEmbeddingRequest
from danswer.utils.logger import setup_logger
from shared_configs.configs import MODEL_SERVER_HOST
from shared_configs.configs import MODEL_SERVER_PORT
from shared_configs.enums import EmbeddingProvider
from shared_configs.enums import EmbedTextType

logger = setup_logger()


admin_router = APIRouter(prefix="/admin/embedding")
basic_router = APIRouter(prefix="/embedding")


@admin_router.post("/test-embedding")
def test_embedding_configuration(
    test_llm_request: TestEmbeddingRequest,
    _: User | None = Depends(current_admin_user),
) -> None:
    try:
        test_model = EmbeddingModel(
            server_host=MODEL_SERVER_HOST,
            server_port=MODEL_SERVER_PORT,
            api_key=test_llm_request.api_key,
            provider_type=test_llm_request.provider_type,
            normalize=False,
            query_prefix=None,
            passage_prefix=None,
            model_name=None,
        )
        test_model.encode(["Testing Embedding"], text_type=EmbedTextType.QUERY)

    except ValueError as e:
        error_msg = f"Not a valid embedding model. Exception thrown: {e}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    except Exception as e:
        error_msg = "An error occurred while testing your embedding model. Please check your configuration."
        logger.error(f"{error_msg} Error message: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=error_msg)


@admin_router.get("/embedding-provider")
def list_embedding_providers(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[CloudEmbeddingProvider]:
    return [
        CloudEmbeddingProvider.from_request(embedding_provider_model)
        for embedding_provider_model in fetch_existing_embedding_providers(db_session)
    ]


@admin_router.delete("/embedding-provider/{provider_type}")
def delete_embedding_provider(
    provider_type: EmbeddingProvider,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    embedding_provider = get_current_db_embedding_provider(db_session=db_session)
    if (
        embedding_provider is not None
        and provider_type == embedding_provider.provider_type
    ):
        raise HTTPException(
            status_code=400, detail="You can't delete a currently active model"
        )

    remove_embedding_provider(db_session, provider_type=provider_type)


@admin_router.put("/embedding-provider")
def put_cloud_embedding_provider(
    provider: CloudEmbeddingProviderCreationRequest,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> CloudEmbeddingProvider:
    return upsert_cloud_embedding_provider(db_session, provider)
