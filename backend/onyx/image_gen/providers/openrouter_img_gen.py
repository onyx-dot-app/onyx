from __future__ import annotations

import base64
from datetime import datetime
from typing import Any
from typing import TYPE_CHECKING

import requests

from onyx.image_gen.interfaces import ImageGenerationProvider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.image_gen.interfaces import ReferenceImage
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call

if TYPE_CHECKING:
    from onyx.image_gen.interfaces import ImageGenerationResponse


OPENROUTER_DEFAULT_API_BASE = "https://openrouter.ai/api/v1"


class OpenRouterImageGenerationProvider(ImageGenerationProvider):
    def __init__(
        self,
        api_key: str,
        api_base: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_base = (api_base or OPENROUTER_DEFAULT_API_BASE).rstrip("/")

    @classmethod
    def validate_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> bool:
        return bool(credentials.api_key)

    @classmethod
    def _build_from_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> OpenRouterImageGenerationProvider:
        assert credentials.api_key
        return cls(api_key=credentials.api_key, api_base=credentials.api_base)

    @property
    def supports_reference_images(self) -> bool:
        return True

    @property
    def max_reference_images(self) -> int:
        return 10

    def generate_image(
        self,
        prompt: str,
        model: str,
        size: str,
        n: int,
        quality: str | None = None,
        reference_images: list[ReferenceImage] | None = None,
        **kwargs: Any,
    ) -> ImageGenerationResponse:
        from litellm.types.utils import ImageObject
        from litellm.types.utils import ImageResponse

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "n": n,
        }
        if quality:
            payload["quality"] = quality
        if reference_images:
            payload["input_references"] = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": _reference_image_to_data_url(reference_image),
                    },
                }
                for reference_image in reference_images
            ]

        for key, value in kwargs.items():
            if value is not None and key != "response_format":
                payload[key] = value

        with traced_llm_call(
            flow=LLMFlow.IMAGE_EDIT if reference_images else LLMFlow.IMAGE_GENERATION,
            model=model,
            provider="openrouter",
            input_messages=[{"role": "user", "content": prompt}],
        ):
            response = requests.post(
                f"{self._api_base}/images",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=300,
            )
            response.raise_for_status()

        result = response.json()
        generated_data = [
            ImageObject(
                b64_json=item["b64_json"],
                revised_prompt=item.get("revised_prompt") or prompt,
            )
            for item in result.get("data", [])
            if item.get("b64_json")
        ]
        if not generated_data:
            raise RuntimeError("No image data returned from OpenRouter.")

        return ImageResponse(
            created=result.get("created") or int(datetime.now().timestamp()),
            data=generated_data,
        )


def _reference_image_to_data_url(reference_image: ReferenceImage) -> str:
    encoded = base64.b64encode(reference_image.data).decode("utf-8")
    return f"data:{reference_image.mime_type};base64,{encoded}"
