import asyncio
from collections.abc import Callable, Coroutine
from functools import partial
from typing import TYPE_CHECKING

from onyx.connectors.models import ConnectorStopSignal
from onyx.natural_language_processing.constants import DEFAULT_VERTEX_MODEL
from onyx.natural_language_processing.embedding_auth import VertexEmbeddingAuth
from onyx.natural_language_processing.embedding_providers.gemini import (
    format_gemini_embedding_text,
    gemini_base_model_name,
    is_gemini_embedding_2_model,
)
from onyx.natural_language_processing.embedding_providers.vertex_batching import (
    is_token_limit_error,
    vertex_batches,
)
from onyx.natural_language_processing.embedding_providers.vertex_credentials import (
    VERTEX_CREDENTIALS,
)
from onyx.natural_language_processing.embedding_providers.vertex_scheduler import (
    VERTEX_SCHEDULER,
)
from onyx.natural_language_processing.embedding_rate_limit import (
    EmbeddingWaitTimeoutError,
)
from onyx.natural_language_processing.embedding_request_policy import (
    EmbeddingRequestPolicy,
)
from onyx.natural_language_processing.exceptions import EmbeddingRequestFailedError
from onyx.utils.logger import setup_logger
from shared_configs.model_server_models import Embedding

if TYPE_CHECKING:
    from google import genai
    from google.genai import types as genai_types

logger = setup_logger()

_CLIENT_CLOSE_TIMEOUT_SECONDS = 5.0
# The SDK sets no timeout, and a hung request holds its scheduler slot.
_REQUEST_TIMEOUT_SECONDS = 60.0
# `embed()` does not retry these. It retries the other errors.
_ERRORS_THAT_END_THE_CALL = (ConnectorStopSignal, EmbeddingWaitTimeoutError)


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
    from google.genai import types as genai_types

    resolved_model = model or DEFAULT_VERTEX_MODEL
    # ADC discovery can contact the GKE metadata server.
    resolved = await asyncio.to_thread(VERTEX_CREDENTIALS.resolve, auth)
    client = genai.Client(
        vertexai=True,
        project=resolved.project_id,
        location=resolved.location,
        credentials=resolved.credentials,
        http_options=genai_types.HttpOptions(
            timeout=int(_REQUEST_TIMEOUT_SECONDS * 1000)
        ),
    )
    config = _embed_config(resolved_model, embedding_type, reduced_dimension)
    # Vertex counts quota per base model, so each name of a model shares a limit.
    scheduler_key = (
        f"{resolved.project_id}/{resolved.location}/"
        f"{gemini_base_model_name(resolved_model)}"
    )

    async def send_batch(batch_texts: list[str]) -> list[Embedding]:
        request = partial(
            client.aio.models.embed_content,
            model=resolved_model,
            contents=_contents(batch_texts, resolved_model, embedding_type),
            config=config,
        )
        response = await VERTEX_SCHEDULER.send(scheduler_key, request, policy)
        return _embeddings_from(response)

    async def embed_batch(batch_texts: list[str]) -> list[Embedding]:
        try:
            return await send_batch(batch_texts)
        except Exception as e:
            if len(batch_texts) == 1 or not is_token_limit_error(e):
                raise
        half = len(batch_texts) // 2
        return await _embed_in_parallel(
            [batch_texts[:half], batch_texts[half:]], embed_batch
        )

    batches = vertex_batches(texts, resolved_model)
    logger.debug(
        "VertexAI embedding: processing %s texts in %s batches",
        len(texts),
        len(batches),
    )
    try:
        return await _embed_in_parallel(batches, embed_batch)
    except Exception as e:
        if _resending_does_not_help(e):
            raise EmbeddingRequestFailedError(f"{type(e).__name__}: {e}") from e
        raise
    finally:
        await _close(client)


def _resending_does_not_help(error: Exception) -> bool:
    # CloudEmbedding.embed resends a failed call with all of its inputs,
    # including the ones that succeeded. It does not resend this error type.
    # Transient errors stay resendable: the scheduler's short resends do not
    # cover an outage of a few seconds.
    from google.genai import errors as genai_errors

    if isinstance(error, TimeoutError):
        return True
    return isinstance(error, genai_errors.ClientError) and error.code not in (
        401,
        403,
        429,
    )


async def _embed_in_parallel(
    batches: list[list[str]],
    embed_batch: Callable[[list[str]], Coroutine[None, None, list[Embedding]]],
) -> list[Embedding]:
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(embed_batch(batch)) for batch in batches]
    except ExceptionGroup as errors:
        # Callers match on the request's own error type. A stop or a wait
        # timeout goes first, so an error that `embed()` retries cannot hide it.
        raise next(
            (e for e in errors.exceptions if isinstance(e, _ERRORS_THAT_END_THE_CALL)),
            errors.exceptions[0],
        ) from None
    return [embedding for task in tasks for embedding in task.result()]


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
