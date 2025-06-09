import os
from unittest.mock import patch, MagicMock
import pytest
from sqlalchemy.orm import Session

from onyx.connectors.file.connector import LocalFileConnector
from onyx.connectors.file.models import FileSource
from onyx.file_processing.extract_file_text import extract_text_and_images

@pytest.fixture
def file_connector():
    return LocalFileConnector([])

@pytest.fixture
def mock_db_session():
    return MagicMock(spec=Session)

def test_process_file_pdf_with_page_numbers(file_connector, mock_db_session):
    test_file_path = "test.pdf"
    test_content = b"%PDF-1.4"
    
    mock_file = MagicMock()
    mock_file.read.return_value = test_content
    
    with patch("builtins.open", return_value=mock_file), \
         patch("onyx.connectors.file.connector.extract_text_and_images") as mock_extract:
        
        mock_ex        # Mock the text extraction to return page-specific chunks
tract.return_value = (
            "Combined text",
            [],  # No images
            [
                ("Page 1 content", 1),
                ("Page 2 content", 2),
                ("Page 3 content", 3),
            ]
        )
        
        sources = file_connector.process_file(test_file_path, mock_db_session)
        
        assert len(sources) == 3
        
        # Verify each source has the correct page number in its reference
        for idx, source in enumerate(sources, 1):
            assert isinstance(source, FileSource)
            assert source.reference == f"{test_file_path}#page={idx}"
            assert source.content == f"Page {idx} content"

def test_process_file_non_pdf_backward_compatibility(file_connector, mock_db_session):
    test_file_path = "test.txt"
    test_content = "Some text content"
    
    mock_file = MagicMock()
    mock_file.read.return_value = test_content.encode()
    
    with patch("builtins.open", return_value=mock_file), \
         patch("onyx.connectors.file.connector.extract_text_and_images") as mock_extract:
        
        # Mock text extraction without page numbers for non-PDF
        mock_extract.return_value = (
            test_content,
            [],  # No images
            []   # No chunks (non-PDF behavior)
        )
        
        sources = file_connector.process_file(test_file_path, mock_db_session)
        
        assert len(sources) == 1
        assert isinstance(sources[0], FileSource)
        assert sources[0].reference == test_file_path  # No page number
        assert sources[0].content == test_content

def test_get_source_link_with_page_number():
    connector = LocalFileConnector([])
    
    # Test PDF file with page number
    source = FileSource(reference="document.pdf#page=5")
    link = connector.get_source_link(source)
    assert link == "file://document.pdf#page=5"
    
    # Test non-PDF file (backward compatibility)
    source = FileSource(reference="document.txt")
    link = connector.get_source_link(source)
    assert link == "file://document.txt"

def test_process_file_with_spaces_and_special_chars(file_connector, mock_db_session):
    test_file_path = "test file with spaces.pdf"
    test_content = b"%PDF-1.4"
    
    mock_file = MagicMock()
    mock_file.read.return_value = test_content
    
    with patch("builtins.open", return_value=mock_file), \
         patch("onyx.connectors.file.connector.extract_text_and_images") as mock_extract:
        
        mock_extract.return_value = (
            "Test content",
            [],
            [("Page 1 content", 1)]
        )
        
        sources = file_connector.process_file(test_file_path, mock_db_session)
        
        assert len(sources) == 1
        assert sources[0].reference == "test file with spaces.pdf#page=1"
        link = file_connector.get_source_link(sources[0])
        assert link == "file://test%20file%20with%20spaces.pdf#page=1" 