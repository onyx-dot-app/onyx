import json
from collections.abc import Generator
from typing import Any, Dict, Optional, cast

from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.llm.interfaces import LLM
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from langchain_core.messages import BaseMessage
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro

logger = setup_logger()

DOCUMENT_EDITOR_RESPONSE_ID = "document_editor_response"
TEXT_FIELD = "text"
INSTRUCTIONS_FIELD = "instructions"

DOCUMENT_EDITOR_DESCRIPTION = """
Edits text based on user instructions. Use this tool when the user wants to modify text content.
"""


class DocumentEditorTool(Tool):
    """Tool for editing text based on instructions."""

    _NAME = "document_editor"
    _DISPLAY_NAME = "Document Editor Tool"
    _DESCRIPTION = DOCUMENT_EDITOR_DESCRIPTION
    _PARAMETERS = {
        TEXT_FIELD: {
            "type": "string",
            "description": "The original text content to edit",
        },
        INSTRUCTIONS_FIELD: {
            "type": "string",
            "description": "Detailed instructions on what changes to make to the text",
        },
    }
    _REQUIRED_PARAMETERS = [TEXT_FIELD, INSTRUCTIONS_FIELD]

    def __init__(
        self,
        db_session=None,
        user: User | None = None,
        persona: Persona | None = None,
        prompt_config: PromptConfig | None = None,
        llm: LLM | None = None,
        fast_llm: LLM | None = None,
        answer_style_config: AnswerStyleConfig | None = None,
    ) -> None:
        self.user = user
        self.persona = persona
        self.prompt_config = prompt_config
        self.llm = llm
        self.fast_llm = fast_llm
        self.db_session = db_session
        self.answer_style_config = answer_style_config

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
                        TEXT_FIELD: {
                            "type": "string",
                            "description": "The original text content to edit",
                        },
                        INSTRUCTIONS_FIELD: {
                            "type": "string",
                            "description": "Detailed instructions on what changes to make to the text",
                        },
                    },
                    "required": [TEXT_FIELD, INSTRUCTIONS_FIELD],
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
        self,
        query: str,
        history: list[Any],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        # Document editor is typically explicitly invoked, not automatically
        return None

    """Actual tool execution"""

    def _run(
        self,
        text: str,
        instructions: str,
        **kwargs: Any,
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
        
        INSTRUCTIONS:
        {instructions}
        
        ORIGINAL TEXT:
        {text}
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
                    "schema": {
                        "type": "object",
                        "properties": {
                            "edited_text": {
                                "type": "string",
                                "description": "The edited version of the original text. This MUST be compilable HTML just like the input."
                            },
                            "summary": {
                                "type": "string",
                                "description": "A brief summary of the changes made to the text."
                            }
                        },
                        "required": ["edited_text", "summary"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                }
        }
        
        try:
            # Call the LLM to get the edited text with structured response format
            llm_response = self.llm.invoke(
                msg,
                structured_response_format=structured_response_format
            )
            
            # Get the structured response directly
            edit_result_str = llm_response.content
            
            edit_result = json.loads(edit_result_str)

            # When using structured_response_format, the content is already a dict
            # Ensure the required fields are present
            if "edited_text" not in edit_result or "summary" not in edit_result:
                raise ValueError("LLM response missing required fields: edited_text and/or summary")
            
            # Return the result with required fields
            return {
                "success": True,
                "original_text": text,
                "edited_text": edit_result.get("edited_text", ""),
                "message": edit_result.get("summary", ""),
                "edited": text != edit_result.get("edited_text", ""),
            }
            
        except Exception as e:
            logger.error(f"Error in document editing: {e}")
            return {
                "success": False,
                "original_text": text,
                "edited_text": text,
                "message": f"Failed to edit text: {str(e)}",
                "edited": False,
            }

    def run(
        self, override_kwargs: Optional[Dict[str, Any]] = None, **llm_kwargs: Any
    ) -> Generator[ToolResponse, None, None]:
        text = cast(str, llm_kwargs[TEXT_FIELD])
        instructions = cast(str, llm_kwargs[INSTRUCTIONS_FIELD])

        logger.info(f"Running document editor with instructions: {instructions}")
        
        # Execute the document editing logic
        edit_result = self._run(text=text, instructions=instructions)
        
        # Yield the response
        yield ToolResponse(
            id=DOCUMENT_EDITOR_RESPONSE_ID,
            response=edit_result,
        )

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
