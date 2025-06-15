"""Tests for the document editor tool."""

import json
import os
from datetime import datetime
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
    TABLE_DOCUMENT,
    WORD_REPLACEMENT_INSTRUCTIONS,
    get_default_llm,
    get_test_document_editor,
)

# Load environment variables for end-to-end tests
load_dotenv()


def output_test_case_details(
    test_name, instructions, original_text, edited_text, error=None, verbose=False
):
    """Output test case details to both stdout and a file for debugging.

    Args:
        test_name: Name of the test case
        instructions: Instructions given to the document editor
        original_text: Original document text
        edited_text: Edited document text
        error: Optional error message if the test failed
        verbose: If True, output to stdout in a pipe-friendly format
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = "test_failures"
    os.makedirs(output_dir, exist_ok=True)

    # Create a detailed output string for file
    file_output = f"""
Test Case: {test_name}
Timestamp: {timestamp}
{"=" * 80}

Instructions:
{instructions}

{"=" * 80}

Original Document:
{original_text}

{"=" * 80}

Edited Document:
{edited_text}

{"=" * 80}
"""
    if error:
        file_output += f"""
Error:
{str(error)}
"""

    # Write to file
    filename = f"{output_dir}/{test_name}_{timestamp}.txt"
    with open(filename, "w") as f:
        f.write(file_output)

    # If verbose is True, output to stdout in a pipe-friendly format
    if verbose:
        stdout_output = {
            "test_name": test_name,
            "timestamp": timestamp,
            "instructions": instructions,
            "original_text": original_text,
            "edited_text": edited_text,
            "error": str(error) if error else None,
            "output_file": filename,
        }
        print(json.dumps(stdout_output, indent=2))
    else:
        print(f"\nDetailed output saved to: {filename}")


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
    return get_test_document_editor(mock_llm)


def test_basic_document_editing(document_editor):
    """Test basic document editing functionality."""
    # Run the document editor
    responses = list(
        document_editor.run(
            instructions=SAMPLE_INSTRUCTIONS, search_results="", document_id="sample"
        )
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
    editor = get_test_document_editor(llm)

    try:
        # Run the document editor
        responses = list(
            editor.run(
                instructions=SAMPLE_INSTRUCTIONS,
                search_results="",
                document_id="sample",
            )
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

    except Exception as e:
        output_test_case_details(
            "test_end_to_end_document_editing",
            SAMPLE_INSTRUCTIONS,
            SAMPLE_DOCUMENT,
            result["edited_text"]
            if "result" in locals()
            else "No edited text available",
            error=e,
            verbose=False,
        )
        raise


@pytest.mark.e2e
def test_find_and_modify_single_word():
    """Test finding and modifying a single word in a larger document using the real LLM."""
    # Initialize the real LLM
    llm = get_default_llm()

    # Create the document editor with real LLM
    editor = DocumentEditorTool(llm=llm, documents={"large": LARGE_DOCUMENT})

    try:
        # Run the document editor
        responses = list(
            editor.run(
                instructions=WORD_REPLACEMENT_INSTRUCTIONS,
                search_results="",
                document_id="large",
            )
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
        output_test_case_details(
            "test_find_and_modify_single_word",
            WORD_REPLACEMENT_INSTRUCTIONS,
            LARGE_DOCUMENT,
            result["edited_text"]
            if "result" in locals()
            else "No edited text available",
            error=e,
            verbose=False,
        )
        raise


@pytest.mark.e2e
def test_find_and_modify_single_word_in_table():
    """Test finding and modifying a single word in a larger document using the real LLM."""
    # Initialize the real LLM
    llm = get_default_llm()

    # Create the document editor with real LLM
    editor = DocumentEditorTool(llm=llm, documents={"table": TABLE_DOCUMENT})

    table_instructions = "Update PRD 3.11 to PRD 4.0"
    try:
        # Run the document editor
        responses = list(
            editor.run(
                instructions=table_instructions, search_results="", document_id="table"
            )
        )

        # Get the result from the response
        result = responses[0].response

        # Print the result for debugging
        print("\nResult:", json.dumps(result, indent=2))

        # Verify the result
        assert result["success"] is True
        assert result["edited"] is True
        assert result["original_text"] == TABLE_DOCUMENT

        # Check that all instances of "plastic" were changed to "metal"
        edited_text = result["edited_text"]
        # Verify specific changes
        assert "<deletion-mark>3.11</deletion-mark>" in edited_text
        assert "<addition-mark>4.0</addition-mark>" in edited_text

    except Exception as e:
        output_test_case_details(
            "test_find_and_modify_single_word_in_table",
            table_instructions,
            TABLE_DOCUMENT,
            result["edited_text"]
            if "result" in locals()
            else "No edited text available",
            error=e,
            verbose=True,
        )
        raise
