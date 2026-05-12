from typing import Any

from pydantic import BaseModel
from pydantic import TypeAdapter
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.configs.app_configs import CODE_INTERPRETER_BASE_URL
from onyx.configs.app_configs import CODE_INTERPRETER_DEFAULT_TIMEOUT_MS
from onyx.configs.app_configs import CODE_INTERPRETER_MAX_OUTPUT_LENGTH
from onyx.db.code_interpreter import fetch_code_interpreter_server
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import BashToolDelta
from onyx.server.query_and_chat.streaming_models import BashToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterClient,
)
from onyx.tools.tool_implementations.utils import truncate_output as _truncate_output
from onyx.utils.logger import setup_logger

logger = setup_logger()

CMD_FIELD = "cmd"


class BashToolOverrideKwargs(BaseModel):
    pass


class LlmBashExecutionResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    error: str | None = None


class BashTool(Tool[BashToolOverrideKwargs]):
    """Bash command execution tool backed by a Code Interpreter session."""

    NAME = "bash"
    DISPLAY_NAME = "Bash"
    DESCRIPTION = (
        "Execute a bash command inside an isolated, network-restricted " "session."
    )

    def __init__(self, tool_id: int, session_id: str, emitter: Emitter) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._session_id = session_id

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @property
    def session_id(self) -> str:
        return self._session_id

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """Available only when the code-interpreter is configured, healthy,
        AND the deployed service version supports the session/bash routes.

        Mirrors ``PythonTool.is_available`` for the env / DB / health checks,
        plus a ``client.supports(...)`` capability gate so an outdated
        code-interpreter deployment doesn't make this tool appear available
        when its underlying calls would be rejected by the version guard.
        """
        if not CODE_INTERPRETER_BASE_URL:
            return False
        server = fetch_code_interpreter_server(db_session)
        if not server.server_enabled:
            return False

        with CodeInterpreterClient() as client:
            if not client.health(use_cache=True).healthy:
                return False
            return client.supports(
                CodeInterpreterClient.create_session,
                CodeInterpreterClient.execute_bash_in_session,
                CodeInterpreterClient.delete_session,
            )

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        CMD_FIELD: {
                            "type": "string",
                            "description": "Bash command to execute in the session.",
                        },
                    },
                    "required": [CMD_FIELD],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        """Emit start packet for this tool. Code will be emitted in run() method."""
        # cmd isn't available until run(); BashToolStart is emitted there,
        # mirroring PythonTool's pattern.

    def run(
        self,
        placement: Placement,
        override_kwargs: BashToolOverrideKwargs,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        if CMD_FIELD not in llm_kwargs:
            raise ToolCallException(
                message=f"Missing required '{CMD_FIELD}' parameter in bash tool call",
                llm_facing_message=(
                    f"The bash tool requires a '{CMD_FIELD}' parameter containing "
                    f"the bash command to execute. Please provide like: "
                    f'{{"cmd": "ls -la"}}'
                ),
            )
        cmd = llm_kwargs[CMD_FIELD]
        if not isinstance(cmd, str):
            raise ToolCallException(
                message=(
                    f"'{CMD_FIELD}' must be a string in bash tool call, "
                    f"got {type(cmd).__name__}"
                ),
                llm_facing_message=(
                    f"The bash tool requires '{CMD_FIELD}' to be a string "
                    f"(got {type(cmd).__name__}). Pass a single shell "
                    f'command, e.g. {{"cmd": "ls -la"}}.'
                ),
            )

        self.emitter.emit(
            Packet(placement=placement, obj=BashToolStart(cmd=cmd)),
        )

        adapter = TypeAdapter(LlmBashExecutionResult)

        try:
            with CodeInterpreterClient() as client:
                logger.debug("Executing bash in session %s: %s", self._session_id, cmd)
                response = client.execute_bash_in_session(
                    session_id=self._session_id,
                    cmd=cmd,
                    timeout_ms=CODE_INTERPRETER_DEFAULT_TIMEOUT_MS,
                )
        except Exception as e:
            logger.error("Bash execution failed: %s", e)
            error_msg = str(e)
            error_result = LlmBashExecutionResult(
                stdout="",
                stderr=error_msg,
                exit_code=-1,
                timed_out=False,
                error=error_msg,
            )
            self.emitter.emit(
                Packet(
                    placement=placement,
                    obj=BashToolDelta(
                        stdout="",
                        stderr=error_msg,
                        exit_code=-1,
                        timed_out=False,
                    ),
                ),
            )
            return ToolResponse(
                rich_response=None,
                llm_facing_response=adapter.dump_json(error_result).decode(),
            )

        truncated_stdout = _truncate_output(
            response.stdout, CODE_INTERPRETER_MAX_OUTPUT_LENGTH, "stdout"
        )
        truncated_stderr = _truncate_output(
            response.stderr, CODE_INTERPRETER_MAX_OUTPUT_LENGTH, "stderr"
        )

        result = LlmBashExecutionResult(
            stdout=truncated_stdout,
            stderr=truncated_stderr,
            exit_code=response.exit_code,
            timed_out=response.timed_out,
            error=(None if response.exit_code == 0 else truncated_stderr),
        )

        self.emitter.emit(
            Packet(
                placement=placement,
                obj=BashToolDelta(
                    stdout=truncated_stdout,
                    stderr=truncated_stderr,
                    exit_code=response.exit_code,
                    timed_out=response.timed_out,
                ),
            ),
        )

        return ToolResponse(
            rich_response=None,
            llm_facing_response=adapter.dump_json(result).decode(),
        )

    @classmethod
    @override
    def should_emit_argument_deltas(cls) -> bool:
        return True
