import hashlib
import mimetypes
import os
import re
from io import BytesIO
from typing import Any
from typing import cast

from pydantic import BaseModel
from pydantic import TypeAdapter
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.configs.app_configs import CODE_INTERPRETER_BASE_URL
from onyx.configs.app_configs import CODE_INTERPRETER_DEFAULT_TIMEOUT_MS
from onyx.configs.app_configs import CODE_INTERPRETER_MAX_OUTPUT_LENGTH
from onyx.configs.app_configs import CODE_INTERPRETER_MAX_STAGED_BYTES
from onyx.configs.app_configs import CODE_INTERPRETER_MAX_STAGED_FILES
from onyx.configs.app_configs import CODE_INTERPRETER_STAGING_CONCURRENCY
from onyx.configs.constants import FileOrigin
from onyx.db.code_interpreter import fetch_code_interpreter_server
from onyx.file_store.utils import build_full_frontend_file_url
from onyx.file_store.utils import get_default_file_store
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PythonToolDelta
from onyx.server.query_and_chat.streaming_models import PythonToolStart
from onyx.tools.interface import Tool
from onyx.tools.models import ChatFile
from onyx.tools.models import LlmPythonExecutionResult
from onyx.tools.models import PythonExecutionFile
from onyx.tools.models import PythonToolOverrideKwargs
from onyx.tools.models import PythonToolRichResponse
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterClient,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import FileInput
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    StreamErrorEvent,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    StreamOutputEvent,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    StreamResultEvent,
)
from onyx.tools.tool_implementations.utils import truncate_output as _truncate_output
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()

CODE_FIELD = "code"
CODE_INTERPRETER_DEFAULT_FILENAME = "file"
CODE_INTERPRETER_FILENAME_MAX_LENGTH = 200
CODE_INTERPRETER_UNSAFE_FILENAME_CHARS = re.compile(r"[\x00-\x1f/\\:\*\?\"<>\|]+")


def _safe_code_interpreter_filename(filename: str) -> str:
    sanitized = CODE_INTERPRETER_UNSAFE_FILENAME_CHARS.sub("_", filename)
    sanitized = sanitized.strip().strip(".")
    if not sanitized:
        return CODE_INTERPRETER_DEFAULT_FILENAME

    base, ext = os.path.splitext(sanitized)
    if not base:
        base = CODE_INTERPRETER_DEFAULT_FILENAME

    max_base_len = max(1, CODE_INTERPRETER_FILENAME_MAX_LENGTH - len(ext))
    return f"{base[:max_base_len]}{ext}"


def _dedupe_code_interpreter_filename(
    filename: str,
    seen_filenames: set[str],
    fallback_id: str,
) -> str:
    safe_filename = _safe_code_interpreter_filename(filename)
    if safe_filename not in seen_filenames:
        seen_filenames.add(safe_filename)
        return safe_filename

    base, ext = os.path.splitext(safe_filename)
    suffix = f"_{fallback_id}{ext}"
    max_base_len = max(1, CODE_INTERPRETER_FILENAME_MAX_LENGTH - len(suffix))
    deduped_filename = f"{base[:max_base_len]}{suffix}"
    seen_filenames.add(deduped_filename)
    return deduped_filename


class _StagePlan(BaseModel):
    file_name: str
    content: bytes
    cache_key: tuple[str, str]  # (file_name, content_hash)


def _code_references_file(filename: str, code: str) -> bool:
    """Heuristic: the code wants a file if its name appears literally in the
    code. Checked on the raw filename and its sanitized (sandbox) form, since
    the model may write either. Filename-only — no object-store read."""
    if not filename:
        return False
    return filename in code or _safe_code_interpreter_filename(filename) in code


def _read_chat_file_content(chat_file: ChatFile) -> bytes:
    """Materialize a (possibly lazy) chat file's bytes; the object-store read
    happens here. Extracted so reads can be batched in parallel."""
    return chat_file.content


def _staging_priority(chat_files: list[ChatFile], code: str) -> list[int]:
    """``chat_files`` indices in staging-priority order: files the code names
    first, then the rest, newest-first within each group."""
    referenced: list[int] = []
    unreferenced: list[int] = []
    for idx, chat_file in enumerate(chat_files):
        bucket = (
            referenced
            if _code_references_file(chat_file.filename, code)
            else unreferenced
        )
        bucket.append(idx)
    return list(reversed(referenced)) + list(reversed(unreferenced))


class _StagingSelection(BaseModel):
    # Selected (file, content) pairs in chronological order.
    files: list[tuple[ChatFile, bytes]]
    # Files excluded by the count/byte caps (not counting read failures).
    dropped_by_caps: int
    # Filenames whose bytes could not be read from the object store.
    read_failures: list[str]


def _select_files_for_staging(
    chat_files: list[ChatFile],
    code: str,
    *,
    max_files: int,
    max_bytes: int,
    read_concurrency: int,
) -> _StagingSelection:
    """Choose which session files to stage, reading bytes only for the chosen.

    Files the ``code`` names explicitly are staged first; the remaining
    count/byte budget is backfilled with the most recent of the rest. Candidates
    are read in bounded parallel batches — concurrency hides read latency while
    only one batch is held in memory at a time.
    """
    # Count cap: only the top candidates can ever be staged, so never read more.
    candidates = _staging_priority(chat_files, code)[:max_files]

    selected: dict[int, bytes] = {}
    read_failures: list[str] = []
    staged_bytes = 0
    for start in range(0, len(candidates), read_concurrency):
        batch = candidates[start : start + read_concurrency]
        contents = run_functions_tuples_in_parallel(
            [(_read_chat_file_content, (chat_files[idx],)) for idx in batch],
            allow_failures=True,
            max_workers=read_concurrency,
        )

        over_budget = False
        for idx, content in zip(batch, contents):
            if content is None:
                logger.warning(
                    "Failed to read file for Python execution: %s",
                    chat_files[idx].filename,
                )
                read_failures.append(chat_files[idx].filename)
                continue
            # Always stage at least one file; otherwise stop at the byte budget.
            if selected and staged_bytes + len(content) > max_bytes:
                over_budget = True
                break
            selected[idx] = content
            staged_bytes += len(content)
        if over_budget:
            break

    chronological = [(chat_files[idx], selected[idx]) for idx in sorted(selected)]
    return _StagingSelection(
        files=chronological,
        dropped_by_caps=len(chat_files) - len(selected) - len(read_failures),
        read_failures=read_failures,
    )


def _build_staging_notice(
    dropped_count: int,
    total_files: int,
    failed_files: list[str],
) -> str | None:
    """LLM-facing note when some session files are absent — dropped by the caps
    or failed to stage (read/upload error) — so the model doesn't assume they're
    available. ``None`` when everything staged."""
    parts: list[str] = []
    if dropped_count > 0:
        parts.append(
            f"{dropped_count} of {total_files} session files were not staged due "
            f"to per-execution limits ({CODE_INTERPRETER_MAX_STAGED_FILES} files / "
            f"{CODE_INTERPRETER_MAX_STAGED_BYTES} bytes); files referenced in the "
            f"code were prioritized."
        )
    if failed_files:
        parts.append(
            f"Failed to stage {len(failed_files)} file(s): {', '.join(failed_files)}."
        )
    return " ".join(parts) if parts else None


class PythonTool(Tool[PythonToolOverrideKwargs]):
    """
    Python code execution tool using an external Code Interpreter service.

    This tool allows executing Python code in a secure, isolated sandbox environment.
    It supports uploading files from the chat session and downloading generated files.
    """

    NAME = "python"
    DISPLAY_NAME = "Code Interpreter"
    DESCRIPTION = "Execute Python code in an isolated sandbox environment."

    def __init__(self, tool_id: int, emitter: Emitter) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        # Cache of (filename, content_hash) -> ci_file_id to avoid re-uploading
        # the same file on every tool call iteration within the same agent session.
        # Filename is included in the key so two files with identical bytes but
        # different names each get their own upload slot.
        # TTL assumption: code-interpreter file TTLs (typically hours) greatly
        # exceed the lifetime of a single agent session (at most MAX_LLM_CYCLES
        # iterations, typically a few minutes), so stale-ID eviction is not needed.
        self._uploaded_file_cache: dict[tuple[str, str], str] = {}

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
    def is_available(cls, db_session: Session) -> bool:
        if not CODE_INTERPRETER_BASE_URL:
            return False
        server = fetch_code_interpreter_server(db_session)
        if not server.server_enabled:
            return False

        with CodeInterpreterClient() as client:
            return client.health(use_cache=True).healthy

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        CODE_FIELD: {
                            "type": "string",
                            "description": "Python source code to execute",
                        },
                    },
                    "required": [CODE_FIELD],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        """Emit start packet for this tool. Code will be emitted in run() method."""
        # Note: PythonToolStart requires code, but we don't have it in emit_start
        # The code is available in run() method via llm_kwargs
        # We'll emit the start packet in run() instead

    def _upload_and_stage(
        self,
        client: CodeInterpreterClient,
        selected: list[tuple[ChatFile, bytes]],
    ) -> tuple[list[FileInput], list[str]]:
        """Upload the selected files, returning stage specs and the names of any
        that failed to upload.

        Cache misses upload concurrently (bounded); the cache is written
        single-threaded afterward so it is never mutated from worker threads.
        Files are staged in chronological order for deterministic dedup naming.
        """
        seen_filenames: set[str] = set()
        plans: list[_StagePlan] = []
        for ind, (chat_file, content) in enumerate(selected):
            file_name = _dedupe_code_interpreter_filename(
                chat_file.filename, seen_filenames, str(ind)
            )
            content_hash = hashlib.sha256(content).hexdigest()
            plans.append(
                _StagePlan(
                    file_name=file_name,
                    content=content,
                    cache_key=(file_name, content_hash),
                )
            )

        # allow_failures keeps one bad upload from sinking the batch; each upload
        # is individually bounded by the client's per-request timeout.
        misses = [p for p in plans if p.cache_key not in self._uploaded_file_cache]
        if misses:
            upload_results = run_functions_tuples_in_parallel(
                [(client.upload_file, (p.content, p.file_name)) for p in misses],
                allow_failures=True,
                max_workers=CODE_INTERPRETER_STAGING_CONCURRENCY,
            )
            for plan, ci_file_id in zip(misses, upload_results):
                if ci_file_id is None:
                    logger.warning(
                        "Failed to upload file for Python execution: %s", plan.file_name
                    )
                    continue
                self._uploaded_file_cache[plan.cache_key] = ci_file_id

        files_to_stage: list[FileInput] = []
        failed_uploads: list[str] = []
        for plan in plans:
            ci_file_id = self._uploaded_file_cache.get(plan.cache_key)
            if ci_file_id is None:
                failed_uploads.append(plan.file_name)
                continue
            files_to_stage.append({"path": plan.file_name, "file_id": ci_file_id})
            logger.info("Staged file for Python execution: %s", plan.file_name)
        return files_to_stage, failed_uploads

    def run(
        self,
        placement: Placement,
        override_kwargs: PythonToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        """
        Execute Python code in the Code Interpreter service.

        Args:
            placement: The placement info (turn_index and tab_index) for this tool call.
            override_kwargs: Contains chat_files to stage for execution
            **llm_kwargs: Contains 'code' parameter from LLM

        Returns:
            ToolResponse with execution results
        """
        if CODE_FIELD not in llm_kwargs:
            raise ToolCallException(
                message=f"Missing required '{CODE_FIELD}' parameter in python tool call",
                llm_facing_message=(
                    f"The python tool requires a '{CODE_FIELD}' parameter containing "
                    f"the Python code to execute. Please provide like: "
                    f'{{"code": "print(\'Hello, world!\')"}}'
                ),
            )
        code = cast(str, llm_kwargs[CODE_FIELD])
        chat_files = override_kwargs.chat_files if override_kwargs else []

        # Emit start event with the code
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=PythonToolStart(code=code),
            )
        )

        # Create Code Interpreter client — context manager ensures
        # session.close() is called on every exit path.
        with CodeInterpreterClient() as client:
            # Select the files to stage (referenced-first, recent backfill,
            # bounded by the caps), upload them, and note any drops to the LLM.
            selection = _select_files_for_staging(
                chat_files,
                code,
                max_files=CODE_INTERPRETER_MAX_STAGED_FILES,
                max_bytes=CODE_INTERPRETER_MAX_STAGED_BYTES,
                read_concurrency=CODE_INTERPRETER_STAGING_CONCURRENCY,
            )
            files_to_stage, upload_failures = self._upload_and_stage(
                client, selection.files
            )

            staging_notice = _build_staging_notice(
                selection.dropped_by_caps,
                len(chat_files),
                selection.read_failures + upload_failures,
            )
            if staging_notice:
                logger.warning(staging_notice)

            try:
                logger.debug("Executing code: %s", code)

                # Execute code with streaming (falls back to batch if unavailable)
                stdout_parts: list[str] = []
                stderr_parts: list[str] = []
                result_event: StreamResultEvent | None = None

                for event in client.execute_streaming(
                    code=code,
                    timeout_ms=CODE_INTERPRETER_DEFAULT_TIMEOUT_MS,
                    files=files_to_stage or None,
                ):
                    if isinstance(event, StreamOutputEvent):
                        if event.stream == "stdout":
                            stdout_parts.append(event.data)
                        else:
                            stderr_parts.append(event.data)
                        # Emit incremental delta to frontend
                        self.emitter.emit(
                            Packet(
                                placement=placement,
                                obj=PythonToolDelta(
                                    stdout=(
                                        event.data if event.stream == "stdout" else ""
                                    ),
                                    stderr=(
                                        event.data if event.stream == "stderr" else ""
                                    ),
                                ),
                            )
                        )
                    elif isinstance(event, StreamResultEvent):
                        result_event = event
                    elif isinstance(event, StreamErrorEvent):
                        raise RuntimeError(f"Code interpreter error: {event.message}")

                if result_event is None:
                    raise RuntimeError(
                        "Code interpreter stream ended without a result event"
                    )

                full_stdout = "".join(stdout_parts)
                full_stderr = "".join(stderr_parts)

                # Truncate output for LLM consumption
                truncated_stdout = _truncate_output(
                    full_stdout, CODE_INTERPRETER_MAX_OUTPUT_LENGTH, "stdout"
                )
                truncated_stderr = _truncate_output(
                    full_stderr, CODE_INTERPRETER_MAX_OUTPUT_LENGTH, "stderr"
                )

                # Handle generated files
                generated_files: list[PythonExecutionFile] = []
                generated_file_ids: list[str] = []
                file_ids_to_cleanup: list[str] = []
                file_store = get_default_file_store()

                for workspace_file in result_event.files:
                    if workspace_file.kind != "file" or not workspace_file.file_id:
                        continue

                    try:
                        # Download file from Code Interpreter
                        file_content = client.download_file(workspace_file.file_id)

                        # Determine MIME type from file extension
                        filename = workspace_file.path.split("/")[-1]
                        mime_type, _ = mimetypes.guess_type(filename)
                        # Default to binary if we can't determine the type
                        mime_type = mime_type or "application/octet-stream"

                        # Save to Onyx file store
                        onyx_file_id = file_store.save_file(
                            content=BytesIO(file_content),
                            display_name=filename,
                            file_origin=FileOrigin.CHAT_IMAGE_GEN,
                            file_type=mime_type,
                        )

                        generated_files.append(
                            PythonExecutionFile(
                                filename=filename,
                                file_link=build_full_frontend_file_url(onyx_file_id),
                            )
                        )
                        generated_file_ids.append(onyx_file_id)

                        # Mark for cleanup
                        file_ids_to_cleanup.append(workspace_file.file_id)

                    except Exception as e:
                        logger.error(
                            "Failed to handle generated file %s: %s",
                            workspace_file.path,
                            e,
                        )

                # Cleanup Code Interpreter files (generated files)
                for ci_file_id in file_ids_to_cleanup:
                    try:
                        client.delete_file(ci_file_id)
                    except Exception as e:
                        logger.error(
                            "Failed to delete Code Interpreter generated file %s: %s",
                            ci_file_id,
                            e,
                        )

                # Note: staged input files are intentionally not deleted here because
                # _uploaded_file_cache reuses their file_ids across iterations. They are
                # orphaned when the session ends, but the code interpreter cleans up
                # stale files on its own TTL.

                # Emit file_ids once files are processed
                if generated_file_ids:
                    self.emitter.emit(
                        Packet(
                            placement=placement,
                            obj=PythonToolDelta(file_ids=generated_file_ids),
                        )
                    )

                # Build result
                result = LlmPythonExecutionResult(
                    stdout=truncated_stdout,
                    stderr=truncated_stderr,
                    exit_code=result_event.exit_code,
                    timed_out=result_event.timed_out,
                    generated_files=generated_files,
                    error=(None if result_event.exit_code == 0 else truncated_stderr),
                    staging_notice=staging_notice,
                )

                # Serialize result for LLM
                adapter = TypeAdapter(LlmPythonExecutionResult)
                llm_response = adapter.dump_json(result).decode()

                return ToolResponse(
                    rich_response=PythonToolRichResponse(
                        generated_files=generated_files,
                    ),
                    llm_facing_response=llm_response,
                )

            except Exception as e:
                logger.error("Python execution failed: %s", e)
                error_msg = str(e)

                # Emit error delta
                self.emitter.emit(
                    Packet(
                        placement=placement,
                        obj=PythonToolDelta(
                            stdout="",
                            stderr=error_msg,
                            file_ids=[],
                        ),
                    )
                )

                # Return error result
                result = LlmPythonExecutionResult(
                    stdout="",
                    stderr=error_msg,
                    exit_code=-1,
                    timed_out=False,
                    generated_files=[],
                    error=error_msg,
                    staging_notice=staging_notice,
                )

                adapter = TypeAdapter(LlmPythonExecutionResult)
                llm_response = adapter.dump_json(result).decode()

                return ToolResponse(
                    rich_response=None,
                    llm_facing_response=llm_response,
                )

    @classmethod
    @override
    def should_emit_argument_deltas(cls) -> bool:
        return True
