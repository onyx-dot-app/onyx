"""SCIM reaches only accounts and groups it provisions.

The token is a provisioning credential: it must not adopt or deactivate an
admin it did not provision, nor write the seeded default groups.
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.server.scim.api import (
    create_group,
    create_user,
    patch_group,
    patch_user,
    replace_user,
)
from ee.onyx.server.scim.models import (
    ScimGroupMember,
    ScimGroupResource,
    ScimPatchOperation,
    ScimPatchOperationType,
    ScimPatchRequest,
    ScimUserResource,
)
from ee.onyx.server.scim.providers.base import get_default_provider
from onyx.db.enums import AccountType, Permission
from onyx.db.models import ScimToken, ScimUserMapping, User, UserGroup
from onyx.db.users import user_is_admin
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user


@pytest.fixture
def token(db_session: Session) -> Generator[ScimToken, None, None]:
    owner = create_test_user(db_session, "scim_guard_owner")
    scim_token = ScimToken(
        name="scim-guard",
        hashed_token=uuid4().hex,
        token_display="onyx_scim_****guard",
        created_by_id=owner.id,
    )
    db_session.add(scim_token)
    db_session.commit()
    try:
        yield scim_token
    finally:
        db_session.rollback()
        db_session.delete(scim_token)
        delete_test_user(db_session, owner)
        db_session.commit()


def _status(result: object) -> int:
    assert isinstance(result, JSONResponse)
    return result.status_code


def _has_mapping(db_session: Session, user: User) -> bool:
    return (
        db_session.scalar(
            select(ScimUserMapping).where(ScimUserMapping.user_id == user.id)
        )
        is not None
    )


def _deactivate() -> ScimPatchRequest:
    return ScimPatchRequest(
        Operations=[
            ScimPatchOperation(
                op=ScimPatchOperationType.REPLACE, path="active", value=False
            )
        ]
    )


def test_unmanaged_admin_cannot_be_adopted_or_deactivated(
    db_session: Session, token: ScimToken
) -> None:
    admin = create_test_user(db_session, "scim_guard_admin", is_admin=True)
    provider = get_default_provider()
    resource = ScimUserResource(
        userName=admin.email, externalId="ext-guard-admin", active=False
    )

    adopt = create_user(resource, token, provider, db_session)
    put = replace_user(str(admin.id), resource, token, provider, db_session)
    patch = patch_user(str(admin.id), _deactivate(), token, provider, db_session)

    assert [_status(adopt), _status(put), _status(patch)] == [403, 404, 404]
    db_session.expire_all()
    assert admin.is_active
    assert user_is_admin(admin)
    assert not _has_mapping(db_session, admin)

    delete_test_user(db_session, admin)
    db_session.commit()


def test_default_admin_group_membership_is_out_of_reach(
    db_session: Session, token: ScimToken
) -> None:
    user = create_test_user(db_session, "scim_guard_member")
    admin_group = db_session.scalar(
        select(UserGroup).where(
            UserGroup.is_default.is_(True), UserGroup.name == "Admin"
        )
    )
    assert admin_group is not None
    add = ScimPatchRequest(
        Operations=[
            ScimPatchOperation(
                op=ScimPatchOperationType.ADD,
                path="members",
                value=[ScimGroupMember(value=str(user.id))],
            )
        ]
    )

    result = patch_group(
        str(admin_group.id), add, token, get_default_provider(), db_session
    )

    assert _status(result) == 404
    db_session.expire_all()
    assert Permission.FULL_ADMIN_PANEL_ACCESS not in user.effective_permissions

    delete_test_user(db_session, user)
    db_session.commit()


def test_bot_account_cannot_join_a_group(db_session: Session, token: ScimToken) -> None:
    bot = create_test_user(
        db_session,
        "scim_guard_bot",
        account_type=AccountType.BOT,
        assign_default_group=False,
    )
    name = f"scim-guard-{uuid4().hex[:12]}"

    result = create_group(
        ScimGroupResource(
            displayName=name, members=[ScimGroupMember(value=str(bot.id))]
        ),
        token,
        get_default_provider(),
        db_session,
    )

    assert _status(result) == 400
    assert db_session.scalar(select(UserGroup).where(UserGroup.name == name)) is None

    delete_test_user(db_session, bot)
    db_session.commit()
