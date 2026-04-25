"""Module with custom fields processing functions"""

import os
from typing import Any
from typing import List83

from urllib.parse import urlparse

from jira import JIRA
from jira.resources import CustomFieldOption
from jira.resources import Issue
from jira.resources import User

from onyx.connectors.cross_connector_utils.miscellaneous_utils import scoped_url
from onyx.connectors.models import BasicExpertInfo
from onyx.utils.logger import setup_logger

logger = setup_logger()


PROJECT_URL_PAT = "projects"
JIRA_SERVER_API_VERSION = os.environ.get("JIRA_SERVER_API_VERSION") or "2"
JIRA_CLOUD_API_VERSION = os.environ.get("JIRA_CLOUD_API_VERSION") or "3"


def best_effort_basic_expert_info(obj: Any) -> BasicExpertInfo | None:
    display_name = None
    email = None

    try:
        if hasattr(obj, "displayName"):
            display_name = obj.displayName
        else:
            display_name = obj.get("displayName")

        if hasattr(obj, "emailAddress"):
            email = obj.emailAddress
        else:
            email = obj.get("emailAddress")

    except Exception:
        return None

    if not email and not display_name:
        return None

    return BasicExpertInfo(display_name=display_name, email=email)


def best_effort_get_field_from_issue(jira_issue: Issue, field: str) -> Any:
    if hasattr(jira_issue, field):
        return getattr(jira_issue, field)

    if hasattr(jira_issue, "fields") and hasattr(jira_issue.fields, field):
        return getattr(jira_issue.fields, field)

    try:
        return jira_issue.raw["fields"][field]
    except Exception:
        return None


def extract_text_from_adf(adf: dict[str, Any] | None) -> str:
    """Extracts plain text from Atlassian Document Format with improved formatting."""
    if adf is None:
        return ""

    texts: list[str] = []

    def _traverse(node: Any) -> None:
        if not isinstance(node, dict):
            return

        node_type = node.get("type")

        if node_type == "text":
            text = node.get("text", "")
            if text:
                texts.append(text)

        elif node_type == "hardBreak":
            texts.append("\n")
        elif node_type == "paragraph":
                        if "content" in node:
                                            for child in node["content"]:
                                                                    _traverse(child)
                                                            texts.append("\n")
                                        return

        elif node_type == "heading":
                        if "content" in node:
                                            for child in node["content"]:
                                                                    _traverse(child)
                                                            texts.append("\n")
                                        return

        elif node_type == "listItem":
                        if "content" in node:
                                            for child in node["content"]:
                                                                    _traverse(child)
                                                            texts.append("\n")
                                        return

        elif node_type in ("bulletList", "orderedList"):
                        if "content" in node:
                                            for child in node["content"]:
                                                                    _traverse(child)
                                                            texts.append("\n")
                                        return

        # Generic traversal for other node types
                content = node.get("content")
        if content and isinstance(content, list):
                        for child in content:
                                            _traverse(child)

    _traverse(adf)
    return str("".join(texts).strip())
