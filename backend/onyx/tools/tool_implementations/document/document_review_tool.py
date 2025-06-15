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

DOCUMENT_REVIEW_RESPONSE_ID = "document_review_response"
SEARCH_RESULTS_FIELD = "search_results"
REVIEW_TYPE_FIELD = "review_type"

DOCUMENT_REVIEW_DESCRIPTION = """
Reviews documents as an FDA regulator for submission requirements and compliance. Use this tool when you need to \
evaluate whether a document meets FDA regulatory standards, identify potential compliance issues, or provide \
regulatory feedback. When multiple documents are available, you must specify which document to review using the \
document_id parameter.
"""


class ReviewFinding(BaseModel):
    severity: Literal["critical", "major", "minor", "observation"]
    category: str  # e.g., "Clinical Data", "Manufacturing", "Labeling", "Safety"
    issue: str
    description: str
    regulatory_reference: str  # CFR section, FDA guidance, etc.
    location: str  # where in the document this was found
    recommendation: str

    model_config = ConfigDict(extra="forbid")


class DocumentReviewResult(BaseModel):
    overall_assessment: Literal["compliant", "needs_revision", "major_deficiencies", "not_approvable"]
    findings: list[ReviewFinding]
    summary: str
    recommendations: list[str]
    regulatory_pathway: str  # e.g., "510(k)", "PMA", "De Novo", "ANDA"
    estimated_review_timeline: str
    next_steps: list[str]

    model_config = ConfigDict(extra="forbid")


class DocumentReviewTool(Tool):
    """Tool for reviewing documents as an FDA regulator."""

    _NAME = "document_review"
    _DISPLAY_NAME = "Document Review Tool"
    _DESCRIPTION = DOCUMENT_REVIEW_DESCRIPTION
    _PARAMETERS = {
        SEARCH_RESULTS_FIELD: {
            "type": "string",
            "description": "Results from our Agentic Search tool to provide context (use '' if none)",
        },
        REVIEW_TYPE_FIELD: {
            "type": "string",
            "description": "Type of FDA review to conduct (e.g., '510k', 'PMA', 'ANDA', 'IND', 'NDA', 'BLA', 'general')",
        },
        "document_id": {
            "type": "string",
            "description": "ID of the specific document to review (required when multiple documents are available)",
        },
    }
    _REQUIRED_PARAMETERS = [SEARCH_RESULTS_FIELD, REVIEW_TYPE_FIELD, "document_id"]

    def __init__(
        self,
        db_session=None,
        user: User | None = None,
        persona: Persona | None = None,
        prompt_config: PromptConfig | None = None,
        llm: LLM | None = None,
        fast_llm: LLM | None = None,
        answer_style_config: AnswerStyleConfig | None = None,
        documents: dict[str, str] | None = None,
    ) -> None:
        self.user = user
        self.persona = persona
        self.prompt_config = prompt_config
        self.llm = llm
        self.fast_llm = fast_llm
        self.db_session = db_session
        self.answer_style_config = answer_style_config
        self.documents = documents or {}

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
        required_params = [SEARCH_RESULTS_FIELD, REVIEW_TYPE_FIELD, "document_id"]

        # Add available document IDs to the description
        document_id_description = f"ID of the specific document to review (choose from: {list(self.documents.keys())})"

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
                        REVIEW_TYPE_FIELD: {
                            "type": "string",
                            "description": "Type of FDA review to conduct (e.g., '510k', 'PMA', 'ANDA', 'IND', 'NDA', 'BLA', 'general')",
                        },
                        "document_id": {
                            "type": "string",
                            "description": document_id_description,
                        },
                    },
                    "required": required_params,
                },
            },
        }

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        review_response = next(
            response for response in args if response.id == DOCUMENT_REVIEW_RESPONSE_ID
        )
        return json.dumps(review_response.response)

    """For LLMs that don't support tool calling"""

    def get_args_for_non_tool_calling_llm(
        self, query: str, history: list[Any], llm: LLM, force_run: bool = False
    ) -> dict[str, Any] | None:
        # Document review is typically explicitly invoked, not automatically
        return None

    """Actual tool execution"""

    def _run(
        self, search_results: str | None, review_type: str, document_id: str, **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Review document as an FDA regulator.

        Args:
            search_results: Search results for context
            review_type: Type of FDA review to conduct
            document_id: ID of document to review (required)

        Returns:
            Dict containing the result of the review operation
        """
        logger.info(f"Reviewing document with review type: {review_type}")

        # Validate document selection and get document content
        if not document_id:
            raise ValueError(f"document_id is required. Choose from: {list(self.documents.keys())}")
        if document_id not in self.documents:
            raise ValueError(f"Document ID '{document_id}' not found. Available documents: {list(self.documents.keys())}")
        if not self.documents:
            raise ValueError("No documents available for review")

        document_content = self.documents[document_id]
        logger.info(f"Reviewing document with ID: {document_id}")

        # Create a prompt for the LLM to review the document as an FDA regulator
        document_review_prompt = f"""
        You are an experienced FDA regulator conducting a comprehensive review of a regulatory submission document.

        DOCUMENT CONTENT:
        {document_content}

        REVIEW TYPE: {review_type.upper()}

        INSTRUCTIONS:
        As an FDA regulator, you must conduct a thorough review of this document for compliance with FDA regulations.
        Your review should follow FDA guidelines and regulatory standards.

        Based on the review type "{review_type}", focus on the specific requirements for that submission type:

        - 510(k): Substantial equivalence, predicate devices, performance testing
        - PMA: Safety and effectiveness, clinical data, risk-benefit analysis
        - ANDA: Bioequivalence, chemistry manufacturing controls, labeling
        - IND: Clinical protocol, investigator qualifications, safety data
        - NDA/BLA: Comprehensive safety and efficacy data, manufacturing controls
        - General: Overall regulatory compliance assessment

        You must provide a structured review with:
        1. Overall assessment (compliant, needs_revision, major_deficiencies, not_approvable)
        2. Detailed findings categorized by severity (critical, major, minor, observation)
        3. Specific regulatory references (CFR sections, FDA guidance documents)
        4. Recommendations for addressing each finding
        5. Estimated review timeline
        6. Next steps for the applicant

        Each finding should include:
        - Severity level and category
        - Clear description of the issue
        - Specific regulatory reference
        - Location in the document where found
        - Recommendation for resolution

        SEARCH RESULTS (for additional context):
        {search_results}

        Provide your review in a structured format that follows FDA review practices.
        """

        # Use the LLM to generate the regulatory review
        if not self.llm:
            raise ValueError("LLM is required for document review")

        from langchain_core.messages import HumanMessage

        msg = [HumanMessage(content=document_review_prompt)]

        structured_response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "document_review",
                "schema": DocumentReviewResult.model_json_schema(),
                "strict": True,
            },
        }

        try:
            # Call the LLM to get the review with structured response format
            llm_response = self.llm.invoke(
                msg, structured_response_format=structured_response_format
            )
            assert isinstance(llm_response.content, str)
            # Parse the response into our Pydantic model
            review_result = DocumentReviewResult.model_validate_json(llm_response.content)

            # Return the result with required fields
            return {
                "success": True,
                "document_id": document_id,
                "review_type": review_type,
                "overall_assessment": review_result.overall_assessment,
                "findings": [finding.model_dump() for finding in review_result.findings],
                "summary": review_result.summary,
                "recommendations": review_result.recommendations,
                "regulatory_pathway": review_result.regulatory_pathway,
                "estimated_review_timeline": review_result.estimated_review_timeline,
                "next_steps": review_result.next_steps,
                "total_findings": len(review_result.findings),
                "critical_findings": len([f for f in review_result.findings if f.severity == "critical"]),
                "major_findings": len([f for f in review_result.findings if f.severity == "major"]),
                "minor_findings": len([f for f in review_result.findings if f.severity == "minor"]),
                "observations": len([f for f in review_result.findings if f.severity == "observation"]),
            }

        except Exception as e:
            logger.error(f"Error in document review: {e}")
            return {
                "success": False,
                "document_id": document_id,
                "review_type": review_type,
                "message": f"Failed to complete document review: {str(e)}",
                "overall_assessment": "review_failed",
                "findings": [],
                "summary": f"Review failed due to error: {str(e)}",
                "recommendations": [],
                "regulatory_pathway": "unknown",
                "estimated_review_timeline": "unknown",
                "next_steps": ["Contact FDA for assistance"],
                "total_findings": 0,
                "critical_findings": 0,
                "major_findings": 0,
                "minor_findings": 0,
                "observations": 0,
            }

    def run(
        self, override_kwargs: Optional[Dict[str, Any]] = None, **llm_kwargs: Any
    ) -> Generator[ToolResponse, None, None]:
        review_type = cast(str, llm_kwargs[REVIEW_TYPE_FIELD])
        search_results = cast(str, llm_kwargs.get(SEARCH_RESULTS_FIELD, ""))
        document_id = cast(str, llm_kwargs["document_id"])

        logger.info(f"Running document review with review type: {review_type}")

        # Execute the document review logic
        review_result = self._run(
            search_results=search_results, review_type=review_type, document_id=document_id
        )

        # Yield the response
        yield ToolResponse(id=DOCUMENT_REVIEW_RESPONSE_ID, response=review_result)

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        review_response = next(
            arg.response for arg in args if arg.id == DOCUMENT_REVIEW_RESPONSE_ID
        )
        return review_response

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

    # Sample document content (FDA submission example)
    sample_document = """
    510(k) Premarket Notification

    Device Name: Advanced Blood Glucose Monitor
    Classification: Class II Medical Device
    Product Code: NBW

    EXECUTIVE SUMMARY:
    This 510(k) submission requests clearance for the Advanced Blood Glucose Monitor,
    intended for use by healthcare professionals and patients for monitoring blood glucose levels.

    PREDICATE DEVICE:
    The predicate device is the Standard Glucose Monitor (K123456789), cleared by FDA on January 15, 2020.

    DEVICE DESCRIPTION:
    The Advanced Blood Glucose Monitor is a handheld device that measures blood glucose concentrations
    in capillary whole blood samples. The device uses electrochemical biosensor technology.

    INTENDED USE:
    The device is intended for the quantitative measurement of glucose in fresh capillary whole blood
    samples drawn from the fingertip, palm, or forearm of persons with diabetes mellitus.

    SUBSTANTIAL EQUIVALENCE:
    The subject device is substantially equivalent to the predicate device in terms of:
    - Intended use and indications for use
    - Technological characteristics
    - Performance characteristics

    PERFORMANCE TESTING:
    Clinical accuracy testing was performed according to ISO 15197:2013 standards.
    Results showed 98.5% of readings within ±15% of reference values.

    LABELING:
    Device labeling includes instructions for use, warnings, and precautions as required by 21 CFR 820.
    """

    # Initialize the LLM
    llm = DefaultMultiLLM(
        model_provider="openai",
        model_name="gpt-4o-mini",
        temperature=0.0,
        api_key=os.getenv("OPENAI_API_KEY"),
        max_input_tokens=10000,
    )

    # Create the document review tool
    reviewer = DocumentReviewTool(llm=llm, documents={"sample_510k": sample_document})

    # Example review
    logger.info("Starting FDA review")
    for response in reviewer.run(
        review_type="510k",
        search_results="",
        document_id="sample_510k"
    ):
        result = response.response
        print("\n=== FDA REGULATORY REVIEW ===")
        print(f"Document ID: {result['document_id']}")
        print(f"Review Type: {result['review_type']}")
        print(f"Overall Assessment: {result['overall_assessment']}")
        print(f"Regulatory Pathway: {result['regulatory_pathway']}")
        print(f"Estimated Timeline: {result['estimated_review_timeline']}")
        print(f"\nSummary: {result['summary']}")
        print("\nFindings Summary:")
        print(f"  - Critical: {result['critical_findings']}")
        print(f"  - Major: {result['major_findings']}")
        print(f"  - Minor: {result['minor_findings']}")
        print(f"  - Observations: {result['observations']}")

        if result['findings']:
            print("\nDetailed Findings:")
            for i, finding in enumerate(result['findings'], 1):
                print(f"{i}. [{finding['severity'].upper()}] {finding['category']}")
                print(f"   Issue: {finding['issue']}")
                print(f"   Reference: {finding['regulatory_reference']}")
                print(f"   Recommendation: {finding['recommendation']}")
                print()

    logger.info("Review complete")
