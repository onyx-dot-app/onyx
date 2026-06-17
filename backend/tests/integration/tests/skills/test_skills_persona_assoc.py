"""Persona ↔ skill association (HTTP boundary).

Guards the inert persona-skill link added in PR2:
- a skill the editor can see persists on their persona and round-trips on fetch;
- a skill id the editor can't see is silently dropped (no error), so co-editors
  of a shared persona aren't blocked by another editor's private skill;
- a private skill attached to a shared persona is masked from a different
  user's fetch of that persona — the snapshot exposes only the intersection of
  attached skills and what the viewer can see.
"""

from __future__ import annotations

from uuid import uuid4

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def _create_persona_with_skills(
    user: DATestUser, *, skill_ids: list[str], is_public: bool = False
) -> dict:
    name = f"persona-skill-{uuid4().hex[:6]}"
    payload = {
        "name": name,
        "description": f"Description for {name}",
        "document_set_ids": [],
        "is_public": is_public,
        "tool_ids": [],
        "skill_ids": skill_ids,
        "system_prompt": "sys",
        "task_prompt": "task",
        "datetime_aware": False,
    }
    response = client.post(
        f"{API_SERVER_URL}/persona",
        json=payload,
        headers=user.headers,
    )
    response.raise_for_status()
    return response.json()


def _get_persona(user: DATestUser, persona_id: int) -> dict:
    response = client.get(
        f"{API_SERVER_URL}/persona/{persona_id}",
        headers=user.headers,
    )
    response.raise_for_status()
    return response.json()


def test_attach_visible_skill_persists(
    basic_user: DATestUser,
) -> None:
    skill = SkillManager.create_self_serve(basic_user, slug=f"vis-{uuid4().hex[:6]}")
    skill_id = str(skill.id)

    created = _create_persona_with_skills(basic_user, skill_ids=[skill_id])
    assert created["skill_ids"] == [skill_id]

    fetched = _get_persona(basic_user, created["id"])
    assert fetched["skill_ids"] == [skill_id]


def test_invisible_skill_id_silently_dropped(
    basic_user: DATestUser,
) -> None:
    user_b = UserManager.create(name=f"persona-skill-b-{uuid4().hex[:6]}")
    # Private skill authored by user_b; basic_user can't see it.
    other_skill = SkillManager.create_self_serve(
        user_b, slug=f"hidden-{uuid4().hex[:6]}"
    )

    created = _create_persona_with_skills(basic_user, skill_ids=[str(other_skill.id)])
    # Dropped, not 403'd.
    assert created["skill_ids"] == []


def test_private_skill_on_shared_persona_masked_from_other_user(
    basic_user: DATestUser,
) -> None:
    user_b = UserManager.create(name=f"persona-skill-b-{uuid4().hex[:6]}")

    skill = SkillManager.create_self_serve(
        basic_user, slug=f"owner-priv-{uuid4().hex[:6]}"
    )
    skill_id = str(skill.id)

    # Public persona so user_b can fetch it; the attached skill stays private.
    created = _create_persona_with_skills(
        basic_user, skill_ids=[skill_id], is_public=True
    )
    assert created["skill_ids"] == [skill_id]

    # Owner still sees the attachment.
    assert _get_persona(basic_user, created["id"])["skill_ids"] == [skill_id]

    # A different user sees the persona but not the owner's private skill.
    assert _get_persona(user_b, created["id"])["skill_ids"] == []
