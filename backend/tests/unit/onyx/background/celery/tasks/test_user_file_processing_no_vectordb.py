"""Tests for no-vector-DB user file processing paths.

Verifies that when DISABLE_VECTOR_DB is True:
- _process_user_file_impl calls _process_user_file_without_vector_db (not indexing)
- _process_user_file_without_vector_db extracts text, counts tokens, stores plaintext,
  sets status=COMPLETED and chunk_count=0
- _delete_user_file_impl skips vector DB chunk deletion
- _project_sync_user_file_impl skips vector DB metadata update
"""

from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

from onyx.background.celery.tasks.user_file_processing.tasks import (
    _delete_user_file_impl,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    _process_user_file_impl,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    _process_user_file_without_vector_db,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    _project_sync_user_file_impl,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.db.enums import UserFileStatus

TASKS_MODULE = "onyx.background.celery.tasks.user_file_processing.tasks"
LLM_FACTORY_MODULE = "onyx.llm.factory"


def _make_documents(texts: list[str]) -> list[Document]:
    """Build a list of Document objects with the given section texts."""
    return [
        Document(
            id=str(uuid4()),
            source=DocumentSource.USER_FILE,
            sections=[TextSection(text=t)],
            semantic_identifier=f"test-doc-{i}",
            metadata={},
        )
        for i, t in enumerate(texts)
    ]


def _make_user_file(
    *,
    status: UserFileStatus = UserFileStatus.PROCESSING,
    file_id: str = "test-file-id",
    name: str = "test.txt",
) -> MagicMock:
    """Return a MagicMock mimicking a UserFile ORM instance."""
    uf = MagicMock()
    uf.id = uuid4()
    uf.file_id = file_id
    uf.name = name
    uf.status = status
    uf.token_count = None
    uf.chunk_count = None
    uf.last_project_sync_at = None
    uf.projects = []
    uf.assistants = []
    uf.needs_project_sync = True
    uf.needs_persona_sync = True
    return uf


# ------------------------------------------------------------------
# _process_user_file_without_vector_db — direct tests
# ------------------------------------------------------------------


class TestProcessUserFileWithoutVectorDb:
    @patch(f"{TASKS_MODULE}.store_user_file_plaintext")
    @patch(f"{LLM_FACTORY_MODULE}.get_llm_tokenizer_encode_func")
    @patch(f"{LLM_FACTORY_MODULE}.get_default_llm")
    def test_extracts_and_combines_text(
        self,
        mock_get_llm: MagicMock,  # noqa: ARG002
        mock_get_encode: MagicMock,
        mock_store_plaintext: MagicMock,
    ) -> None:
        mock_encode = MagicMock(return_value=[1, 2, 3, 4, 5])
        mock_get_encode.return_value = mock_encode

        uf = _make_user_file()
        docs = _make_documents(["hello world", "foo bar"])
        db_session = MagicMock()

        _process_user_file_without_vector_db(uf, docs, db_session)

        stored_text = mock_store_plaintext.call_args.kwargs["plaintext_content"]
        assert "hello world" in stored_text
        assert "foo bar" in stored_text

    @patch(f"{TASKS_MODULE}.store_user_file_plaintext")
    @patch(f"{LLM_FACTORY_MODULE}.get_llm_tokenizer_encode_func")
    @patch(f"{LLM_FACTORY_MODULE}.get_default_llm")
    def test_computes_token_count(
        self,
        mock_get_llm: MagicMock,  # noqa: ARG002
        mock_get_encode: MagicMock,
        mock_store_plaintext: MagicMock,  # noqa: ARG002
    ) -> None:
        mock_encode = MagicMock(return_value=list(range(42)))
        mock_get_encode.return_value = mock_encode

        uf = _make_user_file()
        docs = _make_documents(["some text content"])
        db_session = MagicMock()

        _process_user_file_without_vector_db(uf, docs, db_session)

        assert uf.token_count == 42

    @patch(f"{TASKS_MODULE}.store_user_file_plaintext")
    @patch(f"{LLM_FACTORY_MODULE}.get_llm_tokenizer_encode_func")
    @patch(f"{LLM_FACTORY_MODULE}.get_default_llm")
    def test_token_count_falls_back_to_none_on_error(
        self,
        mock_get_llm: MagicMock,
        mock_get_encode: MagicMock,  # noqa: ARG002
        mock_store_plaintext: MagicMock,  # noqa: ARG002
    ) -> None:
        mock_get_llm.side_effect = RuntimeError("No LLM configured")

        uf = _make_user_file()
        docs = _make_documents(["text"])
        db_session = MagicMock()

        _process_user_file_without_vector_db(uf, docs, db_session)

        assert uf.token_count is None

    @patch(f"{TASKS_MODULE}.store_user_file_plaintext")
    @patch(f"{LLM_FACTORY_MODULE}.get_llm_tokenizer_encode_func")
    @patch(f"{LLM_FACTORY_MODULE}.get_default_llm")
    def test_stores_plaintext(
        self,
        mock_get_llm: MagicMock,  # noqa: ARG002
        mock_get_encode: MagicMock,
        mock_store_plaintext: MagicMock,
    ) -> None:
        mock_get_encode.return_value = MagicMock(return_value=[1])

        uf = _make_user_file()
        docs = _make_documents(["content to store"])
        db_session = MagicMock()

        _process_user_file_without_vector_db(uf, docs, db_session)

        mock_store_plaintext.assert_called_once_with(
            user_file_id=uf.id,
            plaintext_content="content to store",
        )

    @patch(f"{TASKS_MODULE}.store_user_file_plaintext")
    @patch(f"{LLM_FACTORY_MODULE}.get_llm_tokenizer_encode_func")
    @patch(f"{LLM_FACTORY_MODULE}.get_default_llm")
    def test_sets_completed_status_and_zero_chunk_count(
        self,
        mock_get_llm: MagicMock,  # noqa: ARG002
        mock_get_encode: MagicMock,
        mock_store_plaintext: MagicMock,  # noqa: ARG002
    ) -> None:
        mock_get_encode.return_value = MagicMock(return_value=[1])

        uf = _make_user_file()
        docs = _make_documents(["text"])
        db_session = MagicMock()

        _process_user_file_without_vector_db(uf, docs, db_session)

        assert uf.status == UserFileStatus.COMPLETED
        assert uf.chunk_count == 0
        assert uf.last_project_sync_at is not None
        db_session.add.assert_called_once_with(uf)
        db_session.commit.assert_called_once()

    @patch(f"{TASKS_MODULE}.store_user_file_plaintext")
    @patch(f"{LLM_FACTORY_MODULE}.get_llm_tokenizer_encode_func")
    @patch(f"{LLM_FACTORY_MODULE}.get_default_llm")
    def test_preserves_deleting_status(
        self,
        mock_get_llm: MagicMock,  # noqa: ARG002
        mock_get_encode: MagicMock,
        mock_store_plaintext: MagicMock,  # noqa: ARG002
    ) -> None:
        mock_get_encode.return_value = MagicMock(return_value=[1])

        uf = _make_user_file(status=UserFileStatus.DELETING)
        docs = _make_documents(["text"])
        db_session = MagicMock()

        _process_user_file_without_vector_db(uf, docs, db_session)

        assert uf.status == UserFileStatus.DELETING
        assert uf.chunk_count == 0


# ------------------------------------------------------------------
# _process_user_file_impl — branching on DISABLE_VECTOR_DB
# ------------------------------------------------------------------


class TestProcessImplBranching:
    @patch(f"{TASKS_MODULE}._process_user_file_without_vector_db")
    @patch(f"{TASKS_MODULE}._process_user_file_with_indexing")
    @patch(f"{TASKS_MODULE}.DISABLE_VECTOR_DB", True)
    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    def test_calls_without_vector_db_when_disabled(
        self,
        mock_get_session: MagicMock,
        mock_with_indexing: MagicMock,
        mock_without_vdb: MagicMock,
    ) -> None:
        uf = _make_user_file()
        session = MagicMock()
        session.get.return_value = uf
        mock_get_session.return_value.__enter__.return_value = session

        connector_mock = MagicMock()
        connector_mock.load_from_state.return_value = [_make_documents(["hello"])]

        with patch(f"{TASKS_MODULE}.LocalFileConnector", return_value=connector_mock):
            _process_user_file_impl(
                user_file_id=str(uf.id),
                tenant_id="test-tenant",
                redis_locking=False,
            )

        mock_without_vdb.assert_called_once()
        mock_with_indexing.assert_not_called()

    @patch(f"{TASKS_MODULE}._process_user_file_without_vector_db")
    @patch(f"{TASKS_MODULE}._process_user_file_with_indexing")
    @patch(f"{TASKS_MODULE}.DISABLE_VECTOR_DB", False)
    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    def test_calls_with_indexing_when_vector_db_enabled(
        self,
        mock_get_session: MagicMock,
        mock_with_indexing: MagicMock,
        mock_without_vdb: MagicMock,
    ) -> None:
        uf = _make_user_file()
        session = MagicMock()
        session.get.return_value = uf
        mock_get_session.return_value.__enter__.return_value = session

        connector_mock = MagicMock()
        connector_mock.load_from_state.return_value = [_make_documents(["hello"])]

        with patch(f"{TASKS_MODULE}.LocalFileConnector", return_value=connector_mock):
            _process_user_file_impl(
                user_file_id=str(uf.id),
                tenant_id="test-tenant",
                redis_locking=False,
            )

        mock_with_indexing.assert_called_once()
        mock_without_vdb.assert_not_called()

    @patch(f"{TASKS_MODULE}.run_indexing_pipeline")
    @patch(f"{TASKS_MODULE}.store_user_file_plaintext")
    @patch(f"{TASKS_MODULE}.DISABLE_VECTOR_DB", True)
    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    def test_indexing_pipeline_not_called_when_disabled(
        self,
        mock_get_session: MagicMock,
        mock_store_plaintext: MagicMock,  # noqa: ARG002
        mock_run_pipeline: MagicMock,
    ) -> None:
        """End-to-end: verify run_indexing_pipeline is never invoked."""
        uf = _make_user_file()
        session = MagicMock()
        session.get.return_value = uf
        mock_get_session.return_value.__enter__.return_value = session

        connector_mock = MagicMock()
        connector_mock.load_from_state.return_value = [_make_documents(["content"])]

        with (
            patch(f"{TASKS_MODULE}.LocalFileConnector", return_value=connector_mock),
            patch(f"{LLM_FACTORY_MODULE}.get_default_llm"),
            patch(
                f"{LLM_FACTORY_MODULE}.get_llm_tokenizer_encode_func",
                return_value=MagicMock(return_value=[1, 2, 3]),
            ),
        ):
            _process_user_file_impl(
                user_file_id=str(uf.id),
                tenant_id="test-tenant",
                redis_locking=False,
            )

        mock_run_pipeline.assert_not_called()


# ------------------------------------------------------------------
# _delete_user_file_impl — vector DB skip
# ------------------------------------------------------------------


class TestDeleteImplNoVectorDb:
    @patch(f"{TASKS_MODULE}.DISABLE_VECTOR_DB", True)
    @patch(f"{TASKS_MODULE}.get_default_file_store")
    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    def test_skips_vector_db_deletion(
        self,
        mock_get_session: MagicMock,
        mock_get_file_store: MagicMock,
    ) -> None:
        uf = _make_user_file(status=UserFileStatus.DELETING)
        session = MagicMock()
        session.get.return_value = uf
        mock_get_session.return_value.__enter__.return_value = session
        mock_get_file_store.return_value = MagicMock()

        with (
            patch(f"{TASKS_MODULE}.get_all_document_indices") as mock_get_indices,
            patch(f"{TASKS_MODULE}.get_active_search_settings") as mock_get_ss,
            patch(f"{TASKS_MODULE}.httpx_init_vespa_pool") as mock_vespa_pool,
        ):
            _delete_user_file_impl(
                user_file_id=str(uf.id),
                tenant_id="test-tenant",
                redis_locking=False,
            )

            mock_get_indices.assert_not_called()
            mock_get_ss.assert_not_called()
            mock_vespa_pool.assert_not_called()

        session.delete.assert_called_once_with(uf)
        session.commit.assert_called_once()

    @patch(f"{TASKS_MODULE}.DISABLE_VECTOR_DB", True)
    @patch(f"{TASKS_MODULE}.get_default_file_store")
    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    def test_still_deletes_file_store_and_db_record(
        self,
        mock_get_session: MagicMock,
        mock_get_file_store: MagicMock,
    ) -> None:
        uf = _make_user_file(status=UserFileStatus.DELETING)
        session = MagicMock()
        session.get.return_value = uf
        mock_get_session.return_value.__enter__.return_value = session

        file_store = MagicMock()
        mock_get_file_store.return_value = file_store

        _delete_user_file_impl(
            user_file_id=str(uf.id),
            tenant_id="test-tenant",
            redis_locking=False,
        )

        assert file_store.delete_file.call_count == 2
        session.delete.assert_called_once_with(uf)
        session.commit.assert_called_once()


# ------------------------------------------------------------------
# _project_sync_user_file_impl — vector DB skip
# ------------------------------------------------------------------


class TestProjectSyncImplNoVectorDb:
    @patch(f"{TASKS_MODULE}.DISABLE_VECTOR_DB", True)
    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    def test_skips_vector_db_update(
        self,
        mock_get_session: MagicMock,
    ) -> None:
        uf = _make_user_file(status=UserFileStatus.COMPLETED)
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = uf
        mock_get_session.return_value.__enter__.return_value = session

        with (
            patch(f"{TASKS_MODULE}.get_all_document_indices") as mock_get_indices,
            patch(f"{TASKS_MODULE}.get_active_search_settings") as mock_get_ss,
            patch(f"{TASKS_MODULE}.httpx_init_vespa_pool") as mock_vespa_pool,
        ):
            _project_sync_user_file_impl(
                user_file_id=str(uf.id),
                tenant_id="test-tenant",
                redis_locking=False,
            )

            mock_get_indices.assert_not_called()
            mock_get_ss.assert_not_called()
            mock_vespa_pool.assert_not_called()

    @patch(f"{TASKS_MODULE}.DISABLE_VECTOR_DB", True)
    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    def test_still_clears_sync_flags(
        self,
        mock_get_session: MagicMock,
    ) -> None:
        uf = _make_user_file(status=UserFileStatus.COMPLETED)
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = uf
        mock_get_session.return_value.__enter__.return_value = session

        _project_sync_user_file_impl(
            user_file_id=str(uf.id),
            tenant_id="test-tenant",
            redis_locking=False,
        )

        assert uf.needs_project_sync is False
        assert uf.needs_persona_sync is False
        assert uf.last_project_sync_at is not None
        session.add.assert_called_once_with(uf)
        session.commit.assert_called_once()
