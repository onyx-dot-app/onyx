from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel
from pydantic import field_validator

from onyx.tools.tool_implementations.open_url.snippet_matcher import (
    find_snippet_in_content,
)

"""
We want to store tests in the json file in the following format:
{
    "categories": [
        {
            "category":  "...",
            "tests": [
                {
                    "name": "...",
                    "content": "... or ["...", "..."] where each item is a new line",
                    "snippet": "..." or ["...", "..."] where each item is a new line,
                    "expected_result": {
                        "snippet_located": true,
                        "expected_start_idx": 0,
                        "expected_end_idx": 10
                    },
                    "allow_buffer": false (Optional,  default: true)
                },
                ...
            ]
        },
        ...
    ]
}
"""

TEST_DATA_FILE_PATH = Path(__file__).parent / "data" / "test_snippet_finding_data.json"


class TestSchemaResult(BaseModel):
    """
    Expected results from the snippet matcher.
    """

    snippet_located: bool

    # Don't include if snippet_located is False
    expected_start_idx: int = -1
    expected_end_idx: int = -1


class TestSchema(BaseModel):
    """
    A test takes in some content and a snippet.

    Expected result is what we expect the output to be.
    """

    name: str
    content: str
    snippet: str

    expected_result: TestSchemaResult
    allow_buffer: bool = True

    @field_validator("content", "snippet", mode="before")
    @classmethod
    def convert_list_to_string(cls, v: str | list[str]) -> str:
        """
        We want to be able to handle strings or list of strings for content and snippet.
        The client should only see strings though, so we do some parsing here.
        """
        if isinstance(v, list):
            return "\n".join(v)
        return v


class TestCategory(BaseModel):
    """
    A category of tests.
    """

    category: str
    tests: list[TestSchema]


class TestDataFile(BaseModel):
    """
    The root structure of the test data JSON file.
    """

    categories: list[TestCategory]


def load_all_tests() -> list[tuple[str, TestSchema]]:
    """
    Loads all tests from the JSON file and returns them as a list of tuples.

    Each tuple contains (test_id, test_data) where test_id is "{category}_{name}".
    """
    with open(TEST_DATA_FILE_PATH, "r") as file:
        data = json.load(file)

    # Validate the entire file structure using Pydantic
    test_data = TestDataFile.model_validate(data)

    # Collect all tests with their category-prefixed names
    all_tests: list[tuple[str, TestSchema]] = []
    for category in test_data.categories:
        for test in category.tests:
            test_id = f"{category.category}_{test.name}"
            all_tests.append((test_id, test))

    return all_tests


# Load tests at module level for parametrization
_ALL_TESTS = load_all_tests()


@pytest.mark.parametrize(
    "test_data",
    [test for _, test in _ALL_TESTS],
    ids=[test_id for test_id, _ in _ALL_TESTS],
)
def test_snippet_finding(test_data: TestSchema) -> None:
    """
    Tests the snippet matching functionality.

    Each test case is defined in the JSON file and named {category}_{name}.
    """
    result = find_snippet_in_content(test_data.content, test_data.snippet)

    assert result.snippet_located == test_data.expected_result.snippet_located, (
        f"snippet_located mismatch: expected {test_data.expected_result.snippet_located}, "
        f"got {result.snippet_located}"
    )

    # If buffer is allowed, we let the start and end indices be within 10 characters of where we expect
    BUFFER_SIZE = 10 if test_data.allow_buffer else 0

    assert (
        test_data.expected_result.expected_start_idx - BUFFER_SIZE
        <= result.start_idx
        <= test_data.expected_result.expected_start_idx + BUFFER_SIZE
    ), (
        f"start_idx mismatch: expected {test_data.expected_result.expected_start_idx}, "
        f"got {result.start_idx}"
    )
    assert (
        test_data.expected_result.expected_end_idx - BUFFER_SIZE
        <= result.end_idx
        <= test_data.expected_result.expected_end_idx + BUFFER_SIZE
    ), (
        f"end_idx mismatch: expected {test_data.expected_result.expected_end_idx}, "
        f"got {result.end_idx}"
    )
