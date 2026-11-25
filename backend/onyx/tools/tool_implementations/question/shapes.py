"""The question tool's shape in each tool family: its name, the arguments
that the model sends, and the description with the arguments' limits. Each
shape's `request()` gives the same `ToolQuestion` list (models.py)."""

from collections.abc import Mapping
from typing import NamedTuple

from annotated_types import MaxLen
from pydantic import BaseModel, ConfigDict, Field, model_validator

from onyx.llm.model_capabilities import ToolFamily
from onyx.prompts.question_tool import QUESTION_TOOL_DESCRIPTION
from onyx.tools.constants import (
    ASK_USER_QUESTION_TOOL_NAME,
    REQUEST_USER_INPUT_TOOL_NAME,
)
from onyx.tools.interface import ToolArguments
from onyx.tools.tool_implementations.question.models import (
    MAX_QUESTION_HEADER_CHARS,
    ToolQuestion,
    ToolQuestionOption,
)

HEADER_DESCRIPTION = f"Short label, at most {MAX_QUESTION_HEADER_CHARS} characters."
MULTI_SELECT_DESCRIPTION = (
    "True when more than one option can apply, so the user can choose "
    "several; false when the options are exclusive."
)


class QuestionOptionArgument(ToolQuestionOption):
    # Keys that the model adds, such as `preview`, are ignored.
    model_config = ConfigDict(extra="ignore")


class RequestUserInputQuestion(BaseModel):
    id: str = Field(
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Unique snake_case ID that the answers use.",
    )
    header: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_HEADER_CHARS,
        description=HEADER_DESCRIPTION,
    )
    question: str = Field(min_length=1, description="One sentence for the user.")
    options: list[QuestionOptionArgument] = Field(
        min_length=2,
        max_length=3,
        description="2-3 choices; put the recommended one first.",
    )
    multi_select: bool = Field(default=False, description=MULTI_SELECT_DESCRIPTION)


class RequestUserInputArguments(ToolArguments[list[ToolQuestion]]):
    """The OpenAI shape: each question names the ID that its answer uses."""

    questions: list[RequestUserInputQuestion] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_ids(self) -> "RequestUserInputArguments":
        if len({question.id for question in self.questions}) < len(self.questions):
            raise ValueError("Give each question a unique id.")
        return self

    def request(self) -> list[ToolQuestion]:
        return [
            ToolQuestion(
                id=question.id,
                header=question.header,
                question=question.question,
                options=[
                    ToolQuestionOption(
                        label=option.label, description=option.description
                    )
                    for option in question.options
                ],
                multi_select=question.multi_select,
            )
            for question in self.questions
        ]


class AskUserQuestionItem(BaseModel):
    question: str = Field(min_length=1, description="One sentence for the user.")
    header: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_HEADER_CHARS,
        description=HEADER_DESCRIPTION,
    )
    options: list[QuestionOptionArgument] = Field(
        min_length=2,
        max_length=4,
        description="2-4 choices; put the recommended one first.",
    )
    multiSelect: bool = Field(default=False, description=MULTI_SELECT_DESCRIPTION)


class AskUserQuestionArguments(ToolArguments[list[ToolQuestion]]):
    """The shape Claude models are trained on: questions carry no ID, so the
    answers name each question by its text. Keys that the model adds, such as
    `answers` or `metadata`, are ignored."""

    questions: list[AskUserQuestionItem] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def unique_texts(self) -> "AskUserQuestionArguments":
        texts = [question.question for question in self.questions]
        if len(set(texts)) < len(texts):
            raise ValueError("Give each question a different `question` text.")
        return self

    def request(self) -> list[ToolQuestion]:
        return [
            ToolQuestion(
                id=question.question,
                header=question.header,
                question=question.question,
                options=[
                    ToolQuestionOption(
                        label=option.label, description=option.description
                    )
                    for option in question.options
                ],
                multi_select=question.multiSelect,
            )
            for question in self.questions
        ]


def _max_length(model: type[BaseModel], field: str) -> int:
    return next(
        item.max_length
        for item in model.model_fields[field].metadata
        if isinstance(item, MaxLen)
    )


class QuestionShape(NamedTuple):
    """How one tool family names and asks the question tool."""

    name: str
    arguments: type[ToolArguments[list[ToolQuestion]]]
    # The tool description, with the shape's limits.
    description: str


QUESTION_SHAPES: Mapping[ToolFamily, QuestionShape] = {
    ToolFamily.OPENAI: QuestionShape(
        name=REQUEST_USER_INPUT_TOOL_NAME,
        arguments=RequestUserInputArguments,
        description=QUESTION_TOOL_DESCRIPTION.format(
            max_questions=_max_length(RequestUserInputArguments, "questions"),
            max_options=_max_length(RequestUserInputQuestion, "options"),
            answer_keys="question ID",
        ),
    ),
    ToolFamily.CLAUDE: QuestionShape(
        name=ASK_USER_QUESTION_TOOL_NAME,
        arguments=AskUserQuestionArguments,
        description=QUESTION_TOOL_DESCRIPTION.format(
            max_questions=_max_length(AskUserQuestionArguments, "questions"),
            max_options=_max_length(AskUserQuestionItem, "options"),
            answer_keys="question text",
        ),
    ),
}
# The shapes by tool name: a chat's history can hold calls of every shape,
# and a saved call carries only its name.
QUESTION_SHAPES_BY_NAME: Mapping[str, QuestionShape] = {
    shape.name: shape for shape in QUESTION_SHAPES.values()
}
QUESTION_TOOL_NAMES = frozenset(QUESTION_SHAPES_BY_NAME)
