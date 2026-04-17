from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.jsm.connector import JsmConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.models import Document

def test_jsm_connector_source_override():
    """
    Test that JsmConnector correctly overrides the source of documents yielded 
    by the base JiraConnector.
    """
    mock_checkpoint = JiraConnectorCheckpoint()
    
    # Mock document that would be yielded by super().load_from_checkpoint
    mock_doc = Document(
        id="test-issue",
        sections=[],
        source=DocumentSource.JIRA,  # Base Jira source
        metadata={},
        semantic_identifier="TEST-1",
    )

    def mock_gen(*args, **kwargs):
        yield mock_doc
        return mock_checkpoint

    connector = JsmConnector(jira_base_url="https://test.atlassian.net")
    
    with patch("onyx.connectors.jira.connector.JiraConnector.load_from_checkpoint", side_effect=mock_gen):
        gen = connector.load_from_checkpoint(0, 100, mock_checkpoint)
        
        # Pull the document from the generator
        yielded_item = next(gen)
        
        assert yielded_item.id == "test-issue"
        # CRITICAL: Check that source was overridden to JIRA_SERVICE_MANAGEMENT
        assert yielded_item.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        
        # Check return value (checkpoint)
        try:
            next(gen)
        except StopIteration as e:
            assert e.value == mock_checkpoint

if __name__ == "__main__":
    test_jsm_connector_source_override()
    print("Test passed!")
