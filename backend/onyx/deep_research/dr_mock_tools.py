GENERATE_PLAN_TOOL_NAME = "generate_plan"

RESEARCH_AGENT_TOOL_NAME = "research_agent"

GENERATE_REPORT_TOOL_NAME = "generate_report"

THINK_TOOL_NAME = "think_tool"


# ruff: noqa: E501, W605 start
def get_clarification_tool_definitions() -> list[dict]:
    return [
        {
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
    ]


def get_orchestrator_tools(include_think_tool: bool) -> list[dict]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": RESEARCH_AGENT_TOOL_NAME,
                "description": "Conduct research on a specific topic.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The research task to investigate, should be 1-2 descriptive sentences outlining the direction of investigation.",
                        }
                    },
                    "required": ["task"],
                },
            },
        },
        {
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
        },
    ]
    if include_think_tool:
        tools.append(
            {
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
        )
    return tools


# ruff: noqa: E501, W605 end
