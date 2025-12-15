GENERATE_PLAN_TOOL_NAME = "generate_plan"


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
