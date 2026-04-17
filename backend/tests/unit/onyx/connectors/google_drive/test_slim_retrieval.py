"""Unit tests for GoogleDriveConnector slim retrieval routing.

Verifies that:
- GoogleDriveConnector implements SlimConnector so pruning takes the ID-only path
- retrieve_all_slim_docs() calls _extract_slim_docs_from_google_drive with include_permissions=False
- retrieve_all_slim_docs_perm_sync() calls _extract_slim_docs_from_google_drive with include_permissions=True
- celery_utils routing picks retrieve_all_slim_docs() for GoogleDriveConnector
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.file_retrieval import DriveFileFieldType
from onyx.connectors.google_drive.models import DriveRetrievalStage
from onyx.connectors.google_drive.models import GoogleDriveCheckpoint
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import SlimDocument
from onyx.utils.threadpool_concurrency import ThreadSafeDict
from onyx.utils.threadpool_concurrency import ThreadSafeSet


def _make_done_checkpoint() -> GoogleDriveCheckpoint:
    return GoogleDriveCheckpoint(
        retrieved_folder_and_drive_ids=set(),
        completion_stage=DriveRetrievalStage.DONE,
        completion_map=ThreadSafeDict(),
        all_retrieved_file_ids=set(),
        has_more=False,
    )


def _make_connector() -> GoogleDriveConnector:
    connector = GoogleDriveConnector(include_my_drives=True)
    connector._creds = MagicMock()
    connector._primary_admin_email = "admin@example.com"
    return connector


class TestGoogleDriveSlimConnectorInterface:
    def test_implements_slim_connector(self) -> None:
        connector = _make_connector()
        assert isinstance(connector, SlimConnector)

    def test_implements_slim_connector_with_perm_sync(self) -> None:
        connector = _make_connector()
        assert isinstance(connector, SlimConnectorWithPermSync)

    def test_slim_connector_checked_before_perm_sync(self) -> None:
        """SlimConnector must appear before SlimConnectorWithPermSync in MRO
        so celery_utils isinstance check routes to retrieve_all_slim_docs()."""
        mro = GoogleDriveConnector.__mro__
        slim_idx = mro.index(SlimConnector)
        perm_sync_idx = mro.index(SlimConnectorWithPermSync)
        assert slim_idx < perm_sync_idx


class TestRetrieveAllSlimDocs:
    def test_does_not_call_extract_when_checkpoint_is_done(self) -> None:
        connector = _make_connector()
        slim_doc = MagicMock(
            spec=SlimDocument, id="doc1", parent_hierarchy_raw_node_id=None
        )

        with patch.object(
            connector, "build_dummy_checkpoint", return_value=_make_done_checkpoint()
        ):
            with patch.object(
                connector,
                "_extract_slim_docs_from_google_drive",
                return_value=iter([[slim_doc]]),
            ) as mock_extract:
                list(connector.retrieve_all_slim_docs())

        mock_extract.assert_not_called()  # loop exits immediately since checkpoint is DONE

    def test_calls_extract_with_include_permissions_false_non_done_checkpoint(
        self,
    ) -> None:
        connector = _make_connector()
        slim_doc = MagicMock(
            spec=SlimDocument, id="doc1", parent_hierarchy_raw_node_id=None
        )
        # Checkpoint starts at START, _extract advances it to DONE
        with patch.object(connector, "build_dummy_checkpoint") as mock_build:
            start_checkpoint = GoogleDriveCheckpoint(
                retrieved_folder_and_drive_ids=set(),
                completion_stage=DriveRetrievalStage.START,
                completion_map=ThreadSafeDict(),
                all_retrieved_file_ids=set(),
                has_more=False,
            )
            mock_build.return_value = start_checkpoint

            def _advance_checkpoint(**_kwargs: object) -> object:
                start_checkpoint.completion_stage = DriveRetrievalStage.DONE
                yield [slim_doc]

            with patch.object(
                connector,
                "_extract_slim_docs_from_google_drive",
                side_effect=_advance_checkpoint,
            ) as mock_extract:
                list(connector.retrieve_all_slim_docs())

        mock_extract.assert_called_once()
        _, kwargs = mock_extract.call_args
        assert kwargs.get("include_permissions") is False

    def test_yields_slim_documents(self) -> None:
        connector = _make_connector()
        slim_doc = MagicMock(
            spec=SlimDocument, id="doc1", parent_hierarchy_raw_node_id=None
        )
        start_checkpoint = GoogleDriveCheckpoint(
            retrieved_folder_and_drive_ids=set(),
            completion_stage=DriveRetrievalStage.START,
            completion_map=ThreadSafeDict(),
            all_retrieved_file_ids=set(),
            has_more=False,
        )

        with patch.object(
            connector, "build_dummy_checkpoint", return_value=start_checkpoint
        ):

            def _advance_and_yield(**_kwargs: object) -> object:
                start_checkpoint.completion_stage = DriveRetrievalStage.DONE
                yield [slim_doc]

            with patch.object(
                connector,
                "_extract_slim_docs_from_google_drive",
                side_effect=_advance_and_yield,
            ):
                batches = list(connector.retrieve_all_slim_docs())

        assert len(batches) == 1
        assert batches[0][0] is slim_doc


class TestRetrieveAllSlimDocsPermSync:
    def test_calls_extract_with_include_permissions_true(self) -> None:
        connector = _make_connector()
        slim_doc = MagicMock(
            spec=SlimDocument, id="doc1", parent_hierarchy_raw_node_id=None
        )
        start_checkpoint = GoogleDriveCheckpoint(
            retrieved_folder_and_drive_ids=set(),
            completion_stage=DriveRetrievalStage.START,
            completion_map=ThreadSafeDict(),
            all_retrieved_file_ids=set(),
            has_more=False,
        )

        with patch.object(
            connector, "build_dummy_checkpoint", return_value=start_checkpoint
        ):

            def _advance_and_yield(**_kwargs: object) -> object:
                start_checkpoint.completion_stage = DriveRetrievalStage.DONE
                yield [slim_doc]

            with patch.object(
                connector,
                "_extract_slim_docs_from_google_drive",
                side_effect=_advance_and_yield,
            ) as mock_extract:
                list(connector.retrieve_all_slim_docs_perm_sync())

        mock_extract.assert_called_once()
        _, kwargs = mock_extract.call_args
        assert (
            kwargs.get("include_permissions") is None
            or kwargs.get("include_permissions") is True
        )


class TestCeleryUtilsRouting:
    def test_pruning_uses_retrieve_all_slim_docs(self) -> None:
        """extract_ids_from_runnable_connector must call retrieve_all_slim_docs,
        not retrieve_all_slim_docs_perm_sync, for GoogleDriveConnector."""
        connector = _make_connector()
        slim_doc = MagicMock(
            spec=SlimDocument, id="doc1", parent_hierarchy_raw_node_id=None
        )
        with (
            patch.object(
                connector, "retrieve_all_slim_docs", return_value=iter([[slim_doc]])
            ) as mock_slim,
            patch.object(
                connector, "retrieve_all_slim_docs_perm_sync"
            ) as mock_perm_sync,
        ):
            extract_ids_from_runnable_connector(
                connector, connector_type="google_drive"
            )

        mock_slim.assert_called_once()
        mock_perm_sync.assert_not_called()


class TestFailedFolderIdsByEmail:
    def _make_failed_map(
        self, entries: dict[str, set[str]]
    ) -> ThreadSafeDict[str, ThreadSafeSet[str]]:
        return ThreadSafeDict({k: ThreadSafeSet(v) for k, v in entries.items()})

    def test_skips_api_call_for_known_failed_pair(self) -> None:
        """_get_folder_metadata must skip the API call for a (folder, email) pair
        that previously confirmed no accessible parent."""
        connector = _make_connector()
        failed_map = self._make_failed_map(
            {
                "retriever@example.com": {"folder1"},
                "admin@example.com": {"folder1"},
            }
        )

        with patch(
            "onyx.connectors.google_drive.connector.get_folder_metadata"
        ) as mock_api:
            result = connector._get_folder_metadata(
                folder_id="folder1",
                retriever_email="retriever@example.com",
                field_type=DriveFileFieldType.SLIM,
                failed_folder_ids_by_email=failed_map,
            )

        mock_api.assert_not_called()
        assert result is None

    def test_records_failed_pair_when_no_parents(self) -> None:
        """_get_folder_metadata must record (email → folder_id) in the map
        when the API returns a folder with no parents."""
        connector = _make_connector()
        failed_map: ThreadSafeDict[str, ThreadSafeSet[str]] = ThreadSafeDict()
        folder_no_parents: dict = {"id": "folder1", "name": "Orphaned"}

        with (
            patch(
                "onyx.connectors.google_drive.connector.get_drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "onyx.connectors.google_drive.connector.get_folder_metadata",
                return_value=folder_no_parents,
            ),
        ):
            connector._get_folder_metadata(
                folder_id="folder1",
                retriever_email="retriever@example.com",
                field_type=DriveFileFieldType.SLIM,
                failed_folder_ids_by_email=failed_map,
            )

        assert "folder1" in failed_map.get("retriever@example.com", ThreadSafeSet())
        assert "folder1" in failed_map.get("admin@example.com", ThreadSafeSet())

    def test_does_not_record_when_parents_found(self) -> None:
        """_get_folder_metadata must NOT record a pair when parents are found."""
        connector = _make_connector()
        failed_map: ThreadSafeDict[str, ThreadSafeSet[str]] = ThreadSafeDict()
        folder_with_parents: dict = {
            "id": "folder1",
            "name": "Normal",
            "parents": ["root"],
        }

        with (
            patch(
                "onyx.connectors.google_drive.connector.get_drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "onyx.connectors.google_drive.connector.get_folder_metadata",
                return_value=folder_with_parents,
            ),
        ):
            connector._get_folder_metadata(
                folder_id="folder1",
                retriever_email="retriever@example.com",
                field_type=DriveFileFieldType.SLIM,
                failed_folder_ids_by_email=failed_map,
            )

        assert len(failed_map) == 0
