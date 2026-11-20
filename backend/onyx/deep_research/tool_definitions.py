from onyx.llm.models import ToolDefinition

GENERATE_PLAN_TOOL_NAME = "generate_plan"

RESEARCH_AGENT_IN_CODE_ID = "ResearchAgent"
RESEARCH_AGENT_TOOL_NAME = "research_agent"
RESEARCH_AGENT_TASK_KEY = "task"

GENERATE_REPORT_TOOL_NAME = "generate_report"

# ruff: noqa: E501, W605 start
GENERATE_PLAN_TOOL_DESCRIPTION: ToolDefinition = ToolDefinition(
    name=GENERATE_PLAN_TOOL_NAME,
    description="No clarification needed, generate a research plan for the user's query.",
    strict=True,
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {},
        "required": [],
    },
)


RESEARCH_AGENT_TOOL_DESCRIPTION: ToolDefinition = ToolDefinition(
    name=RESEARCH_AGENT_TOOL_NAME,
    description="Conduct research on a specific topic.",
    strict=True,
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            RESEARCH_AGENT_TASK_KEY: {
                "type": "string",
                "description": "The research task to investigate, should be 1-2 descriptive sentences outlining the direction of investigation.",
            }
        },
        "required": [RESEARCH_AGENT_TASK_KEY],
    },
)


GENERATE_REPORT_TOOL_DESCRIPTION: ToolDefinition = ToolDefinition(
    name=GENERATE_REPORT_TOOL_NAME,
    description="Generate the final research report from all of the findings. Should be called when all aspects of the user's query have been researched, or maximum cycles are reached.",
    strict=True,
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {},
        "required": [],
    },
)


def get_clarification_tool_definitions() -> list[ToolDefinition]:
    return [GENERATE_PLAN_TOOL_DESCRIPTION]


# ruff: noqa: E501, W605 end
