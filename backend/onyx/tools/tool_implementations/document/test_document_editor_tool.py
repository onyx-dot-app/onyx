"""Tests for the document editor tool."""

import json
from unittest.mock import MagicMock

import pytest
from dotenv import load_dotenv

from onyx.llm.chat_llm import DefaultMultiLLM
from onyx.tools.tool_implementations.document.document_editor_tool import (
    DocumentEditorTool,
)
from onyx.tools.tool_implementations.document.test_constants import (
    LARGE_DOCUMENT,
    SAMPLE_DOCUMENT,
    SAMPLE_INSTRUCTIONS,
    WORD_REPLACEMENT_INSTRUCTIONS,
    get_default_llm,
)

# Load environment variables for end-to-end tests
load_dotenv()


@pytest.fixture
def mock_llm():
    """Create a mock LLM for testing."""
    llm = MagicMock(spec=DefaultMultiLLM)
    # Mock the invoke method to return a structured response
    llm.invoke.return_value.content = """
    {
        "changes": [
            {
                "type": "deletion",
                "context_before": "<h1>",
                "context_after": "</h1>",
                "text_to_delete": "Sample Document",
                "text_to_add": ""
            },
            {
                "type": "addition",
                "context_before": "<h1>",
                "context_after": "</h1>",
                "text_to_delete": "",
                "text_to_add": "Modified Article"
            },
            {
                "type": "addition",
                "context_before": "</p>",
                "context_after": "</body>",
                "text_to_delete": "",
                "text_to_add": "<p>This is a new paragraph.</p>"
            }
        ],
        "summary": "Modified title and added new paragraph"
    }
    """
    return llm


@pytest.fixture
def document_editor(mock_llm):
    """Create a document editor instance with mocked dependencies."""
    return DocumentEditorTool(llm=mock_llm, document_content=SAMPLE_DOCUMENT)


def test_basic_document_editing(document_editor):
    """Test basic document editing functionality."""
    # Run the document editor
    responses = list(
        document_editor.run(instructions=SAMPLE_INSTRUCTIONS, search_results="")
    )

    # Get the result from the response
    result = responses[0].response

    # Verify the result
    assert result["success"] is True
    assert result["edited"] is True
    assert "Modified Article" in result["edited_text"]
    assert "This is a new paragraph" in result["edited_text"]
    assert result["original_text"] == SAMPLE_DOCUMENT


@pytest.mark.e2e
def test_end_to_end_document_editing():
    """End-to-end test using the actual LLM."""
    # Initialize the real LLM
    llm = get_default_llm()

    # Create the document editor with real LLM
    editor = DocumentEditorTool(llm=llm, document_content=SAMPLE_DOCUMENT)

    # Run the document editor with more specific instructions
    specific_instructions = """
    1. Change the title to "Modified Article"
    2. Add a new paragraph after the first paragraph
    3. Remove the third list item
    """

    try:
        # Run the document editor
        responses = list(
            editor.run(instructions=specific_instructions, search_results="")
        )

        # Get the result from the response
        result = responses[0].response

        # Print the result for debugging
        print("\nResult:", json.dumps(result, indent=2))

        # Verify the result
        assert result["success"] is True
        assert result["edited"] is True
        assert result["original_text"] == SAMPLE_DOCUMENT

        # Check for specific changes
        edited_text = result["edited_text"]
        assert (
            "<h1><addition-mark>Modified Article</addition-mark><deletion-mark>Sample Document</deletion-mark></h1>"
            in edited_text
        ), (
            "Modified Article not found in edited text with correct addition and deletion marks"
        )
        assert (
            "<addition-mark><p>This is a new paragraph.</p></addition-mark>"
            in edited_text
        ), "New paragraph not found in edited text with correct addition mark"

    except Exception as e:
        print(f"\nError occurred: {str(e)}")
        print(f"Error type: {type(e)}")
        if hasattr(e, "__cause__"):
            print(f"Caused by: {str(e.__cause__)}")
        raise


@pytest.mark.e2e
def test_find_and_modify_single_word():
    """Test finding and modifying a single word in a larger document using the real LLM."""
    # Initialize the real LLM
    llm = get_default_llm()

    # Create the document editor with real LLM
    editor = DocumentEditorTool(llm=llm, document_content=LARGE_DOCUMENT)

    try:
        # Run the document editor
        responses = list(
            editor.run(instructions=WORD_REPLACEMENT_INSTRUCTIONS, search_results="")
        )

        # Get the result from the response
        result = responses[0].response

        # Print the result for debugging
        print("\nResult:", json.dumps(result, indent=2))

        # Verify the result
        assert result["success"] is True
        assert result["edited"] is True
        assert result["original_text"] == LARGE_DOCUMENT

        # Check that all instances of "plastic" were changed to "metal"
        edited_text = result["edited_text"]
        # Verify specific changes
        assert "<deletion-mark>plastic</deletion-mark>" in edited_text
        assert "<addition-mark>metal</addition-mark>" in edited_text

        # Verify the context of changes
        assert (
            "high-quality <addition-mark>metal</addition-mark><deletion-mark>plastic</deletion-mark> components"
            in edited_text
        )

    except Exception as e:
        print(f"\nError occurred: {str(e)}")
        print(f"Error type: {type(e)}")
        if hasattr(e, "__cause__"):
            print(f"Caused by: {str(e.__cause__)}")
        raise
