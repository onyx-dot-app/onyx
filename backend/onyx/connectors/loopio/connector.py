import json
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any

from oauthlib.oauth2 import BackendApplicationClient
from requests_oauthlib import OAuth2Session  # type: ignore

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.file_processing.html_utils import strip_excessive_newlines_and_spaces
from onyx.utils.logger import setup_logger

LOOPIO_API_BASE = "https://api.loopio.com/"
LOOPIO_AUTH_URL = LOOPIO_API_BASE + "oauth2/access_token"
LOOPIO_DATA_URL = LOOPIO_API_BASE + "data/"

logger = setup_logger()


class LoopioConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        loopio_stack_name: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.batch_size = batch_size
        self.loopio_client_id: str | None = None
        self.loopio_client_token: str | None = None
        self.loopio_stack_name = loopio_stack_name

    def _fetch_data(
        self, resource: str, params: dict[str, str | int]
    ) -> Generator[dict[str, Any], None, None]:
        client = BackendApplicationClient(
            client_id=self.loopio_client_id, scope=["library:read"]
        )
        session = OAuth2Session(client=client)
        session.fetch_token(
            token_url=LOOPIO_AUTH_URL,
            client_id=self.loopio_client_id,
            client_secret=self.loopio_client_token,
        )
        page = 0
        stop_at_page = 1
        while (page := page + 1) <= stop_at_page:
            params["page"] = page
            response = session.request(
                "GET",
                LOOPIO_DATA_URL + resource,
                headers={"Accept": "application/json"},
                params=params,
            )
            if response.status_code == 400:
                logger.error(
                    f"Loopio API returned 400 for {resource} with params {params}",
                )
                logger.error(response.text)
            response.raise_for_status()
            response_data = json.loads(response.text)
            stop_at_page = response_data.get("totalPages", 1)
            yield response_data

    def _build_search_filter(
        self, stack_name: str | None, start: str | None, end: str | None
    ) -> dict[str, Any]:
        filter: dict[str, Any] = {}
        if start is not None and end is not None:
            filter["lastUpdatedDate"] = {"gte": start, "lt": end}

        if stack_name is not None:
            # Right now this is fetching the stacks every time, which is not ideal.
            # We should update this later to store the ID when we create the Connector
            for stack in self._fetch_data(resource="v2/stacks", params={}):
                for item in stack["items"]:
                    if item["name"] == stack_name:
                        filter["locations"] = [{"stackID": item["id"]}]
                        break
            if "locations" not in filter:
                raise ValueError(f"Stack {stack_name} not found in Loopio")
        return filter

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.loopio_subdomain = credentials["loopio_subdomain"]
        self.loopio_client_id = credentials["loopio_client_id"]
        self.loopio_client_token = credentials["loopio_client_token"]
        return None

    def _process_entries(
        self, start: str | None = None, end: str | None = None
    ) -> GenerateDocumentsOutput:
        if self.loopio_client_id is None or self.loopio_client_token is None:
            raise ConnectorMissingCredentialError("Loopio")

        filter = self._build_search_filter(
            stack_name=self.loopio_stack_name, start=start, end=end
        )
        params: dict[str, str | int] = {"pageSize": self.batch_size}
        params["filter"] = json.dumps(filter)

        doc_batch: list[Document] = []
        for library_entries in self._fetch_data(
            resource="v2/libraryEntries", params=params
        ):
            for entry in library_entries.get("items", []):
                link = f"https://{self.loopio_subdomain}.loopio.com/library?entry={entry['id']}"
                topic = "/".join(
                    part["name"] for part in entry["location"].values() if part
                )

                answer_text = entry.get("answer", {}).get("text", "")
                if not answer_text:
                    logger.warning(
                        f"The Library entry {entry['id']} has no answer text. Skipping."
                    )
                    continue

                try:
                    answer = parse_html_page_basic(answer_text)
                except Exception as e:
                    logger.error(f"Error parsing HTML for entry {entry['id']}: {e}")
                    continue

                questions = [
                    question.get("text").replace("\xa0", " ")
                    for question in entry["questions"]
                    if question.get("text")
                ]
                questions_string = strip_excessive_newlines_and_spaces(
                    "\n".join(questions)
                )
                content_text = f"{answer}\n\nRelated Questions: {questions_string}"
                content_text = strip_excessive_newlines_and_spaces(
                    content_text.replace("\xa0", " ")
                )

                last_updated = time_str_to_utc(entry["lastUpdatedDate"])
                last_reviewed = (
                    time_str_to_utc(entry["lastReviewedDate"])
                    if entry.get("lastReviewedDate")
                    else None
                )

                # For Onyx, we decay document score overtime, either last_updated or
                # last_reviewed is a good enough signal for the document's recency
                latest_time = (
                    max(last_reviewed, last_updated) if last_reviewed else last_updated
                )
                creator = entry.get("creator")
                last_updated_by = entry.get("lastUpdatedBy")
                last_reviewed_by = entry.get("lastReviewedBy")

                primary_owners: list[BasicExpertInfo] = [
                    BasicExpertInfo(display_name=owner.get("name"))
                    for owner in [creator, last_updated_by]
                    if owner is not None
                ]
                secondary_owners: list[BasicExpertInfo] = [
                    BasicExpertInfo(display_name=owner.get("name"))
                    for owner in [last_reviewed_by]
                    if owner is not None
                ]
                doc_batch.append(
                    Document(
                        id=str(entry["id"]),
                        sections=[TextSection(link=link, text=content_text)],
                        source=DocumentSource.LOOPIO,
                        semantic_identifier=questions[0],
                        doc_updated_at=latest_time,
                        primary_owners=primary_owners,
                        secondary_owners=secondary_owners,
                        metadata={
                            "topic": topic,
                            "questions": "\n".join(questions),
                            "creator": creator.get("name") if creator else "",
                        },
                    )
                )

            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []
        if len(doc_batch) > 0:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._process_entries()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_time = datetime.fromtimestamp(start, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
        end_time = datetime.fromtimestamp(end, tz=timezone.utc).isoformat(
            timespec="seconds"
        )

        return self._process_entries(start_time, end_time)


if __name__ == "__main__":
    import os

    connector = LoopioConnector(
        loopio_stack_name=os.environ.get("LOOPIO_STACK_NAME", None)
    )
    connector.load_credentials(
        {
            "loopio_client_id": os.environ["LOOPIO_CLIENT_ID"],
            "loopio_client_token": os.environ["LOOPIO_CLIENT_TOKEN"],
            "loopio_subdomain": os.environ["LOOPIO_SUBDOMAIN"],
        }
    )

    latest_docs = connector.load_from_state()
    print(next(latest_docs))
