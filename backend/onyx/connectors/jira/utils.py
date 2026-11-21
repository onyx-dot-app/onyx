import os
from typing import Any
from urllib.parse import urlparse

from onyx.connectors.models import BasicExpertInfo
from onyx.utils.logger import setup_logger

logger = setup_logger()


PROJECT_URL_PAT = "projects"
JIRA_SERVER_API_VERSION = os.environ.get("JIRA_SERVER_API_VERSION") or "2"
JIRA_CLOUD_API_VERSION = os.environ.get("JIRA_CLOUD_API_VERSION") or "3"

# Permission sync reads who holds this permission in each project.
BROWSE_PROJECTS_PERMISSION = "BROWSE_PROJECTS"
HOLDER_TYPE_ANYONE = "anyone"
HOLDER_TYPE_APPLICATION_ROLE = "applicationRole"
HOLDER_TYPE_USER = "user"
HOLDER_TYPE_PROJECT_ROLE = "projectRole"
HOLDER_TYPE_GROUP = "group"

SUPPORTED_STATIC_HOLDER_TYPES = {
    HOLDER_TYPE_ANYONE,
    HOLDER_TYPE_APPLICATION_ROLE,
    HOLDER_TYPE_USER,
    HOLDER_TYPE_PROJECT_ROLE,
    HOLDER_TYPE_GROUP,
}

# Jira DC/Server returns project-role actors flat with this `type` discriminator;
# Jira Cloud v3 instead wraps them in nested `actorGroup` / `actorUser` objects.
ATLASSIAN_GROUP_ROLE_ACTOR_TYPE = "atlassian-group-role-actor"
ATLASSIAN_USER_ROLE_ACTOR_TYPE = "atlassian-user-role-actor"


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


def get_issue_field(issue: dict[str, Any], field: str) -> Any:
    """A field of a raw issue, or None when the issue does not have it."""
    fields: Any = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    return fields.get(field)


def get_named_field(issue: dict[str, Any], field: str) -> str | None:
    """The ``name`` of an object field of a raw issue (priority, status, ...)."""
    value: Any = get_issue_field(issue, field)
    if isinstance(value, dict):
        name: Any = value.get("name")
        return name if isinstance(name, str) else None
    return None


def extract_text_from_adf(adf: dict | None) -> str:
    """Extracts plain text from Atlassian Document Format:
    https://developer.atlassian.com/cloud/jira/platform/apis/document/structure/
    """
    texts: list[str] = []

    def _extract(node: dict) -> None:
        if node.get("type") == "text":
            text = node.get("text", "")
            if text:
                texts.append(text)
        for child in node.get("content", []):
            _extract(child)

    if adf is not None:
        _extract(adf)
    return " ".join(texts)


def rich_text(value: Any) -> str:
    """Plain text of a Jira rich-text value: a string on REST v2, Atlassian
    Document Format on REST v3."""
    if isinstance(value, str):
        return value
    return extract_text_from_adf(value if isinstance(value, dict) else None)


def build_jira_url(jira_base_url: str, issue_key: str) -> str:
    """
    Get the url used to access an issue in the UI.
    """
    return f"{jira_base_url}/browse/{issue_key}"


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
    issue: dict[str, Any],
    comment_email_blacklist: tuple[str, ...] = (),
    skip_restricted: bool = False,
    skip_jsm_internal: bool = False,
) -> list[str]:
    """Extract comment text from a Jira issue.

    Args:
        issue: Raw Jira issue dict
        comment_email_blacklist: Email addresses whose comments to skip
        skip_restricted: When True, skip comments with visibility restrictions
        skip_jsm_internal: When True, skip JSM internal comments. Checks both
            jsdPublic field and sd.public.comment property. Handles properties
            as dict or list, and boolean values as bool or string ("true"/"false").
            Fails closed (skips comment) when JSM markers cannot be determined.

    Returns:
        List of comment text strings
    """
    comment_field: dict[str, Any] = get_issue_field(issue, "comment") or {}
    comment_strs: list[str] = []
    for comment in comment_field.get("comments", []):
        try:
            author: dict[str, Any] = comment.get("author") or {}
            if author.get("emailAddress") in comment_email_blacklist:
                continue

            if skip_restricted and comment.get("visibility") is not None:
                continue

            if skip_jsm_internal:
                # Check jsdPublic field (handles bool and string representations)
                jsd_public = comment.get("jsdPublic")
                if jsd_public is not None:
                    # Handle string representations like "false"/"true"
                    if isinstance(jsd_public, str):
                        jsd_public_normalized = jsd_public.lower() == "true"
                    else:
                        jsd_public_normalized = bool(jsd_public)
                    if not jsd_public_normalized:
                        continue

                # Check properties field (can be dict or list of property objects)
                properties: Any = comment.get("properties")
                should_skip = False
                
                # Handle properties as dict
                if isinstance(properties, dict):
                    sd_public_comment = properties.get("sd.public.comment")
                    if isinstance(sd_public_comment, dict):
                        internal_value = sd_public_comment.get("internal")
                        if internal_value is None:
                            logger.warning(
                                "JSM comment has sd.public.comment property but internal value is missing; skipping for safety"
                            )
                            should_skip = True
                        else:
                            # Handle string representations like "false"/"true"
                            if isinstance(internal_value, str):
                                internal_normalized = internal_value.lower() == "true"
                            else:
                                internal_normalized = bool(internal_value)
                            if internal_normalized:
                                should_skip = True
                
                # Handle properties as list
                elif isinstance(properties, list):
                    for prop in properties:
                        if isinstance(prop, dict) and prop.get("key") == "sd.public.comment":
                            prop_value = prop.get("value")
                            if isinstance(prop_value, dict):
                                internal_value = prop_value.get("internal")
                                if internal_value is None:
                                    logger.warning(
                                        "JSM comment has sd.public.comment property but internal value is missing; skipping for safety"
                                    )
                                    should_skip = True
                                else:
                                    # Handle string representations like "false"/"true"
                                    if isinstance(internal_value, str):
                                        internal_normalized = internal_value.lower() == "true"
                                    else:
                                        internal_normalized = bool(internal_value)
                                    if internal_normalized:
                                        should_skip = True
                            break
                
                if should_skip:
                    continue

            comment_strs.append(rich_text(comment.get("body")))
        except Exception as e:
            logger.error("Failed to process comment due to an error: %s", e)
            continue

    return comment_strs
