from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

import requests

from onyx.image_gen.exceptions import ImageProviderCredentialsError
from onyx.image_gen.interfaces import (
    ImageGenerationProvider,
    ImageGenerationProviderCredentials,
    ReferenceImage,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call

if TYPE_CHECKING:
    from onyx.image_gen.interfaces import ImageGenerationResponse


class MiniMaxImageGenerationProvider(ImageGenerationProvider):
    """MiniMax image-01 provider using the regional image-generation API."""

    _DEFAULT_API_BASE = "https://api.minimax.io/v1/image_generation"
    _MODEL_NAMES = frozenset(("image-01", "image-01-live"))
    _ASPECT_RATIOS = {
        "1024x1024": "1:1",
        "1792x1024": "16:9",
        "1024x1792": "9:16",
        "1536x1024": "3:2",
        "1024x1536": "2:3",
    }

    def __init__(self, api_key: str, api_base: str | None = None):
        self._api_key = api_key
        base = (api_base or self._DEFAULT_API_BASE).rstrip("/")
        self._api_base = (
            f"{base}/image_generation" if base.endswith("/v1") else base
        )

    @classmethod
    def validate_credentials(
        cls, credentials: ImageGenerationProviderCredentials
    ) -> bool:
        return bool(credentials.api_key)

    @classmethod
    def _build_from_credentials(
        cls, credentials: ImageGenerationProviderCredentials
    ) -> MiniMaxImageGenerationProvider:
        if not credentials.api_key:
            raise ImageProviderCredentialsError("MiniMax API key is required")
        return cls(api_key=credentials.api_key, api_base=credentials.api_base)

    @property
    def supports_reference_images(self) -> bool:
        return False

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
        if reference_images:
            raise ValueError(
                "MiniMax image generation does not support reference images."
            )

        model_name = model.rsplit("/", 1)[-1]
        if model_name not in self._MODEL_NAMES:
            raise ValueError(f"Unsupported MiniMax image model: {model_name}")

        payload: dict[str, Any] = {
            "model": model_name,
            "prompt": prompt,
            "aspect_ratio": self._ASPECT_RATIOS.get(size, "1:1"),
            "n": n,
            # MiniMax returns generated assets in data.image_urls. Downloading
            # those short-lived URLs lets Onyx retain the same base64 response
            # contract as its other image-generation providers.
            "response_format": "url",
        }
        if quality:
            payload["quality"] = quality
        for field in (
            "subject_reference",
            "width",
            "height",
            "seed",
            "prompt_optimizer",
        ):
            if field in kwargs and kwargs[field] is not None:
                payload[field] = kwargs[field]

        with traced_llm_call(
            flow=LLMFlow.IMAGE_GENERATION,
            model=model_name,
            provider="minimax",
            image_count=n,
            input_messages=[{"role": "user", "content": prompt}],
        ):
            response = requests.post(
                self._api_base,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            response_json = response.json()

        if response_json.get("base_resp", {}).get("status_code") not in (None, 0):
            raise RuntimeError("MiniMax image generation returned an error.")

        image_urls = response_json.get("data", {}).get("image_urls") or []
        if not image_urls:
            raise RuntimeError("MiniMax image generation returned no image URLs.")

        from litellm.types.utils import ImageObject, ImageResponse

        generated = []
        for image_url in image_urls[:n]:
            image_response = requests.get(image_url, timeout=120)
            image_response.raise_for_status()
            generated.append(
                ImageObject(
                    b64_json=base64.b64encode(image_response.content).decode("ascii"),
                    revised_prompt=prompt,
                )
            )
        if not generated:
            raise RuntimeError(
                "MiniMax image generation returned no downloadable images."
            )
        return ImageResponse(data=generated)
