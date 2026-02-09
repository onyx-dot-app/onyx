from typing import Any
from typing import cast
from uuid import UUID

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.file_store.utils import load_user_file
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.utils.logger import setup_logger

logger = setup_logger()

FILE_ID_FIELD = "file_id"
START_CHAR_FIELD = "start_char"
NUM_CHARS_FIELD = "num_chars"

MAX_NUM_CHARS = 4000
DEFAULT_NUM_CHARS = MAX_NUM_CHARS


class FileReaderToolOverrideKwargs:
    """No override kwargs needed for the file reader tool."""


class FileReaderTool(Tool[FileReaderToolOverrideKwargs]):
    NAME = "read_file"
    DISPLAY_NAME = "File Reader"
    DESCRIPTION = (
        "Read a section of a user-uploaded file by character offset. "
        "Returns up to 4000 characters starting from the given offset."
    )

    def __init__(
        self,
        tool_id: int,
        emitter: Emitter,
        available_file_ids: list[UUID],
    ) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._available_file_ids = available_file_ids

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

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:  # noqa: ARG003
        return True

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        FILE_ID_FIELD: {
                            "type": "string",
                            "description": "The UUID of the file to read.",
                        },
                        START_CHAR_FIELD: {
                            "type": "integer",
                            "description": (
                                "Character offset to start reading from. Defaults to 0."
                            ),
                        },
                        NUM_CHARS_FIELD: {
                            "type": "integer",
                            "description": (
                                "Number of characters to return (max 4000). "
                                "Defaults to 4000."
                            ),
                        },
                    },
                    "required": [FILE_ID_FIELD],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CustomToolStart(tool_name=self.DISPLAY_NAME),
            )
        )

    def _validate_file_id(self, raw_file_id: str) -> UUID:
        try:
            file_id = UUID(raw_file_id)
        except ValueError:
            raise ToolCallException(
                message=f"Invalid file_id: {raw_file_id}",
                llm_facing_message=f"'{raw_file_id}' is not a valid file UUID.",
            )

        if file_id not in self._available_file_ids:
            raise ToolCallException(
                message=f"File {file_id} not in available files",
                llm_facing_message=(
                    f"File '{file_id}' is not available. "
                    "Please use one of the file IDs listed in the context."
                ),
            )

        return file_id

    def run(
        self,
        placement: Placement,  # noqa: ARG002
        override_kwargs: FileReaderToolOverrideKwargs,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        if FILE_ID_FIELD not in llm_kwargs:
            raise ToolCallException(
                message=f"Missing required '{FILE_ID_FIELD}' parameter",
                llm_facing_message=(
                    f"The read_file tool requires a '{FILE_ID_FIELD}' parameter. "
                    f'Example: {{"file_id": "abc-123", "start_char": 0, "num_chars": 4000}}'
                ),
            )

        raw_file_id = cast(str, llm_kwargs[FILE_ID_FIELD])
        file_id = self._validate_file_id(raw_file_id)
        start_char = max(0, int(llm_kwargs.get(START_CHAR_FIELD, 0)))
        num_chars = min(
            MAX_NUM_CHARS,
            max(1, int(llm_kwargs.get(NUM_CHARS_FIELD, DEFAULT_NUM_CHARS))),
        )

        with get_session_with_current_tenant() as db_session:
            chat_file = load_user_file(file_id, db_session)

        if not chat_file.file_type.is_text_file():
            raise ToolCallException(
                message=f"File {file_id} is not a text file (type={chat_file.file_type})",
                llm_facing_message=(
                    f"File '{chat_file.filename or file_id}' is a "
                    f"{chat_file.file_type.value} file and cannot be read as text."
                ),
            )

        try:
            full_text = chat_file.content.decode("utf-8", errors="replace")
        except Exception:
            raise ToolCallException(
                message=f"Failed to decode file {file_id}",
                llm_facing_message="The file could not be read as text.",
            )

        total_chars = len(full_text)
        end_char = min(start_char + num_chars, total_chars)
        section = full_text[start_char:end_char]

        has_more = end_char < total_chars
        header = (
            f"File: {chat_file.filename or file_id}\n"
            f"Characters {start_char}–{end_char} of {total_chars}"
        )
        if has_more:
            header += f" (use start_char={end_char} to continue reading)"

        llm_response = f"{header}\n\n{section}"

        return ToolResponse(
            rich_response=None,
            llm_facing_response=llm_response,
        )
