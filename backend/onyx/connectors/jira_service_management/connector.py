import copy
import time
from collections.abc import Mapping
from typing import Any

from jira import JIRA
from jira.client import ResultList
from jira.exceptions import JIRAError
from jira.resources import Issue
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.jira_service_management.utils import (
    build_jira_client,
    build_jira_url,
    build_jsm_document_id,
    extract_text_from_adf,
    get_comment_strs,
    is_cloud_credential,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

_JIRA_FULL_PAGE_SIZE = 50
_JIRA_SLIM_PAGE_SIZE = 100
_SLIM_END_BUFFER_SECONDS = 24 * 60 * 60
_MINUTE_MS = 60_000
_MAX_JQL_EXCLUDED_IDS = 200


class _JqlPageResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    issues: list[Any]
    next_page_token: str | None = None
    has_more: bool = False


def _is_cloud_client(jira_client: JIRA, default_is_cloud: bool) -> bool:
    try:
        deployment_type = jira_client.deploymentType
    except AttributeError:
        deployment_type = None
    if isinstance(deployment_type, str) and deployment_type:
        return deployment_type == "Cloud"
    try:
        sdk_is_cloud = jira_client._is_cloud
    except AttributeError:
        sdk_is_cloud = None
    if isinstance(sdk_is_cloud, bool):
        return sdk_is_cloud
    return default_is_cloud


def _translate_jira_error(e: JIRAError, context: str) -> None:
    if e.status_code == 401:
        raise CredentialExpiredError(
            "Invalid or expired Jira Service Management credentials (HTTP 401)."
        ) from e
    if e.status_code == 403:
        raise InsufficientPermissionsError(
            f"Insufficient permissions for Jira Service Management {context} (HTTP 403)."
        ) from e
    if e.status_code in (400, 404):
        raise ConnectorValidationError(
            f"Jira Service Management request failed for {context} (HTTP {e.status_code})."
        ) from e


def _read_optional_str_token(raw_result: Any) -> str | None:
    if isinstance(raw_result, ResultList):
        token = raw_result.nextPageToken
    else:
        try:
            token = raw_result.nextPageToken
        except AttributeError:
            return None
    return token if isinstance(token, str) and token else None


def _read_optional_bool_is_last(raw_result: Any) -> bool | None:
    if isinstance(raw_result, ResultList):
        val = raw_result.isLast
    else:
        try:
            val = raw_result.isLast
        except AttributeError:
            return None
    return val if isinstance(val, bool) else None


def _read_optional_int_total(raw_result: Any) -> int | None:
    if isinstance(raw_result, ResultList):
        val = raw_result.total
    else:
        try:
            val = raw_result.total
        except AttributeError:
            return None
    return val if isinstance(val, int) and not isinstance(val, bool) else None


def _read_start_at(raw_result: Any, default_start: int) -> int:
    if isinstance(raw_result, ResultList):
        val = raw_result.startAt
    else:
        try:
            val = raw_result.startAt
        except AttributeError:
            return default_start
    return val if isinstance(val, int) and not isinstance(val, bool) else default_start


def _cloud_page_result(raw_result: Any, *, request_token: str | None) -> _JqlPageResult:
    issues = list(raw_result)
    returned_token = _read_optional_str_token(raw_result)
    is_last = _read_optional_bool_is_last(raw_result)
    has_more = bool(returned_token) and is_last is not True
    if has_more and request_token is not None and returned_token == request_token:
        raise RuntimeError(
            "Jira Service Management Cloud pagination did not advance: "
            "response repeated request nextPageToken."
        )
    return _JqlPageResult(
        issues=issues,
        next_page_token=returned_token if has_more else None,
        has_more=has_more,
    )


def _server_page_result(
    raw_result: Any, *, start: int, max_results: int
) -> _JqlPageResult:
    issues = list(raw_result)
    total = _read_optional_int_total(raw_result)
    start_at = _read_start_at(raw_result, start)
    is_last = _read_optional_bool_is_last(raw_result)

    if is_last is True:
        has_more = False
    elif total is not None:
        has_more = len(issues) > 0 and (start_at + len(issues)) < total
    else:
        has_more = len(issues) >= max_results and len(issues) > 0

    return _JqlPageResult(
        issues=issues,
        next_page_token=None,
        has_more=has_more,
    )


def _perform_jql_search(
    jira_client: JIRA,
    jql: str,
    *,
    is_cloud: bool,
    next_page_token: str | None = None,
    start: int = 0,
    max_results: int = _JIRA_FULL_PAGE_SIZE,
    fields: str = "*all",
) -> _JqlPageResult:
    use_cloud = _is_cloud_client(jira_client, is_cloud)
    try:
        if use_cloud:
            raw_result: Any = jira_client.enhanced_search_issues(
                jql_str=jql,
                nextPageToken=next_page_token,
                maxResults=max_results,
                fields=fields,
            )
        else:
            raw_result = jira_client.search_issues(
                jql_str=jql,
                startAt=start,
                maxResults=max_results,
                fields=fields,
            )
    except JIRAError as e:
        _translate_jira_error(e, f"JQL query '{jql}'")
        raise

    if raw_result is None:
        if use_cloud:
            raise RuntimeError(
                "Jira Service Management Cloud search returned no result; "
                "verify that the Jira instance is Cloud and reports deploymentType='Cloud'."
            )
        return _JqlPageResult(issues=[], next_page_token=None, has_more=False)

    if use_cloud:
        return _cloud_page_result(raw_result, request_token=next_page_token)
    return _server_page_result(raw_result, start=start, max_results=max_results)


def _issue_raw_fields(issue: Any) -> Mapping[str, Any] | None:
    try:
        raw = issue.raw
    except AttributeError:
        return None
    if isinstance(raw, Mapping):
        fields = raw.get("fields")
        if isinstance(fields, Mapping):
            return fields
    return None


def _extract_issue_id(issue: Any) -> int | None:
    raw_id: Any = None
    try:
        raw = issue.raw
    except AttributeError:
        raw = None
    if isinstance(raw, Mapping) and "id" in raw:
        raw_id = raw["id"]
    if raw_id is None:
        try:
            raw_id = issue.id
        except AttributeError:
            return None
    if isinstance(raw_id, int) and not isinstance(raw_id, bool):
        return raw_id
    if isinstance(raw_id, str) and raw_id.isdigit():
        return int(raw_id)
    return None


def _extract_updated_ms(issue: Any) -> int | None:
    updated_str = _issue_timestamp(issue, "updated")
    if not updated_str:
        return None
    try:
        return int(time_str_to_utc(updated_str).timestamp() * 1000)
    except (TypeError, ValueError, OverflowError):
        return None


def _advance_updated_cursor(
    issues: list[Any],
    *,
    cursor_updated_ms: int | None,
    cursor_seen_ids: list[int],
    offset: int,
) -> tuple[int | None, list[int], int]:
    """Advance a Server/DC ``updated`` watermark cursor without skipping shifted rows.

    Jira Server/Data Center evaluates ``updated >=`` at minute granularity in some
    versions, so IDs seen in the current minute bucket are tracked for
    ``id not in (...)`` exclusion while ``startAt`` stays at ``0``. Only if a
    single minute contains more than ``_MAX_JQL_EXCLUDED_IDS`` issues (or a page
    lacks parseable ``updated`` / numeric ``id`` values) does pagination fall back
    to ``offset`` while keeping the already-excluded ID set fixed.
    """
    prev_minute = (
        cursor_updated_ms // _MINUTE_MS if cursor_updated_ms is not None else None
    )
    next_updated_ms = cursor_updated_ms
    next_minute = prev_minute
    seen_ids = set(cursor_seen_ids)
    observed_updated = False

    for issue in issues:
        updated_ms = _extract_updated_ms(issue)
        issue_id = _extract_issue_id(issue)
        if updated_ms is not None:
            observed_updated = True
            issue_minute = updated_ms // _MINUTE_MS
            if next_minute is None or issue_minute > next_minute:
                next_minute = issue_minute
                seen_ids = set()
                offset = 0
            if next_updated_ms is None or updated_ms > next_updated_ms:
                next_updated_ms = updated_ms
            if issue_id is not None and issue_minute == next_minute:
                seen_ids.add(issue_id)

    if not observed_updated:
        return (cursor_updated_ms, cursor_seen_ids, offset + len(issues))

    if len(seen_ids) > _MAX_JQL_EXCLUDED_IDS:
        # Minute bucket exceeded the JQL exclusion cap: keep the fixed prefix of
        # already-excluded IDs stable and step with offset within this minute.
        fixed_excluded = (
            list(cursor_seen_ids)
            if next_minute == prev_minute and cursor_seen_ids
            else sorted(seen_ids)[:_MAX_JQL_EXCLUDED_IDS]
        )
        return (next_updated_ms, fixed_excluded, offset + len(issues))

    sorted_seen_ids = sorted(seen_ids)
    if next_minute == prev_minute and sorted_seen_ids == cursor_seen_ids:
        # Neither the minute watermark nor the excluded ID set advanced (e.g.,
        # issues lacked numeric IDs), so advance offset to guarantee progress.
        return (next_updated_ms, sorted_seen_ids, offset + len(issues))

    return (next_updated_ms, sorted_seen_ids, 0)


def _issue_labels(issue: Any) -> set[str]:
    raw_fields = _issue_raw_fields(issue)
    if raw_fields is not None and "labels" in raw_fields:
        labels = raw_fields.get("labels") or []
        return {str(label) for label in labels if label}
    try:
        labels = issue.fields.labels or []
    except AttributeError:
        return set()
    return {str(label) for label in labels if label}


def _issue_description(issue: Any) -> Any:
    raw_fields = _issue_raw_fields(issue)
    if raw_fields is not None and "description" in raw_fields:
        return raw_fields.get("description")
    try:
        return issue.fields.description
    except AttributeError:
        return ""


def _issue_creator_or_reporter(issue: Any) -> Any:
    raw_fields = _issue_raw_fields(issue)
    if raw_fields is not None:
        creator = raw_fields.get("creator") or raw_fields.get("reporter")
        if creator is not None:
            return creator
    try:
        creator = issue.fields.creator
    except AttributeError:
        creator = None
    if creator is not None:
        return creator
    try:
        return issue.fields.reporter
    except AttributeError:
        return None


def _person_info(person: Any) -> BasicExpertInfo | None:
    if person is None:
        return None
    if isinstance(person, Mapping):
        display_name = person.get("displayName")
        email = person.get("emailAddress")
    else:
        try:
            display_name = person.displayName
        except AttributeError:
            display_name = None
        try:
            email = person.emailAddress
        except AttributeError:
            email = None
    if not display_name and not email:
        return None
    return BasicExpertInfo(
        display_name=str(display_name) if display_name else None,
        email=str(email) if email else None,
    )


def _named_attr(obj: Any, default: str | None = None) -> str | None:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        name = obj.get("name")
        return str(name) if name else default
    try:
        name = obj.name
    except AttributeError:
        return default
    return str(name) if name else default


def _project_key(issue: Any) -> str:
    raw_fields = _issue_raw_fields(issue)
    if raw_fields is not None:
        proj = raw_fields.get("project")
        if isinstance(proj, Mapping) and proj.get("key"):
            return str(proj["key"])
    try:
        proj = issue.fields.project
        if proj is not None and proj.key:
            return str(proj.key)
    except AttributeError:
        pass
    return "N/A"


def _status_name(issue: Any) -> str:
    raw_fields = _issue_raw_fields(issue)
    if raw_fields is not None and "status" in raw_fields:
        return _named_attr(raw_fields.get("status"), "N/A") or "N/A"
    try:
        return _named_attr(issue.fields.status, "N/A") or "N/A"
    except AttributeError:
        return "N/A"


def _issuetype_name(issue: Any) -> str | None:
    raw_fields = _issue_raw_fields(issue)
    if raw_fields is not None and "issuetype" in raw_fields:
        return _named_attr(raw_fields.get("issuetype"))
    try:
        return _named_attr(issue.fields.issuetype)
    except AttributeError:
        return None


def _priority_name(issue: Any) -> str | None:
    raw_fields = _issue_raw_fields(issue)
    if raw_fields is not None and "priority" in raw_fields:
        return _named_attr(raw_fields.get("priority"))
    try:
        return _named_attr(issue.fields.priority)
    except AttributeError:
        return None


def _issue_summary(issue: Any) -> str:
    raw_fields = _issue_raw_fields(issue)
    if raw_fields is not None and raw_fields.get("summary"):
        return str(raw_fields["summary"])
    try:
        summary = issue.fields.summary
        if summary:
            return str(summary)
    except AttributeError:
        pass
    return str(issue.key)


def _issue_timestamp(issue: Any, field: str) -> str | None:
    raw_fields = _issue_raw_fields(issue)
    if raw_fields is not None and field in raw_fields:
        val = raw_fields.get(field)
        return str(val) if val else None
    try:
        if field == "updated":
            val = issue.fields.updated
        elif field == "created":
            val = issue.fields.created
        else:
            val = None
    except AttributeError:
        return None
    return str(val) if val else None


def process_jira_issue(
    jira_base_url: str,
    issue: Issue,
    comment_email_blacklist: list[str] | None = None,
    labels_to_skip: list[str] | None = None,
    *,
    jira_client: JIRA | None = None,
) -> Document | None:
    issue_labels = _issue_labels(issue)
    if labels_to_skip and issue_labels.intersection(labels_to_skip):
        return None

    raw_desc = _issue_description(issue)
    description = (
        raw_desc if isinstance(raw_desc, str) else extract_text_from_adf(raw_desc)
    )

    comments = get_comment_strs(
        issue,
        comment_email_blacklist=comment_email_blacklist,
        jira_client=jira_client,
    )
    comment_block = "\n".join(f"Comment: {c}" for c in comments if c)
    content = (
        f"{description}\n{comment_block}".strip() if comment_block else description
    )

    doc_id = build_jsm_document_id(jira_base_url, issue.key)
    page_url = build_jira_url(jira_base_url, issue.key)

    expert = _person_info(_issue_creator_or_reporter(issue))
    primary_owners = [expert] if expert is not None else None

    metadata: dict[str, str | list[str]] = {
        "key": issue.key,
        "status": _status_name(issue),
        "project": _project_key(issue),
    }
    issue_type = _issuetype_name(issue)
    if issue_type:
        metadata["issuetype"] = issue_type
    priority = _priority_name(issue)
    if priority:
        metadata["priority"] = priority
    if issue_labels:
        metadata["labels"] = sorted(issue_labels)

    summary = _issue_summary(issue)
    updated_str = _issue_timestamp(issue, "updated")

    return Document(
        id=doc_id,
        sections=[TextSection(link=page_url, text=content)],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=f"{issue.key}: {summary}",
        title=f"{issue.key} {summary}",
        primary_owners=primary_owners,
        doc_updated_at=time_str_to_utc(updated_str) if updated_str else None,
        metadata=metadata,
    )


class JiraServiceManagementConnectorCheckpoint(ConnectorCheckpoint):
    # Cloud (v3) continuation token returned by enhanced_search_issues.
    next_page_token: str | None = None
    # Server / Data Center (v2) keyset cursor on immutable numeric issue ID.
    last_issue_id: int | None = None
    # Server / Data Center (v2) watermark cursor for multi-project / custom JQL
    # scans where Data Center `id >` range filtering is unsupported.
    cursor_updated_ms: int | None = None
    # Issue IDs already processed in the current `cursor_updated_ms` minute bucket.
    cursor_seen_ids: list[int] = Field(default_factory=list)
    # Fallback offset for responses without usable watermark timestamps/IDs or
    # extreme same-minute tie-groups exceeding `_MAX_JQL_EXCLUDED_IDS`.
    offset: int = 0
    # Upper time bound pinned on the first page so checkpoint resumptions query a
    # fixed time window.
    pinned_end: float | None = None


class JiraServiceManagementConnector(
    CheckpointedConnector[JiraServiceManagementConnectorCheckpoint],
    SlimConnector,
):
    """Ingests Jira Service Management requests, incidents, and service tickets.

    Permissions: this connector does not declare permission-sync support
    (``CheckpointedConnectorWithPermSync`` / ``SlimConnectorWithPermSync``) because
    JSM service-desk customer/organization/agent ACL syncing is not implemented.
    Scope the API credential and ``project_key`` / ``jql_query`` to tickets that are
    appropriate to expose to the configured Onyx access group.
    """

    slim_listing_honors_indexing_start = True

    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        scoped_token: bool = False,
    ) -> None:
        self.jira_base = jira_base_url.rstrip("/")
        self.project_key = (project_key or "").strip() or None
        self.comment_email_blacklist = comment_email_blacklist or []
        self.labels_to_skip = list(labels_to_skip)
        self.jql_query = (jql_query or "").strip() or None
        self.batch_size = batch_size or _JIRA_FULL_PAGE_SIZE
        self.scoped_token = scoped_token
        self._jira_client: JIRA | None = None
        self._is_cloud: bool = True

    @property
    def jira_client(self) -> JIRA:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self._jira_client

    @override
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._is_cloud = is_cloud_credential(credentials)
        self._jira_client = build_jira_client(
            credentials,
            self.jira_base,
            scoped_token=self.scoped_token,
        )
        return None

    def _build_jql(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        *,
        start_ms: int | None = None,
        after_issue_id: int | None = None,
        exclude_issue_ids: list[int] | None = None,
        order_by: str = "id ASC",
    ) -> str:
        """Build JQL with timezone-independent epoch-ms bounds and deterministic ordering.

        Unquoted epoch-ms bounds prevent Jira from reinterpreting naive timestamps
        in the authenticated account's profile timezone.
        """
        clauses: list[str] = []
        if self.jql_query:
            clauses.append(f"({self.jql_query})")
        elif self.project_key:
            clauses.append(f'project = "{self.project_key}"')

        effective_start_ms = (
            start_ms
            if start_ms is not None
            else (int(start * 1000) if start is not None else None)
        )
        if effective_start_ms is not None:
            clauses.append(f"updated >= {effective_start_ms}")
        if end is not None:
            clauses.append(f"updated <= {int(end * 1000)}")
        if after_issue_id is not None:
            clauses.append(f"id > {after_issue_id}")
        if exclude_issue_ids:
            id_list = ", ".join(str(issue_id) for issue_id in exclude_issue_ids)
            clauses.append(f"id not in ({id_list})")

        filter_jql = " AND ".join(clauses)
        if filter_jql:
            return f"{filter_jql} ORDER BY {order_by}"
        return f"ORDER BY {order_by}"

    def _can_use_server_keyset(self) -> bool:
        """Restrict Data Center ``id >`` keyset filtering to single-project queries.

        Atlassian documents that ``id >`` filters can return incomplete results across
        multi-project Data Center JQL queries; multi-project and custom-JQL Server/DC
        scans therefore use an ``updated`` watermark cursor (``ORDER BY updated ASC, id ASC``)
        with same-minute ``id not in (...)`` exclusion and ``startAt=0``.
        """
        return self.project_key is not None and self.jql_query is None

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraServiceManagementConnectorCheckpoint,
    ) -> CheckpointOutput[JiraServiceManagementConnectorCheckpoint]:
        new_checkpoint = copy.deepcopy(checkpoint)
        effective_end = (
            new_checkpoint.pinned_end if new_checkpoint.pinned_end is not None else end
        )
        new_checkpoint.pinned_end = effective_end

        page_size = self.batch_size or _JIRA_FULL_PAGE_SIZE
        use_cloud = _is_cloud_client(self.jira_client, self._is_cloud)
        use_keyset = not use_cloud and self._can_use_server_keyset()
        previous_seen_ids = (
            set(new_checkpoint.cursor_seen_ids)
            if not use_cloud and not use_keyset
            else set()
        )

        if use_cloud:
            jql = self._build_jql(start=start, end=effective_end)
            page = _perform_jql_search(
                self.jira_client,
                jql,
                is_cloud=True,
                next_page_token=new_checkpoint.next_page_token,
                max_results=page_size,
            )
        elif use_keyset:
            after_id = new_checkpoint.last_issue_id
            jql = self._build_jql(
                start=start,
                end=effective_end,
                after_issue_id=after_id,
            )
            page = _perform_jql_search(
                self.jira_client,
                jql,
                is_cloud=False,
                start=0 if after_id is not None else new_checkpoint.offset,
                max_results=page_size,
            )
        else:
            start_ms = int(start * 1000)
            if new_checkpoint.cursor_updated_ms is not None:
                start_ms = max(start_ms, new_checkpoint.cursor_updated_ms)
            jql = self._build_jql(
                start_ms=start_ms,
                end=effective_end,
                exclude_issue_ids=new_checkpoint.cursor_seen_ids or None,
                order_by="updated ASC, id ASC",
            )
            page = _perform_jql_search(
                self.jira_client,
                jql,
                is_cloud=False,
                start=new_checkpoint.offset,
                max_results=page_size,
            )

        max_seen_id = new_checkpoint.last_issue_id
        for issue in page.issues:
            issue_id = _extract_issue_id(issue)
            if issue_id is not None and (max_seen_id is None or issue_id > max_seen_id):
                max_seen_id = issue_id
            if issue_id is not None and issue_id in previous_seen_ids:
                continue

            try:
                doc = process_jira_issue(
                    self.jira_base,
                    issue,
                    comment_email_blacklist=self.comment_email_blacklist,
                    labels_to_skip=self.labels_to_skip,
                    jira_client=self.jira_client,
                )
                if doc is not None:
                    yield doc
            except Exception as e:
                issue_key = str(issue.key)
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=build_jsm_document_id(self.jira_base, issue_key),
                        document_link=build_jira_url(self.jira_base, issue_key),
                    ),
                    failure_message=f"Failed to process Jira Service Management issue: {e}",
                    exception=e,
                )

        if use_cloud:
            new_checkpoint.next_page_token = page.next_page_token
            new_checkpoint.has_more = page.has_more
        elif use_keyset:
            if max_seen_id is not None:
                new_checkpoint.last_issue_id = max_seen_id
                new_checkpoint.offset = 0
            else:
                new_checkpoint.offset += len(page.issues)
            new_checkpoint.has_more = page.has_more
        else:
            (
                new_checkpoint.cursor_updated_ms,
                new_checkpoint.cursor_seen_ids,
                new_checkpoint.offset,
            ) = _advance_updated_cursor(
                page.issues,
                cursor_updated_ms=new_checkpoint.cursor_updated_ms,
                cursor_seen_ids=new_checkpoint.cursor_seen_ids,
                offset=new_checkpoint.offset,
            )
            new_checkpoint.has_more = page.has_more

        return new_checkpoint

    @override
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        effective_start = start if start is not None else 0
        effective_end = (
            end if end is not None else (time.time() + _SLIM_END_BUFFER_SECONDS)
        )
        use_cloud = _is_cloud_client(self.jira_client, self._is_cloud)
        use_keyset = not use_cloud and self._can_use_server_keyset()

        next_page_token: str | None = None
        last_issue_id: int | None = None
        cursor_updated_ms: int | None = None
        cursor_seen_ids: list[int] = []
        offset = 0

        while True:
            if callback is not None and callback.should_stop():
                return

            previous_seen_ids = (
                set(cursor_seen_ids) if not use_cloud and not use_keyset else set()
            )
            if use_cloud:
                jql = self._build_jql(start=effective_start, end=effective_end)
                page = _perform_jql_search(
                    self.jira_client,
                    jql,
                    is_cloud=True,
                    next_page_token=next_page_token,
                    max_results=_JIRA_SLIM_PAGE_SIZE,
                    fields="id,key,labels,created,updated",
                )
            elif use_keyset:
                jql = self._build_jql(
                    start=effective_start,
                    end=effective_end,
                    after_issue_id=last_issue_id,
                )
                page = _perform_jql_search(
                    self.jira_client,
                    jql,
                    is_cloud=False,
                    start=0 if last_issue_id is not None else offset,
                    max_results=_JIRA_SLIM_PAGE_SIZE,
                    fields="id,key,labels,created,updated",
                )
            else:
                start_ms = int(effective_start * 1000)
                if cursor_updated_ms is not None:
                    start_ms = max(start_ms, cursor_updated_ms)
                jql = self._build_jql(
                    start_ms=start_ms,
                    end=effective_end,
                    exclude_issue_ids=cursor_seen_ids or None,
                    order_by="updated ASC, id ASC",
                )
                page = _perform_jql_search(
                    self.jira_client,
                    jql,
                    is_cloud=False,
                    start=offset,
                    max_results=_JIRA_SLIM_PAGE_SIZE,
                    fields="id,key,labels,created,updated",
                )

            slim_batch: list[SlimDocument | HierarchyNode] = []
            max_seen_id = last_issue_id
            for issue in page.issues:
                issue_id = _extract_issue_id(issue)
                if issue_id is not None and (
                    max_seen_id is None or issue_id > max_seen_id
                ):
                    max_seen_id = issue_id
                if issue_id is not None and issue_id in previous_seen_ids:
                    continue

                issue_labels = _issue_labels(issue)
                if self.labels_to_skip and issue_labels.intersection(
                    self.labels_to_skip
                ):
                    continue
                created_str = _issue_timestamp(issue, "created")
                slim_batch.append(
                    SlimDocument(
                        id=build_jsm_document_id(self.jira_base, issue.key),
                        doc_created_at=(
                            time_str_to_utc(created_str) if created_str else None
                        ),
                    )
                )

            if slim_batch:
                yield slim_batch
                if callback is not None:
                    callback.progress(
                        "JiraServiceManagementConnector.retrieve_all_slim_docs",
                        len(slim_batch),
                    )

            if not page.has_more:
                break

            if use_cloud:
                next_page_token = page.next_page_token
            elif use_keyset:
                if max_seen_id is not None:
                    last_issue_id = max_seen_id
                    offset = 0
                else:
                    offset += len(page.issues)
            else:
                cursor_updated_ms, cursor_seen_ids, offset = _advance_updated_cursor(
                    page.issues,
                    cursor_updated_ms=cursor_updated_ms,
                    cursor_seen_ids=cursor_seen_ids,
                    offset=offset,
                )

    @override
    def build_dummy_checkpoint(self) -> JiraServiceManagementConnectorCheckpoint:
        return JiraServiceManagementConnectorCheckpoint(has_more=True)

    @override
    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        try:
            if self.jql_query:
                _perform_jql_search(
                    self.jira_client,
                    self.jql_query,
                    is_cloud=self._is_cloud,
                    max_results=1,
                    fields="id",
                )
            elif self.project_key:
                self.jira_client.project(self.project_key)
            else:
                self.jira_client.projects()
        except JIRAError as e:
            _translate_jira_error(e, "connector validation")
            raise

    @override
    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> JiraServiceManagementConnectorCheckpoint:
        return JiraServiceManagementConnectorCheckpoint.model_validate_json(
            checkpoint_json
        )
