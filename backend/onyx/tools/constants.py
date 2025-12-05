"""Tool name and ID constants matching frontend definitions."""

# Tool names as referenced by tool results / tool calls
SEARCH_TOOL_NAME = "run_search"
INTERNET_SEARCH_TOOL_NAME = "run_internet_search"
IMAGE_GENERATION_TOOL_NAME = "run_image_generation"
PYTHON_TOOL_NAME = "run_python"
OPEN_URL_TOOL_NAME = "open_url"

# In-code tool IDs that also correspond to the tool's name when associated with a persona
SEARCH_TOOL_ID = "SearchTool"
IMAGE_GENERATION_TOOL_ID = "ImageGenerationTool"
WEB_SEARCH_TOOL_ID = "WebSearchTool"
PYTHON_TOOL_ID = "PythonTool"
OPEN_URL_TOOL_ID = "OpenURLTool"
