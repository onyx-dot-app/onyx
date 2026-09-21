import copy
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from hashlib import sha256
from itertools import chain
from typing import Any
from urllib.parse import urlsplit

import msal
import requests
from office365.graph_client import GraphClient
from office365.runtime.client_request_exception import ClientRequestException
from office365.runtime.http.request_options import RequestOptions
from office365.runtime.queries.client_query import ClientQuery
from office365.sharepoint.client_context import ClientContext
from office365.teams.channels.channel import Channel
from office365.teams.team import Team
from pydantic import BaseModel

from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.app_configs import TEAMS_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD
from onyx.configs.constants import DocumentSource, FileOrigin
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.microsoft_utils.drive_items import (
    DriveItemContentError,
    DriveItemData,
    SizeCapExceeded,
    download_graph_url_with_cap,
    extract_drive_item_content,
    iter_drive_items_paged,
)
from onyx.connectors.microsoft_utils.graph_auth import (
    MicrosoftAuthMethod,
    acquire_graph_token,
    acquire_token_for_rest,
    build_msal_app,
)
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient
from onyx.connectors.microsoft_utils.graph_env import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
    resolve_microsoft_environment,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
    ImageSection,
    SlimDocument,
    TextSection,
)
from onyx.connectors.sharepoint.connector_utils import (
    SharepointPermissionCache,
    get_sharepoint_external_access,
)
from onyx.connectors.teams.models import ChannelRef, Message
from onyx.connectors.teams.utils import (
    ChannelFilesUnavailable,
    GraphRetriesExhausted,
    execute_query_with_retry,
    fetch_channel_files_folder,
    fetch_channel_readers,
    fetch_drive_library,
    fetch_message_page,
    fetch_messages,
    fetch_replies,
    hosted_content_urls,
    message_delta_url,
)
from onyx.file_processing.file_types import OnyxMimeTypes
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()

_SLIM_DOC_BATCH_SIZE = 5000

# Rebuilt on the SharePoint connector's schedule, a hedge against a cached
# REST token outliving its hour.
_REST_CTX_MAX_AGE_S = 30 * 60

# Channel files are documents of their own. The prefix keeps them apart from a
# SharePoint connector indexing the same library, which uses the bare item id.
FILE_DOCUMENT_ID_PREFIX = "teams-file:"

# Each pasted image costs a download now and a vision-model call at indexing,
# so a thread stops well past what a working conversation holds.
_MAX_IMAGES_PER_THREAD = 100

# What a thread pasted and the document does not carry, so a reader who sees
# fewer images than the conversation had can tell why.
IMAGES_NOT_INDEXED = "images_not_indexed"

CREDENTIAL_AUTH_METHOD = "authentication_method"
CREDENTIAL_PRIVATE_KEY = "teams_private_key"
CREDENTIAL_CERTIFICATE_PASSWORD = "teams_certificate_password"


def file_document_id(item_id: str) -> str:
    return f"{FILE_DOCUMENT_ID_PREFIX}{item_id}"


class TeamsCheckpoint(ConnectorCheckpoint):
    # None until the teams are listed.
    todo_team_ids: list[str] | None = None
    todo_channels: list[ChannelRef] = []
    # A step walks one page of one channel, so a resumed attempt loses at most
    # a page instead of a whole team. No page url means the channel's first page.
    current_channel: ChannelRef | None = None
    next_messages_url: str | None = None


class TeamsConnector(
    CheckpointedConnectorWithPermSync[TeamsCheckpoint],
    SlimConnector,
    SlimConnectorWithPermSync,
):
    MAX_WORKERS = 10

    def __init__(
        self,
        # TODO: (chris) move from "Display Names" to IDs, since display names
        # are not necessarily guaranteed to be unique
        teams: list[str] | None = None,
        max_workers: int = MAX_WORKERS,
        authority_host: str = DEFAULT_AUTHORITY_HOST,
        graph_api_host: str = DEFAULT_GRAPH_API_HOST,
        # Off by default: a channel file's readers come from SharePoint REST,
        # which needs a certificate credential and a sites grant.
        include_attachments: bool = False,
        # Off by default: every pasted image is a download and a vision call.
        include_inline_images: bool = False,
    ) -> None:
        if teams is None:
            teams = []
        self.graph_client: GraphClient | None = None
        self.msal_app: msal.ConfidentialClientApplication | None = None
        self._acquire_token: Callable[[], dict[str, Any]] | None = None
        self._auth_method = MicrosoftAuthMethod.CLIENT_SECRET
        self.max_workers = max_workers
        self.requested_team_list: list[str] = teams
        self.include_attachments = include_attachments
        self.include_inline_images = include_inline_images
        # Granted by the factory from the image analysis setting.
        self.allow_images = False
        # Channels walked again from their first page in this attempt: a saved
        # page url Graph rejects recovers once per attempt and can never loop.
        self._restarted_channel_ids: set[str] = set()
        # The current channel's readers and library, read once per channel per
        # attempt. The cache dies with the process, so a resumed attempt re-reads.
        self._channel_state: dict[str, _ChannelState] = {}
        # One REST context per channel site, rebuilt after _REST_CTX_MAX_AGE_S.
        self._rest_contexts: dict[str, tuple[ClientContext, float]] = {}
        # Group expansions SharePoint resolves, shared across files.
        self._permission_cache = SharepointPermissionCache()

        resolved_env = resolve_microsoft_environment(graph_api_host, authority_host)
        self._azure_environment = resolved_env.environment
        self.authority_host = resolved_env.authority_host
        self.graph_api_host = resolved_env.graph_host
        self.sharepoint_domain_suffix = resolved_env.sharepoint_domain_suffix

    # impls for BaseConnector

    def set_allow_images(self, value: bool) -> None:
        self.allow_images = value

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._auth_method = MicrosoftAuthMethod.parse(
            credentials.get(CREDENTIAL_AUTH_METHOD)
        )
        self.msal_app = build_msal_app(
            client_id=credentials["teams_client_id"],
            directory_id=credentials["teams_directory_id"],
            authority_host=self.authority_host,
            auth_method=self._auth_method,
            # A client-secret credential must carry its secret. The certificate
            # method carries a key instead, so neither key is always present.
            client_secret=(
                credentials["teams_client_secret"]
                if self._auth_method is MicrosoftAuthMethod.CLIENT_SECRET
                else credentials.get("teams_client_secret")
            ),
            private_key_b64=credentials.get(CREDENTIAL_PRIVATE_KEY),
            certificate_password=credentials.get(CREDENTIAL_CERTIFICATE_PASSWORD),
        ).app

        def _acquire_token_func() -> dict[str, Any]:
            """
            Acquire token via MSAL
            """
            if self.msal_app is None:
                raise RuntimeError("MSAL app is not initialized")

            token = acquire_graph_token(self.msal_app, self.graph_api_host)

            if not isinstance(token, dict):
                raise RuntimeError("`token` instance must be of type dict")

            return token

        self.graph_client = GraphClient(
            _acquire_token_func, environment=self._azure_environment
        )
        # File downloads stream outside the SDK and carry the token themselves.
        self._acquire_token = _acquire_token_func
        return None

    def validate_connector_settings(self) -> None:
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Teams credentials not loaded.")

        # Check if any requested teams have special characters that need client-side filtering
        has_special_chars = _has_odata_incompatible_chars(self.requested_team_list)
        if has_special_chars:
            logger.info(
                "Some requested team names contain special characters (&, (, )) that require "
                "client-side filtering during data retrieval."
            )

        # Minimal validation: just check if we can access the teams endpoint
        timeout = 10  # Short timeout for basic validation

        try:
            # For validation, do a lightweight check instead of full team search
            logger.info(
                "Requested team count: %s, Has special chars: %s",
                len(self.requested_team_list) if self.requested_team_list else 0,
                has_special_chars,
            )

            # The attachments probe picks a channel from this listing.
            validation_query = self.graph_client.teams.get().top(
                50 if self.include_attachments else 1
            )
            run_with_timeout(
                timeout=timeout,
                func=lambda: validation_query.execute_query(),
            )

            logger.info(
                "Teams validation successful - Access to teams endpoint confirmed"
            )

        except TimeoutError as e:
            raise ConnectorValidationError(
                f"Timeout while validating Teams access (waited {timeout}s). "
                f"This may indicate network issues or authentication problems. "
                f"Error: {e}"
            )

        except ClientRequestException as e:
            if not e.response:
                raise RuntimeError(f"No response provided in error; {e=}")
            status_code = e.response.status_code
            if status_code == 401:
                raise CredentialExpiredError(
                    "Invalid or expired Microsoft Teams credentials (401 Unauthorized)."
                )
            elif status_code == 403:
                raise InsufficientPermissionsError(
                    "Your app lacks sufficient permissions to read Teams (403 Forbidden)."
                )
            raise UnexpectedValidationError(f"Unexpected error retrieving teams: {e}")

        except Exception as e:
            error_str = str(e).lower()
            if (
                "unauthorized" in error_str
                or "401" in error_str
                or "invalid_grant" in error_str
            ):
                raise CredentialExpiredError(
                    "Invalid or expired Microsoft Teams credentials."
                )
            elif "forbidden" in error_str or "403" in error_str:
                raise InsufficientPermissionsError(
                    "App lacks required permissions to read from Microsoft Teams."
                )
            raise ConnectorValidationError(
                f"Unexpected error during Teams validation: {e}"
            )

        if self.include_attachments:
            if not self._auth_method.supports_sharepoint_rest:
                raise ConnectorValidationError(
                    "Include Attachments needs certificate authentication: the "
                    "readers of a channel file are read from SharePoint, which "
                    "refuses app-only tokens from a client secret."
                )
            self._validate_attachment_access(list(validation_query))

    def _validate_attachment_access(self, tenant_teams: list[Team]) -> None:
        """Channel files need a sites grant the Teams permissions do not cover,
        so each validation opens the first channel found: its library through
        Graph and its site through SharePoint REST. Configured teams first,
        else the tenant teams already listed."""
        assert self.graph_client is not None
        try:
            teams = (
                _collect_all_teams(
                    graph_client=self.graph_client, requested=self.requested_team_list
                )
                if self.requested_team_list
                else tenant_teams
            )
            for team in teams:
                channels = _collect_all_channels_from_team(team=team)
                if not channels:
                    continue
                library = self._channel_library(_channel_ref(team.id, channels[0]))
                self._probe_sharepoint_rest(library.site_url)
                return
            # Every team has a General channel, so this is a listing oddity, not
            # a verified grant. Reported without marking the connector invalid.
            raise UnexpectedValidationError(
                "Could not find a channel to check the files grant on. Configure "
                "the teams to index, or retry once the tenant lists a channel."
            )
        except requests.HTTPError as e:
            if _status(e) in (401, 403):
                raise InsufficientPermissionsError(
                    "Include Attachments needs read access to the channel files on "
                    f"Graph, through {_GRANT_BY_CALL['files folder']} "
                    f"({_status(e)} on a channel's files)."
                )
            raise UnexpectedValidationError(
                f"Could not read a channel's files folder: {e}"
            )
        # Outages and MSAL token errors (a ValueError from the REST token) land
        # here: this error type keeps the pair active so the next attempt retries.
        except (
            ChannelFilesUnavailable,
            GraphRetriesExhausted,
            # Covers the SharePoint SDK's ClientRequestException, its subclass.
            requests.RequestException,
            ValueError,
        ) as e:
            raise UnexpectedValidationError(
                f"Could not list a channel or read its files folder: {e}"
            )

    def _probe_sharepoint_rest(self, site_url: str) -> None:
        """A role assignments read on the channel's site, the kind indexing makes
        for each file's readers. A read grant opens the site over REST and is
        still refused here, which Graph alone would never show."""
        assert self.msal_app is not None
        token = acquire_token_for_rest(
            self.msal_app, _tenant_domain(site_url), self.sharepoint_domain_suffix
        )
        response = requests.get(
            f"{site_url.rstrip('/')}/_api/web/roleassignments?$top=1",
            headers={
                "Authorization": f"Bearer {token.accessToken}",
                "Accept": "application/json",
            },
            timeout=10,
        )
        if response.status_code in (401, 403):
            raise InsufficientPermissionsError(
                "Include Attachments reads each file's readers from SharePoint, "
                "which needs Sites.FullControl.All on the SharePoint API. With "
                "Sites.Selected, grant the app full control on each channel site "
                f"({response.status_code} on a channel site's role assignments)."
            )
        response.raise_for_status()

    # impls for CheckpointedConnector

    def build_dummy_checkpoint(self) -> TeamsCheckpoint:
        return TeamsCheckpoint(
            has_more=True,
        )

    def validate_checkpoint_json(self, checkpoint_json: str) -> TeamsCheckpoint:
        return TeamsCheckpoint.model_validate_json(checkpoint_json)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
        checkpoint: TeamsCheckpoint,
    ) -> CheckpointOutput[TeamsCheckpoint]:
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Teams")

        checkpoint = copy.deepcopy(checkpoint)

        if checkpoint.todo_team_ids is None:
            teams = _collect_all_teams(
                graph_client=self.graph_client,
                requested=self.requested_team_list,
            )
            checkpoint.todo_team_ids = [team.id for team in teams if team.id]
        elif checkpoint.current_channel is None and not checkpoint.todo_channels:
            # A team is left, or has_more would have ended the walk.
            team_id = checkpoint.todo_team_ids.pop()
            team = _get_team_by_id(graph_client=self.graph_client, team_id=team_id)
            checkpoint.todo_channels = [
                _channel_ref(team_id, channel)
                for channel in _collect_all_channels_from_team(team=team)
            ]
            logger.info(
                "Listed %s channel(s) of team %s; %s team(s) left",
                len(checkpoint.todo_channels),
                team_id,
                len(checkpoint.todo_team_ids),
            )
        else:
            if checkpoint.current_channel is None:
                checkpoint.current_channel = checkpoint.todo_channels.pop()
            yield from _walk_channel_page(
                self.graph_client,
                checkpoint,
                start,
                self._restarted_channel_ids,
                self._channel_state,
                self._channel_library if self.include_attachments else None,
                self._index_channel_files if self.include_attachments else None,
                self._message_images if self.include_inline_images else None,
            )

        checkpoint.has_more = bool(
            checkpoint.current_channel
            or checkpoint.todo_channels
            or checkpoint.todo_team_ids
        )
        return checkpoint

    def _message_images(self, message: Message, limit: int) -> "_ImageHarvest":
        """Up to ``limit`` images pasted into one message, stored for the vision
        model. Nothing is downloaded while image analysis is off. A refused or
        oversized image is left out, anything else fails the attempt so the page
        is retried."""
        if not self.allow_images or not message.body.content:
            return _ImageHarvest(sections=[], downloads=0, missed=0)
        if self._acquire_token is None:
            raise ConnectorMissingCredentialError("Teams")
        graph_root = f"{self.graph_api_host}/v1.0"
        pasted = hosted_content_urls(message.body.content, graph_root)
        urls = pasted[:limit]
        missed = len(pasted) - len(urls)
        sections: list[ImageSection] = []
        for url in urls:
            try:
                data = download_graph_url_with_cap(
                    self._acquire_token()["access_token"],
                    url,
                    TEAMS_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD,
                    description=f"image of message {message.id}",
                )
            except SizeCapExceeded:
                logger.warning("Skipping an oversized image of message %s", message.id)
                missed += 1
                continue
            except requests.HTTPError as e:
                if not _is_permanent(e):
                    raise
                logger.warning("Skipping an image of message %s: %s", message.id, e)
                missed += 1
                continue
            section, _ = store_image_and_create_section(
                image_data=data,
                # Deterministic, so a re-index overwrites instead of piling up.
                file_id=f"teams-image-{sha256(url.encode()).hexdigest()[:32]}",
                display_name=f"Image in a message of {message.created_date_time:%Y-%m-%d}",
                link=message.web_url,
                media_type=_image_media_type(data),
                file_origin=FileOrigin.CONNECTOR,
            )
            sections.append(section)
        return _ImageHarvest(sections=sections, downloads=len(urls), missed=missed)

    def _channel_library(self, channel: ChannelRef) -> "_ChannelLibrary":
        """Where the channel's files live, resolved through Graph."""
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Teams")
        folder = fetch_channel_files_folder(
            self.graph_client, channel.team_id, channel.id
        )
        drive_name, site_url = fetch_drive_library(self.graph_client, folder.drive_id)
        return _ChannelLibrary(
            site_url=site_url,
            drive_id=folder.drive_id,
            drive_name=drive_name,
            folder_id=folder.id,
        )

    def _graph_api_client(self) -> GraphApiClient:
        if self._acquire_token is None:
            raise ConnectorMissingCredentialError("Teams")
        acquire_token = self._acquire_token
        return GraphApiClient(
            lambda: acquire_token()["access_token"], f"{self.graph_api_host}/v1.0"
        )

    def channel_site_urls(self) -> Iterator[str]:
        """The distinct SharePoint sites behind the configured teams' channels,
        for the group sync. A refused channel raises, as in the slim walk: the
        sync deletes the memberships of every group a partial listing misses."""
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Teams")
        seen: set[str] = set()
        teams = _collect_all_teams(
            graph_client=self.graph_client, requested=self.requested_team_list
        )
        for team in teams:
            if not team.id:
                continue
            for channel in _collect_all_channels_from_team(team=team):
                ref = _channel_ref(team.id, channel)
                with _channel_context(ref, "files folder"):
                    site_url = self._channel_library(ref).site_url
                if site_url not in seen:
                    seen.add(site_url)
                    yield site_url

    def rest_context(self, site_url: str) -> ClientContext:
        """SharePoint REST for a channel's site, the way the SharePoint connector
        opens it: one context per site, rebuilt once its token could be stale."""
        cached = self._rest_contexts.get(site_url)
        if cached and time.monotonic() - cached[1] <= _REST_CTX_MAX_AGE_S:
            return cached[0]
        if self.msal_app is None:
            raise ConnectorMissingCredentialError("Teams")
        msal_app = self.msal_app
        tenant_domain = _tenant_domain(site_url)
        suffix = self.sharepoint_domain_suffix
        context = ClientContext(site_url).with_access_token(
            lambda: acquire_token_for_rest(msal_app, tenant_domain, suffix)
        )
        self._rest_contexts[site_url] = (context, time.monotonic())
        return context

    def _file_access(
        self, library: "_ChannelLibrary", item: DriveItemData
    ) -> ExternalAccess:
        """The file's own readers from SharePoint, expanded through site and
        Entra groups. Empty without the enterprise permission code, as for
        SharePoint documents, so the pair's access type decides on those builds."""
        assert self.graph_client is not None
        access = get_sharepoint_external_access(
            ctx=self.rest_context(library.site_url),
            graph_client=self.graph_client,
            permission_cache=self._permission_cache,
            drive_item=item.to_sdk_driveitem(self.graph_client),
            drive_name=library.drive_name,
        )
        # The Teams group sync persists these groups under this source's prefix,
        # so the file's groups carry the same prefix or they would never match.
        return ExternalAccess(
            external_user_emails=access.external_user_emails,
            external_user_group_ids={
                build_ext_group_name_for_onyx(group_id, DocumentSource.TEAMS)
                for group_id in access.external_user_group_ids
            },
            is_public=access.is_public,
        )

    def _channel_files(
        self, library: "_ChannelLibrary", start: SecondsSinceUnixEpoch | None
    ) -> Iterator[DriveItemData]:
        """Every indexable file under the channel's folder, changed since
        ``start``. Both walks apply the same eligibility rule, so pruning removes
        a file that grew past the threshold instead of keeping its old text."""
        window_start = datetime.fromtimestamp(start, tz=timezone.utc) if start else None
        items = iter_drive_items_paged(
            self._graph_api_client(),
            library.drive_id,
            folder_id=library.folder_id,
            start=window_start,
        )
        return (item for item in items if _indexable_file(item))

    def _index_channel_files(
        self,
        channel: ChannelRef,
        library: "_ChannelLibrary",
        start: SecondsSinceUnixEpoch,
    ) -> Iterator[Document | ConnectorFailure]:
        for item in self._channel_files(library, start):
            yield self._file_document(channel, library, item)

    def _file_document(
        self, channel: ChannelRef, library: "_ChannelLibrary", item: DriveItemData
    ) -> Document | ConnectorFailure:
        """One document per channel file, carrying the file's own SharePoint
        readers so permission sync and pruning treat it like a message."""
        if self._acquire_token is None:
            raise ConnectorMissingCredentialError("Teams")
        try:
            content = extract_drive_item_content(
                item,
                size_threshold=TEAMS_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD,
                graph_api_base=f"{self.graph_api_host}/v1.0",
                access_token=self._acquire_token()["access_token"],
                raw_file_callback=self.raw_file_callback,
            )
        except DriveItemContentError as e:
            return ConnectorFailure(
                failed_document=DocumentFailure(
                    document_id=file_document_id(item.id), document_link=item.web_url
                ),
                failure_message=f"Teams file '{item.name}' in {channel.display_name}: {e}",
                exception=e,
            )
        sections = content.sections if content is not None else []
        if not sections:
            # The slim walk lists this file, so an empty or unreadable one must
            # still replace its document or its old text would outlive it.
            sections = [TextSection(link=item.web_url, text=item.name)]
        owners = (
            [
                BasicExpertInfo(
                    display_name=item.last_modified_by_display_name,
                    email=item.last_modified_by_email,
                )
            ]
            if item.last_modified_by_email
            else []
        )
        return Document(
            id=file_document_id(item.id),
            sections=sections,
            source=DocumentSource.TEAMS,
            semantic_identifier=item.name,
            title=item.name,
            doc_created_at=item.created_datetime,
            doc_updated_at=item.last_modified_datetime,
            primary_owners=owners,
            metadata={"channel": channel.display_name},
            external_access=self._file_access(library, item),
            file_id=content.staged_file_id if content is not None else None,
        )

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: TeamsCheckpoint,
    ) -> CheckpointOutput[TeamsCheckpoint]:
        # Every document already carries its channel's access list, so the plain
        # walk is the permission walk.
        return self.load_from_checkpoint(start, end, checkpoint)

    # impls for SlimConnectorWithPermSync

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Ids alone, for pruning. Readers cost a members call per channel and a
        SharePoint call per file, and pruning throws them away."""
        yield from self._slim_docs(start, callback, with_readers=False)

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        yield from self._slim_docs(start, callback, with_readers=True)

    def _slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None,
        callback: IndexingHeartbeatInterface | None,
        with_readers: bool,
    ) -> GenerateSlimDocumentOutput:
        start = start or 0

        teams = _collect_all_teams(
            graph_client=self.graph_client,  # ty: ignore[invalid-argument-type]
            requested=self.requested_team_list,
        )

        for team in teams:
            if not team.id:
                logger.warning(
                    "Expected a team with an id, instead got no id: team=%r", team
                )
                continue

            channels = _collect_all_channels_from_team(
                team=team,
            )

            for channel in channels:
                if not channel.id:
                    logger.warning(
                        "Expected a channel with an id, instead got no id: channel=%r",
                        channel,
                    )
                    continue

                ref = _channel_ref(team.id, channel)
                external_access: ExternalAccess | None = None
                if with_readers:
                    # A refused members call raises: a listing without its
                    # readers would let permission sync act on a partial picture.
                    with _channel_context(ref, "members"):
                        _, external_access = fetch_channel_readers(
                            graph_client=self.graph_client,  # ty: ignore[invalid-argument-type]
                            team_id=ref.team_id,
                            channel_id=ref.id,
                        )

                messages = fetch_messages(
                    graph_client=self.graph_client,  # ty: ignore[invalid-argument-type]
                    team_id=team.id,
                    channel_id=channel.id,
                    start=start,
                )

                slim_docs: Iterator[SlimDocument] = (
                    SlimDocument(
                        id=message.id,
                        external_access=external_access,
                        # NOTE: doc_created_at population not yet verified against live data
                        doc_created_at=message.created_date_time,
                    )
                    # The indexing walk skips these roots, so listing them here
                    # would keep their stale documents out of pruning.
                    for message in messages
                    if message.is_indexable
                )
                if self.include_attachments:
                    slim_docs = chain(
                        slim_docs, self._slim_channel_files(ref, with_readers)
                    )

                slim_doc_buffer: list[SlimDocument | HierarchyNode] = []
                for slim_doc in slim_docs:
                    slim_doc_buffer.append(slim_doc)
                    if len(slim_doc_buffer) >= _SLIM_DOC_BATCH_SIZE:
                        if callback:
                            if callback.should_stop():
                                raise RuntimeError(
                                    "retrieve_all_slim_docs_perm_sync: Stop signal detected"
                                )
                            callback.progress("retrieve_all_slim_docs_perm_sync", 1)
                        yield slim_doc_buffer
                        slim_doc_buffer = []

                # Flush any remaining slim documents collected for this channel
                if slim_doc_buffer:
                    yield slim_doc_buffer

    def _slim_channel_files(
        self, channel: ChannelRef, with_readers: bool
    ) -> Iterator[SlimDocument]:
        """Channel files with the ids the indexing walk writes, and with the
        readers SharePoint grants them when the caller needs those. A refused
        folder or site raises, as a refused members call does: a channel missing
        from this listing would have its documents pruned."""
        with _channel_context(channel, "files"):
            library = self._channel_library(channel)
            for item in self._channel_files(library, start=None):
                yield SlimDocument(
                    id=file_document_id(item.id),
                    external_access=(
                        self._file_access(library, item) if with_readers else None
                    ),
                    doc_created_at=item.created_datetime,
                )


def _escape_odata_string(name: str) -> str:
    """Escape special characters for OData string literals.

    Uses proper OData v4 string literal escaping:
    - Single quotes: ' becomes ''
    - Other characters are handled by using contains() instead of eq for problematic cases
    """
    # Escape single quotes for OData syntax (replace ' with '')
    escaped = name.replace("'", "''")
    return escaped


def _has_odata_incompatible_chars(team_names: list[str] | None) -> bool:
    """Check if any team name contains characters that break Microsoft Graph OData filters.

    The Microsoft Graph Teams API has limited OData support. Characters like
    &, (, and ) cause parsing errors and require client-side filtering instead.
    """
    if not team_names:
        return False
    return any(char in name for name in team_names for char in ["&", "(", ")"])


def _can_use_odata_filter(
    team_names: list[str] | None,
) -> tuple[bool, list[str], list[str]]:
    """Determine which teams can use OData filtering vs client-side filtering.

    Microsoft Graph /teams endpoint OData limitations:
    - Only supports basic 'eq' operators in filters
    - No 'contains', 'startswith', or other advanced operators
    - Special characters (&, (, )) break OData parsing

    Returns:
        tuple: (can_use_odata, safe_names, problematic_names)
    """
    if not team_names:
        return False, [], []

    safe_names = []
    problematic_names = []

    for name in team_names:
        if any(char in name for char in ["&", "(", ")"]):
            problematic_names.append(name)
        else:
            safe_names.append(name)

    return bool(safe_names), safe_names, problematic_names


def _build_simple_odata_filter(safe_names: list[str]) -> str | None:
    """Build simple OData filter using only 'eq' operators for safe names."""
    if not safe_names:
        return None

    filter_parts = []
    for name in safe_names:
        escaped_name = _escape_odata_string(name)
        filter_parts.append(f"displayName eq '{escaped_name}'")

    return " or ".join(filter_parts)


def _sender_name(message: Message) -> str:
    """Bots and apps post without a user, so the sender is not always known."""
    if message.from_ and message.from_.user and message.from_.user.display_name:
        return message.from_.user.display_name
    return "Unknown User"


def _construct_semantic_identifier(channel: ChannelRef, top_message: Message) -> str:
    top_message_user_name = _sender_name(top_message)
    top_message_content = top_message.body.content or ""
    top_message_subject = top_message.subject or "Unknown Subject"
    channel_name = channel.display_name

    try:
        snippet = parse_html_page_basic(top_message_content.rstrip())
        snippet = snippet[:50] + "..." if len(snippet) > 50 else snippet

    except Exception:
        logger.exception(
            "Error parsing snippet for message %s with url %s",
            top_message.id,
            top_message.web_url,
        )
        snippet = ""

    semantic_identifier = (
        f"{top_message_user_name} in {channel_name} about {top_message_subject}"
    )
    if snippet:
        semantic_identifier += f": {snippet}"

    return semantic_identifier


def _message_header(message: Message) -> str:
    return (
        f"From: {_sender_name(message)}\nDate: {message.created_date_time.isoformat()}"
    )


def _message_section(message: Message) -> TextSection | None:
    """One section per message, so a hit cites the message that said it."""
    body = parse_html_page_basic(message.body.content) if message.body.content else ""
    body = body.strip()
    if not body:
        return None
    return TextSection(
        link=message.web_url, text=f"{_message_header(message)}\n\n{body}"
    )


def _modified_at(message: Message) -> datetime:
    return message.last_modified_date_time or message.created_date_time


# The images of one message within a budget, and the downloads charged to it.
_MessageImages = Callable[[Message, int], "_ImageHarvest"]


class _ImageHarvest(BaseModel):
    """What one message gave the thread: its image sections, the downloads they
    cost the thread budget, and the images left out of the document."""

    sections: list[ImageSection]
    downloads: int
    missed: int


def _image_media_type(data: bytes) -> str:
    """Graph names no trustworthy type on the hosted content route, so the type
    is read off the bytes."""
    try:
        return get_image_type_from_bytes(data)
    except ValueError:
        return "application/octet-stream"


def _convert_thread_to_document(
    channel: ChannelRef,
    root: Message,
    replies: list[Message],
    expert_infos: list[BasicExpertInfo],
    external_access: ExternalAccess,
    message_images: _MessageImages | None,
) -> Document:
    """A thread (the root message and its replies) is one document, oldest
    first, each message's text followed by the images pasted into it."""
    messages = sorted([root, *replies], key=lambda m: m.created_date_time)
    sections: list[TextSection | ImageSection] = []
    images_left = _MAX_IMAGES_PER_THREAD
    missed_images = 0
    for message in messages:
        if not message.is_indexable:
            continue
        if section := _message_section(message):
            sections.append(section)
        if message_images is None:
            continue
        harvest = message_images(message, images_left)
        images_left -= harvest.downloads
        missed_images += harvest.missed
        sections.extend(harvest.sections)
    # The slim walk lists every indexable root, so a thread left with no text
    # and no image must still replace its document or the old text would
    # outlive it.
    if not sections:
        sections = [TextSection(link=root.web_url, text=_message_header(root))]

    return Document(
        id=root.id,
        sections=sections,
        source=DocumentSource.TEAMS,
        semantic_identifier=_construct_semantic_identifier(channel, root),
        title="",  # teams threads don't really have a "title"
        doc_created_at=root.created_date_time,
        # Indexing skips a document whose update time has not moved, and an
        # edit or a deleted reply moves a message's modified time, not its creation.
        doc_updated_at=max(_modified_at(message) for message in messages),
        primary_owners=expert_infos,
        metadata=({IMAGES_NOT_INDEXED: str(missed_images)} if missed_images else {}),
        external_access=external_access,
    )


def _update_request_url(request: RequestOptions, next_url: str) -> None:
    request.url = next_url


def _add_prefer_header(request: RequestOptions) -> None:
    """Add Prefer header to work around Microsoft Graph API ampersand bug.
    See: https://developer.microsoft.com/en-us/graph/known-issues/?search=18185
    """
    if not hasattr(request, "headers") or request.headers is None:
        request.headers = {}
    # Add header to handle properly encoded ampersands in filters
    request.headers["Prefer"] = "legacySearch=false"


def _team_page_query(
    graph_client: GraphClient, odata_filter: str | None, next_url: str | None
) -> ClientQuery:
    """One page of the teams listing: filtered by name, or 50 plain rows."""
    if odata_filter is None:
        query = graph_client.teams.get().top(50)
    else:
        # Graph accepts only 'eq' operators in this filter.
        query = graph_client.teams.get().filter(odata_filter)
    # Works around a Graph issue with ampersands in filters.
    query.before_execute(lambda req: _add_prefer_header(request=req))
    if next_url:
        query.before_execute(partial(_update_request_url, next_url=next_url))
    return query


def _collect_all_teams(
    graph_client: GraphClient,
    requested: list[str] | None = None,
) -> list[Team]:
    """Collect teams from Microsoft Graph using appropriate filtering strategy.

    For teams with special characters (&, (, )), uses client-side filtering
    with paginated search. For teams without special characters, uses efficient
    OData server-side filtering.

    Args:
        graph_client: Authenticated Microsoft Graph client
        requested: List of team names to find, or None for all teams

    Returns:
        List of Team objects matching the requested names
    """
    teams: list[Team] = []
    next_url: str | None = None

    # No names means every team, which is what the connector form promises, so
    # the plain listing is paged to its end with no name to stop on.
    every_team = not requested
    _, safe_names, problematic_names = _can_use_odata_filter(requested)

    # Determine filtering strategy based on Microsoft Graph limitations
    if every_team:
        logger.info("No teams configured, listing every team")
        use_client_side_filtering = True
        odata_filter = None
    elif problematic_names and not safe_names:
        # ALL requested teams have special characters - cannot use OData filtering
        logger.info(
            "All requested team names contain special characters (&, (, )) which require client-side filtering. Using basic /teams endpoint with pagination. Teams: %s",
            problematic_names,
        )
        # Use unfiltered query with pagination limit to avoid fetching too many teams
        use_client_side_filtering = True
        odata_filter = None
    elif problematic_names and safe_names:
        # Mixed scenario - need to fetch more teams to find the problematic ones
        logger.info(
            "Mixed team types: will use client-side filtering for all. Safe names: %s, Special char names: %s",
            safe_names,
            problematic_names,
        )
        use_client_side_filtering = True
        odata_filter = None
    else:
        # All names are safe - use OData filtering
        logger.info("Using OData filtering for all requested teams: %s", safe_names)
        use_client_side_filtering = False
        odata_filter = _build_simple_odata_filter(safe_names)

    # Track pagination to avoid fetching too many teams for client-side filtering
    max_pages = 200
    page_count = 0

    while True:
        try:
            team_collection = execute_query_with_retry(
                partial(
                    _team_page_query,
                    graph_client,
                    None if use_client_side_filtering else odata_filter,
                    next_url,
                ),
                method_name="_collect_all_teams",
            )
        except (ClientRequestException, ValueError) as e:
            # If OData filter fails, fall back to client-side filtering
            if not use_client_side_filtering and odata_filter:
                logger.warning(
                    "OData filter failed: %s. Falling back to client-side filtering.", e
                )
                use_client_side_filtering = True
                odata_filter = None
                teams = []
                next_url = None
                page_count = 0
                continue
            # If client-side approach also fails, re-raise
            logger.error("Teams query failed: %s", e)
            raise

        filtered_teams = (
            team
            for team in team_collection
            if _filter_team(team=team, requested=requested)
        )
        teams.extend(filtered_teams)

        # For client-side filtering, check if we found all requested teams or hit page limit
        if use_client_side_filtering and not every_team:
            page_count += 1
            found_team_names = {
                team.display_name for team in teams if team.display_name
            }
            requested_set = set(requested or [])

            # Log progress every 10 pages to avoid excessive logging
            if page_count % 10 == 0:
                logger.info(
                    "Searched %s pages, found %s matching teams so far",
                    page_count,
                    len(found_team_names),
                )

            # Stop if we found all requested teams or hit the page limit
            if requested_set.issubset(found_team_names):
                logger.info("Found all requested teams after %s pages", page_count)
                break
            elif page_count >= max_pages:
                logger.warning(
                    "Reached maximum page limit (%s) while searching for teams. Found: %s, Missing: %s",
                    max_pages,
                    found_team_names & requested_set,
                    requested_set - found_team_names,
                )
                break

        if not team_collection.has_next:
            break

        if not isinstance(team_collection._next_request_url, str):
            raise ValueError(
                f"The next request url field should be a string, instead got {type(team_collection._next_request_url)}"
            )
        # Listing every team has no name to stop on, so a page that points back
        # at itself would be read for ever.
        if team_collection._next_request_url == next_url:
            raise RuntimeError(f"Graph repeated a page of teams: {next_url}")

        next_url = team_collection._next_request_url

    return teams


def _normalize_team_name(name: str) -> str:
    """Normalize team name for flexible matching."""
    if not name:
        return ""
    # Convert to lowercase and strip whitespace for case-insensitive matching
    return name.lower().strip()


def _matches_requested_team(
    team_display_name: str, requested: list[str] | None
) -> bool:
    """Check if team display name matches any of the requested team names.

    Uses flexible matching to handle slight variations in team names.
    """
    if not requested or not team_display_name:
        return (
            not requested
        )  # If no teams requested, match all; if no name, don't match

    normalized_team_name = _normalize_team_name(team_display_name)

    for requested_name in requested:
        normalized_requested = _normalize_team_name(requested_name)

        # Exact match after normalization
        if normalized_team_name == normalized_requested:
            return True

        # Flexible matching - check if team name contains all significant words
        # This helps with slight variations in formatting
        team_words = set(normalized_team_name.split())
        requested_words = set(normalized_requested.split())

        # If the requested name has special characters, split on those too
        for char in ["&", "(", ")"]:
            if char in normalized_requested:
                # Split on special characters and add words
                parts = normalized_requested.replace(char, " ").split()
                requested_words.update(parts)

        # Remove very short words that aren't meaningful
        meaningful_requested_words = {
            word for word in requested_words if len(word) >= 3
        }

        # Check if team name contains most of the meaningful words
        if (
            meaningful_requested_words
            and len(meaningful_requested_words & team_words)
            >= len(meaningful_requested_words) * 0.7
        ):
            return True

    return False


def _filter_team(
    team: Team,
    requested: list[str] | None = None,
) -> bool:
    """
    Returns the true if:
        - Team is not expired / deleted
        - Team has a display-name and ID
        - Team display-name matches any of the requested teams (with flexible matching)

    Otherwise, returns false.
    """

    if not team.id or not team.display_name:
        return False

    if not _matches_requested_team(team.display_name, requested):
        return False

    props = team.properties

    expiration = props.get("expirationDateTime")
    deleted = props.get("deletedDateTime")

    # We just check for the existence of those two fields, not their actual dates.
    # This is because if these fields do exist, they have to have occurred in the past, thus making them already
    # expired / deleted.
    return not expiration and not deleted


def _get_team_by_id(
    graph_client: GraphClient,
    team_id: str,
) -> Team:
    team_collection = execute_query_with_retry(
        lambda: graph_client.teams.get().filter(f"id eq '{team_id}'").top(1),
        method_name="_get_team_by_id",
    )

    if not team_collection:
        raise ValueError(f"No team with {team_id=} was found")
    elif team_collection.has_next:
        # shouldn't happen, but catching it regardless
        raise RuntimeError(f"Multiple teams with {team_id=} were found")

    return team_collection[0]


def _collect_all_channels_from_team(
    team: Team,
) -> list[Channel]:
    if not team.id:
        raise RuntimeError(f"The {team=} has an empty `id` field")

    # `get_all` follows the collection's pages itself. The argument is needed
    # because of incorrect type definitions in the `office365` library.
    channel_collection = execute_query_with_retry(
        lambda: team.channels.get_all(page_loaded=lambda _: None),
        method_name="_collect_all_channels_from_team",
    )
    return [channel for channel in channel_collection if channel.id]


def _channel_ref(team_id: str, channel: Channel) -> ChannelRef:
    return ChannelRef(
        team_id=team_id,
        id=channel.id,
        display_name=channel.properties.get("displayName") or "Unknown",
    )


def _indexable_file(item: DriveItemData) -> bool:
    """Decided from listing metadata alone, the way extraction decides it, so
    the slim walk can apply the same rule without downloading anything."""
    if not item.mime_type or item.mime_type in OnyxMimeTypes.EXCLUDED_IMAGE_TYPES:
        return False
    return item.size is None or item.size <= TEAMS_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD


def _status(error: requests.RequestException) -> int | None:
    return error.response.status_code if error.response is not None else None


def _tenant_domain(site_url: str) -> str:
    """The tenant part of a SharePoint host: danswerai of danswerai.sharepoint.com."""
    return (urlsplit(site_url).hostname or "").split(".")[0]


def _is_permanent(error: requests.RequestException) -> bool:
    """A refusal or a missing resource stays that way, so it is recorded and the
    walk moves on. Anything else (expired token, exhausted retries) fails the
    attempt so the saved checkpoint is retried, not skipped for good."""
    return _status(error) in (403, 404)


def _rejects_saved_cursor(
    error: requests.HTTPError,
    checkpoint: TeamsCheckpoint,
    restarted_channel_ids: set[str],
) -> bool:
    """Graph answers a page url it no longer honors with 400 or 410 (measured
    for a tampered skip token). Retrying it would never progress, so the channel
    is walked again from its first page, once per attempt."""
    channel = checkpoint.current_channel
    return (
        channel is not None
        and checkpoint.next_messages_url is not None
        and channel.id not in restarted_channel_ids
        and _status(error) in (400, 410)
    )


@dataclass
class _ChannelLibrary:
    """Where a channel's files live: the SharePoint site, its document library
    and the channel's folder in it."""

    site_url: str
    drive_id: str
    drive_name: str
    folder_id: str


@dataclass
class _ChannelState:
    """What a channel's pages share and a resumed attempt must re-read."""

    expert_infos: list[BasicExpertInfo]
    external_access: ExternalAccess
    library: _ChannelLibrary | None


def _leave_channel(
    checkpoint: TeamsCheckpoint, state_cache: dict[str, _ChannelState]
) -> None:
    if checkpoint.current_channel is not None:
        state_cache.pop(checkpoint.current_channel.id, None)
    checkpoint.current_channel = None
    checkpoint.next_messages_url = None


@contextmanager
def _channel_context(channel: ChannelRef, call: str) -> Iterator[None]:
    """A refusal in here stops a walk whose partial listing would delete
    documents, so it becomes an error naming the channel, the call and the way
    out. A transient refusal passes through and the attempt retries it."""
    try:
        yield
    except (requests.HTTPError, ClientRequestException) as e:
        if not _is_permanent(e):
            raise
        raise ConnectorValidationError(
            f"{_channel_refusal(channel, call, e)} {_channel_remedy(call, e)}"
        ) from e


def _channel_refusal(
    channel: ChannelRef, call: str, error: requests.RequestException
) -> str:
    """Names the channel and the call, since a channel id alone sends the admin
    looking through Graph for the team and tab it belongs to."""
    return (
        f'The {call} of channel "{channel.display_name}" in team '
        f"{channel.team_id} answered {_status(error)}."
    )


# The calls whose grant this connector already names to the admin.
_GRANT_BY_CALL = {
    "files folder": "Files.Read.All or Sites.Read.All",
    "files": "Files.Read.All or Sites.Read.All",
}


def _channel_remedy(call: str, error: requests.RequestException) -> str:
    """404 is a channel that is gone or invisible to the app, 403 is a grant."""
    if _status(error) == 404:
        return "Leave the team out of the connector if the channel is gone."
    grant = _GRANT_BY_CALL.get(call, "the application permission that call needs")
    return f"Grant {grant}, or leave the team out of the connector."


def _channel_failure(
    channel: ChannelRef, call: str, error: Exception
) -> ConnectorFailure:
    """One channel recorded and skipped. Graph answered with a status for a
    refusal, and with a body this connector cannot use for anything else."""
    named = f'the {call} of channel "{channel.display_name}" in team {channel.team_id}'
    return ConnectorFailure(
        failed_entity=EntityFailure(entity_id=channel.id),
        failure_message=(
            _channel_refusal(channel, call, error)
            if isinstance(error, requests.RequestException)
            else f"Could not read {named}: {error}"
        ),
        exception=error,
    )


_IndexFiles = Callable[
    [ChannelRef, _ChannelLibrary, SecondsSinceUnixEpoch],
    Iterator[Document | ConnectorFailure],
]


def _walk_channel_page(
    graph_client: GraphClient,
    checkpoint: TeamsCheckpoint,
    start: SecondsSinceUnixEpoch,
    restarted_channel_ids: set[str],
    state_cache: dict[str, _ChannelState],
    open_library: Callable[[ChannelRef], _ChannelLibrary] | None,
    index_files: _IndexFiles | None,
    message_images: _MessageImages | None,
) -> Iterator[Document | ConnectorFailure]:
    """One page of the current channel's threads, and after the last page the
    channel's files. Moves the checkpoint to the next page, or off the channel
    when the page was its last or is refused."""
    channel = checkpoint.current_channel
    if channel is None:
        raise RuntimeError("No channel is being walked")

    # Readers and the library are never checkpointed, a saved copy would be
    # stale on resume. No readers is unsafe and no library means the files grant
    # the admin turned on is missing, so either refusal is one channel failure.
    no_files: ChannelFilesUnavailable | None = None
    try:
        state = state_cache.get(channel.id)
        if state is None:
            expert_infos, external_access = fetch_channel_readers(
                graph_client=graph_client,
                team_id=channel.team_id,
                channel_id=channel.id,
            )
            library = None
            if open_library:
                try:
                    library = open_library(channel)
                except ChannelFilesUnavailable as e:
                    # Graph describes no usable library for this channel. Its
                    # messages are still readable, so only the files are lost.
                    no_files = e
            state = _ChannelState(
                expert_infos=expert_infos,
                external_access=external_access,
                library=library,
            )
            state_cache[channel.id] = state
        expert_infos, external_access, library = (
            state.expert_infos,
            state.external_access,
            state.library,
        )
    except requests.HTTPError as e:
        if not _is_permanent(e):
            raise
        yield _channel_failure(channel, "members or files", e)
        _leave_channel(checkpoint, state_cache)
        return

    if no_files is not None:
        yield _channel_failure(channel, "files", no_files)

    try:
        roots, next_url = fetch_message_page(
            graph_client=graph_client,
            request_url=checkpoint.next_messages_url
            or message_delta_url(channel.team_id, channel.id, start),
        )
    except requests.HTTPError as e:
        if _rejects_saved_cursor(e, checkpoint, restarted_channel_ids):
            logger.warning(
                "Graph rejected the saved page of channel %s; walking it again "
                "from its first page",
                channel.id,
            )
            checkpoint.next_messages_url = None
            restarted_channel_ids.add(channel.id)
            return
        if not _is_permanent(e):
            raise
        yield _channel_failure(channel, "messages", e)
        _leave_channel(checkpoint, state_cache)
        return

    for root in roots:
        # A thread is its root message. A deleted or system root drops the
        # whole thread, which is what the slim walk lists for pruning too.
        if not root.is_indexable:
            continue
        try:
            replies = list(
                fetch_replies(
                    graph_client=graph_client,
                    team_id=channel.team_id,
                    channel_id=channel.id,
                    root_message_id=root.id,
                )
            )
        except requests.HTTPError as e:
            if not _is_permanent(e):
                raise
            yield ConnectorFailure(
                failed_entity=EntityFailure(entity_id=root.id),
                failure_message=f"Could not read the replies of {root.id} in channel {channel.id}",
                exception=e,
            )
            continue
        yield _convert_thread_to_document(
            channel=channel,
            root=root,
            replies=replies,
            expert_infos=expert_infos,
            external_access=external_access,
            message_images=message_images,
        )

    checkpoint.next_messages_url = next_url
    if next_url is not None:
        return
    # The files follow the last page of messages. A refused folder listing on
    # Graph or a refused site on SharePoint REST (the SDK's own exception) is
    # one recorded failure for the channel, anything else fails the attempt.
    if library is not None and index_files is not None:
        try:
            yield from index_files(channel, library, start)
        except (requests.HTTPError, ClientRequestException) as e:
            if not _is_permanent(e):
                raise
            yield _channel_failure(channel, "files", e)
    _leave_channel(checkpoint, state_cache)


if __name__ == "__main__":
    from tests.daily.connectors.utils import load_all_from_connector

    app_id = os.environ["TEAMS_APPLICATION_ID"]
    dir_id = os.environ["TEAMS_DIRECTORY_ID"]
    secret = os.environ["TEAMS_SECRET"]

    teams_env_var = os.environ.get("TEAMS", None)
    teams = teams_env_var.split(",") if teams_env_var else []

    teams_connector = TeamsConnector(teams=teams)
    teams_connector.load_credentials(
        {
            "teams_client_id": app_id,
            "teams_directory_id": dir_id,
            "teams_client_secret": secret,
        }
    )
    teams_connector.validate_connector_settings()

    for _slim_doc in teams_connector.retrieve_all_slim_docs_perm_sync():
        ...

    for doc in load_all_from_connector(
        connector=teams_connector,
        start=0.0,
        end=datetime.now(tz=timezone.utc).timestamp(),
    ).documents:
        print(doc)
