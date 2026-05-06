"""Parses uploaded checklist documents into atomic review rules via LLM.

Uses a two-pass approach to handle checklists of any size without hitting
output token limits:

  Pass 1 — Enumerate:  Identify all distinct checklist items from the
           document (names, categories, sub-checks). This produces a small,
           bounded output regardless of document size.

  Pass 2 — Decompose:  For each identified item, make a focused LLM call
           to generate atomic review rules with full prompt templates.
           Each call produces 1–5 rules, well within token limits.

Callers orchestrate persistence — this module is pure LLM + parsing, no
DB access, no callbacks, no threads.
"""

import json
import re
from dataclasses import dataclass
from dataclasses import field

from onyx.configs.model_configs import GEN_AI_MODEL_FALLBACK_MAX_TOKENS
from onyx.llm.interfaces import LLM
from onyx.llm.models import AssistantMessage
from onyx.llm.models import SystemMessage
from onyx.llm.models import ToolMessage
from onyx.llm.models import UserMessage
from onyx.llm.utils import get_llm_max_output_tokens
from onyx.llm.utils import get_model_map
from onyx.llm.utils import llm_response_to_string
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import llm_generation_span
from onyx.tracing.llm_utils import record_llm_response
from onyx.utils.logger import setup_logger

logger = setup_logger()


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ChecklistItem:
    """A single checklist item identified during pass 1."""

    id: str
    name: str
    category: str
    description: str
    sub_checks: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompts — Pass 1 (Enumerate)
# ---------------------------------------------------------------------------

_ENUMERATE_SYSTEM = """\
You are an expert at analyzing institutional review checklists for university \
grant offices. Your task is to read a checklist document and identify every \
distinct checklist item or section that requires review."""

_ENUMERATE_USER = """\
Read the checklist document below and list every distinct checklist item.

CHECKLIST DOCUMENT:
---
{checklist_text}
---

For each item, provide:
- **id**: A short identifier derived from the document (e.g., "IR-1", \
"KR-3", "Section-A.2"). Invent one if the document doesn't assign one.
- **name**: The item's title or heading.
- **category**: A display label combining the id and name \
(e.g., "IR-2: Regulatory Compliance").
- **description**: One sentence summarizing what this item covers.
- **sub_checks**: A list of the individual checks or requirements \
mentioned under this item. Be thorough — include every distinct \
requirement even if the document groups them together.

Respond with ONLY a valid JSON array:
[
  {{
    "id": "IR-1",
    "name": "Institutional and PI Eligibility",
    "category": "IR-1: Institutional and PI Eligibility Requirements",
    "description": "Verify institution and PI meet sponsor eligibility.",
    "sub_checks": ["Institutional eligibility", "PI eligibility", ...]
  }},
  ...
]"""


# ---------------------------------------------------------------------------
# Prompts — Pass 2 (Decompose one item into rules)
# ---------------------------------------------------------------------------

_DECOMPOSE_SYSTEM = """\
You are an expert at creating AI review rules for university grant proposal \
review. Each rule you create will be independently evaluated by an LLM \
against a grant proposal. Rules must be atomic (one criterion each) and \
self-contained (the prompt template includes all context needed).

Variable placeholders available for prompt templates:
  {{{{proposal_text}}}}          — full proposal and supporting documents
  {{{{budget_text}}}}            — budget / financial sections
  {{{{foa_text}}}}               — funding opportunity announcement
  {{{{metadata}}}}               — structured metadata (PI, sponsor, etc.)
  {{{{metadata.FIELD_NAME}}}}    — a specific metadata field

Rule types:
  DOCUMENT_CHECK    — verify presence / content in documents
  METADATA_CHECK    — validate a structured metadata field
  CROSS_REFERENCE   — compare information across documents
  CUSTOM_NL         — natural language evaluation

Rule intents:
  CHECK     — pass / fail criterion
  HIGHLIGHT — informational flag (no pass / fail)

If a rule requires institution-specific info NOT present in the checklist \
(IDC rates, mandatory cost categories, local policies, etc.), set \
refinement_needed=true and include a refinement_question."""

_DECOMPOSE_USER = """\
Create atomic review rules for the checklist item described below.

ITEM TO DECOMPOSE:
  ID: {item_id}
  Name: {item_name}
  Category: {item_category}
  Description: {item_description}
  Sub-checks: {sub_checks}

FULL CHECKLIST (for context — only create rules for the item above):
---
{checklist_text}
---

Generate one rule per sub-check. Each rule object must have:
{{
  "name": "Short descriptive name (max 100 chars)",
  "description": "What this rule checks",
  "category": "{item_category}",
  "rule_type": "DOCUMENT_CHECK | METADATA_CHECK | CROSS_REFERENCE | CUSTOM_NL",
  "rule_intent": "CHECK | HIGHLIGHT",
  "prompt_template": "Self-contained prompt with {{{{variable}}}} placeholders.",
  "refinement_needed": false,
  "refinement_question": null
}}

Respond with ONLY a valid JSON array of rule objects."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enumerate_checklist_items(
    checklist_text: str,
    llm: LLM,
) -> list[ChecklistItem]:
    """Pass 1: Identify all distinct checklist items from the document.

    One LLM call.  Output is small and bounded regardless of document size.

    Args:
        checklist_text: Full text extracted from the uploaded checklist file.
        llm: The LLM instance to use.

    Returns:
        Ordered list of checklist items found in the document.

    Raises:
        RuntimeError: If the LLM call fails or returns unparseable output.
    """
    user_content = _ENUMERATE_USER.format(checklist_text=checklist_text)
    messages: list[SystemMessage | UserMessage | AssistantMessage | ToolMessage] = [
        SystemMessage(content=_ENUMERATE_SYSTEM),
        UserMessage(content=user_content),
    ]

    max_output_tokens = _get_max_output_tokens(llm)

    try:
        with llm_generation_span(
            llm, LLMFlow.CHECKLIST_ENUMERATE, messages
        ) as gen_span:
            response = llm.invoke(
                messages, timeout_override=300, max_tokens=max_output_tokens
            )
            record_llm_response(gen_span, response)
        raw_text = llm_response_to_string(response)
    except Exception as e:
        logger.error("Pass 1 (enumerate) LLM call failed: %s", e)
        raise RuntimeError(f"Failed to enumerate checklist items: {str(e)}") from e

    parsed = _parse_json_array(raw_text, context="enumerate")

    items: list[ChecklistItem] = []
    for i, raw in enumerate(parsed):
        if not isinstance(raw, dict):
            logger.warning("Enumerate: skipping non-dict at index %s", i)
            continue

        item_id = str(raw.get("id", f"ITEM-{i + 1}"))
        name = raw.get("name")
        if not name:
            logger.warning("Enumerate: skipping item at index %s (no name)", i)
            continue

        items.append(
            ChecklistItem(
                id=item_id,
                name=str(name),
                category=str(raw.get("category", f"{item_id}: {name}")),
                description=str(raw.get("description", "")),
                sub_checks=[str(s) for s in raw.get("sub_checks", [])],
            )
        )

    return items


def decompose_checklist_item(
    item: ChecklistItem,
    checklist_text: str,
    llm: LLM,
) -> list[dict]:
    """Pass 2: Decompose one checklist item into atomic review rules.

    One LLM call.  Output is bounded (1–10 rules per item).

    Args:
        item: The checklist item to decompose.
        checklist_text: Full checklist text (passed as context).
        llm: The LLM instance to use.

    Returns:
        List of validated rule dicts for this item.

    Raises:
        RuntimeError: If the LLM call fails or returns unparseable output.
    """
    sub_checks_str = "\n".join(f"  - {s}" for s in item.sub_checks) or "  (none listed)"

    user_content = _DECOMPOSE_USER.format(
        item_id=item.id,
        item_name=item.name,
        item_category=item.category,
        item_description=item.description,
        sub_checks=sub_checks_str,
        checklist_text=checklist_text,
    )
    messages: list[SystemMessage | UserMessage | AssistantMessage | ToolMessage] = [
        SystemMessage(content=_DECOMPOSE_SYSTEM),
        UserMessage(content=user_content),
    ]

    max_output_tokens = _get_max_output_tokens(llm)

    try:
        with llm_generation_span(
            llm, LLMFlow.CHECKLIST_DECOMPOSE, messages
        ) as gen_span:
            response = llm.invoke(
                messages, timeout_override=300, max_tokens=max_output_tokens
            )
            record_llm_response(gen_span, response)
        raw_text = llm_response_to_string(response)
    except Exception as e:
        raise RuntimeError(f"LLM call failed for item '{item.name}': {str(e)}") from e

    parsed = _parse_json_array(raw_text, context=f"decompose[{item.id}]")

    rules: list[dict] = []
    for i, raw_rule in enumerate(parsed):
        if not isinstance(raw_rule, dict):
            continue
        rule = _validate_rule(raw_rule, i)
        if rule:
            if not rule["category"]:
                rule["category"] = item.category
            rules.append(rule)

    return rules


# ---------------------------------------------------------------------------
# Prompts — Refinement (single rule)
# ---------------------------------------------------------------------------

_REFINE_SYSTEM = """\
You are an expert at creating AI review rules for university grant proposal \
review. You are refining a rule that was previously flagged as needing \
institution-specific information. The user has now provided that information.

Variable placeholders available for prompt templates:
  {{{{proposal_text}}}}          — full proposal and supporting documents
  {{{{budget_text}}}}            — budget / financial sections
  {{{{foa_text}}}}               — funding opportunity announcement
  {{{{metadata}}}}               — structured metadata (PI, sponsor, etc.)
  {{{{metadata.FIELD_NAME}}}}    — a specific metadata field

Rule types:
  DOCUMENT_CHECK    — verify presence / content in documents
  METADATA_CHECK    — validate a structured metadata field
  CROSS_REFERENCE   — compare information across documents
  CUSTOM_NL         — natural language evaluation

Rule intents:
  CHECK     — pass / fail criterion
  HIGHLIGHT — informational flag (no pass / fail)"""

_REFINE_USER = """\
The following rule was imported from a checklist but flagged as needing \
additional information before it can be used.

CURRENT RULE:
  Name: {rule_name}
  Description: {rule_description}
  Prompt Template: {rule_prompt_template}

QUESTION THAT WAS ASKED:
  {refinement_question}

USER'S ANSWER:
  {user_answer}

Using the user's answer, produce a refined version of this rule. \
Incorporate the institution-specific information into the prompt_template \
so the rule is fully self-contained and no longer needs refinement.

Respond with ONLY a single JSON object (not an array):
{{
  "name": "Short descriptive name (max 100 chars)",
  "description": "What this rule checks",
  "rule_type": "DOCUMENT_CHECK | METADATA_CHECK | CROSS_REFERENCE | CUSTOM_NL",
  "rule_intent": "CHECK | HIGHLIGHT",
  "prompt_template": "Refined self-contained prompt with {{{{variable}}}} placeholders.",
  "refinement_needed": false,
  "refinement_question": null
}}"""


def refine_rule(
    rule_name: str,
    rule_description: str | None,
    rule_prompt_template: str,
    refinement_question: str,
    user_answer: str,
    llm: LLM,
) -> dict:
    """Refine a single rule using the user's answer to the refinement question.

    One LLM call. Returns a validated rule dict with refinement_needed=False.

    Raises:
        RuntimeError: If the LLM call fails or returns unparseable output.
    """
    user_content = _REFINE_USER.format(
        rule_name=rule_name,
        rule_description=rule_description or "(none)",
        rule_prompt_template=rule_prompt_template,
        refinement_question=refinement_question,
        user_answer=user_answer,
    )
    messages: list[SystemMessage | UserMessage | AssistantMessage | ToolMessage] = [
        SystemMessage(content=_REFINE_SYSTEM),
        UserMessage(content=user_content),
    ]

    try:
        with llm_generation_span(llm, LLMFlow.CHECKLIST_REFINE, messages) as gen_span:
            response = llm.invoke(messages, timeout_override=120)
            record_llm_response(gen_span, response)
        raw_text = llm_response_to_string(response)
    except Exception as e:
        raise RuntimeError(f"LLM call failed during rule refinement: {str(e)}") from e

    # Parse the single JSON object (strip code fences)
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM returned invalid JSON during refinement: {e}") from e

    if isinstance(parsed, list):
        if not parsed:
            raise RuntimeError("LLM returned an empty array during refinement")
        parsed = parsed[0]

    if not isinstance(parsed, dict):
        raise RuntimeError("LLM returned non-object JSON during refinement")

    rule = _validate_rule(parsed, 0)
    if not rule:
        raise RuntimeError("LLM returned an invalid rule during refinement")

    # Force refinement_needed to False
    rule["refinement_needed"] = False
    rule["refinement_question"] = None
    return rule


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_max_output_tokens(llm: LLM) -> int:
    """Look up the model's max output tokens from litellm's model cost map."""
    try:
        model_map = get_model_map()
        return get_llm_max_output_tokens(
            model_map=model_map,
            model_name=llm.config.model_name,
            model_provider=llm.config.model_provider,
        )
    except Exception as e:
        logger.warning("Failed to resolve max output tokens: %s", e)
        return int(GEN_AI_MODEL_FALLBACK_MAX_TOKENS)


def _parse_json_array(raw_text: str, context: str) -> list:
    """Parse an LLM response as a JSON array, stripping code fences."""
    text = raw_text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("[%s] Failed to parse JSON: %s", context, e)
        logger.debug("[%s] Raw LLM response: %s...", context, text[:500])
        raise RuntimeError(
            f"LLM returned invalid JSON during {context}. "
            "Please try the import again."
        ) from e

    if not isinstance(parsed, list):
        raise RuntimeError(
            f"LLM returned non-array JSON during {context}. " "Expected a list."
        )

    return parsed


def _validate_rule(raw_rule: dict, index: int) -> dict | None:
    """Validate and normalize a single parsed rule dict."""
    valid_types = {
        "DOCUMENT_CHECK",
        "METADATA_CHECK",
        "CROSS_REFERENCE",
        "CUSTOM_NL",
    }
    valid_intents = {"CHECK", "HIGHLIGHT"}

    name = raw_rule.get("name")
    if not name:
        logger.warning("Rule at index %s missing 'name', skipping", index)
        return None

    prompt_template = raw_rule.get("prompt_template")
    if not prompt_template:
        logger.warning("Rule '%s' missing 'prompt_template', skipping", name)
        return None

    rule_type = str(raw_rule.get("rule_type", "CUSTOM_NL")).upper()
    if rule_type not in valid_types:
        rule_type = "CUSTOM_NL"

    rule_intent = str(raw_rule.get("rule_intent", "CHECK")).upper()
    if rule_intent not in valid_intents:
        rule_intent = "CHECK"

    return {
        "name": str(name)[:200],
        "description": raw_rule.get("description"),
        "category": raw_rule.get("category"),
        "rule_type": rule_type,
        "rule_intent": rule_intent,
        "prompt_template": str(prompt_template),
        "refinement_needed": bool(raw_rule.get("refinement_needed", False)),
        "refinement_question": (
            str(raw_rule["refinement_question"])
            if raw_rule.get("refinement_question")
            else None
        ),
    }
