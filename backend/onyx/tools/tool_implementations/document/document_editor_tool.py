import json
from collections.abc import Generator
from typing import Any, Dict, Literal, Optional, cast

from pydantic import BaseModel, ConfigDict

from onyx.chat.models import AnswerStyleConfig, PromptConfig
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.db.models import Persona, User
from onyx.llm.chat_llm import DefaultMultiLLM
from onyx.llm.interfaces import LLM
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro

logger = setup_logger()

DOCUMENT_EDITOR_RESPONSE_ID = "document_editor_response"
SEARCH_RESULTS_FIELD = "search_results"
INSTRUCTIONS_FIELD = "instructions"

DOCUMENT_EDITOR_DESCRIPTION = """
Edits a document based on user instructions. Use this tool when the user wants to modify text of a document or \
when the user wants to modify the document in some way.
"""


class DocumentChange(BaseModel):
    type: Literal["deletion", "addition"]
    context_before: str
    context_after: str
    text_to_delete: str
    text_to_add: str

    model_config = ConfigDict(extra="forbid")


class DocumentEditResult(BaseModel):
    changes: list[DocumentChange]
    summary: str

    model_config = ConfigDict(extra="forbid")


class DocumentEditorTool(Tool):
    """Tool for editing text based on instructions."""

    _NAME = "document_editor"
    _DISPLAY_NAME = "Document Editor Tool"
    _DESCRIPTION = DOCUMENT_EDITOR_DESCRIPTION
    _PARAMETERS = {
        SEARCH_RESULTS_FIELD: {
            "type": "string",
            "description": "Results from our Agentic Search tool to provide context (use '' if none)",
        },
        INSTRUCTIONS_FIELD: {
            "type": "string",
            "description": "Detailed instructions on what changes to make to the text",
        },
    }
    _REQUIRED_PARAMETERS = [SEARCH_RESULTS_FIELD, INSTRUCTIONS_FIELD]

    def __init__(
        self,
        db_session=None,
        user: User | None = None,
        persona: Persona | None = None,
        prompt_config: PromptConfig | None = None,
        llm: LLM | None = None,
        fast_llm: LLM | None = None,
        answer_style_config: AnswerStyleConfig | None = None,
        document_content: str | None = None,
    ) -> None:
        self.user = user
        self.persona = persona
        self.prompt_config = prompt_config
        self.llm = llm
        self.fast_llm = fast_llm
        self.db_session = db_session
        self.answer_style_config = answer_style_config
        self.document_content = document_content

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def description(self) -> str:
        return self._DESCRIPTION

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

    """For explicit tool calling"""

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        SEARCH_RESULTS_FIELD: {
                            "type": "string",
                            "description": "Results from our Agentic Search tool to provide context (provide empty string if none)",
                        },
                        INSTRUCTIONS_FIELD: {
                            "type": "string",
                            "description": "Detailed instructions on what changes to make to the document content",
                        },
                    },
                    "required": [SEARCH_RESULTS_FIELD, INSTRUCTIONS_FIELD],
                },
            },
        }

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        editor_response = next(
            response for response in args if response.id == DOCUMENT_EDITOR_RESPONSE_ID
        )
        return json.dumps(editor_response.response)

    """For LLMs that don't support tool calling"""

    def get_args_for_non_tool_calling_llm(
        self, query: str, history: list[Any], llm: LLM, force_run: bool = False
    ) -> dict[str, Any] | None:
        # Document editor is typically explicitly invoked, not automatically
        return None

    """Actual tool execution"""

    def _run(
        self, search_results: str | None, instructions: str, **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Edit text based on instructions.

        Args:
            text: The original text content to edit
            instructions: Detailed instructions on what changes to make

        Returns:
            Dict containing the result of the edit operation including the edited text
        """
        logger.info(f"Editing text with instructions: {instructions}")

        # Create a prompt for the LLM to edit the text
        document_editor_prompt = f"""
        You are a document editor assistant. Your task is to edit the provided HTML text according to the instructions.
        Do not add any newlines in the HTML edited_text output. The edited_text should be a valid HTML string.

        IMPORTANT: You must return a JSON object with the following structure:
        {{
            "changes": [
                // Array of changes, where each change has:
                {{
                    "type": "deletion" or "addition",
                    "context_before": "text before the change",
                    "context_after": "text after the change",
                    "text_to_delete": "text to remove (empty for additions)",
                    "text_to_add": "text to add (empty for deletions)"
                }}
            ],
            "summary": "A brief summary of all changes made"
        }}

        Example response format:
        {{
            "changes": [
                {{
                    "type": "deletion",
                    "context_before": "<p>This is a ",
                    "context_after": " text.</p>",
                    "text_to_delete": "sample",
                    "text_to_add": ""
                }},
                {{
                    "type": "addition",
                    "context_before": "<p>This is a ",
                    "context_after": " text.</p>",
                    "text_to_delete": "",
                    "text_to_add": "modified"
                }}
            ],
            "summary": "Changed 'sample' to 'modified' in the paragraph"
        }}

        INSTRUCTIONS:
        {instructions}

        Here are the results of our Agentic Search tool to provide context (possibly null):
        SEARCH RESULTS:
        {search_results}

        TEXT TO EDIT:
        {self.document_content}
        """

        # Use the LLM to edit the text
        if not self.llm:
            raise ValueError("LLM is required for document editing")

        from langchain_core.messages import HumanMessage

        msg = [HumanMessage(content=document_editor_prompt)]

        structured_response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "document_editor",
                "schema": DocumentEditResult.model_json_schema(),
                "strict": True,
            },
        }

        try:
            # Call the LLM to get the changes with structured response format
            llm_response = self.llm.invoke(
                msg, structured_response_format=structured_response_format
            )

            # Parse the response into our Pydantic model
            edit_result = DocumentEditResult.model_validate_json(llm_response.content)

            # Apply the changes to the original text
            edited_text = self.document_content
            changes = edit_result.changes

            # Sort changes in reverse order to avoid position shifting issues
            changes.sort(key=lambda x: len(x.context_before), reverse=True)

            for change in changes:
                # Find the position to make the change
                start_pos = edited_text.find(change.context_before)
                if start_pos == -1:
                    continue

                start_pos += len(change.context_before)
                end_pos = edited_text.find(change.context_after, start_pos)
                if end_pos == -1:
                    continue

                # Apply the change
                if change.type == "deletion":
                    if edited_text[start_pos:end_pos] == change.text_to_delete:
                        edited_text = (
                            edited_text[:start_pos]
                            + f"<deletion-mark>{change.text_to_delete}</deletion-mark>"
                            + edited_text[end_pos:]
                        )
                elif change.type == "addition":
                    edited_text = (
                        edited_text[:start_pos]
                        + f"<addition-mark>{change.text_to_add}</addition-mark>"
                        + edited_text[start_pos:]
                    )

            # Return the result with required fields
            return {
                "success": True,
                "original_text": self.document_content,
                "edited_text": edited_text,
                "message": edit_result.summary,
                "edited": self.document_content != edited_text,
            }

        except Exception as e:
            logger.error(f"Error in document editing: {e}")
            return {
                "success": False,
                "original_text": self.document_content,
                "edited_text": self.document_content,
                "message": f"Failed to edit text: {str(e)}",
                "edited": False,
            }

    def run(
        self, override_kwargs: Optional[Dict[str, Any]] = None, **llm_kwargs: Any
    ) -> Generator[ToolResponse, None, None]:
        instructions = cast(str, llm_kwargs[INSTRUCTIONS_FIELD])
        search_results = cast(str, llm_kwargs.get(SEARCH_RESULTS_FIELD, ""))

        logger.info(f"Running document editor with instructions: {instructions}")

        # Execute the document editing logic
        edit_result = self._run(
            search_results=search_results, instructions=instructions
        )

        # Yield the response
        yield ToolResponse(id=DOCUMENT_EDITOR_RESPONSE_ID, response=edit_result)

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        editor_response = next(
            arg.response for arg in args if arg.id == DOCUMENT_EDITOR_RESPONSE_ID
        )
        return editor_response

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        if using_tool_calling_llm:
            prompt_builder.append_message(tool_call_summary.tool_call_request)
            prompt_builder.append_message(tool_call_summary.tool_call_result)
        return prompt_builder


if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    # Load environment variables
    load_dotenv()

    # Sample document content
    sample_document = """
    <html>
    <body>
    <h1>Sample Document</h1>
    <p>This is a sample document.</p>
    </body>
    </html>
    """
    # Initialize the LLM
    llm = DefaultMultiLLM(
        model_provider="openai",
        model_name="gpt-4o-mini",
        temperature=0.0,
        api_key=os.getenv("OPENAI_API_KEY"),
        max_input_tokens=10000,
    )

    # Create the document editor tool
    editor = DocumentEditorTool(llm=llm, document_content=sample_document)

    # Example instructions
    instructions = """
    1. Change the title to "Modified Article"
    2. Add a new paragraph after the first paragraph
    3. Remove the third list item
    """

    # Run the tool
    logger.info("starting edit")
    for response in editor.run(instructions=instructions, search_results=""):
        result = response.response
        print("\nOriginal text:")
        print(result["original_text"])
        print("\nEdited text:")
        print(result["edited_text"])
        print("\nSummary of changes:")
        print(result["message"])
        print("\nWas the document edited?", result["edited"])

    logger.info("edit complete")
