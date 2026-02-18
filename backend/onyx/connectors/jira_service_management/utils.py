from typing import Any
from jira import JIRA
from onyx.utils.logger import setup_logger

logger = setup_logger()

JIRA_CLOUD_API_VERSION = "3"

def build_jira_client(credentials: dict[str, Any], jira_base: str, scoped_token: bool = False) -> JIRA:
    user_email = credentials.get("jira_user_email")
    api_token = credentials.get("jira_api_token")
    
    # Fix: Validate credentials before attempting connection
    if not user_email or not api_token:
        raise ValueError("Missing Jira user email or API token.")
    
    options = {"server": jira_base, "rest_api_version": JIRA_CLOUD_API_VERSION}
    return JIRA(options=options, basic_auth=(user_email, api_token))

def build_jira_url(base_url: str, issue_key: str) -> str:
    return f"{base_url}/browse/{issue_key}"

def extract_text_from_adf(adf_content: Any) -> str:
    if not adf_content:
        return ""
    text_parts = []
    def _traverse(node: Any):
        if isinstance(node, dict):
            if node.get("type") == "text":
                text_parts.append(node.get("text", ""))
            for value in node.values():
                _traverse(value)
        elif isinstance(node, list):
            for item in node:
                _traverse(item)
    _traverse(adf_content)
    return " ".join(text_parts)

def get_comment_strs(issue: Any, comment_email_blacklist: Any = None) -> list[str]:
    comments = []
    try:
        for comment in issue.fields.comment.comments:
            author_email = getattr(comment.author, "emailAddress", "")
            if comment_email_blacklist and author_email in comment_email_blacklist:
                continue
            comments.append(comment.body)
    except AttributeError:
        pass
    return comments

def best_effort_get_field_from_issue(issue: Any, field_name: str) -> Any:
    try:
        return getattr(issue.fields, field_name, None)
    except Exception:
        return None

def best_effort_basic_expert_info(user_obj: Any) -> Any:
    if not user_obj:
        return None
    return {
        "display_name": getattr(user_obj, "displayName", "Unknown"),
        "email": getattr(user_obj, "emailAddress", None)
    }