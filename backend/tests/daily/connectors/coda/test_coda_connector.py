import os
import time
from collections.abc import Generator
from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.coda.connector import CodaConnector
from onyx.connectors.exceptions import CredentialInvalidError
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode


def connector_doc_generator(
    connector: CodaConnector,
) -> Generator[Document, None, None]:
    for batch in connector.load_from_state():
        for doc in batch:
            if isinstance(doc, HierarchyNode):
                continue
            yield doc


@pytest.fixture
def coda_credentials() -> dict[str, str]:
    """Fixture to get and validate Coda credentials."""
    bearer_token = os.environ.get("CODA_BEARER_TOKEN")

    if not bearer_token:
        pytest.skip("CODA_BEARER_TOKEN not set")

    return {
        "coda_bearer_token": bearer_token,
    }


@pytest.fixture
def connector(coda_credentials: dict[str, str]) -> CodaConnector:
    """Fixture to create and authenticate connector."""
    conn = CodaConnector(batch_size=5, index_page_content=True)
    conn.load_credentials(coda_credentials)
    return conn


@pytest.fixture
def workspace_scoped_connector(coda_credentials: dict[str, str]) -> CodaConnector:
    """Fixture to create connector scoped to a specific workspace (if CODA_WORKSPACE_ID is set)."""
    workspace_id = os.environ.get("CODA_WORKSPACE_ID")
    if not workspace_id:
        pytest.skip("CODA_WORKSPACE_ID not set - skipping workspace-scoped tests")

    conn = CodaConnector(
        batch_size=5, index_page_content=True, workspace_id=workspace_id
    )
    conn.load_credentials(coda_credentials)
    return conn


@pytest.fixture
def reference_data(connector: CodaConnector) -> dict[str, Any]:
    """Fixture to fetch reference data from API for validation."""
    all_docs = connector._list_all_docs()

    if not all_docs:
        pytest.skip("No docs found in Coda workspace")

    expected_page_count = 0
    expected_table_count = 0
    pages_by_doc = {}
    tables_by_doc = {}

    for doc in all_docs:
        doc_id = doc.id

        try:
            pages = connector._list_pages_in_doc(doc_id)
            pages_by_doc[doc_id] = pages
            expected_page_count += len(pages)
        except Exception as e:
            print(f"Warning: Could not fetch pages for doc {doc_id}: {e}")
            pages_by_doc[doc_id] = []

        try:
            tables = connector._list_tables(doc_id)
            tables_by_doc[doc_id] = tables
            expected_table_count += len(tables)
        except Exception as e:
            print(f"Warning: Could not fetch tables for doc {doc_id}: {e}")
            tables_by_doc[doc_id] = []

    total_expected_documents = expected_page_count + expected_table_count

    if total_expected_documents == 0:
        pytest.skip("No pages or tables found in Coda workspace")

    return {
        "docs": all_docs,
        "total_pages": expected_page_count,
        "total_tables": expected_table_count,
        "total_documents": total_expected_documents,
        "pages_by_doc": pages_by_doc,
        "tables_by_doc": tables_by_doc,
    }


class TestCodaConnectorValidation:
    """Test suite for connector validation and credential handling."""

    def test_validate_connector_settings_success(
        self, connector: CodaConnector
    ) -> None:
        """Test that validate_connector_settings succeeds with valid credentials."""
        # Should not raise any exceptions
        connector.validate_connector_settings()

    def test_validate_workspace_scoped_connector(
        self, workspace_scoped_connector: CodaConnector
    ) -> None:
        """Test that workspace-scoped connector validates successfully."""
        workspace_scoped_connector.validate_connector_settings()

    def test_load_credentials_invalid_token(self) -> None:
        """Test that invalid credentials are rejected."""
        conn = CodaConnector()

        with pytest.raises(CredentialInvalidError):
            conn.load_credentials(
                {
                    "coda_bearer_token": "invalid_token_12345",
                }
            )


class TestLoadFromState:
    """Test suite for load_from_state functionality."""

    def test_returns_generator(self, connector: CodaConnector) -> None:
        """Test that load_from_state returns a generator."""
        gen = connector.load_from_state()
        assert isinstance(gen, Generator), "load_from_state should return a Generator"

    def test_batch_sizes_respect_config(
        self, connector: CodaConnector, reference_data: dict[str, Any]
    ) -> None:
        """Test that batches respect the configured batch_size."""
        batch_size = connector.batch_size
        gen = connector.load_from_state()

        batch_sizes = []
        for batch in gen:
            batch_sizes.append(len(batch))
            assert (
                len(batch) <= batch_size
            ), f"Batch size {len(batch)} exceeds configured {batch_size}"

        for i, size in enumerate(batch_sizes[:-1]):
            assert (
                size == batch_size
            ), f"Non-final batch {i} has size {size}, expected {batch_size}"

        # Last batch may be smaller or equal
        if batch_sizes:
            assert batch_sizes[-1] <= batch_size

    def test_document_count_matches_expected(
        self, connector: CodaConnector, reference_data: dict[str, Any]
    ) -> None:
        """Test that total documents match expected pages + tables."""
        gen = connector.load_from_state()

        total_documents = sum(len(batch) for batch in gen)
        expected_count = reference_data["total_documents"]

        assert total_documents == expected_count, (
            f"Expected {expected_count} documents "
            f"({reference_data['total_pages']} pages + "
            f"{reference_data['total_tables']} tables) "
            f"but got {total_documents}"
        )

    def test_document_required_fields(
        self, connector: CodaConnector, reference_data: dict[str, Any]
    ) -> None:
        """Test that all documents have required fields with valid values."""
        gen = connector.load_from_state()

        for batch in gen:
            for doc in batch:
                assert isinstance(doc, Document)

                assert doc.id is not None, "Document ID should not be None"
                assert doc.id.startswith(
                    "coda-"
                ), "Document ID should start with 'coda-'"
                assert (
                    doc.source == DocumentSource.CODA
                ), "Document source should be CODA"
                assert (
                    doc.semantic_identifier is not None
                ), "Semantic identifier should not be None"
                assert (
                    doc.doc_updated_at is not None
                ), "doc_updated_at should not be None"

                assert (
                    len(doc.sections) > 0
                ), "Document should have at least one section"
                for section in doc.sections:
                    assert section.text is not None, "Section text should not be None"
                    assert len(section.text) > 0, "Section text should not be empty"
                    assert section.link is not None, "Section link should not be None"
                    assert section.link.startswith(
                        "https://"
                    ), "Section link should be a valid URL"

                assert "doc_id" in doc.metadata, "Metadata should contain doc_id"
                assert (
                    "browser_link" in doc.metadata
                ), "Metadata should contain browser_link"

    def test_document_types(
        self, connector: CodaConnector, reference_data: dict[str, Any]
    ) -> None:
        """Test that both page and table documents are generated correctly."""
        page_docs = []
        table_docs = []

        for doc in connector_doc_generator(connector):
            if "coda-page-" in doc.id:
                page_docs.append(doc)
                assert "content_type" in doc.metadata
            elif "coda-table-" in doc.id:
                table_docs.append(doc)
                assert "row_count" in doc.metadata

        # Verify we found both types (if both exist in the workspace)
        if reference_data["total_pages"] > 0:
            assert len(page_docs) > 0, "Should have found page documents"

        if reference_data["total_tables"] > 0:
            assert len(table_docs) > 0, "Should have found table documents"

        # Verify counts match
        assert (
            len(page_docs) == reference_data["total_pages"]
        ), f"Expected {reference_data['total_pages']} page documents, got {len(page_docs)}"
        assert (
            len(table_docs) == reference_data["total_tables"]
        ), f"Expected {reference_data['total_tables']} table documents, got {len(table_docs)}"

    def test_no_duplicate_documents(
        self, connector: CodaConnector, reference_data: dict[str, Any]
    ) -> None:
        """Test that no documents are yielded twice."""
        document_ids = []
        for doc in connector_doc_generator(connector):
            document_ids.append(doc.id)

        unique_ids = set(document_ids)
        assert len(document_ids) == len(
            unique_ids
        ), f"Found {len(document_ids) - len(unique_ids)} duplicate documents"

    def test_all_docs_processed(
        self, connector: CodaConnector, reference_data: dict[str, Any]
    ) -> None:
        """Test that content from all docs are included."""
        processed_doc_ids = set()
        for doc in connector_doc_generator(connector):
            doc_id = doc.metadata.get("doc_id")
            processed_doc_ids.add(doc_id)

        expected_doc_ids = {doc.id for doc in reference_data["docs"]}

        expected_doc_ids_with_content = {
            doc_id
            for doc_id in expected_doc_ids
            if len(reference_data["pages_by_doc"].get(doc_id, [])) > 0
            or len(reference_data["tables_by_doc"].get(doc_id, [])) > 0
        }

        assert (
            processed_doc_ids == expected_doc_ids_with_content
        ), f"Not all docs with content were processed. Expected {expected_doc_ids_with_content}, got {processed_doc_ids}"

    def test_document_content_not_empty(
        self, connector: CodaConnector, reference_data: dict[str, Any]
    ) -> None:
        """Test that all documents have meaningful content."""
        for doc in connector_doc_generator(connector):
            assert doc.semantic_identifier, "Semantic identifier should not be empty"
            assert (
                len(doc.semantic_identifier) > 0
            ), "Semantic identifier should have content"

            total_text_length = sum(len(section.text or "") for section in doc.sections)
            assert total_text_length > 0, f"Document {doc.id} has no content"

    def test_page_content_indexing(self, coda_credentials: dict[str, str]) -> None:
        """Test that index_page_content flag works correctly."""
        # page indexing disabled
        conn_no_content = CodaConnector(batch_size=5, index_page_content=False)
        conn_no_content.load_credentials(coda_credentials)

        # page indexing enabled
        conn_with_content = CodaConnector(batch_size=5, index_page_content=True)
        conn_with_content.load_credentials(coda_credentials)

        docs_no_content = []
        for batch in conn_no_content.load_from_state():
            for doc in batch:
                if isinstance(doc, HierarchyNode):
                    continue
                if "coda-page-" in doc.id:
                    docs_no_content.append(doc)
                    break
            if docs_no_content:
                break

        docs_with_content = []
        for batch in conn_with_content.load_from_state():
            for doc in batch:
                if isinstance(doc, HierarchyNode):
                    continue
                if "coda-page-" in doc.id:
                    docs_with_content.append(doc)
                    break
            if docs_with_content:
                break

        if docs_no_content and docs_with_content:
            no_content_length = sum(
                len(s.text or "") for s in docs_no_content[0].sections
            )
            with_content_length = sum(
                len(s.text or "") for s in docs_with_content[0].sections
            )

            assert (
                with_content_length >= no_content_length
            ), "Content-indexed page should have at least as much text as non-indexed"


class TestPollSource:
    """Test suite for poll_source functionality."""

    def test_poll_source_returns_generator(self, connector: CodaConnector) -> None:
        """Test that poll_source returns a generator."""
        current_time = time.time()
        start_time = current_time - 86400  # 24 hours

        gen = connector.poll_source(start_time, current_time)
        assert isinstance(gen, Generator), "poll_source should return a Generator"

    def test_poll_source_recent_updates(self, connector: CodaConnector) -> None:
        """Test polling for recently updated documents."""
        current_time = time.time()
        start_time = current_time - (86400 * 30)

        gen = connector.poll_source(start_time, current_time)

        documents = []
        for batch in gen:
            documents.extend(batch)

        # All returned documents should be updated within the time range
        for doc in documents:
            if isinstance(doc, HierarchyNode):
                continue
            assert doc.doc_updated_at is not None, "doc_updated_at should not be None"
            doc_timestamp = doc.doc_updated_at.timestamp()
            assert (
                start_time < doc_timestamp <= current_time
            ), f"Document {doc.id} updated at {doc_timestamp} is outside range [{start_time}, {current_time}]"

    def test_poll_source_no_updates_in_range(self, connector: CodaConnector) -> None:
        """Test polling with a time range that has no updates."""
        end_time = time.time() - (86400 * 365)  # 1 year ago
        start_time = end_time - 86400  # 1 day before that

        gen = connector.poll_source(start_time, end_time)

        documents = []
        for batch in gen:
            documents.extend(batch)

        # Should return no documents (unless workspace is very old)
        print(f"Found {len(documents)} documents updated over a year ago")
        assert len(documents) == 0

    def test_poll_source_batch_sizes(self, connector: CodaConnector) -> None:
        """Test that poll_source respects batch sizes."""
        current_time = time.time()
        start_time = current_time - (86400 * 30)

        batch_size = connector.batch_size
        gen = connector.poll_source(start_time, current_time)

        for batch in gen:
            assert (
                len(batch) <= batch_size
            ), f"Batch size {len(batch)} exceeds configured {batch_size}"


class TestWorkspaceScoping:
    """Test suite for workspace_id scoping functionality."""

    def test_workspace_scoped_loads_subset(
        self,
        connector: CodaConnector,
        workspace_scoped_connector: CodaConnector,
        reference_data: dict[str, Any],
    ) -> None:
        """Test that workspace-scoped connector loads a subset of documents."""
        all_docs = []
        for batch in connector.load_from_state():
            all_docs.extend(batch)

        scoped_docs = []
        for batch in workspace_scoped_connector.load_from_state():
            scoped_docs.extend(batch)

        # Scoped should be <= all docs
        assert len(scoped_docs) <= len(
            all_docs
        ), "Workspace-scoped connector should return same or fewer documents"

        workspace_id = workspace_scoped_connector.workspace_id
        for doc in scoped_docs:
            if isinstance(doc, HierarchyNode):
                continue
            doc_id = doc.metadata.get("doc_id")
            assert isinstance(doc_id, str), "doc_id should be a string"
            coda_doc = workspace_scoped_connector._get_doc(doc_id)
            assert (
                coda_doc.workspace_id == workspace_id
            ), f"Document {doc_id} has workspace {coda_doc.workspace_id}, expected {workspace_id}"


class TestErrorHandling:
    """Test suite for error handling and edge cases."""

    def test_handles_missing_page_content_gracefully(
        self, connector: CodaConnector
    ) -> None:
        """Test that connector handles pages without accessible content."""
        gen = connector.load_from_state()

        documents = []
        for batch in gen:
            documents.extend(batch)

        assert (
            len(documents) > 0
        ), "Should yield documents even if some content is inaccessible"

    def test_handles_empty_tables_gracefully(self, connector: CodaConnector) -> None:
        """Test that connector handles tables with no rows."""
        for doc in connector_doc_generator(connector):
            if "coda-table-" in doc.id:
                assert len(doc.sections) > 0, "Empty table should still have a section"
                if doc.metadata.get("row_count") == "0":
                    assert (
                        len(doc.sections) == 1
                    ), "Empty table should have exactly one section"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
