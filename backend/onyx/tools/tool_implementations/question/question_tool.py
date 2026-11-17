"""The question tool: the root chat agent asks the user multiple-choice
questions and waits for the answers (onyx/chat/tool_questions.py)."""

from uuid import UUID

from onyx.agents.tools import PendingToolInput, ToolInvocation
from onyx.chat.tool_questions import open_tool_question
from onyx.llm.models import ToolDefinition
from onyx.prompts.question_tool import QUESTION_TOOL_DESCRIPTION
from onyx.tools.interface import (
    Tool,
    parse_tool_arguments,
    tool_definition_from_arguments,
)
from onyx.tools.models import CodeModeExposure, ToolCallException, ToolContext
from onyx.tools.tool_implementations.question.models import (
    MAX_QUESTIONS_BYTES,
    QuestionArguments,
)
from onyx.utils.postgres_sanitization import sanitize_json_like


class QuestionTool(Tool):
    """A response's question tool. `name` depends on the model family; a
    restored run keeps the name that its saved step declared."""

    id = None
    code_mode_exposure = CodeModeExposure.DIRECT
    display_name = "Ask User Question"
    description = QUESTION_TOOL_DESCRIPTION

    def __init__(
        self,
        name: str,
        *,
        tenant_id: str,
        chat_session_id: UUID,
        response_id: int,
    ) -> None:
        self._name = name
        self.tenant_id = tenant_id
        self.chat_session_id = chat_session_id
        self.response_id = response_id

    @property
    def name(self) -> str:
        return self._name

    def tool_definition(self) -> ToolDefinition:
        # Not strict: the nested question models are `$defs` references.
        return tool_definition_from_arguments(
            self.name, self.description, QuestionArguments
        )

    def _run(
        self,
        invocation: ToolInvocation,
        context: ToolContext,  # noqa: ARG002
    ) -> PendingToolInput:
        arguments = parse_tool_arguments(QuestionArguments, invocation.arguments)
        # The card shows the call's arguments and the row saves them
        # sanitized, so both must be the same text.
        shown = arguments.model_dump(mode="json")
        if sanitize_json_like(shown) != shown:
            raise ToolCallException(
                "Questions contain characters that cannot be saved.",
                "Remove NUL characters and invalid Unicode from the questions "
                "and call the tool again.",
            )
        if len(arguments.model_dump_json().encode()) > MAX_QUESTIONS_BYTES:
            raise ToolCallException(
                f"Questions exceed {MAX_QUESTIONS_BYTES} bytes.",
                f"The questions can have at most {MAX_QUESTIONS_BYTES} bytes. "
                "Shorten them and call the tool again.",
            )
        questions = arguments.questions
        if len({question.id for question in questions}) < len(questions):
            raise ToolCallException(
                "Question IDs repeat.",
                "Give each question a unique id and call the tool again.",
            )
        return open_tool_question(
            tenant_id=self.tenant_id,
            chat_session_id=self.chat_session_id,
            response_id=self.response_id,
            tool_call_id=invocation.call_id,
            display_name=self.display_name,
            questions=questions,
        )
