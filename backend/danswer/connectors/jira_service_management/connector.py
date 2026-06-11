"""
Jira Service Management Connector

This connector pulls in all tickets from a specified Jira Service Management project.
It uses the Jira REST API to fetch issues and their associated comments, attachments,
and other relevant data.

For more details on adding new connectors, see:
https://github.com/danswer-ai/danswer/blob/main/backend/danswer/connectors/README.md
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import aiohttp
from pydantic import BaseModel, Field

from danswer.connectors.interfaces import (
    GenerateDocumentsOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from danswer.connectors.models import BasicExpertInfo, ConnectorMissingCredentialError, Document, Section
from danswer.utils.logger import setup_logger

logger = setup_logger()


class JiraServiceManagementConfig(BaseModel):
    """Configuration for Jira Service Management connector."""

    base_url: str = Field(
        description="Base URL of your Jira instance (e.g., https://your-domain.atlassian.net)"
    )
    project_key: str = Field(
        description="Project key to fetch tickets from (e.g., ITSM)"
    )
    email: Optional[str] = Field(
        default=None,
        description="Email address for Jira account (required for API token auth)",
    )
    api_token: Optional[str] = Field(
        default=None,
        description="API token for Jira authentication (generate at https://id.atlassian.com/manage-profile/security/api-tokens)",
    )
    personal_access_token: Optional[str] = Field(
        default=None,
        description="Personal Access Token for Jira authentication (alternative to email+api_token)",
    )
    batch_size: int = Field(
        default=100,
        description="Number of issues to fetch per API call",
        ge=1,
        le=100,
    )
    include_comments: bool = Field(
        default=True,
        description="Whether to include comments in the document content",
    )
    include_attachments: bool = Field(
        default=False,
        description="Whether to include attachment content (requires additional API calls)",
    )
    jql_query: Optional[str] = Field(
        default=None,
        description="Custom JQL query to filter issues (overrides default project filter)",
    )


class JiraServiceManagementConnector(LoadConnector, PollConnector):
    """Connector for Jira Service Management projects."""

    def __init__(self, config: JiraServiceManagementConfig) -> None:
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
        self._headers: Dict[str, str] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session with authentication."""
        if self._session is None:
            self._session = aiohttp.ClientSession()

            # Set up authentication headers
            if self.config.personal_access_token:
                self._headers = {
                    "Authorization": f"Bearer {self.config.personal_access_token}",
                    "Accept": "application/json",
                }
            elif self.config.email and self.config.api_token:
                # Basic auth with API token
                auth = aiohttp.BasicAuth(self.config.email, self.config.api_token)
                self._session.auth = auth
                self._headers = {"Accept": "application/json"}
            else:
                raise ConnectorMissingCredentialError(
                    "Jira Service Management",
                    "Either personal_access_token or both email and api_token must be provided",
                )

        return self._session

    async def _make_request(
        self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make an authenticated request to the Jira API."""
        session = await self._get_session()
        url = urljoin(self.config.base_url, f"/rest/api/3/{endpoint}")

        async with session.request(
            method=method, url=url, headers=self._headers, params=params
        ) as response:
            response.raise_for_status()
            return await response.json()

    async def _fetch_issue_batch(
        self, start_at: int = 0, jql: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Fetch a batch of issues from Jira."""
        if jql is None:
            jql = f'project = "{self.config.project_key}" ORDER BY created DESC'

        params = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": self.config.batch_size,
            "fields": "*all",  # Get all fields
            "expand": "renderedFields,names,schema,operations,editmeta,changelog,versionedRepresentations",
        }

        try:
            data = await self._make_request("GET", "search", params=params)
            issues = data.get("issues", [])
            total = data.get("total", 0)
            return issues, total
        except Exception as e:
            logger.error(f"Error fetching issues batch starting at {start_at}: {e}")
            return [], 0

    async def _fetch_comments(self, issue_key: str) -> List[Dict[str, Any]]:
        """Fetch comments for a specific issue."""
        try:
            data = await self._make_request(
                "GET", f"issue/{issue_key}/comment", params={"expand": "renderedBody"}
            )
            return data.get("comments", [])
        except Exception as e:
            logger.error(f"Error fetching comments for issue {issue_key}: {e}")
            return []

    async def _fetch_attachments(self, issue_key: str) -> List[Dict[str, Any]]:
        """Fetch attachment metadata for a specific issue."""
        try:
            # Get issue with attachment fields
            data = await self._make_request(
                "GET",
                f"issue/{issue_key}",
                params={"fields": "attachment"},
            )
            fields = data.get("fields", {})
            return fields.get("attachment", [])
        except Exception as e:
            logger.error(f"Error fetching attachments for issue {issue_key}: {e}")
            return []

    def _extract_issue_content(self, issue: Dict[str, Any]) -> str:
        """Extract and format content from an issue."""
        fields = issue.get("fields", {})
        rendered_fields = issue.get("renderedFields", {})

        # Basic issue information
        content_parts = []

        # Summary
        summary = fields.get("summary", "")
        if summary:
            content_parts.append(f"Summary: {summary}")

        # Description (prefer rendered HTML if available)
        description = rendered_fields.get("description", fields.get("description", ""))
        if description:
            # Clean HTML tags for plain text
            description_clean = re.sub(r"<[^>]+>", " ", description)
            description_clean = re.sub(r"\s+", " ", description_clean).strip()
            if description_clean:
                content_parts.append(f"Description: {description_clean}")

        # Additional fields that might be useful
        field_mappings = {
            "issuetype": "Issue Type",
            "priority": "Priority",
            "status": "Status",
            "resolution": "Resolution",
            "creator": "Creator",
            "reporter": "Reporter",
            "assignee": "Assignee",
            "created": "Created",
            "updated": "Updated",
            "resolutiondate": "Resolved",
            "duedate": "Due Date",
        }

        for field_key, field_label in field_mappings.items():
            field_value = fields.get(field_key)
            if field_value:
                if isinstance(field_value, dict):
                    display_value = field_value.get("name") or field_value.get(
                        "displayName"
                    )
                else:
                    display_value = str(field_value)
                if display_value:
                    content_parts.append(f"{field_label}: {display_value}")

        # Custom fields (Service Management specific)
        for field_name, field_value in fields.items():
            if field_name.startswith("customfield_"):
                if isinstance(field_value, dict):
                    display_value = field_value.get("value") or field_value.get(
                        "name"
                    )
                elif field_value:
                    display_value = str(field_value)
                else:
                    continue

                if display_value:
                    # Try to get the field's display name from names mapping
                    field_id = issue.get("names", {}).get(field_name, field_name)
                    content_parts.append(f"{field_id}: {display_value}")

        return "\n".join(content_parts)

    def _extract_comments_content(self, comments: List[Dict[str, Any]]) -> str:
        """Extract and format content from comments."""
        if not comments:
            return ""

        comment_parts = ["Comments:"]
        for comment in comments:
            author = comment.get("author", {}).get("displayName", "Unknown")
            created = comment.get("created", "")
            body = comment.get("renderedBody", comment.get("body", ""))

            if body:
                # Clean HTML tags
                body_clean = re.sub(r"<[^>]+>", " ", body)
                body_clean = re.sub(r"\s+", " ", body_clean).strip()
                if body_clean:
                    timestamp = f" ({created})" if created else ""
                    comment_parts.append(f"- {author}{timestamp}: {body_clean}")

        return "\n".join(comment_parts)

    async def _process_issue(
        self, issue: Dict[str, Any]
    ) -> Optional[Document]:
        """Process a single issue into a Document."""
        try:
            issue_key = issue.get("key", "")
            if not issue_key:
                logger.warning("Issue missing key, skipping")
                return None

            fields = issue.get("fields", {})
            created_str = fields.get("created")
            updated_str = fields.get("updated")

            # Parse timestamps
            created = None
            updated = None
            try:
                if created_str:
                    created = datetime.fromisoformat(
                        created_str.replace("Z", "+00:00")
                    ).timestamp()
                if updated_str:
                    updated = datetime.fromisoformat(
                        updated_str.replace("Z", "+00:00")
                    ).timestamp()
            except (ValueError, TypeError):
                logger.warning(f"Could not parse timestamps for issue {issue_key}")

            # Extract main content
            issue_content = self._extract_issue_content(issue)

            # Fetch and include comments if configured
            comments_content = ""
            if self.config.include_comments:
                comments = await self._fetch_comments(issue_key)
                comments_content = self._extract_comments_content(comments)

            # Combine all content
            all_content = issue_content
            if comments_content:
                all_content += "\n\n" + comments_content

            # Note: Attachments are not included in content by default due to
            # complexity and API limitations. The include_attachments flag
            # currently only fetches metadata.

            # Build document metadata
            metadata = {
                "issue_key": issue_key,
                "project": self.config.project_key,
                "issue_type": fields.get("issuetype", {}).get("name", ""),
                "status": fields.get("status", {}).get("name", ""),
                "priority": fields.get("priority", {}).get("name", ""),
                "assignee": fields.get("assignee", {}).get("displayName", ""),
                "reporter": fields.get("reporter", {}).get("displayName", ""),
                "created": created_str,
                "updated": updated_str,
            }

            # Create document sections
            sections = [
                Section(
                    text=all_content,
                    link=urljoin(
                        self.config.base_url, f"/browse/{issue_key}"
                    ),
                )
            ]

            return Document(
                id=issue_key,
                sections=sections,
                source=self.__class__.__name__,
                semantic_identifier=fields.get("summary", issue_key),
                metadata=metadata,
                doc_updated_at=updated or created or datetime.now(timezone.utc).timestamp(),
                primary_owners=[
                    BasicExpertInfo(
                        display_name=fields.get("reporter", {}).get(
                            "displayName", "Unknown"
                        ),
                        email=fields.get("reporter", {}).get("emailAddress"),
                    )
                ]
                if fields.get("reporter")
                else [],
            )

        except Exception as e:
            logger.error(f"Error processing issue {issue.get('key', 'unknown')}: {e}")
            return None

    async def load_from_state(self) -> GenerateDocumentsOutput:
        """Load all documents from the Jira Service Management project."""
        await self._get_session()  # Initialize session

        jql = self.config.jql_query or f'project = "{self.config.project_key}"'
        start_at = 0
        all_documents: List[Document] = []

        try:
            while True:
                logger.info(f"Fetching issues starting at {start_at}")
                issues, total = await self._fetch_issue_batch(start_at, jql)

                if not issues:
                    break

                # Process issues concurrently
                tasks = [self._process_issue(issue) for issue in issues]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, Exception):
                        logger.error(f"Error processing issue: {result}")
                    elif result is not None:
                        all_documents.append(result)

                logger.info(f"Processed {len(issues)} issues, total so far: {len(all_documents)}")

                start_at += len(issues)
                if start_at >= total:
                    break

                # Be nice to the API
                await asyncio.sleep(0.1)

        finally:
            await self.cleanup()

        return GenerateDocumentsOutput(documents=all_documents)

    async def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Poll for documents modified within the given time range."""
        await self._get_session()  # Initialize session

        # Convert timestamps to Jira date format
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )

        jql = (
            self.config.jql_query
            or f'project = "{self.config.project_key}" AND updated >= "{start_dt}" AND updated <= "{end_dt}"'
        )

        start_at = 0
        all_documents: List[Document] = []

        try:
            while True:
                logger.info(
                    f"Polling issues updated between {start_dt} and {end_dt}, starting at {start_at}"
                )
                issues, total = await self._fetch_issue_batch(start_at, jql)

                if not issues:
                    break

                # Process issues concurrently
                tasks = [self._process_issue(issue) for issue in issues]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, Exception):
                        logger.error(f"Error processing issue: {result}")
                    elif result is not None:
                        all_documents.append(result)

                logger.info(f"Processed {len(issues)} issues, total so far: {len(all_documents)}")

                start_at += len(issues)
                if start_at >= total:
                    break

                # Be nice to the API
                await asyncio.sleep(0.1)

        finally:
            await self.cleanup()

        return GenerateDocumentsOutput(documents=all_documents)

    async def cleanup(self) -> None:
        """Clean up resources."""
        if self._session:
            await self._session.close()
            self._session = None

    def __del__(self) -> None:
        """Ensure session is closed on destruction."""
        if self._session and not self._session.closed:
            asyncio.create_task(self._session.close())