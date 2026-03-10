import json
from typing import Any
from typing import cast
from uuid import UUID

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import InMemoryChatFile
from onyx.file_store.utils import load_chat_file_by_id
from onyx.file_store.utils import load_user_file
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import FileReaderResult
from onyx.server.query_and_chat.streaming_models import FileReaderStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.utils.logger import setup_logger

logger = setup_logger()

FILE_ID_FIELD = "file_id"
START_CHAR_FIELD = "start_char"
NUM_CHARS_FIELD = "num_chars"

MAX_NUM_CHARS = 16000
DEFAULT_NUM_CHARS = MAX_NUM_CHARS
PREVIEW_CHARS = 500


class FileReaderToolOverrideKwargs:
    """No override kwargs needed for the file reader tool."""


class FileReaderTool(Tool[FileReaderToolOverrideKwargs]):
    NAME = "read_file"
    DISPLAY_NAME = "File Reader"
    DESCRIPTION = (
        "Read a section of a user-uploaded file by character offset. "
        "Returns up to 16000 characters starting from the given offset."
    )

    def __init__(
        self,
        tool_id: int,
        emitter: Emitter,
        user_file_ids: list[UUID],
        chat_file_ids: list[UUID],
    ) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._user_file_ids = set(user_file_ids)
        self._chat_file_ids = set(chat_file_ids)

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
        # TODO(evan): temporary – gate behind DISABLE_VECTOR_DB until the tool is
        # generalised for standard (vector-DB-enabled) deployments.
        return DISABLE_VECTOR_DB

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
                                "Number of characters to return (max 16000). "
                                "Defaults to 16000."
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
                obj=FileReaderStart(),
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

        if file_id not in self._user_file_ids and file_id not in self._chat_file_ids:
            raise ToolCallException(
                message=f"File {file_id} not in available files",
                llm_facing_message=(
                    f"File '{file_id}' is not available. "
                    "Please use one of the file IDs listed in the context."
                ),
            )

        return file_id

    def _load_file(self, file_id: UUID) -> InMemoryChatFile:
        if file_id in self._user_file_ids:
            with get_session_with_current_tenant() as db_session:
                return load_user_file(file_id, db_session)
        return load_chat_file_by_id(str(file_id))

    def run(
        self,
        placement: Placement,
        override_kwargs: FileReaderToolOverrideKwargs,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        if FILE_ID_FIELD not in llm_kwargs:
            raise ToolCallException(
                message=f"Missing required '{FILE_ID_FIELD}' parameter",
                llm_facing_message=(
                    f"The read_file tool requires a '{FILE_ID_FIELD}' parameter. "
                    f'Example: {{"file_id": "abc-123", "start_char": 0, "num_chars": 16000}}'
                ),
            )

        raw_file_id = cast(str, llm_kwargs[FILE_ID_FIELD])
        file_id = self._validate_file_id(raw_file_id)
        start_char = max(0, int(llm_kwargs.get(START_CHAR_FIELD, 0)))
        num_chars = min(
            MAX_NUM_CHARS,
            max(1, int(llm_kwargs.get(NUM_CHARS_FIELD, DEFAULT_NUM_CHARS))),
        )

        chat_file = self._load_file(file_id)

        # Only PLAIN_TEXT and CSV are guaranteed to contain actual text bytes.
        # DOC type in a loaded file means plaintext extraction failed and the
        # content is the original binary (e.g. raw PDF/DOCX bytes).
        if chat_file.file_type not in (ChatFileType.PLAIN_TEXT, ChatFileType.CSV):
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

        file_name = chat_file.filename or str(file_id)

        preview_start = section[:PREVIEW_CHARS]
        preview_end = section[-PREVIEW_CHARS:] if len(section) > PREVIEW_CHARS else ""

        # Emit result packet so the frontend can display what was read
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=FileReaderResult(
                    file_name=file_name,
                    file_id=str(file_id),
                    start_char=start_char,
                    end_char=end_char,
                    total_chars=total_chars,
                    preview_start=preview_start,
                    preview_end=preview_end,
                ),
            )
        )

        has_more = end_char < total_chars
        header = (
            f"File: {file_name}\n"
            f"Characters {start_char}-{end_char} of {total_chars}"
        )
        if has_more:
            header += f" (use start_char={end_char} to continue reading)"

        llm_response = f"{header}\n\n{section}"

        # Build a lightweight summary for DB storage (avoids saving full text).
        # The LLM-facing response carries the real content; the rich_response
        # is what gets persisted and re-hydrated on page reload.
        saved_summary = json.dumps(
            {
                "file_name": file_name,
                "file_id": str(file_id),
                "start_char": start_char,
                "end_char": end_char,
                "total_chars": total_chars,
                "preview_start": preview_start,
                "preview_end": preview_end,
            }
        )

        return ToolResponse(
            rich_response=saved_summary,
            llm_facing_response=llm_response,
        )
