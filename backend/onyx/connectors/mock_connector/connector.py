from typing import Any

import httpx
from pydantic import BaseModel

from onyx.connectors.interfaces import CheckpointConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger


logger = setup_logger()


class SingleConnectorYield(BaseModel):
    documents: list[Document]
    checkpoint: ConnectorCheckpoint
    failures: list[ConnectorFailure]
    unhandled_exception: str | None = None


class MockConnector(CheckpointConnector):
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

    def _save_checkpoint(self, checkpoint: ConnectorCheckpoint) -> None:
        response = self.client.post(
            self._get_mock_server_url("add-checkpoint"),
            json=checkpoint.model_dump(mode="json"),
        )
        response.raise_for_status()

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ConnectorCheckpoint,
    ) -> CheckpointOutput:
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
            yield document

        for failure in current_yield.failures:
            yield failure

        return current_yield.checkpoint
