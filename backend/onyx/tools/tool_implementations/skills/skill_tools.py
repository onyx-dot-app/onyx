"""Tools that list the user's skills and read their instructions. Each call
reads the user's current skills, as Codex reads the current files."""

from collections.abc import Sequence
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field

from onyx.agents.tools import ToolInvocation
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.db.skill import list_chat_skills
from onyx.integrations.plugin_needs import unavailable_need_names
from onyx.llm.models import SystemMessage, ToolDefinition, ToolResult
from onyx.prompts.skill_prompts import SKILLS_UNAVAILABLE_INTEGRATIONS_LINE
from onyx.skills.chat import render_skills_catalog, truncate_catalog_description
from onyx.skills.content import read_chat_skills_md
from onyx.tools.constants import SKILLS_LIST_TOOL_NAME, SKILLS_READ_TOOL_NAME
from onyx.tools.interface import (
    Tool,
    parse_tool_arguments,
    tool_definition_from_arguments,
)
from onyx.tools.models import (
    CodeModeExposure,
    CustomToolCallSummary,
    ToolCallException,
    ToolContext,
)

SKILLS_PER_PAGE: Final = 20
SKILL_READ_MAX_CHARS: Final = 32000


class SkillsListArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset: int = Field(default=0, ge=0, description="Skills to skip.")


class SkillsReadArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Skill name.")
    start_char: int = Field(
        default=0, ge=0, description="Character offset to continue a long SKILL.md."
    )


class _SkillTool(Tool):
    id = None
    code_mode_exposure = CodeModeExposure.DIRECT
    arguments: ClassVar[type[BaseModel]]

    def __init__(self, user: User, *, built_ins: bool) -> None:
        self.user = user
        self.built_ins = built_ins

    def tool_definition(self) -> ToolDefinition:
        return tool_definition_from_arguments(
            self.name, self.description, self.arguments
        )

    def _summary(self, result: dict[str, str | int]) -> CustomToolCallSummary:
        return CustomToolCallSummary(
            tool_name=self.name, response_type="json", tool_result=result
        )


class SkillsListTool(_SkillTool):
    name = SKILLS_LIST_TOOL_NAME
    display_name = "List skills"
    description = (
        f"List the skills you can use, {SKILLS_PER_PAGE} at a time, with their "
        f"descriptions. Read one with {SKILLS_READ_TOOL_NAME}."
    )
    arguments = SkillsListArguments

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(SkillsListArguments, invocation.arguments)
        with get_session_with_current_tenant() as db_session:
            skills = list_chat_skills(db_session, self.user, built_ins=self.built_ins)
        page = skills[request.offset : request.offset + SKILLS_PER_PAGE]
        lines = [
            f"- {skill.name}: {truncate_catalog_description(skill.description)}"
            for skill in page
        ]
        end = request.offset + len(page)
        if end < len(skills):
            lines.append(f"{len(skills) - end} more skills: use offset={end}.")
        return ToolResult(
            content="\n".join(lines) if lines else "No skills at this offset.",
            details=self._summary({"skills": len(page)}),
        )


class SkillsReadTool(_SkillTool):
    name = SKILLS_READ_TOOL_NAME
    display_name = "Read skill"
    description = (
        "Read the SKILL.md of a skill by name. Read the whole file before you "
        "use the skill."
    )
    arguments = SkillsReadArguments

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(SkillsReadArguments, invocation.arguments)
        with get_session_with_current_tenant() as db_session:
            skill = next(
                (
                    skill
                    for skill in list_chat_skills(
                        db_session, self.user, built_ins=self.built_ins
                    )
                    if skill.name == request.name
                ),
                None,
            )
            if skill is None:
                raise ToolCallException(
                    message=f"Unknown skill: {request.name}",
                    llm_facing_message=(
                        f"No skill is named '{request.name}'. Call "
                        f"{SKILLS_LIST_TOOL_NAME} for the skills you can use."
                    ),
                )
            skill_md = read_chat_skills_md(
                [skill], self.user.id, db_session, sandbox=self.built_ins
            ).get((skill.version_id, skill.path))
        if skill_md is None:
            raise ToolCallException(
                message=f"Unreadable skill: {request.name}",
                llm_facing_message=(
                    f"The SKILL.md of skill '{request.name}' cannot be read now."
                ),
            )
        end = min(request.start_char + SKILL_READ_MAX_CHARS, len(skill_md))
        content = skill_md[request.start_char : end]
        if end < len(skill_md):
            content += (
                f"\n\n[Characters {request.start_char}-{end} of {len(skill_md)}. "
                f"Use start_char={end} to continue reading.]"
            )
        return ToolResult(content=content, details=self._summary({"skill": skill.name}))


def skills_catalog_message(
    tools: Sequence[Tool], context_window_tokens: int
) -> SystemMessage | None:
    """The catalog of the user's current skills, for the prompt of an agent
    that has `skills_list`. Chat, Deep Research and research agents each
    build it once, when the agent is built, so the prompt stays the same for
    the agent's steps."""
    list_tool = next((tool for tool in tools if isinstance(tool, SkillsListTool)), None)
    if list_tool is None:
        return None
    with get_session_with_current_tenant() as db_session:
        skills = list_chat_skills(
            db_session, list_tool.user, built_ins=list_tool.built_ins
        )
        catalog = render_skills_catalog(skills, context_window_tokens)
        if catalog is None:
            return None
        unavailable = unavailable_need_names(
            list_tool.user, {skill.version_id for skill in skills}, db_session
        )
    if unavailable:
        catalog += "\n" + SKILLS_UNAVAILABLE_INTEGRATIONS_LINE.format(
            names=", ".join(unavailable)
        )
    return SystemMessage(content=catalog)
