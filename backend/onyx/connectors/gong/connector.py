import base64
import copy
import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import cast

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from onyx.configs.app_configs import GONG_CONNECTOR_START_TIME
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


class GongConnectorCheckpoint(ConnectorCheckpoint):
    # Resolved workspace IDs to iterate through.
    # None means "not yet resolved" — first checkpoint call resolves them.
    # Inner None means "no workspace filter" (fetch all).
    workspace_ids: list[str | None] | None = None
    # Index into workspace_ids for current workspace
    workspace_index: int = 0
    # Gong API cursor for current workspace's transcript pagination
    cursor: str | None = None


class GongConnector(CheckpointedConnector[GongConnectorCheckpoint]):
    BASE_URL = "https://api.gong.io"
    MAX_CALL_DETAILS_ATTEMPTS = 6
    CALL_DETAILS_DELAY = 30  # in seconds
    # Gong API limit is 3 calls/sec — stay safely under it
    MIN_REQUEST_INTERVAL = 0.5  # seconds between requests

    def __init__(
        self,
        workspaces: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        hide_user_info: bool = False,
    ) -> None:
        self.workspaces = workspaces
        self.batch_size: int = batch_size
        self.auth_token_basic: str | None = None
        self.hide_user_info = hide_user_info
        self._last_request_time: float = 0.0

        # urllib3 Retry already respects the Retry-After header by default
        # (respect_retry_after_header=True), so on 429 it will sleep for the
        # duration Gong specifies before retrying.
        retry_strategy = Retry(
            total=10,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
        )

        session = requests.Session()
        session.mount(GongConnector.BASE_URL, HTTPAdapter(max_retries=retry_strategy))
        self._session = session

    @staticmethod
    def make_url(endpoint: str) -> str:
        url = f"{GongConnector.BASE_URL}{endpoint}"
        return url

    def _throttled_request(
        self, method: str, url: str, **kwargs: Any
    ) -> requests.Response:
        """Rate-limited request wrapper. Enforces MIN_REQUEST_INTERVAL between
        calls to stay under Gong's 3 calls/sec limit and avoid triggering 429s."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)

        response = self._session.request(method, url, **kwargs)
        self._last_request_time = time.monotonic()
        return response

    def _get_workspace_id_map(self) -> dict[str, str]:
        response = self._throttled_request(
            "GET", GongConnector.make_url("/v2/workspaces")
        )
        response.raise_for_status()

        workspaces_details = response.json().get("workspaces")
        name_id_map = {
            workspace["name"]: workspace["id"] for workspace in workspaces_details
        }
        id_id_map = {
            workspace["id"]: workspace["id"] for workspace in workspaces_details
        }
        # In very rare case, if a workspace is given a name which is the id of another workspace,
        # Then the user input is treated as the name
        return {**id_id_map, **name_id_map}

    def _fetch_transcript_page(
        self,
        start_datetime: str | None,
        end_datetime: str | None,
        workspace_id: str | None,
        cursor: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch one page of transcripts from the Gong API.

        Returns (transcripts, next_cursor). next_cursor is None when no more pages.
        """
        body: dict[str, Any] = {"filter": {}}
        if start_datetime:
            body["filter"]["fromDateTime"] = start_datetime
        if end_datetime:
            body["filter"]["toDateTime"] = end_datetime
        if workspace_id:
            body["filter"]["workspaceId"] = workspace_id
        if cursor:
            body["cursor"] = cursor

        response = self._throttled_request(
            "POST", GongConnector.make_url("/v2/calls/transcript"), json=body
        )
        # If no calls in the range, return empty
        if response.status_code == 404:
            return [], None

        try:
            response.raise_for_status()
        except Exception:
            logger.error(f"Error fetching transcripts: {response.text}")
            raise

        data = response.json()
        transcripts = data.get("callTranscripts", [])
        next_cursor = data.get("records", {}).get("cursor")
        return transcripts, next_cursor

    def _get_call_details_by_ids(self, call_ids: list[str]) -> dict[str, Any]:
        body = {
            "filter": {"callIds": call_ids},
            "contentSelector": {"exposedFields": {"parties": True}},
        }

        response = self._throttled_request(
            "POST", GongConnector.make_url("/v2/calls/extensive"), json=body
        )
        response.raise_for_status()

        calls = response.json().get("calls")
        call_to_metadata = {}
        for call in calls:
            call_to_metadata[call["metaData"]["id"]] = call

        return call_to_metadata

    @staticmethod
    def _parse_parties(parties: list[dict]) -> dict[str, str]:
        id_mapping = {}
        for party in parties:
            name = party.get("name")
            email = party.get("emailAddress")

            if name and email:
                full_identifier = f"{name} ({email})"
            elif name:
                full_identifier = name
            elif email:
                full_identifier = email
            else:
                full_identifier = "Unknown"

            id_mapping[party["speakerId"]] = full_identifier

        return id_mapping

    def _resolve_workspace_ids(self) -> list[str | None]:
        """Resolve configured workspace names/IDs to actual workspace IDs.

        Returns a list of workspace IDs. If no workspaces are configured,
        returns [None] to indicate "fetch all workspaces".
        """
        if not self.workspaces:
            return [None]

        workspace_map = self._get_workspace_id_map()
        resolved: list[str | None] = []
        for workspace in self.workspaces:
            workspace_id = workspace_map.get(workspace)
            if not workspace_id:
                logger.error(f"Invalid Gong workspace: {workspace}")
                continue
            resolved.append(workspace_id)

        # If all workspaces were invalid, fall back to fetching all
        if not resolved:
            logger.warning(
                "No valid workspaces found, falling back to fetching all workspaces"
            )
            return [None]

        return resolved

    @staticmethod
    def _compute_time_range(
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> tuple[str, str]:
        """Compute the start/end datetime strings for the Gong API filter,
        applying GONG_CONNECTOR_START_TIME and the 1-day offset."""
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)

        # if this env variable is set, don't start from a timestamp before the specified
        # start time
        if GONG_CONNECTOR_START_TIME:
            special_start_datetime = datetime.fromisoformat(GONG_CONNECTOR_START_TIME)
            special_start_datetime = special_start_datetime.replace(tzinfo=timezone.utc)
        else:
            special_start_datetime = datetime.fromtimestamp(0, tz=timezone.utc)

        # don't let the special start dt be past the end time, this causes issues when
        # the Gong API (`filter.fromDateTime: must be before toDateTime`)
        special_start_datetime = min(special_start_datetime, end_datetime)

        start_datetime = max(
            datetime.fromtimestamp(start, tz=timezone.utc), special_start_datetime
        )

        # Because these are meeting start times, the meeting needs to end and be processed
        # so adding a 1 day buffer and fetching by default till current time
        start_one_day_offset = start_datetime - timedelta(days=1)
        start_time = start_one_day_offset.isoformat()
        end_time = end_datetime.isoformat()

        return start_time, end_time

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        combined = (
            f"{credentials['gong_access_key']}:{credentials['gong_access_key_secret']}"
        )
        self.auth_token_basic = base64.b64encode(combined.encode("utf-8")).decode(
            "utf-8"
        )

        if self.auth_token_basic is None:
            raise ConnectorMissingCredentialError("Gong")

        self._session.headers.update(
            {"Authorization": f"Basic {self.auth_token_basic}"}
        )
        return None

    def build_dummy_checkpoint(self) -> GongConnectorCheckpoint:
        return GongConnectorCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> GongConnectorCheckpoint:
        return GongConnectorCheckpoint.model_validate_json(checkpoint_json)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GongConnectorCheckpoint,
    ) -> CheckpointOutput[GongConnectorCheckpoint]:
        checkpoint = copy.deepcopy(checkpoint)

        # Step 1: Resolve workspace IDs on first call
        if checkpoint.workspace_ids is None:
            checkpoint.workspace_ids = self._resolve_workspace_ids()
            checkpoint.has_more = True
            return checkpoint

        workspace_ids = checkpoint.workspace_ids

        # If we've exhausted all workspaces, we're done
        if checkpoint.workspace_index >= len(workspace_ids):
            checkpoint.has_more = False
            return checkpoint

        start_time, end_time = self._compute_time_range(start, end)
        logger.info(
            f"Fetching Gong calls between {start_time} and {end_time} "
            f"(workspace {checkpoint.workspace_index + 1}/{len(workspace_ids)})"
        )

        workspace_id = workspace_ids[checkpoint.workspace_index]

        # Step 2: Fetch one page of transcripts
        transcripts, next_cursor = self._fetch_transcript_page(
            start_datetime=start_time,
            end_datetime=end_time,
            workspace_id=workspace_id,
            cursor=checkpoint.cursor,
        )

        # Step 3: Process transcripts into documents
        if transcripts:
            transcript_call_ids = cast(
                list[str],
                [t.get("callId") for t in transcripts if t.get("callId")],
            )

            call_details_map: dict[str, Any] = {}

            # There's a likely race condition in the API where a transcript will have a
            # call id but the call to v2/calls/extensive will not return all of the id's
            # retry with exponential backoff has been observed to mitigate this
            # in ~2 minutes. After max attempts, proceed with whatever we have —
            # the per-call loop below will yield failures for missing IDs.
            current_attempt = 0
            while True:
                current_attempt += 1
                call_details_map = self._get_call_details_by_ids(transcript_call_ids)
                if set(transcript_call_ids) == set(call_details_map.keys()):
                    break

                missing_call_ids = set(transcript_call_ids) - set(
                    call_details_map.keys()
                )
                logger.warning(
                    f"_get_call_details_by_ids is missing call id's: "
                    f"current_attempt={current_attempt} "
                    f"missing_call_ids={missing_call_ids}"
                )
                if current_attempt >= self.MAX_CALL_DETAILS_ATTEMPTS:
                    logger.error(
                        f"Giving up on missing call id's after "
                        f"{self.MAX_CALL_DETAILS_ATTEMPTS} attempts: "
                        f"missing_call_ids={missing_call_ids} — "
                        f"proceeding with {len(call_details_map)} of "
                        f"{len(transcript_call_ids)} calls"
                    )
                    break

                wait_seconds = self.CALL_DETAILS_DELAY * pow(2, current_attempt - 1)
                logger.warning(
                    f"_get_call_details_by_ids waiting to retry: "
                    f"wait={wait_seconds}s "
                    f"current_attempt={current_attempt} "
                    f"next_attempt={current_attempt + 1} "
                    f"max_attempts={self.MAX_CALL_DETAILS_ATTEMPTS}"
                )
                time.sleep(wait_seconds)

            for transcript in transcripts:
                call_id = transcript.get("callId")

                if not call_id or call_id not in call_details_map:
                    logger.error(
                        f"Couldn't get call information for Call ID: {call_id}"
                    )
                    if call_id:
                        logger.error(
                            f"Call debug info: call_id={call_id} "
                            f"call_ids={transcript_call_ids} "
                            f"call_details_map={call_details_map.keys()}"
                        )
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=call_id or "unknown",
                        ),
                        failure_message=f"Couldn't get call information for Call ID: {call_id}",
                    )
                    continue

                call_details = call_details_map[call_id]
                call_metadata = call_details["metaData"]

                call_time_str = call_metadata["started"]
                call_title = call_metadata["title"]
                logger.info(
                    f"Indexing Gong call id {call_id} from {call_time_str.split('T', 1)[0]}: {call_title}"
                )

                call_parties = cast(list[dict] | None, call_details.get("parties"))
                if call_parties is None:
                    logger.error(f"Couldn't get parties for Call ID: {call_id}")
                    call_parties = []

                id_to_name_map = self._parse_parties(call_parties)

                speaker_to_name: dict[str, str] = {}

                transcript_text = ""
                call_purpose = call_metadata["purpose"]
                if call_purpose:
                    transcript_text += f"Call Description: {call_purpose}\n\n"

                contents = transcript["transcript"]
                for segment in contents:
                    speaker_id = segment.get("speakerId", "")
                    if speaker_id not in speaker_to_name:
                        if self.hide_user_info:
                            speaker_to_name[speaker_id] = (
                                f"User {len(speaker_to_name) + 1}"
                            )
                        else:
                            speaker_to_name[speaker_id] = id_to_name_map.get(
                                speaker_id, "Unknown"
                            )

                    speaker_name = speaker_to_name[speaker_id]

                    sentences = segment.get("sentences", {})
                    monolog = " ".join(
                        [sentence.get("text", "") for sentence in sentences]
                    )
                    transcript_text += f"{speaker_name}: {monolog}\n\n"

                yield Document(
                    id=call_id,
                    sections=[
                        TextSection(link=call_metadata["url"], text=transcript_text)
                    ],
                    source=DocumentSource.GONG,
                    semantic_identifier=call_title or "Untitled",
                    doc_updated_at=datetime.fromisoformat(call_time_str).astimezone(
                        timezone.utc
                    ),
                    metadata={"client": call_metadata.get("system")},
                )

        # Step 4: Update checkpoint state
        if next_cursor:
            # More pages in this workspace
            checkpoint.cursor = next_cursor
            checkpoint.has_more = True
        else:
            # This workspace is exhausted — advance to next
            checkpoint.workspace_index += 1
            checkpoint.cursor = None
            checkpoint.has_more = checkpoint.workspace_index < len(workspace_ids)

        return checkpoint


if __name__ == "__main__":
    import os

    connector = GongConnector()
    connector.load_credentials(
        {
            "gong_access_key": os.environ["GONG_ACCESS_KEY"],
            "gong_access_key_secret": os.environ["GONG_ACCESS_KEY_SECRET"],
        }
    )

    checkpoint = connector.build_dummy_checkpoint()
    while checkpoint.has_more:
        doc_generator = connector.load_from_checkpoint(0, time.time(), checkpoint)
        try:
            while True:
                item = next(doc_generator)
                print(item)
        except StopIteration as e:
            checkpoint = e.value
            print(f"Checkpoint: {checkpoint}")
