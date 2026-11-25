"""The arguments of the sandbox tools whose models call them in their own
shapes: the shell of each tool family (SHELL_SHAPES), and the artifact tool's
actions (ArtifactArguments), which give the library tools' operations. Each
arguments model's pure `request` gives the operation's typed input."""

from collections.abc import Mapping
from typing import Literal, NamedTuple

from pydantic import ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from onyx.llm.model_capabilities import ToolFamily
from onyx.server.features.build.sandbox.exec_output import (
    EXEC_DEFAULT_YIELD_MS,
    EXEC_MAX_YIELD_MS,
    EXEC_MIN_YIELD_MS,
    POLL_MAX_YIELD_MS,
    POLL_MIN_YIELD_MS,
    WRITE_STDIN_DEFAULT_YIELD_MS,
    WRITE_STDIN_MAX_YIELD_MS,
)
from onyx.tools.constants import (
    BASH_TOOL_NAME,
    DEFAULT_MAX_OUTPUT_CHARS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    EXEC_COMMAND_TOOL_NAME,
    MAX_OUTPUT_TOKENS_DESCRIPTION,
)
from onyx.tools.models import ToolArguments
from onyx.tools.tool_implementations.sandbox.models import (
    ARTIFACT_PUBLISH_PATHS,
    ARTIFACT_TEXT_MAX_ITEMS,
    ARTIFACTS_LIST_MAX_LIMIT,
    ARTIFACTS_MATERIALIZE_MAX_ITEMS,
    ARTIFACTS_QUERY_MAX_CHARS,
    FIND_MAX_MATCHES,
    FIND_PATTERN_MAX_CHARS,
    LIBRARY_SEARCH_MAX_TOP_K,
    PUBLISH_FILES_MAX_FILES,
    READ_MAX_LINES,
    ArtifactType,
    EchoedText,
    LibraryCreateLibraryFileArguments,
    LibraryFindArguments,
    LibraryListArguments,
    LibraryPrepareMaterializeArguments,
    LibraryReadArguments,
    LibraryReplaceLibraryFileArguments,
    LibraryRequest,
    LibrarySearchArguments,
    ManageLibraryArguments,
    parse_artifact_url,
    parse_file_reference,
)
from onyx.tools.tool_implementations.utils import output_chars_from_tokens


class ExecRequest(NamedTuple):
    """A call of the shell's run operation: start a command."""

    cmd: str
    workdir: str | None
    # None: the sandbox's default wait.
    yield_time_ms: int | None
    max_chars: int


class WriteStdinRequest(NamedTuple):
    """A call of the shell's write operation: write to a running command, or
    poll it."""

    session_id: str
    chars: str
    yield_time_ms: int | None
    max_chars: int


# What the shell card shows of a call; for write_stdin, the same keys in
# every shape.
_SESSION_ID_DESCRIPTION = "Identifier of the running command."
_CHARS_DESCRIPTION = (
    "Characters to write to stdin. Defaults to empty, which polls without "
    'writing. "\\u0003" interrupts the command.'
)


class ExecCommandArguments(ToolArguments[ExecRequest]):
    cmd: str = Field(description="Shell command to execute.")
    workdir: str | None = Field(
        default=None,
        description="Working directory for the command. Defaults to the chat "
        "session directory.",
    )
    yield_time_ms: int | None = Field(
        default=None,
        description=f"Wait before yielding output. Defaults to "
        f"{EXEC_DEFAULT_YIELD_MS} ms; effective range is "
        f"{EXEC_MIN_YIELD_MS}-{EXEC_MAX_YIELD_MS} ms.",
    )
    max_output_tokens: int = Field(
        default=DEFAULT_MAX_OUTPUT_TOKENS, description=MAX_OUTPUT_TOKENS_DESCRIPTION
    )

    def request(self) -> ExecRequest:
        return ExecRequest(
            cmd=self.cmd,
            workdir=self.workdir,
            yield_time_ms=self.yield_time_ms,
            max_chars=output_chars_from_tokens(self.max_output_tokens),
        )


class BashArguments(ToolArguments[ExecRequest]):
    command: str = Field(description="The command to execute")
    timeout: int | None = Field(
        default=None,
        description="Milliseconds to wait for the command before returning its "
        "output so far, with a session ID while it keeps running. Defaults to "
        f"{EXEC_DEFAULT_YIELD_MS}, at most {EXEC_MAX_YIELD_MS}.",
    )
    description: str | None = Field(
        default=None,
        description="Clear, concise description of what this command does in "
        "5-10 words.",
    )
    run_in_background: bool = Field(
        default=False,
        description="Return at once with a session ID while the command runs. "
        "Poll it with write_stdin; nothing reports when it ends.",
    )

    def request(self) -> ExecRequest:
        return ExecRequest(
            cmd=self.command,
            workdir=None,
            yield_time_ms=EXEC_MIN_YIELD_MS if self.run_in_background else self.timeout,
            max_chars=DEFAULT_MAX_OUTPUT_CHARS,
        )


_WRITE_STDIN_YIELD = (
    f"Non-empty writes default to {WRITE_STDIN_DEFAULT_YIELD_MS} ms and cap at "
    f"{WRITE_STDIN_MAX_YIELD_MS} ms; empty polls wait "
    f"{POLL_MIN_YIELD_MS}-{POLL_MAX_YIELD_MS} ms."
)


class WriteStdinArguments(ToolArguments[WriteStdinRequest]):
    # Models may send the session ID as a number.
    model_config = ConfigDict(coerce_numbers_to_str=True)

    session_id: str = Field(description=_SESSION_ID_DESCRIPTION)
    chars: str = Field(default="", description=_CHARS_DESCRIPTION)
    yield_time_ms: int | None = Field(
        default=None, description=f"Wait before yielding output. {_WRITE_STDIN_YIELD}"
    )
    max_output_tokens: int = Field(
        default=DEFAULT_MAX_OUTPUT_TOKENS, description=MAX_OUTPUT_TOKENS_DESCRIPTION
    )

    def request(self) -> WriteStdinRequest:
        return WriteStdinRequest(
            session_id=self.session_id,
            chars=self.chars,
            yield_time_ms=self.yield_time_ms,
            max_chars=output_chars_from_tokens(self.max_output_tokens),
        )


class BashWriteStdinArguments(ToolArguments[WriteStdinRequest]):
    model_config = ConfigDict(coerce_numbers_to_str=True)

    session_id: str = Field(description=_SESSION_ID_DESCRIPTION)
    chars: str = Field(default="", description=_CHARS_DESCRIPTION)
    timeout: int | None = Field(
        default=None,
        description=f"Milliseconds to wait before returning output. {_WRITE_STDIN_YIELD}",
    )

    def request(self) -> WriteStdinRequest:
        return WriteStdinRequest(
            session_id=self.session_id,
            chars=self.chars,
            yield_time_ms=self.timeout,
            max_chars=DEFAULT_MAX_OUTPUT_CHARS,
        )


class ShellShape(NamedTuple):
    """How one tool family names and calls the shell's operations: run a
    command, and write to a running one. write_stdin has one name in every
    shape."""

    name: str
    arguments: type[ToolArguments[ExecRequest]]
    # The arguments that hold the command and its working directory, which
    # the shell card shows; None: the shape has no working directory.
    command_argument: str
    workdir_argument: str | None
    write_stdin_arguments: type[ToolArguments[WriteStdinRequest]]


SHELL_SHAPES: Mapping[ToolFamily, ShellShape] = {
    ToolFamily.OPENAI: ShellShape(
        name=EXEC_COMMAND_TOOL_NAME,
        arguments=ExecCommandArguments,
        command_argument="cmd",
        workdir_argument="workdir",
        write_stdin_arguments=WriteStdinArguments,
    ),
    # The shape Claude models are trained on.
    ToolFamily.CLAUDE: ShellShape(
        name=BASH_TOOL_NAME,
        arguments=BashArguments,
        command_argument="command",
        workdir_argument=None,
        write_stdin_arguments=BashWriteStdinArguments,
    ),
}
# Each shape by its command tool's name: a chat's history can hold calls of
# every shape.
SHELL_SHAPES_BY_NAME: Mapping[str, ShellShape] = {
    shape.name: shape for shape in SHELL_SHAPES.values()
}
SHELL_TOOL_NAMES = frozenset(SHELL_SHAPES_BY_NAME)


# The arguments that each action of the artifact tool takes.
ArtifactAction = Literal["publish", "list", "read", "delete", "rename", "restore"]
ARTIFACT_ACTION_ARGUMENTS: dict[ArtifactAction, frozenset[str]] = {
    "publish": frozenset(
        {
            *ARTIFACT_PUBLISH_PATHS,
            "title",
            "description",
            "url",
            "path",
            "force",
            "label",
        }
    ),
    "list": frozenset({"scope", "type", "query", "limit", "after"}),
    "read": frozenset({"url", "path", "paths", "out_dir", "query", "offset", "limit"}),
    "delete": frozenset({"url"}),
    "rename": frozenset({"url", "name"}),
    "restore": frozenset({"url", "label"}),
}


class ArtifactArguments(ToolArguments[LibraryRequest]):
    """The arguments of the artifact tool, in the shape of the Artifact tool
    that Claude models are trained on, where Onyx has the operation: an
    action and the arguments of each action. Each action takes only its own
    arguments (ARTIFACT_ACTION_ARGUMENTS); arguments that the model adds
    beyond these are ignored. `request` gives the library operation's
    arguments, so both tool families run the same operations."""

    action: ArtifactAction = Field(
        default="publish",
        description="publish (the default) gives files from the VM to the user; "
        "list finds published files, by content with query; read shows their text, finds text in them "
        "with query, or copies them into the VM with out_dir; delete deletes a "
        "published file, after the user approves; rename renames a published "
        "file; restore makes an older version the newest.",
    )
    file_path: EchoedText | None = Field(
        default=None,
        description="publish: a file in the VM, relative to the working "
        "directory or absolute.",
    )
    file_paths: list[EchoedText] | None = Field(
        default=None,
        max_length=PUBLISH_FILES_MAX_FILES,
        description=f"publish: up to {PUBLISH_FILES_MAX_FILES} files instead of "
        "file_path; all are published, or none.",
    )
    title: str | None = Field(
        default=None, description="publish with file_path: a short title."
    )
    description: str | None = Field(
        default=None,
        description="publish: one sentence about the files. Accepted, not shown.",
    )
    url: EchoedText | None = Field(
        default=None,
        description="read: the url of a published file from an earlier result; "
        "one that ends in /v<N> names that version. publish with file_path: "
        "the file to add a version to, by the url of the version you last saw. "
        "delete: the file to delete, with all its versions, by the url of its "
        "newest version. rename: the file to rename. restore: the version to "
        "restore, ending in /v<N>.",
    )
    name: EchoedText | None = Field(
        default=None,
        description="rename: the new file name, not a path, with the current "
        "extension.",
    )
    force: bool | None = Field(
        default=None,
        description="publish with url: add the version even when the file has a "
        "newer version than the url names. Older versions stay.",
    )
    label: str | None = Field(
        default=None,
        description="publish with url, restore: a short note on why this "
        "version exists.",
    )
    path: EchoedText | None = Field(
        default=None,
        description="read: a file ID, or the url of a published file. publish "
        "with url: a file ID of any published file, whose copy becomes the "
        "url's newest version.",
    )
    paths: list[EchoedText] | None = Field(
        default=None,
        description=f"read: up to {ARTIFACT_TEXT_MAX_ITEMS} file IDs or urls, or "
        f"up to {ARTIFACTS_MATERIALIZE_MAX_ITEMS} with out_dir.",
    )
    out_dir: EchoedText | None = Field(
        default=None,
        description="read: copy the files into this directory, relative to the "
        "working directory, instead of showing their text.",
    )
    offset: int | None = Field(
        default=None,
        description="read: the line number to start reading from; with query, "
        "the matches to skip. Only with one file.",
    )
    scope: Literal["mine"] | None = Field(
        default=None, description="list: only mine, the user's own files."
    )
    type: ArtifactType | None = Field(
        default=None, description="list: only files of this type."
    )
    query: str | None = Field(
        default=None,
        description="list: search the files' content, names and titles; best "
        "matches first. read: text to find in the files' lines, in any case.",
    )
    limit: int | None = Field(
        default=None,
        description=f"list: the most files, from 1 to {ARTIFACTS_LIST_MAX_LIMIT}; "
        f"with query, to {LIBRARY_SEARCH_MAX_TOP_K}. "
        f"read: the most lines, at most {READ_MAX_LINES}; with query, the most "
        f"matches, at most {FIND_MAX_MATCHES}.",
    )
    after: str | None = Field(
        default=None, description="list: the next_cursor of the previous page."
    )

    @model_validator(mode="after")
    def _action_arguments(self) -> "ArtifactArguments":
        takes = ARTIFACT_ACTION_ARGUMENTS[self.action]
        extra = sorted(
            name
            for name, value in self
            if value is not None and name != "action" and name not in takes
        )
        if extra:
            raise PydanticCustomError(
                "action_arguments",
                "Action {action} does not take {extra}; it takes {takes}",
                {
                    "action": self.action,
                    "extra": ", ".join(extra),
                    "takes": ", ".join(sorted(takes)),
                },
            )
        if self.action in ("delete", "rename", "restore") and self.url is None:
            raise PydanticCustomError(
                "action_arguments", "{action} takes url", {"action": self.action}
            )
        if self.action == "rename" and self.name is None:
            raise PydanticCustomError("action_arguments", "rename takes url and name")
        # One offset holds for one file's lines or matches.
        targets = [self.url, self.path, *(self.paths or [])]
        if self.offset is not None and len(targets) - targets.count(None) > 1:
            raise PydanticCustomError(
                "action_arguments",
                "offset pages one file; read one file at a time to page",
            )
        if self.path is not None and (
            self.action == "publish"
            and (self.url is None or (self.file_path, self.file_paths, self.title))
            != (None, None, None)
        ):
            raise PydanticCustomError(
                "action_arguments",
                "path goes with url, without file_path, file_paths or title",
            )
        try:
            reference = None if self.url is None else parse_artifact_url(self.url)
        except ValueError as error:
            raise PydanticCustomError(
                "action_arguments", "{error}", {"error": str(error)}
            ) from error
        if self.action == "publish":
            if reference is None and (self.force, self.label) != (None, None):
                raise PydanticCustomError(
                    "action_arguments", "force and label go with url"
                )
            if reference is not None and reference[1] is None and not self.force:
                raise PydanticCustomError(
                    "action_arguments",
                    "Pass the url from your last result, which names the version "
                    "you saw, or force:true",
                )
            if self.path is None and (
                (self.file_path is None and not self.file_paths)
                or (self.file_path is not None and self.file_paths is not None)
            ):
                raise PydanticCustomError(
                    "action_arguments", "publish takes file_path or file_paths"
                )
            if self.file_paths is not None and (
                self.title is not None or reference is not None
            ):
                raise PydanticCustomError(
                    "action_arguments", "title and url go with file_path"
                )
        if self.action == "restore" and reference is not None and reference[1] is None:
            raise PydanticCustomError(
                "action_arguments",
                "restore takes the url of the version to restore, ending in /v<N>",
            )
        return self

    @model_validator(mode="after")
    def _read_and_list_arguments(self) -> "ArtifactArguments":
        """The read's and the list's arguments, in this tool's names, so
        `request` gives valid library arguments."""
        if self.action == "read":
            targets = (
                (self.url is not None) + (self.path is not None) + len(self.paths or [])
            )
            if not targets:
                raise PydanticCustomError(
                    "action_arguments", "read takes url, path or paths"
                )
            if self.out_dir is not None and (self.query, self.offset, self.limit) != (
                None,
                None,
                None,
            ):
                raise PydanticCustomError(
                    "action_arguments",
                    "out_dir copies files; query, offset and limit go with a read "
                    "of their text, without out_dir",
                )
            if self.out_dir is not None:
                if targets > ARTIFACTS_MATERIALIZE_MAX_ITEMS:
                    raise PydanticCustomError(
                        "action_arguments",
                        f"read copies at most {ARTIFACTS_MATERIALIZE_MAX_ITEMS} "
                        "files; pass fewer paths",
                    )
                return self
            if targets > ARTIFACT_TEXT_MAX_ITEMS:
                raise PydanticCustomError(
                    "action_arguments",
                    f"read shows the text of at most {ARTIFACT_TEXT_MAX_ITEMS} "
                    "files; pass fewer paths, or copy them with out_dir",
                )
            # The ranges of the read's or the find's own arguments.
            if self.query is None:
                lowest_offset, most = 1, READ_MAX_LINES
            else:
                lowest_offset, most = 0, FIND_MAX_MATCHES
                if not 0 < len(self.query) <= FIND_PATTERN_MAX_CHARS:
                    raise PydanticCustomError(
                        "action_arguments",
                        "read's query takes 1 to {most} characters",
                        {"most": FIND_PATTERN_MAX_CHARS},
                    )
            if self.offset is not None and self.offset < lowest_offset:
                raise PydanticCustomError(
                    "action_arguments",
                    "read's offset is at least {lowest}",
                    {"lowest": lowest_offset},
                )
            if self.limit is not None and not 1 <= self.limit <= most:
                raise PydanticCustomError(
                    "action_arguments",
                    "read's limit is from 1 to {most}",
                    {"most": most},
                )
        if (
            self.action == "list"
            and self.query is not None
            and len(self.query.strip()) > ARTIFACTS_QUERY_MAX_CHARS
        ):
            raise PydanticCustomError(
                "action_arguments",
                "list's query takes at most {most} characters",
                {"most": ARTIFACTS_QUERY_MAX_CHARS},
            )
        return self

    def request(self) -> LibraryRequest:
        """The arguments of the library operation that the call runs; the
        validators above check them in this tool's argument names."""
        reference = None if self.url is None else parse_artifact_url(self.url)
        if self.action == "publish":
            expected = None if reference is None or self.force else reference[1]
            if reference is not None and self.path is not None:
                return ManageLibraryArguments.model_validate(
                    {
                        "operations": [
                            {
                                "operation": "update",
                                "library_file_id": reference[0],
                                "file_uri": {"file_id": self.path},
                                "expected_current_version": expected,
                                "version_reason": self.label,
                            }
                        ]
                    }
                )
            if reference is not None:
                return LibraryReplaceLibraryFileArguments.model_validate(
                    {
                        "library_file_id": reference[0],
                        "file": self.file_path,
                        "expected_current_version": expected,
                        "title": self.title,
                        "version_reason": self.label,
                    }
                )
            return LibraryCreateLibraryFileArguments.model_validate(
                {
                    "file": self.file_path,
                    "files": self.file_paths,
                    "title": self.title,
                    "description": self.description,
                }
            )
        if reference is not None and self.action in ("delete", "rename", "restore"):
            artifact_id, version = reference
            return ManageLibraryArguments.model_validate(
                {
                    "operations": [
                        # A delete's version must be the newest, which it checks.
                        {
                            "operation": "delete",
                            "target": {
                                "library_file_id": artifact_id,
                                "version_number": version,
                            },
                        }
                        if self.action == "delete"
                        else {
                            "operation": "rename",
                            "target": {"library_file_id": artifact_id},
                            "new_name": self.name,
                        }
                        if self.action == "rename"
                        else {
                            "operation": "restore_version",
                            "library_file_id": artifact_id,
                            "version_number": version,
                            "version_reason": self.label,
                        }
                    ]
                }
            )
        if self.action == "list":
            page = {"cursor": self.after, "filters": {"category": self.type}}
            if (self.query or "").strip():
                return LibrarySearchArguments.model_validate(
                    {
                        "search_query": [{"q": self.query}],
                        **page,
                        **({} if self.limit is None else {"top_k": self.limit}),
                    }
                )
            return LibraryListArguments.model_validate(
                {**page, **({} if self.limit is None else {"limit": self.limit})}
            )
        # A url names an artifact; another target is a file ID.
        references = [
            parse_file_reference(target).model_dump(mode="json", exclude_none=True)
            for target in (
                *([] if self.url is None else [self.url]),
                *([] if self.path is None else [self.path]),
                *(self.paths or []),
            )
        ]
        if self.out_dir is not None:
            return LibraryPrepareMaterializeArguments.model_validate(
                {"items": references, "destination": {"directory": self.out_dir}}
            )
        # read shows the text; with query, it finds the query's lines.
        options = (
            {"start_line": self.offset, "max_lines": self.limit}
            if self.query is None
            else {
                "pattern": self.query,
                "match_offset": self.offset,
                "max_matches": self.limit,
            }
        )
        items = [
            reference
            | {key: value for key, value in options.items() if value is not None}
            for reference in references
        ]
        if self.query is None:
            return LibraryReadArguments.model_validate({"read": items})
        return LibraryFindArguments.model_validate({"find": items})
