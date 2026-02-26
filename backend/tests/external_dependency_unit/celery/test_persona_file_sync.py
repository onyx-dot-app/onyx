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
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from unittest.mock import PropertyMock
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.background.celery.tasks.user_file_processing.tasks import (
    check_for_user_file_project_sync,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    process_single_user_file_project_sync,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    user_file_project_sync_lock_key,
)
from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.enums import UserFileStatus
from onyx.db.models import Persona
from onyx.db.models import Persona__UserFile
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.persona import upsert_persona
from onyx.document_index.interfaces import VespaDocumentUserFields
from onyx.redis.redis_pool import get_redis_client
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.constants import TEST_TENANT_ID

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
        num_chunks=10.0,
        chunks_above=0,
        chunks_below=0,
        llm_relevance_filter=False,
        llm_filter_extraction=False,
        recency_bias=RecencyBiasSetting.NO_DECAY,
        system_prompt="You are a test assistant",
        task_prompt="Answer the question",
        tools=[],
        document_sets=[],
        users=[user],
        groups=[],
        is_visible=True,
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


_PATCH_QUEUE_DEPTH = (
    "onyx.background.celery.tasks.user_file_processing.tasks"
    ".get_user_file_project_sync_queue_depth"
)


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
            check_for_user_file_project_sync.run(tenant_id=TEST_TENANT_ID)

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
            check_for_user_file_project_sync.run(tenant_id=TEST_TENANT_ID)

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
            check_for_user_file_project_sync.run(tenant_id=TEST_TENANT_ID)

        matching_calls = [
            call
            for call in mock_app.send_task.call_args_list
            if call.kwargs["kwargs"]["user_file_id"] == str(uf.id)
        ]
        assert len(matching_calls) == 1


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
        mock_search_settings.secondary = None

        redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
        lock_key = user_file_project_sync_lock_key(str(uf.id))
        redis_client.delete(lock_key)

        with (
            patch(_PATCH_DISABLE_VDB, False),
            patch(_PATCH_HTTPX_INIT),
            patch(_PATCH_GET_SETTINGS, return_value=mock_search_settings),
            patch(_PATCH_GET_INDICES, return_value=[mock_doc_index]),
        ):
            process_single_user_file_project_sync.run(
                user_file_id=str(uf.id), tenant_id=TEST_TENANT_ID
            )

        mock_doc_index.update_single.assert_called_once()
        call_args = mock_doc_index.update_single.call_args
        user_fields: VespaDocumentUserFields = call_args.kwargs["user_fields"]
        assert user_fields.personas is not None
        assert persona.id in user_fields.personas
        assert call_args.args[0] == str(uf.id)

    def test_clears_persona_sync_flag(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """After a successful sync the needs_persona_sync flag is cleared."""
        user = create_test_user(db_session, "sync_clear")
        uf = _create_completed_user_file(db_session, user, needs_persona_sync=True)

        redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
        lock_key = user_file_project_sync_lock_key(str(uf.id))
        redis_client.delete(lock_key)

        with patch(_PATCH_DISABLE_VDB, True):
            process_single_user_file_project_sync.run(
                user_file_id=str(uf.id), tenant_id=TEST_TENANT_ID
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
        mock_search_settings.secondary = None

        redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
        lock_key = user_file_project_sync_lock_key(str(uf.id))
        redis_client.delete(lock_key)

        with (
            patch(_PATCH_DISABLE_VDB, False),
            patch(_PATCH_HTTPX_INIT),
            patch(_PATCH_GET_SETTINGS, return_value=mock_search_settings),
            patch(_PATCH_GET_INDICES, return_value=[mock_doc_index]),
        ):
            process_single_user_file_project_sync.run(
                user_file_id=str(uf.id), tenant_id=TEST_TENANT_ID
            )

        call_kwargs = mock_doc_index.update_single.call_args.kwargs
        user_fields: VespaDocumentUserFields = call_kwargs["user_fields"]
        assert user_fields.personas is not None
        assert user_fields.user_projects is not None
        assert persona.id in user_fields.personas
        assert project.id in user_fields.user_projects

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
        mock_search_settings.secondary = None

        redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
        lock_key = user_file_project_sync_lock_key(str(uf.id))
        redis_client.delete(lock_key)

        with (
            patch(_PATCH_DISABLE_VDB, False),
            patch(_PATCH_HTTPX_INIT),
            patch(_PATCH_GET_SETTINGS, return_value=mock_search_settings),
            patch(_PATCH_GET_INDICES, return_value=[mock_doc_index]),
        ):
            process_single_user_file_project_sync.run(
                user_file_id=str(uf.id), tenant_id=TEST_TENANT_ID
            )

        call_kwargs = mock_doc_index.update_single.call_args.kwargs
        user_fields: VespaDocumentUserFields = call_kwargs["user_fields"]
        assert user_fields.personas is not None
        assert persona.id not in user_fields.personas


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
            num_chunks=10.0,
            llm_relevance_filter=False,
            llm_filter_extraction=False,
            recency_bias=RecencyBiasSetting.NO_DECAY,
            llm_model_provider_override=None,
            llm_model_version_override=None,
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
            num_chunks=10.0,
            llm_relevance_filter=False,
            llm_filter_extraction=False,
            recency_bias=RecencyBiasSetting.NO_DECAY,
            llm_model_provider_override=None,
            llm_model_version_override=None,
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

        assert persona.num_chunks is not None
        # Now update the persona to swap files
        upsert_persona(
            user=user,
            name=persona.name,
            description=persona.description,
            num_chunks=persona.num_chunks,
            llm_relevance_filter=persona.llm_relevance_filter,
            llm_filter_extraction=persona.llm_filter_extraction,
            recency_bias=persona.recency_bias,
            llm_model_provider_override=None,
            llm_model_version_override=None,
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
            num_chunks=10.0,
            llm_relevance_filter=False,
            llm_filter_extraction=False,
            recency_bias=RecencyBiasSetting.NO_DECAY,
            llm_model_provider_override=None,
            llm_model_version_override=None,
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

        assert persona.num_chunks is not None
        upsert_persona(
            user=user,
            name=persona.name,
            description=persona.description,
            num_chunks=persona.num_chunks,
            llm_relevance_filter=persona.llm_relevance_filter,
            llm_filter_extraction=persona.llm_filter_extraction,
            recency_bias=persona.recency_bias,
            llm_model_provider_override=None,
            llm_model_version_override=None,
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
