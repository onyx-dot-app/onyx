import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.gitbook.connector import GitbookConnector


@pytest.fixture
def gitbook_connector() -> GitbookConnector:
    connector = GitbookConnector(
        space_id=os.environ["GITBOOK_SPACE_ID"],
    )
    connector.load_credentials(
        {
            "gitbook_api_key": os.environ["GITBOOK_API_KEY"],
        }
    )
    return connector


def test_gitbook_connector_basic(gitbook_connector: GitbookConnector) -> None:
    doc_batch_generator = gitbook_connector.load_from_state()

    # Get first batch of documents
    doc_batch = next(doc_batch_generator)
    assert len(doc_batch) > 0

    # Verify first document structure
    doc = doc_batch[0]

    # Basic document properties
    assert doc.id.startswith("gitbook-")
    assert doc.semantic_identifier == "Acme Corp Internal Handbook"
    assert doc.source == DocumentSource.GITBOOK

    # Metadata checks
    assert "path" in doc.metadata
    assert "type" in doc.metadata
    assert "kind" in doc.metadata

    # Section checks
    assert len(doc.sections) == 1
    section = doc.sections[0]

    # Content specific checks
    content = section.text

    # Check for specific content elements
    assert "* Fruit Shopping List:" in content
    assert "> test quote it doesn't mean anything" in content

    # Check headings
    assert "# Heading 1" in content
    assert "## Heading 2" in content
    assert "### Heading 3" in content

    # Check task list
    assert "- [ ] Uncompleted Task" in content
    assert "- [x] Completed Task" in content

    # Check table content
    assert "| ethereum | 10 | 3000 |" in content
    assert "| bitcoin | 2 | 98000 |" in content

    # Check paragraph content
    assert "New York City comprises 5 boroughs" in content
    assert "Empire State Building" in content

    # Check code block (just verify presence of some unique code elements)
    assert "function fizzBuzz(n)" in content
    assert 'res.push("FizzBuzz")' in content

    assert section.link  # Should have a URL

    # Time-based polling test
    current_time = time.time()
    poll_docs = gitbook_connector.poll_source(0, current_time)
    poll_batch = next(poll_docs)
    assert len(poll_batch) > 0
