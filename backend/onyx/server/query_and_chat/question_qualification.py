import json
import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.configs.app_configs import ENABLE_QUESTION_QUALIFICATION
from onyx.configs.app_configs import QUESTION_QUALIFICATION_MODEL
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.llm import fetch_default_provider
from onyx.llm.factory import get_default_llm
from onyx.llm.factory import llm_from_provider
from onyx.llm.interfaces import LLM


logger = logging.getLogger(__name__)


class QuestionQualificationResponse(BaseModel):
    """Pydantic model for structured LLM response."""

    block_confidence: float = Field(
        description=(
            "Confidence score between 0.0 and 1.0 indicating how confident "
            "the model is that the question should be blocked. "
            "0.0 means should not block, 1.0 means should block."
        ),
        ge=0.0,
        le=1.0,
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


# Minimal task-focused prompt for question qualification
QUESTION_QUALIFICATION_PROMPT = """Analyze if the user question asks about any blocked topic.

BLOCKED QUESTIONS:
{blocked_questions}

USER QUESTION: {user_question}

Determine semantic similarity between the user question and blocked questions. Consider variations in wording and phrasing.

Return a JSON object with exactly these fields:
- "block_confidence": a number between 0.0 and 1.0 indicating how confident you are
  that the question should be blocked (0.0 = not block, 1.0 = definitely block)
- "matched_index": the index number of the matched blocked question, or -1 if no match

Example response: {{"block_confidence": 0.85, "matched_index": 2}}"""


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

    def _get_llm_for_qualification(self) -> LLM | None:
        """Get LLM for question qualification.

        This method returns an LLM for running question qualification checks. The LLM used
        is independent of the user's chat session model - question qualification always uses
        a system-configured model to ensure consistent behavior.

        Configuration priority:
        1. QUESTION_QUALIFICATION_MODEL env var - if set, uses this model name with the
           DEFAULT provider's credentials. The model must be available from that provider.
           Recommended for fast/cheap models (e.g., gpt-4o-mini, claude-3-haiku).
        2. Falls back to the default provider's default model if env var is not set.

        Returns None if LLM initialization fails entirely.
        """
        try:
            # If a specific fast model is configured, use it with the default provider.
            # NOTE: The model name MUST be available from the default provider since we use
            # that provider's API credentials. This is independent of user's chat model.
            if QUESTION_QUALIFICATION_MODEL:
                with get_session_with_current_tenant() as db_session:
                    llm_provider = fetch_default_provider(db_session)
                if not llm_provider:
                    logger.warning(
                        "No default LLM provider found, cannot use QUESTION_QUALIFICATION_MODEL"
                    )
                    return None
                logger.debug(
                    f"Using configured fast model for question qualification: "
                    f"{QUESTION_QUALIFICATION_MODEL} via provider '{llm_provider.name}'"
                )
                return llm_from_provider(
                    model_name=QUESTION_QUALIFICATION_MODEL,
                    llm_provider=llm_provider,
                )
            # Fall back to default LLM (default provider's default model)
            return get_default_llm()
        except Exception as e:
            logger.warning(f"Failed to get LLM for question qualification: {e}")
            return None

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

            # Get LLM fresh each call to handle admin config changes
            llm = self._get_llm_for_qualification()
            if llm is None:
                logger.warning("No LLM available, question qualification skipped")
                return QuestionQualificationResult(
                    is_blocked=False, similarity_score=0.0
                )

            logger.debug(
                f"Using LLM: {llm.config.model_name} ({llm.config.model_provider})"
            )

            # Format blocked questions with indices
            blocked_questions_text = "\n".join(
                f"{i}: {q}" for i, q in enumerate(self.questions)
            )

            # Create structured response format schema from Pydantic model
            structured_response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "QuestionQualificationResponse",
                    "schema": QuestionQualificationResponse.model_json_schema(),
                    "strict": True,
                },
            }

            # Create minimal task-focused prompt
            prompt = QUESTION_QUALIFICATION_PROMPT.format(
                blocked_questions=blocked_questions_text,
                user_question=question,
            )

            # Get response using structured outputs
            response = llm.invoke(
                prompt,
                structured_response_format=structured_response_format,
                max_tokens=200,
            )

            # Parse the JSON response
            try:
                response_text = response.choice.message.content or ""
                # Try to extract JSON from the response
                parsed_data = json.loads(response_text)

                block_confidence = float(parsed_data.get("block_confidence", 0.0))
                matched_index = int(parsed_data.get("matched_index", -1))

                # Get matched question if available
                matched_question = ""
                if matched_index >= 0 and matched_index < len(self.questions):
                    matched_question = self.questions[matched_index]

                # Log detailed information including LLM used
                logger.info(
                    f"Question qualification: block_confidence={block_confidence:.3f}, "
                    f"threshold={self.threshold} | "
                    f"LLM: {llm.config.model_name}"
                )
                if matched_question:
                    logger.info(
                        f"Matched blocked question (index {matched_index}): '{matched_question[:100]}...'"
                    )

                # Apply threshold
                final_blocked = block_confidence >= self.threshold

                if final_blocked:
                    logger.info(
                        f"Question blocked by LLM analysis: block_confidence {block_confidence:.3f} >= {self.threshold}"
                    )

                standard_response = self.standard_response if final_blocked else ""
                return QuestionQualificationResult(
                    is_blocked=final_blocked,
                    similarity_score=block_confidence,
                    standard_response=standard_response,
                    matched_question=matched_question,
                    matched_question_index=matched_index,
                    reasoning="",
                )

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.error(
                    f"Error parsing JSON response: {e}, response: {response.choice.message.content}"
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
