"""Card answers keep each chosen option once, in the question's order."""

from onyx.chat.tool_questions import card_answers
from onyx.tools.tool_implementations.question.models import (
    ToolQuestion,
    ToolQuestionAnswer,
    ToolQuestionOption,
)


def test_a_saved_question_with_repeated_labels_keeps_one_choice() -> None:
    question = ToolQuestion(
        id="cadence",
        header="Cadence",
        question="How often?",
        options=[
            ToolQuestionOption(label="Weekly", description="Once a week."),
            ToolQuestionOption(label="Weekly", description="Every Monday."),
            ToolQuestionOption(label="Daily", description="Every day."),
        ],
    )
    [answer] = card_answers(
        [question],
        [ToolQuestionAnswer(question_id="cadence", option_labels=["Weekly"])],
    )
    assert answer.option_labels == ["Weekly"]
