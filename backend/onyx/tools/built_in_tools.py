import os
from typing import Type

from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.knowledge_graph.knowledge_graph_tool import (
    KnowledgeGraphTool,
)
from onyx.tools.tool_implementations.okta_profile.okta_profile_tool import (
    OktaProfileTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import (
    WebSearchTool,
)
from onyx.utils.logger import setup_logger
from sqlalchemy.orm import Session

logger = setup_logger()


BUILT_IN_TOOL_MAP: dict[str, Type[Tool]] = {
    SearchTool.__name__: SearchTool,
    ImageGenerationTool.__name__: ImageGenerationTool,
    WebSearchTool.__name__: WebSearchTool,
    KnowledgeGraphTool.__name__: KnowledgeGraphTool,
    OktaProfileTool.__name__: OktaProfileTool,
}


def get_built_in_tool_ids() -> list[str]:
    return list(BUILT_IN_TOOL_MAP.keys())


def load_builtin_tools(db_session: Session) -> None:
    existing_in_code_tools = db_session.scalars(
        select(ToolDBModel).where(not_(ToolDBModel.in_code_tool_id.is_(None)))
    ).all()
    in_code_tool_id_to_tool = {
        tool.in_code_tool_id: tool for tool in existing_in_code_tools
    }

    # Add or update existing tools
    for tool_info in BUILT_IN_TOOLS:
        tool_name = tool_info["cls"].__name__
        tool = in_code_tool_id_to_tool.get(tool_info["in_code_tool_id"])
        if tool:
            # Update existing tool
            tool.name = tool_name
            tool.description = tool_info["description"]
            tool.display_name = tool_info["display_name"]
            logger.notice(f"Updated tool: {tool_name}")
        else:
            # Add new tool
            new_tool = ToolDBModel(
                name=tool_name,
                description=tool_info["description"],
                display_name=tool_info["display_name"],
                in_code_tool_id=tool_info["in_code_tool_id"],
            )
            db_session.add(new_tool)
            logger.notice(f"Added new tool: {tool_name}")

    # Remove tools that are no longer in BUILT_IN_TOOLS
    built_in_ids = {tool_info["in_code_tool_id"] for tool_info in BUILT_IN_TOOLS}
    for tool_id, tool in list(in_code_tool_id_to_tool.items()):
        if tool_id not in built_in_ids:
            db_session.delete(tool)
            logger.notice(f"Removed action no longer in built-in list: {tool.name}")

    db_session.commit()
    logger.notice("All built-in tools are loaded/verified.")


def get_builtin_tool(
    db_session: Session,
    tool_type: Type[
        SearchTool | ImageGenerationTool | InternetSearchTool | KnowledgeGraphTool
    ],
) -> ToolDBModel:
    """
    Retrieves a built-in tool from the database based on the tool type.
    """
    tool_id = next(
        (
            tool["in_code_tool_id"]
            for tool in BUILT_IN_TOOLS
            if tool["cls"].__name__ == tool_type.__name__
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


def auto_add_search_tool_to_personas(db_session: Session) -> None:
    """
    Automatically adds the SearchTool to all Persona objects in the database that have
    `num_chunks` either unset or set to a value that isn't 0. This is done to migrate
    Persona objects that were created before the concept of Tools were added.
    """
    # Fetch the SearchTool from the database based on in_code_tool_id from BUILT_IN_TOOLS
    search_tool = get_builtin_tool(db_session=db_session, tool_type=SearchTool)

    # Fetch all Personas that need the SearchTool added
    personas_to_update = (
        db_session.execute(
            select(Persona).where(
                or_(Persona.num_chunks.is_(None), Persona.num_chunks != 0)
            )
        )
        .scalars()
        .all()
    )

    # Add the SearchTool to each relevant Persona
    for persona in personas_to_update:
        if search_tool not in persona.tools:
            persona.tools.append(search_tool)
            logger.notice(f"Added SearchTool to Persona ID: {persona.id}")

    # Commit changes to the database
    db_session.commit()
    logger.notice("Completed adding SearchTool to relevant Personas.")


_built_in_tools_cache: dict[str, Type[Tool]] | None = None


def refresh_built_in_tools_cache(db_session: Session) -> None:
    global _built_in_tools_cache
    _built_in_tools_cache = {}
    all_tool_built_in_tools = (
        db_session.execute(
            select(ToolDBModel).where(not_(ToolDBModel.in_code_tool_id.is_(None)))
        )
        .scalars()
        .all()
    )
    for tool in all_tool_built_in_tools:
        tool_info = next(
            (
                item
                for item in BUILT_IN_TOOLS
                if item["in_code_tool_id"] == tool.in_code_tool_id
            ),
            None,
        )
        if tool_info and tool.in_code_tool_id:
            _built_in_tools_cache[tool.in_code_tool_id] = tool_info["cls"]


def get_built_in_tool_by_id(
    in_code_tool_id: str, db_session: Session, force_refresh: bool = False
) -> Type[Tool]:
    global _built_in_tools_cache

    # If the tool is not in the cache, refresh it once
    if (
        _built_in_tools_cache is None
        or force_refresh
        or in_code_tool_id not in _built_in_tools_cache
    ):
        refresh_built_in_tools_cache(db_session)

    if _built_in_tools_cache is None:
        raise RuntimeError(
            "Built-in tools cache is None despite being refreshed. Should never happen."
        )

    if in_code_tool_id not in _built_in_tools_cache:
        raise ValueError(
            f"No built-in tool found in the cache with ID {in_code_tool_id}"
        )

    return _built_in_tools_cache[in_code_tool_id]
