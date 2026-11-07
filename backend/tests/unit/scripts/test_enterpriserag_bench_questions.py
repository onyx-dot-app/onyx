"""Answer benchmarks require observed retrieval, not only a tool preference."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from scripts.run_enterpriserag_bench_questions import QuestionRecord, submit_question


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "called_tool,search_completed",
    [
        (None, False),
        ("web_search", True),
        ("internal_search", True),
        ("internal_search", False),
    ],
)
async def test_answer_requires_internal_search(
    called_tool: str | None, search_completed: bool
) -> None:
    response = {
        "answer": "Answer",
        "citation_info": [],
        "tool_calls": [
            {"tool_name": called_tool, "search_docs": [] if search_completed else None}
        ]
        if called_tool
        else [],
    }
    with patch(
        "scripts.run_enterpriserag_bench_questions.request_json_with_retries",
        new_callable=AsyncMock,
        return_value=response,
    ) as request:
        operation = submit_question(
            session=MagicMock(spec=aiohttp.ClientSession),
            api_base="http://localhost:3000/api",
            headers={},
            internal_search_tool_id=1,
            question_record=QuestionRecord(question_id="question", question="Question"),
        )
        if called_tool == "internal_search" and search_completed:
            result = await operation
            assert result.answer == "Answer"
            assert result.document_ids == []
        else:
            with pytest.raises(RuntimeError, match="did not complete internal search"):
                await operation
        request.assert_awaited_once()
