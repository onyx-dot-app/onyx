"""The OPERATE and EDIT access levels on cc-pairs.

A scoped manager passes when a group they manage holds a matching role on the pair,
whatever the pair's access type and whatever other groups manage it. Global
MANAGE_CONNECTORS passes everything.
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.db.user_group import update_user_group
from ee.onyx.server.user_group.models import UserGroupUpdate
from onyx.configs.constants import DocumentSource
from onyx.db.connector_credential_pair import (
    CCPairAccessLevel,
    get_cc_pair_access_sets_for_user,
    get_managed_cc_pair_ids,
    verify_user_can_edit_connector,
    verify_user_can_manage_all_cc_pairs,
    verify_user_has_access_to_cc_pair,
)
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    ConnectorManageRole,
)
from onyx.db.feedback import (
    fetch_docs_ranked_by_boost_for_user,
    update_document_boost_for_user,
    update_document_hidden_for_user,
)
from onyx.db.models import (
    ConnectorCredentialPair,
    Credential,
    DocumentByConnectorCredentialPair,
    User,
    User__UserGroup,
    UserGroup,
    UserGroup__CCPairDataAccess,
    UserGroup__ConnectorCredentialPair,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.connector import (
    _fetch_and_check_file_connector_cc_pair_permissions,
)
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import (
    make_cc_pair,
    seed_cc_pair_documents,
)

_MANAGE_LEVELS = (CCPairAccessLevel.OPERATE, CCPairAccessLevel.EDIT)


@pytest.fixture
def ee(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    fetch_versioned_implementation.cache_clear()
    monkeypatch.setattr(global_version, "is_ee_version", lambda: True)
    yield
    fetch_versioned_implementation.cache_clear()


def _group(db_session: Session) -> UserGroup:
    group = UserGroup(name=f"roles-{uuid4().hex[:12]}")
    db_session.add(group)
    db_session.flush()
    return group


def _manager_of(db_session: Session, prefix: str, group: UserGroup) -> User:
    user = create_test_user(db_session, prefix)
    user.effective_permissions = []
    user.is_group_manager = True
    db_session.add(
        User__UserGroup(user_id=user.id, user_group_id=group.id, is_manager=True)
    )
    db_session.commit()
    return user


def _pair(
    db_session: Session,
    access_type: AccessType,
    manage_rows: list[tuple[UserGroup, ConnectorManageRole]],
) -> ConnectorCredentialPair:
    cc_pair = make_cc_pair(db_session)
    cc_pair.access_type = access_type
    for group, role in manage_rows:
        db_session.add(
            UserGroup__ConnectorCredentialPair(
                user_group_id=group.id, cc_pair_id=cc_pair.id, role=role
            )
        )
    db_session.commit()
    return cc_pair


def _levels(
    db_session: Session, cc_pair: ConnectorCredentialPair, user: User
) -> dict[CCPairAccessLevel, bool]:
    return {
        level: verify_user_has_access_to_cc_pair(cc_pair.id, db_session, user, level)
        for level in _MANAGE_LEVELS
    }


def test_role_decides_operate_and_edit_for_every_access_type(
    db_session: Session,
) -> None:
    editor_group = _group(db_session)
    operator_group = _group(db_session)
    other_group = _group(db_session)
    editor = _manager_of(db_session, "roles-editor", editor_group)
    operator = _manager_of(db_session, "roles-operator", operator_group)
    no_role = _manager_of(db_session, "roles-norole", other_group)
    admin = create_test_user(db_session, "roles-admin", is_admin=True)

    for access_type in (AccessType.PRIVATE, AccessType.SYNC, AccessType.PUBLIC):
        cc_pair = _pair(
            db_session,
            access_type,
            [
                (editor_group, ConnectorManageRole.EDITOR),
                (operator_group, ConnectorManageRole.OPERATOR),
            ],
        )
        assert _levels(db_session, cc_pair, editor) == {
            CCPairAccessLevel.OPERATE: True,
            CCPairAccessLevel.EDIT: True,
        }, access_type
        assert _levels(db_session, cc_pair, operator) == {
            CCPairAccessLevel.OPERATE: True,
            CCPairAccessLevel.EDIT: False,
        }, access_type
        assert _levels(db_session, cc_pair, no_role) == {
            CCPairAccessLevel.OPERATE: False,
            CCPairAccessLevel.EDIT: False,
        }, access_type
        assert _levels(db_session, cc_pair, admin) == {
            CCPairAccessLevel.OPERATE: True,
            CCPairAccessLevel.EDIT: True,
        }, access_type


def test_role_needs_the_manager_edge(db_session: Session) -> None:
    """A plain member of an Editor group holds no management: only managers of the
    group hold the scoped MANAGE_CONNECTORS form."""
    group = _group(db_session)
    member = create_test_user(db_session, "roles-member")
    member.effective_permissions = []
    db_session.add(User__UserGroup(user_id=member.id, user_group_id=group.id))
    db_session.commit()
    cc_pair = _pair(
        db_session, AccessType.PRIVATE, [(group, ConnectorManageRole.EDITOR)]
    )

    assert _levels(db_session, cc_pair, member) == {
        CCPairAccessLevel.OPERATE: False,
        CCPairAccessLevel.EDIT: False,
    }


def test_role_ignores_stale_rows(db_session: Session) -> None:
    group = _group(db_session)
    editor = _manager_of(db_session, "roles-stale", group)
    cc_pair = _pair(db_session, AccessType.PRIVATE, [])
    db_session.add(
        UserGroup__ConnectorCredentialPair(
            user_group_id=group.id,
            cc_pair_id=cc_pair.id,
            role=ConnectorManageRole.EDITOR,
            is_current=False,
        )
    )
    db_session.commit()

    assert _levels(db_session, cc_pair, editor) == {
        CCPairAccessLevel.OPERATE: False,
        CCPairAccessLevel.EDIT: False,
    }


def test_groupless_creator_is_editor(db_session: Session) -> None:
    creator = _manager_of(db_session, "roles-creator", _group(db_session))
    cc_pair = _pair(db_session, AccessType.SYNC, [])
    cc_pair.creator_id = creator.id
    db_session.commit()

    assert _levels(db_session, cc_pair, creator) == {
        CCPairAccessLevel.OPERATE: True,
        CCPairAccessLevel.EDIT: True,
    }

    # An Operator row from another group makes the pair managed: the fallback stops.
    db_session.add(
        UserGroup__ConnectorCredentialPair(
            user_group_id=_group(db_session).id,
            cc_pair_id=cc_pair.id,
            role=ConnectorManageRole.OPERATOR,
        )
    )
    db_session.commit()
    assert _levels(db_session, cc_pair, creator) == {
        CCPairAccessLevel.OPERATE: False,
        CCPairAccessLevel.EDIT: False,
    }


def test_bulk_checks_need_the_level_on_every_pair(db_session: Session) -> None:
    editor_group = _group(db_session)
    operator_group = _group(db_session)
    user = _manager_of(db_session, "roles-bulk", editor_group)
    db_session.add(
        User__UserGroup(
            user_id=user.id, user_group_id=operator_group.id, is_manager=True
        )
    )
    db_session.commit()
    edited = _pair(
        db_session, AccessType.PRIVATE, [(editor_group, ConnectorManageRole.EDITOR)]
    )
    operated = _pair(
        db_session, AccessType.PRIVATE, [(operator_group, ConnectorManageRole.OPERATOR)]
    )
    both = {edited.id, operated.id}

    assert get_managed_cc_pair_ids(both, db_session, user, CCPairAccessLevel.EDIT) == {
        edited.id
    }
    assert verify_user_can_manage_all_cc_pairs(
        both, db_session, user, CCPairAccessLevel.OPERATE
    )
    assert not verify_user_can_manage_all_cc_pairs(
        both, db_session, user, CCPairAccessLevel.EDIT
    )
    # empty never authorizes
    assert not verify_user_can_manage_all_cc_pairs(
        set(), db_session, user, CCPairAccessLevel.OPERATE
    )


def test_connector_edit_needs_editor_on_every_pair(db_session: Session) -> None:
    group = _group(db_session)
    editor = _manager_of(db_session, "roles-conn", group)
    admin = create_test_user(db_session, "roles-conn-admin", is_admin=True)
    cc_pair = _pair(
        db_session, AccessType.PRIVATE, [(group, ConnectorManageRole.EDITOR)]
    )

    assert verify_user_can_edit_connector(cc_pair.connector_id, db_session, editor)

    row = db_session.get(
        UserGroup__ConnectorCredentialPair, (group.id, cc_pair.id, True)
    )
    assert row is not None
    row.role = ConnectorManageRole.OPERATOR
    db_session.commit()
    assert not verify_user_can_edit_connector(cc_pair.connector_id, db_session, editor)
    assert verify_user_can_edit_connector(cc_pair.connector_id, db_session, admin)


@pytest.mark.usefixtures("ee")
def test_manage_roles_and_data_access_are_independent(db_session: Session) -> None:
    """Manage rows grant no documents, and data-access rows grant no management."""
    editor_group = _group(db_session)
    operator_group = _group(db_session)
    data_group = _group(db_session)
    editor = _manager_of(db_session, "roles-indep-editor", editor_group)
    operator = _manager_of(db_session, "roles-indep-operator", operator_group)
    reader = _manager_of(db_session, "roles-indep-reader", data_group)
    cc_pair = _pair(
        db_session,
        AccessType.PRIVATE,
        [
            (editor_group, ConnectorManageRole.EDITOR),
            (operator_group, ConnectorManageRole.OPERATOR),
        ],
    )
    db_session.add(
        UserGroup__CCPairDataAccess(user_group_id=data_group.id, cc_pair_id=cc_pair.id)
    )
    db_session.commit()

    for manager in (editor, operator):
        access_sets = get_cc_pair_access_sets_for_user(db_session, manager)
        assert cc_pair.id not in access_sets.open_cc_pair_ids, manager.email
        assert cc_pair.id not in access_sets.acl_cc_pair_ids, manager.email

    assert (
        cc_pair.id
        in get_cc_pair_access_sets_for_user(db_session, reader).open_cc_pair_ids
    )
    assert _levels(db_session, cc_pair, reader) == {
        CCPairAccessLevel.OPERATE: False,
        CCPairAccessLevel.EDIT: False,
    }


def test_feedback_needs_operate_on_every_pair_of_the_document(
    db_session: Session,
) -> None:
    operator_group = _group(db_session)
    other_group = _group(db_session)
    operator = _manager_of(db_session, "roles-feedback", operator_group)
    operated = _pair(
        db_session, AccessType.PRIVATE, [(operator_group, ConnectorManageRole.OPERATOR)]
    )
    other = _pair(
        db_session, AccessType.PRIVATE, [(other_group, ConnectorManageRole.EDITOR)]
    )
    [own_doc] = seed_cc_pair_documents(
        db_session, operated, 1, prefix="fb-own-", unique=True
    )
    [shared_doc, other_doc] = seed_cc_pair_documents(
        db_session, other, 2, prefix="fb-other-", unique=True
    )
    db_session.add(
        DocumentByConnectorCredentialPair(
            id=shared_doc,
            connector_id=operated.connector_id,
            credential_id=operated.credential_id,
            has_been_indexed=True,
        )
    )
    db_session.commit()

    ranked = {
        doc.id for doc in fetch_docs_ranked_by_boost_for_user(db_session, operator)
    }
    assert {own_doc, shared_doc} <= ranked
    assert other_doc not in ranked

    update_document_boost_for_user(db_session, own_doc, 3, operator)
    update_document_hidden_for_user(db_session, own_doc, True, operator)
    for doc_id in (shared_doc, other_doc):
        with pytest.raises(HTTPException):
            update_document_boost_for_user(db_session, doc_id, 3, operator)
        with pytest.raises(HTTPException):
            update_document_hidden_for_user(db_session, doc_id, True, operator)


@pytest.mark.usefixtures("ee")
def test_legacy_group_update_keeps_roles_and_needs_editor_to_attach(
    db_session: Session,
) -> None:
    operator_group = _group(db_session)
    other_group = _group(db_session)
    operator_group.is_up_to_date = other_group.is_up_to_date = True
    manager = _manager_of(db_session, "roles-legacy", operator_group)
    db_session.add(
        User__UserGroup(
            user_id=manager.id, user_group_id=other_group.id, is_manager=True
        )
    )
    db_session.commit()
    operated = _pair(
        db_session, AccessType.PRIVATE, [(operator_group, ConnectorManageRole.OPERATOR)]
    )
    own = _pair(db_session, AccessType.PRIVATE, [])
    own.creator_id = manager.id
    db_session.commit()

    # A kept pair keeps its role, and a newly attached pair gets EDITOR.
    update_user_group(
        db_session,
        manager,
        operator_group.id,
        UserGroupUpdate(user_ids=[manager.id], cc_pair_ids=[operated.id, own.id]),
    )
    roles = dict(
        db_session.execute(
            select(
                UserGroup__ConnectorCredentialPair.cc_pair_id,
                UserGroup__ConnectorCredentialPair.role,
            ).where(
                UserGroup__ConnectorCredentialPair.user_group_id == operator_group.id,
                UserGroup__ConnectorCredentialPair.is_current.is_(True),
            )
        )
        .tuples()
        .all()
    )
    assert roles == {
        operated.id: ConnectorManageRole.OPERATOR,
        own.id: ConnectorManageRole.EDITOR,
    }

    # Attaching the operated pair to another group would make its manager an Editor.
    with pytest.raises(OnyxError):
        update_user_group(
            db_session,
            manager,
            other_group.id,
            UserGroupUpdate(user_ids=[manager.id], cc_pair_ids=[operated.id]),
        )


def test_file_connector_needs_the_level_on_every_pair(db_session: Session) -> None:
    group = _group(db_session)
    other_group = _group(db_session)
    editor = _manager_of(db_session, "roles-file", group)
    first = make_cc_pair(db_session, DocumentSource.FILE)
    first.access_type = AccessType.PRIVATE
    credential = Credential(source=DocumentSource.FILE, credential_json={})
    db_session.add(credential)
    db_session.flush()
    second = ConnectorCredentialPair(
        connector_id=first.connector_id,
        credential_id=credential.id,
        name=f"roles-file-{uuid4().hex[:8]}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PRIVATE,
    )
    db_session.add(second)
    db_session.flush()
    db_session.add_all(
        [
            UserGroup__ConnectorCredentialPair(
                user_group_id=group.id,
                cc_pair_id=first.id,
                role=ConnectorManageRole.EDITOR,
            ),
            UserGroup__ConnectorCredentialPair(
                user_group_id=other_group.id,
                cc_pair_id=second.id,
                role=ConnectorManageRole.EDITOR,
            ),
        ]
    )
    db_session.commit()

    # The file list is shared config, so an Editor of one pair is not enough.
    for level in _MANAGE_LEVELS:
        with pytest.raises(OnyxError):
            _fetch_and_check_file_connector_cc_pair_permissions(
                first.connector_id, editor, db_session, level
            )

    db_session.add(
        UserGroup__ConnectorCredentialPair(
            user_group_id=group.id,
            cc_pair_id=second.id,
            role=ConnectorManageRole.EDITOR,
        )
    )
    db_session.commit()
    for level in _MANAGE_LEVELS:
        _fetch_and_check_file_connector_cc_pair_permissions(
            first.connector_id, editor, db_session, level
        )
