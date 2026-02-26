import base64
import copy
import time
from collections.abc import Generator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import cast

import requests
from requests.adapters import HTTPAdapter
from typing_extensions import override
from urllib3.util import Retry

from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
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
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


class GongConnectorCheckpoint(ConnectorCheckpoint):
    cursor: str | None = None  # API pagination cursor for /v2/calls/transcript
    workspace_index: int = 0  # Index into the workspace_list being processed


class GongConnector(CheckpointedConnector[GongConnectorCheckpoint]):
    BASE_URL = "https://api.gong.io"
    MAX_CALL_DETAILS_ATTEMPTS = 6
    CALL_DETAILS_DELAY = 30  # in seconds

    def __init__(
        self,
        workspaces: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        continue_on_fail: bool = CONTINUE_ON_CONNECTOR_FAILURE,
        hide_user_info: bool = False,
    ) -> None:
        self.workspaces = workspaces
        self.batch_size: int = batch_size
        self.continue_on_fail = continue_on_fail
        self.auth_token_basic: str | None = None
        self.hide_user_info = hide_user_info

        retry_strategy = Retry(
            total=5,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
        )

        session = requests.Session()
        session.mount(GongConnector.BASE_URL, HTTPAdapter(max_retries=retry_strategy))
        self._session = session

    @staticmethod
    def make_url(endpoint: str) -> str:
        return f"{GongConnector.BASE_URL}{endpoint}"

    def _get_workspace_id_map(self) -> dict[str, str]:
        response = self._session.get(GongConnector.make_url("/v2/workspaces"))
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

    def _get_call_details_by_ids(self, call_ids: list[str]) -> dict:
        body = {
            "filter": {"callIds": call_ids},
            "contentSelector": {"exposedFields": {"parties": True}},
        }

        response = self._session.post(
            GongConnector.make_url("/v2/calls/extensive"), json=body
        )
        response.raise_for_status()

        calls = response.json().get("calls")
        call_to_metadata = {}
        for call in calls:
            call_to_metadata[call["metaData"]["id"]] = call

        return call_to_metadata

    def _fetch_call_details_with_retry(self, call_ids: list[str]) -> dict[str, Any]:
        """Fetch call details with retry for the race condition where transcript IDs
        aren't immediately available in the extensive endpoint."""
        current_attempt = 0
        while True:
            current_attempt += 1
            call_details_map = self._get_call_details_by_ids(call_ids)
            if set(call_ids) == set(call_details_map.keys()):
                return call_details_map

            missing_call_ids = set(call_ids) - set(call_details_map.keys())
            logger.warning(
                f"_get_call_details_by_ids is missing call id's: "
                f"current_attempt={current_attempt} "
                f"missing_call_ids={missing_call_ids}"
            )
            if current_attempt >= self.MAX_CALL_DETAILS_ATTEMPTS:
                raise RuntimeError(
                    f"Attempt count exceeded for _get_call_details_by_ids: "
                    f"missing_call_ids={missing_call_ids} "
                    f"max_attempts={self.MAX_CALL_DETAILS_ATTEMPTS}"
                )

            wait_seconds = self.CALL_DETAILS_DELAY * pow(2, current_attempt - 1)
            logger.warning(
                f"_get_call_details_by_ids waiting to retry: "
                f"wait={wait_seconds}s "
                f"current_attempt={current_attempt} "
                f"next_attempt={current_attempt+1} "
                f"max_attempts={self.MAX_CALL_DETAILS_ATTEMPTS}"
            )
            time.sleep(wait_seconds)

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

    def _transcripts_to_documents(
        self, transcripts: list[dict[str, Any]]
    ) -> Generator[Document | HierarchyNode | ConnectorFailure, None, None]:
        """Convert a page of transcripts to Documents, fetching call details as needed."""
        if not transcripts:
            return

        transcript_call_ids = cast(
            list[str],
            [t.get("callId") for t in transcripts if t.get("callId")],
        )

        # Raises RuntimeError if all retry attempts are exhausted
        call_details_map = self._fetch_call_details_with_retry(transcript_call_ids)

        num_calls = 0
        for transcript in transcripts:
            call_id = transcript.get("callId")

            if not call_id or call_id not in call_details_map:
                logger.error(f"Couldn't get call information for Call ID: {call_id}")
                if call_id:
                    logger.error(
                        f"Call debug info: call_id={call_id} "
                        f"call_ids={transcript_call_ids} "
                        f"call_details_map={call_details_map.keys()}"
                    )
                if not self.continue_on_fail:
                    raise RuntimeError(
                        f"Couldn't get call information for Call ID: {call_id}"
                    )
                if call_id:
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(document_id=call_id),
                        failure_message=f"Couldn't get call information for Call ID: {call_id}",
                    )
                continue

            call_details = call_details_map[call_id]
            call_metadata = call_details["metaData"]

            call_time_str = call_metadata["started"]
            call_title = call_metadata["title"]
            logger.info(
                f"{num_calls + 1}: Indexing Gong call id {call_id} "
                f"from {call_time_str.split('T', 1)[0]}: {call_title}"
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
                        speaker_to_name[speaker_id] = f"User {len(speaker_to_name) + 1}"
                    else:
                        speaker_to_name[speaker_id] = id_to_name_map.get(
                            speaker_id, "Unknown"
                        )

                speaker_name = speaker_to_name[speaker_id]
                sentences = segment.get("sentences", {})
                monolog = " ".join([sentence.get("text", "") for sentence in sentences])
                transcript_text += f"{speaker_name}: {monolog}\n\n"

            yield Document(
                id=call_id,
                sections=[TextSection(link=call_metadata["url"], text=transcript_text)],
                source=DocumentSource.GONG,
                semantic_identifier=call_title or "Untitled",
                doc_updated_at=datetime.fromisoformat(call_time_str).astimezone(
                    timezone.utc
                ),
                metadata={"client": call_metadata.get("system")},
            )

            num_calls += 1

    def _compute_time_range(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> tuple[str, str]:
        """Compute start/end datetime strings for the Gong API.

        Applies GONG_CONNECTOR_START_TIME lower bound and a 1-day lookback buffer
        to account for meeting processing lag (meeting start time vs. transcript
        availability).
        """
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)

        if GONG_CONNECTOR_START_TIME:
            special_start = datetime.fromisoformat(GONG_CONNECTOR_START_TIME).replace(
                tzinfo=timezone.utc
            )
        else:
            special_start = datetime.fromtimestamp(0, tz=timezone.utc)

        special_start = min(special_start, end_datetime)
        start_datetime = max(
            datetime.fromtimestamp(start, tz=timezone.utc), special_start
        )
        # 1-day buffer so recently-completed meetings are included
        start_one_day_offset = start_datetime - timedelta(days=1)
        return start_one_day_offset.isoformat(), end_datetime.isoformat()

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        combined = (
            f'{credentials["gong_access_key"]}:{credentials["gong_access_key_secret"]}'
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

    @override
    def build_dummy_checkpoint(self) -> GongConnectorCheckpoint:
        return GongConnectorCheckpoint(has_more=True)

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> GongConnectorCheckpoint:
        return GongConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GongConnectorCheckpoint,
    ) -> CheckpointOutput[GongConnectorCheckpoint]:
        """Fetch one page of Gong call transcripts and yield their documents.

        Each invocation processes a single API page for the current workspace.
        The returned checkpoint stores the cursor and workspace index so the
        next invocation can resume exactly where this one left off.
        """
        start_time, end_time = self._compute_time_range(start, end)
        logger.info(f"Fetching Gong calls between {start_time} and {end_time}")

        new_checkpoint = copy.deepcopy(checkpoint)

        workspace_list: list[str | None] = self.workspaces or [None]
        workspace_map = self._get_workspace_id_map() if self.workspaces else {}

        workspace_idx = new_checkpoint.workspace_index
        while workspace_idx < len(workspace_list):
            workspace = workspace_list[workspace_idx]

            body: dict[str, Any] = {
                "filter": {
                    "fromDateTime": start_time,
                    "toDateTime": end_time,
                }
            }

            if workspace:
                workspace_id = workspace_map.get(workspace)
                if not workspace_id:
                    logger.error(f"Invalid Gong workspace: {workspace}")
                    if not self.continue_on_fail:
                        raise ValueError(f"Invalid workspace: {workspace}")
                    workspace_idx += 1
                    continue
                body["filter"]["workspaceId"] = workspace_id
                logger.info(f"Targeting workspace '{workspace}'")

            # Resume pagination within the current workspace
            if workspace_idx == checkpoint.workspace_index and checkpoint.cursor:
                body["cursor"] = checkpoint.cursor

            response = self._session.post(
                GongConnector.make_url("/v2/calls/transcript"), json=body
            )

            if response.status_code == 404:
                # No calls for this workspace in the given time range
                workspace_idx += 1
                continue

            try:
                response.raise_for_status()
            except Exception:
                logger.error(f"Error fetching transcripts: {response.text}")
                raise

            data = response.json()
            call_transcripts = data.get("callTranscripts", [])

            yield from self._transcripts_to_documents(call_transcripts)

            next_cursor = data.get("records", {}).get("cursor")
            if next_cursor:
                # More pages remain in this workspace
                new_checkpoint.cursor = next_cursor
                new_checkpoint.workspace_index = workspace_idx
                new_checkpoint.has_more = True
            else:
                # This workspace is exhausted; advance to the next
                new_checkpoint.cursor = None
                new_checkpoint.workspace_index = workspace_idx + 1
                new_checkpoint.has_more = workspace_idx + 1 < len(workspace_list)

            return new_checkpoint

        # All workspaces processed (or all returned 404 / were invalid)
        new_checkpoint.cursor = None
        new_checkpoint.workspace_index = len(workspace_list)
        new_checkpoint.has_more = False
        return new_checkpoint


if __name__ == "__main__":
    import os
    import time as _time

    from onyx.connectors.connector_runner import CheckpointOutputWrapper

    connector = GongConnector()
    connector.load_credentials(
        {
            "gong_access_key": os.environ["GONG_ACCESS_KEY"],
            "gong_access_key_secret": os.environ["GONG_ACCESS_KEY_SECRET"],
        }
    )

    checkpoint = connector.build_dummy_checkpoint()
    while checkpoint.has_more:
        wrapper: CheckpointOutputWrapper[GongConnectorCheckpoint] = (
            CheckpointOutputWrapper()
        )
        for doc, node, failure, next_cp in wrapper(
            connector.load_from_checkpoint(0, _time.time(), checkpoint)
        ):
            if doc is not None:
                print(doc)
            if next_cp is not None:
                checkpoint = next_cp
