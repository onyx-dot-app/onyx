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
from langchain_core.messages import BaseMessage, HumanMessage
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro
from onyx.agents.agent_search.document_chat.states import RegulatoryReviewComments

logger = setup_logger()

REGULATORY_REVIEW_RESPONSE_ID = "regulatory_review_response"
DOCUMENT_CONTENT_FIELD = "document_content"
REGULATORY_BODY_FIELD = "regulatory_body"

REGULATORY_REVIEW_DESCRIPTION = """
Use this tool to conduct a regulatory review on documents. This tool reviews document content from the perspective of a regulatory body (e.g., FDA) and provides feedback on compliance with government guidelines. This should tool does not require any documents be included in the request.
"""

class RegulatoryReviewTool(Tool):
    """Tool for reviewing documents from a regulatory perspective."""

    _NAME = "regulatory_review"
    _DISPLAY_NAME = "Regulatory Review Tool"
    _DESCRIPTION = REGULATORY_REVIEW_DESCRIPTION
    _PARAMETERS = {
        REGULATORY_BODY_FIELD: {
            "type": "string",
            "description": "The regulatory body to review from (e.g., 'FDA', 'EMA', 'MHRA')",
        },
    }
    _REQUIRED_PARAMETERS = []

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

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        REGULATORY_BODY_FIELD: {
                            "type": "string",
                            "description": "The regulatory body to review from (e.g., 'FDA', 'EMA', 'MHRA')",
                        },
                    },
                    "required": [REGULATORY_BODY_FIELD],
                },
            },
        }

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        review_response = next(
            response for response in args if response.id == REGULATORY_REVIEW_RESPONSE_ID
        )
        return json.dumps(review_response.response)

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[Any],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        # """Get arguments for non-tool calling LLM."""
        # if not self.document_content:
        #     return None
            
        # return {
        #     "regulatory_body": "FDA",  # Default to FDA
        #     "document_content": self.document_content
        # }
                # Document editor is typically explicitly invoked, not automatically
        return None

    """Actual tool execution"""

    def _run(
        self,
        regulatory_body: str,
        state: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Review document content from a regulatory perspective.
        
        Args:
            regulatory_body: The regulatory body to review from
            state: The current state containing document content
            **kwargs: Additional arguments including document_content
            
        Returns:
            Dict containing the regulatory review feedback
        """
        # Try to get document content from state first (most reliable source)
        document_content = None
        if state:
            # Prefer edited text if available, then original text
            document_content = state.get("edited_text") or state.get("original_text")
        
        # Fall back to kwargs if state doesn't have content
        if not document_content:
            document_content = kwargs.get("document_content")
            
        # Last resort: use instance variable
        if not document_content:
            document_content = self.document_content

        if not document_content:
            raise ValueError("No document content provided for regulatory review")
        
        logger.info(f"Reviewing document {document_content} from {regulatory_body} perspective")
        
        regulatory_review_prompt = f"""
        You are a senior reviewer at the {regulatory_body}. Your task is to review the provided document content and provide detailed feedback on its compliance with {regulatory_body} guidelines and regulations.

        Focus on the following aspects:
        1. Regulatory compliance
        2. Documentation completeness
        3. Scientific accuracy
        4. Risk assessment
        5. Labeling and claims
        6. Data quality and integrity
        7. Manufacturing and quality control
        8. Safety considerations

        For each finding, specify:
        - Whether it meets or does not meet regulatory requirements
        - The specific regulation or guideline reference (if applicable)
        - The severity of the issue (Critical, Major, Minor, or Observation)
        - Recommended actions to address the finding

        DOCUMENT CONTENT TO REVIEW:
        {document_content}
        """
        
        if not self.llm:
            raise ValueError("LLM is required for regulatory review")
        
        msg = [HumanMessage(content=regulatory_review_prompt)]
        
        structured_response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "regulatory_review",
                "schema": {
                    "type": "object",
                    "properties": {
                        "findings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "category": {
                                        "type": "string",
                                        "description": "The category of the finding (e.g., 'Regulatory Compliance', 'Documentation', etc.)"
                                    },
                                    "finding": {
                                        "type": "string",
                                        "description": "Description of the finding"
                                    },
                                    "severity": {
                                        "type": "string",
                                        "description": "Severity level (Critical, Major, Minor, or Observation)"
                                    },
                                    "regulation_reference": {
                                        "type": "string",
                                        "description": "Reference to specific regulation or guideline"
                                    },
                                    "recommendation": {
                                        "type": "string",
                                        "description": "Recommended action to address the finding"
                                    }
                                },
                                "required": ["category", "finding", "severity", "recommendation"]
                            }
                        },
                        "summary": {
                            "type": "string",
                            "description": "Overall summary of the regulatory review"
                        }
                    },
                    "required": ["findings", "summary"]
                }
            }
        }
        
        response = self.llm.invoke(
            msg,
            structured_response_format=structured_response_format,
        )
        
        # Parse the response content
        try:
            if isinstance(response.content, str):
                review_result = json.loads(response.content)
            else:
                review_result = response.content
                
            if not isinstance(review_result, dict):
                raise ValueError(f"Expected dict response, got {type(review_result)}")
                
            if "findings" not in review_result or "summary" not in review_result:
                raise ValueError("Response missing required fields: findings and summary")
                
        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")
            # Provide a default response if parsing fails
            review_result = {
                "findings": [{
                    "category": "Error",
                    "finding": "Failed to parse regulatory review response",
                    "severity": "Critical",
                    "recommendation": "Please try the review again"
                }],
                "summary": "Error occurred during regulatory review"
            }
        
        # Create RegulatoryReviewComments object
        review_comments = RegulatoryReviewComments(
            document_content=document_content,
            regulatory_body=regulatory_body,
            findings=review_result["findings"],
            summary=review_result["summary"]
        )
        
        return {
            "review_comments": review_comments.model_dump(),
            "findings": review_result["findings"],
            "summary": review_result["summary"]
        }

    def run(
        self, override_kwargs: Optional[Dict[str, Any]] = None, **llm_kwargs: Any
    ) -> Generator[ToolResponse, None, None]:
        """Run the regulatory review tool."""
        if override_kwargs is None:
            override_kwargs = {}
            
        # Ensure FDA is the default regulatory body if not specified
        if "regulatory_body" not in override_kwargs:
            override_kwargs["regulatory_body"] = "FDA"
            
        # Add document_content to override_kwargs if it exists in the instance
        if self.document_content and "document_content" not in override_kwargs:
            override_kwargs["document_content"] = self.document_content
            
        result = self._run(**override_kwargs)
        
        yield ToolResponse(
            id=REGULATORY_REVIEW_RESPONSE_ID,
            response=result,
        )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        """Get the final result of the regulatory review."""
        review_response = next(
            response for response in args if response.id == REGULATORY_REVIEW_RESPONSE_ID
        )
        return review_response.response

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        """Build the next prompt for the LLM."""
        if using_tool_calling_llm:
            prompt_builder.append_message(tool_call_summary.tool_call_request)
            prompt_builder.append_message(tool_call_summary.tool_call_result)
        return prompt_builder
