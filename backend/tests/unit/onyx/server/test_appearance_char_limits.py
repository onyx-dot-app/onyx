"""The theme page duplicates the appearance length caps so it can draw its
character counters without an API round-trip. Duplication is fine; drifting is
not, and drifting upward is the harmful direction — the form would let an admin
type past what the API accepts, and the save would fail at submit.

This pins the two copies together, so drift fails here rather than in a user's
face.
"""

import re
from pathlib import Path

import pydantic
import pytest

from ee.onyx.server.enterprise_settings.models import (
    APPEARANCE_FIELD_MAX_LENGTHS,
    MAX_APPLICATION_NAME_LEN,
    MAX_CONSENT_SCREEN_PROMPT_LEN,
    MAX_GREETING_MESSAGE_LEN,
    MAX_HEADER_CONTENT_LEN,
    MAX_LOGIN_SUBTITLE_LEN,
    MAX_LOWER_DISCLAIMER_CONTENT_LEN,
    MAX_POPUP_CONTENT_LEN,
    MAX_POPUP_HEADER_LEN,
    EnterpriseSettings,
)
from ee.onyx.server.enterprise_settings.store import _clamp_appearance_fields
from onyx.server.features.admin_banner.api import MAX_CONTENT_LEN, MAX_TITLE_LEN

THEME_PAGE = (
    Path(__file__).resolve().parents[5]
    / "web"
    / "src"
    / "app"
    / "ee"
    / "admin"
    / "theme"
    / "page.tsx"
)

# The announcement fields are the admin banner, which is a separate endpoint
# and model from the enterprise settings blob.
BACKEND_LIMITS = {
    "application_name": MAX_APPLICATION_NAME_LEN,
    "custom_greeting_message": MAX_GREETING_MESSAGE_LEN,
    "custom_login_subtitle": MAX_LOGIN_SUBTITLE_LEN,
    "custom_header_content": MAX_HEADER_CONTENT_LEN,
    "custom_lower_disclaimer_content": MAX_LOWER_DISCLAIMER_CONTENT_LEN,
    "custom_popup_header": MAX_POPUP_HEADER_LEN,
    "custom_popup_content": MAX_POPUP_CONTENT_LEN,
    "consent_screen_prompt": MAX_CONSENT_SCREEN_PROMPT_LEN,
    "system_announcement_header": MAX_TITLE_LEN,
    "system_announcement_content": MAX_CONTENT_LEN,
}


def _frontend_limits() -> dict[str, int]:
    source = THEME_PAGE.read_text()
    block = re.search(r"const CHAR_LIMITS = \{(.*?)\n\};", source, re.DOTALL)
    assert block, f"could not find CHAR_LIMITS in {THEME_PAGE}"
    return {
        name: int(value)
        for name, value in re.findall(r"(\w+):\s*(\d+),", block.group(1))
    }


def test_theme_page_is_readable() -> None:
    # A moved or renamed file would otherwise make every case below vacuous.
    assert THEME_PAGE.is_file(), f"{THEME_PAGE} not found"
    assert _frontend_limits(), "CHAR_LIMITS parsed as empty"


def test_every_backend_cap_has_a_frontend_counterpart() -> None:
    assert set(_frontend_limits()) == set(BACKEND_LIMITS)


@pytest.mark.parametrize("field", sorted(BACKEND_LIMITS))
def test_frontend_limit_matches_backend(field: str) -> None:
    assert _frontend_limits()[field] == BACKEND_LIMITS[field], (
        f"{field}: the theme page says {_frontend_limits()[field]}, the API "
        f"enforces {BACKEND_LIMITS[field]}. Update whichever is stale."
    )


# The comparison above only proves the two sets of numbers agree. It would keep
# passing with every `max_length=` deleted, so the enforcement those numbers are
# supposed to describe needs its own coverage.
# `model_validate` rather than kwargs, and `model_dump` rather than `getattr`:
# the field name is a parameter here, and both keep that dynamic access
# something the type checker can still follow.
@pytest.mark.parametrize("field,limit", sorted(APPEARANCE_FIELD_MAX_LENGTHS.items()))
def test_field_accepts_its_limit(field: str, limit: int) -> None:
    settings = EnterpriseSettings.model_validate({field: "x" * limit})
    assert settings.model_dump()[field] == "x" * limit


@pytest.mark.parametrize("field,limit", sorted(APPEARANCE_FIELD_MAX_LENGTHS.items()))
def test_field_rejects_one_over(field: str, limit: int) -> None:
    with pytest.raises(pydantic.ValidationError) as caught:
        EnterpriseSettings.model_validate({field: "x" * (limit + 1)})
    assert any(e["type"] == "string_too_long" for e in caught.value.errors())


# A cap validates on the way out as well as in, so a blob stored before the cap
# existed would make the settings endpoint unreadable. It is unauthenticated,
# so that is a 500 for every caller and an admin page that cannot open to fix
# the value.
def test_oversized_stored_value_is_trimmed_rather_than_fatal() -> None:
    field = "custom_lower_disclaimer_content"
    limit = APPEARANCE_FIELD_MAX_LENGTHS[field]
    stored = {field: "x" * (limit + 250), "application_name": "Onyx"}

    settings = EnterpriseSettings.model_validate(_clamp_appearance_fields(stored))

    assert settings.custom_lower_disclaimer_content is not None
    assert len(settings.custom_lower_disclaimer_content) == limit
    # Trimming one field must not discard the rest of the configuration.
    assert settings.application_name == "Onyx"


def test_clamping_leaves_a_value_within_its_limit_alone() -> None:
    field = "custom_popup_header"
    value = "x" * APPEARANCE_FIELD_MAX_LENGTHS[field]
    assert _clamp_appearance_fields({field: value})[field] == value
