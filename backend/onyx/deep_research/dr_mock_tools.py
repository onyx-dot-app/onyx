GENERATE_PLAN_TOOL_NAME = "generate_plan"

RESEARCH_AGENT_TOOL_NAME = "research_agent"
RESEARCH_AGENT_TASK_KEY = "task"

GENERATE_REPORT_TOOL_NAME = "generate_report"

THINK_TOOL_NAME = "think_tool"


# ruff: noqa: E501, W605 start
GENERATE_PLAN_TOOL_DESCRIPTION = {
    "type": "function",
    "function": {
        "name": GENERATE_PLAN_TOOL_NAME,
        "description": "No clarification needed, generate a research plan for the user's query.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


RESEARCH_AGENT_TOOL_DESCRIPTION = {
    "type": "function",
    "function": {
        "name": RESEARCH_AGENT_TOOL_NAME,
        "description": "Conduct research on a specific topic.",
        "parameters": {
            "type": "object",
            "properties": {
                RESEARCH_AGENT_TASK_KEY: {
                    "type": "string",
                    "description": "The research task to investigate, should be 1-2 descriptive sentences outlining the direction of investigation.",
                }
            },
            "required": [RESEARCH_AGENT_TASK_KEY],
        },
    },
}


GENERATE_REPORT_TOOL_DESCRIPTION = {
    "type": "function",
    "function": {
        "name": GENERATE_REPORT_TOOL_NAME,
        "description": "Generate the final research report from all of the findings. Should be called when all aspects of the user's query have been researched, or maximum cycles are reached.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


THINK_TOOL_DESCRIPTION = {
    "type": "function",
    "function": {
        "name": THINK_TOOL_NAME,
        "description": "Use this for reasoning between research_agent calls and before calling generate_report. Think deeply about key results, identify knowledge gaps, and plan next steps.",
        "parameters": {
            "type": "object",
            "properties": {
                "reasoning": {
                    "type": "string",
                    "description": "Your chain of thought reasoning, use paragraph format, no lists.",
                }
            },
            "required": ["reasoning"],
        },
    },
}


RESEARCH_AGENT_THINK_TOOL_DESCRIPTION = {
    "type": "function",
    "function": {
        "name": "think_tool",
        "description": "Use this for reasoning between research steps. Think deeply about key results, identify knowledge gaps, and plan next steps.",
        "parameters": {
            "type": "object",
            "properties": {
                "reasoning": {
                    "type": "string",
                    "description": "Your chain of thought reasoning, can be as long as a lengthy paragraph.",
                }
            },
            "required": ["reasoning"],
        },
    },
}


RESEARCH_AGENT_GENERATE_REPORT_TOOL_DESCRIPTION = {
    "type": "function",
    "function": {
        "name": "generate_report",
        "description": "Generate the final research report from all findings. Should be called when research is complete.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


THINK_TOOL_RESPONSE_MESSAGE = "Acknowledged, please continue."
THINK_TOOL_RESPONSE_TOKEN_COUNT = 10


def get_clarification_tool_definitions() -> list[dict]:
    return [GENERATE_PLAN_TOOL_DESCRIPTION]


def get_orchestrator_tools(include_think_tool: bool) -> list[dict]:
    tools = [
        RESEARCH_AGENT_TOOL_DESCRIPTION,
        GENERATE_REPORT_TOOL_DESCRIPTION,
    ]
    if include_think_tool:
        tools.append(THINK_TOOL_DESCRIPTION)
    return tools


def get_research_agent_additional_tool_definitions(
    include_think_tool: bool,
) -> list[dict]:
    tools = [GENERATE_REPORT_TOOL_DESCRIPTION]
    if include_think_tool:
        tools.append(RESEARCH_AGENT_THINK_TOOL_DESCRIPTION)
    return tools


# ruff: noqa: E501, W605 end
