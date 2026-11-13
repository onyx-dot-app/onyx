"""Tools that list the user's skills and read their instructions."""

from collections.abc import Sequence
from typing import ClassVar, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from onyx.agents.tools import ToolInvocation
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.skills.content import read_versions_instructions
from onyx.skills.models import ChatSkill
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

    def __init__(self, skills: Sequence[ChatSkill]) -> None:
        self.skills = list(skills)

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
        page = self.skills[request.offset : request.offset + SKILLS_PER_PAGE]
        lines = [f"- {skill.name}: {skill.description}" for skill in page]
        end = request.offset + len(page)
        if end < len(self.skills):
            lines.append(f"{len(self.skills) - end} more skills: use offset={end}.")
        return ToolResult(
            content="\n".join(lines) if lines else "No skills at this offset.",
            details=self._summary({"skills": len(page)}),
        )


class SkillsReadTool(_SkillTool):
    name = SKILLS_READ_TOOL_NAME
    display_name = "Read skill"
    description = (
        "Read the SKILL.md instructions of a skill by name. Read the whole file "
        "before you use the skill."
    )
    arguments = SkillsReadArguments

    def __init__(self, skills: Sequence[ChatSkill], user_id: UUID) -> None:
        super().__init__(skills)
        self.user_id = user_id

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(SkillsReadArguments, invocation.arguments)
        skill = next(
            (skill for skill in self.skills if skill.name == request.name), None
        )
        if skill is None:
            raise ToolCallException(
                message=f"Unknown skill: {request.name}",
                llm_facing_message=(
                    f"No skill is named '{request.name}'. Call "
                    f"{SKILLS_LIST_TOOL_NAME} for the skills you can use."
                ),
            )
        with get_session_with_current_tenant() as db_session:
            instructions = read_versions_instructions(
                [skill.version_id], self.user_id, db_session
            ).get(skill.version_id)
        if instructions is None:
            raise ToolCallException(
                message=f"Unreadable skill: {request.name}",
                llm_facing_message=(
                    f"The instructions of skill '{request.name}' cannot be read now."
                ),
            )
        end = min(request.start_char + SKILL_READ_MAX_CHARS, len(instructions))
        content = instructions[request.start_char : end]
        if end < len(instructions):
            content += (
                f"\n\n[Characters {request.start_char}-{end} of {len(instructions)}. "
                f"Use start_char={end} to continue reading.]"
            )
        return ToolResult(content=content, details=self._summary({"skill": skill.name}))
