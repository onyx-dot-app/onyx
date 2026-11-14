"""parse_tool_arguments and tool_definition_from_arguments on generic models."""

from enum import Enum

import pytest
from pydantic import BaseModel

from onyx.tools.interface import parse_tool_arguments, tool_definition_from_arguments
from onyx.tools.models import KnowledgeGraphArguments, ToolCallException


class _Defaults(BaseModel):
    required: str
    defaulted: int = 5
    nullable: int | None = 7


def test_null_selects_the_default_only_when_the_type_rejects_null() -> None:
    arguments = parse_tool_arguments(
        _Defaults, {"required": "x", "defaulted": None, "nullable": None}
    )
    assert arguments.defaulted == 5
    assert arguments.nullable is None


def test_null_for_a_required_argument_is_an_error() -> None:
    with pytest.raises(ToolCallException, match="required: Input should be a valid"):
        parse_tool_arguments(_Defaults, {"required": None})


def test_strict_tool_parsing_ignores_unknown_arguments() -> None:
    definition = tool_definition_from_arguments(
        "kg", "d", KnowledgeGraphArguments, strict=True
    )
    assert definition.parameters["additionalProperties"] is False
    arguments = parse_tool_arguments(
        KnowledgeGraphArguments, {"query": "q", "unknown": 1}
    )
    assert arguments.query == "q"


class _Inner(BaseModel):
    value: str


class _Color(Enum):
    RED = "red"


class _Nested(BaseModel):
    inner: _Inner


class _WithEnum(BaseModel):
    color: _Color


@pytest.mark.parametrize("model", [_Nested, _WithEnum])
def test_strict_definition_rejects_referenced_types(model: type[BaseModel]) -> None:
    with pytest.raises(ValueError, match="inline argument types"):
        tool_definition_from_arguments("t", "d", model, strict=True)
