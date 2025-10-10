import json
from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.models import GeneratedImage
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.sub_agents.states import BranchInput
from onyx.agents.agent_search.dr.sub_agents.states import BranchUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.file_store.utils import build_frontend_file_url
from onyx.file_store.utils import save_files
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolHeartbeat
from onyx.tools.tool_implementations.images.image_generation_tool import (
    IMAGE_GENERATION_HEARTBEAT_ID,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    IMAGE_GENERATION_RESPONSE_ID,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationResponse,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.images.image_generation_tool import ImageShape
from onyx.utils.logger import setup_logger

logger = setup_logger()


def image_generation(
    state: BranchInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> BranchUpdate:
    """
    LangGraph node to perform a standard search as part of the DR process.
    """

    node_start_time = datetime.now()
    iteration_nr = state.iteration_nr
    parallelization_nr = state.parallelization_nr
    state.assistant_system_prompt
    state.assistant_task_prompt

    branch_query = state.branch_question
    if not branch_query:
        raise ValueError("branch_query is not set")

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    graph_config.inputs.prompt_builder.raw_user_query
    graph_config.behavior.research_type

    if not state.available_tools:
        raise ValueError("available_tools is not set")

    image_tool_info = state.available_tools[state.tools_used[-1]]
    image_tool = cast(ImageGenerationTool, image_tool_info.tool_object)

    image_prompt = branch_query
    requested_shape: ImageShape | None = None

    try:
        parsed_query = json.loads(branch_query)
    except json.JSONDecodeError:
        parsed_query = None

    if isinstance(parsed_query, dict):
        prompt_from_llm = parsed_query.get("prompt")
        if isinstance(prompt_from_llm, str) and prompt_from_llm.strip():
            image_prompt = prompt_from_llm.strip()

        raw_shape = parsed_query.get("shape")
        if isinstance(raw_shape, str):
            try:
                requested_shape = ImageShape(raw_shape)
            except ValueError:
                logger.warning(
                    "Received unsupported image shape '%s' from LLM. Falling back to square.",
                    raw_shape,
                )

    logger.debug(
        f"Image generation start for {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    # Generate images using the image generation tool
    image_generation_responses: list[ImageGenerationResponse] = []

    if requested_shape is not None:
        tool_iterator = image_tool.run(
            prompt=image_prompt,
            shape=requested_shape.value,
        )
    else:
        tool_iterator = image_tool.run(prompt=image_prompt)

    for tool_response in tool_iterator:
        if tool_response.id == IMAGE_GENERATION_HEARTBEAT_ID:
            # Stream heartbeat to frontend
            write_custom_event(
                state.current_step_nr,
                ImageGenerationToolHeartbeat(),
                writer,
            )
        elif tool_response.id == IMAGE_GENERATION_RESPONSE_ID:
            response = cast(list[ImageGenerationResponse], tool_response.response)
            image_generation_responses = response
            break

    # save images to file store
    file_ids = save_files(
        urls=[img.url for img in image_generation_responses if img.url],
        base64_files=[
            img.image_data for img in image_generation_responses if img.image_data
        ],
    )

    final_generated_images = [
        GeneratedImage(
            file_id=file_id,
            url=build_frontend_file_url(file_id),
            revised_prompt=img.revised_prompt,
            shape=(requested_shape or ImageShape.SQUARE).value,
        )
        for file_id, img in zip(file_ids, image_generation_responses)
    ]

    logger.debug(
        f"Image generation complete for {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    # Create answer string describing the generated images
    if final_generated_images:
        image_descriptions = []
        for i, img in enumerate(final_generated_images, 1):
            if img.shape and img.shape != ImageShape.SQUARE.value:
                image_descriptions.append(
                    f"Image {i}: {img.revised_prompt} (shape: {img.shape})"
                )
            else:
                image_descriptions.append(f"Image {i}: {img.revised_prompt}")

        answer_string = (
            f"Generated {len(final_generated_images)} image(s) based on the request: {image_prompt}\n\n"
            + "\n".join(image_descriptions)
        )
        if requested_shape:
            reasoning = (
                "Used image generation tool to create "
                f"{len(final_generated_images)} image(s) in {requested_shape.value} orientation."
            )
        else:
            reasoning = (
                "Used image generation tool to create "
                f"{len(final_generated_images)} image(s) based on the user's request."
            )
    else:
        answer_string = f"Failed to generate images for request: {image_prompt}"
        reasoning = "Image generation tool did not return any results."

    return BranchUpdate(
        branch_iteration_responses=[
            IterationAnswer(
                tool=image_tool_info.llm_path,
                tool_id=image_tool_info.tool_id,
                iteration_nr=iteration_nr,
                parallelization_nr=parallelization_nr,
                question=branch_query,
                answer=answer_string,
                claims=[],
                cited_documents={},
                reasoning=reasoning,
                generated_images=final_generated_images,
            )
        ],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="image_generation",
                node_name="generating",
                node_start_time=node_start_time,
            )
        ],
    )
