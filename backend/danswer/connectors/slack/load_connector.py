import json
import os
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import cast

from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.constants import DocumentSource
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.connectors.slack.connector import filter_channels
from danswer.connectors.slack.utils import get_message_link
from danswer.utils.logger import setup_logger


logger = setup_logger()


def get_event_time(event: dict[str, Any]) -> datetime | None:
    ts = event.get("ts")
    if not ts:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)


class SlackLoadConnector(LoadConnector):
    # WARNING: DEPRECATED, DO NOT USE
    def __init__(
        self,
        workspace: str,
        export_path_str: str,
        channels: list[str] | None = None,
        # if specified, will treat the specified channel strings as
        # regexes, and will only index channels that fully match the regexes
        channel_regex_enabled: bool = False,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.workspace = workspace
        self.channels = channels
        self.channel_regex_enabled = channel_regex_enabled
        self.export_path_str = export_path_str
        self.batch_size = batch_size

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        if credentials:
            logger.warning("Unexpected credentials provided for Slack Load Connector")
        return None

    @staticmethod
    def _process_batch_event(
        slack_event: dict[str, Any],
        channel: dict[str, Any],
        matching_doc: Document | None,
        workspace: str,
    ) -> Document | None:
        if (
            slack_event["type"] == "message"
            and slack_event.get("subtype") != "channel_join"
        ):
            if matching_doc:
                return Document(
                    id=matching_doc.id,
                    sections=matching_doc.sections
                    + [
                        Section(
                            link=get_message_link(
                                event=slack_event,
                                workspace=workspace,
                                channel_id=channel["id"],
                            ),
                            text=slack_event["text"],
                        )
                    ],
                    source=matching_doc.source,
                    semantic_identifier=matching_doc.semantic_identifier,
                    title="",  # slack docs don't really have a "title"
                    doc_updated_at=get_event_time(slack_event),
                    metadata=matching_doc.metadata,
                )

            return Document(
                id=slack_event["ts"],
                sections=[
                    Section(
                        link=get_message_link(
                            event=slack_event,
                            workspace=workspace,
                            channel_id=channel["id"],
                        ),
                        text=slack_event["text"],
                    )
                ],
                source=DocumentSource.SLACK,
                semantic_identifier=channel["name"],
                title="",  # slack docs don't really have a "title"
                doc_updated_at=get_event_time(slack_event),
                metadata={},
            )

        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        export_path = Path(self.export_path_str)

        with open(export_path / "channels.json") as f:
            all_channels = json.load(f)

        filtered_channels = filter_channels(
            all_channels, self.channels, self.channel_regex_enabled
        )

        document_batch: dict[str, Document] = {}
        for channel_info in filtered_channels:
            channel_dir_path = export_path / cast(str, channel_info["name"])
            channel_file_paths = [
                channel_dir_path / file_name
                for file_name in os.listdir(channel_dir_path)
            ]
            for path in channel_file_paths:
                with open(path) as f:
                    events = cast(list[dict[str, Any]], json.load(f))
                for slack_event in events:
                    doc = self._process_batch_event(
                        slack_event=slack_event,
                        channel=channel_info,
                        matching_doc=document_batch.get(
                            slack_event.get("thread_ts", "")
                        ),
                        workspace=self.workspace,
                    )
                    if doc:
                        document_batch[doc.id] = doc
                        if len(document_batch) >= self.batch_size:
                            yield list(document_batch.values())

        yield list(document_batch.values())
