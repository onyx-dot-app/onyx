import json
import threading
from typing import Any
from typing import cast

import requests
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.configs.app_configs import IMAGE_MODEL_NAME
from onyx.configs.app_configs import IMAGE_MODEL_PROVIDER
from onyx.db.image_generation import get_default_image_generation_config
from onyx.file_store.utils import build_frontend_file_url
from onyx.file_store.utils import save_files
from onyx.image_gen.factory import get_image_generation_provider
from onyx.image_gen.factory import validate_credentials
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import GeneratedImage
from onyx.server.query_and_chat.streaming_models import ImageGenerationFinal
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolHeartbeat
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolExecutionException
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.images.models import (
    FinalImageGenerationResponse,
)
from onyx.tools.tool_implementations.images.models import ImageGenerationResponse
from onyx.tools.tool_implementations.images.models import ImageShape
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()

# Heartbeat interval in seconds to prevent timeouts
HEARTBEAT_INTERVAL = 5.0

PROMPT_FIELD = "prompt"


# override_kwargs is not supported for image generation tools
class ImageGenerationTool(Tool[None]):
    NAME = "generate_image"
    DESCRIPTION = "Generate an image based on a prompt. Do not use unless the user specifically requests an image."
    DISPLAY_NAME = "Image Generation"

    def __init__(
        self,
        image_generation_credentials: ImageGenerationProviderCredentials,
        tool_id: int,
        emitter: Emitter,
        model: str = IMAGE_MODEL_NAME,
        provider: str = IMAGE_MODEL_PROVIDER,
        num_imgs: int = 1,
    ) -> None:
        super().__init__(emitter=emitter)
        self.model = model
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
        try:
            config = get_default_image_generation_config(db_session)
            if not config or not config.model_configuration:
                return False

            llm_provider = config.model_configuration.llm_provider
            credentials = ImageGenerationProviderCredentials(
                api_key=llm_provider.api_key,
                api_base=llm_provider.api_base,
                api_version=llm_provider.api_version,
                deployment_name=llm_provider.deployment_name,
                custom_config=llm_provider.custom_config,
            )
            return validate_credentials(
                provider=llm_provider.provider,
                credentials=credentials,
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
                    },
                    "required": [PROMPT_FIELD],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=ImageGenerationToolStart(),
            )
        )

    def _generate_image(
        self, prompt: str, shape: ImageShape
    ) -> tuple[ImageGenerationResponse, Any]:
        if shape == ImageShape.LANDSCAPE:
            if "gpt-image-1" in self.model:
                size = "1536x1024"
            else:
                size = "1792x1024"
        elif shape == ImageShape.PORTRAIT:
            if "gpt-image-1" in self.model:
                size = "1024x1536"
            else:
                size = "1024x1792"
        else:
            size = "1024x1024"
        logger.debug(f"Generating image with model: {self.model}, size: {size}")
        try:
            response = self.img_provider.generate_image(
                prompt=prompt,
                model=self.model,
                size=size,
                n=1,
                # response_format parameter is not supported for gpt-image-1
                response_format=None if "gpt-image-1" in self.model else "b64_json",
            )

            if not response.data or len(response.data) == 0:
                raise RuntimeError("No image data returned from the API")

            image_item = response.data[0].model_dump()

            image_data = image_item.get("b64_json")
            if not image_data:
                raise RuntimeError("No base64 image data returned from the API")

            revised_prompt = image_item.get("revised_prompt")
            if revised_prompt is None:
                revised_prompt = prompt

            return (
                ImageGenerationResponse(
                    revised_prompt=revised_prompt,
                    image_data=image_data,
                ),
                response,
            )

        except requests.RequestException as e:
            logger.error(f"Error fetching or converting image: {e}")
            raise ToolExecutionException(
                "Failed to fetch or convert the generated image", emit_error_packet=True
            )
        except Exception as e:
            logger.debug(f"Error occurred during image generation: {e}")

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

    def run(
        self,
        placement: Placement,
        override_kwargs: None = None,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        if PROMPT_FIELD not in llm_kwargs:
            raise ToolCallException(
                message=f"Missing required '{PROMPT_FIELD}' parameter in generate_image tool call",
                llm_facing_message=(
                    f"The generate_image tool requires a '{PROMPT_FIELD}' parameter describing "
                    f'the image to generate. Please provide like: {{"prompt": "a sunset over mountains"}}'
                ),
            )
        prompt = cast(str, llm_kwargs[PROMPT_FIELD])
        shape = ImageShape(llm_kwargs.get("shape", ImageShape.SQUARE.value))

        # Use threading to generate images in parallel while emitting heartbeats
        results: list[tuple[ImageGenerationResponse, Any] | None] = [
            None
        ] * self.num_imgs
        completed = threading.Event()
        error_holder: list[Exception | None] = [None]

        # TODO allow the LLM to determine number of images
        def generate_all_images() -> None:
            try:
                generated_results = cast(
                    list[tuple[ImageGenerationResponse, Any]],
                    run_functions_tuples_in_parallel(
                        [
                            (
                                self._generate_image,
                                (
                                    prompt,
                                    shape,
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

        # Emit heartbeat packets while waiting for completion
        heartbeat_count = 0
        while not completed.is_set():
            # Emit a heartbeat packet to prevent timeout
            self.emitter.emit(
                Packet(
                    placement=placement,
                    obj=ImageGenerationToolHeartbeat(),
                )
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

        if not valid_results:
            raise ValueError("No images were generated")

        # Extract ImageGenerationResponse objects
        image_generation_responses = [r[0] for r in valid_results]

        # Save files and create GeneratedImage objects
        file_ids = save_files(
            urls=[],
            base64_files=[img.image_data for img in image_generation_responses],
        )
        generated_images_metadata = [
            GeneratedImage(
                file_id=file_id,
                url=build_frontend_file_url(file_id),
                revised_prompt=img.revised_prompt,
                shape=shape.value,
            )
            for img, file_id in zip(image_generation_responses, file_ids)
        ]

        # Emit final packet with generated images
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=ImageGenerationFinal(images=generated_images_metadata),
            )
        )

        final_image_generation_response = FinalImageGenerationResponse(
            generated_images=generated_images_metadata
        )

        # Create llm_facing_response
        llm_facing_response = json.dumps(
            [
                {
                    "revised_prompt": img.revised_prompt,
                }
                for img in generated_images_metadata
            ]
        )

        return ToolResponse(
            rich_response=final_image_generation_response,
            llm_facing_response=cast(str, llm_facing_response),
        )
