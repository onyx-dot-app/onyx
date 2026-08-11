"""Shared helpers for the Jira connector"""

import os
from typing import Any
from urllib.parse import urlparse

from jira import JIRA
from jira.resources import Issue

from onyx.connectors.cross_connector_utils.miscellaneous_utils import scoped_url
from onyx.connectors.jira.adf import extract_text_from_adf
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


def build_jira_url(jira_base_url: str, issue_key: str) -> str:
    """
    Get the url used to access an issue in the UI.
    """
    return f"{jira_base_url}/browse/{issue_key}"


def build_jira_client(
    credentials: dict[str, Any], jira_base: str, scoped_token: bool = False
) -> JIRA:
    jira_base = scoped_url(jira_base, "jira") if scoped_token else jira_base
    api_token = credentials["jira_api_token"]
    # if user provide an email we assume it's cloud
    if "jira_user_email" in credentials:
        email = credentials["jira_user_email"]
        return JIRA(
            basic_auth=(email, api_token),
            server=jira_base,
            options={"rest_api_version": JIRA_CLOUD_API_VERSION},
        )
    else:
        return JIRA(
            token_auth=api_token,
            server=jira_base,
            options={"rest_api_version": JIRA_SERVER_API_VERSION},
        )


def extract_jira_project(url: str) -> tuple[str, str]:
    parsed_url = urlparse(url)
    jira_base = parsed_url.scheme + "://" + parsed_url.netloc

    # Split the path by '/' and find the position of 'projects' to get the project name
    split_path = parsed_url.path.split("/")
    if PROJECT_URL_PAT in split_path:
        project_pos = split_path.index(PROJECT_URL_PAT)
        if len(split_path) > project_pos + 1:
            jira_project = split_path[project_pos + 1]
        else:
            raise ValueError("No project name found in the URL")
    else:
        raise ValueError("'projects' not found in the URL")

    return jira_base, jira_project


def get_comment_strs(
    issue: Issue, comment_email_blacklist: tuple[str, ...] = ()
) -> list[str]:
    comment_strs = []
    for comment in issue.fields.comment.comments:
        try:
            if isinstance(comment.body, str):
                body_text = comment.body
            else:
                body_text = extract_text_from_adf(comment.raw["body"])

            if (
                hasattr(comment, "author")
                and hasattr(comment.author, "emailAddress")
                and comment.author.emailAddress in comment_email_blacklist
            ):
                continue  # Skip adding comment if author's email is in blacklist

            comment_strs.append(body_text)
        except Exception as e:
            logger.error("Failed to process comment due to an error: %s", e)
            continue

    return comment_strs


def get_jira_project_key_from_issue(issue: Issue) -> str | None:
    if not hasattr(issue, "fields"):
        return None
    if not hasattr(issue.fields, "project"):
        return None
    if not hasattr(issue.fields.project, "key"):
        return None

    return issue.fields.project.key
