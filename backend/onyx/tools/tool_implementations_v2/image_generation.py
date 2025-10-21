from typing import cast

from agents import function_tool
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.models import GeneratedImage
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.chat.stop_signal_checker import is_connected
from onyx.chat.turn.models import ChatTurnContext
from onyx.file_store.utils import build_frontend_file_url
from onyx.file_store.utils import save_files
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolDelta
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolHeartbeat
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationResponse,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting
from onyx.utils.logger import setup_logger

logger = setup_logger()


@tool_accounting
def _image_generation_core(
    run_context: RunContextWrapper[ChatTurnContext],
    prompt: str,
    shape: str,
    image_generation_tool_instance: ImageGenerationTool,
) -> list[GeneratedImage]:
    index = run_context.context.current_run_step
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
    generated_images: list[GeneratedImage] = []
    heartbeat_count = 0

    for tool_response in image_generation_tool_instance.run(
        **tool_args  # type: ignore[arg-type]
    ):
        # Check if the session has been cancelled
        if not is_connected(
            run_context.context.chat_session_id,
            run_context.context.run_dependencies.redis_client,
        ):
            break

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

    run_context.context.iteration_instructions.append(
        IterationInstructions(
            iteration_nr=index,
            plan="Generating images",
            purpose="Generating images",
            reasoning="Generating images",
        )
    )
    run_context.context.aggregated_context.global_iteration_responses.append(
        IterationAnswer(
            tool=image_generation_tool_instance.name,
            tool_id=image_generation_tool_instance.id,
            iteration_nr=run_context.context.current_run_step,
            parallelization_nr=0,
            question=prompt,
            answer="",
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
    emitter.emit(
        Packet(
            ind=index,
            obj=ImageGenerationToolDelta(
                type="image_generation_tool_delta", images=generated_images
            ),
        )
    )

    return generated_images


# failure_error_function=None causes error to be re-raised instead of passing error
# message back to the LLM. This is needed for image_generation since we configure our agent
# to stop at this tool.
@function_tool(failure_error_function=None)
def image_generation(
    run_context: RunContextWrapper[ChatTurnContext], prompt: str, shape: str = "square"
) -> str:
    """
    Generate an image from a text prompt using AI image generation models.

    Args:
        prompt: The text description of the image to generate
        shape: The desired image shape - 'square', 'portrait', or 'landscape'
    """
    image_generation_tool_instance = (
        run_context.context.run_dependencies.image_generation_tool
    )
    assert image_generation_tool_instance is not None

    generated_images: list[GeneratedImage] = _image_generation_core(
        run_context, prompt, shape, image_generation_tool_instance
    )

    # We should stop after this tool is called, so it doesn't matter what it returns
    return f"Successfully generated {len(generated_images)} images"
