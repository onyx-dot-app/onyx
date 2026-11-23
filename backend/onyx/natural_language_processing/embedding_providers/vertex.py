import asyncio
from typing import TYPE_CHECKING

from onyx.natural_language_processing.constants import DEFAULT_VERTEX_MODEL
from onyx.natural_language_processing.embedding_auth import VertexEmbeddingAuth
from onyx.natural_language_processing.embedding_providers.gemini import (
    format_gemini_embedding_text,
    is_gemini_embedding_2_model,
)
from onyx.natural_language_processing.embedding_providers.vertex_credentials import (
    VERTEX_CREDENTIALS,
)
from onyx.natural_language_processing.embedding_request_policy import (
    EmbeddingRequestPolicy,
)
from onyx.utils.logger import setup_logger
from shared_configs.configs import VERTEXAI_EMBEDDING_LOCAL_BATCH_SIZE
from shared_configs.model_server_models import Embedding

if TYPE_CHECKING:
    from google import genai
    from google.genai import types as genai_types

logger = setup_logger()

_CLIENT_CLOSE_TIMEOUT_SECONDS = 5.0


async def embed_with_vertex(
    texts: list[str],
    *,
    auth: VertexEmbeddingAuth,
    policy: EmbeddingRequestPolicy,
    model: str | None,
    embedding_type: str,
    reduced_dimension: int | None,
) -> list[Embedding]:
    from google import genai

    resolved_model = model or DEFAULT_VERTEX_MODEL
    # ADC discovery can contact the GKE metadata server.
    resolved = await asyncio.to_thread(VERTEX_CREDENTIALS.resolve, auth)
    client = genai.Client(
        vertexai=True,
        project=resolved.project_id,
        location=resolved.location,
        credentials=resolved.credentials,
    )
    config = _embed_config(resolved_model, embedding_type, reduced_dimension)

    async def embed_batch(batch_texts: list[str]) -> list[Embedding]:
        contents = _contents(batch_texts, resolved_model, embedding_type)
        response = await policy.send_async(
            lambda: client.aio.models.embed_content(
                model=resolved_model, contents=contents, config=config
            )
        )
        return _embeddings_from(response)

    # Process VertexAI batches sequentially to avoid additional intra-task fanout.
    # The higher-level thread pool already provides concurrency; running these
    # requests in parallel here was causing excessive memory usage.
    batch_size = (
        1
        if is_gemini_embedding_2_model(resolved_model)
        else VERTEXAI_EMBEDDING_LOCAL_BATCH_SIZE
    )
    batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
    all_embeddings: list[Embedding] = []

    logger.debug(
        "VertexAI embedding: processing %s texts in %s batches (batch_size=%s)",
        len(texts),
        len(batches),
        batch_size,
    )

    try:
        for batch_idx, batch in enumerate(batches):
            all_embeddings.extend(await embed_batch(batch))

            # Log progress for large batches to track memory usage patterns
            if batch_idx % 10 == 0 and batch_idx > 0:
                logger.debug(
                    "VertexAI embedding progress: batch %s/%s, total_embeddings=%s",
                    batch_idx,
                    len(batches),
                    len(all_embeddings),
                )

        logger.debug(
            "VertexAI embedding completed: %s embeddings generated",
            len(all_embeddings),
        )
        return all_embeddings
    finally:
        await _close(client)


def _embed_config(
    model: str, embedding_type: str, reduced_dimension: int | None
) -> "genai_types.EmbedContentConfig":
    from google.genai import types as genai_types

    # gemini-embedding-2 rejects task_type; embedding intent is conveyed
    # via the instruction-formatted text instead. Older models continue
    # to use task_type.
    if is_gemini_embedding_2_model(model):
        return genai_types.EmbedContentConfig(
            output_dimensionality=reduced_dimension,
            auto_truncate=True,
        )
    return genai_types.EmbedContentConfig(
        task_type=embedding_type,
        output_dimensionality=reduced_dimension,
        auto_truncate=True,
    )


def _contents(
    texts: list[str], model: str, embedding_type: str
) -> "list[genai_types.ContentUnion]":
    from google.genai import types as genai_types

    return [
        genai_types.Content(
            parts=[
                genai_types.Part(
                    text=format_gemini_embedding_text(
                        text=text, model=model, embedding_type=embedding_type
                    )
                )
            ]
        )
        for text in texts
    ]


def _embeddings_from(
    response: "genai_types.EmbedContentResponse",
) -> list[Embedding]:
    if not response.embeddings:
        raise RuntimeError("Received empty embeddings from Google GenAI.")

    embeddings: list[Embedding] = []
    for idx, embedding in enumerate(response.embeddings):
        if embedding.values is None:
            raise RuntimeError(f"Missing embedding values for input at index {idx}.")
        embeddings.append(embedding.values)
    return embeddings


async def _close(client: "genai.Client") -> None:
    try:
        await asyncio.wait_for(
            client.aio.aclose(), timeout=_CLIENT_CLOSE_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        logger.warning("Google GenAI client aclose() timed out after 5s")
    except Exception as e:
        logger.warning("Error closing Google GenAI client: %s", e)
