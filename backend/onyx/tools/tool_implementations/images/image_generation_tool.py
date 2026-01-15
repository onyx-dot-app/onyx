import json
import threading
from typing import Any
from typing import cast

import requests
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.configs.app_configs import IMAGE_MODEL_NAME
from onyx.db.image_generation import get_default_image_generation_config
from onyx.file_store.utils import build_frontend_file_url
from onyx.file_store.utils import save_files
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import GeneratedImage
from onyx.server.query_and_chat.streaming_models import ImageGenerationFinal
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolHeartbeat
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
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


# override_kwargs is not supported for image generation tools
class ImageGenerationTool(Tool[None]):
    NAME = "generate_image"
    DESCRIPTION = "Generate an image based on a prompt. Do not use unless the user specifically requests an image."
    DISPLAY_NAME = "Image Generation"

    def __init__(
        self,
        api_key: str,
        api_base: str | None,
        api_version: str | None,
        tool_id: int,
        emitter: Emitter,
        model: str = IMAGE_MODEL_NAME,
        num_imgs: int = 1,
    ) -> None:
        super().__init__(emitter=emitter)

        self.api_key = api_key
        self.api_base = api_base
        self.api_version = api_version

        self.model = model
        self.num_imgs = num_imgs

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
            return llm_provider is not None and llm_provider.api_key is not None
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
        from litellm import image_generation

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
            response = image_generation(
                prompt=prompt,
                model=self.model,
                api_key=self.api_key,
                api_base=self.api_base or None,
                api_version=self.api_version or None,
                # response_format parameter is not supported for gpt-image-1
                response_format=None if "gpt-image-1" in self.model else "b64_json",
                size=size,
                n=1,
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
        self,
        placement: Placement,
        override_kwargs: None = None,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        prompt = cast(str, llm_kwargs["prompt"])
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
