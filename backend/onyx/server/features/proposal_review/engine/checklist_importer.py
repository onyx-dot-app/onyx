"""Parses uploaded checklist documents into atomic review rules via LLM."""

import json
import re

from onyx.llm.factory import get_default_llm
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.llm.utils import llm_response_to_string
from onyx.utils.logger import setup_logger

logger = setup_logger()

_IMPORT_SYSTEM_PROMPT = """\
You are an expert at analyzing institutional review checklists for university grant \
offices. Your task is to decompose a checklist document into atomic, self-contained \
review rules that can each be independently evaluated by an AI against a grant proposal.

Key principles:
1. ATOMIC DECOMPOSITION: Each checklist item may contain multiple distinct requirements. \
You MUST split compound items into separate atomic rules. Each rule should test exactly \
ONE pass/fail criterion.

2. CATEGORY PRESERVATION: All rules decomposed from the same source checklist item \
should share the same category value. Use the checklist item's identifier and title \
(e.g., "IR-2: Regulatory Compliance") as the category.

3. SELF-CONTAINED PROMPTS: Each rule's prompt_template must be fully self-contained. \
It should include all context needed to evaluate the criterion. Use {{variable}} \
placeholders for dynamic content:
   - {{proposal_text}} - full text of the proposal and supporting documents
   - {{budget_text}} - budget/financial sections
   - {{foa_text}} - funding opportunity announcement
   - {{metadata}} - structured metadata (PI, sponsor, deadlines, etc.)
   - {{metadata.FIELD_NAME}} - specific metadata field

4. REFINEMENT DETECTION: If a rule requires institution-specific information that is \
NOT present in the source checklist (such as IDC rates, cost categories, institutional \
policies, specific thresholds, or local procedures), mark it with:
   - refinement_needed: true
   - refinement_question: a clear question asking for the missing information
   - Use a placeholder like {{INSTITUTION_IDC_RATES}} in the prompt_template

5. RULE TYPES:
   - DOCUMENT_CHECK: Verifies presence/content of specific documents or sections
   - METADATA_CHECK: Validates structured metadata fields
   - CROSS_REFERENCE: Compares information across multiple documents (e.g., budget vs narrative)
   - CUSTOM_NL: Natural language evaluation of content quality or compliance

6. RULE INTENT:
   - CHECK: Pass/fail criterion that must be satisfied
   - HIGHLIGHT: Informational flag for officer attention (no pass/fail)"""

_IMPORT_USER_PROMPT = """\
Analyze the following checklist document and decompose it into atomic review rules.

CHECKLIST CONTENT:
---
{checklist_text}
---

Respond with ONLY a valid JSON array of rule objects. Each rule must have:
{{
  "name": "Short descriptive name for the rule (max 100 chars)",
  "description": "Detailed description of what this rule checks",
  "category": "Source checklist item identifier and title (e.g., 'IR-2: Regulatory Compliance')",
  "rule_type": "DOCUMENT_CHECK | METADATA_CHECK | CROSS_REFERENCE | CUSTOM_NL",
  "rule_intent": "CHECK | HIGHLIGHT",
  "prompt_template": "Self-contained prompt with {{{{variable}}}} placeholders. Must clearly state the criterion and ask for evaluation.",
  "refinement_needed": false,
  "refinement_question": null
}}

For rules that need institution-specific info:
{{
  "name": "...",
  "description": "...",
  "category": "...",
  "rule_type": "...",
  "rule_intent": "CHECK",
  "prompt_template": "... {{{{INSTITUTION_IDC_RATES}}}} ...",
  "refinement_needed": true,
  "refinement_question": "Please provide your institution's IDC rate schedule."
}}

Important:
- Decompose compound checklist items into multiple atomic rules
- Each rule tests exactly ONE criterion
- Prompt templates must be specific and actionable
- Include all relevant context placeholders in templates
- Flag any rule requiring institution-specific knowledge"""


def import_checklist(
    extracted_text: str,
) -> list[dict]:
    """Parse a checklist document into atomic review rules via LLM.

    Args:
        extracted_text: The full text content extracted from the uploaded checklist file.

    Returns:
        List of rule dicts, each with: name, description, category, rule_type,
        rule_intent, prompt_template, refinement_needed, refinement_question.
    """
    if not extracted_text or not extracted_text.strip():
        logger.warning("Empty checklist text provided for import")
        return []

    # Build the prompt
    user_content = _IMPORT_USER_PROMPT.format(checklist_text=extracted_text)

    prompt_messages = [
        SystemMessage(content=_IMPORT_SYSTEM_PROMPT),
        UserMessage(content=user_content),
    ]

    # Call LLM synchronously (this runs in the API request, not Celery)
    try:
        llm = get_default_llm()
        response = llm.invoke(prompt_messages)
        raw_text = llm_response_to_string(response)
    except Exception as e:
        logger.error(f"LLM call failed during checklist import: {e}")
        raise RuntimeError(f"Failed to parse checklist via LLM: {str(e)}") from e

    # Parse JSON response
    rules = _parse_import_response(raw_text)
    logger.info(f"Checklist import produced {len(rules)} atomic rules")

    return rules


def _parse_import_response(raw_text: str) -> list[dict]:
    """Parse the LLM response text as a JSON array of rule dicts."""
    text = raw_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse import response as JSON: {e}")
        logger.debug(f"Raw LLM response: {text[:500]}...")
        raise RuntimeError(
            "LLM returned invalid JSON. Please try the import again."
        ) from e

    if not isinstance(parsed, list):
        raise RuntimeError(
            "LLM returned a non-array JSON. Expected a list of rule objects."
        )

    # Validate and normalize each rule
    validated_rules: list[dict] = []
    for i, raw_rule in enumerate(parsed):
        if not isinstance(raw_rule, dict):
            logger.warning(f"Skipping non-dict entry at index {i}")
            continue

        rule = _validate_rule(raw_rule, i)
        if rule:
            validated_rules.append(rule)

    return validated_rules


def _validate_rule(raw_rule: dict, index: int) -> dict | None:
    """Validate and normalize a single parsed rule dict."""
    valid_types = {"DOCUMENT_CHECK", "METADATA_CHECK", "CROSS_REFERENCE", "CUSTOM_NL"}
    valid_intents = {"CHECK", "HIGHLIGHT"}

    name = raw_rule.get("name")
    if not name:
        logger.warning(f"Rule at index {index} missing 'name', skipping")
        return None

    prompt_template = raw_rule.get("prompt_template")
    if not prompt_template:
        logger.warning(f"Rule '{name}' missing 'prompt_template', skipping")
        return None

    rule_type = str(raw_rule.get("rule_type", "CUSTOM_NL")).upper()
    if rule_type not in valid_types:
        rule_type = "CUSTOM_NL"

    rule_intent = str(raw_rule.get("rule_intent", "CHECK")).upper()
    if rule_intent not in valid_intents:
        rule_intent = "CHECK"

    return {
        "name": str(name)[:200],  # Cap length
        "description": raw_rule.get("description"),
        "category": raw_rule.get("category"),
        "rule_type": rule_type,
        "rule_intent": rule_intent,
        "prompt_template": str(prompt_template),
        "refinement_needed": bool(raw_rule.get("refinement_needed", False)),
        "refinement_question": raw_rule.get("refinement_question"),
    }
