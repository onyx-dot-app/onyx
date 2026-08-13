"""Creator fallback for groupless non-public resources.

No managed scope matches a resource in no group, so without a creator fallback
detaching its last group strands it — invisible to its creator, and delete is
admin-only. Connectors had the fallback and document sets did not, so the same action
gave opposite outcomes. Both types are tested together to keep them from drifting.
"""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.connector_credential_pair import (
    get_connector_credential_pair_from_id_for_user,
    user_owns_groupless_cc_pair,
)
from onyx.db.document_set import (
    filter_document_set_ids_by_user_access,
    filter_document_set_names_by_user_access,
    get_document_set_by_id_for_user,
    user_owns_groupless_document_set,
)
from onyx.db.enums import AccessType
from onyx.db.models import (
    DocumentSet,
    DocumentSet__UserGroup,
    User,
    User__UserGroup,
    UserGroup,
    UserGroup__ConnectorCredentialPair,
)
from onyx.server.documents.cc_pair import _get_readable_cc_pair
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import make_cc_pair


@pytest.fixture
def manager(db_session: Session) -> User:
    user = create_test_user(db_session, "groupless-creator")
    user.effective_permissions = []
    user.is_group_manager = True
    db_session.commit()
    return user


def _managed_group(db_session: Session, user: User) -> UserGroup:
    group = UserGroup(name=f"gl-{uuid4().hex[:12]}")
    db_session.add(group)
    db_session.flush()
    db_session.add(
        User__UserGroup(user_id=user.id, user_group_id=group.id, is_manager=True)
    )
    db_session.commit()
    return group


def test_connector_creator_keeps_groupless_pair(
    db_session: Session, manager: User
) -> None:
    group = _managed_group(db_session, manager)
    cc_pair = make_cc_pair(db_session)
    cc_pair.access_type = AccessType.PRIVATE
    cc_pair.creator_id = manager.id
    db_session.add(
        UserGroup__ConnectorCredentialPair(
            user_group_id=group.id, cc_pair_id=cc_pair.id, is_current=True
        )
    )
    db_session.commit()

    assert (
        get_connector_credential_pair_from_id_for_user(
            cc_pair.id, db_session, manager, get_editable=True
        )
        is not None
    )

    # detach the only group; the creator fallback takes over
    db_session.query(UserGroup__ConnectorCredentialPair).filter_by(
        cc_pair_id=cc_pair.id
    ).delete()
    db_session.commit()

    assert (
        get_connector_credential_pair_from_id_for_user(
            cc_pair.id, db_session, manager, get_editable=True
        )
        is not None
    )

    # the read path stays as-is; the detail route falls back to the editable fetch
    assert (
        get_connector_credential_pair_from_id_for_user(
            cc_pair.id, db_session, manager, get_editable=False
        )
        is None
    ), "groupless pair leaked into the read path"


def test_detail_page_read_gate_admits_the_creator(
    db_session: Session, manager: User
) -> None:
    """The sub-resource routes gate on this; a 404 here hangs the page on its spinner
    because usePaginatedFetch never clears isLoading on error."""
    _managed_group(db_session, manager)
    cc_pair = make_cc_pair(db_session)
    cc_pair.access_type = AccessType.PRIVATE
    cc_pair.creator_id = manager.id
    db_session.commit()

    assert _get_readable_cc_pair(cc_pair.id, db_session, manager) is not None


def test_detail_page_read_gate_refuses_a_non_creator(
    db_session: Session, manager: User
) -> None:
    other = create_test_user(db_session, "groupless-gate-other")
    other.effective_permissions = []
    other.is_group_manager = True
    _managed_group(db_session, other)

    cc_pair = make_cc_pair(db_session)
    cc_pair.access_type = AccessType.PRIVATE
    cc_pair.creator_id = manager.id
    db_session.commit()

    assert _get_readable_cc_pair(cc_pair.id, db_session, other) is None


def test_delete_predicates_track_the_group_link(
    db_session: Session, manager: User
) -> None:
    """Both delete gates and both delete affordances read these, so a wrong answer
    either hides the button or lets a manager delete a shared resource."""
    group = _managed_group(db_session, manager)
    other = create_test_user(db_session, "groupless-del-other")

    cc_pair = make_cc_pair(db_session)
    cc_pair.access_type = AccessType.PRIVATE
    cc_pair.creator_id = manager.id
    doc_set = DocumentSet(
        name=f"gl-ds-{uuid4().hex[:12]}", is_public=False, user_id=manager.id
    )
    db_session.add(doc_set)
    db_session.commit()

    assert user_owns_groupless_cc_pair(cc_pair, db_session, manager)
    assert user_owns_groupless_document_set(doc_set, manager)
    assert not user_owns_groupless_cc_pair(cc_pair, db_session, other)
    assert not user_owns_groupless_document_set(doc_set, other)

    # attaching a group makes both shared, so both fall back to admin-only
    db_session.add(
        UserGroup__ConnectorCredentialPair(
            user_group_id=group.id, cc_pair_id=cc_pair.id, is_current=True
        )
    )
    db_session.add(
        DocumentSet__UserGroup(document_set_id=doc_set.id, user_group_id=group.id)
    )
    db_session.commit()
    db_session.refresh(doc_set)

    assert not user_owns_groupless_cc_pair(cc_pair, db_session, manager)
    assert not user_owns_groupless_document_set(doc_set, manager)

    # a stale junction row is not a share — the cc_pair predicate must ignore it
    db_session.query(UserGroup__ConnectorCredentialPair).filter_by(
        cc_pair_id=cc_pair.id
    ).update({"is_current": False})
    db_session.commit()
    assert user_owns_groupless_cc_pair(cc_pair, db_session, manager)


def test_connector_fallback_is_creator_only(db_session: Session, manager: User) -> None:
    """Only the creator, not every manager."""
    other = create_test_user(db_session, "groupless-conn-other")
    other.effective_permissions = []
    other.is_group_manager = True
    _managed_group(db_session, other)

    cc_pair = make_cc_pair(db_session)
    cc_pair.access_type = AccessType.PRIVATE
    cc_pair.creator_id = manager.id
    db_session.commit()

    for editable in (True, False):
        assert (
            get_connector_credential_pair_from_id_for_user(
                cc_pair.id, db_session, other, get_editable=editable
            )
            is None
        ), f"leaked to a non-creator with get_editable={editable}"


def test_document_set_creator_keeps_groupless_set(
    db_session: Session, manager: User
) -> None:
    group = _managed_group(db_session, manager)
    doc_set = DocumentSet(
        name=f"gl-ds-{uuid4().hex[:12]}", is_public=False, user_id=manager.id
    )
    db_session.add(doc_set)
    db_session.flush()
    db_session.add(
        DocumentSet__UserGroup(document_set_id=doc_set.id, user_group_id=group.id)
    )
    db_session.commit()

    assert (
        get_document_set_by_id_for_user(
            db_session=db_session,
            document_set_id=doc_set.id,
            user=manager,
            get_editable=True,
        )
        is not None
    )

    db_session.query(DocumentSet__UserGroup).filter_by(
        document_set_id=doc_set.id
    ).delete()
    db_session.commit()

    assert (
        get_document_set_by_id_for_user(
            db_session=db_session,
            document_set_id=doc_set.id,
            user=manager,
            get_editable=True,
        )
        is not None
    ), "creator lost their own groupless document set"

    # the read path stays as-is; the admin listing unions in the editable query
    assert (
        get_document_set_by_id_for_user(
            db_session=db_session,
            document_set_id=doc_set.id,
            user=manager,
            get_editable=False,
        )
        is None
    ), "groupless set leaked into the read path shared with search and chat"


def test_document_set_fallback_is_creator_only(
    db_session: Session, manager: User
) -> None:
    """Only the creator, not every manager."""
    other = create_test_user(db_session, "groupless-other")
    other.effective_permissions = []
    other.is_group_manager = True
    _managed_group(db_session, other)

    doc_set = DocumentSet(
        name=f"gl-ds-{uuid4().hex[:12]}", is_public=False, user_id=manager.id
    )
    db_session.add(doc_set)
    db_session.commit()

    for editable in (True, False):
        assert (
            get_document_set_by_id_for_user(
                db_session=db_session,
                document_set_id=doc_set.id,
                user=other,
                get_editable=editable,
            )
            is None
        ), f"leaked to a non-creator with get_editable={editable}"


def test_document_set_fallback_switches_off_once_grouped(
    db_session: Session, manager: User
) -> None:
    """~has_group is load-bearing: a set in an unmanaged group is refused again."""
    unmanaged = UserGroup(name=f"gl-unmanaged-{uuid4().hex[:12]}")
    db_session.add(unmanaged)
    db_session.flush()
    doc_set = DocumentSet(
        name=f"gl-ds-{uuid4().hex[:12]}", is_public=False, user_id=manager.id
    )
    db_session.add(doc_set)
    db_session.flush()
    db_session.add(
        DocumentSet__UserGroup(document_set_id=doc_set.id, user_group_id=unmanaged.id)
    )
    db_session.commit()

    assert (
        get_document_set_by_id_for_user(
            db_session=db_session,
            document_set_id=doc_set.id,
            user=manager,
            get_editable=True,
        )
        is None
    )


def test_pipeline_filters_ignore_the_creator_fallback(
    db_session: Session, manager: User
) -> None:
    """The entry points search, chat and persona validation actually call. A groupless
    set must stay invisible to them even for its creator — the fallback exists for the
    admin list, and widening these would change what a search may scope to."""
    group = _managed_group(db_session, manager)
    groupless = DocumentSet(
        name=f"gl-ds-{uuid4().hex[:12]}", is_public=False, user_id=manager.id
    )
    public = DocumentSet(
        name=f"gl-pub-{uuid4().hex[:12]}", is_public=True, user_id=manager.id
    )
    shared = DocumentSet(
        name=f"gl-shared-{uuid4().hex[:12]}", is_public=False, user_id=manager.id
    )
    db_session.add_all([groupless, public, shared])
    db_session.flush()
    db_session.add(
        DocumentSet__UserGroup(document_set_id=shared.id, user_group_id=group.id)
    )
    db_session.commit()

    names = [groupless.name, public.name, shared.name]
    visible = filter_document_set_names_by_user_access(
        db_session=db_session, document_set_names=names, user=manager
    )
    assert groupless.name not in visible, "groupless set reachable from search/chat"
    assert {public.name, shared.name} <= visible, "pipeline lost a set it should keep"

    ids = filter_document_set_ids_by_user_access(
        db_session=db_session,
        document_set_ids=[groupless.id, public.id, shared.id],
        user=manager,
    )
    assert groupless.id not in ids, "groupless set reachable from persona validation"
    assert {public.id, shared.id} <= set(ids)
