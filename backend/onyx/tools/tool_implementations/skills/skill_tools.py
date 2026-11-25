"""Tools that list the user's skills and read their instructions. Each call
reads the user's current skills, as Codex reads the current files."""

from collections.abc import Callable, Mapping, Sequence
from typing import Final, NamedTuple

from pydantic import BaseModel, Field

from onyx.agents.tools import ToolInvocation
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.db.skill import list_chat_skills
from onyx.integrations.plugin_needs import unavailable_need_names
from onyx.llm.model_capabilities import ToolFamily
from onyx.llm.models import SystemMessage, ToolDefinition, ToolResult
from onyx.prompts.skill_prompts import SKILLS_UNAVAILABLE_INTEGRATIONS_LINE
from onyx.skills.chat import render_skills_catalog, truncate_catalog_description
from onyx.skills.content import read_chat_skills_md
from onyx.tools.constants import (
    SKILL_TOOL_NAME,
    SKILLS_LIST_TOOL_NAME,
    SKILLS_READ_TOOL_NAME,
)
from onyx.tools.interface import (
    Tool,
    parse_tool_arguments,
    tool_definition_from_arguments,
)
from onyx.tools.models import (
    CodeModeExposure,
    CodeModeResultKind,
    CodeModeResultSpec,
    CustomToolCallSummary,
    ToolArguments,
    ToolCallException,
    ToolContext,
)
from onyx.tools.ordering import ToolRank

SKILLS_PER_PAGE: Final = 20
SKILL_READ_MAX_CHARS: Final = 32000


class SkillsListArguments(BaseModel):
    offset: int = Field(default=0, ge=0, description="Skills to skip.")


class SkillReadRequest(NamedTuple):
    """A call of the skill read operation: a skill's SKILL.md from a
    character."""

    name: str
    start_char: int


_START_CHAR_DESCRIPTION = "Character offset to continue a long SKILL.md."


class SkillsReadArguments(ToolArguments[SkillReadRequest]):
    name: str = Field(min_length=1, description="Skill name.")
    start_char: int = Field(default=0, ge=0, description=_START_CHAR_DESCRIPTION)

    def request(self) -> SkillReadRequest:
        return SkillReadRequest(name=self.name, start_char=self.start_char)


class SkillArguments(ToolArguments[SkillReadRequest]):
    skill: str = Field(min_length=1, description="The skill name.")
    start_char: int = Field(default=0, ge=0, description=_START_CHAR_DESCRIPTION)

    def request(self) -> SkillReadRequest:
        return SkillReadRequest(name=self.skill, start_char=self.start_char)


class SkillReadShape(NamedTuple):
    """How one tool family names and calls the skill read operation;
    skills_list has one name in every shape."""

    name: str
    arguments: type[ToolArguments[SkillReadRequest]]


SKILL_READ_SHAPES: Mapping[ToolFamily, SkillReadShape] = {
    ToolFamily.OPENAI: SkillReadShape(SKILLS_READ_TOOL_NAME, SkillsReadArguments),
    # The shape Claude models are trained on.
    ToolFamily.CLAUDE: SkillReadShape(SKILL_TOOL_NAME, SkillArguments),
}
# The read tool's names across the shapes and saved chats.
SKILLS_READ_TOOL_NAMES = frozenset(shape.name for shape in SKILL_READ_SHAPES.values())
SKILL_TOOL_NAMES = SKILLS_READ_TOOL_NAMES | {SKILLS_LIST_TOOL_NAME}


class _SkillTool(Tool):
    id = None
    code_mode_exposure = CodeModeExposure.IMMEDIATE
    code_mode_result = CodeModeResultSpec(
        kind=CodeModeResultKind.TEXT, annotation="str"
    )
    arguments: type[BaseModel]

    def __init__(
        self, user: User, read_shape: SkillReadShape, *, with_sandbox: bool
    ) -> None:
        self.user = user
        self.with_sandbox = with_sandbox
        # The skill read tool of the model's tool family, which the tools name.
        self.read_shape = read_shape

    def tool_definition(self) -> ToolDefinition:
        return tool_definition_from_arguments(
            self.name, self.description, self.arguments
        )

    def _summary(self, result: dict[str, str | int]) -> CustomToolCallSummary:
        return CustomToolCallSummary(
            tool_name=self.name, response_type="json", tool_result=result
        )


class SkillsListTool(_SkillTool):
    rank = ToolRank.SKILLS_LIST
    name = SKILLS_LIST_TOOL_NAME
    display_name = "List skills"
    arguments = SkillsListArguments

    @property
    def description(self) -> str:
        return self.describe(str)

    def describe(self, called_name: Callable[[str], str]) -> str:
        return (
            f"List the skills you can use, {SKILLS_PER_PAGE} at a time, with their "
            f"descriptions. Read one with {called_name(self.read_shape.name)}."
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(SkillsListArguments, invocation.arguments)
        with get_session_with_current_tenant() as db_session:
            skills = list_chat_skills(
                db_session, self.user, with_sandbox=self.with_sandbox
            )
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
    """Reads a skill's SKILL.md; the tool family's shape (SKILL_READ_SHAPES)
    names it and takes its arguments."""

    rank = ToolRank.SKILLS_READ
    display_name = "Read skill"
    description = (
        "Read the SKILL.md of a skill by name. Read the whole file before you "
        "use the skill."
    )

    def __init__(
        self, user: User, read_shape: SkillReadShape, *, with_sandbox: bool
    ) -> None:
        super().__init__(user, read_shape, with_sandbox=with_sandbox)
        self.arguments = read_shape.arguments

    @property
    def name(self) -> str:
        return self.read_shape.name

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
        request = parse_tool_arguments(
            self.read_shape.arguments, invocation.arguments
        ).request()
        with get_session_with_current_tenant() as db_session:
            skill = next(
                (
                    skill
                    for skill in list_chat_skills(
                        db_session, self.user, with_sandbox=self.with_sandbox
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
                        f"{context.called_name(SKILLS_LIST_TOOL_NAME)} for the "
                        "skills you can use."
                    ),
                )
            skill_md = read_chat_skills_md(
                [skill], self.user.id, db_session, with_sandbox=self.with_sandbox
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
    tools: Sequence[Tool],
    context_window_tokens: int,
    called_name: Callable[[str], str] = str,
) -> SystemMessage | None:
    """The catalog of the user's current skills, for the prompt of an agent
    that has `skills_list`, naming the skill tools by `called_name`. Chat,
    Deep Research and research agents each build it once, when the agent is
    built, so the prompt stays the same for the agent's steps."""
    list_tool = next((tool for tool in tools if isinstance(tool, SkillsListTool)), None)
    if list_tool is None:
        return None
    with get_session_with_current_tenant() as db_session:
        skills = list_chat_skills(
            db_session, list_tool.user, with_sandbox=list_tool.with_sandbox
        )
        catalog = render_skills_catalog(
            skills,
            context_window_tokens,
            read_tool_name=list_tool.read_shape.name,
            called_name=called_name,
        )
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
