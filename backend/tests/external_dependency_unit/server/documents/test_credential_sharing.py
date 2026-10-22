"""Credential sharing: who sees a saved credential, and who may change its
sharing. "Admins" (admin_public) reaches global MANAGE_CONNECTORS holders;
groups (EE) reach the users who hold Manage Connectors in a named group."""

from collections.abc import Generator, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.factory import assert_user_can_use_credential
from onyx.connectors.models import InputType
from onyx.db.credentials import (
    CredentialAccessLevel,
    delete_credential_for_user,
    fetch_credential_by_id_for_user,
    update_credential,
)
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    Credential__UserGroup,
    User,
    User__UserGroup,
    UserGroup,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import credential as credential_api
from onyx.server.documents.cc_pair import get_cc_pair_full_info
from onyx.server.documents.connector import get_connector_status
from onyx.server.documents.credential import (
    get_cc_source_full_info,
    get_credential_by_id,
    list_credentials,
    list_credentials_admin,
    update_credential_sharing_endpoint,
)
from onyx.server.documents.models import (
    CredentialBase,
    CredentialSharing,
    CredentialSnapshot,
)
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

_SOURCE = DocumentSource.MOCK_CONNECTOR


@dataclass
class _Env:
    owner: User
    admin: User
    # An admin who is a plain member of ``group``.
    admin_member: User
    # A group manager of ``group``: Manage Connectors scoped to it.
    manager: User
    # A plain member of ``group`` without Manage Connectors.
    member: User
    # A group manager of ``other_group`` only.
    other_manager: User
    group: UserGroup
    other_group: UserGroup


def _credential(
    db_session: Session,
    owner: User | None,
    *,
    admin_public: bool,
    groups: list[UserGroup] | None = None,
) -> Credential:
    credential = Credential(
        name=f"share-{uuid4().hex[:8]}",
        source=_SOURCE,
        credential_json={"token": "secret"},
        user_id=owner.id if owner else None,
        admin_public=admin_public,
    )
    db_session.add(credential)
    db_session.flush()
    for group in groups or []:
        db_session.add(
            Credential__UserGroup(credential_id=credential.id, user_group_id=group.id)
        )
    db_session.commit()
    return credential


@pytest.fixture
def env(db_session: Session, tenant_context: None) -> Generator[_Env, None, None]:  # noqa: ARG001
    owner = create_test_user(db_session, "share_owner")
    admin = create_test_user(db_session, "share_admin", is_admin=True)
    admin_member = create_test_user(db_session, "share_admin_member", is_admin=True)
    manager = create_test_user(db_session, "share_manager")
    member = create_test_user(db_session, "share_member")
    other_manager = create_test_user(db_session, "share_other_manager")
    group = UserGroup(name=f"share-group-{uuid4().hex[:8]}")
    other_group = UserGroup(name=f"share-other-{uuid4().hex[:8]}")
    db_session.add_all([group, other_group])
    db_session.flush()
    db_session.add_all(
        [
            User__UserGroup(
                user_id=manager.id, user_group_id=group.id, is_manager=True
            ),
            User__UserGroup(user_id=owner.id, user_group_id=group.id, is_manager=True),
            User__UserGroup(user_id=member.id, user_group_id=group.id),
            User__UserGroup(user_id=admin_member.id, user_group_id=group.id),
            User__UserGroup(
                user_id=other_manager.id,
                user_group_id=other_group.id,
                is_manager=True,
            ),
        ]
    )
    for user in (manager, owner, other_manager):
        user.is_group_manager = True
    db_session.commit()

    yield _Env(
        owner=owner,
        admin=admin,
        admin_member=admin_member,
        manager=manager,
        member=member,
        other_manager=other_manager,
        group=group,
        other_group=other_group,
    )

    db_session.rollback()
    group_ids = [group.id, other_group.id]
    db_session.execute(
        delete(Credential__UserGroup).where(
            Credential__UserGroup.user_group_id.in_(group_ids)
        )
    )
    users = [owner, admin, admin_member, manager, member, other_manager]
    db_session.execute(
        delete(Credential).where(Credential.user_id.in_([u.id for u in users]))
    )
    db_session.execute(
        delete(User__UserGroup).where(User__UserGroup.user_group_id.in_(group_ids))
    )
    db_session.execute(delete(UserGroup).where(UserGroup.id.in_(group_ids)))
    db_session.commit()
    delete_test_user(db_session, *users)


@pytest.fixture
def community_edition() -> Generator[None, None, None]:
    was_ee = global_version.is_ee_version()
    global_version.unset_ee()
    fetch_versioned_implementation.cache_clear()
    yield
    if was_ee:
        global_version.set_ee()
    fetch_versioned_implementation.cache_clear()


def _visible_ids(user: User, db_session: Session) -> set[int]:
    return {
        snapshot.id
        for snapshot in list_credentials_admin(user=user, db_session=db_session)
    }


@pytest.mark.usefixtures("enable_ee")
def test_only_me_is_visible_to_the_owner_only(env: _Env, db_session: Session) -> None:
    credential = _credential(db_session, env.owner, admin_public=False)

    assert credential.id in _visible_ids(env.owner, db_session)
    for user in (env.admin, env.admin_member, env.manager, env.member):
        assert credential.id not in _visible_ids(user, db_session)


@pytest.mark.usefixtures("enable_ee")
def test_admins_reach_global_connector_managers_only(
    env: _Env, db_session: Session
) -> None:
    credential = _credential(db_session, env.owner, admin_public=True)

    assert credential.id in _visible_ids(env.admin, db_session)
    # A group manager is no admin: scoped Manage Connectors does not count.
    assert credential.id not in _visible_ids(env.manager, db_session)
    assert credential.id not in _visible_ids(env.member, db_session)


@pytest.mark.usefixtures("enable_ee")
def test_groups_reach_connector_managers_in_the_group(
    env: _Env, db_session: Session
) -> None:
    credential = _credential(
        db_session, env.owner, admin_public=False, groups=[env.group]
    )

    assert credential.id in _visible_ids(env.manager, db_session)
    assert credential.id in _visible_ids(env.admin_member, db_session)
    # A member without Manage Connectors, a manager of another group, and an
    # admin outside the group do not get it.
    assert (
        fetch_credential_by_id_for_user(credential.id, env.member, db_session) is None
    )
    assert credential.id not in _visible_ids(env.other_manager, db_session)
    assert credential.id not in _visible_ids(env.admin, db_session)


@pytest.mark.usefixtures("enable_ee")
def test_shared_users_cannot_edit_or_delete(env: _Env, db_session: Session) -> None:
    credential = _credential(
        db_session, env.owner, admin_public=False, groups=[env.group]
    )

    assert (
        fetch_credential_by_id_for_user(
            credential.id,
            env.manager,
            db_session,
            access_level=CredentialAccessLevel.EDIT,
        )
        is None
    )
    with pytest.raises(OnyxError) as exc:
        delete_credential_for_user(credential.id, env.manager, db_session)
    assert exc.value.error_code is OnyxErrorCode.CREDENTIAL_NOT_FOUND
    with pytest.raises(OnyxError) as exc:
        update_credential_sharing_endpoint(
            credential.id,
            CredentialSharing(admin_public=True),
            user=env.manager,
            db_session=db_session,
        )
    assert exc.value.error_code is OnyxErrorCode.CREDENTIAL_NOT_FOUND


@pytest.mark.usefixtures("enable_ee")
def test_snapshot_reports_groups_and_owner(env: _Env, db_session: Session) -> None:
    credential = _credential(
        db_session, env.owner, admin_public=True, groups=[env.group]
    )

    owner_view = get_credential_by_id(
        credential.id, user=env.owner, db_session=db_session
    )
    manager_view = get_credential_by_id(
        credential.id, user=env.manager, db_session=db_session
    )

    assert isinstance(owner_view, CredentialSnapshot)
    assert isinstance(manager_view, CredentialSnapshot)
    assert owner_view.groups == [env.group.id]
    assert owner_view.is_owner is True
    assert manager_view.is_owner is False


@pytest.mark.usefixtures("enable_ee")
def test_owner_changes_sharing(env: _Env, db_session: Session) -> None:
    credential = _credential(db_session, env.owner, admin_public=False)

    snapshot = update_credential_sharing_endpoint(
        credential.id,
        CredentialSharing(admin_public=True, groups=[env.group.id]),
        user=env.owner,
        db_session=db_session,
    )

    assert snapshot.admin_public is True
    assert snapshot.groups == [env.group.id]
    assert snapshot.name == credential.name
    assert credential.id in _visible_ids(env.manager, db_session)

    # Back to "Only Me".
    snapshot = update_credential_sharing_endpoint(
        credential.id,
        CredentialSharing(admin_public=False),
        user=env.owner,
        db_session=db_session,
    )
    assert snapshot.groups == []
    assert credential.id not in _visible_ids(env.manager, db_session)
    assert credential.id not in _visible_ids(env.admin, db_session)


@pytest.mark.usefixtures("enable_ee")
def test_scoped_owner_cannot_share_outside_their_groups(
    env: _Env, db_session: Session
) -> None:
    credential = _credential(db_session, env.owner, admin_public=False)

    with pytest.raises(OnyxError) as exc:
        update_credential_sharing_endpoint(
            credential.id,
            CredentialSharing(admin_public=False, groups=[env.other_group.id]),
            user=env.owner,
            db_session=db_session,
        )
    assert exc.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS


@pytest.mark.usefixtures("enable_ee")
def test_admin_changes_sharing_of_an_admin_credential(
    env: _Env, db_session: Session
) -> None:
    credential = _credential(db_session, env.owner, admin_public=True)

    snapshot = update_credential_sharing_endpoint(
        credential.id,
        CredentialSharing(admin_public=True, groups=[env.other_group.id]),
        user=env.admin,
        db_session=db_session,
    )

    assert snapshot.groups == [env.other_group.id]
    # The owner stays the owner.
    assert snapshot.user_id == env.owner.id


@pytest.mark.usefixtures("enable_ee")
def test_unknown_group_is_rejected(env: _Env, db_session: Session) -> None:
    credential = _credential(db_session, env.owner, admin_public=True)

    with pytest.raises(OnyxError) as exc:
        update_credential_sharing_endpoint(
            credential.id,
            CredentialSharing(admin_public=True, groups=[-1]),
            user=env.admin,
            db_session=db_session,
        )
    assert exc.value.error_code is OnyxErrorCode.INVALID_INPUT


@pytest.mark.usefixtures("community_edition")
def test_community_edition_rejects_groups(env: _Env, db_session: Session) -> None:
    credential = _credential(db_session, env.owner, admin_public=True)

    with pytest.raises(OnyxError) as exc:
        update_credential_sharing_endpoint(
            credential.id,
            CredentialSharing(admin_public=True, groups=[env.group.id]),
            user=env.admin,
            db_session=db_session,
        )
    assert exc.value.error_code is OnyxErrorCode.FEATURE_NOT_AVAILABLE


@pytest.mark.usefixtures("community_edition")
def test_community_edition_ignores_stored_groups(
    env: _Env, db_session: Session
) -> None:
    credential = _credential(
        db_session, env.owner, admin_public=False, groups=[env.group]
    )

    assert credential.id not in _visible_ids(env.manager, db_session)


@pytest.mark.usefixtures("enable_ee")
def test_update_keeps_the_owner(env: _Env, db_session: Session) -> None:
    credential = _credential(db_session, env.owner, admin_public=True)

    updated = update_credential(
        credential.id,
        CredentialBase(
            credential_json={"token": "rotated"},
            admin_public=True,
            source=_SOURCE,
        ),
        env.admin,
        db_session,
    )

    assert updated is not None
    assert updated.user_id == env.owner.id


# Secret values: a user who may reuse a credential but not edit it never gets
# them, whatever the workspace masking setting.

_SECRET = "secret-token-0123456789abcdef"


@pytest.fixture
def masking_off() -> Generator[None, None, None]:
    settings = SimpleNamespace(mask_credential_prefix=False)
    with patch.object(credential_api, "get_security_settings", return_value=settings):
        yield


def _secret_credential(
    db_session: Session,
    owner: User,
    *,
    admin_public: bool,
    groups: list[UserGroup] | None = None,
) -> Credential:
    credential = _credential(
        db_session, owner, admin_public=admin_public, groups=groups
    )
    credential.credential_json = {"token": _SECRET}  # ty: ignore[invalid-assignment]
    db_session.commit()
    return credential


def _token_by_id(snapshots: Sequence[CredentialSnapshot]) -> dict[int, str]:
    return {s.id: s.credential_json["token"] for s in snapshots}


@pytest.mark.usefixtures("enable_ee", "masking_off")
def test_shared_user_gets_masked_values(env: _Env, db_session: Session) -> None:
    credential = _secret_credential(
        db_session, env.owner, admin_public=False, groups=[env.group]
    )

    for user, expect_secret in ((env.owner, True), (env.manager, False)):
        single = get_credential_by_id(credential.id, user=user, db_session=db_session)
        assert isinstance(single, CredentialSnapshot)
        tokens = [
            single.credential_json["token"],
            _token_by_id(list_credentials(user=user, db_session=db_session))[
                credential.id
            ],
            _token_by_id(list_credentials_admin(user=user, db_session=db_session))[
                credential.id
            ],
            _token_by_id(
                get_cc_source_full_info(_SOURCE, user=user, db_session=db_session)
            )[credential.id],
        ]
        for token in tokens:
            # A masked value keeps its key, so the form still sees the field.
            assert (token == _SECRET) is expect_secret, user.email


@pytest.mark.usefixtures("enable_ee", "masking_off")
def test_pair_views_mask_a_credential_the_reader_cannot_edit(
    env: _Env, db_session: Session
) -> None:
    private = _secret_credential(
        db_session, env.owner, admin_public=False, groups=[env.group]
    )
    admin_shared = _secret_credential(db_session, env.owner, admin_public=True)
    pairs = []
    for credential in (private, admin_shared):
        connector = Connector(
            name=f"share-{uuid4().hex[:8]}",
            source=_SOURCE,
            input_type=InputType.POLL,
            connector_specific_config={},
        )
        db_session.add(connector)
        db_session.flush()
        pair = ConnectorCredentialPair(
            name=f"share-{uuid4().hex[:8]}",
            connector_id=connector.id,
            credential_id=credential.id,
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=AccessType.PUBLIC,
        )
        db_session.add(pair)
        db_session.commit()
        pairs.append(pair)
    try:
        # The admin reads every pair, but can edit only the admin credential.
        full_infos = [
            get_cc_pair_full_info(pair.id, user=env.admin, db_session=db_session)
            for pair in pairs
        ]
        assert full_infos[0].credential.credential_json["token"] != _SECRET
        assert full_infos[1].credential.credential_json["token"] == _SECRET

        statuses = {
            status.cc_pair_id: status.credential.credential_json.get("token")
            for status in get_connector_status(user=env.admin, db_session=db_session)
        }
        assert statuses[pairs[0].id] != _SECRET
        assert statuses[pairs[1].id] == _SECRET
    finally:
        for pair in pairs:
            connector_id = pair.connector_id
            db_session.delete(pair)
            db_session.flush()
            db_session.execute(delete(Connector).where(Connector.id == connector_id))
        db_session.commit()


@pytest.mark.usefixtures("enable_ee")
def test_group_shared_user_falls_under_the_use_rule(
    env: _Env, db_session: Session
) -> None:
    site = "https://acme.atlassian.net"
    credential = Credential(
        name=f"share-{uuid4().hex[:8]}",
        source=DocumentSource.CONFLUENCE,
        credential_json={"confluence_access_token": _SECRET},
        user_id=env.owner.id,
        admin_public=False,
    )
    db_session.add(credential)
    db_session.flush()
    db_session.add(
        Credential__UserGroup(credential_id=credential.id, user_group_id=env.group.id)
    )
    connector = Connector(
        name=f"share-{uuid4().hex[:8]}",
        source=DocumentSource.CONFLUENCE,
        input_type=InputType.POLL,
        connector_specific_config={"wiki_base": site, "is_cloud": True},
    )
    db_session.add(connector)
    db_session.flush()
    pair = ConnectorCredentialPair(
        name=f"share-{uuid4().hex[:8]}",
        connector_id=connector.id,
        credential_id=credential.id,
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
    )
    db_session.add(pair)
    db_session.commit()

    def use(wiki_base: str) -> None:
        assert_user_can_use_credential(
            db_session,
            user=env.manager,
            credential=credential,
            source=DocumentSource.CONFLUENCE,
            connector_specific_config={"wiki_base": wiki_base, "is_cloud": True},
        )

    try:
        use(site)
        with pytest.raises(OnyxError) as exc:
            use("https://attacker.example.com")
        assert exc.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    finally:
        db_session.delete(pair)
        db_session.flush()
        db_session.execute(delete(Connector).where(Connector.id == connector.id))
        db_session.commit()
