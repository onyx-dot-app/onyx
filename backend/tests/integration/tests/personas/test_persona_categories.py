from uuid import uuid4

import pytest
from requests.exceptions import HTTPError

from tests.integration.common_utils.managers.persona import (
    PersonaLabelManager,
)
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestPersonaLabel
from tests.integration.common_utils.test_models import DATestUser


def test_persona_label_management(reset: None) -> None:
    admin_user: DATestUser = UserManager.create(name="admin_user")

    persona_label = DATestPersonaLabel(
        id=None,
        name=f"Test label {uuid4()}",
    )
    persona_label = PersonaLabelManager.create(
        label=persona_label,
        user_performing_action=admin_user,
    )
    print(f"Created persona label {persona_label.name} with id {persona_label.id}")

    assert PersonaLabelManager.verify(
        label=persona_label,
        user_performing_action=admin_user,
    ), "Persona label was not found after creation"

    regular_user: DATestUser = UserManager.create(name="regular_user")

    updated_persona_label = DATestPersonaLabel(
        id=persona_label.id,
        name=f"Updated {persona_label.name}",
    )
    with pytest.raises(HTTPError) as exc_info:
        PersonaLabelManager.update(
            label=updated_persona_label,
            user_performing_action=regular_user,
        )
    assert exc_info.value.response is not None
    assert exc_info.value.response.status_code == 403

    assert PersonaLabelManager.verify(
        label=persona_label,
        user_performing_action=admin_user,
    ), "Persona label should not have been updated by non-admin user"

    result = PersonaLabelManager.delete(
        label=persona_label,
        user_performing_action=regular_user,
    )
    assert (
        result is False
    ), "Regular user should not be able to delete the persona label"

    assert PersonaLabelManager.verify(
        label=persona_label,
        user_performing_action=admin_user,
    ), "Persona label should not have been deleted by non-admin user"

    updated_persona_label.name = f"Updated {persona_label.name}"
    updated_persona_label = PersonaLabelManager.update(
        label=updated_persona_label,
        user_performing_action=admin_user,
    )
    print(f"Updated persona label to {updated_persona_label.name}")

    assert PersonaLabelManager.verify(
        label=updated_persona_label,
        user_performing_action=admin_user,
    ), "Persona label was not updated by admin"

    success = PersonaLabelManager.delete(
        label=persona_label,
        user_performing_action=admin_user,
    )
    assert success, "Admin user should be able to delete the persona label"
    print(f"Deleted persona label {persona_label.name} with id {persona_label.id}")

    assert not PersonaLabelManager.verify(
        label=persona_label,
        user_performing_action=admin_user,
    ), "Persona label should not exist after deletion by admin"
