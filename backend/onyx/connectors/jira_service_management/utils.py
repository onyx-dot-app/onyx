import os
from collections.abc import Mapping
from typing import Any

from jira import JIRA
from jira.resources import PropertyHolder

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.connectors.cross_connector_utils.miscellaneous_utils import scoped_url
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.utils.logger import setup_logger

logger = setup_logger()

JIRA_SERVER_API_VERSION = os.environ.get("JIRA_SERVER_API_VERSION") or "2"
JIRA_CLOUD_API_VERSION = os.environ.get("JIRA_CLOUD_API_VERSION") or "3"
JIRA_CONNECT_TIMEOUT_SECONDS = 10
JIRA_READ_TIMEOUT_SECONDS = REQUEST_TIMEOUT_SECONDS
_COMMENT_PAGE_SIZE = 50

_ADF_BLOCK_NODE_TYPES = frozenset(
    {
        "doc",
        "paragraph",
        "heading",
        "bulletList",
        "orderedList",
        "listItem",
        "blockquote",
        "codeBlock",
        "panel",
        "table",
        "tableRow",
        "tableCell",
        "tableHeader",
        "rule",
    }
)


def is_cloud_credential(credentials: Mapping[str, Any]) -> bool:
    """True when the credential includes an account email (Atlassian Cloud).

    Token-only credentials authenticate against Jira Server / Data Center via PAT.
    """
    return bool(credentials.get("jira_user_email") or credentials.get("jira_api_email"))


def build_jira_client(
    credentials: Mapping[str, Any],
    jira_base: str,
    scoped_token: bool = False,
) -> JIRA:
    user_email = credentials.get("jira_user_email") or credentials.get("jira_api_email")
    api_token = credentials.get("jira_api_token")

    if not api_token:
        raise ConnectorMissingCredentialError("Jira Service Management")

    normalized_base = jira_base.rstrip("/")
    api_url = scoped_url(normalized_base, "jira") if scoped_token else normalized_base
    timeout = (JIRA_CONNECT_TIMEOUT_SECONDS, JIRA_READ_TIMEOUT_SECONDS)

    if user_email:
        return JIRA(
            server=api_url,
            options={"rest_api_version": JIRA_CLOUD_API_VERSION},
            basic_auth=(str(user_email), str(api_token)),
            timeout=timeout,
        )

    return JIRA(
        server=api_url,
        options={"rest_api_version": JIRA_SERVER_API_VERSION},
        token_auth=str(api_token),
        timeout=timeout,
    )


def build_jira_url(base_url: str, issue_key: str) -> str:
    return f"{base_url.rstrip('/')}/browse/{issue_key}"


def build_jsm_document_id(base_url: str, issue_key: str) -> str:
    """Return a JSM-scoped document ID distinct from the Jira connector's browse URL."""
    return f"jira_service_management:{build_jira_url(base_url, issue_key)}"


def _node_as_mapping(node: Any) -> Mapping[str, Any] | None:
    if isinstance(node, Mapping):
        return node
    if isinstance(node, PropertyHolder):
        return vars(node)
    if isinstance(node, (str, bytes, int, float, bool, list, tuple, set)):
        return None
    try:
        node_dict = vars(node)
    except TypeError:
        return None
    raw = node_dict.get("raw")
    if isinstance(raw, Mapping):
        return raw
    return node_dict


def extract_text_from_adf(adf_content: Any) -> str:
    """Extract plain text from Atlassian Document Format (ADF dicts or SDK PropertyHolder).

    Adjacent inline text nodes inside the same block are concatenated directly so
    tokens like ``JSM-`` + bold ``101`` remain ``JSM-101``. Block boundaries and
    explicit ``hardBreak`` nodes emit line breaks.
    """
    if not adf_content:
        return ""
    if isinstance(adf_content, str):
        return adf_content

    chunks: list[str] = []
    visited: set[int] = set()

    def _append_break() -> None:
        if chunks and not chunks[-1].endswith("\n"):
            chunks.append("\n")

    def _traverse(node: Any) -> None:
        if node is None or isinstance(node, (str, bytes, int, float, bool)):
            return

        node_id = id(node)
        if node_id in visited:
            return
        visited.add(node_id)

        if isinstance(node, (list, tuple)):
            for item in node:
                _traverse(item)
            return

        node_map = _node_as_mapping(node)
        if node_map is None:
            return

        node_type = node_map.get("type")
        if node_type == "text":
            text_val = node_map.get("text")
            if text_val:
                chunks.append(str(text_val))
            return

        if node_type == "hardBreak":
            _append_break()
            return

        is_block = isinstance(node_type, str) and node_type in _ADF_BLOCK_NODE_TYPES
        if is_block:
            _append_break()

        content = node_map.get("content")
        if content is not None:
            _traverse(content)
        else:
            for key, value in node_map.items():
                if key in ("type", "text", "marks"):
                    continue
                _traverse(value)

        if is_block:
            _append_break()

    _traverse(adf_content)
    return "".join(chunks).strip()


def _raw_issue_fields(issue: Any) -> Mapping[str, Any] | None:
    try:
        raw = issue.raw
    except AttributeError:
        return None
    if isinstance(raw, Mapping):
        fields = raw.get("fields")
        if isinstance(fields, Mapping):
            return fields
    return None


def _comment_author_email(comment: Any) -> str:
    if isinstance(comment, Mapping):
        author = comment.get("author")
        if isinstance(author, Mapping):
            email = author.get("emailAddress")
            return str(email) if email else ""
        return ""
    try:
        author = comment.author
    except AttributeError:
        return ""
    if author is None:
        return ""
    if isinstance(author, Mapping):
        email = author.get("emailAddress")
        return str(email) if email else ""
    try:
        email = author.emailAddress
    except AttributeError:
        return ""
    return str(email) if email else ""


def _comment_body(comment: Any) -> Any:
    if isinstance(comment, Mapping):
        return comment.get("body", "")
    try:
        raw = comment.raw
    except AttributeError:
        raw = None
    if isinstance(raw, Mapping) and "body" in raw:
        return raw["body"]
    try:
        return comment.body
    except AttributeError:
        return ""


def _embedded_comments_and_total(issue: Any) -> tuple[list[Any], int | None]:
    raw_fields = _raw_issue_fields(issue)
    if raw_fields is not None:
        raw_comment_obj = raw_fields.get("comment")
        if isinstance(raw_comment_obj, Mapping):
            raw_comments = raw_comment_obj.get("comments")
            raw_total = raw_comment_obj.get("total")
            total = (
                raw_total
                if isinstance(raw_total, int) and not isinstance(raw_total, bool)
                else None
            )
            return (list(raw_comments) if raw_comments else [], total)

    try:
        comment_obj = issue.fields.comment
    except AttributeError:
        return ([], None)
    if comment_obj is None:
        return ([], None)

    try:
        embedded = list(comment_obj.comments or [])
    except AttributeError:
        embedded = []

    try:
        raw_total = comment_obj.total
    except AttributeError:
        raw_total = None
    total = (
        raw_total
        if isinstance(raw_total, int) and not isinstance(raw_total, bool)
        else None
    )
    return (embedded, total)


def _fetch_remaining_comments(
    jira_client: JIRA,
    issue_key: str,
    start_at: int,
    total: int,
) -> list[Any]:
    fetched: list[Any] = []
    cursor = start_at
    while cursor < total:
        page = jira_client.comments(
            issue_key,
            start_at=cursor,
            max_results=_COMMENT_PAGE_SIZE,
        )
        if not page:
            break
        fetched.extend(page)
        cursor += len(page)
    return fetched


def get_comment_strs(
    issue: Any,
    comment_email_blacklist: list[str] | set[str] | None = None,
    *,
    jira_client: JIRA | None = None,
) -> list[str]:
    comments: list[str] = []
    blacklist = set(comment_email_blacklist or [])

    embedded, total = _embedded_comments_and_total(issue)
    all_comments = list(embedded)
    if jira_client is not None and total is not None and total > len(embedded):
        all_comments.extend(
            _fetch_remaining_comments(
                jira_client,
                str(issue.key),
                start_at=len(embedded),
                total=total,
            )
        )

    for comment in all_comments:
        author_email = _comment_author_email(comment)
        if author_email and author_email in blacklist:
            continue

        body = _comment_body(comment)
        text = body if isinstance(body, str) else extract_text_from_adf(body)
        if text:
            comments.append(text)

    return comments
