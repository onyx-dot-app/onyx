"""Agent Skills metadata parsing, validation, and serialization."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from typing import Final

import yaml
from pydantic import ValidationError

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.models import SkillDocument
from onyx.skills.models import SkillMetadata

_FRONTMATTER_REGEX: Final[re.Pattern[str]] = re.compile(
    r"\A---[ \t]*\r?\n(?P<frontmatter>.*?)(?:\r?\n)---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)


def split_skill_md(raw: bytes) -> tuple[str, str]:
    """Return the raw frontmatter YAML and Markdown body."""
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "SKILL.md must be UTF-8 encoded",
        ) from exc
    match = _FRONTMATTER_REGEX.match(content)
    if match is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "SKILL.md must start with YAML frontmatter delimited by two --- lines",
        )
    return match.group("frontmatter"), content[match.end() :]


def parse_skill_md_frontmatter(raw: bytes) -> tuple[dict[Any, Any], str]:
    """Parse frontmatter without applying the current metadata schema."""
    frontmatter_yaml, instructions_markdown = split_skill_md(raw)

    try:
        parsed = yaml.safe_load(frontmatter_yaml)
    except yaml.YAMLError as exc:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"SKILL.md frontmatter is not valid YAML: {exc}",
        ) from exc
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "SKILL.md frontmatter must be a mapping",
        )
    return parsed, instructions_markdown


def parse_skill_document(
    raw: bytes,
    *,
    directory_name: str | None = None,
) -> SkillDocument:
    frontmatter, instructions_markdown = parse_skill_md_frontmatter(raw)
    if any(not isinstance(key, str) for key in frontmatter):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "SKILL.md frontmatter keys must be strings",
        )
    try:
        metadata = SkillMetadata.model_validate(frontmatter)
    except ValidationError as exc:
        first_error = exc.errors(include_url=False)[0]
        location = first_error.get("loc", ())
        field = str(location[0]) if location else "frontmatter"
        message = str(first_error.get("msg", "is invalid"))
        message = message.removeprefix("Value error, ")
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"SKILL.md frontmatter field '{field}' {message}",
        ) from exc
    if directory_name is not None and metadata.name != directory_name:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "SKILL.md frontmatter field 'name' must match its parent directory "
            f"('{directory_name}')",
        )
    return SkillDocument(
        metadata=metadata,
        instructions_markdown=instructions_markdown.strip(),
    )


def serialize_skill_md(
    frontmatter: Mapping[str, Any],
    instructions_markdown: str,
) -> str:
    serialized_frontmatter = yaml.safe_dump(
        dict(frontmatter),
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    return f"---\n{serialized_frontmatter}\n---\n\n{instructions_markdown.strip()}\n"
