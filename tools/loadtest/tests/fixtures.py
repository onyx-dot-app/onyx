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

# Code mode (CODE_MODE_ENABLED): retrieval tools are async functions inside
# exec programs; the description lists their stubs.
EXEC_TOOL = {
    "type": "function",
    "function": {
        "name": "exec",
        "description": (
            "Run a Python program that calls the tools listed below.\n\n"
            "Functions:\n```python\n"
            "async def internal_search(*, queries: list[str]) -> SearchResults:\n"
            "    ...\n\n"
            "async def web_search(*, queries: list[str]) -> SearchResults:\n"
            "    ...\n```"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "yield_time_ms": {"type": "integer"},
                "max_output_tokens": {"type": "integer"},
            },
            "required": ["code"],
        },
    },
}

WAIT_TOOL = {
    "type": "function",
    "function": {
        "name": "wait",
        "description": "Waits on a running `exec` cell.",
        "parameters": {
            "type": "object",
            "properties": {
                "cell_id": {"type": "integer"},
                "yield_time_ms": {"type": "integer"},
                "max_tokens": {"type": "integer"},
                "terminate": {"type": "boolean"},
            },
            "required": ["cell_id"],
        },
    },
}
