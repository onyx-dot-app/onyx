import json
from typing import cast

from agents import function_tool
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.models import GeneratedImage
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.chat.turn.models import ChatTurnContext
from onyx.file_store.utils import build_frontend_file_url
from onyx.file_store.utils import save_files
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolDelta
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolHeartbeat
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationResponse,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


@function_tool
def image_generation_tool(
    run_context: RunContextWrapper[ChatTurnContext], prompt: str, shape: str = "square"
) -> str:
    """
    Generate an image from a text prompt using AI image generation models.

    Args:
        prompt: The text description of the image to generate
        shape: The desired image shape - 'square', 'portrait', or 'landscape'
    """
    try:
        # Get the image generation tool from context
        image_generation_tool = (
            run_context.context.run_dependencies.image_generation_tool
        )
        if image_generation_tool is None:
            raise RuntimeError("Image generation tool not available in context")

        index = run_context.context.current_run_step + 1
        emitter = run_context.context.run_dependencies.emitter

        # Emit start event
        emitter.emit(
            Packet(
                ind=index,
                obj=ImageGenerationToolStart(type="image_generation_tool_start"),
            )
        )

        # Prepare tool arguments
        tool_args = {"prompt": prompt}
        if shape != "square":  # Only include shape if it's not the default
            tool_args["shape"] = shape

        # Run the actual image generation tool with heartbeat handling
        generated_images = []
        heartbeat_count = 0

        for tool_response in image_generation_tool.run(**tool_args):
            # Handle heartbeat responses
            if tool_response.id == "image_generation_heartbeat":
                # Emit heartbeat event for every iteration
                emitter.emit(
                    Packet(
                        ind=index,
                        obj=ImageGenerationToolHeartbeat(
                            type="image_generation_tool_heartbeat"
                        ),
                    )
                )
                heartbeat_count += 1
                logger.debug(f"Image generation heartbeat #{heartbeat_count}")
                continue

            # Process the tool response to get the generated images
            if tool_response.id == "image_generation_response":
                image_generation_responses = cast(
                    list[ImageGenerationResponse], tool_response.response
                )
                file_ids = save_files(
                    urls=[img.url for img in image_generation_responses if img.url],
                    base64_files=[
                        img.image_data
                        for img in image_generation_responses
                        if img.image_data
                    ],
                )
                generated_images = [
                    GeneratedImage(
                        file_id=file_id,
                        url=img.url if img.url else build_frontend_file_url(file_id),
                        revised_prompt=img.revised_prompt,
                    )
                    for img, file_id in zip(image_generation_responses, file_ids)
                ]
                break

        if not generated_images:
            raise RuntimeError("No images were generated")

        run_context.context.aggregated_context.global_iteration_responses.append(
            IterationAnswer(
                tool="image_generation_tool",
                tool_id=2,
                iteration_nr=run_context.context.current_run_step,
                parallelization_nr=0,
                question=prompt,
                answer=generated_images[0].url,
                reasoning="",
                claims=[],
                generated_images=generated_images,
                additional_data={},
                response_type=None,
                data=None,
                file_ids=None,
                cited_documents={},
            )
        )
        # Emit final result
        emitter.emit(
            Packet(
                ind=index,
                obj=ImageGenerationToolDelta(
                    type="image_generation_tool_delta", images=generated_images
                ),
            )
        )

        # Emit section end
        emitter.emit(
            Packet(
                ind=index,
                obj=SectionEnd(
                    type="section_end",
                ),
            )
        )

        run_context.context.current_run_step = index + 1

        # Return all generated images data
        return json.dumps(
            [
                {
                    "file_id": image.file_id,
                    "revised_prompt": image.revised_prompt,
                    "url": image.url,
                }
                for image in generated_images
            ]
        )
    except Exception as e:
        run_context.context.current_run_step = index + 1
        raise e
