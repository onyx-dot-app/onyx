from datetime import datetime

from onyx.agents.agent_search.dr.constants import DRPath
from onyx.agents.agent_search.dr.models import DRPromptPurpose
from onyx.agents.agent_search.dr.models import DRTimeBudget
from onyx.prompts.dr_prompts import KG_TYPES_DESCRIPTIONS
from onyx.prompts.dr_prompts import ORCHESTRATOR_DEEP_INITIAL_PLAN_PROMPT
from onyx.prompts.dr_prompts import ORCHESTRATOR_DEEP_ITERATIVE_DECISION_PROMPT
from onyx.prompts.dr_prompts import ORCHESTRATOR_FAST_ITERATIVE_DECISION_PROMPT
from onyx.prompts.dr_prompts import TOOL_DESCRIPTION
from onyx.prompts.dr_prompts import TOOL_DIFFERENTIATION_HINTS
from onyx.prompts.dr_prompts import TOOL_QUESTION_HINTS


def _replace_signature_strings_in_template(
    template: str,
    string_replacements: dict[str, str],
) -> str:
    for key, value in string_replacements.items():
        if value:
            template = template.replace(f"---{key}---", value)
    return template


def get_dr_prompt_template(
    purpose: DRPromptPurpose,
    time_budget: DRTimeBudget,
    entity_types_string: str | None = None,
    relationship_types_string: str | None = None,
    available_tools: list[dict[str, str]] | None = None,
) -> str | None:

    available_tool_paths = [tool["path"] for tool in available_tools or []]

    tool_differentiations = []
    for tool_1 in available_tool_paths:
        for tool_2 in available_tool_paths:
            if (
                tool_1 in TOOL_DIFFERENTIATION_HINTS
                and tool_2 in TOOL_DIFFERENTIATION_HINTS[tool_1]
            ):
                tool_differentiations.append(TOOL_DIFFERENTIATION_HINTS[tool_1][tool_2])
    tool_differentiation_hint_string = (
        "\n  - ".join(tool_differentiations) or "(No differentiating hints available)"
    )

    # TODO: add tool deliniation pairs for custom tools as well

    tool_question_hints = []
    for tool in available_tool_paths:
        if tool in TOOL_QUESTION_HINTS:
            tool_question_hints.append(TOOL_QUESTION_HINTS[tool])
    tool_question_hint_string = (
        "\n  - ".join(tool_question_hints) or "(No examples available)"
    )

    string_replacements = {
        "num_available_tools": str(len(available_tool_paths)),
        "available_tools": ", ".join(
            available_tool_paths
        ),  # The tool paths are the same as the tool names
        "tool_choice_options": " or ".join(
            [f"{tool}" for tool in available_tool_paths]
        ),
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kg_types_descriptions": (
            KG_TYPES_DESCRIPTIONS
            if DRPath.KNOWLEDGE_GRAPH in available_tool_paths
            else "(The Knowledge Graph is not used.)"
        ),
        "tool_descriptions": "\n".join(
            [
                TOOL_DESCRIPTION[tool] for tool in available_tool_paths
            ]  # TODO: add custom tool descriptions
        ),
        "tool_differentiation_hints": tool_differentiation_hint_string,
        "tool_question_hints": tool_question_hint_string,
        "possible_entities": entity_types_string
        or "(The Knowledge Graph is not used.)",
        "possible_relationships": relationship_types_string
        or "(The Knowledge Graph is not used.)",
    }

    if purpose == DRPromptPurpose.PLAN:

        if time_budget == DRTimeBudget.FAST:
            return None

        base_template = ORCHESTRATOR_DEEP_INITIAL_PLAN_PROMPT

    elif purpose == DRPromptPurpose.NEXT_STEP:

        if time_budget == DRTimeBudget.FAST:
            base_template = ORCHESTRATOR_FAST_ITERATIVE_DECISION_PROMPT
        else:
            base_template = ORCHESTRATOR_DEEP_ITERATIVE_DECISION_PROMPT

    return _replace_signature_strings_in_template(base_template, string_replacements)
