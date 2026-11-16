from uuid import UUID, uuid4

import pytest

from onyx.db.enums import SkillSharePermission
from onyx.server.features.skill.models import (
    SkillBulkResponse,
    SkillUserShareRequest,
)
from tests.integration.common_utils.constants import ADMIN_USER_NAME, API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import (
    SkillManager,
    build_minimal_bundle,
)
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture(scope="module", autouse=True)
def _module_reset_and_seed() -> None:
    reset_all()
    UserManager.create(name=ADMIN_USER_NAME)


def test_bulk_organization_sharing_updates_every_selected_skill(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    skills = [SkillManager.create_custom(admin_user) for _ in range(3)]
    selected_ids = {skill.id for skill in skills}
    response = client.post(
        f"{API_SERVER_URL}/skills/bulk",
        headers=admin_user.headers,
        json={
            "skill_ids": [str(skill.id) for skill in skills],
            "action": "share",
            "sharing": {
                "public_permission": "VIEWER",
                "installation_policy": "DEFAULT",
            },
        },
    )
    response.raise_for_status()
    result = SkillBulkResponse.model_validate(response.json())
    assert set(result.succeeded) == selected_ids
    assert result.failed == []
    for skill in skills:
        shared = SkillManager.get_for_user(skill.id, basic_user)
        assert shared.public_permission == "VIEWER"
        assert shared.installation_policy == "DEFAULT"
        assert shared.enabled is True


def test_bulk_failure_does_not_undo_other_skills(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    own_skill = SkillManager.create_custom(basic_user)
    other_skill = SkillManager.create_custom(admin_user)
    response = client.post(
        f"{API_SERVER_URL}/skills/bulk",
        headers=basic_user.headers,
        json={
            "skill_ids": [str(own_skill.id), str(other_skill.id)],
            "action": "share",
            "sharing": {"public_permission": "VIEWER"},
        },
    )
    response.raise_for_status()
    result = SkillBulkResponse.model_validate(response.json())
    assert result.succeeded == [own_skill.id]
    assert [failure.skill_id for failure in result.failed] == [other_skill.id]
    assert (
        SkillManager.get_for_user(own_skill.id, admin_user).public_permission
        == "VIEWER"
    )
    assert (
        SkillManager.get_for_user(other_skill.id, admin_user).public_permission is None
    )


def test_bulk_failure_after_write_rolls_back_only_that_skill(
    admin_user: DATestUser,
) -> None:
    name = f"dup-{uuid4().hex[:8]}"
    taken = SkillManager.create_custom(admin_user, name=name)
    conflicting = SkillManager.create_custom(admin_user, name=name, auto_enable=False)
    clean = SkillManager.create_custom(admin_user)

    def share(skill_ids: list[str]) -> SkillBulkResponse:
        response = client.post(
            f"{API_SERVER_URL}/skills/bulk",
            headers=admin_user.headers,
            json={
                "skill_ids": skill_ids,
                "action": "share",
                "sharing": {
                    "public_permission": "VIEWER",
                    "installation_policy": "DEFAULT",
                },
            },
        )
        response.raise_for_status()
        return SkillBulkResponse.model_validate(response.json())

    assert share([str(taken.id)]).failed == []
    # public_permission is written before the policy's unique index rejects the name
    result = share([str(conflicting.id), str(clean.id)])
    assert result.succeeded == [clean.id]
    assert [failure.skill_id for failure in result.failed] == [conflicting.id]
    rolled_back = SkillManager.get_for_user(conflicting.id, admin_user)
    assert rolled_back.public_permission is None
    assert rolled_back.installation_policy is None
    applied = SkillManager.get_for_user(clean.id, admin_user)
    assert applied.public_permission == "VIEWER"
    assert applied.installation_policy == "DEFAULT"


def test_bulk_toggle_changes_only_current_users_preferences(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    skills = [SkillManager.create_custom(admin_user, is_public=True) for _ in range(2)]
    for action, expected in [("enable", True), ("disable", False)]:
        response = client.post(
            f"{API_SERVER_URL}/skills/bulk",
            headers=basic_user.headers,
            json={"skill_ids": [str(skill.id) for skill in skills], "action": action},
        )
        response.raise_for_status()
        assert SkillBulkResponse.model_validate(response.json()).failed == []
        for skill in skills:
            assert SkillManager.get_for_user(skill.id, basic_user).enabled is expected
            assert SkillManager.get_for_user(skill.id, admin_user).enabled is True


def test_batch_upload_shares_at_creation_and_reports_invalid_bundles(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    names = [f"batch-{uuid4().hex[:8]}" for _ in range(2)]
    headers = dict(admin_user.headers)
    headers.pop("Content-Type", None)
    response = client.post(
        f"{API_SERVER_URL}/skills/custom/batch",
        headers=headers,
        files=[
            ("bundles", (f"{name}.zip", build_minimal_bundle(name), "application/zip"))
            for name in names
        ]
        + [("bundles", ("invalid.zip", b"invalid", "application/zip"))],
        data={
            "sharing": '{"public_permission":"VIEWER","installation_policy":"DEFAULT"}'
        },
    )
    response.raise_for_status()
    result = response.json()
    assert {item["skill"]["name"] for item in result["imported"]} == set(names)
    assert [item["path"] for item in result["not_imported"]] == ["invalid.zip"]
    for item in result["imported"]:
        shared = SkillManager.get_for_user(item["skill"]["id"], basic_user)
        assert shared.public_permission == "VIEWER"
        assert shared.enabled is True


def test_bulk_sharing_keeps_existing_direct_access(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    skill = SkillManager.create_custom(admin_user)
    SkillManager.share(
        skill,
        admin_user,
        user_shares=[
            SkillUserShareRequest(
                user_id=UUID(basic_user.id), permission=SkillSharePermission.EDITOR
            )
        ],
    )
    new_user = UserManager.create()
    response = client.post(
        f"{API_SERVER_URL}/skills/bulk",
        headers=admin_user.headers,
        json={
            "skill_ids": [str(skill.id)],
            "action": "share",
            "sharing": {
                "user_shares": [{"user_id": new_user.id, "permission": "VIEWER"}]
            },
        },
    )
    response.raise_for_status()
    assert SkillBulkResponse.model_validate(response.json()).failed == []
    editable = SkillManager.get_editable(skill.id, basic_user)
    assert {
        (str(share.user.id), share.permission) for share in editable.user_shares
    } == {
        (basic_user.id, SkillSharePermission.EDITOR),
        (new_user.id, SkillSharePermission.VIEWER),
    }


def test_bulk_delete_preserves_required_skill_for_non_admin(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    required_skill = SkillManager.create_custom(basic_user)
    ordinary_skill = SkillManager.create_custom(basic_user)
    policy_response = client.post(
        f"{API_SERVER_URL}/skills/bulk",
        headers=admin_user.headers,
        json={
            "skill_ids": [str(required_skill.id)],
            "action": "share",
            "sharing": {"installation_policy": "REQUIRED"},
        },
    )
    policy_response.raise_for_status()
    assert SkillBulkResponse.model_validate(policy_response.json()).failed == []
    response = client.post(
        f"{API_SERVER_URL}/skills/bulk",
        headers=basic_user.headers,
        json={
            "skill_ids": [str(required_skill.id), str(ordinary_skill.id)],
            "action": "delete",
        },
    )
    response.raise_for_status()
    result = SkillBulkResponse.model_validate(response.json())
    assert result.succeeded == [ordinary_skill.id]
    assert [failure.skill_id for failure in result.failed] == [required_skill.id]
    assert (
        SkillManager.get_for_user(required_skill.id, basic_user).installation_policy
        == "REQUIRED"
    )
    missing = client.get(
        f"{API_SERVER_URL}/skills/{ordinary_skill.id}", headers=basic_user.headers
    )
    assert missing.status_code == 404
