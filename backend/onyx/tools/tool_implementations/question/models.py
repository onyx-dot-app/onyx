"""Arguments, answers and result details of the question tool (question_tool.py)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from onyx.db.enums import QuestionAnsweredVia, QuestionOutcome

MAX_QUESTIONS = 3
MAX_QUESTIONS_BYTES = 8 * 1024
MAX_QUESTION_HEADER_CHARS = 12


class ToolQuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, description="The choice, in 1-5 words.")
    description: str = Field(
        description="One sentence on what the choice means or changes."
    )


class ToolQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Unique snake_case ID that the answers use.",
    )
    header: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_HEADER_CHARS,
        description=f"Short label, at most {MAX_QUESTION_HEADER_CHARS} characters.",
    )
    question: str = Field(min_length=1, description="One sentence for the user.")
    options: list[ToolQuestionOption] = Field(
        min_length=2,
        max_length=3,
        description="2-3 exclusive choices; put the recommended one first.",
    )


class QuestionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[ToolQuestion] = Field(min_length=1, max_length=MAX_QUESTIONS)


class ToolQuestionAnswer(BaseModel):
    """The user's answer to one question: a listed option, a note, or both."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    option_label: str | None = None
    user_note: str | None = None


class QuestionToolDetails(BaseModel):
    """How the user answered a question call: `answers` from the card, or the
    `message` that the user typed in the chat instead."""

    type: Literal["question"] = "question"
    outcome: QuestionOutcome
    answered_via: QuestionAnsweredVia | None = None
    answers: list[ToolQuestionAnswer] | None = None
    message: str | None = None
