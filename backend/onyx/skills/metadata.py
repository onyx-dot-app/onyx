"""Agent Skills metadata parsing, validation, and serialization."""

from __future__ import annotations

import datetime
import json
import math
import re
from collections.abc import Mapping
from typing import Any, Final

import yaml
from pydantic import JsonValue, ValidationError
from pydantic_core import ErrorDetails
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent
from yaml.nodes import Node, ScalarNode

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.models import (
    UNUSED_FRONTMATTER_FIELDS,
    SkillDocument,
    SkillMetadata,
)
from onyx.utils.unique_key_yaml import UniqueKeySafeLoader

SKILLS_DIR: Final = "skills"

_FRONTMATTER_REGEX: Final[re.Pattern[str]] = re.compile(
    r"\A---[ \t]*\r?\n(?P<frontmatter>.*?)(?:\r?\n)---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)

_MAX_FRONTMATTER_CHARS: Final[int] = 64 * 1024


class OversizedYamlInt:
    """A YAML integer with more digits than Python converts from text. It is
    kept as its text, so a save stays possible and the value round-trips."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text

    def __eq__(self, other: object) -> bool:
        return isinstance(other, OversizedYamlInt) and other.text == self.text

    def __hash__(self) -> int:
        return hash(self.text)


class _UniqueKeySafeLoader(UniqueKeySafeLoader):
    def compose_node(self, parent: Node | None, index: int) -> Node | None:
        if self.check_event(AliasEvent):
            raise ConstructorError(
                None,
                None,
                "YAML aliases are not allowed in SKILL.md frontmatter",
                self.get_mark(),
            )
        return super().compose_node(parent, index)


def _construct_int(loader: yaml.SafeLoader, node: Node) -> int | OversizedYamlInt:
    if not isinstance(node, ScalarNode):
        raise ConstructorError(None, None, "expected a scalar integer", node.start_mark)
    try:
        return loader.construct_yaml_int(node)
    except ValueError:
        # Python refuses to convert integers longer than 4300 digits.
        return OversizedYamlInt(str(node.value))


_UniqueKeySafeLoader.add_constructor("tag:yaml.org,2002:int", _construct_int)


class _SkillMdDumper(yaml.SafeDumper):
    pass


def _represent_oversized_int(dumper: yaml.SafeDumper, data: OversizedYamlInt) -> Node:
    return dumper.represent_scalar("tag:yaml.org,2002:int", data.text)


_SkillMdDumper.add_representer(OversizedYamlInt, _represent_oversized_int)


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
    if len(frontmatter_yaml) > _MAX_FRONTMATTER_CHARS:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "SKILL.md frontmatter is too large",
        )

    try:
        loader = _UniqueKeySafeLoader(frontmatter_yaml)
        try:
            parsed = loader.get_single_data()
        finally:
            loader.dispose()
    except (yaml.YAMLError, RecursionError) as exc:
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


_PLAIN_ERRORS: Final[Mapping[str, str]] = {
    "missing": "is required",
    "string_type": "must be text",
    "string_too_long": "is too long",
}


def _plain_error(error: ErrorDetails) -> str:
    plain = _PLAIN_ERRORS.get(error["type"])
    if plain is not None:
        return plain
    if error["type"] == "value_error":
        return error["msg"].removeprefix("Value error, ")
    return "has a value Onyx cannot read"


def _validate_metadata(frontmatter: dict[str, Any]) -> SkillMetadata:
    """Validate, and drop a field Onyx does not read when its value is bad.
    The stored frontmatter keeps that field as written."""
    try:
        return SkillMetadata.model_validate(frontmatter)
    except ValidationError as exc:
        bad = {str(error["loc"][0]) for error in exc.errors() if error["loc"]}
        unused = bad & UNUSED_FRONTMATTER_FIELDS
        if not unused or unused != bad:
            raise
    return SkillMetadata.model_validate(
        {key: value for key, value in frontmatter.items() if key not in unused}
    )


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
        metadata = _validate_metadata(frontmatter)
    except ValidationError as exc:
        first_error = exc.errors(include_url=False)[0]
        location = first_error.get("loc", ())
        field = str(location[0]) if location else "frontmatter"
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"SKILL.md frontmatter field '{field}' {_plain_error(first_error)}",
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
        frontmatter=frontmatter,
    )


class _NotJsonbSafe(Exception):
    pass


def _is_jsonb_string(value: str) -> bool:
    if "\x00" in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _jsonb_value(value: object) -> JsonValue:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        # A hex YAML integer skips Python's digit limit on parse, but JSON
        # writes it in decimal, which the limit refuses.
        try:
            str(value)
        except ValueError:
            raise _NotJsonbSafe from None
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _NotJsonbSafe
        return value
    if isinstance(value, str):
        if not _is_jsonb_string(value):
            raise _NotJsonbSafe
        return value
    # datetime is a subclass of date, so both take this branch.
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, list):
        return [_jsonb_value(item) for item in value]
    if isinstance(value, dict):
        return _jsonb_mapping(value)
    # bytes, sets, OversizedYamlInt and other YAML types JSON cannot hold.
    raise _NotJsonbSafe


def _jsonb_mapping(mapping: Mapping[Any, object]) -> dict[str, JsonValue]:
    """Keep each entry JSONB can hold. Drop an entry whose key is not a string
    or whose value (a list, for example) holds a value JSONB cannot hold."""
    converted: dict[str, JsonValue] = {}
    for key, item in mapping.items():
        if not isinstance(key, str) or not _is_jsonb_string(key):
            continue
        try:
            converted[key] = _jsonb_value(item)
        except (_NotJsonbSafe, RecursionError):
            continue
    return converted


def frontmatter_for_jsonb(document: SkillDocument) -> dict[str, JsonValue]:
    """Return a copy of the parsed frontmatter that a JSONB column can hold,
    with dates as ISO strings. A value JSONB cannot hold is dropped and every
    other key is kept. name and description are always the validated
    strings."""
    required: dict[str, JsonValue] = {
        "name": document.metadata.name,
        "description": document.metadata.description,
    }
    converted = _jsonb_mapping(document.frontmatter) | required
    try:
        json.dumps(converted, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        return required
    return converted


def serialize_skill_md(
    frontmatter: Mapping[str, Any],
    instructions_markdown: str,
) -> str:
    serialized_frontmatter = yaml.dump(
        dict(frontmatter),
        Dumper=_SkillMdDumper,
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    return f"---\n{serialized_frontmatter}\n---\n\n{instructions_markdown.strip()}\n"
