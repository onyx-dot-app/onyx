from dataclasses import dataclass
from uuid import UUID
from uuid import uuid4

from onyx.chat.brand_required_docs import add_brand_required_file_descriptors
from onyx.chat.brand_required_docs import brand_required_search_document_ids
from onyx.chat.brand_required_docs import matched_required_doc_names


@dataclass
class FakeUserFile:
    id: UUID
    file_id: str
    name: str
    file_type: str | None = "text/markdown"


@dataclass
class FakePersona:
    name: str
    user_files: list[FakeUserFile]


def _file(name: str, file_id: str | None = None) -> FakeUserFile:
    return FakeUserFile(id=uuid4(), file_id=file_id or f"doc-{name}", name=name)


def _config() -> dict:
    return {
        "brands": [
            {
                "brand_key": "acme",
                "persona_name_prefixes": ["ACME"],
                "persona_roles": [
                    {"key": "planner", "name_contains": ["Planner"]},
                    {"key": "service", "name_contains": ["Service"]},
                ],
                "intent_routes": [
                    {
                        "key": "launch",
                        "personas": ["planner"],
                        "triggers": ["launch"],
                        "required_docs": [
                            "brand/positioning.md",
                            "products/sku.md",
                        ],
                    },
                    {
                        "key": "care",
                        "personas": ["planner", "service"],
                        "triggers": ["care"],
                        "required_docs": ["generic.md"],
                        "required_docs_by_persona": {
                            "planner": ["brand/copy-rules.md"],
                            "service": ["support/faq.md"],
                        },
                    },
                ],
            }
        ]
    }


def test_non_matching_persona_is_noop() -> None:
    persona = FakePersona(name="General Assistant", user_files=[_file("positioning.md")])

    assert (
        matched_required_doc_names(
            message="launch plan",
            persona=persona,  # type: ignore[arg-type]
            config=_config(),
        )
        == ()
    )
    assert (
        brand_required_search_document_ids(
            message="launch plan",
            persona=persona,  # type: ignore[arg-type]
            config=_config(),
        )
        == []
    )


def test_route_matching_normalizes_config_paths_to_user_file_basenames() -> None:
    persona = FakePersona(
        name="ACME Planner",
        user_files=[_file("positioning.md", "doc-positioning"), _file("sku.md", "doc-sku")],
    )

    assert matched_required_doc_names(
        message="build a launch plan",
        persona=persona,  # type: ignore[arg-type]
        config=_config(),
    ) == ("positioning.md", "sku.md")
    assert brand_required_search_document_ids(
        message="build a launch plan",
        persona=persona,  # type: ignore[arg-type]
        config=_config(),
    ) == ["doc-positioning", "doc-sku"]


def test_missing_required_docs_do_not_expand_scope() -> None:
    persona = FakePersona(
        name="ACME Planner",
        user_files=[_file("positioning.md", "doc-positioning")],
    )

    assert brand_required_search_document_ids(
        message="build a launch plan",
        persona=persona,  # type: ignore[arg-type]
        config=_config(),
    ) == ["doc-positioning"]


def test_required_docs_by_persona_selects_role_specific_docs() -> None:
    persona = FakePersona(
        name="ACME Service",
        user_files=[_file("copy-rules.md", "doc-copy"), _file("faq.md", "doc-faq")],
    )

    assert matched_required_doc_names(
        message="care instructions",
        persona=persona,  # type: ignore[arg-type]
        config=_config(),
    ) == ("faq.md",)
    assert brand_required_search_document_ids(
        message="care instructions",
        persona=persona,  # type: ignore[arg-type]
        config=_config(),
    ) == ["doc-faq"]


def test_existing_file_descriptor_is_not_duplicated() -> None:
    existing = _file("positioning.md", "doc-positioning")
    persona = FakePersona(
        name="ACME Planner",
        user_files=[existing, _file("sku.md", "doc-sku")],
    )

    descriptors = add_brand_required_file_descriptors(
        message="build a launch plan",
        persona=persona,  # type: ignore[arg-type]
        file_descriptors=[
            {
                "id": existing.file_id,
                "type": "plain_text",
                "name": existing.name,
                "user_file_id": str(existing.id),
            }
        ],
        db_session=None,  # type: ignore[arg-type]
        config=_config(),
    )

    assert [descriptor["name"] for descriptor in descriptors] == [
        "positioning.md",
        "sku.md",
    ]
