"""Unit tests for SkillPatchRequest intent tracking."""

import pytest
from pydantic import ValidationError

from onyx.db.enums import SkillSharePermission
from onyx.server.features.skill.models import SkillPatchRequest


def test_omitted_fields_do_not_count_as_updates() -> None:
    req = SkillPatchRequest(is_public=True)

    assert req.model_fields_set == {"is_public"}
    assert req.has_db_field_update is True
    assert req.has_details_update is False


def test_all_fields_sent() -> None:
    req = SkillPatchRequest(
        is_public=True,
        public_permission=SkillSharePermission.EDITOR,
        enabled=False,
    )

    assert req.model_fields_set == {"is_public", "public_permission", "enabled"}
    assert req.is_public is True
    assert req.public_permission == SkillSharePermission.EDITOR
    assert req.enabled is False


def test_false_values_count_as_updates() -> None:
    req = SkillPatchRequest(is_public=False, enabled=False)

    assert req.model_fields_set == {"is_public", "enabled"}
    assert req.has_db_field_update is True
    assert req.is_public is False
    assert req.enabled is False


def test_empty_request_has_no_update_intent() -> None:
    req = SkillPatchRequest()

    assert req.model_fields_set == set()
    assert req.has_db_field_update is False
    assert req.has_details_update is False


def test_detail_fields_track_intent() -> None:
    req = SkillPatchRequest(
        name=" Updated name ",
        description=" Updated description ",
        instructions_markdown=" Updated instructions ",
    )

    assert req.name == "Updated name"
    assert req.description == "Updated description"
    assert req.instructions_markdown == "Updated instructions"
    assert req.has_details_update is True
    assert req.has_db_field_update is False


@pytest.mark.parametrize(
    "field",
    [
        "name",
        "description",
        "instructions_markdown",
        "is_public",
        "public_permission",
        "enabled",
    ],
)
def test_explicit_null_rejected(field: str) -> None:
    """Sending field=null (not omitting it) should raise ValidationError."""
    with pytest.raises(ValidationError, match=f"{field} cannot be null"):
        SkillPatchRequest.model_validate({field: None})


@pytest.mark.parametrize("field", ["name", "description", "instructions_markdown"])
def test_empty_strings_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match=f"{field} cannot be empty"):
        SkillPatchRequest.model_validate({field: "  "})


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        SkillPatchRequest.model_validate({"slug": "new-slug"})
