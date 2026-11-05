from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
import json
import logging
from typing import Any
import requests
from requests.auth import HTTPBasicAuth

from onyx.connectors.jira_service_management.utils import get_text_adf

logger = logging.getLogger(__name__)

@dataclass
class JSMPerson:
    name: str
    email: str

@dataclass
class JSMIssue:
    id: str
    key: str
    url: str
    summary: str
    description: str
    comments: list[str]
    created_by: JSMPerson
    assigned_to: JSMPerson | None
    last_modified_time: datetime
    labels: list[str]
    priority: str
    status: str

class JiraServiceManagementAPI:
    def __init__(
        self,
        base_url: str,
        user_email: str,
        api_token: str,
        labels_to_skip: list[str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(user_email, api_token)
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self.labels_to_skip = set(labels_to_skip or [])

    def get_issues(
        self,
        project_key: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        batch_size: int = 50,
    ) -> Iterator[list[JSMIssue]]:
        jql_clauses = []
        if project_key:
            jql_clauses.append(f"project = '{project_key}'")
        if start_time:
            jql_clauses.append(f"updated >= '{start_time.strftime('%Y-%m-%d %H:%M')}'")
        if end_time:
            jql_clauses.append(f"updated <= '{end_time.strftime('%Y-%m-%d %H:%M')}'")

        jql = " AND ".join(jql_clauses) if jql_clauses else "ORDER BY updated ASC"
        if jql_clauses:
            jql += " ORDER BY updated ASC"

        start_at = 0
        while True:
            endpoint = f"{self.base_url}/rest/api/3/search/jql"
            params = {
                "jql": jql,
                "startAt": start_at,
                "maxResults": batch_size,
                "fields": [
                    "summary",
                    "description",
                    "comment",
                    "creator",
                    "assignee",
                    "updated",
                    "labels",
                    "priority",
                    "status",
                ],
            }
            try:
                resp = self.session.get(endpoint, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                issues_raw = data.get("issues", [])
                if not issues_raw:
                    break

                batch: list[JSMIssue] = []
                for item in issues_raw:
                    fields = item.get("fields", {})
                    labels = fields.get("labels", [])
                    if any(l in self.labels_to_skip for l in labels):
                        continue

                    comments_data = fields.get("comment", {}).get("comments", [])
                    comment_texts = []
                    for c in comments_data:
                        body = c.get("body")
                        if isinstance(body, dict):
                            comment_texts.append(get_text_adf(body))
                        elif isinstance(body, str):
                            comment_texts.append(body)

                    desc_raw = fields.get("description")
                    desc = get_text_adf(desc_raw) if isinstance(desc_raw, dict) else (desc_raw or "")

                    creator = fields.get("creator") or {}
                    assignee = fields.get("assignee") or {}
                    updated_str = fields.get("updated")
                    updated_dt = (
                        datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                        if updated_str
                        else datetime.now()
                    )

                    issue = JSMIssue(
                        id=str(item.get("id")),
                        key=item.get("key", ""),
                        url=f"{self.base_url}/browse/{item.get('key')}",
                        summary=fields.get("summary", ""),
                        description=desc,
                        comments=comment_texts,
                        created_by=JSMPerson(
                            name=creator.get("displayName", "Unknown"),
                            email=creator.get("emailAddress", ""),
                        ),
                        assigned_to=JSMPerson(
                            name=assignee.get("displayName", "Unassigned"),
                            email=assignee.get("emailAddress", ""),
                        )
                        if assignee
                        else None,
                        last_modified_time=updated_dt,
                        labels=labels,
                        priority=fields.get("priority", {}).get("name", "Medium")
                        if isinstance(fields.get("priority"), dict)
                        else "Medium",
                        status=fields.get("status", {}).get("name", "Open")
                        if isinstance(fields.get("status"), dict)
                        else "Open",
                    )
                    batch.append(issue)

                if batch:
                    yield batch

                total = data.get("total", 0)
                start_at += len(issues_raw)
                if start_at >= total or len(issues_raw) < batch_size:
                    break
            except Exception as e:
                logger.error(f"Error fetching JSM issues: {e}")
                break
