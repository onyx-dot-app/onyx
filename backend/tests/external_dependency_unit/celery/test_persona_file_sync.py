"""
External dependency unit tests for persona file sync.

Validates that:

1. The check_for_user_file_project_sync beat task picks up UserFiles with
   needs_persona_sync=True (not just needs_project_sync).

2. The process_single_user_file_project_sync worker task reads persona
   associations from the DB, passes persona_ids to the document index via
   VespaDocumentUserFields, and clears needs_persona_sync afterwards.

3. upsert_persona correctly marks affected UserFiles with
   needs_persona_sync=True when file associations change.

Uses real Redis and PostgreSQL.  Document index (Vespa) calls are mocked
since we only need to verify the arguments passed to update_single.
"""

from collections.abc import Generator
from contextlib import contextmanager
from contextlib import ExitStack
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from unittest.mock import PropertyMock
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.access.models import DocumentAccess
from onyx.background.celery.tasks.user_file_processing.tasks import (
    _process_user_file_with_indexing,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    _supply_user_file_to_secondary,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    check_for_user_file_project_sync,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    process_single_user_file_project_sync,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    user_file_project_sync_lock_key,
)
from onyx.db.enums import UserFileStatus
from onyx.db.models import Persona
from onyx.db.models import Persona__UserFile
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.persona import upsert_persona
from onyx.document_index.interfaces_new import MetadataUpdateRequest
from onyx.document_index.interfaces_new import SecondaryIndexDocumentMissingError
from onyx.indexing.adapters.user_file_indexing_adapter import UserFileChunkEnricher
from onyx.indexing.adapters.user_file_indexing_adapter import UserFileIndexingAdapter
from onyx.indexing.indexing_pipeline import IndexingPipelineResult
from onyx.redis.redis_pool import get_redis_client
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import make_doc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_completed_user_file(
    db_session: Session,
    user: User,
    needs_persona_sync: bool = False,
    needs_project_sync: bool = False,
) -> UserFile:
    """Insert a UserFile in COMPLETED status."""
    uf = UserFile(
        id=uuid4(),
        user_id=user.id,
        file_id=f"test_file_{uuid4().hex[:8]}",
        name=f"test_{uuid4().hex[:8]}.txt",
        file_type="text/plain",
        status=UserFileStatus.COMPLETED,
        needs_persona_sync=needs_persona_sync,
        needs_project_sync=needs_project_sync,
        chunk_count=5,
    )
    db_session.add(uf)
    db_session.commit()
    db_session.refresh(uf)
    return uf


def _create_test_persona(
    db_session: Session,
    user: User,
    user_files: list[UserFile] | None = None,
) -> Persona:
    """Create a minimal Persona via direct model insert."""
    persona = Persona(
        name=f"Test Persona {uuid4().hex[:8]}",
        description="Test persona",
        system_prompt="You are a test assistant",
        task_prompt="Answer the question",
        tools=[],
        document_sets=[],
        users=[user],
        groups=[],
        is_listed=True,
        is_public=True,
        display_priority=None,
        starter_messages=None,
        deleted=False,
        user_files=user_files or [],
        user_id=user.id,
    )
    db_session.add(persona)
    db_session.commit()
    db_session.refresh(persona)
    return persona


def _link_file_to_persona(
    db_session: Session, persona: Persona, user_file: UserFile
) -> None:
    """Create the join table row between a persona and a user file."""
    link = Persona__UserFile(persona_id=persona.id, user_file_id=user_file.id)
    db_session.add(link)
    db_session.commit()


_PATCH_QUEUE_DEPTH = "onyx.background.celery.tasks.user_file_processing.tasks.get_user_file_project_sync_queue_depth"


@contextmanager
def _patch_task_app(task: Any, mock_app: MagicMock) -> Generator[None, None, None]:
    """Patch the ``app`` property on a bound Celery task."""
    task_instance = task.run.__self__
    with (
        patch.object(
            type(task_instance),
            "app",
            new_callable=PropertyMock,
            return_value=mock_app,
        ),
        patch(_PATCH_QUEUE_DEPTH, return_value=0),
        patch(
            "onyx.background.celery.tasks.user_file_processing.tasks.celery_get_broker_client",
            return_value=MagicMock(),
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# Test: check_for_user_file_project_sync picks up persona sync
# ---------------------------------------------------------------------------


class TestCheckSweepIncludesPersonaSync:
    """The beat task must pick up files needing persona sync, not just project sync."""

    def test_persona_sync_flag_enqueues_task(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """A file with needs_persona_sync=True (and COMPLETED) gets enqueued."""
        user = create_test_user(db_session, "persona_sweep")
        uf = _create_completed_user_file(db_session, user, needs_persona_sync=True)

        mock_app = MagicMock()

        with _patch_task_app(check_for_user_file_project_sync, mock_app):
            check_for_user_file_project_sync.run(
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
            )

        enqueued_ids = {
            call.kwargs["kwargs"]["user_file_id"]
            for call in mock_app.send_task.call_args_list
        }
        assert str(uf.id) in enqueued_ids

    def test_neither_flag_does_not_enqueue(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """A file with both flags False is not enqueued."""
        user = create_test_user(db_session, "no_sync")
        uf = _create_completed_user_file(db_session, user)

        mock_app = MagicMock()

        with _patch_task_app(check_for_user_file_project_sync, mock_app):
            check_for_user_file_project_sync.run(
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
            )

        enqueued_ids = {
            call.kwargs["kwargs"]["user_file_id"]
            for call in mock_app.send_task.call_args_list
        }
        assert str(uf.id) not in enqueued_ids

    def test_both_flags_enqueues_once(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """A file with BOTH flags True is enqueued exactly once."""
        user = create_test_user(db_session, "both_flags")
        uf = _create_completed_user_file(
            db_session, user, needs_persona_sync=True, needs_project_sync=True
        )

        mock_app = MagicMock()

        with _patch_task_app(check_for_user_file_project_sync, mock_app):
            check_for_user_file_project_sync.run(
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
            )

        matching_calls = [
            call
            for call in mock_app.send_task.call_args_list
            if call.kwargs["kwargs"]["user_file_id"] == str(uf.id)
        ]
        assert len(matching_calls) == 1

    def test_secondary_pending_flag_reenqueues_when_needs_sync_cleared(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """C1: a deferred file (needs_*_sync already cleared) is still re-enqueued so the
        drain can retry the FUTURE update — else the flag stays stuck and blocks the swap."""
        user = create_test_user(db_session, "secpend_sweep")
        uf = _create_completed_user_file(db_session, user)
        uf.secondary_reconcile_pending = True
        db_session.commit()

        mock_app = MagicMock()

        with _patch_task_app(check_for_user_file_project_sync, mock_app):
            check_for_user_file_project_sync.run(
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
            )

        enqueued_ids = {
            call.kwargs["kwargs"]["user_file_id"]
            for call in mock_app.send_task.call_args_list
        }
        assert str(uf.id) in enqueued_ids


# ---------------------------------------------------------------------------
# Test: process_single_user_file_project_sync passes persona_ids to index
# ---------------------------------------------------------------------------

_PATCH_GET_SETTINGS = (
    "onyx.background.celery.tasks.user_file_processing.tasks.get_active_search_settings"
)
_PATCH_GET_INDICES = (
    "onyx.background.celery.tasks.user_file_processing.tasks.get_all_document_indices"
)
_PATCH_HTTPX_INIT = (
    "onyx.background.celery.tasks.user_file_processing.tasks.httpx_init_vespa_pool"
)
_PATCH_DISABLE_VDB = (
    "onyx.background.celery.tasks.user_file_processing.tasks.DISABLE_VECTOR_DB"
)
_PATCH_ACTIVE_SECONDARY = "onyx.background.celery.tasks.user_file_processing.tasks.active_secondary_port_target"
_PATCH_SUPPLY = "onyx.background.celery.tasks.user_file_processing.tasks._supply_user_file_to_secondary"
_PATCH_INDEX_SECONDARY = "onyx.background.celery.tasks.user_file_processing.tasks._index_user_file_to_secondary"
_PATCH_LOAD_DOCS = (
    "onyx.background.celery.tasks.user_file_processing.tasks._load_user_file_documents"
)
_PATCH_GET_SETTINGS_LIST = "onyx.background.celery.tasks.user_file_processing.tasks.get_active_search_settings_list"
_PATCH_EMBEDDER = (
    "onyx.background.celery.tasks.user_file_processing.tasks.DefaultIndexingEmbedder"
)
_PATCH_RUN_PIPELINE = (
    "onyx.background.celery.tasks.user_file_processing.tasks.run_indexing_pipeline"
)


def _purge_user_files(db_session: Session, user: User) -> None:
    """Drop a test's COMPLETED user files so they don't pollute the tenant-global
    port-scope helpers other suites read."""
    db_session.rollback()
    db_session.query(UserFile).filter(UserFile.user_id == user.id).delete(
        synchronize_session="fetch"
    )
    db_session.commit()


class TestSyncTaskWritesPersonaIds:
    """The sync task reads persona associations and sends them to the index."""

    def test_passes_persona_ids_to_update_single(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """After linking a file to a persona, sync sends the persona ID."""
        user = create_test_user(db_session, "sync_persona")
        uf = _create_completed_user_file(db_session, user, needs_persona_sync=True)
        persona = _create_test_persona(db_session, user)
        _link_file_to_persona(db_session, persona, uf)

        mock_doc_index = MagicMock()
        mock_search_settings = MagicMock()
        mock_search_settings.primary = MagicMock()
        mock_search_settings.primary.port_backfill_source_id = None
        mock_search_settings.secondary = None

        redis_client = get_redis_client(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        )
        lock_key = user_file_project_sync_lock_key(str(uf.id))
        redis_client.delete(lock_key)

        with (
            patch(_PATCH_DISABLE_VDB, False),
            patch(_PATCH_HTTPX_INIT),
            patch(_PATCH_GET_SETTINGS, return_value=mock_search_settings),
            patch(_PATCH_GET_INDICES, return_value=[mock_doc_index]),
        ):
            process_single_user_file_project_sync.run(
                user_file_id=str(uf.id),
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            )

        mock_doc_index.update.assert_called_once()
        call_args = mock_doc_index.update.call_args
        update_requests: list[MetadataUpdateRequest] = call_args.args[0]
        assert len(update_requests) == 1
        update_request = update_requests[0]
        assert update_request.document_ids == [str(uf.id)]
        assert update_request.persona_ids is not None
        assert persona.id in update_request.persona_ids

    def test_clears_persona_sync_flag(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """After a successful sync the needs_persona_sync flag is cleared."""
        user = create_test_user(db_session, "sync_clear")
        uf = _create_completed_user_file(db_session, user, needs_persona_sync=True)

        redis_client = get_redis_client(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        )
        lock_key = user_file_project_sync_lock_key(str(uf.id))
        redis_client.delete(lock_key)

        with patch(_PATCH_DISABLE_VDB, True):
            process_single_user_file_project_sync.run(
                user_file_id=str(uf.id),
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            )

        db_session.refresh(uf)
        assert uf.needs_persona_sync is False

    def test_passes_both_project_and_persona_ids(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """A file linked to both a project and a persona gets both IDs."""
        from onyx.db.models import Project__UserFile
        from onyx.db.models import UserProject

        user = create_test_user(db_session, "sync_both")
        uf = _create_completed_user_file(
            db_session, user, needs_persona_sync=True, needs_project_sync=True
        )
        persona = _create_test_persona(db_session, user)
        _link_file_to_persona(db_session, persona, uf)

        project = UserProject(user_id=user.id, name="test-project", instructions="")
        db_session.add(project)
        db_session.commit()
        db_session.refresh(project)

        link = Project__UserFile(project_id=project.id, user_file_id=uf.id)
        db_session.add(link)
        db_session.commit()

        mock_doc_index = MagicMock()
        mock_search_settings = MagicMock()
        mock_search_settings.primary = MagicMock()
        mock_search_settings.primary.port_backfill_source_id = None
        mock_search_settings.secondary = None

        redis_client = get_redis_client(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        )
        lock_key = user_file_project_sync_lock_key(str(uf.id))
        redis_client.delete(lock_key)

        with (
            patch(_PATCH_DISABLE_VDB, False),
            patch(_PATCH_HTTPX_INIT),
            patch(_PATCH_GET_SETTINGS, return_value=mock_search_settings),
            patch(_PATCH_GET_INDICES, return_value=[mock_doc_index]),
        ):
            process_single_user_file_project_sync.run(
                user_file_id=str(uf.id),
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            )

        update_requests: list[MetadataUpdateRequest] = (
            mock_doc_index.update.call_args.args[0]
        )
        assert len(update_requests) == 1
        update_request = update_requests[0]
        assert update_request.persona_ids is not None
        assert update_request.project_ids is not None
        assert persona.id in update_request.persona_ids
        assert project.id in update_request.project_ids

        # Both flags should be cleared
        db_session.refresh(uf)
        assert uf.needs_persona_sync is False
        assert uf.needs_project_sync is False

    def test_deleted_persona_excluded_from_ids(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """A soft-deleted persona should NOT appear in the persona_ids sent to Vespa."""
        user = create_test_user(db_session, "sync_deleted")
        uf = _create_completed_user_file(db_session, user, needs_persona_sync=True)
        persona = _create_test_persona(db_session, user)
        _link_file_to_persona(db_session, persona, uf)

        persona.deleted = True
        db_session.commit()

        mock_doc_index = MagicMock()
        mock_search_settings = MagicMock()
        mock_search_settings.primary = MagicMock()
        mock_search_settings.primary.port_backfill_source_id = None
        mock_search_settings.secondary = None

        redis_client = get_redis_client(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        )
        lock_key = user_file_project_sync_lock_key(str(uf.id))
        redis_client.delete(lock_key)

        with (
            patch(_PATCH_DISABLE_VDB, False),
            patch(_PATCH_HTTPX_INIT),
            patch(_PATCH_GET_SETTINGS, return_value=mock_search_settings),
            patch(_PATCH_GET_INDICES, return_value=[mock_doc_index]),
        ):
            process_single_user_file_project_sync.run(
                user_file_id=str(uf.id),
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            )

        update_requests: list[MetadataUpdateRequest] = (
            mock_doc_index.update.call_args.args[0]
        )
        assert len(update_requests) == 1
        update_request = update_requests[0]
        assert update_request.persona_ids is not None
        assert persona.id not in update_request.persona_ids


# ---------------------------------------------------------------------------
# Test: upsert_persona marks files for persona sync
# ---------------------------------------------------------------------------


class TestUpsertPersonaMarksSyncFlag:
    """upsert_persona must set needs_persona_sync on affected UserFiles."""

    def test_creating_persona_with_files_marks_sync(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        user = create_test_user(db_session, "upsert_create")
        uf = _create_completed_user_file(db_session, user)
        assert uf.needs_persona_sync is False

        upsert_persona(
            user=user,
            name=f"persona-{uuid4().hex[:8]}",
            description="test",
            starter_messages=None,
            system_prompt="test",
            task_prompt="test",
            datetime_aware=None,
            is_public=True,
            db_session=db_session,
            user_file_ids=[uf.id],
        )

        db_session.refresh(uf)
        assert uf.needs_persona_sync is True

    def test_updating_persona_files_marks_both_old_and_new(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """When file associations change, both the removed and added files are flagged."""
        user = create_test_user(db_session, "upsert_update")
        uf_old = _create_completed_user_file(db_session, user)
        uf_new = _create_completed_user_file(db_session, user)

        persona = upsert_persona(
            user=user,
            name=f"persona-{uuid4().hex[:8]}",
            description="test",
            starter_messages=None,
            system_prompt="test",
            task_prompt="test",
            datetime_aware=None,
            is_public=True,
            db_session=db_session,
            user_file_ids=[uf_old.id],
        )

        # Clear the flag from creation so we can observe the update
        uf_old.needs_persona_sync = False
        db_session.commit()

        # Now update the persona to swap files
        upsert_persona(
            user=user,
            name=persona.name,
            description=persona.description,
            starter_messages=None,
            system_prompt=persona.system_prompt,
            task_prompt=persona.task_prompt,
            datetime_aware=None,
            is_public=persona.is_public,
            db_session=db_session,
            persona_id=persona.id,
            user_file_ids=[uf_new.id],
        )

        db_session.refresh(uf_old)
        db_session.refresh(uf_new)
        assert uf_old.needs_persona_sync is True, "Removed file should be flagged"
        assert uf_new.needs_persona_sync is True, "Added file should be flagged"

    def test_removing_all_files_marks_old_files(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Removing all files from a persona flags the previously associated files."""
        user = create_test_user(db_session, "upsert_remove")
        uf = _create_completed_user_file(db_session, user)

        persona = upsert_persona(
            user=user,
            name=f"persona-{uuid4().hex[:8]}",
            description="test",
            starter_messages=None,
            system_prompt="test",
            task_prompt="test",
            datetime_aware=None,
            is_public=True,
            db_session=db_session,
            user_file_ids=[uf.id],
        )

        uf.needs_persona_sync = False
        db_session.commit()

        upsert_persona(
            user=user,
            name=persona.name,
            description=persona.description,
            starter_messages=None,
            system_prompt=persona.system_prompt,
            task_prompt=persona.task_prompt,
            datetime_aware=None,
            is_public=persona.is_public,
            db_session=db_session,
            persona_id=persona.id,
            user_file_ids=[],
        )

        db_session.refresh(uf)
        assert uf.needs_persona_sync is True


# ---------------------------------------------------------------------------
# Test: GAP 2 — re-enabled secondary ACL sync defers on a missing FUTURE doc
# and drains once the port supplies it
# ---------------------------------------------------------------------------


def _run_sync(
    uf_id: str,
    mock_doc_index: MagicMock,
    secondary: Any,
    port_target: Any = None,
    supply: MagicMock | None = None,
) -> None:
    """Run the sync task with the index mocked. `active_secondary_port_target` is patched
    (default None) so the 404 fallback is deterministic; pass `supply` to stub the fallback."""
    mock_search_settings = MagicMock()
    mock_search_settings.primary = MagicMock()
    mock_search_settings.primary.port_backfill_source_id = None
    mock_search_settings.secondary = secondary

    redis_client = get_redis_client(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    redis_client.delete(user_file_project_sync_lock_key(uf_id))

    patches: list[Any] = [
        patch(_PATCH_DISABLE_VDB, False),
        patch(_PATCH_HTTPX_INIT),
        patch(_PATCH_GET_SETTINGS, return_value=mock_search_settings),
        patch(_PATCH_GET_INDICES, return_value=[mock_doc_index]),
        patch(_PATCH_ACTIVE_SECONDARY, return_value=port_target),
    ]
    if supply is not None:
        patches.append(patch(_PATCH_SUPPLY, supply))

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        process_single_user_file_project_sync.run(
            user_file_id=uf_id,
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        )


class TestSecondaryDeferAndDrain:
    """project_sync_user_file_impl defers a missing-FUTURE write and drains on retry."""

    def test_defer_on_secondary_missing_sets_flag(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """FUTURE lacks the not-yet-ported file: needs_*_sync clears but the file is
        flagged so a later scan retries the update."""
        user = create_test_user(db_session, "defer_set")
        uf = _create_completed_user_file(db_session, user, needs_project_sync=True)

        mock_doc_index = MagicMock()
        mock_doc_index.update.side_effect = SecondaryIndexDocumentMissingError(
            [str(uf.id)]
        )

        _run_sync(str(uf.id), mock_doc_index, secondary=MagicMock())

        db_session.refresh(uf)
        assert uf.secondary_reconcile_pending is True
        assert uf.needs_project_sync is False

    def test_drain_clears_flag_on_success(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Once the port has copied the file, the update succeeds and the flag clears."""
        user = create_test_user(db_session, "defer_drain")
        uf = _create_completed_user_file(db_session, user)
        uf.secondary_reconcile_pending = True
        db_session.commit()

        mock_doc_index = MagicMock()  # update() succeeds
        _run_sync(str(uf.id), mock_doc_index, secondary=MagicMock())

        db_session.refresh(uf)
        assert uf.secondary_reconcile_pending is False

    def test_no_secondary_drain_clears_flag(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Post-INSTANT-swap the secondary is None; the drain updates the promoted primary
        and clears the flag — else it stays stuck forever (no secondary to reach)."""
        user = create_test_user(db_session, "defer_nosec")
        uf = _create_completed_user_file(db_session, user)
        uf.secondary_reconcile_pending = True
        db_session.commit()

        mock_doc_index = MagicMock()
        _run_sync(str(uf.id), mock_doc_index, secondary=None)

        db_session.refresh(uf)
        assert uf.secondary_reconcile_pending is False

    def test_non_portable_file_not_flagged(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """A non-COMPLETED file that misses FUTURE is never ported, so it must not be
        flagged — its flag would never drain (mark it synced instead)."""
        user = create_test_user(db_session, "defer_nonportable")
        uf = _create_completed_user_file(db_session, user, needs_project_sync=True)
        uf.status = UserFileStatus.PROCESSING
        db_session.commit()

        mock_doc_index = MagicMock()
        mock_doc_index.update.side_effect = SecondaryIndexDocumentMissingError(
            [str(uf.id)]
        )

        _run_sync(str(uf.id), mock_doc_index, secondary=MagicMock())

        db_session.refresh(uf)
        assert uf.secondary_reconcile_pending is False

    def test_drain_dual_write_supplies_content_and_clears_flag(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """PR4 404 fallback: update() finds FUTURE missing the content, so the drain
        dual-writes it. A successful dual-write clears the flag now (no wait on the port)."""
        user = create_test_user(db_session, "drain_dw_ok")
        uf = _create_completed_user_file(db_session, user, needs_project_sync=True)
        try:
            mock_doc_index = MagicMock()
            mock_doc_index.update.side_effect = SecondaryIndexDocumentMissingError(
                [str(uf.id)]
            )
            supply = MagicMock(return_value=True)

            _run_sync(
                str(uf.id),
                mock_doc_index,
                secondary=MagicMock(),
                port_target=MagicMock(),
                supply=supply,
            )

            supply.assert_called_once_with(
                str(uf.id), POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
            )
            db_session.refresh(uf)
            assert uf.secondary_reconcile_pending is False
        finally:
            _purge_user_files(db_session, user)


class TestDualWriteFallbackHelper:
    """_supply_user_file_to_secondary: resolve target, supply content, isolate."""

    def test_no_target_returns_false_without_writing(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """No active port target (e.g. after an INSTANT swap) — the fallback is a no-op that
        keeps the flag; the file self-heals via the port instead."""
        user = create_test_user(db_session, "fb_notarget")
        uf = _create_completed_user_file(db_session, user)
        try:
            index_secondary = MagicMock()
            with (
                patch(_PATCH_ACTIVE_SECONDARY, return_value=None),
                patch(_PATCH_INDEX_SECONDARY, index_secondary),
            ):
                result = _supply_user_file_to_secondary(
                    str(uf.id), POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
                )
            assert result is False
            index_secondary.assert_not_called()
        finally:
            _purge_user_files(db_session, user)

    def test_supplies_content_returns_true(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """With a target and a loadable blob, the fallback re-indexes into FUTURE (threading
        the resolved target through) and reports success so the flag can clear."""
        user = create_test_user(db_session, "fb_ok")
        uf = _create_completed_user_file(db_session, user)
        try:
            target = MagicMock()
            index_secondary = MagicMock()
            with (
                patch(_PATCH_ACTIVE_SECONDARY, return_value=target),
                patch(_PATCH_LOAD_DOCS, return_value=([make_doc(str(uf.id))], [])),
                patch(_PATCH_INDEX_SECONDARY, index_secondary),
            ):
                result = _supply_user_file_to_secondary(
                    str(uf.id), POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
                )
            assert result is True
            index_secondary.assert_called_once()
            assert index_secondary.call_args.args[2] is target
        finally:
            _purge_user_files(db_session, user)

    def test_write_failure_is_isolated_returns_false(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """A FUTURE write failure never propagates into the sync task — it just returns False
        so the flag stays set for a retry."""
        user = create_test_user(db_session, "fb_fail")
        uf = _create_completed_user_file(db_session, user)
        try:
            with (
                patch(_PATCH_ACTIVE_SECONDARY, return_value=MagicMock()),
                patch(_PATCH_LOAD_DOCS, return_value=([make_doc(str(uf.id))], [])),
                patch(_PATCH_INDEX_SECONDARY, side_effect=RuntimeError("future down")),
            ):
                result = _supply_user_file_to_secondary(
                    str(uf.id), POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
                )
            assert result is False
        finally:
            _purge_user_files(db_session, user)


def _run_index_pass(uf_id: str, port_target: Any, index_secondary: MagicMock) -> None:
    """Drive _process_user_file_with_indexing with the PRESENT pass fully mocked, so only
    the FUTURE dual-write orchestration is exercised."""
    present_result = IndexingPipelineResult(
        new_docs=1, total_docs=1, total_chunks=3, failures=[]
    )
    current = MagicMock()
    current.status.is_current.return_value = True

    with (
        patch(_PATCH_HTTPX_INIT),
        patch(_PATCH_GET_SETTINGS_LIST, return_value=[current]),
        patch(_PATCH_EMBEDDER),
        patch(_PATCH_GET_INDICES, return_value=[MagicMock()]),
        patch(_PATCH_RUN_PIPELINE, return_value=present_result),
        patch(_PATCH_ACTIVE_SECONDARY, return_value=port_target),
        patch(_PATCH_INDEX_SECONDARY, index_secondary),
    ):
        _process_user_file_with_indexing(
            uf_id, [make_doc(uf_id)], POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        )


class TestIndexTimeDualWrite:
    """_process_user_file_with_indexing runs a FUTURE pass during a port, isolated from
    live status."""

    def test_dual_write_runs_when_target_present(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """A target exists -> after the PRESENT pass the file is also indexed into FUTURE,
        with the resolved target threaded through."""
        user = create_test_user(db_session, "idx_dw")
        uf = _create_completed_user_file(db_session, user)
        try:
            target = MagicMock()
            index_secondary = MagicMock()
            _run_index_pass(
                str(uf.id), port_target=target, index_secondary=index_secondary
            )
            index_secondary.assert_called_once()
            assert index_secondary.call_args.args[0] == str(uf.id)
            assert index_secondary.call_args.args[2] is target
        finally:
            _purge_user_files(db_session, user)

    def test_no_dual_write_when_no_target(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """No port in progress -> no FUTURE pass (the common, non-reindex case)."""
        user = create_test_user(db_session, "idx_notgt")
        uf = _create_completed_user_file(db_session, user)
        try:
            index_secondary = MagicMock()
            _run_index_pass(
                str(uf.id), port_target=None, index_secondary=index_secondary
            )
            index_secondary.assert_not_called()
        finally:
            _purge_user_files(db_session, user)

    def test_dual_write_failure_flags_and_keeps_status(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """H1: a FUTURE-pass failure flags the file for the drain and must NOT flip live
        status — the PRESENT write already succeeded."""
        user = create_test_user(db_session, "idx_fail")
        uf = _create_completed_user_file(db_session, user)
        try:
            index_secondary = MagicMock(side_effect=RuntimeError("future down"))
            _run_index_pass(
                str(uf.id), port_target=MagicMock(), index_secondary=index_secondary
            )
            db_session.refresh(uf)
            assert uf.secondary_reconcile_pending is True
            assert uf.status == UserFileStatus.COMPLETED
        finally:
            _purge_user_files(db_session, user)


class TestSecondaryPassSkipsTerminalSideEffects:
    """A secondary (index_to_secondary) post_index must not re-apply the PRESENT pass's
    terminal side-effects."""

    def test_secondary_post_index_is_noop(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """post_index with index_to_secondary=True leaves status and chunk_count untouched (a
        primary pass would set COMPLETED + the enrichment chunk count)."""
        user = create_test_user(db_session, "secondary_pass")
        uf = UserFile(
            id=uuid4(),
            user_id=user.id,
            file_id=f"fp_{uuid4().hex[:8]}",
            name=f"{uuid4().hex[:8]}.txt",
            file_type="text/plain",
            status=UserFileStatus.INDEXING,
            chunk_count=99,
        )
        db_session.add(uf)
        db_session.commit()
        db_session.refresh(uf)
        try:
            enricher = UserFileChunkEnricher(
                user_file_id_to_access={},
                user_file_id_to_project_ids={},
                user_file_id_to_persona_ids={},
                doc_id_to_previous_chunk_cnt={},
                doc_id_to_new_chunk_cnt={str(uf.id): 0},
                user_file_id_to_raw_text={},
                user_file_id_to_token_count={},
                no_access=DocumentAccess.build(
                    user_emails=[],
                    user_groups=[],
                    external_user_emails=[],
                    external_user_group_ids=[],
                    is_public=False,
                ),
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            )
            adapter = UserFileIndexingAdapter(
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
                db_session=db_session,
            )
            adapter.post_index(
                context=MagicMock(),
                updatable_chunk_data=[],
                filtered_documents=[],
                enrichment=enricher,
                db_session=db_session,
                index_to_secondary=True,
            )
            db_session.refresh(uf)
            assert uf.status == UserFileStatus.INDEXING
            assert uf.chunk_count == 99
        finally:
            _purge_user_files(db_session, user)
