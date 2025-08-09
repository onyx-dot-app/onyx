from datetime import datetime

from onyx.agents.agent_search.dr.enums import DRPath
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import DRPromptPurpose
from onyx.agents.agent_search.dr.models import OrchestratorTool
from onyx.prompts.dr_prompts import GET_CLARIFICATION_PROMPT
from onyx.prompts.dr_prompts import KG_TYPES_DESCRIPTIONS
from onyx.prompts.dr_prompts import ORCHESTRATOR_DEEP_INITIAL_PLAN_PROMPT
from onyx.prompts.dr_prompts import ORCHESTRATOR_DEEP_ITERATIVE_DECISION_PROMPT
from onyx.prompts.dr_prompts import ORCHESTRATOR_FAST_ITERATIVE_DECISION_PROMPT
from onyx.prompts.dr_prompts import ORCHESTRATOR_FAST_ITERATIVE_REASONING_PROMPT
from onyx.prompts.dr_prompts import ORCHESTRATOR_NEXT_STEP_PURPOSE_PROMPT
from onyx.prompts.dr_prompts import TOOL_DIFFERENTIATION_HINTS
from onyx.prompts.dr_prompts import TOOL_QUESTION_HINTS
from onyx.prompts.prompt_template import PromptTemplate


def get_dr_prompt_orchestration_templates(
    purpose: DRPromptPurpose,
    time_budget: ResearchType,
    entity_types_string: str | None = None,
    relationship_types_string: str | None = None,
    available_tools: list[OrchestratorTool] | None = None,
    reasoning_result: str | None = None,
    tool_calls_string: str | None = None,
) -> PromptTemplate:
    # TODO: instead of using paths as names, have either a TOOL or CLOSER path
    # the LLM spits out the tool name or CLOSER, which gets converted into a
    # (TOOL, <TOOL_NAME>) request, or a CLOSER request
    # revisit in v2 when we have tools and subagents more neatly laid out
    available_tool_names = [tool.path.value for tool in available_tools or []]
    available_tool_paths = [tool.path for tool in available_tools or []]
    available_tool_cost_string = "\n".join(
        f"{tool.path}: {tool.cost}" for tool in available_tools or []
    )

    tool_differentiations: list[str] = []
    for tool_1 in available_tool_paths:
        for tool_2 in available_tool_paths:
            if (tool_1, tool_2) in TOOL_DIFFERENTIATION_HINTS:
                tool_differentiations.append(
                    TOOL_DIFFERENTIATION_HINTS[(tool_1, tool_2)]
                )
    tool_differentiation_hint_string = (
        "\n".join(tool_differentiations) or "(No differentiating hints available)"
    )
    # TODO: add tool deliniation pairs for custom tools as well

    tool_question_hint_string = (
        "\n".join(
            "- " + TOOL_QUESTION_HINTS[tool]
            for tool in available_tool_paths
            if tool in TOOL_QUESTION_HINTS
        )
        or "(No examples available)"
    )

    if DRPath.KNOWLEDGE_GRAPH in available_tool_paths:
        if not entity_types_string or not relationship_types_string:
            raise ValueError(
                "Entity types and relationship types must be provided if the Knowledge Graph is used."
            )
        kg_types_descriptions = KG_TYPES_DESCRIPTIONS.build(
            possible_entities=entity_types_string,
            possible_relationships=relationship_types_string,
        )
    else:
        kg_types_descriptions = "(The Knowledge Graph is not used.)"

    if purpose == DRPromptPurpose.PLAN:
        if time_budget == ResearchType.THOUGHTFUL:
            raise ValueError("plan generation is not supported for FAST time budget")
        base_template = ORCHESTRATOR_DEEP_INITIAL_PLAN_PROMPT

    elif purpose == DRPromptPurpose.NEXT_STEP_REASONING:
        if time_budget == ResearchType.THOUGHTFUL:
            base_template = ORCHESTRATOR_FAST_ITERATIVE_REASONING_PROMPT
        else:
            raise ValueError(
                "reasoning is not separately required for DEEP time budget"
            )

    elif purpose == DRPromptPurpose.NEXT_STEP_PURPOSE:
        base_template = ORCHESTRATOR_NEXT_STEP_PURPOSE_PROMPT

    elif purpose == DRPromptPurpose.NEXT_STEP:
        if time_budget == ResearchType.THOUGHTFUL:
            base_template = ORCHESTRATOR_FAST_ITERATIVE_DECISION_PROMPT
        else:
            base_template = ORCHESTRATOR_DEEP_ITERATIVE_DECISION_PROMPT

    elif purpose == DRPromptPurpose.CLARIFICATION:
        if time_budget == ResearchType.THOUGHTFUL:
            raise ValueError("clarification is not supported for FAST time budget")
        base_template = GET_CLARIFICATION_PROMPT

    else:
        # for mypy, clearly a mypy bug
        raise ValueError(f"Invalid purpose: {purpose}")

    return base_template.partial_build(
        num_available_tools=str(len(available_tool_names)),
        available_tools=", ".join(available_tool_names),
        tool_choice_options=" or ".join(available_tool_names),
        current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        kg_types_descriptions=kg_types_descriptions,
        tool_descriptions="\n".join(tool.description for tool in available_tools or []),
        tool_differentiation_hints=tool_differentiation_hint_string,
        tool_question_hints=tool_question_hint_string,
        average_tool_costs=available_tool_cost_string,
        reasoning_result=reasoning_result or "(No reasoning result provided.)",
        tool_calls_string=tool_calls_string or "(No tool calls provided.)",
    )
