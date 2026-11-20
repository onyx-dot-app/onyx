from typing import Any

from jira import JIRA

from onyx.utils.logger import setup_logger

logger = setup_logger()

JIRA_CLOUD_API_VERSION = "3"


def build_jira_client(
    credentials: dict[str, Any],
    jira_base: str,
    scoped_token: bool = False,
) -> JIRA:
    user_email = credentials.get("jira_user_email") or credentials.get("jira_api_email")
    api_token = credentials.get("jira_api_token")

    if not user_email or not api_token:
        raise ValueError("Missing Jira user email or API token.")

    options: dict[str, Any] = {
        "server": jira_base.rstrip("/"),
        "rest_api_version": JIRA_CLOUD_API_VERSION,
    }
    return JIRA(options=options, basic_auth=(user_email, api_token))


def build_jira_url(base_url: str, issue_key: str) -> str:
    return f"{base_url.rstrip('/')}/browse/{issue_key}"


def extract_text_from_adf(adf_content: Any) -> str:
    """Extract plain text from Atlassian Document Format (ADF JSON/dict)."""
    if not adf_content:
        return ""
    if isinstance(adf_content, str):
        return adf_content

    text_parts: list[str] = []

    def _traverse(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text":
                text_val = node.get("text", "")
                if text_val:
                    text_parts.append(str(text_val))
            for value in node.values():
                _traverse(value)
        elif isinstance(node, list):
            for item in node:
                _traverse(item)

    _traverse(adf_content)
    return " ".join(text_parts)


def get_comment_strs(
    issue: Any,
    comment_email_blacklist: list[str] | set[str] | None = None,
) -> list[str]:
    comments: list[str] = []
    blacklist = set(comment_email_blacklist or [])
    try:
        raw_comments = getattr(getattr(issue.fields, "comment", None), "comments", []) or []
        for comment in raw_comments:
            author = getattr(comment, "author", None)
            author_email = getattr(author, "emailAddress", "") if author else ""
            if author_email and author_email in blacklist:
                continue

            body = getattr(comment, "body", "")
            text = body if isinstance(body, str) else extract_text_from_adf(body)
            if text:
                comments.append(text)
    except AttributeError:
        pass
    return comments
