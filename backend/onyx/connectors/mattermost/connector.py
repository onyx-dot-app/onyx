"""Mattermost connector.

Indexes Mattermost posts as one Onyx Document per thread (a root post plus its
replies). Modeled on the Slack connector: a checkpointed, channel-by-channel walk
with resume support and thread de-duplication.

Phase 1 (this file): token auth + indexing + slim docs. Document-level permission
sync (private-channel ACLs) is a later phase; ``external_access`` stays ``None``.
"""
import copy
import re
from datetime import datetime
from datetime import timezone
from typing import Any

import requests
from pydantic import BaseModel

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.mattermost.client import MattermostClient
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.db.enums import HierarchyNodeType
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

_SYSTEM_POST_PREFIX = "system_"
_DEFAULT_PER_PAGE = 200
# Direct + group message channel types, excluded from indexing unless opted in.
_DM_CHANNEL_TYPES = ("D", "G")


def _build_doc_id(channel_id: str, root_id: str) -> str:
    return f"{channel_id}__{root_id}"


def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def _is_indexable_post(post: dict) -> bool:
    """Skip system messages and soft-deleted posts."""
    if str(post.get("type", "")).startswith(_SYSTEM_POST_PREFIX):
        return False
    if post.get("delete_at", 0):
        return False
    return True


def _name_matches(
    patterns: list[str], regex_enabled: bool, channel: "ChannelInfo"
) -> bool:
    """True if the channel matches any pattern (by name or display name)."""
    candidates = (channel.name, channel.display_name)
    if regex_enabled:
        return any(
            re.fullmatch(pat, cand) is not None
            for pat in patterns
            for cand in candidates
        )
    lowered = {c.lower() for c in candidates}
    return any(pat.lower().lstrip("#") in lowered for pat in patterns)


class ChannelInfo(BaseModel):
    """Serializable channel summary carried inside the checkpoint."""

    id: str
    type: str  # "O" | "P" | "D" | "G"
    name: str
    display_name: str
    team_id: str
    team_name: str
    team_display_name: str


class MattermostCheckpoint(ConnectorCheckpoint):
    channel_ids: list[str] | None = None
    # channel_id -> oldest post_id processed so far (the `before=` cursor)
    channel_completion_map: dict[str, str] = {}
    current_channel: ChannelInfo | None = None
    current_channel_access: Any | None = None  # ExternalAccess; populated in a later phase
    seen_root_ids: list[str] = []


class MattermostConnector(SlimConnector, CheckpointedConnector[MattermostCheckpoint]):
    def __init__(
        self,
        teams: list[str] | None = None,
        channels: list[str] | None = None,
        channel_regex_enabled: bool = False,
        exclude_channels: list[str] | None = None,
        include_private_channels: bool = True,
        include_dms: bool = False,
        include_archived: bool = False,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.teams = teams or []
        self.channels = channels or []
        self.channel_regex_enabled = channel_regex_enabled
        self.exclude_channels = exclude_channels or []
        self.include_private_channels = include_private_channels
        self.include_dms = include_dms
        self.include_archived = include_archived
        self.batch_size = batch_size

        self.client: MattermostClient | None = None
        self._user_id: str | None = None
        self._user_cache: dict[str, BasicExpertInfo] = {}
        self._channel_by_id: dict[str, ChannelInfo] = {}
        self._current_channel_access: Any | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.client = MattermostClient(
            base_url=credentials["mattermost_base_url"],
            access_token=credentials["mattermost_access_token"],
        )
        return None

    # ---- enumeration ----
    def _require_client(self) -> MattermostClient:
        if self.client is None:
            raise ConnectorMissingCredentialError("Mattermost")
        return self.client

    def _user_id_value(self) -> str:
        if self._user_id is None:
            self._user_id = self._require_client().get_me()["id"]
        return self._user_id

    def _enumerate_channels(self) -> list[ChannelInfo]:
        client = self._require_client()
        user_id = self._user_id_value()
        teams = client.get_my_teams()
        if self.teams:
            wanted = set(self.teams)
            teams = [
                t for t in teams if t["name"] in wanted or t["display_name"] in wanted
            ]
        out: list[ChannelInfo] = []
        for team in teams:
            for ch in client.get_channels_for_team(user_id, team["id"]):
                info = ChannelInfo(
                    id=ch["id"],
                    type=ch["type"],
                    name=ch.get("name", ""),
                    display_name=ch.get("display_name") or ch.get("name", ""),
                    team_id=team["id"],
                    team_name=team["name"],
                    team_display_name=team["display_name"],
                )
                if self._channel_allowed(ch, info):
                    out.append(info)
        return out

    def _channel_allowed(self, raw: dict, info: ChannelInfo) -> bool:
        if info.type == "P" and not self.include_private_channels:
            return False
        if info.type in _DM_CHANNEL_TYPES and not self.include_dms:
            return False
        if raw.get("delete_at", 0) and not self.include_archived:
            return False
        if self.exclude_channels and _name_matches(
            self.exclude_channels, self.channel_regex_enabled, info
        ):
            return False
        if self.channels and not _name_matches(
            self.channels, self.channel_regex_enabled, info
        ):
            return False
        return True

    # ---- people ----
    def _author(self, user_id: str) -> BasicExpertInfo:
        if user_id not in self._user_cache:
            try:
                u = self._require_client().get_user(user_id)
            except Exception:
                u = {}
            self._user_cache[user_id] = BasicExpertInfo(
                display_name=u.get("nickname") or u.get("username") or None,
                first_name=u.get("first_name") or None,
                last_name=u.get("last_name") or None,
                email=u.get("email") or None,
            )
        return self._user_cache[user_id]

    # ---- thread assembly ----
    def _thread_posts(self, root_id: str) -> list[dict]:
        thread = self._require_client().get_thread(root_id)
        posts = [p for p in thread.get("posts", {}).values() if _is_indexable_post(p)]
        posts.sort(key=lambda p: p["create_at"])
        return posts

    def _thread_to_doc(
        self, channel: ChannelInfo, root_id: str, posts: list[dict]
    ) -> Document:
        client = self._require_client()
        sections = [
            TextSection(
                text=f"{self._author(p['user_id']).get_semantic_name()}: {p['message']}",
                link=f"{client.base_url}/{channel.team_name}/pl/{p['id']}",
            )
            for p in posts
            if p.get("message")
        ]
        root = posts[0]
        root_msg = root.get("message", "")
        snippet = (root_msg[:50].rstrip() + "...") if len(root_msg) > 50 else root_msg
        sem_id = (
            f"{self._author(root['user_id']).get_semantic_name()} "
            f"in #{channel.display_name}: {snippet}"
        ).replace("\n", " ")
        return Document(
            id=_build_doc_id(channel.id, root_id),
            sections=sections,
            source=DocumentSource.MATTERMOST,
            semantic_identifier=sem_id,
            doc_updated_at=_ms_to_dt(max(p["update_at"] for p in posts)),
            primary_owners=[self._author(root["user_id"])],
            metadata={
                "Team": channel.team_display_name,
                "Channel": channel.display_name,
                "is_private": str(channel.type == "P"),
            },
            doc_metadata={
                "hierarchy": {
                    "source_path": [channel.team_display_name, channel.display_name],
                    "channel_id": channel.id,
                    "team_id": channel.team_id,
                }
            },
            parent_hierarchy_raw_node_id=channel.id,
            external_access=self._current_channel_access,
        )

    def _channel_hierarchy_node(self, channel: ChannelInfo) -> HierarchyNode:
        client = self._require_client()
        return HierarchyNode(
            raw_node_id=channel.id,
            raw_parent_id=None,
            display_name=f"#{channel.display_name}",
            link=f"{client.base_url}/{channel.team_name}/channels/{channel.name}",
            node_type=HierarchyNodeType.CHANNEL,
            external_access=self._current_channel_access,
        )

    def _walk_channel_roots(self, channel_id: str):
        """Yield each thread root_id for a whole channel (newest -> oldest)."""
        client = self._require_client()
        seen: set[str] = set()
        before: str | None = None
        while True:
            pl = client.get_channel_posts(channel_id, before=before)
            order = pl.get("order", [])
            if not order:
                return
            for pid in order:
                post = pl["posts"][pid]
                if not _is_indexable_post(post):
                    continue
                root_id = post.get("root_id") or post["id"]
                if root_id in seen:
                    continue
                seen.add(root_id)
                yield root_id
            before = pl.get("prev_post_id") or ""
            if not before:
                return

    # ---- checkpointed indexing (mirrors SlackConnector._load_from_checkpoint) ----
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
        checkpoint: MattermostCheckpoint,
    ) -> CheckpointOutput[MattermostCheckpoint]:
        self._require_client()
        checkpoint = copy.deepcopy(checkpoint)
        start_ms = int(start * 1000) if start else 0
        self._current_channel_access = checkpoint.current_channel_access

        # Step 1: first call -> enumerate channels, store ids + first channel, return.
        if checkpoint.channel_ids is None:
            channels = self._enumerate_channels()
            self._channel_by_id = {c.id: c for c in channels}
            checkpoint.channel_ids = [c.id for c in channels]
            checkpoint.current_channel = channels[0] if channels else None
            checkpoint.has_more = checkpoint.current_channel is not None
            return checkpoint

        channel = checkpoint.current_channel
        if channel is None:
            checkpoint.has_more = False
            return checkpoint

        # rebuild id->info map after a resume on a fresh connector instance
        if not self._channel_by_id:
            self._channel_by_id = {c.id: c for c in self._enumerate_channels()}

        # Step 2: process exactly one page of the current channel, then checkpoint.
        try:
            cursor = checkpoint.channel_completion_map.get(channel.id)
            if cursor is None:  # first visit -> emit the channel's hierarchy node
                yield self._channel_hierarchy_node(channel)

            pl = self._require_client().get_channel_posts(channel.id, before=cursor)
            order = pl.get("order", [])
            seen = set(checkpoint.seen_root_ids)
            reached_start = False
            for pid in order:  # newest -> oldest
                post = pl["posts"][pid]
                if post["create_at"] < start_ms:
                    reached_start = True
                    continue
                if not _is_indexable_post(post):
                    continue
                root_id = post.get("root_id") or post["id"]
                if root_id in seen:
                    continue
                seen.add(root_id)
                thread = self._thread_posts(root_id)
                if thread:
                    yield self._thread_to_doc(channel, root_id, thread)

            checkpoint.seen_root_ids = list(seen)
            checkpoint.channel_completion_map[channel.id] = (
                order[-1] if order else (cursor or "")
            )
            more_in_channel = bool(pl.get("prev_post_id")) and not reached_start
            if not more_in_channel:
                next_id = next(
                    (
                        cid
                        for cid in checkpoint.channel_ids
                        if cid not in checkpoint.channel_completion_map
                    ),
                    None,
                )
                checkpoint.current_channel = (
                    self._channel_by_id.get(next_id) if next_id else None
                )
            checkpoint.has_more = checkpoint.current_channel is not None
        except Exception as e:
            logger.exception("Error processing Mattermost channel %s", channel.id)
            yield ConnectorFailure(
                failed_entity=EntityFailure(entity_id=channel.id),
                failure_message=str(e),
                exception=e,
            )

        return checkpoint

    def build_dummy_checkpoint(self) -> MattermostCheckpoint:
        return MattermostCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> MattermostCheckpoint:
        return MattermostCheckpoint.model_validate_json(checkpoint_json)

    # ---- slim docs (deletion detection / pruning) ----
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        self._require_client()
        for channel in self._enumerate_channels():
            slim = [
                SlimDocument(id=_build_doc_id(channel.id, root_id))
                for root_id in self._walk_channel_roots(channel.id)
            ]
            if slim:
                yield slim
            if callback:
                callback.progress("mattermost_slim", len(slim))

    # ---- validation ----
    def validate_connector_settings(self) -> None:
        if self.channel_regex_enabled:
            for pat in self.channels + self.exclude_channels:
                try:
                    re.compile(pat)
                except re.error as e:
                    raise ConnectorValidationError(
                        f"Invalid channel regex '{pat}': {e}"
                    )
        client = self._require_client()
        try:
            client.get_me()
            client.get_my_teams()
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            self._raise_for_status(code, str(e))
        except Exception as e:
            # client raises MattermostClientError with a status_code attribute
            code = getattr(e, "status_code", None)
            if isinstance(code, int):
                self._raise_for_status(code, str(e))
            raise ConnectorValidationError(
                f"Could not reach Mattermost server: {e}"
            )

    @staticmethod
    def _raise_for_status(code: int, message: str) -> None:
        if code in (401, 403) and "token" in message.lower():
            raise CredentialExpiredError("Invalid or expired Mattermost token.")
        if code == 401:
            raise CredentialExpiredError("Invalid or expired Mattermost token.")
        if code == 403:
            raise InsufficientPermissionsError(
                "Token lacks permission to list teams/channels."
            )
        raise UnexpectedValidationError(f"Mattermost API error {code}: {message}")


if __name__ == "__main__":
    # Local smoke test (no Onyx stack needed):
    #   MATTERMOST_BASE_URL=https://your.mm  MATTERMOST_TOKEN=xxxx \
    #   [MATTERMOST_TEAM=teamname] python -m onyx.connectors.mattermost.connector
    import os
    import time

    connector = MattermostConnector(
        teams=[os.environ["MATTERMOST_TEAM"]]
        if os.environ.get("MATTERMOST_TEAM")
        else None
    )
    connector.load_credentials(
        {
            "mattermost_base_url": os.environ["MATTERMOST_BASE_URL"],
            "mattermost_access_token": os.environ["MATTERMOST_TOKEN"],
        }
    )
    cp = connector.build_dummy_checkpoint()
    emitted = 0
    now = time.time()
    while cp.has_more:
        gen = connector.load_from_checkpoint(0, now, cp)
        try:
            while True:
                item = next(gen)
                label = getattr(item, "semantic_identifier", None) or getattr(
                    item, "id", type(item).__name__
                )
                print(f"[{type(item).__name__}] {label}")
                emitted += 1
        except StopIteration as stop:
            cp = stop.value
    print(f"--- done; emitted {emitted} items ---")
