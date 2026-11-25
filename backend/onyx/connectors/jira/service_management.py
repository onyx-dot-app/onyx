"""Jira Service Management (JSM) connector extension for Onyx.

Supports indexing Jira Service Management customer requests, service desks,
request types, SLA status cycles, approvals, and customer organizations via
the Atlassian Service Desk REST API (`/rest/servicedeskapi/*`).
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

import requests
from pydantic import BaseModel, Field

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document, SlimDocument, TextSection


class JsmSlaMetric(BaseModel):
    name: str
    elapsed_millis: int = 0
    goal_millis: int | None = None
    breached: bool = False
    paused: bool = False
    completed: bool = False


class JsmApproval(BaseModel):
    id: str
    name: str
    final_decision: str = "pending"
    approvers: list[str] = Field(default_factory=list)


class JsmCustomerRequest(BaseModel):
    issue_id: str
    issue_key: str
    service_desk_id: str
    request_type_id: str
    request_type_name: str = ""
    summary: str
    description: str = ""
    current_status: str = ""
    reporter_email: str | None = None
    reporter_display_name: str | None = None
    organizations: list[str] = Field(default_factory=list)
    sla_metrics: list[JsmSlaMetric] = Field(default_factory=list)
    approvals: list[JsmApproval] = Field(default_factory=list)
    comments: list[str] = Field(default_factory=list)
    created_epoch: int = 0
    updated_epoch: int = 0
    web_url: str = ""


def parse_iso_timestamp(ts: str | int | None) -> int:
    if ts is None:
        return 0
    if isinstance(ts, int):
        return ts // 1000 if ts > 10_000_000_000 else ts
    raw = str(ts).strip()
    if not raw:
        return 0
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    elif len(raw) >= 5 and (raw[-5] in ("+", "-")) and ":" not in raw[-5:]:
        raw = raw[:-2] + ":" + raw[-2:]
    try:
        return int(datetime.fromisoformat(raw).astimezone(timezone.utc).timestamp())
    except ValueError:
        return 0


def parse_jsm_sla_values(sla_payload: dict[str, Any] | list[dict[str, Any]]) -> list[JsmSlaMetric]:
    values = (
        sla_payload.get("values", [])
        if isinstance(sla_payload, dict)
        else sla_payload
    )
    metrics: list[JsmSlaMetric] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "SLA")
        ongoing = item.get("ongoingCycle") or {}
        completed_cycles = item.get("completedCycles") or []
        latest_completed = completed_cycles[-1] if completed_cycles else {}
        active = ongoing if ongoing else latest_completed

        elapsed = int((active.get("elapsedTime") or {}).get("millis") or 0)
        goal_raw = (active.get("goalDuration") or {}).get("millis")
        goal = int(goal_raw) if goal_raw is not None else None
        breached = bool(active.get("breached", False))
        paused = bool(active.get("paused", False))
        completed = not bool(ongoing) and bool(completed_cycles)

        metrics.append(
            JsmSlaMetric(
                name=name,
                elapsed_millis=elapsed,
                goal_millis=goal,
                breached=breached,
                paused=paused,
                completed=completed,
            )
        )
    return metrics


def parse_jsm_approvals(approval_payload: dict[str, Any] | list[dict[str, Any]]) -> list[JsmApproval]:
    values = (
        approval_payload.get("values", [])
        if isinstance(approval_payload, dict)
        else approval_payload
    )
    approvals: list[JsmApproval] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        approvers: list[str] = []
        for ap in item.get("approvers") or []:
            approver_obj = ap.get("approver") or {}
            label = (
                approver_obj.get("emailAddress")
                or approver_obj.get("displayName")
                or ""
            )
            if label:
                approvers.append(str(label))
        approvals.append(
            JsmApproval(
                id=str(item.get("id") or ""),
                name=str(item.get("name") or "Approval"),
                final_decision=str(item.get("finalDecision") or "pending"),
                approvers=approvers,
            )
        )
    return approvals


def jsm_request_to_document(
    req: JsmCustomerRequest,
    base_url: str,
) -> Document:
    """Converts a normalized JSM CustomerRequest into an Onyx Document."""
    sections: list[TextSection] = []
    link = req.web_url or f"{base_url.rstrip('/')}/browse/{req.issue_key}"

    body_lines = [
        f"Service Desk Request: {req.issue_key} - {req.summary}",
        f"Request Type: {req.request_type_name or req.request_type_id}",
        f"Status: {req.current_status}",
    ]
    if req.description:
        body_lines.append(f"\nDescription:\n{req.description}")

    if req.sla_metrics:
        sla_summary = []
        for m in req.sla_metrics:
            state = "BREACHED" if m.breached else ("COMPLETED" if m.completed else "ONGOING")
            sla_summary.append(f"{m.name}: {state} (elapsed={m.elapsed_millis}ms)")
        body_lines.append("\nSLA Metrics:\n" + "\n".join(sla_summary))

    if req.approvals:
        approval_summary = [
            f"{a.name}: {a.final_decision} (approvers: {', '.join(a.approvers) or 'none'})"
            for a in req.approvals
        ]
        body_lines.append("\nApprovals:\n" + "\n".join(approval_summary))

    sections.append(TextSection(link=link, text="\n".join(body_lines)))

    for idx, comment in enumerate(req.comments):
        if comment.strip():
            sections.append(
                TextSection(
                    link=f"{link}#comment-{idx + 1}",
                    text=f"Comment {idx + 1}:\n{comment.strip()}",
                )
            )

    metadata: dict[str, str | list[str]] = {
        "issue_key": req.issue_key,
        "service_desk_id": req.service_desk_id,
        "request_type": req.request_type_name or req.request_type_id,
        "status": req.current_status,
        "sla_breached": str(any(m.breached for m in req.sla_metrics)).lower(),
    }
    if req.organizations:
        metadata["organizations"] = req.organizations
    if req.reporter_email:
        metadata["reporter_email"] = req.reporter_email

    updated_dt = (
        datetime.fromtimestamp(req.updated_epoch or req.created_epoch, tz=timezone.utc)
        if (req.updated_epoch or req.created_epoch) > 0
        else None
    )

    return Document(
        id=link,
        sections=sections,
        source=DocumentSource.JIRA,
        semantic_identifier=f"{req.issue_key}: {req.summary}",
        doc_updated_at=updated_dt,
        metadata=metadata,
    )


class JiraServiceManagementConnector:
    """Connector for indexing Atlassian Jira Service Management (JSM) service desks."""

    def __init__(
        self,
        jira_base_url: str,
        service_desk_id: str | None = None,
        request_type_ids: list[str] | None = None,
        include_sla: bool = True,
        include_approvals: bool = True,
        batch_size: int = 50,
    ) -> None:
        self.jira_base_url = jira_base_url.rstrip("/")
        self.service_desk_id = service_desk_id
        self.request_type_ids = set(request_type_ids or [])
        self.include_sla = include_sla
        self.include_approvals = include_approvals
        self.batch_size = batch_size
        self._session: requests.Session | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        session = requests.Session()
        email = credentials.get("jira_user_email") or credentials.get("email")
        token = credentials.get("jira_api_token") or credentials.get("api_token")
        pat = credentials.get("jira_pat") or credentials.get("personal_access_token")
        if email and token:
            session.auth = (str(email), str(token))
        elif pat:
            session.headers["Authorization"] = f"Bearer {pat}"
        session.headers["Accept"] = "application/json"
        session.headers["X-ExperimentalApi"] = "opt-in"
        self._session = session
        return None

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._session is None:
            raise RuntimeError("Credentials not loaded on JiraServiceManagementConnector")
        url = f"{self.jira_base_url}{path}"
        resp = self._session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def list_service_desks(self) -> list[dict[str, Any]]:
        if self.service_desk_id:
            return [{"id": str(self.service_desk_id)}]
        data = self._get_json("/rest/servicedeskapi/servicedesk", params={"limit": self.batch_size})
        return list(data.get("values") or [])

    def _parse_raw_request(self, raw: dict[str, Any]) -> JsmCustomerRequest:
        issue_id = str(raw.get("issueId") or "")
        issue_key = str(raw.get("issueKey") or "")
        sd_id = str(raw.get("serviceDeskId") or self.service_desk_id or "")
        rt_id = str(raw.get("requestTypeId") or "")

        field_values = raw.get("requestFieldValues") or []
        summary = ""
        description = ""
        organizations: list[str] = []
        for fv in field_values:
            fid = str(fv.get("fieldId") or "")
            val = fv.get("value")
            if fid == "summary" and isinstance(val, str):
                summary = val
            elif fid == "description" and isinstance(val, str):
                description = val
            elif fid == "organizations" and isinstance(val, list):
                organizations = [str(o.get("name") or o.get("id")) for o in val if isinstance(o, dict)]

        status_obj = raw.get("currentStatus") or {}
        current_status = str(status_obj.get("status") or "")
        status_epoch = parse_iso_timestamp((status_obj.get("statusDate") or {}).get("iso8601"))
        created_epoch = parse_iso_timestamp((raw.get("createdDate") or {}).get("iso8601"))
        updated_epoch = max(status_epoch, created_epoch)

        reporter = raw.get("reporter") or {}
        links = raw.get("_links") or {}
        web_url = str(links.get("web") or links.get("agent") or f"{self.jira_base_url}/browse/{issue_key}")

        sla_metrics: list[JsmSlaMetric] = []
        if self.include_sla and issue_key:
            try:
                sla_data = self._get_json(f"/rest/servicedeskapi/request/{issue_key}/sla")
                sla_metrics = parse_jsm_sla_values(sla_data)
            except Exception:
                sla_metrics = []

        approvals: list[JsmApproval] = []
        if self.include_approvals and issue_key:
            try:
                app_data = self._get_json(f"/rest/servicedeskapi/request/{issue_key}/approval")
                approvals = parse_jsm_approvals(app_data)
            except Exception:
                approvals = []

        comments: list[str] = []
        if issue_key:
            try:
                comm_data = self._get_json(f"/rest/servicedeskapi/request/{issue_key}/comment")
                for c in comm_data.get("values") or []:
                    body = str(c.get("body") or "").strip()
                    if body:
                        comments.append(body)
            except Exception:
                comments = []

        return JsmCustomerRequest(
            issue_id=issue_id,
            issue_key=issue_key,
            service_desk_id=sd_id,
            request_type_id=rt_id,
            summary=summary or issue_key,
            description=description,
            current_status=current_status,
            reporter_email=reporter.get("emailAddress"),
            reporter_display_name=reporter.get("displayName"),
            organizations=organizations,
            sla_metrics=sla_metrics,
            approvals=approvals,
            comments=comments,
            created_epoch=created_epoch,
            updated_epoch=updated_epoch,
            web_url=web_url,
        )

    def poll_source(
        self,
        start: float = 0.0,
        end: float | None = None,
    ) -> Generator[list[Document], None, None]:
        """Yields batches of Onyx Documents for JSM requests updated inside [start, end]."""
        for desk in self.list_service_desks():
            desk_id = str(desk.get("id") or "")
            start_idx = 0
            while True:
                params: dict[str, Any] = {
                    "start": start_idx,
                    "limit": self.batch_size,
                }
                if desk_id:
                    params["serviceDeskId"] = desk_id
                page = self._get_json("/rest/servicedeskapi/request", params=params)
                values = list(page.get("values") or [])
                if not values:
                    break

                batch_docs: list[Document] = []
                for raw in values:
                    rt_id = str(raw.get("requestTypeId") or "")
                    if self.request_type_ids and rt_id not in self.request_type_ids:
                        continue
                    parsed = self._parse_raw_request(raw)
                    if start > 0 and parsed.updated_epoch and parsed.updated_epoch < int(start):
                        continue
                    if end is not None and parsed.updated_epoch and parsed.updated_epoch > int(end):
                        continue
                    batch_docs.append(jsm_request_to_document(parsed, self.jira_base_url))

                if batch_docs:
                    yield batch_docs

                if page.get("isLastPage", True):
                    break
                start_idx += len(values)

    def retrieve_all_slim_documents(
        self,
        start: float = 0.0,
        end: float | None = None,
    ) -> Generator[list[SlimDocument], None, None]:
        for doc_batch in self.poll_source(start=start, end=end):
            yield [SlimDocument(id=d.id) for d in doc_batch]
