"""Wire-format tool fixtures shared by mock contract tests."""

INTERNAL_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "internal_search",
        "description": "Search connected applications for information.",
        "parameters": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of search queries to execute.",
                }
            },
            "required": ["queries"],
        },
    },
}
