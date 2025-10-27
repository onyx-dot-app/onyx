from onyx.tools.tool_implementations.custom.custom_tool import CustomTool
from onyx.tools.tool_implementations.custom.openapi_parsing import MethodSpec


class SimpleTestTool(CustomTool):
    """A simple test implementation of CustomTool for testing purposes."""

    def __init__(self, tool_id: int = 1, name: str = "test_tool"):
        # Create a minimal MethodSpec for testing
        method_spec = MethodSpec(
            name=name,
            summary="A simple test tool for testing purposes",
            path="/test",
            method="GET",
            spec={
                "parameters": [
                    {
                        "name": "query",
                        "in": "query",
                        "schema": {"type": "string", "description": "The search query"},
                        "required": True,
                    }
                ]
            },
        )
        super().__init__(
            id=tool_id,
            method_spec=method_spec,
            base_url="http://test.local",
            custom_headers=None,
            user_oauth_token=None,
        )
