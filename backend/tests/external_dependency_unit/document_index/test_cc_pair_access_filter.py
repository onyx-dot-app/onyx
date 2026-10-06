"""Query-time cc-pair access: the per-user allowed cc-pair sets, the OpenSearch
filter built from them, shadow mode, and the enforce gate.

Uses real Postgres and OpenSearch. Chunks are written with the access and
cc_pair_ids that indexing computes from Postgres.
"""

from collections.abc import Generator
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ee.onyx.db.cc_pair_data_access import (
    fetch_data_access_cc_pair_ids_for_user_group,
    set_cc_pair_data_access_groups__no_commit,
)
from ee.onyx.db.user_group import prepare_user_group_for_deletion
from onyx.access.access import get_access_for_documents, user_can_access_chat_file
from onyx.access.cc_pair_access import get_cc_pair_access_mode
from onyx.access.models import DocumentAccess
from onyx.background.celery.tasks.vespa.tasks import document_index_metadata_sync_task
from onyx.configs.constants import ANONYMOUS_USER_EMAIL, ANONYMOUS_USER_UUID
from onyx.context.search.models import CCPairAccessMode, IndexFilters
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.db.connector_credential_pair import (
    build_user_cc_pair_access_filter,
    get_cc_pair_access_sets_for_user,
    has_guarded_cc_pairs,
)
from onyx.db.connector_edit_requests import apply_access_change__no_commit
from onyx.db.document import (
    get_cc_pair_ids_for_documents,
    upsert_document_by_connector_credential_pair,
)
from onyx.db.document_access import get_accessible_documents_by_ids
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    ConnectorManageRole,
)
from onyx.db.models import (
    ConnectorCredentialPair,
    User,
    UserGroup,
    UserGroup__CCPairDataAccess,
    UserGroup__ConnectorCredentialPair,
)
from onyx.db.models import Document as DbDocument
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.interfaces import DocumentSectionRequest, TenantState
from onyx.document_index.opensearch import (
    cc_pair_ids_backfill,
    opensearch_document_index,
)
from onyx.document_index.opensearch.client import OpenSearchIndexClient
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.schema import get_opensearch_doc_chunk_id
from onyx.server.runtime.onyx_runtime import OnyxRuntime
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.db.agent_sharing_helpers import (
    create_test_user_group,
)
from tests.external_dependency_unit.document_index.conftest import (
    make_chunk,
    make_indexing_metadata,
)
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_ACCESS_FILTERS_MODULE = "onyx.context.search.preprocessing.access_filters"


class _World(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    owner: User  # owns the private pair's credential
    member: User  # in the private pair's data-access group
    manager: User  # in a group that only manages the private pair
    outsider: User
    external_user: User  # named in a synced document's external ACL
    anonymous: User
    group: UserGroup
    manage_group: UserGroup
    public_pair: ConnectorCredentialPair
    private_pair: ConnectorCredentialPair
    sync_pair: ConnectorCredentialPair
    deleting_pair: ConnectorCredentialPair


def _set_ee(monkeypatch: pytest.MonkeyPatch, is_ee: bool) -> None:
    fetch_versioned_implementation.cache_clear()
    monkeypatch.setattr(global_version, "is_ee_version", lambda: is_ee)


@pytest.fixture
def ee(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    _set_ee(monkeypatch, True)
    yield
    fetch_versioned_implementation.cache_clear()


@pytest.fixture
def ce(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    _set_ee(monkeypatch, False)
    yield
    fetch_versioned_implementation.cache_clear()


def _make_pair(
    db_session: Session,
    access_type: AccessType,
    status: ConnectorCredentialPairStatus = ConnectorCredentialPairStatus.ACTIVE,
) -> ConnectorCredentialPair:
    pair = make_cc_pair(db_session)
    pair.access_type = access_type
    pair.status = status
    db_session.commit()
    return pair


@pytest.fixture
def world(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[_World, None, None]:
    owner = create_test_user(db_session, "cc_access_owner")
    member = create_test_user(db_session, "cc_access_member")
    manager = create_test_user(db_session, "cc_access_manager")
    outsider = create_test_user(db_session, "cc_access_outsider")
    external_user = create_test_user(db_session, "cc_access_external")
    group = create_test_user_group(db_session, members=[member])
    manage_group = create_test_user_group(db_session, members=[manager])

    public_pair = _make_pair(db_session, AccessType.PUBLIC)
    private_pair = _make_pair(db_session, AccessType.PRIVATE)
    private_pair.credential.user_id = owner.id
    sync_pair = _make_pair(db_session, AccessType.SYNC)
    deleting_pair = _make_pair(
        db_session, AccessType.PRIVATE, ConnectorCredentialPairStatus.DELETING
    )
    for pair in (private_pair, deleting_pair):
        db_session.add(
            UserGroup__CCPairDataAccess(user_group_id=group.id, cc_pair_id=pair.id)
        )
    # Manage rows grant no data access.
    db_session.add(
        UserGroup__ConnectorCredentialPair(
            user_group_id=manage_group.id,
            cc_pair_id=private_pair.id,
            is_current=True,
            role=ConnectorManageRole.EDITOR,
        )
    )
    db_session.commit()

    try:
        yield _World(
            owner=owner,
            member=member,
            manager=manager,
            outsider=outsider,
            external_user=external_user,
            anonymous=User(id=UUID(ANONYMOUS_USER_UUID), email=ANONYMOUS_USER_EMAIL),
            group=group,
            manage_group=manage_group,
            public_pair=public_pair,
            private_pair=private_pair,
            sync_pair=sync_pair,
            deleting_pair=deleting_pair,
        )
    finally:
        db_session.rollback()
        db_session.execute(
            delete(UserGroup__ConnectorCredentialPair).where(
                UserGroup__ConnectorCredentialPair.user_group_id == manage_group.id
            )
        )
        db_session.commit()
        for pair in (public_pair, private_pair, sync_pair, deleting_pair):
            cleanup_cc_pair(db_session, pair)
        delete_test_user(db_session, owner, member, manager, outsider, external_user)
        db_session.execute(
            delete(UserGroup).where(UserGroup.id.in_([group.id, manage_group.id]))
        )
        db_session.commit()


def _mine(world: _World, cc_pair_ids: set[int]) -> set[int]:
    return cc_pair_ids & {
        world.public_pair.id,
        world.private_pair.id,
        world.sync_pair.id,
        world.deleting_pair.id,
    }


@pytest.mark.usefixtures("ee")
def test_access_sets_ee(db_session: Session, world: _World) -> None:
    def sets(user: User) -> tuple[set[int], set[int]]:
        access_sets = get_cc_pair_access_sets_for_user(db_session, user)
        return (
            _mine(world, access_sets.open_cc_pair_ids),
            _mine(world, access_sets.acl_cc_pair_ids),
        )

    sync_only = {world.sync_pair.id}
    public = world.public_pair.id
    private = world.private_pair.id
    # DELETING pairs are in neither set, even for a member of their group.
    assert sets(world.member) == ({public, private}, sync_only)
    assert sets(world.owner) == ({public, private}, sync_only)
    assert sets(world.manager) == ({public}, sync_only)
    assert sets(world.outsider) == ({public}, sync_only)
    assert sets(world.anonymous) == ({public}, sync_only)

    # The Postgres filter is the same rule, without the DELETING exclusion.
    stmt = select(ConnectorCredentialPair.id).where(
        build_user_cc_pair_access_filter(world.member.id)
    )
    assert _mine(world, set(db_session.scalars(stmt))) == {
        public,
        private,
        world.deleting_pair.id,
    }


@pytest.mark.usefixtures("ce")
def test_access_sets_ce_ignore_groups(db_session: Session, world: _World) -> None:
    member_sets = get_cc_pair_access_sets_for_user(db_session, world.member)
    owner_sets = get_cc_pair_access_sets_for_user(db_session, world.owner)
    assert _mine(world, member_sets.open_cc_pair_ids) == {world.public_pair.id}
    assert _mine(world, owner_sets.open_cc_pair_ids) == {
        world.public_pair.id,
        world.private_pair.id,
    }


@pytest.mark.usefixtures("ee")
def test_chat_file_check_follows_cc_pair_rule(
    db_session: Session, world: _World
) -> None:
    doc_id = f"acc-chat-file-{uuid4().hex[:8]}"
    file_id = f"file-{doc_id}"
    _add_document(db_session, [world.private_pair], doc_id, is_public=True)
    doc = db_session.get(DbDocument, doc_id)
    assert doc is not None
    doc.file_id = file_id
    db_session.commit()

    def can_access(user: User, mode: CCPairAccessMode | None) -> bool:
        with patch("onyx.access.access.get_cc_pair_access_mode", return_value=mode):
            return user_can_access_chat_file(file_id, user, db_session)

    # Public in the source, but the private pair limits it to its groups.
    assert can_access(world.outsider, None)
    assert not can_access(world.outsider, CCPairAccessMode.ENFORCE)
    assert can_access(world.member, CCPairAccessMode.ENFORCE)
    assert can_access(world.owner, CCPairAccessMode.ENFORCE)


# --- OpenSearch filter ------------------------------------------------------


class _Docs(BaseModel):
    private_and_sync: str  # external ACL names external_user
    private_public_in_source: str
    sync_public_in_source: str
    public_and_sync: str
    deleting_only: str
    user_file: str  # no cc-pair, owned by owner


def _write_chunk(
    db_session: Session, index: OpenSearchDocumentIndex, doc_id: str
) -> None:
    """Writes the chunk with the access and cc_pair_ids indexing computes."""
    access = get_access_for_documents([doc_id], db_session)[doc_id]
    cc_pair_ids = get_cc_pair_ids_for_documents(db_session, [doc_id]).get(doc_id)
    chunk = make_chunk(doc_id).model_copy(
        update={"access": access, "cc_pair_ids": cc_pair_ids}
    )
    index.index(
        chunks=[chunk], indexing_metadata=make_indexing_metadata([doc_id], [0], [1])
    )


def _add_document(
    db_session: Session,
    pairs: list[ConnectorCredentialPair],
    doc_id: str,
    is_public: bool = False,
    external_user_emails: list[str] | None = None,
) -> None:
    db_session.add(
        DbDocument(
            id=doc_id,
            semantic_id=doc_id,
            chunk_count=1,
            is_public=is_public,
            external_user_emails=external_user_emails,
        )
    )
    db_session.commit()
    for pair in pairs:
        upsert_document_by_connector_credential_pair(
            db_session, pair.connector_id, pair.credential_id, [doc_id]
        )


@pytest.fixture
def docs(
    db_session: Session,
    world: _World,
    opensearch_index: OpenSearchDocumentIndex,
    test_index_name: str,
) -> Generator[_Docs, None, None]:
    suffix = uuid4().hex[:8]
    doc_ids = _Docs(
        private_and_sync=f"acc-private-sync-{suffix}",
        private_public_in_source=f"acc-private-public-{suffix}",
        sync_public_in_source=f"acc-sync-public-{suffix}",
        public_and_sync=f"acc-public-sync-{suffix}",
        deleting_only=f"acc-deleting-{suffix}",
        user_file=f"acc-user-file-{suffix}",
    )
    _add_document(
        db_session,
        [world.private_pair, world.sync_pair],
        doc_ids.private_and_sync,
        external_user_emails=[world.external_user.email],
    )
    _add_document(
        db_session,
        [world.private_pair],
        doc_ids.private_public_in_source,
        is_public=True,
    )
    _add_document(
        db_session, [world.sync_pair], doc_ids.sync_public_in_source, is_public=True
    )
    _add_document(
        db_session, [world.public_pair, world.sync_pair], doc_ids.public_and_sync
    )
    _add_document(db_session, [world.deleting_pair], doc_ids.deleting_only)
    for doc_id in doc_ids.model_dump().values():
        if doc_id != doc_ids.user_file:
            _write_chunk(db_session, opensearch_index, doc_id)

    user_file_chunk = make_chunk(doc_ids.user_file).model_copy(
        update={
            "access": DocumentAccess.build(
                user_emails=[world.owner.email],
                user_groups=[],
                external_user_emails=[],
                external_user_group_ids=[],
                is_public=False,
            )
        }
    )
    opensearch_index.index(
        chunks=[user_file_chunk],
        indexing_metadata=make_indexing_metadata([doc_ids.user_file], [0], [1]),
    )
    OpenSearchIndexClient(index_name=test_index_name).refresh_index()
    yield doc_ids
    for doc_id in doc_ids.model_dump().values():
        opensearch_index.delete(doc_id)


def _visible_docs(
    db_session: Session,
    index: OpenSearchDocumentIndex,
    user: User,
    mode: CCPairAccessMode | None,
    docs: _Docs,
) -> set[str]:
    return _visible_doc_ids(
        db_session, index, user, mode, set(docs.model_dump().values())
    )


def _visible_doc_ids(
    db_session: Session,
    index: OpenSearchDocumentIndex,
    user: User,
    mode: CCPairAccessMode | None,
    doc_ids: set[str],
) -> set[str]:
    with patch(f"{_ACCESS_FILTERS_MODULE}.get_cc_pair_access_mode", return_value=mode):
        access_filters = build_access_filters_for_user(user, db_session)
    chunks = index.keyword_retrieval(
        query="test content",
        filters=IndexFilters(
            access_control_list=access_filters.access_control_list,
            cc_pair_access=access_filters.cc_pair_access,
        ),
        num_to_retrieve=100,
    )
    return {chunk.document_id for chunk in chunks} & doc_ids


@pytest.mark.usefixtures("ee")
def test_cc_pair_filter_visibility(
    db_session: Session,
    world: _World,
    docs: _Docs,
    opensearch_index: OpenSearchDocumentIndex,
) -> None:
    everyone = {docs.sync_public_in_source, docs.public_and_sync}
    in_private_pair = {
        docs.private_and_sync,
        docs.private_public_in_source,
    }
    expected_new: list[tuple[User, set[str]]] = [
        (world.member, everyone | in_private_pair),
        (world.owner, everyone | in_private_pair | {docs.user_file}),
        # The old filter too: group: entries come from data-access groups.
        (world.manager, everyone),
        (world.outsider, everyone),
        (world.external_user, everyone | {docs.private_and_sync}),
        (world.anonymous, everyone),
    ]
    for user, expected in expected_new:
        assert (
            _visible_docs(
                db_session, opensearch_index, user, CCPairAccessMode.ENFORCE, docs
            )
            == expected
        ), user.email
        # The old filter also shows a public-in-source doc of a private pair
        # to everyone. That is the one intended difference.
        assert _visible_docs(db_session, opensearch_index, user, None, docs) == (
            expected | {docs.private_public_in_source}
        ), user.email


@pytest.mark.usefixtures("ee")
def test_shadow_mode_keeps_old_results_and_logs_disagreement(
    db_session: Session,
    world: _World,
    docs: _Docs,
    opensearch_index: OpenSearchDocumentIndex,
) -> None:
    expected_chunk_id = get_opensearch_doc_chunk_id(
        tenant_state=TenantState(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
        ),
        document_id=docs.private_public_in_source,
        chunk_index=0,
    )
    # Run the background comparison inline so the test can read its log.
    with (
        patch.object(
            opensearch_document_index,
            "_submit_cc_pair_access_shadow_check",
            lambda check: check(),
        ),
        patch.object(opensearch_document_index.logger, "warning") as warning,
    ):
        visible = _visible_docs(
            db_session,
            opensearch_index,
            world.outsider,
            CCPairAccessMode.SHADOW,
            docs,
        )
        assert docs.private_public_in_source in visible
        assert [call.args[-1] for call in warning.call_args_list] == [
            [expected_chunk_id]
        ]

        # ID-based retrieval compares only the requested documents.
        warning.reset_mock()
        with patch(
            f"{_ACCESS_FILTERS_MODULE}.get_cc_pair_access_mode",
            return_value=CCPairAccessMode.SHADOW,
        ):
            access_filters = build_access_filters_for_user(world.outsider, db_session)
        id_filters = IndexFilters(
            access_control_list=access_filters.access_control_list,
            cc_pair_access=access_filters.cc_pair_access,
        )
        for document_id, expected_logs in (
            (docs.sync_public_in_source, []),
            (docs.private_public_in_source, [[expected_chunk_id]]),
        ):
            warning.reset_mock()
            opensearch_index.id_based_retrieval(
                chunk_requests=[DocumentSectionRequest(document_id=document_id)],
                filters=id_filters,
            )
            assert [
                call.args[-1] for call in warning.call_args_list
            ] == expected_logs, document_id


@pytest.mark.usefixtures("ee")
def test_public_pair_made_private_hides_doc_after_metadata_sync(
    db_session: Session,
    world: _World,
    docs: _Docs,
    opensearch_index: OpenSearchDocumentIndex,
    test_index_name: str,
) -> None:
    world.public_pair.access_type = AccessType.PRIVATE
    db_session.commit()

    with patch(
        "onyx.background.celery.tasks.vespa.tasks.get_default_document_index",
        return_value=opensearch_index,
    ):
        result = document_index_metadata_sync_task.apply(
            args=(docs.public_and_sync,),
            kwargs={"tenant_id": POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE},
        )
        assert result.successful(), result.traceback
    OpenSearchIndexClient(index_name=test_index_name).refresh_index()

    visible = _visible_docs(
        db_session, opensearch_index, world.outsider, CCPairAccessMode.ENFORCE, docs
    )
    assert docs.public_and_sync not in visible


@pytest.mark.usefixtures("ee")
def test_data_access_change_applies_to_new_filter_at_once_and_old_after_sync(
    db_session: Session,
    world: _World,
    docs: _Docs,
    opensearch_index: OpenSearchDocumentIndex,
    test_index_name: str,
) -> None:
    doc_id = docs.private_and_sync
    doc = db_session.get(DbDocument, doc_id)
    assert doc is not None
    last_modified_before = doc.last_modified

    set_cc_pair_data_access_groups__no_commit(
        db_session,
        cc_pair_id=world.private_pair.id,
        requested_group_ids={world.group.id, world.manage_group.id},
        visible_group_ids=None,
    )
    db_session.commit()
    db_session.refresh(doc)
    assert doc.last_modified != last_modified_before

    def manager_sees(mode: CCPairAccessMode | None) -> bool:
        return doc_id in _visible_docs(
            db_session, opensearch_index, world.manager, mode, docs
        )

    assert manager_sees(CCPairAccessMode.ENFORCE)
    # The old filter reads the chunk's group: entries, which metadata sync writes.
    assert not manager_sees(None)
    with patch(
        "onyx.background.celery.tasks.vespa.tasks.get_default_document_index",
        return_value=opensearch_index,
    ):
        result = document_index_metadata_sync_task.apply(
            args=(doc_id,),
            kwargs={"tenant_id": POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE},
        )
        assert result.successful(), result.traceback
    OpenSearchIndexClient(index_name=test_index_name).refresh_index()
    assert manager_sees(None)


@pytest.mark.usefixtures("ee")
def test_group_deletion_drops_data_access_and_marks_documents(
    db_session: Session, world: _World, docs: _Docs
) -> None:
    doc = db_session.get(DbDocument, docs.private_and_sync)
    assert doc is not None
    last_modified_before = doc.last_modified
    world.group.is_up_to_date = True
    db_session.commit()

    prepare_user_group_for_deletion(db_session, world.group.id)

    # Gone before the group row, so metadata sync drops the group: entry.
    assert (
        fetch_data_access_cc_pair_ids_for_user_group(db_session, world.group.id)
        == set()
    )
    db_session.refresh(doc)
    assert doc.last_modified != last_modified_before


# --- Enforce gate -----------------------------------------------------------


@pytest.mark.usefixtures("kv_progress_restored", "tenant_context")
def test_enforce_gate_waits_for_pending_cc_pairs(db_session: Session) -> None:
    search_settings = get_current_search_settings(db_session)

    def _mode(pending: list[int] | None, enforce: bool) -> CCPairAccessMode | None:
        cc_pair_ids_backfill.store_cc_pair_ids_backfill_progress(
            cc_pair_ids_backfill.CCPairIdsBackfillProgress(
                search_settings_id=search_settings.id,
                index_name=search_settings.index_name,
                pending_cc_pair_ids=pending,
            )
        )
        with (
            patch.object(
                OnyxRuntime, "get_cc_pair_access_filter_enabled", return_value=True
            ),
            patch.object(
                OnyxRuntime, "get_cc_pair_access_filter_enforce", return_value=enforce
            ),
        ):
            return get_cc_pair_access_mode(db_session)

    # No snapshot yet, or cc-pairs still pending: shadow only.
    assert _mode(None, enforce=True) == CCPairAccessMode.SHADOW
    assert _mode([1, 2], enforce=True) == CCPairAccessMode.SHADOW
    # Every cc-pair done: the enforce flag decides, and can be turned back off.
    assert _mode([], enforce=True) == CCPairAccessMode.ENFORCE
    assert _mode([], enforce=False) == CCPairAccessMode.SHADOW


# --- SYNC_RESTRICTED --------------------------------------------------------


class _Restricted(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    acl_member: User  # in the data-access group and the source ACL
    member: User  # in the data-access group only
    acl_outsider: User  # in the source ACL only
    admin: User
    group: UserGroup
    pair: ConnectorCredentialPair
    groupless_pair: ConnectorCredentialPair
    doc_ids: dict[str, str]


@pytest.fixture
def restricted(
    db_session: Session,
    world: _World,
    opensearch_index: OpenSearchDocumentIndex,
    test_index_name: str,
) -> Generator[_Restricted, None, None]:
    acl_member = create_test_user(db_session, "cc_restricted_acl_member")
    member = create_test_user(db_session, "cc_restricted_member")
    acl_outsider = create_test_user(db_session, "cc_restricted_acl_outsider")
    admin = create_test_user(db_session, "cc_restricted_admin", is_admin=True)
    group = create_test_user_group(db_session, members=[acl_member, member])
    pair = _make_pair(db_session, AccessType.SYNC_RESTRICTED)
    groupless_pair = _make_pair(db_session, AccessType.SYNC_RESTRICTED)
    db_session.add(
        UserGroup__CCPairDataAccess(user_group_id=group.id, cc_pair_id=pair.id)
    )
    db_session.commit()

    suffix = uuid4().hex[:8]
    doc_ids = {
        name: f"acc-restricted-{name}-{suffix}"
        for name in ("acl", "public", "groupless", "with_sync", "with_private")
    }
    _add_document(
        db_session,
        [pair],
        doc_ids["acl"],
        external_user_emails=[acl_member.email, acl_outsider.email],
    )
    _add_document(db_session, [pair], doc_ids["public"], is_public=True)
    _add_document(
        db_session,
        [groupless_pair],
        doc_ids["groupless"],
        is_public=True,
        external_user_emails=[acl_member.email],
    )
    _add_document(
        db_session,
        [pair, world.sync_pair],
        doc_ids["with_sync"],
        external_user_emails=[acl_outsider.email],
    )
    _add_document(
        db_session,
        [pair, world.private_pair],
        doc_ids["with_private"],
        external_user_emails=[acl_outsider.email],
    )
    for doc_id in doc_ids.values():
        _write_chunk(db_session, opensearch_index, doc_id)
    OpenSearchIndexClient(index_name=test_index_name).refresh_index()

    try:
        yield _Restricted(
            acl_member=acl_member,
            member=member,
            acl_outsider=acl_outsider,
            admin=admin,
            group=group,
            pair=pair,
            groupless_pair=groupless_pair,
            doc_ids=doc_ids,
        )
    finally:
        db_session.rollback()
        for doc_id in doc_ids.values():
            opensearch_index.delete(doc_id)
        for restricted_pair in (pair, groupless_pair):
            cleanup_cc_pair(db_session, restricted_pair)
        delete_test_user(db_session, acl_member, member, acl_outsider, admin)
        db_session.execute(delete(UserGroup).where(UserGroup.id == group.id))
        db_session.commit()


@pytest.mark.usefixtures("ee")
def test_restricted_pair_needs_data_access_group_and_acl_match(
    db_session: Session,
    world: _World,
    restricted: _Restricted,
    opensearch_index: OpenSearchDocumentIndex,
) -> None:
    doc_ids = restricted.doc_ids
    # A pair grants only "data-access group AND (public OR ACL match)"; a pair
    # with no group grants nobody; a shared document gets the union of its pairs.
    expected: list[tuple[User, set[str]]] = [
        (restricted.acl_member, {doc_ids["acl"], doc_ids["public"]}),
        (restricted.member, {doc_ids["public"]}),
        (restricted.acl_outsider, {doc_ids["with_sync"]}),
        (world.member, {doc_ids["with_private"]}),
        (restricted.admin, set()),
        (world.outsider, set()),
        (world.anonymous, set()),
    ]
    for user, expected_doc_ids in expected:
        # The old ACL filter hides the pairs that grant the user nothing, so
        # it gives the same result while enforcement is off.
        for mode in (CCPairAccessMode.ENFORCE, None):
            visible = _visible_doc_ids(
                db_session, opensearch_index, user, mode, set(doc_ids.values())
            )
            assert visible == expected_doc_ids, (user.email, mode)

        if user.is_anonymous:
            continue
        # The Postgres form of the rule (assistant attach, tags, hierarchy).
        accessible = get_accessible_documents_by_ids(
            db_session,
            list(doc_ids.values()),
            user_email=user.email,
            external_group_ids=[],
            user_id=user.id,
        )
        assert {doc.id for doc in accessible} == expected_doc_ids, user.email


@pytest.mark.usefixtures("ee")
def test_restricted_pair_access_sets_and_chat_file(
    db_session: Session, restricted: _Restricted
) -> None:
    member_sets = get_cc_pair_access_sets_for_user(db_session, restricted.member)
    assert restricted.pair.id in member_sets.acl_cc_pair_ids
    assert restricted.groupless_pair.id in member_sets.hidden_restricted_cc_pair_ids
    admin_sets = get_cc_pair_access_sets_for_user(db_session, restricted.admin)
    assert {restricted.pair.id, restricted.groupless_pair.id} <= (
        admin_sets.hidden_restricted_cc_pair_ids
    )

    file_id = f"file-{restricted.doc_ids['acl']}"
    doc = db_session.get(DbDocument, restricted.doc_ids["acl"])
    assert doc is not None
    doc.file_id = file_id
    db_session.commit()
    for mode in (None, CCPairAccessMode.ENFORCE):
        with patch("onyx.access.access.get_cc_pair_access_mode", return_value=mode):
            assert user_can_access_chat_file(file_id, restricted.acl_member, db_session)
            assert not user_can_access_chat_file(
                file_id, restricted.acl_outsider, db_session
            )


@pytest.mark.usefixtures("ce")
def test_restricted_pair_grants_nothing_in_ce(
    db_session: Session, restricted: _Restricted
) -> None:
    access_sets = get_cc_pair_access_sets_for_user(db_session, restricted.acl_member)
    assert restricted.pair.id not in access_sets.acl_cc_pair_ids
    assert restricted.pair.id in access_sets.hidden_restricted_cc_pair_ids


@pytest.mark.usefixtures("ee")
def test_deleting_restricted_pair_stays_on_chunks(
    db_session: Session, restricted: _Restricted
) -> None:
    restricted.pair.status = ConnectorCredentialPairStatus.DELETING
    db_session.commit()
    doc_id = restricted.doc_ids["acl"]
    # Without the pair id, a rewritten chunk would fall back to the old ACL filter.
    assert get_cc_pair_ids_for_documents(db_session, [doc_id]) == {
        doc_id: [restricted.pair.id]
    }
    access_sets = get_cc_pair_access_sets_for_user(db_session, restricted.acl_member)
    assert restricted.pair.id in access_sets.hidden_restricted_cc_pair_ids


# --- Awaiting first permission sync ------------------------------------------


class _Pending(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    pair: ConnectorCredentialPair  # moved from PUBLIC to SYNC
    only_doc_id: str  # public in the source, in the pair only
    with_public_doc_id: str  # also in the world's PUBLIC pair


@pytest.fixture
def pending(
    db_session: Session,
    world: _World,
    opensearch_index: OpenSearchDocumentIndex,
    test_index_name: str,
    ee: None,  # noqa: ARG001
) -> Generator[_Pending, None, None]:
    pair = _make_pair(db_session, AccessType.PUBLIC)
    suffix = uuid4().hex[:8]
    only_doc_id = f"acc-pending-only-{suffix}"
    with_public_doc_id = f"acc-pending-with-public-{suffix}"
    _add_document(db_session, [pair], only_doc_id, is_public=True)
    _add_document(db_session, [pair, world.public_pair], with_public_doc_id)
    # Written while the pair is PUBLIC, so both chunks have public=true.
    for doc_id in (only_doc_id, with_public_doc_id):
        _write_chunk(db_session, opensearch_index, doc_id)
    OpenSearchIndexClient(index_name=test_index_name).refresh_index()

    apply_access_change__no_commit(
        db_session,
        pair.id,
        AccessType.SYNC,
        data_access_group_ids=set(),
        visible_group_ids=None,
    )
    db_session.commit()
    db_session.refresh(pair)
    assert pair.perm_sync_pending_since is not None
    try:
        yield _Pending(
            pair=pair, only_doc_id=only_doc_id, with_public_doc_id=with_public_doc_id
        )
    finally:
        db_session.rollback()
        for doc_id in (only_doc_id, with_public_doc_id):
            opensearch_index.delete(doc_id)
        cleanup_cc_pair(db_session, pair)


@pytest.mark.parametrize("is_ee", [True, False])
def test_pending_pair_grants_nothing(
    db_session: Session,
    world: _World,
    pending: _Pending,
    monkeypatch: pytest.MonkeyPatch,
    is_ee: bool,
) -> None:
    _set_ee(monkeypatch, is_ee)
    assert has_guarded_cc_pairs(db_session)
    for user in (world.member, world.outsider, world.external_user, world.anonymous):
        access_sets = get_cc_pair_access_sets_for_user(db_session, user)
        assert pending.pair.id not in access_sets.open_cc_pair_ids, user.email
        assert pending.pair.id not in access_sets.acl_cc_pair_ids, user.email
        assert pending.pair.id in access_sets.hidden_restricted_cc_pair_ids, user.email


def test_pending_pair_hides_stale_public_chunks_in_every_mode(
    db_session: Session,
    world: _World,
    pending: _Pending,
    opensearch_index: OpenSearchDocumentIndex,
) -> None:
    doc_ids = {pending.only_doc_id, pending.with_public_doc_id}

    def visible(user: User, mode: CCPairAccessMode | None) -> set[str]:
        return _visible_doc_ids(db_session, opensearch_index, user, mode, doc_ids)

    def visible_in_postgres(user: User) -> set[str]:
        accessible = get_accessible_documents_by_ids(
            db_session,
            list(doc_ids),
            user_email=user.email,
            external_group_ids=[],
            user_id=user.id,
        )
        return {doc.id for doc in accessible}

    # The chunk keeps public=true until metadata sync, but the pair grants
    # nothing. A granting pair of a shared document still grants.
    for mode in (CCPairAccessMode.ENFORCE, CCPairAccessMode.SHADOW, None):
        for user in (world.outsider, world.anonymous):
            assert visible(user, mode) == {pending.with_public_doc_id}, (
                user.email,
                mode,
            )
    assert visible_in_postgres(world.outsider) == {pending.with_public_doc_id}

    # The mark alone hides it: the same stale chunk shows once it is cleared.
    pending.pair.perm_sync_pending_since = None
    db_session.commit()
    for mode in (CCPairAccessMode.ENFORCE, CCPairAccessMode.SHADOW, None):
        assert visible(world.outsider, mode) == doc_ids, mode
    assert visible_in_postgres(world.outsider) == doc_ids
