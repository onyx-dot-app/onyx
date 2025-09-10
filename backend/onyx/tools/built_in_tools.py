from typing import Type

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import Tool as ToolDBModel
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.internet_search.internet_search_tool import (
    WebSearchTool,
)
from onyx.tools.tool_implementations.knowledge_graph.knowledge_graph_tool import (
    KnowledgeGraphTool,
)
from onyx.tools.tool_implementations.okta_profile.okta_profile_tool import (
    OktaProfileTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.utils.logger import setup_logger

logger = setup_logger()


# same as d09fc20a3c66_seed_builtin_tools.py
BUILD_IN_TOOL_MAP = {
    SearchTool.__name__: SearchTool,
    ImageGenerationTool.__name__: ImageGenerationTool,
    WebSearchTool.__name__: WebSearchTool,
    KnowledgeGraphTool.__name__: KnowledgeGraphTool,
    OktaProfileTool.__name__: OktaProfileTool,
}


def get_built_in_tool_ids() -> list[str]:
    return list(BUILD_IN_TOOL_MAP.keys())


def get_builtin_tool(
    db_session: Session,
    tool_type: Type[
        SearchTool | ImageGenerationTool | WebSearchTool | KnowledgeGraphTool
    ],
) -> ToolDBModel:
    """
    Retrieves a built-in tool from the database based on the tool type.
    """
    tool_id = next(
        (
            tool["in_code_tool_id"]
            for tool, tool_cls in BUILD_IN_TOOL_MAP.items()
            if tool_cls.__name__ == tool_type.__name__
        ),
        None,
    )

    if not tool_id:
        raise RuntimeError(
            f"Tool type {tool_type.__name__} not found in the BUILT_IN_TOOLS list."
        )

    db_tool = db_session.execute(
        select(ToolDBModel).where(ToolDBModel.in_code_tool_id == tool_id)
    ).scalar_one_or_none()

    if not db_tool:
        raise RuntimeError(f"Tool type {tool_type.__name__} not found in the database.")

    return db_tool


_built_in_tools_cache: dict[str, Type[Tool]] | None = None


def get_built_in_tool_by_id(in_code_tool_id: str) -> Type[Tool]:
    return BUILD_IN_TOOL_MAP[in_code_tool_id]
