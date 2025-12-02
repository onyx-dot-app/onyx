from collections.abc import Callable
from datetime import datetime

import pytest

from onyx.connectors.coda.connector import CodaConnector
from onyx.connectors.coda.connector import CodaDoc
from onyx.connectors.coda.connector import CodaPage
from onyx.connectors.coda.connector import CodaPageReference


@pytest.fixture
def coda_api_token() -> str:
    """Mock API token for testing"""
    return "test_coda_api_token_12345"


@pytest.fixture
def coda_connector(coda_api_token: str) -> CodaConnector:
    """Create a Coda connector for testing with mocked credentials"""
    connector = CodaConnector(batch_size=5)
    connector.load_credentials({"coda_api_token": coda_api_token})
    return connector


@pytest.fixture
def create_mock_doc() -> Callable[..., CodaDoc]:
    """Helper to create mock CodaDoc objects"""

    def _create_mock_doc(
        id: str = "doc-123",
        name: str = "Test Doc",
        updated: str = "2023-01-01T12:00:00.000Z",
        owner: str = "test@example.com",
        owner_name: str = "Test User",
    ) -> CodaDoc:
        """Create a mock Coda doc object"""
        return CodaDoc(
            id=id,
            type="doc",
            href=f"https://coda.io/apis/v1/docs/{id}",
            browserLink=f"https://coda.io/d/{id}",
            name=name,
            owner=owner,
            ownerName=owner_name,
            createdAt="2023-01-01T00:00:00.000Z",
            updatedAt=updated,
        )

    return _create_mock_doc


@pytest.fixture
def create_mock_page() -> Callable[..., CodaPage]:
    """Helper to create mock CodaPage objects"""

    def _create_mock_page(
        id: str = "page-123",
        name: str = "Test Page",
        updated: str = "2023-01-01T12:00:00.000Z",
        is_hidden: bool = False,
        parent_id: str | None = None,
    ) -> CodaPage:
        """Create a mock Coda page object"""
        page_dict = CodaPage(
            id=id,
            type="page",
            href=f"https://coda.io/apis/v1/pages/{id}",
            browserLink=f"https://coda.io/d/_d/page/{id}",
            name=name,
            subtitle=None,
            icon=None,
            image=None,
            contentType="canvas",
            isHidden=is_hidden,
            createdAt="2023-01-01T00:00:00.000Z",
            updatedAt=updated,
            parent=None,
            children=[],
        )

        if parent_id:
            page_dict.parent = CodaPageReference(
                id=parent_id,
                type="page",
                href=f"https://coda.io/apis/v1/pages/{parent_id}",
                browserLink=f"https://coda.io/d/_d/page/{parent_id}",
                name="Parent Page",
            )

        return page_dict

    return _create_mock_page


@pytest.fixture
def mock_timestamp() -> Callable[[str], datetime]:
    """Helper to create datetime objects from ISO strings"""

    def _mock_timestamp(iso_string: str) -> datetime:
        return datetime.fromisoformat(iso_string.replace("Z", "+00:00"))

    return _mock_timestamp
