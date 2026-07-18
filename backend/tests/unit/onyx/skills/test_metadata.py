"""Unit tests for Agent Skills metadata handling."""

from __future__ import annotations

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.skills.metadata import parse_skill_document
from onyx.skills.metadata import serialize_skill_md


def _skill_md(frontmatter: str, body: str = "Do the work.") -> bytes:
    return f"---\n{frontmatter}\n---\n\n{body}\n".encode()


@pytest.mark.parametrize("name", ["a", "1-report", "pdf-processing", "a" * 64])
def test_parse_skill_document_accepts_valid_names(name: str) -> None:
    document = parse_skill_document(
        _skill_md(f"name: {name}\ndescription: Use this skill for reports.")
    )
    assert document.metadata.name == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "PDF-processing",
        "has_underscore",
        "-leading",
        "trailing-",
        "two--hyphens",
        "a" * 65,
    ],
)
def test_parse_skill_document_rejects_invalid_names(name: str) -> None:
    with pytest.raises(OnyxError, match="field 'name'"):
        parse_skill_document(
            _skill_md(f"name: '{name}'\ndescription: Use this skill for reports.")
        )


def test_parse_skill_document_validates_description_length() -> None:
    with pytest.raises(OnyxError, match="field 'description'.*1024"):
        parse_skill_document(_skill_md(f"name: reports\ndescription: {'x' * 1025}"))


@pytest.mark.parametrize("description", ["", " "])
def test_parse_skill_document_rejects_empty_description(
    description: str,
) -> None:
    with pytest.raises(OnyxError, match="field 'description'.*empty"):
        parse_skill_document(_skill_md(f"name: reports\ndescription: '{description}'"))


@pytest.mark.parametrize("compatibility", ["", " ", "x" * 501])
def test_parse_skill_document_rejects_invalid_compatibility(
    compatibility: str,
) -> None:
    with pytest.raises(OnyxError, match="field 'compatibility'"):
        parse_skill_document(
            _skill_md(
                "name: reports\n"
                "description: Use this skill for reports.\n"
                f"compatibility: '{compatibility}'"
            )
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("license", "123"),
        ("allowed-tools", "[Read]"),
        ("metadata", "{version: 1}"),
    ],
)
def test_parse_skill_document_validates_optional_field_types(
    field: str,
    value: str,
) -> None:
    with pytest.raises(OnyxError, match=f"field '{field}'"):
        parse_skill_document(
            _skill_md(
                "name: reports\n"
                "description: Use this skill for reports.\n"
                f"{field}: {value}"
            )
        )


def test_parse_skill_document_rejects_non_string_frontmatter_key() -> None:
    with pytest.raises(OnyxError, match="keys must be strings"):
        parse_skill_document(
            _skill_md(
                "name: reports\ndescription: Use this skill for reports.\n1: invalid"
            )
        )


def test_parse_skill_document_rejects_duplicate_frontmatter_key() -> None:
    with pytest.raises(OnyxError, match="duplicate key 'name'"):
        parse_skill_document(
            _skill_md(
                "name: reports\nname: other\ndescription: Use this skill for reports."
            )
        )


@pytest.mark.parametrize("frontmatter", ["false", "[]", "skill"])
def test_parse_skill_document_requires_frontmatter_mapping(
    frontmatter: str,
) -> None:
    with pytest.raises(OnyxError, match="must be a mapping"):
        parse_skill_document(_skill_md(frontmatter))


def test_skill_document_round_trip_preserves_optional_and_unknown_fields() -> None:
    raw = _skill_md(
        "name: reports\n"
        "description: Use this skill for reports.\n"
        "license: Apache-2.0\n"
        "compatibility: Requires git\n"
        "metadata:\n"
        "  author: onyx\n"
        "  version: '1.0'\n"
        "allowed-tools: Bash(git:*) Read\n"
        "x-onyx-setting:\n"
        "  enabled: true",
        "# Instructions\n\nDo the work.",
    )

    document = parse_skill_document(raw)
    serialized = serialize_skill_md(
        document.metadata.model_dump(
            by_alias=True,
            exclude_none=True,
            mode="python",
        ),
        document.instructions_markdown,
    ).encode()
    reparsed = parse_skill_document(serialized)

    assert reparsed == document
    assert reparsed.metadata.model_extra == {"x-onyx-setting": {"enabled": True}}


def test_parse_skill_document_requires_directory_name_match() -> None:
    raw = _skill_md("name: reports\ndescription: Use this skill for reports.")

    document = parse_skill_document(raw, directory_name="reports")
    assert document.metadata.name == "reports"
    with pytest.raises(OnyxError, match="must match its parent directory"):
        parse_skill_document(
            raw,
            directory_name="other",
        )
