import datetime
import requests
from typing import Any, Generator, Optional

from danswer.configs.constants import DocumentSource
from danswer.connectors.interface import BaseConnector
from danswer.connectors.models import Document, Section
from danswer.utils.logger import setup_logger

def _extract_adf_text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        text = ""
        if node.get("type") == "text":
            text += node.get("text", "")
        for child in node.get("content", []):
            child_text = _extract_adf_text(child)
            if child_text:
                text += child_text
        if node.get("type") in ("paragraph", "heading", "bulletList", "orderedList", "listItem", "codeBlock"):
            text += "\n"
        return text
    if isinstance(node, list):
        return "".join(_extract_adf_text(item) for item in node)
    return ""

logger = setup_logger()


class JiraServiceManagementConnector(BaseConnector):
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        project_key: str,
    ):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.api_token = api_token
        self.project_key = project_key
        self.auth = (self.email, self.api_token)

    def load_from_state(self, state: dict[str, Any]) -> None:
        pass

    def store_in_state(self) -> dict[str, Any]:
        return {}

    def poll_source(
        self, start: float, end: float
    ) -> Generator[list[Document], None, None]:
        return self.load(start=start)

    def load(self, start: Optional[float] = None) -> Generator[list[Document], None, None]:
        url = f"{self.base_url}/rest/api/3/search"
        headers = {"Accept": "application/json"}
        
        start_at = 0
        max_results = 50
        
        jql = f"project = '{self.project_key}'"
        if start is not None:
            start_dt = datetime.datetime.fromtimestamp(start, tz=datetime.timezone.utc)
            jql += f' AND updated >= "{start_dt.strftime("%Y/%m/%d %H:%M")}"'

        while True:
            params = {
                "jql": jql,
                "startAt": start_at,
                "maxResults": max_results,
                "expand": "renderedFields",
            }
            
            try:
                response = requests.get(
                    url, auth=self.auth, headers=headers, params=params
                )
                response.raise_for_status()
                data = response.json()
                issues = data.get("issues", [])
                if not issues:
                    break

                doc_batch: list[Document] = []
                for issue in issues:
                    issue_key = issue.get("key")
                    if not issue_key:
                        continue

                    fields = issue.get("fields", {})
                    summary = fields.get("summary", "")

                    description = ""
                    desc_field = fields.get("description")
                    if desc_field:
                        if isinstance(desc_field, dict):
                            description = _extract_adf_text(desc_field)
                        elif isinstance(desc_field, str):
                            description = desc_field

                    comment_obj = fields.get("comment", {})
                    comments_list = comment_obj.get("comments", []) if isinstance(comment_obj, dict) else []
                    comments_text = []
                    for c in comments_list:
                        c_body = c.get("body")
                        if c_body:
                            if isinstance(c_body, dict):
                                comments_text.append(_extract_adf_text(c_body))
                            elif isinstance(c_body, str):
                                comments_text.append(c_body)

                    content_parts = []
                    if summary:
                        content_parts.append(f"Summary: {summary}")
                    if description:
                        content_parts.append(f"Description:\n{description}")
                    if comments_text:
                        content_parts.append("Comments:\n" + "\n---\n".join(comments_text))

                    full_content = "\n\n".join(content_parts)

                    updated_str = fields.get("updated")
                    doc_updated_at = None
                    if updated_str:
                        try:
                            doc_updated_at = datetime.datetime.fromisoformat(
                                updated_str.replace("Z", "+00:00")
                            )
                        except ValueError:
                            doc_updated_at = None

                    doc = Document(
                        id=f"{self.base_url}/browse/{issue_key}",
                        source=DocumentSource.JIRA,
                        sections=[
                            Section(
                                link=f"{self.base_url}/browse/{issue_key}",
                                text=full_content,
                            )
                        ],
                        doc_metadata={
                            "issue_key": issue_key,
                            "summary": summary,
                            "project": self.project_key,
                        },
                        doc_updated_at=doc_updated_at,
                    )
                    doc_batch.append(doc)

                if doc_batch:
                    yield doc_batch

                start_at += len(issues)
                total = data.get("total", 0)
                if start_at >= total:
                    break
            except Exception as e:
                logger.error(f"Error fetching issues from Jira Service Management: {e}")
                break
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                logger.error(f"Failed to fetch Jira Service Management issues: {e}")
                break

            issues = data.get("issues", [])
            if not issues:
                break

            docs: list[Document] = []
            for issue in issues:
                fields = issue.get("fields", {})
                issue_key = issue.get("key", "")
                summary = fields.get("summary", "")
                description_raw = fields.get("description")

                description_text = _extract_adf_text(description_raw) if description_raw else ""
                full_text = f"{summary}\n\n{description_text}".strip()

                issue_url = f"{self.base_url}/browse/{issue_key}" if issue_key else self.base_url

                doc = Document(
                    id=issue_url,
                    source=DocumentSource.JIRA,
                    semantic_identifier=summary or issue_key,
                    sections=[Section(link=issue_url, text=full_text)],
                    metadata={
                        "key": issue_key,
                        "summary": summary,
                    },
                )
                docs.append(doc)

            if docs:
                yield docs

            total = data.get("total", 0)
            start_at += len(issues)
            if start_at >= total:
                break
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                logger.error(
                    f"Failed to fetch issues from Jira Service Management: {e}"
                )
                break

            issues = data.get("issues", [])
            if not issues:
                break

            documents = []
            for issue in issues:
                issue_key = issue.get("key", "")
                fields = issue.get("fields", {})
                summary = fields.get("summary", "")
                description_raw = fields.get("description")
                if isinstance(description_raw, str):
                    description = description_raw
                elif isinstance(description_raw, dict):
                    description = _extract_adf_text(description_raw)
                else:
                    description = ""

                sections = []
                if summary:
                    sections.append(
                        Section(
                            link=f"{self.base_url}/browse/{issue_key}",
                            text=f"Summary: {summary}",
                        )
                    )
                if description:
                    sections.append(
                        Section(
                            link=f"{self.base_url}/browse/{issue_key}",
                            text=f"Description:\n{description.strip()}",
                        )
                    )

                comment_data = fields.get("comment", {})
                comments = (
                    comment_data.get("comments", [])
                    if isinstance(comment_data, dict)
                    else []
                )
                for comment in comments:
                    author = comment.get("author", {}).get("displayName", "Unknown")
                    body_raw = comment.get("body")
                    if isinstance(body_raw, str):
                        body = body_raw
                    elif isinstance(body_raw, dict):
                        body = _extract_adf_text(body_raw)
                    else:
                        body = ""
                    if body:
                        sections.append(
                            Section(
                                link=f"{self.base_url}/browse/{issue_key}",
                                text=f"Comment by {author}:\n{body.strip()}",
                            )
                        )

                doc_id = f"{self.base_url}/browse/{issue_key}"

                try:
                    source_type = DocumentSource.JIRA_SERVICE_MANAGEMENT
                except AttributeError:
                    source_type = getattr(DocumentSource, "JIRA", "jira")

                doc = Document(
                    id=doc_id,
                    sections=sections
                    if sections
                    else [Section(link=doc_id, text=f"Issue {issue_key}")],
                    source=source_type,
                    semantic_identifier=f"{issue_key}: {summary}"
                    if summary
                    else issue_key,
                    metadata={
                        "issue_key": issue_key,
                        "project_key": self.project_key,
                        "status": fields.get("status", {}).get("name", ""),
                        "issue_type": fields.get("issuetype", {}).get("name", ""),
                    },
                )
                documents.append(doc)

            if documents:
                yield documents

            start_at += len(issues)
            total = data.get("total", 0)
            if start_at >= total:
                breakatus()
                data = response.json()
            except Exception as e:
                logger.error(f"Error fetching JSM issues: {e}")
                break

            issues = data.get("issues", [])
            if not issues:
                break

            docs: list[Document] = []
            for issue in issues:
                key = issue.get("key")
                fields = issue.get("fields", {})
                summary = fields.get("summary", "")
                description_raw = fields.get("description")
                description = _extract_adf_text(description_raw)

                web_url = f"{self.base_url}/browse/{key}"
                doc_id = web_url

                sections = [Section(link=web_url, text=f"Summary: {summary}\n\nDescription:\n{description}")]

                # Extract comments if available
                comment_data = fields.get("comment", {})
                comments = comment_data.get("comments", [])
                if comments:
                    comment_texts = []
                    for c in comments:
                        author = c.get("author", {}).get("displayName", "Unknown")
                        body = _extract_adf_text(c.get("body"))
                        comment_texts.append(f"{author}: {body}")
                    if comment_texts:
                        sections.append(Section(link=web_url, text="Comments:\n" + "\n".join(comment_texts)))

                docs.append(
                    Document(
                        id=doc_id,
                        source=DocumentSource.JIRA,
                        semantic_identifier=f"{key}: {summary}",
                        metadata={
                            "jira_key": key,
                            "project_key": self.project_key,
                        },
                        sections=sections,
                    )
                )

            if docs:
                yield docs

            total = data.get("total", 0)
            start_at += max_results
            if start_at >= total:
                breakatus()
                data = response.json()
            except Exception as e:
                logger.error(f"Error fetching tickets from JSM project '{self.project_key}': {e}")
                break

            issues = data.get("issues", [])
            if not issues:
                break

            documents = []
            for issue in issues:
                issue_key = issue.get("key")
                fields = issue.get("fields", {})
                summary = fields.get("summary", "")
                description_adf = fields.get("description")
                description_text = _extract_adf_text(description_adf) if description_adf else ""

                issue_url = f"{self.base_url}/browse/{issue_key}"
                
                text_content = f"Issue: {issue_key}\nSummary: {summary}\n"
                if description_text:
                    text_content += f"Description:\n{description_text}\n"

                comments = fields.get("comment", {}).get("comments", [])
                if comments:
                    text_content += "Comments:\n"
                    for comment in comments:
                        author = comment.get("author", {}).get("displayName", "Unknown")
                        body = _extract_adf_text(comment.get("body"))
                        if body:
                            text_content += f"- {author}: {body}\n"

                updated_str = fields.get("updated")
                updated_at = None
                if updated_str:
                    try:
                        updated_at = datetime.datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                    except ValueError:
                        pass

                doc = Document(
                    id=issue_url,
                    sections=[Section(link=issue_url, text=text_content.strip())],
                    source=DocumentSource.JIRA,
                    semantic_identifier=f"{issue_key}: {summary}",
                    metadata={
                        "project_key": self.project_key,
                        "issue_key": issue_key,
                        "status": fields.get("status", {}).get("name", ""),
                        "issue_type": fields.get("issuetype", {}).get("name", ""),
                    },
                    doc_updated_at=updated_at,
                )
                documents.append(doc)

            if documents:
                yield documents

            total = data.get("total", 0)
            start_at += len(issues)
            if start_at >= total or len(issues) < max_results:
                breakatus()
                data = response.json()
            except Exception as e:
                logger.exception(f"Failed to fetch Jira Service Management tickets: {e}")
                break

            issues = data.get("issues", [])
            if not issues:
                break

            doc_batch: list[Document] = []
            for issue in issues:
                issue_key = issue.get("key")
                if not issue_key:
                    continue
                
                fields = issue.get("fields", {})
                summary = fields.get("summary", "")
                description_raw = fields.get("description")
                description_text = _extract_adf_text(description_raw) if description_raw else ""
                
                comment_data = fields.get("comment", {})
                comments = comment_data.get("comments", []) if isinstance(comment_data, dict) else []
                comment_texts = []
                for comment in comments:
                    c_body = comment.get("body")
                    c_text = _extract_adf_text(c_body) if c_body else ""
                    if c_text.strip():
                        author = comment.get("author", {}).get("displayName", "Unknown") if isinstance(comment.get("author"), dict) else "Unknown"
                        comment_texts.append(f"{author}: {c_text.strip()}")
                
                full_text = f"Summary: {summary}\n\nDescription:\n{description_text.strip()}"
                if comment_texts:
                    full_text += "\n\nComments:\n" + "\n".join(comment_texts)

                issue_url = f"{self.base_url}/browse/{issue_key}"
                
                doc_updated_at = None
                updated_str = fields.get("updated")
                if updated_str:
                    try:
                        doc_updated_at = datetime.datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                    except Exception:
                        pass

                status_val = fields.get("status", {}).get("name", "") if isinstance(fields.get("status"), dict) else ""
                reporter_val = fields.get("reporter", {}).get("displayName", "") if isinstance(fields.get("reporter"), dict) else ""
                assignee_val = fields.get("assignee", {}).get("displayName", "") if isinstance(fields.get("assignee"), dict) else ""

                doc_batch.append(
                    Document(
                        id=issue_url,
                        source=DocumentSource.JIRA,
                        semantic_identifier=f"[{issue_key}] {summary}",
                        sections=[
                            Section(
                                link=issue_url,
                                text=full_text,
                            )
                        ],
                        metadata={
                            "project": self.project_key,
                            "issue_key": issue_key,
                            "status": status_val,
                            "reporter": reporter_val,
                            "assignee": assignee_val,
                        },
                        doc_updated_at=doc_updated_at,
                    )
                )

            if doc_batch:
                yield doc_batch

            total = data.get("total", 0)
            start_at += len(issues)
            if start_at >= total:
                break
