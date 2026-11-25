"""The question tool's questions, answers and result details
(question_tool.py). Each tool family's arguments (shapes.py) normalize into
the same questions, which the card shows and the row saves."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from onyx.db.enums import QuestionAnsweredVia, QuestionOutcome

MAX_QUESTIONS_BYTES = 8 * 1024
MAX_QUESTION_HEADER_CHARS = 12


class ToolQuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, description="The choice, in 1-5 words.")
    description: str = Field(
        description="One sentence on what the choice means or changes."
    )


class ToolQuestion(BaseModel):
    """One question as the card shows it and the row saves it, whatever
    shape asked it. Each shape limits its questions within these bounds. `id`
    names the question in the answers and in the result that the model
    reads: a snake_case ID, or the question text for Claude's shape."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    header: str = Field(min_length=1, max_length=MAX_QUESTION_HEADER_CHARS)
    question: str = Field(min_length=1)
    options: list[ToolQuestionOption] = Field(min_length=2, max_length=4)
    multi_select: bool = False


class ToolQuestionAnswer(BaseModel):
    """The user's answer to one question: its chosen options, a note, or
    both. A single-select question has at most one chosen option."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    option_labels: list[str] = Field(default_factory=list)
    user_note: str | None = None


class QuestionToolDetails(BaseModel):
    """How the user answered a question call: `answers` from the card, or the
    `message` that the user typed in the chat instead."""

    type: Literal["question"] = "question"
    outcome: QuestionOutcome
    answered_via: QuestionAnsweredVia | None = None
    answers: list[ToolQuestionAnswer] | None = None
    message: str | None = None
