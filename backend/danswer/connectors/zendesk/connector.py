from typing import Any

from zenpy import Zenpy  # type: ignore
from zenpy.lib.api_objects.help_centre_objects import Article  # type: ignore

from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.constants import DocumentSource
from danswer.connectors.cross_connector_utils.miscellaneous_utils import (
    time_str_to_utc,
)
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import SecondsSinceUnixEpoch
from danswer.connectors.models import BasicExpertInfo
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.file_processing.html_utils import parse_html_page_basic


def _article_to_document(article: Article) -> Document:
    author = BasicExpertInfo(
        display_name=article.author.name, email=article.author.email
    )
    update_time = time_str_to_utc(article.updated_at)
    labels = [str(label) for label in article.label_names]

    return Document(
        id=f"article:{article.id}",
        sections=[
            Section(link=article.html_url, text=parse_html_page_basic(article.body))
        ],
        source=DocumentSource.ZENDESK,
        semantic_identifier=article.title,
        doc_updated_at=update_time,
        primary_owners=[author],
        metadata={"labels": labels} if labels else {},
    )


class ZendeskClientNotSetUpError(PermissionError):
    def __init__(self) -> None:
        super().__init__("Zendesk Client is not set up, was load_credentials called?")


class ZendeskConnector(LoadConnector, PollConnector):
    def __init__(self, batch_size: int = INDEX_BATCH_SIZE) -> None:
        self.batch_size = batch_size
        self.zendesk_client: Zenpy | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        # Subdomain is actually the whole URL
        subdomain = (
            credentials["zendesk_subdomain"]
            .replace("https://", "")
            .split(".zendesk.com")[0]
        )

        self.zendesk_client = Zenpy(
            subdomain=subdomain,
            email=credentials["zendesk_email"],
            token=credentials["zendesk_token"],
        )
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self.poll_source(None, None)

    def poll_source(
        self, start: SecondsSinceUnixEpoch | None, end: SecondsSinceUnixEpoch | None
    ) -> GenerateDocumentsOutput:
        if self.zendesk_client is None:
            raise ZendeskClientNotSetUpError()

        articles = (
            self.zendesk_client.help_center.articles(cursor_pagination=True)
            if start is None
            else self.zendesk_client.help_center.articles.incremental(
                start_time=int(start)
            )
        )
        doc_batch = []
        for article in articles:
            if article.body is None or article.draft:
                continue

            doc_batch.append(_article_to_document(article))
            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch.clear()

        if doc_batch:
            yield doc_batch
