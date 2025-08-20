from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.sub_agents.states import BranchInput
from onyx.agents.agent_search.dr.sub_agents.states import BranchUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
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

    logger.debug(
        f"Image generation start for {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    # Generate images using the image generation tool
    generated_images: list[ImageGenerationResponse] = []

    for tool_response in image_tool.run(prompt=branch_query):
        if tool_response.id == IMAGE_GENERATION_RESPONSE_ID:
            response = cast(list[ImageGenerationResponse], tool_response.response)
            generated_images = response
            break

    logger.debug(
        f"Image generation complete for {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    # Create answer string describing the generated images
    if generated_images:
        image_descriptions = []
        for i, img in enumerate(generated_images, 1):
            image_descriptions.append(f"Image {i}: {img.revised_prompt}")

        answer_string = (
            f"Generated {len(generated_images)} image(s) based on the request: {branch_query}\n\n"
            + "\n".join(image_descriptions)
        )
        reasoning = f"Used image generation tool to create {len(generated_images)} image(s) based on the user's request."
    else:
        answer_string = f"Failed to generate images for request: {branch_query}"
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
                additional_data=(
                    {"generated_images": str(len(generated_images))}
                    if generated_images
                    else None
                ),
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
