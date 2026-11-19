"""Progress of a file tool call while the model streams its arguments."""

import time

from pydantic import JsonValue

from onyx.server.query_and_chat.streaming_models import FileToolProgress
from onyx.tools.tool_implementations.sandbox.patch import (
    ADD_FILE_MARKER,
    DELETE_FILE_MARKER,
    UPDATE_FILE_MARKER,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    ApplyPatchTool,
    EditTool,
    WriteTool,
)
from onyx.utils.streaming_json import appended_text, parse_partial_object

# The shortest time between two progress reports of one call. Between reports
# the stream only collects the fragments, so a report parses the arguments at
# most this often, not once per fragment.
PROGRESS_INTERVAL_SECONDS = 0.25

# The argument whose lines each file tool counts.
_TEXT_ARGUMENTS: dict[str, str] = {
    WriteTool.NAME: "content",
    EditTool.NAME: "new_string",
    ApplyPatchTool.NAME: "input",
}
_PATH_ARGUMENT = "file_path"
_FILE_MARKERS = (ADD_FILE_MARKER, UPDATE_FILE_MARKER, DELETE_FILE_MARKER)


class FileArgumentStream:
    """The streamed arguments of one write, edit or apply_patch call.

    Line counts and patch headers come from the text each report adds; only
    the partial JSON parse reads all arguments, at most once per interval.
    """

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        self._text_argument = _TEXT_ARGUMENTS[tool_name]
        self._fragments: list[str] = []
        self._arguments: dict[str, JsonValue] = {}
        self._paths: list[str] = []
        self._newlines = 0
        # The text after the last newline: a patch header can span reports.
        self._open_line = ""
        self._reported_at = float("-inf")
        self._reported: FileToolProgress | None = None

    def add(self, fragment: str) -> FileToolProgress | None:
        """Collect a fragment; returns new progress when a report is due.

        Raises ValueError when the arguments cannot be the start of a JSON object.
        """
        self._fragments.append(fragment)
        now = time.monotonic()
        if now - self._reported_at < PROGRESS_INTERVAL_SECONDS:
            return None
        self._reported_at = now
        raw = "".join(self._fragments)
        self._fragments = [raw]
        return self._report(parse_partial_object(raw), False)

    def end(self, arguments: dict[str, JsonValue]) -> FileToolProgress | None:
        """The final progress from the complete arguments, if it changed."""
        return self._report(arguments, True)

    def _report(
        self, arguments: dict[str, JsonValue], complete: bool
    ) -> FileToolProgress | None:
        added = appended_text(self._arguments, arguments).get(self._text_argument, "")
        self._arguments = arguments
        self._newlines += added.count("\n")
        *lines, self._open_line = (self._open_line + added).split("\n")
        if self.tool_name == ApplyPatchTool.NAME:
            for line in [*lines, self._open_line] if complete else lines:
                header = line.strip()
                for marker in _FILE_MARKERS:
                    if header.startswith(marker):
                        self._paths.append(header[len(marker) :].strip())
        else:
            path = arguments.get(_PATH_ARGUMENT)
            # A partial parse keeps the last string cut off; a later key
            # shows that the path is whole.
            if (
                isinstance(path, str)
                and path
                and (complete or next(reversed(arguments)) != _PATH_ARGUMENT)
            ):
                self._paths = [path]
        progress = FileToolProgress(
            paths=list(self._paths),
            lines=self._newlines + (1 if self._open_line else 0),
        )
        if progress == self._reported:
            return None
        self._reported = progress
        return progress
