import io
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.file_processing.extract_file_text import (
    extract_text_and_images,
    is_text_file,
    is_text_file_extension,
    read_pdf_file,
)

def test_is_text_file_extension():
    assert is_text_file_extension("test.txt")
    assert is_text_file_extension("test.md")
    assert not is_text_file_extension("test.pdf")
    assert not is_text_file_extension("test.docx")

def test_is_text_file():
    text_content = "This is a text file"
    text_file = io.BytesIO(text_content.encode())
    assert is_text_file(text_file)

    binary_content = bytes([0x89, 0x50, 0x4E, 0x47])
    binary_file = io.BytesIO(binary_content)
    assert not is_text_file(binary_file)

def test_read_pdf_file_with_page_tracking():
    pdf_content = b"%PDF-1.4\n..." 
    pdf_file = io.BytesIO(pdf_content)

    mock_pages = [
        MagicMock(extract_text=lambda: "Page 1 content"),
        MagicMock(extract_text=lambda: "Page 2 content"),
        MagicMock(extract_text=lambda: "Page 3 content"),
    ]
    
    with patch("onyx.file_processing.extract_file_text.PdfReader") as mock_pdf_reader:
        mock_pdf_reader.return_value.pages = mock_pages
        mock_pdf_reader.return_value.metadata = None
        mock_pdf_reader.return_value.is_encrypted = False

        text, metadata, images, text_chunks = read_pdf_file(pdf_file)
        
        assert "Page 1 content" in text
        assert "Page 2 content" in text
        assert "Page 3 content" in text
        
        assert len(text_chunks) == 3
        assert text_chunks[0] == ("Page 1 content", 1)
        assert text_chunks[1] == ("Page 2 content", 2)
        assert text_chunks[2] == ("Page 3 content", 3)

def test_extract_text_and_images_pdf_with_pages():
    pdf_file = io.BytesIO(b"%PDF-1.4")
    
    with patch("onyx.file_processing.extract_file_text.get_file_ext") as mock_get_ext, \
         patch("onyx.file_processing.extract_file_text.read_pdf_file") as mock_read_pdf, \
         patch("onyx.file_processing.extract_file_text.get_unstructured_api_key", return_value=None):
        
        mock_get_ext.return_value = ".pdf"
        mock_read_pdf.return_value = (
            "Combined text",  
            {},  
            [],  
            [  
                ("Page 1 content", 1),
                ("Page 2 content", 2),
                ("Page 3 content", 3),
            ]
        )
        
        text, images, chunks = extract_text_and_images(pdf_file, "test.pdf")
        
        assert text == "Combined text"  
        assert images == []
        assert len(chunks) == 3
        assert chunks[0] == ("Page 1 content", 1)
        assert chunks[1] == ("Page 2 content", 2)
        assert chunks[2] == ("Page 3 content", 3)

def test_extract_text_and_images_non_pdf_backward_compatibility():
    text_file = io.BytesIO(b"Some text content")
    
    with patch("onyx.file_processing.extract_file_text.get_file_ext") as mock_get_ext, \
         patch("onyx.file_processing.extract_file_text.is_text_file_extension") as mock_is_text, \
         patch("onyx.file_processing.extract_file_text.detect_encoding") as mock_detect_encoding, \
         patch("onyx.file_processing.extract_file_text.read_text_file") as mock_read_text, \
         patch("onyx.file_processing.extract_file_text.get_unstructured_api_key", return_value=None):
        
        mock_get_ext.return_value = ".txt"
        mock_is_text.return_value = True
        mock_detect_encoding.return_value = "utf-8"
        mock_read_text.return_value = ("Some text content", {})
        
        text, images, chunks = extract_text_and_images(text_file, "test.txt")
        
        assert text == "Some text content"
        assert images == []
        assert chunks == [] 