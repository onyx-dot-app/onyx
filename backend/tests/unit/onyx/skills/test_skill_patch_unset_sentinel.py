"""Unit tests for SkillPatchRequest — sentinel mapping and null rejection."""

import pytest
from pydantic import ValidationError

from onyx.db.utils import UnsetType
from onyx.server.features.skill.models import SkillPatchRequest


def test_omitted_fields_produce_unset() -> None:
    """Fields not included in the request should produce UNSET in the domain object."""
    req = SkillPatchRequest(is_public=True)
    patch = req.to_domain()

    assert patch.is_public is True
    assert isinstance(patch.enabled, UnsetType)


def test_all_fields_sent() -> None:
    """All fields explicitly sent should appear in the domain object."""
    req = SkillPatchRequest(is_public=True, enabled=False)
    patch = req.to_domain()

    assert patch.is_public is True
    assert patch.enabled is False


def test_false_values_not_treated_as_unset() -> None:
    """Explicitly sending False should NOT produce UNSET."""
    req = SkillPatchRequest(is_public=False, enabled=False)
    patch = req.to_domain()

    assert patch.is_public is False
    assert patch.enabled is False


def test_empty_request_all_unset() -> None:
    """An empty request should have all fields as UNSET."""
    req = SkillPatchRequest()
    patch = req.to_domain()

    assert isinstance(patch.is_public, UnsetType)
    assert isinstance(patch.enabled, UnsetType)


@pytest.mark.parametrize("field", ["is_public", "enabled"])
def test_explicit_null_rejected(field: str) -> None:
    """Sending field=null (not omitting it) should raise ValidationError."""
    with pytest.raises(ValidationError, match=f"{field} cannot be null"):
        SkillPatchRequest.model_validate({field: None})
