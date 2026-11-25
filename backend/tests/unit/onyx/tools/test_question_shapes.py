"""The question tool's shapes: Claude's shape names its questions, and each
shape's description states the limits of its arguments."""

import pytest
from pydantic import ValidationError

from onyx.llm.model_capabilities import ToolFamily
from onyx.tools.tool_implementations.question.shapes import (
    QUESTION_SHAPES,
    AskUserQuestionArguments,
)


def test_claude_questions_are_named_by_their_text() -> None:
    options = [
        {"label": "Team", "description": "Only the team."},
        {"label": "Company", "description": "Everyone."},
    ]
    question = {"header": "Scope", "question": "Who should get it?", "options": options}
    [asked] = AskUserQuestionArguments.model_validate(
        {"questions": [question]}
    ).request()
    assert asked.id == "Who should get it?"
    with pytest.raises(ValidationError, match="different `question` text"):
        AskUserQuestionArguments.model_validate({"questions": [question, question]})


def test_each_shape_describes_its_own_limits() -> None:
    assert QUESTION_SHAPES[ToolFamily.CLAUDE].description.startswith(
        "Ask the user 1-4 short"
    )
    assert QUESTION_SHAPES[ToolFamily.OPENAI].description.startswith(
        "Ask the user 1-3 short"
    )
    assert "Give each question 2-4 options" in (
        QUESTION_SHAPES[ToolFamily.CLAUDE].description
    )


@pytest.mark.parametrize("family", list(ToolFamily))
def test_each_shape_rejects_repeated_option_labels(family: ToolFamily) -> None:
    options = [
        {"label": "Weekly", "description": "Once a week."},
        {"label": "Weekly", "description": "Every Monday."},
    ]
    question = {
        "id": "cadence",
        "header": "Cadence",
        "question": "How often?",
        "options": options,
    }
    with pytest.raises(ValidationError, match="different label"):
        QUESTION_SHAPES[family].arguments.model_validate({"questions": [question]})
