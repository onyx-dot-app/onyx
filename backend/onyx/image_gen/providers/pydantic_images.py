"""Image API adapters with per-call credentials and deterministic client cleanup."""

import asyncio
import base64
from typing import Any, cast

from pydantic_ai import BinaryImage, ImageGenerator
from pydantic_ai.images import ImageGenerationResult
from pydantic_ai.images.openai import (
    OpenAIImageGenerationModel,
    OpenAIImageGenerationSettings,
)
from pydantic_ai.providers.openai import OpenAIProvider

from onyx.image_gen.interfaces import (
    ImageGenerationResponse,
    ImageObject,
    ReferenceImage,
)


def image_response(result: ImageGenerationResult) -> ImageGenerationResponse:
    return ImageGenerationResponse(
        created=int(result.timestamp.timestamp()),
        data=[
            ImageObject(
                b64_json=base64.b64encode(image.content.data).decode(),
                revised_prompt=image.revised_prompt,
            )
            for image in result.images
        ],
    )


def generate_openai_image(
    *,
    prompt: str,
    model: str,
    size: str,
    n: int,
    quality: str | None,
    reference_images: list[ReferenceImage] | None,
    api_key: str,
    api_base: str | None,
    api_version: str | None = None,
    deployment: str | None = None,
    **kwargs: Any,
) -> ImageGenerationResponse:
    request_options = dict(kwargs)
    timeout = request_options.pop("timeout", None)

    async def generate() -> ImageGenerationResponse:
        from openai import AsyncAzureOpenAI, AsyncOpenAI

        if api_version and not api_base:
            raise ValueError("Azure image generation requires an API base URL")
        client = (
            AsyncAzureOpenAI(
                api_key=api_key, azure_endpoint=api_base or "", api_version=api_version
            )
            if api_version
            else AsyncOpenAI(api_key=api_key, base_url=api_base)
        )
        if timeout is not None:
            client = client.with_options(timeout=timeout)
        async with client:
            # Pydantic AI rejects DALL-E, which remains a supported saved model.
            if model.startswith("dall-e-"):
                params: dict[str, Any] = {
                    "model": deployment or model,
                    "prompt": prompt,
                    "size": size,
                    "n": n,
                    **request_options,
                }
                if quality is not None:
                    params["quality"] = quality
                if reference_images:
                    response = await client.images.edit(
                        image=[
                            (f"image-{i}.png", image.data, image.mime_type)
                            for i, image in enumerate(reference_images)
                        ],
                        **params,
                    )
                else:
                    response = await client.images.generate(**params)
                return ImageGenerationResponse.model_validate(response.model_dump())
            settings = cast(
                OpenAIImageGenerationSettings,
                {
                    "openai_size": size,
                    "openai_n": n,
                    **{
                        key
                        if key
                        in ("extra_headers", "extra_body", "dimensions", "aspect_ratio")
                        else f"openai_{key}": value
                        for key, value in request_options.items()
                    },
                },
            )
            if quality is not None:
                settings["openai_quality"] = cast(Any, quality)
            provider = OpenAIProvider(openai_client=client)
            image_model = OpenAIImageGenerationModel(model, provider=provider)
            if deployment:
                # Azure routes by deployment; preserve the model profile for validation.
                image_model = OpenAIImageGenerationModel(deployment, provider=provider)
            result = await ImageGenerator(image_model).generate(
                prompt,
                images=[
                    BinaryImage(data=image.data, media_type=image.mime_type)
                    for image in reference_images
                ]
                if reference_images
                else None,
                settings=settings,
            )
            return image_response(result)

    return asyncio.run(generate())
