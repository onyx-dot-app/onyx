import json
import threading
from collections.abc import Generator
from enum import Enum
from typing import Any
from typing import cast

import requests
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.chat_utils import combine_message_chain
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.configs.app_configs import AZURE_DALLE_API_KEY
from onyx.configs.app_configs import IMAGE_MODEL_NAME
from onyx.configs.model_configs import GEN_AI_HISTORY_CUTOFF
from onyx.configs.tool_configs import IMAGE_GENERATION_OUTPUT_FORMAT
from onyx.db.llm import fetch_existing_llm_providers
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.llm.utils import build_content_with_imgs
from onyx.llm.utils import message_to_string
from onyx.llm.utils import model_supports_image_input
from onyx.prompts.constants import GENERAL_SEP_PAT
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.images.prompt import (
    build_image_generation_user_prompt,
)
from onyx.utils.headers import build_llm_extra_headers
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel


logger = setup_logger()


IMAGE_GENERATION_RESPONSE_ID = "image_generation_response"
IMAGE_GENERATION_HEARTBEAT_ID = "image_generation_heartbeat"

YES_IMAGE_GENERATION = "Yes Image Generation"
SKIP_IMAGE_GENERATION = "Skip Image Generation"

# Heartbeat interval in seconds to prevent timeouts
HEARTBEAT_INTERVAL = 5.0

IMAGE_GENERATION_TEMPLATE = f"""
Given the conversation history and a follow up query, determine if the system should call \
an external image generation tool to better answer the latest user input.
Your default response is {SKIP_IMAGE_GENERATION}.

Respond "{YES_IMAGE_GENERATION}" if:
- The user is asking for an image to be generated.

Conversation History:
{GENERAL_SEP_PAT}
{{chat_history}}
{GENERAL_SEP_PAT}

If you are at all unsure, respond with {SKIP_IMAGE_GENERATION}.
Respond with EXACTLY and ONLY "{YES_IMAGE_GENERATION}" or "{SKIP_IMAGE_GENERATION}"

Follow Up Input:
{{final_query}}
""".strip()


class ImageFormat(str, Enum):
    URL = "url"
    BASE64 = "b64_json"


_DEFAULT_OUTPUT_FORMAT = ImageFormat(IMAGE_GENERATION_OUTPUT_FORMAT)


class ImageGenerationResponse(BaseModel):
    revised_prompt: str
    url: str | None
    image_data: str | None


class ImageShape(str, Enum):
    SQUARE = "square"
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


# override_kwargs is not supported for image generation tools
class ImageGenerationTool(Tool[None]):
    _NAME = "run_image_generation"
    _DESCRIPTION = "Generate an image from a prompt."
    _DISPLAY_NAME = "Image Generation"

    def __init__(
        self,
        api_key: str,
        api_base: str | None,
        api_version: str | None,
        tool_id: int,
        model: str = IMAGE_MODEL_NAME,
        num_imgs: int = 1,
        additional_headers: dict[str, str] | None = None,
        output_format: ImageFormat = _DEFAULT_OUTPUT_FORMAT,
    ) -> None:

        if model == "gpt-image-1" and output_format == ImageFormat.URL:
            raise ValueError(
                "gpt-image-1 does not support URL format. Please use BASE64 format."
            )

        self.api_key = api_key
        self.api_base = api_base
        self.api_version = api_version

        self.model = model
        self.num_imgs = num_imgs

        self.additional_headers = additional_headers
        self.output_format = output_format

        self._id = tool_id

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def description(self) -> str:
        return self._DESCRIPTION

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """Available if an OpenAI LLM provider is configured in the system."""
        try:
            providers = fetch_existing_llm_providers(db_session)
            return any(
                (provider.provider == "openai" and provider.api_key is not None)
                or (provider.provider == "azure" and AZURE_DALLE_API_KEY is not None)
                for provider in providers
            )
        except Exception:
            logger.exception("Error checking if image generation is available")
            return False

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "Prompt used to generate the image",
                        },
                        "shape": {
                            "type": "string",
                            "description": (
                                "Optional - only specify if you want a specific shape."
                                " Image shape: 'square', 'portrait', or 'landscape'."
                            ),
                            "enum": [shape.value for shape in ImageShape],
                        },
                    },
                    "required": ["prompt"],
                },
            },
        }

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        args = {"prompt": query}
        if force_run:
            return args

        history_str = combine_message_chain(
            messages=history, token_limit=GEN_AI_HISTORY_CUTOFF
        )
        prompt = IMAGE_GENERATION_TEMPLATE.format(
            chat_history=history_str,
            final_query=query,
        )
        use_image_generation_tool_output = message_to_string(llm.invoke(prompt))

        logger.debug(
            f"Evaluated if should use ImageGenerationTool: {use_image_generation_tool_output}"
        )
        if (
            YES_IMAGE_GENERATION.split()[0]
        ).lower() in use_image_generation_tool_output.lower():
            return args

        return None

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        # Filter out heartbeat responses and find the actual image response
        generation_response = None
        for response in args:
            if response.id == IMAGE_GENERATION_RESPONSE_ID:
                generation_response = response
                break

        if generation_response is None:
            raise ValueError("No image generation response found")

        image_generations = cast(
            list[ImageGenerationResponse], generation_response.response
        )

        return build_content_with_imgs(
            message=json.dumps(
                [
                    {
                        "revised_prompt": image_generation.revised_prompt,
                        "url": image_generation.url,
                    }
                    for image_generation in image_generations
                ]
            ),
        )

    def _generate_image(
        self, prompt: str, shape: ImageShape, format: ImageFormat
    ) -> ImageGenerationResponse:
        from litellm import image_generation  # type: ignore

        if shape == ImageShape.LANDSCAPE:
            if self.model == "gpt-image-1":
                size = "1536x1024"
            else:
                size = "1792x1024"
        elif shape == ImageShape.PORTRAIT:
            if self.model == "gpt-image-1":
                size = "1024x1536"
            else:
                size = "1024x1792"
        else:
            size = "1024x1024"
        logger.debug(
            f"Generating image with model: {self.model}, size: {size}, format: {format}"
        )
        try:
            response = image_generation(
                prompt=prompt,
                model=self.model,
                api_key=self.api_key,
                api_base=self.api_base or None,
                api_version=self.api_version or None,
                size=size,
                n=1,
                response_format=format,
                extra_headers=build_llm_extra_headers(self.additional_headers),
            )

            if not response.data or len(response.data) == 0:
                raise RuntimeError("No image data returned from the API")

            image_item = response.data[0].model_dump()

            if format == ImageFormat.URL:
                url = image_item.get("url")
                image_data = None
            else:
                url = None
                image_data = image_item.get("b64_json")

            revised_prompt = image_item.get("revised_prompt")
            if revised_prompt is None:
                revised_prompt = prompt

            return ImageGenerationResponse(
                revised_prompt=revised_prompt,
                url=url,
                image_data=image_data,
            )

        except requests.RequestException as e:
            logger.error(f"Error fetching or converting image: {e}")
            raise ValueError("Failed to fetch or convert the generated image")
        except Exception as e:
            logger.debug(f"Error occurred during image generation: {e}")

            error_message = str(e)
            if "OpenAIException" in str(type(e)):
                if (
                    "Your request was rejected as a result of our safety system"
                    in error_message
                ):
                    raise ValueError(
                        "The image generation request was rejected due to OpenAI's content policy. Please try a different prompt."
                    )
                elif "Invalid image URL" in error_message:
                    raise ValueError("Invalid image URL provided for image generation.")
                elif "invalid_request_error" in error_message:
                    raise ValueError(
                        "Invalid request for image generation. Please check your input."
                    )

            raise ValueError(
                "An error occurred during image generation. Please try again later."
            )

    def run(
        self, override_kwargs: None = None, **kwargs: str
    ) -> Generator[ToolResponse, None, None]:
        prompt = cast(str, kwargs["prompt"])
        shape = ImageShape(kwargs.get("shape", ImageShape.SQUARE))
        format = self.output_format

        # Use threading to generate images in parallel while yielding heartbeats
        results: list[ImageGenerationResponse | None] = [None] * self.num_imgs
        completed = threading.Event()
        error_holder: list[Exception | None] = [None]

        def generate_all_images() -> None:
            try:
                generated_results = cast(
                    list[ImageGenerationResponse],
                    run_functions_tuples_in_parallel(
                        [
                            (
                                self._generate_image,
                                (
                                    prompt,
                                    shape,
                                    format,
                                ),
                            )
                            for _ in range(self.num_imgs)
                        ]
                    ),
                )
                for i, result in enumerate(generated_results):
                    results[i] = result
            except Exception as e:
                error_holder[0] = e
            finally:
                completed.set()

        # Start image generation in background thread
        generation_thread = threading.Thread(target=generate_all_images)
        generation_thread.start()

        # Yield heartbeat packets while waiting for completion
        heartbeat_count = 0
        while not completed.is_set():
            # Yield a heartbeat packet to prevent timeout
            yield ToolResponse(
                id=IMAGE_GENERATION_HEARTBEAT_ID,
                response={
                    "status": "generating",
                    "heartbeat": heartbeat_count,
                },
            )
            heartbeat_count += 1

            # Wait for a short time before next heartbeat
            if completed.wait(timeout=HEARTBEAT_INTERVAL):
                break

        # Ensure thread has completed
        generation_thread.join()

        # Check for errors
        if error_holder[0] is not None:
            raise error_holder[0]

        # Filter out None values (shouldn't happen, but safety check)
        valid_results = [r for r in results if r is not None]

        # Yield the final results
        yield ToolResponse(
            id=IMAGE_GENERATION_RESPONSE_ID,
            response=valid_results,
        )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        # Filter out heartbeat responses and find the actual image response
        for response in args:
            if response.id == IMAGE_GENERATION_RESPONSE_ID:
                image_generation_responses = cast(
                    list[ImageGenerationResponse], response.response
                )
                return [
                    image_generation_response.model_dump()
                    for image_generation_response in image_generation_responses
                ]

        raise ValueError("No image generation response found")

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        img_generation_response = cast(
            list[ImageGenerationResponse] | None,
            next(
                (
                    response.response
                    for response in tool_responses
                    if response.id == IMAGE_GENERATION_RESPONSE_ID
                ),
                None,
            ),
        )
        if img_generation_response is None:
            raise ValueError("No image generation response found")

        img_urls = [img.url for img in img_generation_response if img.url is not None]
        b64_imgs = [
            img.image_data
            for img in img_generation_response
            if img.image_data is not None
        ]

        user_prompt = build_image_generation_user_prompt(
            query=prompt_builder.get_user_message_content(),
            supports_image_input=model_supports_image_input(
                prompt_builder.llm_config.model_name,
                prompt_builder.llm_config.model_provider,
            ),
            prompts=[
                prompt
                for response in img_generation_response
                for prompt in response.revised_prompt
            ],
            img_urls=img_urls,
            b64_imgs=b64_imgs,
        )

        prompt_builder.update_user_prompt(user_prompt)

        return prompt_builder
