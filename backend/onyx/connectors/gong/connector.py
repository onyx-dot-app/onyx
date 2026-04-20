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
from pydantic import BaseModel
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from onyx.configs.app_configs import GONG_CONNECTOR_START_TIME
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
    # Cached time range — computed once, reused across checkpoint calls
    time_range: tuple[str, str] | None = None
    # Transcripts whose call details were not yet available from /v2/calls/extensive
    # (Gong has a known race where transcript call IDs take time to propagate).
    # Keyed by call_id. Retried on subsequent checkpoint invocations.
    #
    # Invariant: all entries share one resolution session — they're stashed
    # together from a single page and share the attempt counter and retry
    # deadline. load_from_checkpoint only fetches a new page when this dict
    # is empty, so entries from different pages can't mix.
    pending_transcripts: dict[str, dict[str, Any]] = {}
    # Number of resolution attempts made for pending_transcripts so far.
    pending_call_details_attempts: int = 0
    # Unix timestamp before which we should not retry pending_transcripts.
    # Enforces exponential backoff independent of worker cadence — Gong's
    # transcript-ID propagation race can take tens of seconds to minutes,
    # longer than typical worker reinvocation intervals.
    pending_retry_after: float | None = None


class _TranscriptPage(BaseModel):
    """One page of transcripts from /v2/calls/transcript."""

    transcripts: list[dict[str, Any]]
    next_cursor: str | None = None


class _CursorExpiredError(Exception):
    """Raised when Gong rejects a pagination cursor as expired.

    Gong pagination cursors TTL is ~1 hour from the first request in a
    pagination sequence, not from the last cursor fetch. Since checkpointed
    connector runs can pause between invocations, a resumed run may encounter
    an expired cursor and must restart the current workspace from scratch.
    See https://visioneers.gong.io/integrations-77/pagination-cursor-expires-after-1-hours-even-for-a-new-cursor-1382
    """


class GongConnector(CheckpointedConnector[GongConnectorCheckpoint]):
    BASE_URL = "https://api.gong.io"
    # Max number of attempts to resolve missing call details across checkpoint
    # invocations before giving up and emitting ConnectorFailure.
    MAX_CALL_DETAILS_ATTEMPTS = 6
    # Base delay for exponential backoff between pending-transcript retry
    # attempts. Delay before attempt N (N >= 2) is CALL_DETAILS_DELAY * 2^(N-2)
    # seconds (30, 60, 120, 240, 480 = ~15.5min total) — matching the original
    # blocking-retry schedule, but enforced via checkpoint deadline rather
    # than in-call time.sleep.
    CALL_DETAILS_DELAY = 30
    # Gong API limit is 3 calls/sec — stay safely under it
    MIN_REQUEST_INTERVAL = 0.5  # seconds between requests

    def __init__(
        self,
        workspaces: list[str] | None = None,
        hide_user_info: bool = False,
    ) -> None:
        self.workspaces = workspaces
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
    ) -> _TranscriptPage:
        """Fetch one page of transcripts from the Gong API.

        Raises _CursorExpiredError if Gong reports the pagination cursor
        expired (TTL is ~1 hour from first request in the pagination sequence).
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
            return _TranscriptPage(transcripts=[])

        if not response.ok:
            # Cursor expiration comes back as a 4xx with this error message —
            # detect it before raise_for_status so callers can restart the workspace.
            if cursor and "cursor has expired" in response.text.lower():
                raise _CursorExpiredError(response.text)
            logger.error(f"Error fetching transcripts: {response.text}")
            response.raise_for_status()

        data = response.json()
        return _TranscriptPage(
            transcripts=data.get("callTranscripts", []),
            next_cursor=data.get("records", {}).get("cursor"),
        )

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

        Raises ValueError if workspaces are configured but none resolve —
        we never silently widen scope to "fetch all" on misconfiguration,
        because that could ingest an entire Gong account by mistake.
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

        if not resolved:
            raise ValueError(
                f"No valid Gong workspaces found — check workspace names/IDs in connector config. Configured: {self.workspaces}"
            )

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

    def _build_document(
        self,
        transcript: dict[str, Any],
        call_details: dict[str, Any],
    ) -> Document:
        """Build a single Document from a transcript and its resolved call details."""
        call_id = transcript["callId"]
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
                    speaker_to_name[speaker_id] = f"User {len(speaker_to_name) + 1}"
                else:
                    speaker_to_name[speaker_id] = id_to_name_map.get(
                        speaker_id, "Unknown"
                    )

            speaker_name = speaker_to_name[speaker_id]

            sentences = segment.get("sentences", {})
            monolog = " ".join([sentence.get("text", "") for sentence in sentences])
            transcript_text += f"{speaker_name}: {monolog}\n\n"

        return Document(
            id=call_id,
            sections=[TextSection(link=call_metadata["url"], text=transcript_text)],
            source=DocumentSource.GONG,
            semantic_identifier=call_title or "Untitled",
            doc_updated_at=datetime.fromisoformat(call_time_str).astimezone(
                timezone.utc
            ),
            metadata={"client": call_metadata.get("system")},
        )

    def _process_transcripts(
        self,
        transcripts: list[dict[str, Any]],
        checkpoint: GongConnectorCheckpoint,
    ) -> Generator[Document | ConnectorFailure, None, None]:
        """Fetch call details for a page of transcripts and yield resulting
        Documents. Transcripts whose call details are missing (Gong race
        condition) are stashed into `checkpoint.pending_transcripts` for retry
        on a future checkpoint invocation rather than blocking here.
        """
        transcript_call_ids = cast(
            list[str],
            [t.get("callId") for t in transcripts if t.get("callId")],
        )

        call_details_map = (
            self._get_call_details_by_ids(transcript_call_ids)
            if transcript_call_ids
            else {}
        )

        newly_stashed: list[str] = []

        for transcript in transcripts:
            call_id = transcript.get("callId")

            if not call_id:
                logger.error(
                    "Couldn't get call information for transcript missing callId"
                )
                yield ConnectorFailure(
                    failed_document=DocumentFailure(document_id="unknown"),
                    failure_message="Transcript missing callId",
                )
                continue

            if call_id in call_details_map:
                yield self._build_document(transcript, call_details_map[call_id])
                continue

            # Details not available yet — stash for retry on next invocation.
            checkpoint.pending_transcripts[call_id] = transcript
            newly_stashed.append(call_id)

        if newly_stashed:
            logger.warning(
                f"Gong call details not yet available (race condition); "
                f"deferring to next checkpoint invocation: "
                f"call_ids={newly_stashed}"
            )
            # First attempt on any newly-stashed transcripts counts as attempt #1.
            # pending_call_details_attempts is guaranteed 0 here because
            # load_from_checkpoint only reaches _process_transcripts when
            # pending_transcripts was empty at entry (see early-return above).
            checkpoint.pending_call_details_attempts = 1
            checkpoint.pending_retry_after = time.time() + self._next_retry_delay(1)

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
            checkpoint.time_range = self._compute_time_range(start, end)
            checkpoint.has_more = True
            return checkpoint

        # Step 2: Resolve any transcripts stashed by a prior invocation whose
        # call details were missing due to Gong's propagation race. Worker
        # cadence between checkpoint calls provides the spacing between retry
        # attempts — no in-call sleep needed.
        if checkpoint.pending_transcripts:
            yield from self._resolve_pending_transcripts(checkpoint)
            # If pending still exists and we haven't exhausted attempts, defer
            # the rest of this invocation — _resolve_pending_transcripts set
            # has_more=True for us.
            if checkpoint.pending_transcripts:
                return checkpoint

        workspace_ids = checkpoint.workspace_ids

        # If we've exhausted all workspaces, we're done
        if checkpoint.workspace_index >= len(workspace_ids):
            checkpoint.has_more = False
            return checkpoint

        # Use cached time range, falling back to computation if not cached
        start_time, end_time = checkpoint.time_range or self._compute_time_range(
            start, end
        )
        logger.info(
            f"Fetching Gong calls between {start_time} and {end_time} "
            f"(workspace {checkpoint.workspace_index + 1}/{len(workspace_ids)})"
        )

        workspace_id = workspace_ids[checkpoint.workspace_index]

        # Step 3: Fetch one page of transcripts
        try:
            page = self._fetch_transcript_page(
                start_datetime=start_time,
                end_datetime=end_time,
                workspace_id=workspace_id,
                cursor=checkpoint.cursor,
            )
        except _CursorExpiredError:
            # Gong cursors TTL ~1h from first request in the sequence. If the
            # checkpoint paused long enough for the cursor to expire, restart
            # the current workspace from the beginning of the time range.
            # Document upserts are idempotent (keyed by call_id) so
            # reprocessing is safe.
            logger.warning(
                f"Gong pagination cursor expired for workspace "
                f"{checkpoint.workspace_index + 1}/{len(workspace_ids)}; "
                f"restarting workspace from beginning of time range."
            )
            checkpoint.cursor = None
            checkpoint.has_more = True
            return checkpoint

        # Step 4: Process transcripts into documents. Missing-details
        # transcripts get stashed into checkpoint.pending_transcripts.
        if page.transcripts:
            yield from self._process_transcripts(page.transcripts, checkpoint)

        # Step 5: Update cursor/workspace state
        if page.next_cursor:
            checkpoint.cursor = page.next_cursor
            checkpoint.has_more = True
        else:
            checkpoint.workspace_index += 1
            checkpoint.cursor = None
            checkpoint.has_more = checkpoint.workspace_index < len(workspace_ids)

        # If pending transcripts were stashed this invocation, we still have
        # work to do on a future invocation even if pagination is exhausted.
        if checkpoint.pending_transcripts:
            checkpoint.has_more = True

        return checkpoint

    def _next_retry_delay(self, attempts_done: int) -> float:
        """Seconds to wait before attempt #(attempts_done + 1).
        Matches the original exponential backoff: 30, 60, 120, 240, 480.
        """
        return self.CALL_DETAILS_DELAY * pow(2, attempts_done - 1)

    def _resolve_pending_transcripts(
        self,
        checkpoint: GongConnectorCheckpoint,
    ) -> Generator[Document | ConnectorFailure, None, None]:
        """Attempt to resolve transcripts whose call details were unavailable
        in a prior invocation. Mutates checkpoint in place: resolved transcripts
        are removed from pending_transcripts; on attempt exhaustion, emits
        ConnectorFailure for each unresolved call_id and clears pending state.

        If the backoff deadline hasn't elapsed yet, returns without issuing
        any API call so the next invocation can try again later.
        """
        if (
            checkpoint.pending_retry_after is not None
            and time.time() < checkpoint.pending_retry_after
        ):
            # Backoff still in effect — defer to a later invocation without
            # burning an attempt or an API call.
            checkpoint.has_more = True
            return

        pending_call_ids = list(checkpoint.pending_transcripts.keys())
        resolved = self._get_call_details_by_ids(pending_call_ids)

        for call_id, details in resolved.items():
            transcript = checkpoint.pending_transcripts.pop(call_id, None)
            if transcript is None:
                continue
            yield self._build_document(transcript, details)

        if not checkpoint.pending_transcripts:
            checkpoint.pending_call_details_attempts = 0
            checkpoint.pending_retry_after = None
            return

        checkpoint.pending_call_details_attempts += 1
        logger.warning(
            f"Gong call details still missing after "
            f"{checkpoint.pending_call_details_attempts}/"
            f"{self.MAX_CALL_DETAILS_ATTEMPTS} attempts: "
            f"missing_call_ids={list(checkpoint.pending_transcripts.keys())}"
        )

        if checkpoint.pending_call_details_attempts >= self.MAX_CALL_DETAILS_ATTEMPTS:
            logger.error(
                f"Giving up on missing Gong call details after "
                f"{self.MAX_CALL_DETAILS_ATTEMPTS} attempts: "
                f"missing_call_ids={list(checkpoint.pending_transcripts.keys())}"
            )
            for call_id in list(checkpoint.pending_transcripts.keys()):
                yield ConnectorFailure(
                    failed_document=DocumentFailure(document_id=call_id),
                    failure_message=(
                        f"Couldn't get call details after {self.MAX_CALL_DETAILS_ATTEMPTS} attempts for Call ID: {call_id}"
                    ),
                )
            checkpoint.pending_transcripts = {}
            checkpoint.pending_call_details_attempts = 0
            checkpoint.pending_retry_after = None
            # has_more is recomputed by the workspace iteration that follows;
            # reset to False here so a stale True from a prior invocation
            # can't leak out via any future early-return path.
            checkpoint.has_more = False
        else:
            checkpoint.pending_retry_after = time.time() + self._next_retry_delay(
                checkpoint.pending_call_details_attempts
            )
            checkpoint.has_more = True


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
