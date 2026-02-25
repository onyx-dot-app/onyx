from __future__ import annotations

from typing import Any
from typing import TYPE_CHECKING

from onyx.image_gen.interfaces import ImageGenerationProvider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.image_gen.interfaces import ReferenceImage

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
        if reference_images:
            if not self._model_supports_image_edits(model):
                raise ValueError(
                    f"Model '{model}' does not support image edits with reference images."
                )

            normalized_model = self._normalize_model_name(model)
            if (
                normalized_model == self._DALL_E_2_MODEL_NAME
                and len(reference_images) > 1
            ):
                raise ValueError(
                    "Model 'dall-e-2' only supports a single reference image for edits."
                )

            from litellm import image_edit

            return image_edit(
                image=[image.data for image in reference_images],
                prompt=prompt,
                model=model,
                api_key=self._api_key,
                api_base=self._api_base,
                size=size,
                n=n,
                quality=quality,
                **kwargs,
            )

        from litellm import image_generation

        return image_generation(
            prompt=prompt,
            model=model,
            api_key=self._api_key,
            api_base=self._api_base,
            size=size,
            n=n,
            quality=quality,
            **kwargs,
        )
