from typing import cast

from agents import function_tool
from agents import RunContextWrapper

from onyx.chat.stop_signal_checker import is_connected
from onyx.chat.turn.models import ChatTurnContext
from onyx.server.query_and_chat.streaming_models import GeneratedImage
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
    run_context.context.current_run_step
    run_context.context.run_dependencies.emitter

    # Emit start event
    # emitter.emit(
    #     Packet(
    #         ind=index,
    #         obj=ImageGenerationToolStart(type="image_generation_tool_start"),
    #     )
    # )

    # Prepare tool arguments
    tool_args = {"prompt": prompt}
    if shape != "square":  # Only include shape if it's not the default
        tool_args["shape"] = shape

    # Run the actual image generation tool with heartbeat handling
    generated_images: list[GeneratedImage] = []

    for tool_response in image_generation_tool_instance.run(
        **tool_args  # type: ignore[arg-type]
    ):
        # Check if the session has been cancelled
        if not is_connected(
            run_context.context.chat_session_id,
            run_context.context.run_dependencies.redis_client,
        ):
            break

        # # Handle heartbeat responses
        # if tool_response.id == "image_generation_heartbeat":
        #     # Emit heartbeat event for every iteration
        #     emitter.emit(
        #         Packet(
        #             ind=index,
        #             obj=ImageGenerationToolHeartbeat(
        #                 type="image_generation_tool_heartbeat"
        #             ),
        #         )
        #     )
        #     heartbeat_count += 1
        #     logger.debug(f"Image generation heartbeat #{heartbeat_count}")
        #     continue

        # Process the tool response to get the generated images
        # if tool_response.id == "image_generation_response":
        #     image_generation_responses = cast(
        #         list[ImageGenerationResponse], tool_response.response
        #     )
        #     file_ids = save_files(
        #         urls=[],
        #         base64_files=[img.image_data for img in image_generation_responses],
        #     )
        #     generated_images = [
        #         GeneratedImage(
        #             file_id=file_id,
        #             url=build_frontend_file_url(file_id),
        #             revised_prompt=img.revised_prompt,
        #         )
        #         for img, file_id in zip(image_generation_responses, file_ids)
        #     ]
        #     break

    # emitter.emit(
    #     Packet(
    #         ind=index,
    #         obj=ImageGenerationFinal(
    #             type="image_generation_tool_delta", images=generated_images
    #         ),
    #     )
    # )

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
    image_generation_tool_instance = next(
        (
            tool
            for tool in run_context.context.run_dependencies.tools
            if tool.name == ImageGenerationTool.NAME
        ),
        None,
    )
    if image_generation_tool_instance is None:
        raise ValueError("Image generation tool not found")

    generated_images: list[GeneratedImage] = _image_generation_core(
        run_context,
        prompt,
        shape,
        cast(ImageGenerationTool, image_generation_tool_instance),
    )

    # We should stop after this tool is called, so it doesn't matter what it returns
    return f"Successfully generated {len(generated_images)} images"
