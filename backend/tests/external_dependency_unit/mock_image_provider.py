import abc
import asyncio
import concurrent.futures
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from unittest.mock import patch

from litellm.types.utils import ImageObject
from litellm.types.utils import ImageResponse

from onyx.image_gen.interfaces import ImageGenerationProvider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.llm.interfaces import LLMConfig


class ImageGenerationProviderController(abc.ABC):
    @abc.abstractmethod
    def add_image(
        self,
        data: str,
        delay: float = 0.0,
    ) -> None:
        raise NotImplementedError


class MockImageGenerationProvider(
    ImageGenerationProvider, ImageGenerationProviderController
):
    def __init__(self) -> None:
        self._images: list[str] = []
        self._delays: list[float] = []

    def add_image(
        self,
        data: str,
        delay: float = 0.0,
    ) -> None:
        self._images.append(data)
        self._delays.append(delay)

    @classmethod
    def validate_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,  # noqa: ARG003
    ) -> bool:
        return True

    @classmethod
    def _build_from_credentials(
        cls,
        _: ImageGenerationProviderCredentials,
    ) -> ImageGenerationProvider:
        return cls()

    def generate_image(
        self,
        prompt: str,
        model: str,  # noqa: ARG002
        size: str,  # noqa: ARG002
        n: int,  # noqa: ARG002
        quality: str | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ImageResponse:
        image_data = self._images.pop(0)
        delay = self._delays.pop(0)

        if delay > 0.0:
            try:
                asyncio.get_running_loop()
                # Event loop is running - run sleep in executor to avoid blocking the event loop
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(time.sleep, delay)
                    future.result()
            except RuntimeError:
                # No running event loop, use regular thread sleep
                time.sleep(delay)

        return ImageResponse(
            created=int(datetime.now().timestamp()),
            data=[
                ImageObject(
                    b64_json=image_data,
                    revised_prompt=prompt,
                )
            ],
        )


def _create_mock_image_generation_llm_config() -> LLMConfig:
    """Create a mock LLMConfig for image generation."""
    return LLMConfig(
        model_provider="openai",
        model_name="gpt-image-1",
        temperature=0.0,
        api_key="mock-api-key",
        api_base=None,
        api_version=None,
        deployment_name=None,
        max_input_tokens=100000,
        custom_config=None,
    )


@contextmanager
def use_mock_image_generation_provider() -> (
    Generator[ImageGenerationProviderController, None, None]
):
    image_gen_provider = MockImageGenerationProvider()

    with (
        # Mock the image generation provider factory
        patch(
            "onyx.tools.tool_implementations.images.image_generation_tool.get_image_generation_provider",
            return_value=image_gen_provider,
        ),
        # Mock is_available to return True so the tool is registered
        patch(
            "onyx.tools.tool_implementations.images.image_generation_tool.ImageGenerationTool.is_available",
            return_value=True,
        ),
        # Mock the config lookup in tool_constructor to return a valid LLMConfig
        patch(
            "onyx.tools.tool_constructor._get_image_generation_config",
            return_value=_create_mock_image_generation_llm_config(),
        ),
    ):
        yield image_gen_provider
