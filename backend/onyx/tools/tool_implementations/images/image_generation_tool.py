import json
from collections.abc import Generator
from enum import Enum
from typing import Any
from typing import cast

import requests
from litellm import image_generation  # type: ignore
from pydantic import BaseModel

from onyx.chat.chat_utils import combine_message_chain
from onyx.chat.prompt_builder.build import AnswerPromptBuilder
from onyx.configs.model_configs import GEN_AI_HISTORY_CUTOFF
from onyx.configs.tool_configs import IMAGE_GENERATION_OUTPUT_FORMAT
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.llm.utils import build_content_with_imgs
from onyx.llm.utils import message_to_string
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

YES_IMAGE_GENERATION = "Yes Image Generation"
SKIP_IMAGE_GENERATION = "Skip Image Generation"

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


class ImageGenerationTool(Tool):
    _NAME = "run_image_generation"
    _DESCRIPTION = "Generate an image from a prompt."
    _DISPLAY_NAME = "Image Generation Tool"

    def __init__(
        self,
        api_key: str,
        api_base: str | None,
        api_version: str | None,
        model: str = "dall-e-3",
        num_imgs: int = 2,
        additional_headers: dict[str, str] | None = None,
        output_format: ImageFormat = _DEFAULT_OUTPUT_FORMAT,
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base
        self.api_version = api_version

        self.model = model
        self.num_imgs = num_imgs

        self.additional_headers = additional_headers
        self.output_format = output_format

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def description(self) -> str:
        return self._DESCRIPTION

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

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
        generation_response = args[0]
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
        if shape == ImageShape.LANDSCAPE:
            size = "1792x1024"
        elif shape == ImageShape.PORTRAIT:
            size = "1024x1792"
        else:
            size = "1024x1024"

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

            if format == ImageFormat.URL:
                url = response.data[0]["url"]
                image_data = None
            else:
                url = None
                image_data = response.data[0]["b64_json"]

            return ImageGenerationResponse(
                revised_prompt=response.data[0]["revised_prompt"],
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

    def run(self, **kwargs: str) -> Generator[ToolResponse, None, None]:
        prompt = cast(str, kwargs["prompt"])
        shape = ImageShape(kwargs.get("shape", ImageShape.SQUARE))
        format = self.output_format

        results = cast(
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
        yield ToolResponse(
            id=IMAGE_GENERATION_RESPONSE_ID,
            response=results,
        )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        image_generation_responses = cast(
            list[ImageGenerationResponse], args[0].response
        )
        return [
            image_generation_response.model_dump()
            for image_generation_response in image_generation_responses
        ]

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
        prompt_builder.update_user_prompt(
            build_image_generation_user_prompt(
                query=prompt_builder.get_user_message_content(),
                img_urls=img_urls,
                b64_imgs=b64_imgs,
            )
        )

        return prompt_builder
