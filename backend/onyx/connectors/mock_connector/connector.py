from typing import Any

import httpx
from pydantic import BaseModel
from typing_extensions import override

from onyx.access.models import ExternalAccess
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger


logger = setup_logger()


EXTERNAL_USER_EMAILS = {"test@example.com", "admin@example.com"}
EXTERNAL_USER_GROUP_IDS = {"mock-group-1", "mock-group-2"}


class MockConnectorCheckpoint(ConnectorCheckpoint):
    last_document_id: str | None = None


class SingleConnectorYield(BaseModel):
    documents: list[Document]
    checkpoint: MockConnectorCheckpoint
    failures: list[ConnectorFailure]
    unhandled_exception: str | None = None


class MockConnector(CheckpointedConnectorWithPermSync[MockConnectorCheckpoint]):
    def __init__(
        self,
        mock_server_host: str,
        mock_server_port: int,
    ) -> None:
        self.mock_server_host = mock_server_host
        self.mock_server_port = mock_server_port
        self.client = httpx.Client(timeout=30.0)

        self.connector_yields: list[SingleConnectorYield] | None = None
        self.current_yield_index: int = 0

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        response = self.client.get(self._get_mock_server_url("get-documents"))
        response.raise_for_status()
        data = response.json()

        self.connector_yields = [
            SingleConnectorYield(**yield_data) for yield_data in data
        ]
        return None

    def _get_mock_server_url(self, endpoint: str) -> str:
        return f"http://{self.mock_server_host}:{self.mock_server_port}/{endpoint}"

    def _save_checkpoint(self, checkpoint: MockConnectorCheckpoint) -> None:
        response = self.client.post(
            self._get_mock_server_url("add-checkpoint"),
            json=checkpoint.model_dump(mode="json"),
        )
        response.raise_for_status()

    def _load_from_checkpoint_common(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: MockConnectorCheckpoint,
        include_permissions: bool = False,
    ) -> CheckpointOutput[MockConnectorCheckpoint]:
        if self.connector_yields is None:
            raise ValueError("No connector yields configured")

        # Save the checkpoint to the mock server
        self._save_checkpoint(checkpoint)

        yield_index = self.current_yield_index
        self.current_yield_index += 1
        current_yield = self.connector_yields[yield_index]

        # If the current yield has an unhandled exception, raise it
        # This is used to simulate an unhandled failure in the connector.
        if current_yield.unhandled_exception:
            raise RuntimeError(current_yield.unhandled_exception)

        # yield all documents
        for document in current_yield.documents:
            # If permissions are requested and not already set, add mock permissions
            if include_permissions and document.external_access is None:
                # Add mock permissions - make documents accessible to specific users/groups
                document.external_access = ExternalAccess(
                    external_user_emails=EXTERNAL_USER_EMAILS,
                    external_user_group_ids=EXTERNAL_USER_GROUP_IDS,
                    is_public=False,
                )
            yield document

        for failure in current_yield.failures:
            yield failure

        return current_yield.checkpoint

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: MockConnectorCheckpoint,
    ) -> CheckpointOutput[MockConnectorCheckpoint]:
        return self._load_from_checkpoint_common(
            start, end, checkpoint, include_permissions=False
        )

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: MockConnectorCheckpoint,
    ) -> CheckpointOutput[MockConnectorCheckpoint]:
        return self._load_from_checkpoint_common(
            start, end, checkpoint, include_permissions=True
        )

    @override
    def build_dummy_checkpoint(self) -> MockConnectorCheckpoint:
        return MockConnectorCheckpoint(
            has_more=True,
            last_document_id=None,
        )

    def validate_checkpoint_json(self, checkpoint_json: str) -> MockConnectorCheckpoint:
        return MockConnectorCheckpoint.model_validate_json(checkpoint_json)
