import os
from unittest.mock import patch, MagicMock
import pytest
from sqlalchemy.orm import Session

from onyx.connectors.file.connector import LocalFileConnector
from onyx.connectors.models import Document, TextSection
from onyx.configs.constants import DocumentSource
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
        
        documents = file_connector.process_file(test_file_path, mock_db_session)
        
        assert len(documents) == 3
        
        # Verify each document has the correct page number in its reference
        for idx, doc in enumerate(documents, 1):
            assert isinstance(doc, Document)
            assert doc.id == f"{test_file_path}#page={idx}"
            assert len(doc.sections) == 1
            assert isinstance(doc.sections[0], TextSection)
            assert doc.sections[0].text == f"Page {idx} content"
            assert doc.sections[0].page_number == idx

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
        
        documents = file_connector.process_file(test_file_path, mock_db_session)
        
        assert len(documents) == 1
        assert isinstance(documents[0], Document)
        assert documents[0].id == test_file_path  # No page number
        assert len(documents[0].sections) == 1
        assert isinstance(documents[0].sections[0], TextSection)
        assert documents[0].sections[0].text == test_content
        assert documents[0].sections[0].page_number is None

def test_get_source_link_with_page_number():
    connector = LocalFileConnector([])
    
    # Test PDF file with page number
    doc = Document(
        id="document.pdf#page=5",
        sections=[TextSection(text="content", page_number=5)],
        source=DocumentSource.FILE,
        semantic_identifier="document.pdf",
        metadata={}
    )
    link = connector.get_source_link(doc)
    assert link == "file://document.pdf#page=5"
    
    # Test non-PDF file (backward compatibility)
    doc = Document(
        id="document.txt",
        sections=[TextSection(text="content")],
        source=DocumentSource.FILE,
        semantic_identifier="document.txt",
        metadata={}
    )
    link = connector.get_source_link(doc)
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
        
        documents = file_connector.process_file(test_file_path, mock_db_session)
        
        assert len(documents) == 1
        assert documents[0].id == "test file with spaces.pdf#page=1"
        link = file_connector.get_source_link(documents[0])
        assert link == "file://test%20file%20with%20spaces.pdf#page=1" 