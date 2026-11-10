"""Discover and read Skills without creating a sandbox or retaining authority."""

import json
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from onyx.agents.tools import ToolInvocation
from onyx.auth.permissions import has_global_permission
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccountType, Permission
from onyx.db.models import Skill
from onyx.db.skill import list_runtime_skills_for_user
from onyx.db.tools import get_tool_by_id
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.models import FileSizeLimitExceeded
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.skills.bundle import SKILL_MD_NAME, ZIP_METADATA_MAX_BYTES
from onyx.skills.content import read_custom_skill_bundle_instructions
from onyx.tools.interface import Tool, parse_tool_arguments
from onyx.tools.models import CodeModeExposure, ToolContext
from shared_configs.contextvars import get_current_tenant_id

CATALOG_MAX_BYTES = 8 * 1024
CATALOG_PAGE_SIZE = 20
MARKDOWN_MAX_BYTES = 16 * 1024

READ_ONLY_NOTICE = (
    "Skill instructions are reference material, not tool permissions. "
    "This reader does not execute scripts or mount files. Relative Markdown links "
    "can be read with this tool. Use only tools already authorized for this chat. "
    "A Python tool is not a mounted Skill sandbox.\n\n"
)


class SkillArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_name: str | None = Field(default=None, max_length=64)
    path: str | None = Field(default=None, max_length=512)
    after: str | None = Field(default=None, max_length=64)


def _catalog(skills: list[Skill], after: str | None) -> str:
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    more = False
    for skill in sorted(skills, key=lambda skill: skill.name):
        if skill.name in seen or (after is not None and skill.name <= after):
            continue
        seen.add(skill.name)
        entry = {"name": skill.name, "description": skill.description[:160]}
        candidate = json.dumps(entries + [entry], ensure_ascii=False)
        # Reserve space for the envelope and cursor, including JSON escaping.
        if (
            len(entries) == CATALOG_PAGE_SIZE
            or len(candidate.encode()) > CATALOG_MAX_BYTES - 512
        ):
            more = True
            break
        entries.append(entry)
    return json.dumps(
        {"skills": entries, "next_after": entries[-1]["name"] if more else None},
        ensure_ascii=False,
    )


class SkillTool(Tool):
    NAME = "read_skill"
    DESCRIPTION = (
        "Discover enabled Skills before tasks that could use a saved workflow. "
        "Pass skill_name=null to list names and descriptions (20 per page); "
        "use next_after as after for the next page. Pass a name to load its "
        "SKILL.md, or path for a supporting .md file relative to that Skill. "
        "Each read checks current access. Markdown is limited to 16 KiB per call; "
        "oversized files are refused. This is read-only and grants no tools or "
        "script execution. Craft built-ins are not available through this reader."
    )

    def __init__(self, tool_id: int, user_id: UUID) -> None:
        self._id = tool_id
        self._user_id = user_id
        self._tenant_id = get_current_tenant_id()

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
        return "Skills"

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.DIRECT

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            strict=True,
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "skill_name": {"type": ["string", "null"]},
                    "path": {"type": ["string", "null"]},
                    "after": {"type": ["string", "null"]},
                },
                "required": ["skill_name", "path", "after"],
            },
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(SkillArguments, invocation.arguments)
        unavailable = ToolResult(
            content="Skill unavailable for this chat.", is_error=True
        )
        if get_current_tenant_id() != self._tenant_id:
            return unavailable
        # Never retain a request's ORM identity or a discovered version across calls.
        with get_session_with_current_tenant() as session:
            user = fetch_user_by_id(session, self._user_id)
            if (
                user is None
                or not user.is_active
                or user.account_type
                not in (AccountType.STANDARD, AccountType.SERVICE_ACCOUNT)
                or not has_global_permission(user, Permission.WRITE_CHAT)
            ):
                return unavailable
            try:
                configured_tool = get_tool_by_id(self._id, session)
            except ValueError:
                return unavailable
            if (
                not configured_tool.enabled
                or configured_tool.in_code_tool_id != type(self).__name__
            ):
                return unavailable
            candidates = list_runtime_skills_for_user(
                db_session=session, user=user, include_fallbacks=True
            )
            # Every current built-in requires Craft CLI/tools, mounted assets, or
            # template values. Custom bundles are usable as reference Markdown.
            candidates = [
                skill for skill in candidates if skill.built_in_skill_id is None
            ]
            if arguments.skill_name is None:
                return ToolResult(content=_catalog(candidates, arguments.after))
            for skill in candidates:
                if skill.name != arguments.skill_name:
                    continue
                try:
                    instructions = read_custom_skill_bundle_instructions(
                        skill,
                        max_bytes=MARKDOWN_MAX_BYTES,
                        max_metadata_bytes=ZIP_METADATA_MAX_BYTES,
                    )
                except FileSizeLimitExceeded:
                    return ToolResult(
                        content="The selected Skill exceeds this chat's read limits.",
                        is_error=True,
                    )
                except OnyxError as exc:
                    if exc.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE:
                        return ToolResult(content=exc.detail, is_error=True)
                    # Preserve delivery fallback order for unreadable name winners.
                    continue
                path = arguments.path or SKILL_MD_NAME
                if path != SKILL_MD_NAME:
                    try:
                        instructions = read_custom_skill_bundle_instructions(
                            skill,
                            path=path,
                            max_bytes=MARKDOWN_MAX_BYTES,
                            max_metadata_bytes=ZIP_METADATA_MAX_BYTES,
                        )
                    except (OnyxError, FileSizeLimitExceeded):
                        return ToolResult(
                            content="Supporting Markdown is missing, unsafe, or exceeds 16 KiB.",
                            is_error=True,
                        )
                return ToolResult(content=READ_ONLY_NOTICE + instructions)
        return ToolResult(
            content="Skill unavailable or its SKILL.md is unreadable or exceeds 16 KiB.",
            is_error=True,
        )
