from typing import Any

JSM_API_BASE = "rest/servicedeskapi"

def build_jsm_url(jira_base_url: str, request_key: str) -> str:
    """
    Get the url used to access a JSM request in the UI.
    """
    return f"{jira_base_url}/servicedesk/customer/portal/search?q={request_key}"

def get_jsm_api_url(jira_base_url: str, endpoint: str) -> str:
    """
    Build a JSM API URL.
    """
    return f"{jira_base_url.rstrip('/')}/{JSM_API_BASE}/{endpoint.lstrip('/')}"

def extract_text_from_adf(adf: Any) -> str:
    """Extracts plain text from Atlassian Document Format:
    https://developer.atlassian.com/cloud/jira/platform/apis/document/structure/
    """
    if adf is None:
        return ""
    if isinstance(adf, str):
        return adf
    if not isinstance(adf, dict):
        return str(adf)

    texts = []

    def walk(node: Any):
        if not isinstance(node, dict):
            return
        
        node_type = node.get("type")
        if node_type == "text":
            texts.append(node.get("text", ""))
        elif node_type == "hardBreak":
            texts.append("\n")
        elif node_type in ["paragraph", "heading", "listItem"]:
            if "content" in node:
                for child in node["content"]:
                    walk(child)
            texts.append("\n")
        elif "content" in node:
            for child in node["content"]:
                walk(child)

    walk(adf)
    return "".join(texts).strip()


def best_effort_basic_expert_info(obj: Any) -> Any:
    """
    Extract display name and email from a JSM user object.
    Matches the pattern in other connectors.
    """
    if not obj:
        return None
    
    display_name = obj.get("displayName")
    email = obj.get("emailAddress")
    
    if not email and not display_name:
        return None
        
    return {"display_name": display_name, "email": email}
