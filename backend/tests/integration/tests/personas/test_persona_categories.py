from uuid import uuid4

import pytest
from requests.exceptions import HTTPError

from tests.integration.common_utils.managers.persona import (
    PersonaCategoryManager,
)
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestPersonaCategory
from tests.integration.common_utils.test_models import DATestUser


def test_persona_category_management(reset: None) -> None:
    admin_user: DATestUser = UserManager.create(name="admin_user")

    persona_category = DATestPersonaCategory(
        id=None,
        name=f"Test Category {uuid4()}",
        description="A description for test category",
    )
    persona_category = PersonaCategoryManager.create(
        category=persona_category,
        user_performing_action=admin_user,
    )
    print(
        f"Created persona category {persona_category.name} with id {persona_category.id}"
    )

    assert PersonaCategoryManager.verify(
        category=persona_category,
        user_performing_action=admin_user,
    ), "Persona category was not found after creation"

    regular_user: DATestUser = UserManager.create(name="regular_user")

    updated_persona_category = DATestPersonaCategory(
        id=persona_category.id,
        name=f"Updated {persona_category.name}",
        description="An updated description",
    )
    with pytest.raises(HTTPError) as exc_info:
        PersonaCategoryManager.update(
            category=updated_persona_category,
            user_performing_action=regular_user,
        )
    assert exc_info.value.response.status_code == 403

    assert PersonaCategoryManager.verify(
        category=persona_category,
        user_performing_action=admin_user,
    ), "Persona category should not have been updated by non-admin user"

    result = PersonaCategoryManager.delete(
        category=persona_category,
        user_performing_action=regular_user,
    )
    assert (
        result is False
    ), "Regular user should not be able to delete the persona category"

    assert PersonaCategoryManager.verify(
        category=persona_category,
        user_performing_action=admin_user,
    ), "Persona category should not have been deleted by non-admin user"

    updated_persona_category.name = f"Updated {persona_category.name}"
    updated_persona_category.description = "An updated description"
    updated_persona_category = PersonaCategoryManager.update(
        category=updated_persona_category,
        user_performing_action=admin_user,
    )
    print(f"Updated persona category to {updated_persona_category.name}")

    assert PersonaCategoryManager.verify(
        category=updated_persona_category,
        user_performing_action=admin_user,
    ), "Persona category was not updated by admin"

    success = PersonaCategoryManager.delete(
        category=persona_category,
        user_performing_action=admin_user,
    )
    assert success, "Admin user should be able to delete the persona category"
    print(
        f"Deleted persona category {persona_category.name} with id {persona_category.id}"
    )

    assert not PersonaCategoryManager.verify(
        category=persona_category,
        user_performing_action=admin_user,
    ), "Persona category should not exist after deletion by admin"
