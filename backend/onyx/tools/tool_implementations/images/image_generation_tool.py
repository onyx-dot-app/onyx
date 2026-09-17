import json
from concurrent.futures import wait
from typing import Any
from uuid import UUID

import requests
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.agents.tools import ToolInvocation
from onyx.configs.app_configs import IMAGE_MODEL_NAME, IMAGE_MODEL_PROVIDER
from onyx.file_store.models import ChatFileType
from onyx.file_store.utils import (
    build_frontend_file_url,
    load_chat_file_by_id,
    save_files,
)
from onyx.image_gen.factory import get_image_generation_provider
from onyx.image_gen.generation import (
    generate_images_with_provider,
    is_image_generation_configured,
    resolve_image_size,
)
from onyx.image_gen.interfaces import (
    ImageGenerationProviderCredentials,
    ImageShape,
    ReferenceImage,
)
from onyx.llm.models import ToolResult
from onyx.tools.interface import (
    FunctionToolDefinition,
    Tool,
    ToolContext,
    parse_tool_arguments,
)
from onyx.tools.models import GeneratedImage, ToolCallException, ToolExecutionException
from onyx.tools.tool_implementations.images.models import (
    FinalImageGenerationResponse,
    ImageGenerationResponse,
)
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor

logger = setup_logger()

# Heartbeat interval in seconds to prevent timeouts
CANCELLATION_POLL_INTERVAL = 5.0

PROMPT_FIELD = "prompt"
REFERENCE_IMAGE_FILE_IDS_FIELD = "reference_image_file_ids"


class ImageGenerationArguments(BaseModel):
    prompt: str
    shape: ImageShape = ImageShape.SQUARE


class ImageGenerationTool(Tool):
    NAME = "generate_image"
    DESCRIPTION = "Generate an image based on a prompt. Do not use unless the user specifically requests an image."
    DISPLAY_NAME = "Image Generation"

    def __init__(
        self,
        image_generation_credentials: ImageGenerationProviderCredentials,
        tool_id: int,
        chat_session_id: UUID,
        model: str = IMAGE_MODEL_NAME,
        provider: str = IMAGE_MODEL_PROVIDER,
        num_imgs: int = 1,
    ) -> None:
        self.model = model
        self._chat_session_id = chat_session_id
        self.provider = provider
        self.num_imgs = num_imgs

        self.img_provider = get_image_generation_provider(
            provider, image_generation_credentials
        )

        self._id = tool_id

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """Available if a default image generation config exists with valid credentials."""
        return is_image_generation_configured(db_session)

    def tool_definition(self) -> FunctionToolDefinition:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        PROMPT_FIELD: {
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
                        REFERENCE_IMAGE_FILE_IDS_FIELD: {
                            "type": "array",
                            "description": (
                                "Optional file_ids of existing images to edit or use as reference;"
                                " the first is the primary edit source."
                                " Get file_ids from `[attached image — file_id: <id>]` tags on"
                                " user-attached images or from prior generate_image tool responses."
                                " Omit for a fresh, unrelated generation."
                            ),
                            "items": {
                                "type": "string",
                            },
                        },
                    },
                    "required": [PROMPT_FIELD],
                },
            },
        }

    def _generate_image(
        self,
        prompt: str,
        shape: ImageShape,
        reference_images: list[ReferenceImage] | None = None,
    ) -> ImageGenerationResponse:
        size = resolve_image_size(self.model, shape)
        logger.debug("Generating image with model: %s, size: %s", self.model, size)
        try:
            generated = generate_images_with_provider(
                provider=self.img_provider,
                model=self.model,
                prompt=prompt,
                size=size,
                n=1,
                reference_images=reference_images,
            )
            first = generated[0]
            return ImageGenerationResponse(
                revised_prompt=first.revised_prompt,
                image_data=first.b64_data,
            )

        except requests.RequestException as e:
            logger.error("Error fetching or converting image: %s", e)
            raise ToolExecutionException(
                "Failed to fetch or convert the generated image", emit_error_packet=True
            )
        except Exception as e:
            logger.debug("Error occurred during image generation: %s", e)

            error_message = str(e)
            if "OpenAIException" in str(type(e)):
                if (
                    "Your request was rejected as a result of our safety system"
                    in error_message
                ):
                    raise ToolExecutionException(
                        (
                            "The image generation request was rejected due to OpenAI's content policy. "
                            "Please try a different prompt."
                        ),
                        emit_error_packet=True,
                    )
                elif "Invalid image URL" in error_message:
                    raise ToolExecutionException(
                        "Invalid image URL provided for image generation.",
                        emit_error_packet=True,
                    )
                elif "invalid_request_error" in error_message:
                    raise ToolExecutionException(
                        "Invalid request for image generation. Please check your input.",
                        emit_error_packet=True,
                    )

            raise ToolExecutionException(
                f"An error occurred during image generation. error={error_message}",
                emit_error_packet=True,
            )

    def _resolve_reference_image_file_ids(
        self,
        llm_kwargs: dict[str, Any],
    ) -> list[str]:
        raw_reference_ids = llm_kwargs.get(REFERENCE_IMAGE_FILE_IDS_FIELD)
        if raw_reference_ids is None:
            # No references requested — plain generation.
            return []

        if not isinstance(raw_reference_ids, list) or not all(
            isinstance(file_id, str) for file_id in raw_reference_ids
        ):
            raise ToolCallException(
                message=(
                    f"Invalid {REFERENCE_IMAGE_FILE_IDS_FIELD}: expected array of strings, got {type(raw_reference_ids)}"
                ),
                llm_facing_message=(
                    f"The '{REFERENCE_IMAGE_FILE_IDS_FIELD}' field must be an array of file_id strings."
                ),
            )

        # Deduplicate while preserving order (first occurrence wins, so the
        # LLM's intended "primary edit source" stays at index 0).
        deduped_reference_image_ids: list[str] = []
        seen_ids: set[str] = set()
        for file_id in raw_reference_ids:
            file_id = file_id.strip()
            if not file_id or file_id in seen_ids:
                continue
            seen_ids.add(file_id)
            deduped_reference_image_ids.append(file_id)

        if not deduped_reference_image_ids:
            return []

        if not self.img_provider.supports_reference_images:
            raise ToolCallException(
                message=(
                    f"Reference images requested but provider '{self.provider}' does not support image-editing context."
                ),
                llm_facing_message=(
                    "This image provider does not support editing from existing images. "
                    "Try text-only generation, or switch to a provider/model that supports image edits."
                ),
            )

        max_reference_images = self.img_provider.max_reference_images
        if max_reference_images > 0:
            return deduped_reference_image_ids[:max_reference_images]
        return deduped_reference_image_ids

    def _load_reference_images(
        self,
        reference_image_file_ids: list[str],
    ) -> list[ReferenceImage]:
        reference_images: list[ReferenceImage] = []

        for file_id in reference_image_file_ids:
            try:
                loaded_file = load_chat_file_by_id(file_id)
            except Exception as e:
                raise ToolCallException(
                    message=f"Could not load reference image file '{file_id}': {e}",
                    llm_facing_message=(
                        f"Reference image file '{file_id}' could not be loaded. "
                        "Use file_id values returned by previous generate_image calls."
                    ),
                )

            if loaded_file.file_type != ChatFileType.IMAGE:
                raise ToolCallException(
                    message=f"Reference file '{file_id}' is not an image",
                    llm_facing_message=f"Reference file '{file_id}' is not an image.",
                )

            try:
                mime_type = get_image_type_from_bytes(loaded_file.content)
            except Exception as e:
                raise ToolCallException(
                    message=f"Unsupported reference image format for '{file_id}': {e}",
                    llm_facing_message=(
                        f"Reference image '{file_id}' has an unsupported format. Only PNG, JPEG, GIF, and WEBP are supported."
                    ),
                )

            reference_images.append(
                ReferenceImage(
                    data=loaded_file.content,
                    mime_type=mime_type,
                )
            )

        return reference_images

    def run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        if PROMPT_FIELD not in invocation.arguments:
            raise ToolCallException(
                message=f"Missing required '{PROMPT_FIELD}' parameter in generate_image tool call",
                llm_facing_message=(
                    f"The generate_image tool requires a '{PROMPT_FIELD}' parameter describing "
                    f'the image to generate. Please provide like: {{"prompt": "a sunset over mountains"}}'
                ),
            )
        arguments = parse_tool_arguments(ImageGenerationArguments, invocation.arguments)
        prompt = arguments.prompt
        shape = arguments.shape
        reference_image_file_ids = self._resolve_reference_image_file_ids(
            llm_kwargs=invocation.arguments,
        )
        reference_images = self._load_reference_images(reference_image_file_ids)

        executor = ContextThreadPoolExecutor(max_workers=self.num_imgs)
        try:
            futures = [
                executor.submit(
                    lambda: self._generate_image(
                        prompt, shape, reference_images or None
                    )
                )
                for _ in range(self.num_imgs)
            ]
            pending = set(futures)
            while pending:
                invocation.cancellation.check()
                _, pending = wait(pending, timeout=CANCELLATION_POLL_INTERVAL)
            image_generation_responses = [future.result() for future in futures]
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        invocation.cancellation.check()
        # Save files and create GeneratedImage objects
        file_ids = save_files(
            urls=[],
            base64_files=[img.image_data for img in image_generation_responses],
            chat_session_id=self._chat_session_id,
        )
        generated_images_metadata = [
            GeneratedImage(
                file_id=file_id,
                url=build_frontend_file_url(file_id),
                revised_prompt=img.revised_prompt,
                shape=shape.value,
            )
            for img, file_id in zip(image_generation_responses, file_ids, strict=True)
        ]

        final_image_generation_response = FinalImageGenerationResponse(
            generated_images=generated_images_metadata
        )

        content = json.dumps(
            [
                {
                    "file_id": img.file_id,
                    "revised_prompt": img.revised_prompt,
                }
                for img in generated_images_metadata
            ]
        )

        return ToolResult(
            details=final_image_generation_response,
            content=content,
        )
