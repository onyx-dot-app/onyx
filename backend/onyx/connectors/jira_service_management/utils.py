from typing import Any

def get_text_adf(data: dict[str, Any] | None) -> str:
    """Extracts plain text from Atlassian Document Format (ADF) recursively."""
    if not isinstance(data, dict):
        return ""
    if "text" in data and isinstance(data["text"], str):
        return data["text"]
    if "content" in data and isinstance(data["content"], list):
        return " ".join(filter(None, (get_text_adf(item) for item in data["content"])))
    return ""
