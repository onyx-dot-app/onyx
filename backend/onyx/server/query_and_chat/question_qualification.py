import logging
from pathlib import Path
from typing import Any

import yaml
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.configs.app_configs import ENABLE_QUESTION_QUALIFICATION
from onyx.llm.factory import get_default_llms
from onyx.llm.interfaces import LLM
from onyx.llm.utils import message_to_string

logger = logging.getLogger(__name__)


class QuestionQualificationResponse(BaseModel):
    """Pydantic model for structured LLM response."""

    blocked: bool = Field(description="Whether the question should be blocked")
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0, where 1.0 means 'should block'", ge=0.0, le=1.0
    )
    matched_index: int = Field(
        description="Index of matched blocked question, -1 if no match", ge=-1
    )


class QuestionQualificationResult:
    def __init__(
        self,
        is_blocked: bool,
        similarity_score: float = 0.0,
        standard_response: str = "",
        matched_question: str = "",
        matched_question_index: int = -1,
        reasoning: str = "",
    ):
        self.is_blocked = is_blocked
        self.similarity_score = similarity_score
        self.standard_response = standard_response
        self.matched_question = matched_question
        self.matched_question_index = matched_question_index
        self.reasoning = reasoning


# LangChain Pydantic output parser
output_parser = PydanticOutputParser(pydantic_object=QuestionQualificationResponse)

# Minimal task-focused prompt with parser format instructions
QUESTION_QUALIFICATION_PROMPT = """Analyze if the user question asks about any blocked topic.

BLOCKED QUESTIONS:
{blocked_questions}

USER QUESTION: {user_question}

Determine semantic similarity between the user question and blocked questions. Consider variations in wording and phrasing.

{format_instructions}"""


class QuestionQualificationService:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # Configuration
        self.config_path = (
            Path(__file__).parent / "../../configs/question_qualification.yaml"
        )
        self.threshold = 0.85  # Now used as confidence threshold
        self.standard_response = (
            "I’m sorry, but I can’t answer this request due to policy restrictions."
        )

        # Store questions
        self.questions = []

        # Track if config has been loaded
        self._config_loaded = False

        # Load configuration only if enabled
        if ENABLE_QUESTION_QUALIFICATION:
            self._load_config()

        # Mark as initialized so subsequent __init__ calls don't reset state
        self._initialized = True

    def _load_config(self) -> bool:
        """Load configuration from YAML file."""
        if self._config_loaded:
            return True
        try:
            if not self.config_path.exists():
                logger.warning(
                    f"Question qualification config file not found: {self.config_path}"
                )
                self._config_loaded = True
                return False

            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            if not config:
                self._config_loaded = True
                return False

            # Load settings
            settings = config.get("settings", {})
            self.threshold = settings.get("threshold", 0.85)
            self.standard_response = settings.get(
                "standard_response", "I am sorry, but I cannot answer this question."
            )

            # Load questions
            questions_config = config.get("questions", [])
            self.questions = []

            for q_config in questions_config:
                if isinstance(q_config, dict) and "question" in q_config:
                    self.questions.append(q_config["question"])
                elif isinstance(q_config, str):
                    self.questions.append(q_config)

            logger.info(
                f"Question qualification service initialized with {len(self.questions)} questions, "
                f"threshold={self.threshold}, env_enabled={ENABLE_QUESTION_QUALIFICATION}"
            )
            self._config_loaded = True
            return True

        except Exception as e:
            logger.error(f"Error loading question qualification config: {e}")
            self._config_loaded = True  # Mark as loaded to avoid repeated attempts
            return False

    def _get_fast_llm(self) -> LLM:
        """Get the fast LLM for question qualification."""
        _, fast_llm = get_default_llms()
        return fast_llm

    def is_enabled(self) -> bool:
        """Check if question qualification is enabled by environment variable."""
        return ENABLE_QUESTION_QUALIFICATION

    def qualify_question(
        self, question: str, db_session: Session
    ) -> QuestionQualificationResult:
        """
        Check if a question should be blocked using fast LLM with structured JSON output.
        """
        # Check environment variable
        if not ENABLE_QUESTION_QUALIFICATION:
            logger.debug("Question qualification disabled by environment variable")
            return QuestionQualificationResult(is_blocked=False, similarity_score=0.0)

        # Lazy-load config if not already loaded
        if not self._config_loaded:
            self._load_config()

        try:
            logger.info(f"Question qualification: question = {question}")

            if not self.questions:
                logger.warning("No blocked questions loaded")
                return QuestionQualificationResult(
                    is_blocked=False, similarity_score=0.0
                )

            # Get fast LLM
            fast_llm = self._get_fast_llm()
            logger.debug(
                f"Using LLM: {fast_llm.config.model_name} ({fast_llm.config.model_provider})"
            )

            # Format blocked questions with indices
            blocked_questions_text = "\n".join(
                f"{i}: {q}" for i, q in enumerate(self.questions)
            )

            # Create minimal task-focused prompt
            prompt = QUESTION_QUALIFICATION_PROMPT.format(
                blocked_questions=blocked_questions_text,
                user_question=question,
                format_instructions=output_parser.get_format_instructions(),
            )

            # Get response using LangChain Pydantic output parser
            response = fast_llm.invoke(
                prompt,
                max_tokens=200,  # Increased for structured JSON output with schema
            )

            # Parse using LangChain output parser
            try:
                parsed_response = output_parser.parse(message_to_string(response))

                is_blocked = parsed_response.blocked
                confidence = parsed_response.confidence
                matched_index = parsed_response.matched_index

                # Get matched question if available
                matched_question = ""
                if matched_index >= 0 and matched_index < len(self.questions):
                    matched_question = self.questions[matched_index]

                # Log detailed information including LLM used
                logger.info(
                    f"Question qualification: blocked={is_blocked}, "
                    f"confidence={confidence:.3f}, threshold={self.threshold} | "
                    f"LLM: {fast_llm.config.model_name}"
                )
                if matched_question:
                    logger.info(
                        f"Matched blocked question (index {matched_index}): '{matched_question[:100]}...'"
                    )

                # Apply threshold
                final_blocked = is_blocked and confidence >= self.threshold

                if final_blocked:
                    logger.info(
                        f"Question blocked by LLM analysis: confidence {confidence:.3f} >= {self.threshold}"
                    )

                standard_response = self.standard_response if final_blocked else ""
                return QuestionQualificationResult(
                    is_blocked=final_blocked,
                    similarity_score=confidence,
                    standard_response=standard_response,
                    matched_question=matched_question,
                    matched_question_index=matched_index,
                    reasoning="",  # No reasoning in structured output
                )

            except Exception as e:
                response_text = message_to_string(response)
                logger.error(
                    f"Error parsing LangChain output: {e}, response: {response_text}"
                )
                # Fallback to safe default
                return QuestionQualificationResult(
                    is_blocked=False, similarity_score=0.0
                )

        except Exception as e:
            logger.error(f"Error in question qualification: {e}")
            # On error, allow the question through to avoid blocking legitimate queries
            return QuestionQualificationResult(is_blocked=False, similarity_score=0.0)

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the question qualification service."""
        return {
            "enabled": ENABLE_QUESTION_QUALIFICATION,
            "num_blocked_questions": len(self.questions),
            "threshold": self.threshold,
            "standard_response": self.standard_response,
        }
