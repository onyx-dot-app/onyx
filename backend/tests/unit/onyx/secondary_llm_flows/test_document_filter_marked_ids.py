from unittest.mock import MagicMock

import pytest

from onyx.llm.interfaces import LLM
from onyx.secondary_llm_flows.document_filter import select_sections_for_expansion
from tests.unit.onyx.secondary_llm_flows.test_document_filter import (
    _make_section,
)


@pytest.mark.parametrize(
    ("response_text", "expected_indices", "expected_full_document_ids"),
    [
        ("0!, 2!, 1!, 4", [0, 2, 1, 4], ["doc-0", "doc-2", "doc-1"]),
        ("[0!, 2!, 1!, 4]", [0, 2, 1, 4], ["doc-0", "doc-2", "doc-1"]),
        ("0, 2, 1, 4", [0, 2, 1, 4], None),
        ("[0, 2, 1, 4]", [0, 2, 1, 4], None),
        ("Section IDs: [3, 0!, 1]", [3, 0, 1], ["doc-0"]),
        ("0!, 2!, 1!, 4.", [0, 2, 1, 4], ["doc-0", "doc-2", "doc-1"]),
        ("1, 2, 3abc", [1, 2], None),
        ("0!, 2!.", [0, 2], ["doc-0", "doc-2"]),
        ("1!!, 2", [2], None),
        ("1st, 2nd", [0, 1, 2, 3, 4], None),
        ("", [0, 1, 2, 3, 4], None),
    ],
)
def test_select_sections_parses_complete_marked_and_unmarked_lists(
    response_text: str,
    expected_indices: list[int],
    expected_full_document_ids: list[str] | None,
) -> None:
    sections = [_make_section(index) for index in range(5)]
    response = MagicMock()
    response.text = response_text
    llm = MagicMock(spec=LLM)
    llm.invoke = MagicMock(return_value=response)

    selected, full_document_ids = select_sections_for_expansion(
        sections=sections,
        user_query="query",
        llm=llm,
        max_sections=5,
    )

    assert [sections.index(section) for section in selected] == expected_indices
    assert full_document_ids == expected_full_document_ids
