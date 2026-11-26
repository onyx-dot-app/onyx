"""The question tool: the root chat agent asks the user multiple-choice
questions and waits for the answers (onyx/chat/tool_questions.py)."""

from uuid import UUID

from onyx.agents.tools import PendingToolInput, ToolInvocation
from onyx.chat.tool_questions import open_tool_question
from onyx.llm.models import ToolDefinition
from onyx.tools.interface import (
    Tool,
    parse_tool_arguments,
    tool_definition_from_arguments,
)
from onyx.tools.models import CodeModeExposure, ToolCallException, ToolContext
from onyx.tools.ordering import ToolRank
from onyx.tools.tool_implementations.question.models import MAX_QUESTIONS_BYTES
from onyx.tools.tool_implementations.question.shapes import QuestionShape
from onyx.utils.postgres_sanitization import sanitize_json_like


class QuestionTool(Tool):
    """A response's question tool, in the shape of the family of the model
    that runs the response (`QUESTION_SHAPES`), also when a restored run
    continues with another model."""

    rank = ToolRank.QUESTION

    id = None
    code_mode_exposure = CodeModeExposure.DIRECT
    display_name = "Ask User Question"

    def __init__(
        self,
        shape: QuestionShape,
        *,
        tenant_id: str,
        chat_session_id: UUID,
        response_id: int,
    ) -> None:
        self._shape = shape
        self.tenant_id = tenant_id
        self.chat_session_id = chat_session_id
        self.response_id = response_id

    @property
    def name(self) -> str:
        return self._shape.name

    @property
    def description(self) -> str:
        return self._shape.description

    def tool_definition(self) -> ToolDefinition:
        # Not strict: the nested question models are `$defs` references.
        return tool_definition_from_arguments(
            self.name, self.description, self._shape.arguments
        )

    def _run(
        self,
        invocation: ToolInvocation,
        context: ToolContext,  # noqa: ARG002
    ) -> PendingToolInput:
        questions = parse_tool_arguments(
            self._shape.arguments, invocation.arguments
        ).request()
        # The card shows the questions and the row saves them sanitized, so
        # both must be the same text.
        shown = [question.model_dump(mode="json") for question in questions]
        if sanitize_json_like(shown) != shown:
            raise ToolCallException(
                "Questions contain characters that cannot be saved.",
                "Remove NUL characters and invalid Unicode from the questions "
                "and call the tool again.",
            )
        if (
            sum(len(question.model_dump_json().encode()) for question in questions)
            > MAX_QUESTIONS_BYTES
        ):
            raise ToolCallException(
                f"Questions exceed {MAX_QUESTIONS_BYTES} bytes.",
                f"The questions can have at most {MAX_QUESTIONS_BYTES} bytes. "
                "Shorten them and call the tool again.",
            )
        return open_tool_question(
            tenant_id=self.tenant_id,
            chat_session_id=self.chat_session_id,
            response_id=self.response_id,
            tool_call_id=invocation.call_id,
            display_name=self.display_name,
            questions=questions,
        )
