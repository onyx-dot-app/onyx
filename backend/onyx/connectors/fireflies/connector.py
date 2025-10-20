from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import cast
from typing import List

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

_FIREFLIES_ID_PREFIX = "FIREFLIES_"

_FIREFLIES_API_URL = "https://api.fireflies.ai/graphql"

_FIREFLIES_TRANSCRIPT_QUERY_SIZE = 50  # Max page size is 50

_FIREFLIES_API_QUERY = """
    query Transcripts($fromDate: DateTime, $toDate: DateTime, $limit: Int!, $skip: Int!) {
        transcripts(fromDate: $fromDate, toDate: $toDate, limit: $limit, skip: $skip) {
            id
            title
            organizer_email
            participants
            date
            duration
            transcript_url
            sentences {
                text
                speaker_name
                start_time
            }
        }
    }
"""

ONE_MINUTE = 60


def _create_doc_from_transcript(transcript: dict) -> Document | None:
    sections: List[TextSection] = []
    current_speaker_name = None
    current_link = ""
    current_text = ""

    if transcript["sentences"] is None:
        return None

    for sentence in transcript["sentences"]:
        if sentence["speaker_name"] != current_speaker_name:
            if current_speaker_name is not None:
                sections.append(
                    TextSection(
                        link=current_link,
                        text=current_text.strip(),
                    )
                )
            current_speaker_name = sentence.get("speaker_name") or "Unknown Speaker"
            current_link = f"{transcript['transcript_url']}?t={sentence['start_time']}"
            current_text = f"{current_speaker_name}: "

        cleaned_text = sentence["text"].replace("\xa0", " ")
        current_text += f"{cleaned_text} "

    # Sometimes these links (links with a timestamp) do not work, it is a bug with Fireflies.
    sections.append(
        TextSection(
            link=current_link,
            text=current_text.strip(),
        )
    )

    fireflies_id = _FIREFLIES_ID_PREFIX + transcript["id"]

    meeting_title = transcript["title"] or "No Title"

    meeting_date_unix = transcript["date"]
    meeting_date = datetime.fromtimestamp(meeting_date_unix / 1000, tz=timezone.utc)

    meeting_organizer_email = transcript["organizer_email"]
    organizer_email_user_info = [BasicExpertInfo(email=meeting_organizer_email)]

    meeting_participants_email_list = []
    for participant in transcript.get("participants", []):
        if participant != meeting_organizer_email and participant:
            meeting_participants_email_list.append(BasicExpertInfo(email=participant))

    return Document(
        id=fireflies_id,
        sections=cast(list[TextSection | ImageSection], sections),
        source=DocumentSource.FIREFLIES,
        semantic_identifier=meeting_title,
        metadata={
            k: str(v)
            for k, v in {
                "meeting_date": meeting_date,
                "duration_min": transcript.get("duration"),
            }.items()
            if v is not None
        },
        doc_updated_at=meeting_date,
        primary_owners=organizer_email_user_info,
        secondary_owners=meeting_participants_email_list,
    )


# If not all transcripts are being indexed, try using a more-recently-generated
# API key.
class FirefliesConnector(PollConnector, LoadConnector):
    def __init__(self, batch_size: int = INDEX_BATCH_SIZE) -> None:
        self.batch_size = batch_size

    def load_credentials(self, credentials: dict[str, str]) -> None:
        api_key = credentials.get("fireflies_api_key")

        if not isinstance(api_key, str):
            raise ConnectorMissingCredentialError(
                "The Fireflies API key must be a string"
            )

        self.api_key = api_key

        return None

    def _fetch_transcripts(
        self, start_datetime: str | None = None, end_datetime: str | None = None
    ) -> Iterator[List[dict]]:
        if self.api_key is None:
            raise ConnectorMissingCredentialError("Missing API key")

        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.api_key,
        }

        skip = 0
        variables: dict[str, int | str] = {
            "limit": _FIREFLIES_TRANSCRIPT_QUERY_SIZE,
        }

        if start_datetime:
            variables["fromDate"] = start_datetime
        if end_datetime:
            variables["toDate"] = end_datetime

        while True:
            variables["skip"] = skip
            response = requests.post(
                _FIREFLIES_API_URL,
                headers=headers,
                json={"query": _FIREFLIES_API_QUERY, "variables": variables},
            )

            response.raise_for_status()

            if response.status_code == 204:
                break

            received_transcripts = response.json()
            parsed_transcripts = received_transcripts.get("data", {}).get(
                "transcripts", []
            )

            yield parsed_transcripts

            if len(parsed_transcripts) < _FIREFLIES_TRANSCRIPT_QUERY_SIZE:
                break

            skip += _FIREFLIES_TRANSCRIPT_QUERY_SIZE

    def _process_transcripts(
        self, start: str | None = None, end: str | None = None
    ) -> GenerateDocumentsOutput:
        doc_batch: List[Document] = []

        for transcript_batch in self._fetch_transcripts(start, end):
            for transcript in transcript_batch:
                if doc := _create_doc_from_transcript(transcript):
                    doc_batch.append(doc)

                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._process_transcripts()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        # add some leeway to account for any timezone funkiness and/or bad handling
        # of start time on the Fireflies side
        start = max(0, start - ONE_MINUTE)
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )

        yield from self._process_transcripts(start_datetime, end_datetime)
