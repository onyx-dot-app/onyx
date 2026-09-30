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
)
from onyx.db.document import (
    get_cc_pair_ids_for_documents,
    upsert_document_by_connector_credential_pair,
)
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    ConnectorCredentialPair,
    User,
    UserGroup,
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
    member: User  # in the private pair's group
    outsider: User
    external_user: User  # named in a synced document's external ACL
    anonymous: User
    group: UserGroup
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
    outsider = create_test_user(db_session, "cc_access_outsider")
    external_user = create_test_user(db_session, "cc_access_external")
    group = create_test_user_group(db_session, members=[member])

    public_pair = _make_pair(db_session, AccessType.PUBLIC)
    private_pair = _make_pair(db_session, AccessType.PRIVATE)
    private_pair.credential.user_id = owner.id
    sync_pair = _make_pair(db_session, AccessType.SYNC)
    deleting_pair = _make_pair(
        db_session, AccessType.PRIVATE, ConnectorCredentialPairStatus.DELETING
    )
    for pair in (private_pair, deleting_pair):
        db_session.add(
            UserGroup__ConnectorCredentialPair(
                user_group_id=group.id, cc_pair_id=pair.id, is_current=True
            )
        )
    db_session.commit()

    try:
        yield _World(
            owner=owner,
            member=member,
            outsider=outsider,
            external_user=external_user,
            anonymous=User(id=UUID(ANONYMOUS_USER_UUID), email=ANONYMOUS_USER_EMAIL),
            group=group,
            public_pair=public_pair,
            private_pair=private_pair,
            sync_pair=sync_pair,
            deleting_pair=deleting_pair,
        )
    finally:
        db_session.rollback()
        db_session.execute(
            delete(UserGroup__ConnectorCredentialPair).where(
                UserGroup__ConnectorCredentialPair.user_group_id == group.id
            )
        )
        db_session.commit()
        for pair in (public_pair, private_pair, sync_pair, deleting_pair):
            cleanup_cc_pair(db_session, pair)
        delete_test_user(db_session, owner, member, outsider, external_user)
        db_session.execute(delete(UserGroup).where(UserGroup.id == group.id))
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
    return {chunk.document_id for chunk in chunks} & set(docs.model_dump().values())


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
