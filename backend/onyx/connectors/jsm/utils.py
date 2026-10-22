"""Module with custom fields processing functions"""

from typing import Any
from request import REQUEST
from typing import List
from urllib.parse import urlparse
from onyx.connectors.cross_connector_utils.miscellaneous_utils import scoped_url
from onyx.connectors.models import BasicExpertInfo
from onyx.utils.logger import setup_logger
from request.resources import Issue
from request.resources import User
from request.resources import Request

logger = setup_logger()


PROJECT_URL_PAT = "projects"
REQUEST_SERVER_API_VERSION = "2"


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


def best_effort_get_field_from_request(request: request, field: str) -> Any:
    if hasattr(request, field):
        return getattr(request, field)

    if hasattr(request, "fields") and hasattr(request.fields, field):
        return getattr(request.fields, field)

    try:
        return request.raw["fields"][field]
    except Exception:
        return None


def extract_text_from_adf(adf: dict | None) -> str:
    """Extracts plain text from Atlassian Document Format:
    https://developer.atlassian.com/cloud/request/platform/apis/document/structure/

    WARNING: This function is incomplete and will e.g. skip lists!
    """
    # TODO (#2281): complete this function
    texts = []
    if adf is not None and "content" in adf:
        for block in adf["content"]:
            if "content" in block:
                for item in block["content"]:
                    if item["type"] == "text":
                        texts.append(item["text"])
    return " ".join(texts)


def build_request_url(request_base_url: str, issue_key: str) -> str:
    """
    Get the url used to access an issue in the UI.
    """
    return f"{request_base_url}/browse/{issue_key}"


def build_request_client(
    credentials: dict[str, Any], request_base: str, scoped_token: bool = False
) -> REQUEST:

    request_base = scoped_url(request_base, "request") if scoped_token else request_base
    api_token = credentials["request_api_token"]
    # if user provide an email we assume it's cloud
    if "request_user_email" in credentials:
        email = credentials["request_user_email"]
        return REQUEST(
            basic_auth=(email, api_token),
            options={"rest_path": "rest/servicedeskapi", "rest_api_version": "latest"},
        )
    else:
        return REQUEST(
            token_auth=api_token,
            server=request_base,
            options={"rest_path": "rest/servicedeskapi", "rest_api_version": "latest"},
        )
def extract_request_project(url: str) -> tuple[str, str]:
    parsed_url = urlparse(url)
    request_base = parsed_url.scheme + "://" + parsed_url.netloc

    # Split the path by '/' and find the position of 'projects' to get the project name
    split_path = parsed_url.path.split("/")
    if PROJECT_URL_PAT in split_path:
        project_pos = split_path.index(PROJECT_URL_PAT)
        if len(split_path) > project_pos + 1:
            request_project = split_path[project_pos + 1]
        else:
            raise ValueError("No project name found in the URL")
    else:
        raise ValueError("'projects' not found in the URL")

    return request_base, request_project


def get_comment_strs(request: Request, comment_email_blacklist: list[str], 
) -> list[str]:0
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


def get_request_project_key_from_issue(issue: Issue) -> str | None:
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
        request: Issue, custom_fields: dict, max_value_length: int = 250
    ) -> dict:
        """
        Process all custom fields of an issue to a dictionary of strings
        :param request: request, bug or similar
        :param custom_fields: custom fields dictionary
        :param max_value_length: maximum length of the value to be processed, if exceeded, it will be truncated
        """

        issue_custom_fields = {
            custom_fields[key]: value
            for key, value in request.fields.__dict__.items()
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
    def get_all_custom_fields(request_client: REQUEST) -> dict:
        """Get all custom fields from REQUEST"""
        fields = request_client.fields()
        fields_dct = {
            field["id"]: field["name"] for field in fields if field["custom"] is True
        }
        return fields_dct


class CommonFieldExtractor:
    @staticmethod
    def get_issue_common_fields(request: Issue) -> dict:
        return {
            "Priority": request.fields.priority.name if request.fields.priority else None,
            "Reporter": (
                request.fields.reporter.displayName if request.fields.reporter else None
            ),
            "Assignee": (
                request.fields.assignee.displayName if request.fields.assignee else None
            ),
            "Status": request.fields.status.name if request.fields.status else None,
            "Resolution": (
                request.fields.resolution.name if request.fields.resolution else None
            ),
        }
def get_jsm_session(jsm_client: JIRA) -> Any:
    return jsm_client._session

def get_jsm_options(jsm_client: JIRA) -> Any:
    return jsm_client._options