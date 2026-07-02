"""Unit tests for SkillPatchRequest intent tracking."""

import pytest
from pydantic import ValidationError

from onyx.db.enums import SkillSharePermission
from onyx.server.features.skill.models import SkillPatchRequest


def test_omitted_fields_do_not_count_as_updates() -> None:
    req = SkillPatchRequest(public_permission=SkillSharePermission.VIEWER)

    assert req.model_fields_set == {"public_permission"}
    assert req.has_db_field_update is True


def test_all_fields_sent() -> None:
    req = SkillPatchRequest(
        public_permission=SkillSharePermission.EDITOR,
        enabled=False,
    )

    assert req.model_fields_set == {"public_permission", "enabled"}
    assert req.public_permission == SkillSharePermission.EDITOR
    assert req.enabled is False


def test_explicit_public_permission_null_counts_as_update() -> None:
    req = SkillPatchRequest(public_permission=None, enabled=False)

    assert req.model_fields_set == {"public_permission", "enabled"}
    assert req.has_db_field_update is True
    assert req.public_permission is None
    assert req.enabled is False


def test_empty_request_has_no_update_intent() -> None:
    req = SkillPatchRequest()

    assert req.model_fields_set == set()
    assert req.has_db_field_update is False


def test_explicit_enabled_null_rejected() -> None:
    """Sending enabled=null (not omitting it) should raise ValidationError."""
    with pytest.raises(ValidationError, match="enabled cannot be null"):
        SkillPatchRequest.model_validate({"enabled": None})


def test_public_permission_null_allowed() -> None:
    req = SkillPatchRequest.model_validate({"public_permission": None})

    assert req.public_permission is None
    assert req.model_fields_set == {"public_permission"}
    assert req.has_db_field_update is True


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        SkillPatchRequest.model_validate({"slug": "new-slug"})
