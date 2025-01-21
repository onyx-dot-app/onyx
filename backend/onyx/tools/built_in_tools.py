import os
from typing import Type
from typing_extensions import TypedDict  # noreorder

from sqlalchemy import not_
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import Persona
from onyx.db.models import Tool as ToolDBModel
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.internet_search.internet_search_tool import (
    InternetSearchTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger

logger = setup_logger()


class InCodeToolInfo(TypedDict):
    cls: Type[Tool]
    description: str
    in_code_tool_id: str
    display_name: str


BUILT_IN_TOOLS: list[InCodeToolInfo] = [
    InCodeToolInfo(
        cls=SearchTool,
        description="The Search Tool allows the Assistant to search through connected knowledge to help build an answer.",
        in_code_tool_id=SearchTool.__name__,
        display_name=SearchTool._DISPLAY_NAME,
    ),
    InCodeToolInfo(
        cls=ImageGenerationTool,
        description=(
            "The Image Generation Tool allows the assistant to use DALL-E 3 to generate images. "
            "The tool will be used when the user asks the assistant to generate an image."
        ),
        in_code_tool_id=ImageGenerationTool.__name__,
        display_name=ImageGenerationTool._DISPLAY_NAME,
    ),
    # don't show the InternetSearchTool as an option if BING_API_KEY is not available
    *(
        [
            InCodeToolInfo(
                cls=InternetSearchTool,
                description=(
                    "The Internet Search Tool allows the assistant "
                    "to perform internet searches for up-to-date information."
                ),
                in_code_tool_id=InternetSearchTool.__name__,
                display_name=InternetSearchTool._DISPLAY_NAME,
            )
        ]
        if os.environ.get("BING_API_KEY")
        else []
    ),
]


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
            logger.notice(f"Removed tool no longer in built-in list: {tool.name}")

    db_session.commit()
    logger.notice("All built-in tools are loaded/verified.")


def get_search_tool(db_session: Session) -> ToolDBModel | None:
    """
    Retrieves for the SearchTool from the BUILT_IN_TOOLS list.
    """
    search_tool_id = next(
        (
            tool["in_code_tool_id"]
            for tool in BUILT_IN_TOOLS
            if tool["cls"].__name__ == SearchTool.__name__
        ),
        None,
    )

    if not search_tool_id:
        raise RuntimeError("SearchTool not found in the BUILT_IN_TOOLS list.")

    search_tool = db_session.execute(
        select(ToolDBModel).where(ToolDBModel.in_code_tool_id == search_tool_id)
    ).scalar_one_or_none()

    return search_tool


def auto_add_search_tool_to_personas(db_session: Session) -> None:
    """
    Automatically adds the SearchTool to all Persona objects in the database that have
    `num_chunks` either unset or set to a value that isn't 0. This is done to migrate
    Persona objects that were created before the concept of Tools were added.
    """
    # Fetch the SearchTool from the database based on in_code_tool_id from BUILT_IN_TOOLS
    search_tool = get_search_tool(db_session)

    if not search_tool:
        raise RuntimeError("SearchTool not found in the database.")

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
