import base64
from collections.abc import Generator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import cast

import requests

from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from onyx.configs.app_configs import GONG_CONNECTOR_START_TIME
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import Section
from onyx.utils.logger import setup_logger


logger = setup_logger()

GONG_BASE_URL = "https://us-34014.api.gong.io"


class GongConnector(LoadConnector, PollConnector):
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

    def _get_auth_header(self) -> dict[str, str]:
        if self.auth_token_basic is None:
            raise ConnectorMissingCredentialError("Gong")

        return {"Authorization": f"Basic {self.auth_token_basic}"}

    def _get_workspace_id_map(self) -> dict[str, str]:
        url = f"{GONG_BASE_URL}/v2/workspaces"
        response = requests.get(url, headers=self._get_auth_header())
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

    def _get_transcript_batches(
        self, start_datetime: str | None = None, end_datetime: str | None = None
    ) -> Generator[list[dict[str, Any]], None, None]:
        url = f"{GONG_BASE_URL}/v2/calls/transcript"
        body: dict[str, dict] = {"filter": {}}
        if start_datetime:
            body["filter"]["fromDateTime"] = start_datetime
        if end_datetime:
            body["filter"]["toDateTime"] = end_datetime

        # The batch_ids in the previous method appears to be batches of call_ids to process
        # In this method, we will retrieve transcripts for them in batches.
        transcripts: list[dict[str, Any]] = []
        workspace_list = self.workspaces or [None]  # type: ignore
        workspace_map = self._get_workspace_id_map() if self.workspaces else {}

        for workspace in workspace_list:
            if workspace:
                logger.info(f"Updating Gong workspace: {workspace}")
                workspace_id = workspace_map.get(workspace)
                if not workspace_id:
                    logger.error(f"Invalid Gong workspace: {workspace}")
                    if not self.continue_on_fail:
                        raise ValueError(f"Invalid workspace: {workspace}")
                    continue
                body["filter"]["workspaceId"] = workspace_id
            else:
                if "workspaceId" in body["filter"]:
                    del body["filter"]["workspaceId"]

            while True:
                response = requests.post(
                    url, headers=self._get_auth_header(), json=body
                )
                # If no calls in the range, just break out
                if response.status_code == 404:
                    break

                try:
                    response.raise_for_status()
                except Exception:
                    logger.error(f"Error fetching transcripts: {response.text}")
                    raise

                data = response.json()
                call_transcripts = data.get("callTranscripts", [])
                transcripts.extend(call_transcripts)

                while len(transcripts) >= self.batch_size:
                    yield transcripts[: self.batch_size]
                    transcripts = transcripts[self.batch_size :]

                cursor = data.get("records", {}).get("cursor")
                if cursor:
                    body["cursor"] = cursor
                else:
                    break

        if transcripts:
            yield transcripts

    def _get_call_details_by_ids(self, call_ids: list[str]) -> dict:
        url = f"{GONG_BASE_URL}/v2/calls/extensive"

        body = {
            "filter": {"callIds": call_ids},
            "contentSelector": {"exposedFields": {"parties": True}},
        }

        response = requests.post(url, headers=self._get_auth_header(), json=body)
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

    def _fetch_calls(
        self, start_datetime: str | None = None, end_datetime: str | None = None
    ) -> GenerateDocumentsOutput:
        for transcript_batch in self._get_transcript_batches(
            start_datetime, end_datetime
        ):
            doc_batch: list[Document] = []

            call_ids = cast(
                list[str],
                [t.get("callId") for t in transcript_batch if t.get("callId")],
            )
            call_details_map = self._get_call_details_by_ids(call_ids)

            for transcript in transcript_batch:
                call_id = transcript.get("callId")

                if not call_id or call_id not in call_details_map:
                    logger.error(
                        f"Couldn't get call information for Call ID: {call_id}"
                    )
                    if not self.continue_on_fail:
                        raise RuntimeError(
                            f"Couldn't get call information for Call ID: {call_id}"
                        )
                    continue

                call_details = call_details_map[call_id]
                call_metadata = call_details["metaData"]

                call_time_str = call_metadata["started"]
                call_title = call_metadata["title"]
                logger.info(
                    f"Indexing Gong call from {call_time_str.split('T', 1)[0]}: {call_title}"
                )

                call_parties = cast(list[dict] | None, call_details.get("parties"))
                if call_parties is None:
                    logger.error(f"Couldn't get parties for Call ID: {call_id}")
                    call_parties = []

                id_to_name_map = self._parse_parties(call_parties)

                # Keeping a separate dict here in case the parties info is incomplete
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
                            speaker_to_name[
                                speaker_id
                            ] = f"User {len(speaker_to_name) + 1}"
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

                metadata = {}
                if call_metadata.get("system"):
                    metadata["client"] = call_metadata.get("system")
                # TODO calls have a clientUniqueId field, can pull that in later

                doc_batch.append(
                    Document(
                        id=call_id,
                        sections=[
                            Section(link=call_metadata["url"], text=transcript_text)
                        ],
                        source=DocumentSource.GONG,
                        # Should not ever be Untitled as a call cannot be made without a Title
                        semantic_identifier=call_title or "Untitled",
                        doc_updated_at=datetime.fromisoformat(call_time_str).astimezone(
                            timezone.utc
                        ),
                        metadata={"client": call_metadata.get("system")},
                    )
                )
            yield doc_batch

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        combined = (
            f'{credentials["gong_access_key"]}:{credentials["gong_access_key_secret"]}'
        )
        self.auth_token_basic = base64.b64encode(combined.encode("utf-8")).decode(
            "utf-8"
        )
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._fetch_calls()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)

        # if this env variable is set, don't start from a timestamp before the specified
        # start time
        # TODO: remove this once this is globally available
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

        end_time = datetime.fromtimestamp(end, tz=timezone.utc).isoformat()

        logger.info(f"Fetching Gong calls between {start_time} and {end_time}")
        return self._fetch_calls(start_time, end_time)


if __name__ == "__main__":
    import os

    connector = GongConnector()
    connector.load_credentials(
        {
            "gong_access_key": os.environ["GONG_ACCESS_KEY"],
            "gong_access_key_secret": os.environ["GONG_ACCESS_KEY_SECRET"],
        }
    )

    latest_docs = connector.load_from_state()
    print(next(latest_docs))
