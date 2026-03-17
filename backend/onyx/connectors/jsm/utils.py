"""Module with custom fields processing functions"""

import os
from typing import Any
from typing import List
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
JSM_SERVER_API_VERSION = os.environ.get("JSM_SERVER_API_VERSION") or "2"
JSM_CLOUD_API_VERSION = "rest/servicedeskapi"


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


def best_effort_get_field_from_issue(jsm_issue: Issue, field: str) -> Any:
    if hasattr(jsm_issue, field):
        return getattr(jsm_issue, field)

    if hasattr(jsm_issue, "fields") and hasattr(jsm_issue.fields, field):
        return getattr(jsm_issue.fields, field)

    try:
        return jsm_issue.raw["fields"][field]
    except Exception:
        return None


def extract_text_from_adf(adf: dict | None) -> str:
    """Extracts plain text from Atlassian Document Format:
    https://developer.atlassian.com/cloud/jsm/platform/apis/document/structure/

    WARNING: This function is incomplete and will e.g. skip lists!
    """
    # TODO: complete this function
    texts = []
    if adf is not None and "content" in adf:
        for block in adf["content"]:
            if "content" in block:
                for item in block["content"]:
                    if item["type"] == "text":
                        texts.append(item["text"])
    return " ".join(texts)


def build_jsm_url(jsm_base_url: str, issue_key: str) -> str:
    """
    Get the url used to access an issue in the UI.
    """
    return f"{jsm_base_url}/browse/{issue_key}"


def build_jsm_client(
    credentials: dict[str, Any], jsm_base: str, scoped_token: bool = False
) -> JSM:

    jsm_base = scoped_url(jsm_base, "jsm") if scoped_token else jsm_base
    api_token = credentials["jsm_api_token"]
    # if user provide an email we assume it's cloud
    if "jsm_user_email" in credentials:
        email = credentials["jsm_user_email"]
        return JSM(
            basic_auth=(email, api_token),
            server=jsm_base,
            options={"rest_api_version": JSM_CLOUD_API_VERSION},
        )
    else:
        return JSM(
            token_auth=api_token,
            server=jsm_base,
            options={"rest_api_version": JSM_SERVER_API_VERSION},
        )


def extract_jsm_project(url: str) -> tuple[str, str]:
    parsed_url = urlparse(url)
    jsm_base = parsed_url.scheme + "://" + parsed_url.netloc

    # Split the path by '/' and find the position of 'projects' to get the project name
    split_path = parsed_url.path.split("/")
    if PROJECT_URL_PAT in split_path:
        project_pos = split_path.index(PROJECT_URL_PAT)
        if len(split_path) > project_pos + 1:
            jsm_project = split_path[project_pos + 1]
        else:
            raise ValueError("No project name found in the URL")
    else:
        raise ValueError("'projects' not found in the URL")

    return jsm_base, jsm_project


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
            logger.error(f"Failed to process comment due to an error: {e}")
            continue

    return comment_strs


def get_jsm_project_key_from_issue(issue: Issue) -> str | None:
    if not hasattr(issue, "fields"):
        return None
    if not hasattr(issue.fields, "project"):
        return None
    if not hasattr(issue.fields.project, "key"):
        return None

    return issue.fields.project.key


class CustomFieldExtractor:
    @staticmethod
    def _process_custom_field_value(value: Any) -> str:
        """
        Process a custom field value to a string
        """
        try:
            if isinstance(value, str):
                return value
            elif isinstance(value, CustomFieldOption):
                return value.value
            elif isinstance(value, User):
                return value.displayName
            elif isinstance(value, List):
                return " ".join(
                    [CustomFieldExtractor._process_custom_field_value(v) for v in value]
                )
            else:
                return str(value)
        except Exception as e:
            logger.error(f"Error processing custom field value {value}: {e}")
            return ""

    @staticmethod
    def get_issue_custom_fields(
        jsm: Issue, custom_fields: dict, max_value_length: int = 250
    ) -> dict:
        """
        Process all custom fields of an issue to a dictionary of strings
        :param jsm: jsm_issue, bug or similar
        :param custom_fields: custom fields dictionary
        :param max_value_length: maximum length of the value to be processed, if exceeded, it will be truncated
        """

        issue_custom_fields = {
            custom_fields[key]: value
            for key, value in jsm.fields.__dict__.items()
            if value and key in custom_fields.keys()
        }

        processed_fields = {}

        if issue_custom_fields:
            for key, value in issue_custom_fields.items():
                processed = CustomFieldExtractor._process_custom_field_value(value)
                # We need max length  parameter, because there are some plugins that often has very long description
                # and there is just a technical information so we just avoid long values
                if len(processed) < max_value_length:
                    processed_fields[key] = processed

        return processed_fields

    @staticmethod
    def get_all_custom_fields(jsm_client: JSM) -> dict:
        """Get all custom fields from JSM"""
        fields = jsm_client.fields()
        fields_dct = {
            field["id"]: field["name"] for field in fields if field["custom"] is True
        }
        return fields_dct


class CommonFieldExtractor:
    @staticmethod
    def get_issue_common_fields(jsm: Issue) -> dict:
        return {
            "Priority": jsm.fields.priority.name if jsm.fields.priority else None,
            "Reporter": (
                jsm.fields.reporter.displayName if jsm.fields.reporter else None
            ),
            "Assignee": (
                jsm.fields.assignee.displayName if jsm.fields.assignee else None
            ),
            "Status": jsm.fields.status.name if jsm.fields.status else None,
            "Resolution": (
                jsm.fields.resolution.name if jsm.fields.resolution else None
            ),
        }
