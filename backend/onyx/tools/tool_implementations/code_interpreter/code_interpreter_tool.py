import os
from collections.abc import Generator
from typing import Any
from typing import cast

from e2b_code_interpreter import Sandbox
from langchain_core.messages import SystemMessage
from pydantic import BaseModel

from onyx.chat.chat_utils import combine_message_chain
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.configs.model_configs import GEN_AI_HISTORY_CUTOFF
from onyx.file_store.models import InMemoryChatFile
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.llm.utils import message_to_string
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger

logger = setup_logger()

CODE_INTERPRETER_TOOL_DESCRIPTION = """
Executes Python code in a secure sandbox for data analysis and processing. Use this tool for:

DATA PROCESSING & ANALYSIS:
- Process CSV, Excel, JSON, or any data files
- Extract insights, statistics, and summaries from raw data
- Clean, transform, and analyze datasets
- Perform exploratory data analysis (EDA)
- Generate visualizations (charts, graphs, plots)

COMPUTATIONS & ALGORITHMS:
- Run mathematical calculations and statistical analysis
- Execute complex algorithms or simulations
- Create data visualizations and reports
- Export results to files (CSV, JSON, images)

AUTOMATED WORKFLOW:
- When users upload data files, automatically analyzes structure and generates appropriate Python code
- Executes code in isolated environment with pandas, numpy, matplotlib, seaborn, scikit-learn, and more
- Automatically truncates large files to manageable sizes (500 lines) to prevent token limit issues

This is the primary tool for any data processing, extraction, analysis, or computational tasks
involving structured data files.
"""

CODE_INTERPRETER_RESPONSE_ID = "code_interpreter_response"
CODE_INTERPRETER_EXECUTION_ID = "code_interpreter_execution"

# Configuration for file truncation
MAX_FILE_LINES = 500
MAX_FILE_SIZE_BYTES = 1024 * 1024  # 1MB

# Tool selection constants
YES_CODE_INTERPRETER = "Yes Code Interpreter"
SKIP_CODE_INTERPRETER = "Skip Code Interpreter"

CODE_INTERPRETER_TEMPLATE = f"""
Given the conversation history and a follow up query, determine if the system should call \
the code interpreter tool to better answer the latest user input.
Your default response is {SKIP_CODE_INTERPRETER}.

Respond "{YES_CODE_INTERPRETER}" if:
- The user is asking for data analysis, calculations, or computations
- The user wants to count, analyze, or process data from files (CSV, Excel, JSON, etc.)
- The user is asking for statistical analysis, visualizations, or data insights
- The user wants to perform mathematical operations or algorithms
- The user mentions specific data operations like "count", "sum", "average", "filter", etc.
- The user uploads data files and asks questions about the data
- The user wants to generate charts, graphs, or data visualizations

Conversation History:
{{chat_history}}

If you are at all unsure, respond with {SKIP_CODE_INTERPRETER}.
Respond with EXACTLY and ONLY "{YES_CODE_INTERPRETER}" or "{SKIP_CODE_INTERPRETER}"

Follow Up Input:
{{final_query}}
""".strip()


class CodeInterpreterOverrideKwargs(BaseModel):
    """Override kwargs for CodeInterpreterTool"""

    sandbox_id: str | None = None


class CodeExecutionResult(BaseModel):
    """Result of code execution"""

    code: str
    output: str
    error: str | None = None
    execution_time: float
    files_created: list[str] = []


class CodeInterpreterTool(Tool[CodeInterpreterOverrideKwargs]):
    _NAME = "run_code_interpreter"
    _DISPLAY_NAME = "Code Interpreter"
    _DESCRIPTION = CODE_INTERPRETER_TOOL_DESCRIPTION

    def __init__(
        self,
        answer_style_config: AnswerStyleConfig,
        prompt_config: PromptConfig,
        llm: LLM,
        fast_llm: LLM,
        files: list["InMemoryChatFile"] | None = None,
    ) -> None:
        self.answer_style_config = answer_style_config
        self.prompt_config = prompt_config
        self.llm = llm
        self.fast_llm = fast_llm
        self.files = files or []
        self._sandbox: Sandbox | None = None
        self._split_files: list[str] = []  # Track which files were split into chunks

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def description(self) -> str:
        return self._DESCRIPTION

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

    def _get_sandbox(self) -> Sandbox:
        """Get or create a sandbox instance"""
        if self._sandbox is None:
            try:
                self._sandbox = Sandbox(api_key=os.getenv("E2B_API_KEY"))
                logger.debug("Sandbox created successfully")
            except Exception as e:
                logger.error("Failed to create sandbox: %s", str(e))
                import traceback

                logger.error("Full traceback: %s", traceback.format_exc())
                raise
        else:
            logger.debug("Using existing sandbox instance")
        logger.debug("=== End Sandbox Creation Debug ===")
        return self._sandbox

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "Your request for data analysis. If files are uploaded, \
                            they will be automatically analyzed and used to generate Python code.",
                        },
                    },
                    "required": ["prompt"],
                },
            },
        }

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        execution_response = next(
            response
            for response in args
            if response.id == CODE_INTERPRETER_EXECUTION_ID
        )
        execution_result = cast(CodeExecutionResult, execution_response.response)

        # Create a comprehensive response that includes both code and results
        response_content = f"""
                            **Code Interpreter Execution**

                            **Code Executed:**
                            ```python
                            {execution_result.code}
                            ```

                            **Execution Results:**
                            - Output: {execution_result.output}
                            """

        # Add chunking information if any files were split
        if self._split_files:
            split_files_list = ", ".join(self._split_files)
            response_content += f"""
                            **File Processing Note:**
                            - The following files were split into chunks: {split_files_list}
                            - This enables processing of the complete dataset while avoiding token limit issues
                            - Each chunk contains up to 500 lines for optimal processing
                            """

        if execution_result.error:
            response_content += f"- Error: {execution_result.error}\n"

        if execution_result.files_created:
            response_content += (
                f"- Files created: {', '.join(execution_result.files_created)}\n"
            )

        if (
            hasattr(execution_result, "execution_time")
            and execution_result.execution_time
        ):
            response_content += (
                f"- Execution time: {execution_result.execution_time:.2f} seconds\n"
            )

        return response_content

    def run(
        self,
        override_kwargs: CodeInterpreterOverrideKwargs | None = None,
        **kwargs: str,
    ) -> Generator[ToolResponse, None, None]:
        user_prompt = cast(str, kwargs["prompt"])

        # Reset split files list for this execution
        self._split_files = []

        try:
            # Initialize the sandbox
            logger.debug("Initializing sandbox...")
            sandbox = self._get_sandbox()

            # If there are files, upload them to the sandbox and analyze them
            if self.files:
                logger.debug("Processing %d files", len(self.files))

                # Step 1: Upload files and get file info
                logger.debug("Step 1: Uploading files to sandbox...")
                file_info = self.get_file_info(self.files)

                # Step 2: Generate Python code based on analysis and user request
                next_prompt = self.construct_prompt(file_info, user_prompt)
                code = self.llm.invoke(next_prompt).text()

                # Clean the generated code to remove markdown formatting
                code = self.clean_generated_code(code)
            else:
                logger.debug(
                    "No files provided, generating code directly from user prompt"
                )
                # No files, generate code directly from user prompt
                code_prompt = f"""
                                if there is history file, use it to understand the data and the user request.
                                User request: {user_prompt}

                                Use python code to analyze the dataset based on my request and produces
                                right result accordingly.
                                Return only the Python code with correct format.
                                """
                logger.debug("Code generation prompt (no files): %s", code_prompt)
                code = self.llm.invoke(code_prompt).text()

                # Clean the generated code to remove markdown formatting
                code = self.clean_generated_code(code)
                logger.debug("Generated code (no files): %s", code)

            # Execute the code
            execution = sandbox.run_code(code, language="python")

            # Get any files that were created
            files_created = []
            try:
                files = sandbox.files.list("/")
                files_created = [
                    f.name
                    for f in files
                    if f.name.endswith((".png", ".jpg", ".jpeg", ".csv", ".json"))
                ]
            except Exception as e:
                logger.warning(f"Could not list files: {e}")

            logger.error("Execution code: %s", code)
            if execution.error:
                print("AI-generated code had an error.")
                print(execution.error.name)
                print(execution.error.value)
                print(execution.error.traceback)

            execution_result = CodeExecutionResult(
                code=code,
                output=execution.logs.to_json(),
                error=execution.error if hasattr(execution, "error") else None,
                execution_time=(
                    execution.execution_time
                    if hasattr(execution, "execution_time")
                    else 0.0
                ),
                files_created=files_created,
            )

            yield ToolResponse(
                id=CODE_INTERPRETER_EXECUTION_ID,
                response=execution_result,
            )

        except Exception as e:
            logger.error("Error in CodeInterpreterTool.run: %s", str(e))
            logger.error("Exception type: %s", type(e).__name__)
            import traceback

            logger.error("Traceback: %s", traceback.format_exc())
            execution_result = CodeExecutionResult(
                code=code,
                output="",
                error=str(e),
                execution_time=0.0,
                files_created=[],
            )

            yield ToolResponse(
                id=CODE_INTERPRETER_EXECUTION_ID,
                response=execution_result,
            )

    def construct_prompt(self, file_info: list[str], user_prompt: str) -> str:
        #                         Based on the following CSV file analysis:
        # {initial_result}

        # Check if any files were split into chunks
        chunking_note = ""
        if self._split_files:
            split_files_list = ", ".join(self._split_files)
            chunking_note = f"""
NOTE: The following files were automatically split into smaller chunks to enable
processing of the full dataset: {split_files_list}
Each chunk contains up to 500 lines. To analyze the complete dataset, you should:
1. Process each chunk separately and combine the results
2. Use pandas to read all chunks and concatenate them: df = pd.concat([pd.read_csv(chunk) for chunk in chunk_files])
3. Perform your analysis on the combined dataset
"""

        next_prompt = f"""
                        Based on User request: {user_prompt}
                        Available files in the sandbox: {file_info}
                        {chunking_note}
                        Understand the column names, data types, and what each of them represents in the file.

                        Please write Python code that:
                        1. Use fileread to read the CSV file(s) from the sandbox using pandas
                        2. If multiple chunks exist for the same file, combine them using pd.concat()
                        3. Performs the analysis requested by the user on the complete dataset
                        4. Provides clear output and visualizations if appropriate
                        5. Handles any errors gracefully
                        6. If working with chunked data, combine results from all chunks for accurate analysis

                        Return only the Python code with correct format and no explanations.
                        """
        return next_prompt

    def get_file_info(self, files: list[InMemoryChatFile]) -> list[str]:
        sandbox = self._get_sandbox()

        # Upload files to sandbox and create file info
        file_info = []
        logger.info(f"Processing {len(files)} files")

        for file in files:
            logger.info(
                f"Processing file: {file.filename} (type: {file.file_type.value}, size: {len(file.content)} bytes)"
            )

            if file.file_type.value in ["csv", "document", "plain_text"]:
                # Truncate file content if necessary
                content = file.content
                try:
                    text_content = content.decode("utf-8")
                    lines = text_content.split("\n")
                    if len(lines) > MAX_FILE_LINES:
                        logger.info(
                            f"Truncating file {file.filename} to {MAX_FILE_LINES} lines"
                        )
                        lines = lines[:MAX_FILE_LINES]
                        text_content = "\n".join(lines)
                        content = text_content.encode("utf-8")
                    if len(content) > MAX_FILE_SIZE_BYTES:
                        logger.info(
                            f"Truncating file {file.filename} to {MAX_FILE_SIZE_BYTES} bytes"
                        )
                        content = content[:MAX_FILE_SIZE_BYTES]
                except Exception as e:
                    logger.warning(
                        f"Could not decode file {file.filename} as UTF-8, using original content: {e}"
                    )
                    if len(content) > MAX_FILE_SIZE_BYTES:
                        content = content[:MAX_FILE_SIZE_BYTES]

                # Upload the (possibly truncated) file to the sandbox
                try:
                    if file.file_type.value == "csv":
                        uploaded_file_info = sandbox.files.write(file.filename, content)
                        file_info.append(f"- CSV file: {uploaded_file_info.path}")
                    elif file.file_type.value == "document":
                        uploaded_file_info = sandbox.files.write(
                            file.filename, content.decode("utf-8")
                        )
                        file_info.append(f"- Document: {uploaded_file_info.path}")
                    elif file.file_type.value == "plain_text":
                        uploaded_file_info = sandbox.files.write(
                            file.filename, content.decode("utf-8")
                        )
                        file_info.append(f"- Text file: {uploaded_file_info.path}")
                    logger.info(f"Successfully uploaded file: {file.filename}")
                except Exception as e:
                    logger.error(f"Failed to upload file {file.filename}: {str(e)}")
                    continue

        logger.info(f"File info result: {file_info}")
        return file_info

    def run_ai_generated_code(self, ai_generated_code: str):
        logger.info("Running the code in the sandbox....")
        logger.debug("Code to execute: %s", ai_generated_code)
        try:
            execution = self._sandbox.run_code(ai_generated_code)
            logger.info("Code execution finished!")
            logger.debug("Execution result: %s", execution)
            return execution
        except Exception as e:
            logger.error("Code execution failed: %s", str(e))
            raise

    def final_result(self, *args: ToolResponse) -> dict[str, Any]:
        execution_response = next(
            response
            for response in args
            if response.id == CODE_INTERPRETER_EXECUTION_ID
        )
        execution_result = cast(CodeExecutionResult, execution_response.response)
        return execution_result.model_dump()

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        # Find the code interpreter execution response
        execution_response = next(
            (
                response
                for response in tool_responses
                if response.id == CODE_INTERPRETER_EXECUTION_ID
            ),
            None,
        )

        if execution_response:
            execution_result = cast(CodeExecutionResult, execution_response.response)

            # Build a comprehensive summary including both code and results
            result_summary = f"""
Code Interpreter Execution Summary:

**Code Executed:**
```python
{execution_result.code}
```

**Execution Results:**
- Output: {execution_result.output}
"""

            # Add chunking information if any files were split
            if self._split_files:
                split_files_list = ", ".join(self._split_files)
                result_summary += f"""

**File Processing Note:**
- The following files were split into chunks: {split_files_list}
- This enables processing of the complete dataset while avoiding token limit issues
- Each chunk contains up to 500 lines for optimal processing
"""

            if execution_result.error:
                result_summary += f"- Error: {execution_result.error}\n"

            if execution_result.files_created:
                result_summary += (
                    f"- Files created: {', '.join(execution_result.files_created)}\n"
                )

            if (
                hasattr(execution_result, "execution_time")
                and execution_result.execution_time
            ):
                result_summary += (
                    f"- Execution time: {execution_result.execution_time:.2f} seconds\n"
                )

            # Add the execution summary to the system prompt and instruct the LLM
            # to include it in the response
            system_message = SystemMessage(
                content=f"""
{result_summary}

IMPORTANT: When responding to the user, make sure to include the above code interpreter
execution details in your response. Show the user the code that was executed and the results obtained.
"""
            )
            prompt_builder.update_system_prompt(system_message)

        # Add tool call information if using tool calling LLM
        if using_tool_calling_llm:
            prompt_builder.append_message(tool_call_summary.tool_call_request)
            prompt_builder.append_message(tool_call_summary.tool_call_result)

        return prompt_builder

    def clean_generated_code(self, code: str) -> str:
        """Clean generated code to remove markdown formatting and extract pure Python code"""
        # Remove markdown code block markers
        lines = code.split("\n")
        cleaned_lines = []
        in_code_block = False

        for line in lines:
            # Check for code block start/end markers
            if line.strip().startswith("```"):
                if line.strip() == "```" or line.strip().startswith("```python"):
                    in_code_block = not in_code_block
                    continue  # Skip the marker line
                else:
                    # If it's a different language marker, skip it
                    continue

            # Only include lines that are inside a code block or if no code block markers found
            if not in_code_block or in_code_block:
                cleaned_lines.append(line)

        cleaned_code = "\n".join(cleaned_lines)

        # Remove any leading/trailing whitespace
        cleaned_code = cleaned_code.strip()

        # If the code is empty after cleaning, return the original
        if not cleaned_code:
            return code

        return cleaned_code

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        args = {"prompt": query}
        if force_run:
            return args

        # If there are files, always use code interpreter
        if self.files:
            logger.debug("Files present, using CodeInterpreterTool")
            return args

        history_str = combine_message_chain(
            messages=history, token_limit=GEN_AI_HISTORY_CUTOFF
        )
        prompt = CODE_INTERPRETER_TEMPLATE.format(
            chat_history=history_str,
            final_query=query,
        )
        use_code_interpreter_tool_output = message_to_string(llm.invoke(prompt))

        logger.debug(
            f"Evaluated if should use CodeInterpreterTool: {use_code_interpreter_tool_output}"
        )
        if (
            YES_CODE_INTERPRETER.split()[0]
        ).lower() in use_code_interpreter_tool_output.lower():
            return args

        return None
