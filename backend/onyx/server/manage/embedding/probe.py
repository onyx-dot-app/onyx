from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.natural_language_processing.embedding_auth import CloudEmbeddingAuth
from onyx.natural_language_processing.exceptions import (
    EmbeddingRequestFailedError,
    EmbeddingRequestRejectedError,
)
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.utils.logger import setup_logger
from shared_configs.configs import MODEL_SERVER_HOST, MODEL_SERVER_PORT
from shared_configs.enums import EmbeddingProvider, EmbedTextType
from shared_configs.model_server_models import Embedding

logger = setup_logger()


def probe_embedding_dimension(
    *,
    provider_type: EmbeddingProvider,
    api_key: str | None,
    api_url: str | None,
    model_name: str | None,
    auth: CloudEmbeddingAuth,
    api_version: str | None = None,
    deployment_name: str | None = None,
    reduced_dimension: int | None = None,
) -> int:
    """Embed one test string with a cloud provider and return the vector length."""
    try:
        test_model: EmbeddingModel = EmbeddingModel(
            server_host=MODEL_SERVER_HOST,
            server_port=MODEL_SERVER_PORT,
            api_key=api_key,
            api_url=api_url,
            provider_type=provider_type,
            model_name=model_name,
            api_version=api_version,
            deployment_name=deployment_name,
            reduced_dimension=reduced_dimension,
            auth=auth,
            normalize=False,
            query_prefix=None,
            passage_prefix=None,
        )
        embeddings: list[Embedding] = test_model.encode(
            ["Testing Embedding"], text_type=EmbedTextType.QUERY
        )
        return len(embeddings[0])

    except EmbeddingRequestRejectedError as e:
        error_msg: str = f"The embedding provider rejected the model {model_name}: {e}"
        logger.warning(error_msg)
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, error_msg) from e

    except EmbeddingRequestFailedError as e:
        error_msg: str = f"The embedding request to the provider failed: {e}"
        logger.warning(error_msg)
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, error_msg) from e

    except ValueError as e:
        error_msg: str = f"Not a valid embedding model. Exception thrown: {e}"
        logger.error(error_msg)
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, error_msg) from e

    except Exception as e:
        error_msg: str = "An error occurred while testing your embedding model. Please check your configuration."
        logger.error("%s Error message: %s", error_msg, e, exc_info=True)
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, error_msg)
