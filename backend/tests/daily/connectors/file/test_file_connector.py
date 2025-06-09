import os
from unittest.mock import patch, MagicMock
import pytest
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from onyx.connectors.file.connector import _process_file
from onyx.connectors.models import Document, TextSection
from onyx.configs.constants import DocumentSource
from onyx.file_processing.extract_file_text import extract_text_and_images

@pytest.fixture
def mock_db_session():
    return MagicMock(spec=Session)

def test_process_file_pdf_with_page_numbers(mock_db_session):
    test_file_path = "test.pdf"
    test_content = b"%PDF-1.4"
    
    mock_file = MagicMock()
    mock_file.read.return_value = test_content
    
    # Mock the PG file store record
    mock_pg_record = MagicMock()
    mock_pg_record.file_name = test_file_path
    
    with patch("onyx.connectors.file.connector.get_pgfilestore_by_file_name", return_value=mock_pg_record), \
         patch("onyx.connectors.file.connector.extract_text_and_images") as mock_extract:
        
        # Mock the text extraction to return page-specific chunks
        mock_extract.return_value = (
            "Combined text",
            [],  # No images
            [
                ("Page 1 content", 1),
                ("Page 2 content", 2),
                ("Page 3 content", 3),
            ]
        )
        
        documents = _process_file(
            file_name=test_file_path,
            file=mock_file,
            metadata={"link": "http://example.com/test.pdf"},
            pdf_pass=None,
            db_session=mock_db_session
        )
        
        assert len(documents) == 1
        doc = documents[0]
        assert isinstance(doc, Document)
        assert len(doc.sections) == 3
        
        # Verify each section has the correct page number in its link
        for idx, section in enumerate(doc.sections, 1):
            assert isinstance(section, TextSection)
            assert section.link == f"http://example.com/test.pdf#page={idx}"
            assert section.text == f"Page {idx} content"

def test_process_file_non_pdf_backward_compatibility(mock_db_session):
    test_file_path = "test.txt"
    test_content = "Some text content"
    
    mock_file = MagicMock()
    mock_file.read.return_value = test_content.encode()
    
    # Mock the PG file store record
    mock_pg_record = MagicMock()
    mock_pg_record.file_name = test_file_path
    
    with patch("onyx.connectors.file.connector.get_pgfilestore_by_file_name", return_value=mock_pg_record), \
         patch("onyx.connectors.file.connector.extract_text_and_images") as mock_extract:
        
        # Mock text extraction without page numbers for non-PDF
        mock_extract.return_value = (
            test_content,
            [],  # No images
            []   # No chunks (non-PDF behavior)
        )
        
        documents = _process_file(
            file_name=test_file_path,
            file=mock_file,
            metadata={"link": "http://example.com/test.txt"},
            pdf_pass=None,
            db_session=mock_db_session
        )
        
        assert len(documents) == 1
        doc = documents[0]
        assert isinstance(doc, Document)
        assert len(doc.sections) == 1
        assert isinstance(doc.sections[0], TextSection)
        assert doc.sections[0].link == "http://example.com/test.txt"  # No page number
        assert doc.sections[0].text == test_content

def test_process_file_with_spaces_and_special_chars(mock_db_session):
    test_file_path = "test file with spaces.pdf"
    test_content = b"%PDF-1.4"
    
    mock_file = MagicMock()
    mock_file.read.return_value = test_content
    
    # Mock the PG file store record
    mock_pg_record = MagicMock()
    mock_pg_record.file_name = test_file_path
    
    with patch("onyx.connectors.file.connector.get_pgfilestore_by_file_name", return_value=mock_pg_record), \
         patch("onyx.connectors.file.connector.extract_text_and_images") as mock_extract:
        
        mock_extract.return_value = (
            "Test content",
            [],
            [("Page 1 content", 1)]
        )
        
        documents = _process_file(
            file_name=test_file_path,
            file=mock_file,
            metadata={"link": "http://example.com/test file with spaces.pdf"},
            pdf_pass=None,
            db_session=mock_db_session
        )
        
        assert len(documents) == 1
        doc = documents[0]
        assert isinstance(doc, Document)
        assert len(doc.sections) == 1
        assert isinstance(doc.sections[0], TextSection)
        assert doc.sections[0].link == "http://example.com/test file with spaces.pdf#page=1"
        assert doc.sections[0].text == "Page 1 content" 