"""Evaluates a single rule against a proposal context via LLM."""

import json
import re

from sqlalchemy.orm import Session

from onyx.llm.factory import get_default_llm
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.llm.utils import llm_response_to_string
from onyx.server.features.proposal_review.db.models import ProposalReviewRule
from onyx.server.features.proposal_review.engine.context_assembler import (
    ProposalContext,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

SYSTEM_PROMPT = """\
You are a meticulous grant proposal compliance reviewer for a university research office.
Your role is to evaluate specific aspects of grant proposals against institutional
and sponsor requirements.

You must evaluate each rule independently, focusing ONLY on the specific criterion
described. Be precise in your assessment. When in doubt, mark for human review.

Always respond with a valid JSON object in the exact format specified."""

RESPONSE_FORMAT_INSTRUCTIONS = """
Respond with ONLY a valid JSON object in the following format:
{
  "verdict": "PASS | FAIL | FLAG | NEEDS_REVIEW | NOT_APPLICABLE",
  "confidence": "HIGH | MEDIUM | LOW",
  "evidence": "Direct quote or reference from the proposal documents that supports your verdict. If no relevant text found, state that clearly.",
  "explanation": "Concise reasoning for why this verdict was reached. Reference specific requirements and how the proposal does or does not meet them.",
  "suggested_action": "If verdict is FAIL or FLAG, describe what the officer or PI should do. Otherwise, null."
}

Verdict meanings:
- PASS: The proposal clearly meets this requirement.
- FAIL: The proposal clearly does NOT meet this requirement.
- FLAG: There is a potential issue that needs human attention.
- NEEDS_REVIEW: Insufficient information to make a determination.
- NOT_APPLICABLE: This rule does not apply to this proposal.
"""


def evaluate_rule(
    rule: ProposalReviewRule,
    context: ProposalContext,
    _db_session: Session | None = None,
) -> dict:
    """Evaluate one rule against proposal context via LLM.

    1. Fills rule.prompt_template variables ({{proposal_text}}, {{metadata}}, etc.)
    2. Wraps in system prompt establishing reviewer role
    3. Calls llm.invoke() with structured output instructions
    4. Parses response into a findings dict

    Args:
        rule: The rule to evaluate.
        context: Assembled proposal context.
        db_session: Optional DB session (not used for LLM call but kept for API compat).

    Returns:
        Dict with verdict, confidence, evidence, explanation, suggested_action,
        plus llm_model and llm_tokens_used if available.
    """
    # 1. Fill template variables
    filled_prompt = _fill_template(rule.prompt_template, context)

    # 2. Build full prompt
    user_content = f"{filled_prompt}\n\n" f"{RESPONSE_FORMAT_INSTRUCTIONS}"

    prompt_messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        UserMessage(content=user_content),
    ]

    # 3. Call LLM
    try:
        llm = get_default_llm()
        response = llm.invoke(prompt_messages)
        raw_text = llm_response_to_string(response)

        # Extract model info
        llm_model = llm.config.model_name if llm.config else None
        llm_tokens_used = _extract_token_usage(response)

    except Exception as e:
        logger.error(f"LLM call failed for rule {rule.id} '{rule.name}': {e}")
        return {
            "verdict": "NEEDS_REVIEW",
            "confidence": "LOW",
            "evidence": None,
            "explanation": f"LLM evaluation failed: {str(e)}",
            "suggested_action": "Manual review required due to system error.",
            "llm_model": None,
            "llm_tokens_used": None,
        }

    # 4. Parse JSON response
    result = _parse_llm_response(raw_text)
    result["llm_model"] = llm_model
    result["llm_tokens_used"] = llm_tokens_used

    return result


def _fill_template(template: str, context: ProposalContext) -> str:
    """Replace {{variable}} placeholders in the prompt template.

    Supported variables:
    - {{proposal_text}} -> context.proposal_text
    - {{budget_text}} -> context.budget_text
    - {{foa_text}} -> context.foa_text
    - {{metadata}} -> JSON dump of context.metadata
    - {{metadata.FIELD}} -> specific metadata field value
    - {{jira_key}} -> context.jira_key
    """
    result = template

    # Direct substitutions
    result = result.replace("{{proposal_text}}", context.proposal_text or "")
    result = result.replace("{{budget_text}}", context.budget_text or "")
    result = result.replace("{{foa_text}}", context.foa_text or "")
    result = result.replace("{{jira_key}}", context.jira_key or "")

    # Metadata as JSON
    metadata_str = json.dumps(context.metadata, indent=2, default=str)
    result = result.replace("{{metadata}}", metadata_str)

    # Specific metadata fields: {{metadata.FIELD}}
    metadata_field_pattern = re.compile(r"\{\{metadata\.([^}]+)\}\}")
    for match in metadata_field_pattern.finditer(result):
        field_name = match.group(1)
        field_value = context.metadata.get(field_name, "")
        if isinstance(field_value, (dict, list)):
            field_value = json.dumps(field_value, default=str)
        result = result.replace(match.group(0), str(field_value))

    return result


def _parse_llm_response(raw_text: str) -> dict:
    """Parse the LLM response text as JSON.

    Handles cases where the LLM wraps JSON in markdown code fences.
    """
    text = raw_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        # Remove opening fence (with optional language tag)
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        # Remove closing fence
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse LLM response as JSON: {text[:200]}...")
        return {
            "verdict": "NEEDS_REVIEW",
            "confidence": "LOW",
            "evidence": None,
            "explanation": f"Failed to parse LLM response. Raw output: {text[:500]}",
            "suggested_action": "Manual review required due to unparseable AI response.",
        }

    # Validate and normalize the parsed result
    valid_verdicts = {"PASS", "FAIL", "FLAG", "NEEDS_REVIEW", "NOT_APPLICABLE"}
    valid_confidences = {"HIGH", "MEDIUM", "LOW"}

    verdict = str(parsed.get("verdict", "NEEDS_REVIEW")).upper()
    if verdict not in valid_verdicts:
        verdict = "NEEDS_REVIEW"

    confidence = str(parsed.get("confidence", "LOW")).upper()
    if confidence not in valid_confidences:
        confidence = "LOW"

    return {
        "verdict": verdict,
        "confidence": confidence,
        "evidence": parsed.get("evidence"),
        "explanation": parsed.get("explanation"),
        "suggested_action": parsed.get("suggested_action"),
    }


def _extract_token_usage(response: object) -> int | None:
    """Best-effort extraction of token usage from the LLM response."""
    try:
        # litellm ModelResponse has a usage attribute
        if hasattr(response, "usage") and response.usage:
            usage = response.usage
            total = getattr(usage, "total_tokens", None)
            if total is not None:
                return int(total)
            # Sum prompt + completion tokens if total not available
            prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            if prompt_tokens or completion_tokens:
                return prompt_tokens + completion_tokens
    except Exception:
        pass
    return None
