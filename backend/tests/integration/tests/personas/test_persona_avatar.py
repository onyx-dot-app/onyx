"""
Tests for the persona avatar endpoint (`GET /persona/{persona_id}/avatar`).

Covers:
1. Round-trip upload + fetch for the persona owner.
2. Cross-user access honoring the persona's own ACL (public readable by
   everyone, private gated to owner/allowed members).
3. 404 responses for personas without a configured avatar or that do not
   exist at all.
"""

import base64
import io
from typing import NamedTuple

import pytest
import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser

# Minimal valid 1x1 PNG — small, parses cleanly, and lets us assert the
# served bytes equal what we uploaded.
_AVATAR_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


class PersonaAvatarSetup(NamedTuple):
    owner: DATestUser
    other_user: DATestUser
    public_persona_id: int
    private_persona_id: int
    no_avatar_persona_id: int


def _upload_persona_avatar(user: DATestUser) -> str:
    """Upload avatar bytes via the admin upload-image endpoint and return
    the storage file_id the frontend would receive."""
    response = requests.post(
        f"{API_SERVER_URL}/admin/persona/upload-image",
        files={
            "file": ("avatar.png", io.BytesIO(_AVATAR_PNG_BYTES), "image/png"),
        },
        headers={k: v for k, v in user.headers.items() if k.lower() != "content-type"},
    )
    response.raise_for_status()
    return response.json()["file_id"]


def _create_persona_with_avatar(
    *,
    owner: DATestUser,
    name: str,
    is_public: bool,
    uploaded_image_id: str | None,
) -> int:
    """Create a persona with (or without) a configured avatar and return its
    id. Built from a raw payload rather than `PersonaManager` so the avatar
    field flows straight through the API shape under test."""
    payload = {
        "name": name,
        "description": f"{name} description",
        "system_prompt": "",
        "task_prompt": "",
        "document_set_ids": [],
        "tool_ids": [],
        "is_public": is_public,
        "datetime_aware": False,
        "uploaded_image_id": uploaded_image_id,
    }
    response = requests.post(
        f"{API_SERVER_URL}/persona",
        json=payload,
        headers=owner.headers,
    )
    response.raise_for_status()
    return response.json()["id"]


@pytest.fixture
def persona_avatar_setup(reset: None) -> PersonaAvatarSetup:  # noqa: ARG001
    """Owner with three personas — public + avatar, private + avatar, and a
    no-avatar control — plus a second authenticated user for cross-user
    access checks."""
    owner: DATestUser = UserManager.create(name="avatar_owner")
    other: DATestUser = UserManager.create(name="avatar_other")

    public_file_id = _upload_persona_avatar(owner)
    public_persona_id = _create_persona_with_avatar(
        owner=owner,
        name="public avatar persona",
        is_public=True,
        uploaded_image_id=public_file_id,
    )

    private_file_id = _upload_persona_avatar(owner)
    private_persona_id = _create_persona_with_avatar(
        owner=owner,
        name="private avatar persona",
        is_public=False,
        uploaded_image_id=private_file_id,
    )

    no_avatar_persona_id = _create_persona_with_avatar(
        owner=owner,
        name="no avatar persona",
        is_public=True,
        uploaded_image_id=None,
    )

    return PersonaAvatarSetup(
        owner=owner,
        other_user=other,
        public_persona_id=public_persona_id,
        private_persona_id=private_persona_id,
        no_avatar_persona_id=no_avatar_persona_id,
    )


def test_persona_owner_can_fetch_their_avatar(
    persona_avatar_setup: PersonaAvatarSetup,
) -> None:
    response = requests.get(
        f"{API_SERVER_URL}/persona/{persona_avatar_setup.public_persona_id}/avatar",
        headers=persona_avatar_setup.owner.headers,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("image/")
    assert response.content == _AVATAR_PNG_BYTES


def test_public_persona_avatar_is_accessible_to_other_users(
    persona_avatar_setup: PersonaAvatarSetup,
) -> None:
    response = requests.get(
        f"{API_SERVER_URL}/persona/{persona_avatar_setup.public_persona_id}/avatar",
        headers=persona_avatar_setup.other_user.headers,
    )
    assert response.status_code == 200, response.text
    assert response.content == _AVATAR_PNG_BYTES


def test_private_persona_avatar_is_denied_to_other_users(
    persona_avatar_setup: PersonaAvatarSetup,
) -> None:
    response = requests.get(
        f"{API_SERVER_URL}/persona/"
        f"{persona_avatar_setup.private_persona_id}/avatar",
        headers=persona_avatar_setup.other_user.headers,
    )
    assert response.status_code == 404, (
        f"Non-member should not be able to read a private persona's avatar, "
        f"got {response.status_code}: {response.text}"
    )
    assert response.content != _AVATAR_PNG_BYTES


def test_persona_avatar_returns_404_when_no_avatar_configured(
    persona_avatar_setup: PersonaAvatarSetup,
) -> None:
    response = requests.get(
        f"{API_SERVER_URL}/persona/"
        f"{persona_avatar_setup.no_avatar_persona_id}/avatar",
        headers=persona_avatar_setup.owner.headers,
    )
    assert response.status_code == 404, response.text


def test_persona_avatar_returns_404_for_missing_persona(
    reset: None,  # noqa: ARG001
) -> None:
    user: DATestUser = UserManager.create(name="missing_persona_user")
    response = requests.get(
        f"{API_SERVER_URL}/persona/99999999/avatar",
        headers=user.headers,
    )
    assert response.status_code == 404, response.text
