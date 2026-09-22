from __future__ import annotations

from typing import TYPE_CHECKING, Any

from onyx.image_gen.interfaces import (
    ImageGenerationProvider,
    ImageGenerationProviderCredentials,
    ReferenceImage,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call

if TYPE_CHECKING:
    from onyx.image_gen.interfaces import ImageGenerationResponse


class OpenAIImageGenerationProvider(ImageGenerationProvider):
    _GPT_IMAGE_MODEL_PREFIX = "gpt-image-"
    _DALL_E_2_MODEL_NAME = "dall-e-2"

    def __init__(
        self,
        api_key: str,
        api_base: str | None = None,
    ):
        self._api_key = api_key
        self._api_base = api_base

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
    ) -> OpenAIImageGenerationProvider:
        assert credentials.api_key

        return cls(
            api_key=credentials.api_key,
            api_base=credentials.api_base,
        )

    @property
    def supports_reference_images(self) -> bool:
        return True

    @property
    def max_reference_images(self) -> int:
        # GPT image models support up to 16 input images for edits.
        return 16

    def _normalize_model_name(self, model: str) -> str:
        return model.rsplit("/", 1)[-1]

    def _model_supports_image_edits(self, model: str) -> bool:
        normalized_model = self._normalize_model_name(model)
        return (
            normalized_model.startswith(self._GPT_IMAGE_MODEL_PREFIX)
            or normalized_model == self._DALL_E_2_MODEL_NAME
        )

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
        from onyx.image_gen.providers.pydantic_images import generate_openai_image

        normalized_model = self._normalize_model_name(model)
        if reference_images and not self._model_supports_image_edits(model):
            raise ValueError(
                f"Model '{model}' does not support image edits with reference images."
            )
        if (
            normalized_model == self._DALL_E_2_MODEL_NAME
            and reference_images
            and len(reference_images) > 1
        ):
            raise ValueError(
                "Model 'dall-e-2' only supports a single reference image for edits."
            )
        with traced_llm_call(
            flow=LLMFlow.IMAGE_EDIT if reference_images else LLMFlow.IMAGE_GENERATION,
            model=normalized_model,
            provider="openai",
            image_count=n,
            input_messages=[{"role": "user", "content": prompt}],
        ):
            return generate_openai_image(
                prompt=prompt,
                model=normalized_model,
                size=size,
                n=n,
                quality=quality,
                reference_images=reference_images,
                api_key=self._api_key,
                api_base=self._api_base,
                **kwargs,
            )
