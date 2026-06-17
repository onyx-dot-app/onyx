"""Load one attached skill's full instructions on demand (progressive disclosure).

The system prompt only carries a compact INDEX of attached skills (see
``onyx.skills.render``). When the model decides a skill is relevant it calls
this tool with the skill's slug; the tool returns that skill's full SKILL.md
body as the LLM-facing response. Available skills are scoped to THIS turn's
acting-user-visible set (the intersection is applied upstream), so the model
cannot load a skill it isn't entitled to see.
"""

from typing import Any
from typing import cast

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.skills.render import render_skill_body
from onyx.tools.constants import LOAD_SKILL_TOOL_NAME
from onyx.tools.interface import Tool
from onyx.tools.models import CustomToolCallSummary
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.utils import truncate_output
from onyx.utils.logger import setup_logger

logger = setup_logger()

SKILL_SLUG_FIELD = "skill_slug"

# Cap a loaded skill body so a large SKILL.md can't blow the next turn's context.
MAX_SKILL_BODY_CHARS = 50_000


class LoadSkillTool(Tool[None]):
    NAME = LOAD_SKILL_TOOL_NAME
    DISPLAY_NAME = "Load Skill"
    DESCRIPTION = (
        "Load the full instructions for one of this assistant's attached "
        "skills, identified by its slug. Call this when a skill listed in the "
        "attached-skills index is relevant to the user's request, then follow "
        "the returned instructions."
    )

    def __init__(
        self,
        tool_id: int,
        emitter: Emitter,
        available_skills: list[Skill],
        user: User,
    ) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._user = user
        # Pre-filtered to the acting user's visible set for this turn.
        self._skills_by_slug = {skill.slug: skill for skill in available_skills}

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:  # noqa: ARG003
        return True

    @override
    def tool_definition(self) -> dict:
        available = ", ".join(sorted(self._skills_by_slug)) or "(none)"
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        SKILL_SLUG_FIELD: {
                            "type": "string",
                            "description": (
                                "The slug of the attached skill to load, exactly "
                                "as listed in the attached-skills index. "
                                f"Available slugs: {available}."
                            ),
                        },
                    },
                    "required": [SKILL_SLUG_FIELD],
                },
            },
        }

    @override
    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CustomToolStart(tool_name=self.name, tool_id=self._id),
            )
        )

    @override
    def run(
        self,
        placement: Placement,
        override_kwargs: None = None,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        if SKILL_SLUG_FIELD not in llm_kwargs:
            raise ToolCallException(
                message=f"Missing required '{SKILL_SLUG_FIELD}' parameter in load_skill tool call",
                llm_facing_message=(
                    f"The load_skill tool requires a '{SKILL_SLUG_FIELD}' parameter. "
                    f'Provide it like: {{"{SKILL_SLUG_FIELD}": "the-skill-slug"}}'
                ),
            )
        skill_slug = cast(str, llm_kwargs[SKILL_SLUG_FIELD])

        skill = self._skills_by_slug.get(skill_slug)
        if skill is None:
            available = ", ".join(sorted(self._skills_by_slug)) or "(none)"
            llm_facing_response = (
                f"Skill '{skill_slug}' is not available to this assistant. "
                f"Available skill slugs: {available}."
            )
        else:
            # Short-lived session: load_skill is called rarely, so we don't
            # hold a connection for the whole LLM loop (per the loop's no-long-
            # lived-session contract).
            with get_session_with_current_tenant() as db_session:
                body = render_skill_body(skill, db_session, self._user)
            if body is None:
                logger.warning("Skill %s has no readable body to load", skill_slug)
                llm_facing_response = (
                    f"Skill '{skill_slug}' could not be loaded "
                    "(its instructions are unavailable)."
                )
            else:
                llm_facing_response = truncate_output(
                    body, MAX_SKILL_BODY_CHARS, label=f"skill {skill_slug}"
                )

        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CustomToolDelta(
                    tool_name=self.name,
                    tool_id=self._id,
                    response_type="text",
                    data=llm_facing_response,
                ),
            )
        )

        return ToolResponse(
            rich_response=CustomToolCallSummary(
                tool_name=self.name,
                response_type="text",
                tool_result=llm_facing_response,
            ),
            llm_facing_response=llm_facing_response,
        )
