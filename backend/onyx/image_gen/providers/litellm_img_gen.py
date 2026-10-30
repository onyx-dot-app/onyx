from __future__ import annotations

from typing import TYPE_CHECKING, Any

from onyx.image_gen.interfaces import (
    ImageGenerationProvider,
    ImageGenerationProviderCredentials,
    ReferenceImage,
)
from onyx.llm.api_surfaces import OPENAI_COMPATIBLE_SURFACES, resolve_api_surface
from onyx.llm.constants import LlmProviderNames
from onyx.llm.custom_config_mapping import map_custom_config_to_model_kwargs
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call

if TYPE_CHECKING:
    from onyx.image_gen.interfaces import ImageGenerationResponse

_LITELLM_PROVIDER_OVERRIDES: dict[str, str] = {
    LlmProviderNames.GOOGLE: "gemini",
    LlmProviderNames.BEDROCK_CONVERSE: LlmProviderNames.BEDROCK,
}

# Providers whose LiteLLM integration implements image_edit.
_IMAGE_EDIT_PROVIDERS: frozenset[str] = frozenset(
    {
        "openai",
        "azure",
        "azure_ai",
        "litellm_proxy",
        "openrouter",
        "bedrock",
        "gemini",
        "vertex_ai",
    }
)


def resolve_litellm_image_provider(
    provider: str, custom_config: dict[str, str] | None
) -> str:
    if resolve_api_surface(provider, custom_config) in OPENAI_COMPATIBLE_SURFACES:
        return "openai"
    return _LITELLM_PROVIDER_OVERRIDES.get(provider, provider)


class LiteLLMImageGenerationProvider(ImageGenerationProvider):
    """Routes image calls for any LLM provider through LiteLLM's own
    integration for that provider, reusing the provider's stored credentials."""

    def __init__(
        self,
        provider: str,
        credentials: ImageGenerationProviderCredentials,
    ):
        self._provider = provider
        self._litellm_provider = resolve_litellm_image_provider(
            provider, credentials.custom_config
        )
        openai_compatible = (
            resolve_api_surface(provider, credentials.custom_config)
            in OPENAI_COMPATIBLE_SURFACES
        )
        # Same /v1 base and placeholder key the chat path applies.
        self._api_key = credentials.api_key or (
            "not-needed" if openai_compatible else None
        )
        self._api_base = credentials.api_base
        if openai_compatible and self._api_base:
            base = self._api_base.rstrip("/")
            self._api_base = base if base.endswith("/v1") else f"{base}/v1"
        self._api_version = credentials.api_version
        self._deployment_name = credentials.deployment_name
        self._provider_kwargs = map_custom_config_to_model_kwargs(
            model_provider=provider,
            custom_config=credentials.custom_config,
            api_key=credentials.api_key,
            api_base=credentials.api_base,
        ).model_kwargs

    @classmethod
    def validate_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,  # noqa: ARG003
    ) -> bool:
        # Credentials were already validated when the LLM provider was saved.
        return True

    @classmethod
    def _build_from_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> LiteLLMImageGenerationProvider:
        raise NotImplementedError("Use build_for_provider")

    @classmethod
    def build_for_provider(
        cls,
        provider: str,
        credentials: ImageGenerationProviderCredentials,
    ) -> LiteLLMImageGenerationProvider:
        return cls(provider=provider, credentials=credentials)

    @property
    def supports_reference_images(self) -> bool:
        return self._litellm_provider in _IMAGE_EDIT_PROVIDERS

    @property
    def max_reference_images(self) -> int:
        return 14 if self.supports_reference_images else 0

    def _litellm_model(self, model: str) -> str:
        return f"{self._litellm_provider}/{self._deployment_name or model}"

    def _call_kwargs(self) -> dict[str, Any]:
        call_kwargs: dict[str, Any] = {
            **self._provider_kwargs,
            "drop_params": True,
        }
        if self._api_key:
            call_kwargs["api_key"] = self._api_key
        if self._api_base:
            call_kwargs["api_base"] = self._api_base
        if self._api_version:
            call_kwargs["api_version"] = self._api_version
        return call_kwargs

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
        litellm_model = self._litellm_model(model)
        call_kwargs = {**self._call_kwargs(), **kwargs}

        if reference_images:
            if not self.supports_reference_images:
                raise ValueError(
                    f"Provider '{self._provider}' does not support image edits."
                )

            from litellm import image_edit

            with traced_llm_call(
                flow=LLMFlow.IMAGE_EDIT,
                model=model,
                provider=self._provider,
                image_count=n,
                input_messages=[{"role": "user", "content": prompt}],
            ):
                return image_edit(
                    image=[image.data for image in reference_images],
                    prompt=prompt,
                    model=litellm_model,
                    size=size,
                    n=n,
                    quality=quality,
                    **call_kwargs,
                )

        from litellm import image_generation

        with traced_llm_call(
            flow=LLMFlow.IMAGE_GENERATION,
            model=model,
            provider=self._provider,
            image_count=n,
            input_messages=[{"role": "user", "content": prompt}],
        ):
            return image_generation(
                prompt=prompt,
                model=litellm_model,
                size=size,
                n=n,
                quality=quality,
                **call_kwargs,
            )
