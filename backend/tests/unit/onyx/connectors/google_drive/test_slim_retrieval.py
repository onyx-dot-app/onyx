"""Unit tests for GoogleDriveConnector slim retrieval routing.

Verifies that:
- GoogleDriveConnector implements SlimConnector so pruning takes the ID-only path
- retrieve_all_slim_docs() calls _extract_slim_docs_from_google_drive with include_permissions=False
- retrieve_all_slim_docs_perm_sync() calls _extract_slim_docs_from_google_drive with include_permissions=True
- celery_utils routing picks retrieve_all_slim_docs() for GoogleDriveConnector
"""

from unittest.mock import MagicMock, call, patch

from google.auth.exceptions import RefreshError

from onyx.access.models import ExternalAccess
from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.doc_conversion import (
    PermissionSyncContext,
    build_slim_document,
)
from onyx.connectors.google_drive.file_retrieval import DriveFileFieldType
from onyx.connectors.google_drive.models import (
    DriveRetrievalStage,
    GoogleDriveCheckpoint,
    StageCompletion,
)
from onyx.connectors.google_utils.resources import ImpersonationError
from onyx.connectors.interfaces import SlimConnector, SlimConnectorWithPermSync
from onyx.connectors.models import SlimDocument
from onyx.utils.threadpool_concurrency import ThreadSafeDict, ThreadSafeSet

_ADMIN_EMAIL = "admin@example.com"
_EXTERNAL_OWNER_EMAIL = "owner@external.example"
_RETRIEVER_EMAIL = "retriever@example.com"
_DOC_CONVERSION_MODULE = "onyx.connectors.google_drive.doc_conversion"


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
    connector._primary_admin_email = _ADMIN_EMAIL
    return connector


class TestBuildSlimDocumentPermissions:
    def test_routes_owner_then_retriever_fallback(self) -> None:
        creds = MagicMock()
        owner_service = MagicMock()
        retriever_service = MagicMock()
        admin_service = MagicMock()
        external_access = ExternalAccess.empty()
        file = {
            "id": "file-id",
            "mimeType": "text/plain",
            "webViewLink": "https://drive.google.com/file/d/file-id/view",
            "owners": [{"emailAddress": _EXTERNAL_OWNER_EMAIL}],
        }
        permission_sync_context = PermissionSyncContext(
            primary_admin_email=_ADMIN_EMAIL,
            google_domain="example.com",
        )

        with (
            patch(
                f"{_DOC_CONVERSION_MODULE}.get_drive_service",
                side_effect=[owner_service, admin_service, retriever_service],
            ) as mock_get_drive_service,
            patch(
                f"{_DOC_CONVERSION_MODULE}._get_external_access_for_raw_gdrive_file",
                return_value=external_access,
            ) as mock_get_external_access,
        ):
            slim_document = build_slim_document(
                creds,
                file,
                permission_sync_context,
                _RETRIEVER_EMAIL,
            )
            fallback_drive_service_factory = mock_get_external_access.call_args.kwargs[
                "fallback_drive_service_factory"
            ]
            assert fallback_drive_service_factory() is retriever_service

        assert slim_document is not None
        assert slim_document.external_access == external_access
        assert mock_get_drive_service.call_args_list == [
            call(creds, user_email=_EXTERNAL_OWNER_EMAIL),
            call(creds, user_email=_ADMIN_EMAIL),
            call(creds, user_email=_RETRIEVER_EMAIL),
        ]
        access_kwargs = mock_get_external_access.call_args.kwargs
        assert access_kwargs["file"] == file
        assert access_kwargs["company_domain"] == "example.com"
        assert access_kwargs["retriever_drive_service"] is owner_service
        assert access_kwargs["admin_drive_service"] is admin_service
        assert access_kwargs["fallback_user_email"] == _RETRIEVER_EMAIL


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
            spec=SlimDocument,
            id="doc1",
            parent_hierarchy_raw_node_id=None,
            doc_created_at=None,
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
            spec=SlimDocument,
            id="doc1",
            parent_hierarchy_raw_node_id=None,
            doc_created_at=None,
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
            spec=SlimDocument,
            id="doc1",
            parent_hierarchy_raw_node_id=None,
            doc_created_at=None,
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
            spec=SlimDocument,
            id="doc1",
            parent_hierarchy_raw_node_id=None,
            doc_created_at=None,
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
            spec=SlimDocument,
            id="doc1",
            parent_hierarchy_raw_node_id=None,
            doc_created_at=None,
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


class TestOrphanedPathBackfill:
    def _make_failed_map(
        self, entries: dict[str, set[str]]
    ) -> ThreadSafeDict[str, ThreadSafeSet[str]]:
        return ThreadSafeDict({k: ThreadSafeSet(v) for k, v in entries.items()})

    def _make_file(self, parent_id: str) -> MagicMock:
        file = MagicMock()
        file.user_email = "retriever@example.com"
        file.drive_file = {"parents": [parent_id]}
        return file

    def test_backfills_intermediate_folders_into_failed_map(self) -> None:
        """When a walk dead-ends at a confirmed orphan, all intermediate folder
        IDs must be added to failed_folder_ids_by_email for both emails so
        future files short-circuit via _get_folder_metadata's cache check."""
        connector = _make_connector()

        # Chain: folderA -> folderB -> folderC (confirmed orphan)
        failed_map = self._make_failed_map(
            {
                "retriever@example.com": {"folderC"},
                "admin@example.com": {"folderC"},
            }
        )

        folder_a = {"id": "folderA", "name": "A", "parents": ["folderB"]}
        folder_b = {"id": "folderB", "name": "B", "parents": ["folderC"]}

        def mock_get_folder(
            _service: MagicMock, folder_id: str, _field_type: DriveFileFieldType
        ) -> dict | None:
            if folder_id == "folderA":
                return folder_a
            if folder_id == "folderB":
                return folder_b
            return None

        with (
            patch(
                "onyx.connectors.google_drive.connector.get_drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "onyx.connectors.google_drive.connector.get_folder_metadata",
                side_effect=mock_get_folder,
            ),
        ):
            connector._get_new_ancestors_for_files(
                files=[self._make_file("folderA")],
                seen_hierarchy_node_raw_ids=ThreadSafeSet(),
                fully_walked_hierarchy_node_raw_ids=ThreadSafeSet(),
                failed_folder_ids_by_email=failed_map,
            )

        # Both emails confirmed folderC as orphan, so both get the backfill
        for email in ("retriever@example.com", "admin@example.com"):
            cached = failed_map.get(email, ThreadSafeSet())
            assert "folderA" in cached
            assert "folderB" in cached
            assert "folderC" in cached

    def test_backfills_only_for_confirming_email(self) -> None:
        """Only the email that confirmed the orphan gets the path backfilled."""
        connector = _make_connector()

        # Only retriever confirmed folderC as orphan; admin has no entry
        failed_map = self._make_failed_map({"retriever@example.com": {"folderC"}})

        folder_a = {"id": "folderA", "name": "A", "parents": ["folderB"]}
        folder_b = {"id": "folderB", "name": "B", "parents": ["folderC"]}

        def mock_get_folder(
            _service: MagicMock, folder_id: str, _field_type: DriveFileFieldType
        ) -> dict | None:
            if folder_id == "folderA":
                return folder_a
            if folder_id == "folderB":
                return folder_b
            return None

        with (
            patch(
                "onyx.connectors.google_drive.connector.get_drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "onyx.connectors.google_drive.connector.get_folder_metadata",
                side_effect=mock_get_folder,
            ),
        ):
            connector._get_new_ancestors_for_files(
                files=[self._make_file("folderA")],
                seen_hierarchy_node_raw_ids=ThreadSafeSet(),
                fully_walked_hierarchy_node_raw_ids=ThreadSafeSet(),
                failed_folder_ids_by_email=failed_map,
            )

        retriever_cached = failed_map.get("retriever@example.com", ThreadSafeSet())
        assert "folderA" in retriever_cached
        assert "folderB" in retriever_cached

        # admin did not confirm the orphan — must not get the backfill
        assert failed_map.get("admin@example.com") is None

    def test_short_circuits_on_backfilled_intermediate(self) -> None:
        """A second file whose parent is already in failed_folder_ids_by_email
        must not trigger any folder metadata API calls."""
        connector = _make_connector()

        # folderA already in the failed map from a previous walk
        failed_map = self._make_failed_map(
            {
                "retriever@example.com": {"folderA"},
                "admin@example.com": {"folderA"},
            }
        )

        with (
            patch(
                "onyx.connectors.google_drive.connector.get_drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "onyx.connectors.google_drive.connector.get_folder_metadata"
            ) as mock_api,
        ):
            connector._get_new_ancestors_for_files(
                files=[self._make_file("folderA")],
                seen_hierarchy_node_raw_ids=ThreadSafeSet(),
                fully_walked_hierarchy_node_raw_ids=ThreadSafeSet(),
                failed_folder_ids_by_email=failed_map,
            )

        mock_api.assert_not_called()


def _make_checkpoint_with_user(user_email: str) -> GoogleDriveCheckpoint:
    completion_map: ThreadSafeDict[str, StageCompletion] = ThreadSafeDict(
        {
            user_email: StageCompletion(
                stage=DriveRetrievalStage.START,
                completed_until=0,
            )
        }
    )
    return GoogleDriveCheckpoint(
        retrieved_folder_and_drive_ids=set(),
        completion_stage=DriveRetrievalStage.MY_DRIVE_FILES,
        completion_map=completion_map,
        all_retrieved_file_ids=set(),
        has_more=False,
        user_emails=[user_email],
    )


class TestImpersonateUserRefreshError:
    def test_user_removed_error_skips_silently(self) -> None:
        """RefreshError + user absent from workspace: silent skip, no error yielded, stage DONE."""
        user_email = "wilbur.suero@savvywealth.com"
        connector = _make_connector()
        checkpoint = _make_checkpoint_with_user(user_email)

        with (
            patch(
                "onyx.connectors.google_drive.connector.get_drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "onyx.connectors.google_drive.connector.get_root_folder_id",
                side_effect=RefreshError("invalid_grant: Invalid email or User ID"),
            ),
            patch(
                "onyx.connectors.google_drive.connector.retry_builder",
                return_value=lambda f: f,
            ),
            patch.object(
                connector,
                "_get_all_user_emails",
                return_value=["admin@example.com"],  # user absent
            ),
        ):
            results = list(
                connector._impersonate_user_for_retrieval(
                    user_email=user_email,
                    field_type=DriveFileFieldType.SLIM,
                    checkpoint=checkpoint,
                    get_new_drive_id=lambda _: None,
                    sorted_filtered_folder_ids=[],
                )
            )

        assert results == []
        assert checkpoint.completion_map[user_email].stage == DriveRetrievalStage.DONE

    def test_impersonation_error_yields_error(self) -> None:
        """RefreshError + user still present: error record yielded, stage DONE."""
        user_email = "wilbur.suero@savvywealth.com"
        connector = _make_connector()
        checkpoint = _make_checkpoint_with_user(user_email)

        with (
            patch(
                "onyx.connectors.google_drive.connector.get_drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "onyx.connectors.google_drive.connector.get_root_folder_id",
                side_effect=RefreshError("token_refresh_failed"),
            ),
            patch(
                "onyx.connectors.google_drive.connector.retry_builder",
                return_value=lambda f: f,
            ),
            patch.object(
                connector,
                "_get_all_user_emails",
                return_value=[user_email, "admin@example.com"],  # user present
            ),
        ):
            results = list(
                connector._impersonate_user_for_retrieval(
                    user_email=user_email,
                    field_type=DriveFileFieldType.SLIM,
                    checkpoint=checkpoint,
                    get_new_drive_id=lambda _: None,
                    sorted_filtered_folder_ids=[],
                )
            )

        assert len(results) == 1
        assert isinstance(results[0].error, ImpersonationError)
        assert results[0].error.user_email == user_email
        assert checkpoint.completion_map[user_email].stage == DriveRetrievalStage.DONE

    def test_fresh_emails_callback_updates_checkpoint(self) -> None:
        """_make_fresh_emails_callback returns a closure that calls _get_all_user_emails
        and updates checkpoint.user_emails as a side effect."""
        user_email = "wilbur.suero@savvywealth.com"
        connector = _make_connector()
        checkpoint = _make_checkpoint_with_user(user_email)
        fresh_emails = ["admin@example.com"]  # user absent from fresh list

        with patch.object(connector, "_get_all_user_emails", return_value=fresh_emails):
            callback = connector._make_fresh_emails_callback(checkpoint)
            result = callback()

        assert result == fresh_emails
        assert checkpoint.user_emails == fresh_emails
        assert user_email not in (checkpoint.user_emails or [])
