"""
Craft File Connector for Onyx Craft.

This connector handles raw binary file uploads (xlsx, pptx, docx, csv, etc.)
that are stored directly in S3 WITHOUT text extraction.

Key differences from LocalFileConnector:
- Does NOT extract text from files
- Stores raw binary files directly to S3
- Uses RAW_BINARY processing mode
- Agent reads files with Python libraries (openpyxl, python-pptx, etc.)

Files are stored at:
    s3://{bucket}/{tenant_id}/knowledge/{user_id}/user_library/{path}

And synced to sandbox at:
    /workspace/files/user_library/{path}

Note: Sync enable/disable is managed via document metadata (sync_disabled field),
not via connector config. The _get_disabled_user_library_paths() function in
tasks.py queries the database for disabled files during sandbox sync.
"""

from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CraftFileConnector(LoadConnector):
    """
    Connector for raw binary files in Onyx Craft.

    Unlike LocalFileConnector which extracts text from files, this connector
    preserves raw binary files for direct access by the sandbox agent.

    The actual file upload happens via API endpoints, not through the
    standard connector indexing flow. This connector exists primarily to:
    1. Provide a valid connector entry for document table relationships
    2. Enable RAW_BINARY processing mode in the indexing pipeline
    """

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """
        Initialize the CraftFileConnector.

        Args:
            batch_size: Number of documents to yield per batch (unused for raw files).
            **kwargs: Extra parameters (ignored, for compatibility with connector config).
        """
        self.batch_size = batch_size

    def load_credentials(
        self, credentials: dict[str, Any]  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """
        Load credentials for the connector.

        Craft files don't require external credentials since files are
        uploaded directly by authenticated users. Returns None.
        """
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        """
        Load documents from the current state.

        For CraftFileConnector, documents are managed via API endpoints.
        This method yields no documents since uploads go directly to S3
        and are tracked in the document table by the API.
        """
        # Craft files are uploaded via API, not fetched by connector
        yield from ()
