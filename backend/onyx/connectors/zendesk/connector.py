from collections.abc import Iterator
from typing import Any

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import ZENDESK_CONNECTOR_SKIP_ARTICLE_LABELS
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    time_str_to_utc,
)
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import Document
from onyx.connectors.models import Section
from onyx.connectors.models import SlimDocument
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.utils.retry_wrapper import retry_builder


MAX_PAGE_SIZE = 30  # Zendesk API maximum
_SLIM_BATCH_SIZE = 1000


class ZendeskCredentialsNotSetUpError(PermissionError):
    def __init__(self) -> None:
        super().__init__(
            "Zendesk Credentials are not set up, was load_credentials called?"
        )


class ZendeskClient:
    def __init__(self, subdomain: str, email: str, token: str):
        self.base_url = f"https://{subdomain}.zendesk.com/api/v2"
        self.auth = (f"{email}/token", token)

    @retry_builder()
    def make_request(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/{endpoint}", auth=self.auth, params=params
        )

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                # Sleep for the duration indicated by the Retry-After header
                time.sleep(int(retry_after))

        response.raise_for_status()
        return response.json()


def _get_content_tag_mapping(client: ZendeskClient) -> dict[str, str]:
    content_tags: dict[str, str] = {}
    params = {"page[size]": MAX_PAGE_SIZE}

    try:
        while True:
            data = client.make_request("guide/content_tags", params)

            for tag in data.get("records", []):
                content_tags[tag["id"]] = tag["name"]

            # Check if there are more pages
            if data.get("meta", {}).get("has_more", False):
                params["page[after]"] = data["meta"]["after_cursor"]
            else:
                break

        return content_tags
    except Exception as e:
        raise Exception(f"Error fetching content tags: {str(e)}")


def _get_articles(
    client: ZendeskClient, start_time: int | None = None, page_size: int = MAX_PAGE_SIZE
) -> Iterator[dict[str, Any]]:
    params = (
        {"start_time": start_time, "page[size]": page_size}
        if start_time
        else {"page[size]": page_size}
    )

    while True:
        data = client.make_request("help_center/articles", params)
        for article in data["articles"]:
            yield article

        if not data.get("meta", {}).get("has_more"):
            break
        params["page[after]"] = data["meta"]["after_cursor"]


def _get_tickets(
    client: ZendeskClient, start_time: int | None = None
) -> Iterator[dict[str, Any]]:
    params = {"start_time": start_time} if start_time else {"start_time": 0}

    while True:
        data = client.make_request("incremental/tickets.json", params)
        for ticket in data["tickets"]:
            yield ticket

        if not data.get("end_of_stream", False):
            params["start_time"] = data["end_time"]
        else:
            break


def _fetch_author(client: ZendeskClient, author_id: str) -> BasicExpertInfo | None:
    # Skip fetching if author_id is invalid
    if not author_id or author_id == "-1":
        return None

    try:
        author_data = client.make_request(f"users/{author_id}", {})
        user = author_data.get("user")
        return (
            BasicExpertInfo(display_name=user.get("name"), email=user.get("email"))
            if user and user.get("name") and user.get("email")
            else None
        )
    except requests.exceptions.HTTPError:
        # Handle any API errors gracefully
        return None


def _article_to_document(
    article: dict[str, Any],
    content_tags: dict[str, str],
    author_map: dict[str, BasicExpertInfo],
    client: ZendeskClient,
) -> tuple[dict[str, BasicExpertInfo] | None, Document]:
    author_id = article.get("author_id")
    if not author_id:
        author = None
    else:
        author = (
            author_map.get(author_id)
            if author_id in author_map
            else _fetch_author(client, author_id)
        )

    new_author_mapping = {author_id: author} if author_id and author else None

    updated_at = article.get("updated_at")
    update_time = time_str_to_utc(updated_at) if updated_at else None

    # Build metadata
    metadata: dict[str, str | list[str]] = {
        "labels": [str(label) for label in article.get("label_names", []) if label],
        "content_tags": [
            content_tags[tag_id]
            for tag_id in article.get("content_tag_ids", [])
            if tag_id in content_tags
        ],
    }

    # Remove empty values
    metadata = {k: v for k, v in metadata.items() if v}

    return new_author_mapping, Document(
        id=f"article:{article['id']}",
        sections=[
            Section(
                link=article.get("html_url"),
                text=parse_html_page_basic(article["body"]),
            )
        ],
        source=DocumentSource.ZENDESK,
        semantic_identifier=article["title"],
        doc_updated_at=update_time,
        primary_owners=[author] if author else None,
        metadata=metadata,
    )


def _get_comment_text(
    comment: dict[str, Any],
    author_map: dict[str, BasicExpertInfo],
    client: ZendeskClient,
) -> tuple[dict[str, BasicExpertInfo] | None, str]:
    author_id = comment.get("author_id")
    if not author_id:
        author = None
    else:
        author = (
            author_map.get(author_id)
            if author_id in author_map
            else _fetch_author(client, author_id)
        )

    new_author_mapping = {author_id: author} if author_id and author else None

    comment_text = f"Comment{' by ' + author.display_name if author and author.display_name else ''}"
    comment_text += f"{' at ' + comment['created_at'] if comment.get('created_at') else ''}:\n{comment['body']}"

    return new_author_mapping, comment_text


def _ticket_to_document(
    ticket: dict[str, Any],
    author_map: dict[str, BasicExpertInfo],
    client: ZendeskClient,
    default_subdomain: str,
) -> tuple[dict[str, BasicExpertInfo] | None, Document]:
    submitter_id = ticket.get("submitter")
    if not submitter_id:
        submitter = None
    else:
        submitter = (
            author_map.get(submitter_id)
            if submitter_id in author_map
            else _fetch_author(client, submitter_id)
        )

    new_author_mapping = (
        {submitter_id: submitter} if submitter_id and submitter else None
    )

    updated_at = ticket.get("updated_at")
    update_time = time_str_to_utc(updated_at) if updated_at else None

    metadata: dict[str, str | list[str]] = {}
    if status := ticket.get("status"):
        metadata["status"] = status
    if priority := ticket.get("priority"):
        metadata["priority"] = priority
    if tags := ticket.get("tags"):
        metadata["tags"] = tags
    if ticket_type := ticket.get("type"):
        metadata["ticket_type"] = ticket_type

    # Fetch comments for the ticket
    comments_data = client.make_request(f"tickets/{ticket.get('id')}/comments", {})
    comments = comments_data.get("comments", [])

    comment_texts = []
    for comment in comments:
        new_author_mapping, comment_text = _get_comment_text(
            comment, author_map, client
        )
        if new_author_mapping:
            author_map.update(new_author_mapping)
        comment_texts.append(comment_text)

    comments_text = "\n\n".join(comment_texts)

    subject = ticket.get("subject")
    full_text = f"Ticket Subject:\n{subject}\n\nComments:\n{comments_text}"

    ticket_url = ticket.get("url")
    subdomain = (
        ticket_url.split("//")[1].split(".zendesk.com")[0]
        if ticket_url
        else default_subdomain
    )

    ticket_display_url = (
        f"https://{subdomain}.zendesk.com/agent/tickets/{ticket.get('id')}"
    )

    return new_author_mapping, Document(
        id=f"zendesk_ticket_{ticket['id']}",
        sections=[Section(link=ticket_display_url, text=full_text)],
        source=DocumentSource.ZENDESK,
        semantic_identifier=f"Ticket #{ticket['id']}: {subject or 'No Subject'}",
        doc_updated_at=update_time,
        primary_owners=[submitter] if submitter else None,
        metadata=metadata,
    )


class ZendeskConnector(LoadConnector, PollConnector, SlimConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        content_type: str = "articles",
    ) -> None:
        self.batch_size = batch_size
        self.content_type = content_type
        self.subdomain = ""
        # Fetch all tags ahead of time
        self.content_tags: dict[str, str] = {}

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        # Subdomain is actually the whole URL
        subdomain = (
            credentials["zendesk_subdomain"]
            .replace("https://", "")
            .split(".zendesk.com")[0]
        )
        self.subdomain = subdomain

        self.client = ZendeskClient(
            subdomain, credentials["zendesk_email"], credentials["zendesk_token"]
        )
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self.poll_source(None, None)

    def poll_source(
        self, start: SecondsSinceUnixEpoch | None, end: SecondsSinceUnixEpoch | None
    ) -> GenerateDocumentsOutput:
        if self.client is None:
            raise ZendeskCredentialsNotSetUpError()

        self.content_tags = _get_content_tag_mapping(self.client)

        if self.content_type == "articles":
            yield from self._poll_articles(start)
        elif self.content_type == "tickets":
            yield from self._poll_tickets(start)
        else:
            raise ValueError(f"Unsupported content_type: {self.content_type}")

    def _poll_articles(
        self, start: SecondsSinceUnixEpoch | None
    ) -> GenerateDocumentsOutput:
        articles = _get_articles(self.client, start_time=int(start) if start else None)

        # This one is built on the fly as there may be more many more authors than tags
        author_map: dict[str, BasicExpertInfo] = {}

        doc_batch = []
        for article in articles:
            if (
                article.get("body") is None
                or article.get("draft")
                or any(
                    label in ZENDESK_CONNECTOR_SKIP_ARTICLE_LABELS
                    for label in article.get("label_names", [])
                )
            ):
                continue

            new_author_map, documents = _article_to_document(
                article, self.content_tags, author_map, self.client
            )
            if new_author_map:
                author_map.update(new_author_map)

            doc_batch.append(documents)
            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch.clear()

        if doc_batch:
            yield doc_batch

    def _poll_tickets(
        self, start: SecondsSinceUnixEpoch | None
    ) -> GenerateDocumentsOutput:
        if self.client is None:
            raise ZendeskCredentialsNotSetUpError()

        author_map: dict[str, BasicExpertInfo] = {}

        ticket_generator = _get_tickets(
            self.client, start_time=int(start) if start else None
        )

        while True:
            doc_batch = []
            for _ in range(self.batch_size):
                try:
                    ticket = next(ticket_generator)

                    # Check if the ticket status is deleted and skip it if so
                    if ticket.get("status") == "deleted":
                        continue

                    new_author_map, documents = _ticket_to_document(
                        ticket=ticket,
                        author_map=author_map,
                        client=self.client,
                        default_subdomain=self.subdomain,
                    )

                    if new_author_map:
                        author_map.update(new_author_map)

                    doc_batch.append(documents)

                    if len(doc_batch) >= self.batch_size:
                        yield doc_batch
                        doc_batch.clear()

                except StopIteration:
                    # No more tickets to process
                    if doc_batch:
                        yield doc_batch
                    return

            if doc_batch:
                yield doc_batch

    def retrieve_all_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateSlimDocumentOutput:
        slim_doc_batch: list[SlimDocument] = []
        if self.content_type == "articles":
            articles = _get_articles(
                self.client, start_time=int(start) if start else None
            )
            for article in articles:
                slim_doc_batch.append(
                    SlimDocument(
                        id=f"article:{article['id']}",
                    )
                )
                if len(slim_doc_batch) >= _SLIM_BATCH_SIZE:
                    yield slim_doc_batch
                    slim_doc_batch = []
        elif self.content_type == "tickets":
            tickets = _get_tickets(
                self.client, start_time=int(start) if start else None
            )
            for ticket in tickets:
                slim_doc_batch.append(
                    SlimDocument(
                        id=f"zendesk_ticket_{ticket['id']}",
                    )
                )
                if len(slim_doc_batch) >= _SLIM_BATCH_SIZE:
                    yield slim_doc_batch
                    slim_doc_batch = []
        else:
            raise ValueError(f"Unsupported content_type: {self.content_type}")
        if slim_doc_batch:
            yield slim_doc_batch


if __name__ == "__main__":
    import os
    import time

    connector = ZendeskConnector()
    connector.load_credentials(
        {
            "zendesk_subdomain": os.environ["ZENDESK_SUBDOMAIN"],
            "zendesk_email": os.environ["ZENDESK_EMAIL"],
            "zendesk_token": os.environ["ZENDESK_TOKEN"],
        }
    )

    current = time.time()
    one_day_ago = current - 24 * 60 * 60  # 1 day
    document_batches = connector.poll_source(one_day_ago, current)

    print(next(document_batches))
