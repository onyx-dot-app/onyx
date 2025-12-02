# import mimetypes
# from io import BytesIO

# from agents import function_tool
# from agents import RunContextWrapper
# from pydantic import TypeAdapter

# from onyx.server.query_and_chat.models import IterationAnswer
# from onyx.server.query_and_chat.models import IterationInstructions
# from onyx.chat.turn.models import ChatTurnContext
# from onyx.configs.app_configs import CODE_INTERPRETER_DEFAULT_TIMEOUT_MS
# from onyx.configs.app_configs import CODE_INTERPRETER_MAX_OUTPUT_LENGTH
# from onyx.configs.constants import FileOrigin
# from onyx.db.tools import get_tool_by_name
# from onyx.file_store.utils import build_full_frontend_file_url
# from onyx.file_store.utils import get_default_file_store
# from onyx.server.query_and_chat.streaming_models import Packet
# from onyx.server.query_and_chat.streaming_models import PythonToolDelta
# from onyx.server.query_and_chat.streaming_models import PythonToolStart
# from onyx.tools.tool_implementations.python.python_tool import PythonTool
# from onyx.tools.tool_implementations_v2.code_interpreter_client import (
#     CodeInterpreterClient,
# )
# from onyx.tools.tool_implementations_v2.code_interpreter_client import ExecuteResponse
# from onyx.tools.tool_implementations_v2.code_interpreter_client import FileInput
# from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting
# from onyx.tools.tool_implementations_v2.tool_result_models import (
#     LlmPythonExecutionResult,
# )
# from onyx.tools.tool_implementations_v2.tool_result_models import PythonExecutionFile
# from onyx.utils.logger import setup_logger

# logger = setup_logger()


# def _truncate_output(output: str, max_length: int, label: str = "output") -> str:
#     """
#     Truncate output string to max_length and append truncation message if needed.

#     Args:
#         output: The original output string to truncate
#         max_length: Maximum length before truncation
#         label: Label for logging (e.g., "stdout", "stderr")

#     Returns:
#         Truncated string with truncation message appended if truncated
#     """
#     truncated = output[:max_length]
#     if len(output) > max_length:
#         truncated += (
#             "\n... [output truncated, "
#             f"{len(output) - max_length} "
#             "characters omitted]"
#         )
#         logger.debug(f"Truncated {label}: {truncated}")
#     return truncated


# def _combine_outputs(stdout: str, stderr: str) -> str:
#     """
#     Combine stdout and stderr into a single string if both exist.

#     Args:
#         stdout: Standard output string
#         stderr: Standard error string

#     Returns:
#         Combined output string with labels if both exist, or the non-empty one
#         if only one exists, or empty string if both are empty
#     """
#     has_stdout = bool(stdout)
#     has_stderr = bool(stderr)

#     if has_stdout and has_stderr:
#         return f"stdout:\n\n{stdout}\n\nstderr:\n\n{stderr}"
#     elif has_stdout:
#         return stdout
#     elif has_stderr:
#         return stderr
#     else:
#         return ""


# @tool_accounting
# def _python_execution_core(
#     run_context: RunContextWrapper[ChatTurnContext],
#     code: str,
#     client: CodeInterpreterClient,
# ) -> LlmPythonExecutionResult:
#     """Core Python execution logic"""
#     index = run_context.context.current_run_step
#     emitter = run_context.context.run_dependencies.emitter

#     # Emit start event
#     emitter.emit(
#         Packet(
#             ind=index,
#             obj=PythonToolStart(code=code),
#         )
#     )

#     run_context.context.iteration_instructions.append(
#         IterationInstructions(
#             iteration_nr=index,
#             plan="Executing Python code",
#             purpose="Running Python code",
#             reasoning="Executing provided Python code in secure environment",
#         )
#     )

#     # Get all files from chat context and upload to Code Interpreter
#     files_to_stage: list[FileInput] = []
#     file_store = get_default_file_store()

#     # Access chat files directly from context (available after Step 0 changes)
#     chat_files = run_context.context.chat_files

#     for ind, chat_file in enumerate(chat_files):
#         file_name = chat_file.filename or f"file_{ind}"
#         try:
#             # Use file content already loaded in memory
#             file_content = chat_file.content

#             # Upload to Code Interpreter
#             ci_file_id = client.upload_file(file_content, file_name)

#             # Stage for execution
#             files_to_stage.append({"path": file_name, "file_id": ci_file_id})

#             logger.info(f"Staged file for Python execution: {file_name}")

#         except Exception as e:
#             logger.warning(f"Failed to stage file {file_name}: {e}")

#     try:
#         logger.debug(f"Executing code: {code}")

#         # Execute code with fixed timeout
#         response: ExecuteResponse = client.execute(
#             code=code,
#             timeout_ms=CODE_INTERPRETER_DEFAULT_TIMEOUT_MS,
#             files=files_to_stage or None,
#         )

#         # Truncate output for LLM consumption
#         truncated_stdout = _truncate_output(
#             response.stdout, CODE_INTERPRETER_MAX_OUTPUT_LENGTH, "stdout"
#         )
#         truncated_stderr = _truncate_output(
#             response.stderr, CODE_INTERPRETER_MAX_OUTPUT_LENGTH, "stderr"
#         )

#         # Handle generated files
#         generated_files: list[PythonExecutionFile] = []
#         generated_file_ids: list[str] = []
#         file_ids_to_cleanup: list[str] = []

#         for workspace_file in response.files:
#             if workspace_file.kind != "file" or not workspace_file.file_id:
#                 continue

#             try:
#                 # Download file from Code Interpreter
#                 file_content = client.download_file(workspace_file.file_id)

#                 # Determine MIME type from file extension
#                 filename = workspace_file.path.split("/")[-1]
#                 mime_type, _ = mimetypes.guess_type(filename)
#                 # Default to binary if we can't determine the type
#                 mime_type = mime_type or "application/octet-stream"

#                 # Save to Onyx file store directly
#                 onyx_file_id = file_store.save_file(
#                     content=BytesIO(file_content),
#                     display_name=filename,
#                     file_origin=FileOrigin.CHAT_UPLOAD,
#                     file_type=mime_type,
#                 )

#                 generated_files.append(
#                     PythonExecutionFile(
#                         filename=filename,
#                         file_link=build_full_frontend_file_url(onyx_file_id),
#                     )
#                 )
#                 generated_file_ids.append(onyx_file_id)

#                 # Mark for cleanup
#                 file_ids_to_cleanup.append(workspace_file.file_id)

#             except Exception as e:
#                 logger.error(
#                     f"Failed to handle generated file {workspace_file.path}: {e}"
#                 )

#         # Cleanup Code Interpreter files (both generated and staged input files)
#         for ci_file_id in file_ids_to_cleanup:
#             try:
#                 client.delete_file(ci_file_id)
#             except Exception as e:
#                 # TODO: add TTL on code interpreter files themselves so they are automatically
#                 # cleaned up after some time.
#                 logger.error(
#                     f"Failed to delete Code Interpreter generated file {ci_file_id}: {e}"
#                 )

#         # Cleanup staged input files
#         for file_mapping in files_to_stage:
#             try:
#                 client.delete_file(file_mapping["file_id"])
#             except Exception as e:
#                 # TODO: add TTL on code interpreter files themselves so they are automatically
#                 # cleaned up after some time.
#                 logger.error(
#                     f"Failed to delete Code Interpreter staged file {file_mapping['file_id']}: {e}"
#                 )

#         # Emit delta with stdout/stderr and generated files
#         emitter.emit(
#             Packet(
#                 ind=index,
#                 obj=PythonToolDelta(
#                     type="python_tool_delta",
#                     stdout=truncated_stdout,
#                     stderr=truncated_stderr,
#                     file_ids=generated_file_ids,
#                 ),
#             )
#         )

#         # Build result with truncated output
#         result = LlmPythonExecutionResult(
#             stdout=truncated_stdout,
#             stderr=truncated_stderr,
#             exit_code=response.exit_code,
#             timed_out=response.timed_out,
#             generated_files=generated_files,
#             error=None if response.exit_code == 0 else truncated_stderr,
#         )

#         # Get tool ID from database
#         tool_id = get_tool_by_name(
#             PythonTool.__name__, run_context.context.run_dependencies.db_session
#         ).id

#         # Store in iteration answer
#         run_context.context.global_iteration_responses.append(
#             IterationAnswer(
#                 tool=PythonTool.__name__,
#                 tool_id=tool_id,
#                 iteration_nr=index,
#                 parallelization_nr=0,
#                 question="Execute Python code",
#                 reasoning="Executing Python code in secure environment",
#                 answer=_combine_outputs(truncated_stdout, truncated_stderr),
#                 cited_documents={},
#                 file_ids=generated_file_ids,
#                 additional_data={
#                     "stdout": truncated_stdout,
#                     "stderr": truncated_stderr,
#                     "code": code,
#                 },
#             )
#         )

#         return result

#     except Exception as e:
#         logger.error(f"Python execution failed: {e}")
#         error_msg = str(e)

#         # Emit error delta
#         emitter.emit(
#             Packet(
#                 ind=index,
#                 obj=PythonToolDelta(
#                     type="python_tool_delta",
#                     stdout="",
#                     stderr=error_msg,
#                     file_ids=[],
#                 ),
#             )
#         )

#         # Return error result
#         return LlmPythonExecutionResult(
#             stdout="",
#             stderr=error_msg,
#             exit_code=-1,
#             timed_out=False,
#             generated_files=[],
#             error=error_msg,
#         )


# @function_tool
# def python(
#     run_context: RunContextWrapper[ChatTurnContext],
#     code: str,
# ) -> str:
#     """
#     When you send a message containing Python code to python, it will be executed in a \
#     isolated sandbox. python will respond with the output of the execution or time \
#     out after 60.0 seconds.

#     Any files uploaded to the chat will be automatically available in the execution \
#     environment current directory.

#     The current directory in the file system can be used to save and persist user files. \
#     Internet access for this session is disabled. Do not make external web \
#     requests or API calls as they will fail.

#     Files written to the current directory will be returned with a `file_link`. Use this \
#     to give the user a way to download the file OR to display generated images.

#     Use `openpyxl` to read and write Excel files. You have access to libraries like \
#     numpy, pandas, scipy, matplotlib, and PIL.

#     IMPORTANT: each call to this tool is independent. Variables from previous calls will NOT \
#     be available in the current call.

#     Args:
#         code: Python source code to execute

#     Returns:
#         JSON string containing stdout, stderr, exit code, and any files \
#         written to the file system.
#     """
#     # NOTE: `IMPORTANT: each call to this tool is independent` is for the GPT family of models,
#     # which have been fine-tuned to use a jupyter notebook which remembers variables from previous cells.

#     client = CodeInterpreterClient()
#     result = _python_execution_core(run_context, code, client)

#     # Serialize and return
#     adapter = TypeAdapter(LlmPythonExecutionResult)
#     return adapter.dump_json(result).decode()
