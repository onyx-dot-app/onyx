import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestUser


def _list_minimal_personas(user: DATestUser) -> list[dict]:
    response = requests.get(
        f"{API_SERVER_URL}/persona",
        headers=user.headers,
        cookies=user.cookies,
    )
    response.raise_for_status()
    return response.json()


def _share_persona(
    persona_id: int, user_ids: list[str], acting_user: DATestUser
) -> None:
    response = requests.patch(
        f"{API_SERVER_URL}/persona/{persona_id}/share",
        json={"user_ids": user_ids},
        headers=acting_user.headers,
        cookies=acting_user.cookies,
    )
    response.raise_for_status()


def test_persona_create_update_share_delete(
    reset: None, admin_user: DATestUser, basic_user: DATestUser
) -> None:
    # TODO: refactor `PersonaManager.verify`, not a good pattern
    # Create a persona as admin and verify it can be fetched
    expected_persona = PersonaManager.create(user_performing_action=admin_user)
    PersonaManager.verify(expected_persona, user_performing_action=admin_user)

    # Update the persona and verify changes
    updated_persona = PersonaManager.edit(
        expected_persona,
        name=f"updated-{expected_persona.name}",
        description=f"updated-{expected_persona.description}",
        num_chunks=expected_persona.num_chunks + 1,
        is_public=False,
        user_performing_action=admin_user,
    )
    assert PersonaManager.verify(updated_persona, user_performing_action=admin_user)

    # Creator should see the persona in their minimal list
    creator_minimals = _list_minimal_personas(admin_user)
    assert any(p["id"] == updated_persona.id for p in creator_minimals)

    # Regular user should not see a non-public, non-shared persona
    other_minimals_before = _list_minimal_personas(basic_user)
    assert all(p["id"] != updated_persona.id for p in other_minimals_before)

    # Share persona with the regular user and verify visibility
    _share_persona(updated_persona.id, [basic_user.id], admin_user)
    other_minimals_after = _list_minimal_personas(basic_user)
    assert any(p["id"] == updated_persona.id for p in other_minimals_after)

    # Delete persona and verify it no longer appears in lists
    assert PersonaManager.delete(updated_persona, user_performing_action=admin_user)

    # After deletion, list should not include it for either user
    creator_minimals_after_delete = _list_minimal_personas(admin_user)
    assert all(p["id"] != updated_persona.id for p in creator_minimals_after_delete)

    regular_minimals_after_delete = _list_minimal_personas(basic_user)
    assert all(p["id"] != updated_persona.id for p in regular_minimals_after_delete)
