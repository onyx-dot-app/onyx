"""
External dependency unit tests for docprocessing task priority.

Tests that docprocessing tasks spawned by connector_document_extraction
get the correct priority based on last_successful_index_time.

Uses real database objects for CC pairs, search settings, and index attempts.
"""

from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.indexing.run_docfetching import connector_document_extraction
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import OnyxCeleryPriority
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import EmbeddingPrecision
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import IndexAttempt
from onyx.db.models import SearchSettings
from tests.external_dependency_unit.constants import TEST_TENANT_ID


def _create_test_connector(db_session: Session, name: str) -> Connector:
    """Create a test connector with all required fields."""
    connector = Connector(
        name=name,
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
        refresh_freq=3600,
    )
    db_session.add(connector)
    db_session.commit()
    db_session.refresh(connector)
    return connector


def _create_test_credential(db_session: Session) -> Credential:
    """Create a test credential with all required fields."""
    credential = Credential(
        name=f"test_credential_{uuid4().hex[:8]}",
        source=DocumentSource.FILE,
        credential_json={},
        admin_public=True,
    )
    db_session.add(credential)
    db_session.commit()
    db_session.refresh(credential)
    return credential


def _create_test_cc_pair(
    db_session: Session,
    connector: Connector,
    credential: Credential,
    status: ConnectorCredentialPairStatus,
    name: str,
    last_successful_index_time: datetime | None = None,
) -> ConnectorCredentialPair:
    """Create a connector credential pair with the specified status."""
    cc_pair = ConnectorCredentialPair(
        name=name,
        connector_id=connector.id,
        credential_id=credential.id,
        status=status,
        access_type=AccessType.PUBLIC,
        last_successful_index_time=last_successful_index_time,
    )
    db_session.add(cc_pair)
    db_session.commit()
    db_session.refresh(cc_pair)
    return cc_pair


def _create_test_search_settings(
    db_session: Session, index_name: str
) -> SearchSettings:
    """Create test search settings with all required fields."""
    search_settings = SearchSettings(
        model_name="test-model",
        model_dim=768,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        status=IndexModelStatus.PRESENT,
        index_name=index_name,
        embedding_precision=EmbeddingPrecision.FLOAT,
    )
    db_session.add(search_settings)
    db_session.commit()
    db_session.refresh(search_settings)
    return search_settings


def _create_test_index_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    from_beginning: bool = False,
) -> IndexAttempt:
    """Create a test index attempt with the specified cc_pair and search_settings."""
    index_attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=search_settings.id,
        from_beginning=from_beginning,
        status=IndexingStatus.IN_PROGRESS,
        celery_task_id=f"test_celery_task_{uuid4().hex[:8]}",
    )
    db_session.add(index_attempt)
    db_session.commit()
    db_session.refresh(index_attempt)
    return index_attempt


class TestDocprocessingPriorityInDocumentExtraction:
    """
    Tests for docprocessing task priority within connector_document_extraction.

    Verifies that the priority passed to docprocessing tasks is determined
    by last_successful_index_time on the cc_pair.
    """

    @pytest.mark.parametrize(
        "has_successful_index,expected_priority",
        [
            # First-time indexing (no last_successful_index_time) should get HIGH priority
            (False, OnyxCeleryPriority.HIGH),
            # Re-indexing (has last_successful_index_time) should get MEDIUM priority
            (True, OnyxCeleryPriority.MEDIUM),
        ],
    )
    @patch("onyx.background.indexing.run_docfetching.get_document_batch_storage")
    @patch("onyx.background.indexing.run_docfetching.MemoryTracer")
    @patch("onyx.background.indexing.run_docfetching._get_connector_runner")
    @patch(
        "onyx.background.indexing.run_docfetching.get_recent_completed_attempts_for_cc_pair"
    )
    @patch(
        "onyx.background.indexing.run_docfetching.get_last_successful_attempt_poll_range_end"
    )
    @patch("onyx.background.indexing.run_docfetching.save_checkpoint")
    @patch("onyx.background.indexing.run_docfetching.get_latest_valid_checkpoint")
    def test_docprocessing_priority_based_on_last_successful_index_time(
        self,
        mock_get_latest_valid_checkpoint: MagicMock,
        mock_save_checkpoint: MagicMock,
        mock_get_last_successful_attempt_poll_range_end: MagicMock,
        mock_get_recent_completed_attempts: MagicMock,
        mock_get_connector_runner: MagicMock,
        mock_memory_tracer_class: MagicMock,
        mock_get_batch_storage: MagicMock,
        db_session: Session,
        has_successful_index: bool,
        expected_priority: OnyxCeleryPriority,
    ) -> None:
        """
        Test that docprocessing tasks get the correct priority based on
        last_successful_index_time.

        Priority is determined by last_successful_index_time:
        - None (never indexed): HIGH priority
        - Has timestamp (previously indexed): MEDIUM priority

        Uses real database objects for CC pairs and search settings.
        """
        unique_suffix = uuid4().hex[:8]

        # Determine last_successful_index_time based on the test case
        last_successful_index_time = (
            datetime.now(timezone.utc) if has_successful_index else None
        )

        # Create real database objects
        connector = _create_test_connector(
            db_session, f"test_connector_docproc_{has_successful_index}_{unique_suffix}"
        )
        credential = _create_test_credential(db_session)
        cc_pair = _create_test_cc_pair(
            db_session,
            connector,
            credential,
            ConnectorCredentialPairStatus.ACTIVE,
            name=f"test_cc_pair_docproc_{has_successful_index}_{unique_suffix}",
            last_successful_index_time=last_successful_index_time,
        )
        search_settings = _create_test_search_settings(
            db_session, f"test_index_docproc_{unique_suffix}"
        )
        index_attempt = _create_test_index_attempt(
            db_session, cc_pair, search_settings, from_beginning=False
        )

        # Setup mocks
        mock_batch_storage = MagicMock()
        mock_get_batch_storage.return_value = mock_batch_storage

        mock_memory_tracer = MagicMock()
        mock_memory_tracer_class.return_value = mock_memory_tracer

        # Create checkpoint mocks - initial checkpoint has_more=True, final has_more=False
        mock_initial_checkpoint = MagicMock(has_more=True)
        mock_final_checkpoint = MagicMock(has_more=False)

        # get_latest_valid_checkpoint returns (checkpoint, resuming_from_checkpoint)
        mock_get_latest_valid_checkpoint.return_value = (mock_initial_checkpoint, False)

        # Create a mock connector runner that yields one document batch
        mock_connector = MagicMock()
        mock_connector_runner = MagicMock()
        mock_connector_runner.connector = mock_connector
        # The connector runner yields (document_batch, failure, next_checkpoint)
        # We provide one batch of documents to trigger a send_task call
        mock_doc = MagicMock()
        mock_doc.to_short_descriptor.return_value = "test_doc"
        mock_doc.sections = []
        mock_connector_runner.run.return_value = iter(
            [([mock_doc], None, mock_final_checkpoint)]
        )
        mock_get_connector_runner.return_value = mock_connector_runner

        mock_get_recent_completed_attempts.return_value = iter([])
        mock_get_last_successful_attempt_poll_range_end.return_value = 0

        # Mock celery app to capture task submission
        mock_celery_app = MagicMock()
        mock_celery_app.send_task.return_value = MagicMock()

        # Call the function
        connector_document_extraction(
            app=mock_celery_app,
            index_attempt_id=index_attempt.id,
            cc_pair_id=cc_pair.id,
            search_settings_id=search_settings.id,
            tenant_id=TEST_TENANT_ID,
            callback=None,
        )

        # Verify send_task was called with the expected priority for docprocessing
        assert mock_celery_app.send_task.called, "send_task should have been called"
        call_kwargs = mock_celery_app.send_task.call_args
        actual_priority = call_kwargs.kwargs["priority"]
        assert actual_priority == expected_priority, (
            f"Expected priority {expected_priority} for has_successful_index={has_successful_index}, "
            f"but got {actual_priority}"
        )
