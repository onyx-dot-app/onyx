from __future__ import annotations

from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.coda.api.client import CodaAPIClient
from onyx.connectors.coda.helpers.document_generator import CodaDocumentGenerator
from onyx.connectors.coda.helpers.parser import CodaParser
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CodaConnector(LoadConnector, PollConnector):
    """Coda connector that reads all Coda docs and pages this integration has been granted access to.

    Responsibilities:
    - Orchestrating the retrieval, parsing, and generation pipeline
    - Managing configuration and credentials
    - Batching documents for output

    The actual work is delegated to:
    - CodaAPIClient: API communication
    - CodaParser: Data transformation
    - CodaDocumentGenerator: Document generation and filtering

    Arguments:
        batch_size (int): Number of objects to index in a batch
        doc_ids (list[str] | None): Specific doc IDs to index. If None, indexes all.
        max_table_rows (int): Maximum rows to fetch per table
        include_tables (bool): Whether to index table content
    """

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        doc_ids: list[str] | None = None,
        max_table_rows: int = 1000,
        include_tables: bool = True,
    ) -> None:
        """Initialize with parameters."""
        self.batch_size = batch_size
        self.doc_ids = set(doc_ids) if doc_ids else None
        self.max_table_rows = max_table_rows
        self.include_tables = include_tables

        # Clients initialized after credentials loaded
        self.client: CodaAPIClient | None = None
        self.parser: CodaParser | None = None
        self.generator: CodaDocumentGenerator | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Initialize API client and related components with credentials."""
        api_token = credentials["coda_api_token"]

        # Initialize components in dependency order
        self.client = CodaAPIClient(api_token)
        self.parser = CodaParser()
        self.generator = CodaDocumentGenerator(
            client=self.client,
            parser=self.parser,
            max_table_rows=self.max_table_rows,
        )

        return None

    def validate_connector_settings(self) -> None:
        """Verify credentials and API access."""
        if not self.client:
            raise ConnectorValidationError("Coda credentials not loaded.")
        self.client.validate_credentials()

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Loads all doc and page data from a Coda workspace.

        Returns:
            GenerateDocumentsOutput: Batched documents
        """
        if not self.generator:
            raise ConnectorValidationError("Generator not initialized.")

        documents = self.generator.generate_all_documents(
            doc_ids=self.doc_ids,
            include_tables=self.include_tables,
        )

        yield from batch_generator(documents, self.batch_size)

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Uses the Coda API to fetch updated docs and pages within a time period."""
        if not self.generator:
            raise ConnectorValidationError("Generator not initialized.")

        documents = self.generator.generate_updated_documents(
            start=start,
            end=end,
            doc_ids=self.doc_ids,
            include_tables=self.include_tables,
        )

        yield from batch_generator(documents, self.batch_size)


if __name__ == "__main__":
    import os

    connector = CodaConnector(
        doc_ids=(
            os.environ.get("CODA_DOC_IDS", "").split(",")
            if os.environ.get("CODA_DOC_IDS")
            else None
        )
    )
    connector.load_credentials({"coda_api_token": os.environ.get("CODA_API_TOKEN")})
    connector.validate_connector_settings()
    print("Coda connector validation successful!")
