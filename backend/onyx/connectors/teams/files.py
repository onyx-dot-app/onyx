"""Channel files: each file in a channel's Files tab is a document of its own,
readable by the people SharePoint grants it to. A channel's files live in a
SharePoint document library, so its readers come from SharePoint REST."""

import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

import msal
import requests
from office365.sharepoint.client_context import ClientContext
from office365.teams.team import Team

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import TEAMS_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.microsoft_utils.drive_items import (
    DriveItemContentError,
    DriveItemData,
    extract_drive_item_content,
    iter_drive_items_paged,
)
from onyx.connectors.microsoft_utils.graph_auth import acquire_token_for_rest
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    SlimDocument,
    TextSection,
)
from onyx.connectors.sharepoint.connector_utils import (
    SharepointPermissionCache,
    get_sharepoint_external_access,
)
from onyx.connectors.teams import listing
from onyx.connectors.teams.models import ChannelRef
from onyx.connectors.teams.refusals import (
    GRANT_BY_CALL,
    channel_context,
    is_permanent,
    status,
    warn_group_left_out,
)
from onyx.connectors.teams.session import TeamsSession
from onyx.connectors.teams.sources import SlimWalk
from onyx.connectors.teams.utils import (
    ChannelFilesUnavailable,
    GraphRetriesExhausted,
    fetch_channel_files_folder,
    fetch_drive_library,
    source_group_ids,
)
from onyx.file_processing.file_types import OnyxMimeTypes
from onyx.file_store.staging import RawFileCallback

# Rebuilt on the SharePoint connector's schedule, a hedge against a cached
# REST token outliving its hour.
_REST_CTX_MAX_AGE_S = 30 * 60

# Channel files are documents of their own. The prefix keeps them apart from a
# SharePoint connector indexing the same library, which uses the bare item id.
FILE_DOCUMENT_ID_PREFIX = "teams-file:"


def file_document_id(item_id: str) -> str:
    return f"{FILE_DOCUMENT_ID_PREFIX}{item_id}"


@dataclass
class ChannelLibrary:
    """Where a channel's files live: the SharePoint site, its document library
    and the channel's folder in it."""

    site_url: str
    drive_id: str
    drive_name: str
    folder_id: str


def _indexable_file(item: DriveItemData) -> bool:
    """Decided from listing metadata alone, the way extraction decides it, so
    the slim walk can apply the same rule without downloading anything."""
    if not item.mime_type or item.mime_type in OnyxMimeTypes.EXCLUDED_IMAGE_TYPES:
        return False
    return item.size is None or item.size <= TEAMS_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD


def _tenant_domain(site_url: str) -> str:
    """The tenant part of a SharePoint host: danswerai of danswerai.sharepoint.com."""
    return (urlsplit(site_url).hostname or "").split(".")[0]


class FileSource:
    def __init__(
        self,
        session: TeamsSession,
        requested_teams: list[str],
        raw_file_callback: Callable[[], RawFileCallback | None],
    ) -> None:
        self._session = session
        self._requested_teams = requested_teams
        self._raw_file_callback = raw_file_callback
        # A channel's library, opened once per channel per attempt. None is a
        # channel whose library would not open, so every page does not try again.
        self._libraries: dict[str, ChannelLibrary | None] = {}
        # One REST context per channel site, rebuilt after _REST_CTX_MAX_AGE_S.
        self._rest_contexts: dict[str, tuple[ClientContext, float]] = {}
        # Group expansions SharePoint resolves, shared across files.
        self._permission_cache = SharepointPermissionCache()

    def open(self, channel: ChannelRef) -> None:
        """Opens the channel's library for ``index``. The library is never
        checkpointed, a saved copy would be stale on resume."""
        if channel.id in self._libraries:
            return
        try:
            self._libraries[channel.id] = self.resolve_library(channel)
        except ChannelFilesUnavailable:
            self._libraries[channel.id] = None
            raise

    def leave(self, channel: ChannelRef) -> None:
        self._libraries.pop(channel.id, None)

    def site_urls(self, channels: Iterable[ChannelRef]) -> Iterator[str]:
        """The distinct SharePoint sites behind these channels, for the group
        sync. A refused channel is left out and the listing goes on."""
        seen: set[str] = set()
        for channel in channels:
            try:
                site_url = self.resolve_library(channel).site_url
            except (requests.HTTPError, ChannelFilesUnavailable) as e:
                if isinstance(e, requests.HTTPError) and not is_permanent(e):
                    raise
                warn_group_left_out(channel, "files folder", e)
                continue
            if site_url not in seen:
                seen.add(site_url)
                yield site_url

    def _msal_app(self) -> msal.ConfidentialClientApplication:
        if self._session.msal_app is None:
            raise ConnectorMissingCredentialError("Teams")
        return self._session.msal_app

    def validate(self, tenant_teams: list[Team]) -> None:
        """Channel files need a sites grant the Teams permissions do not cover,
        so each validation opens the first channel found: its library through
        Graph and its site through SharePoint REST. Configured teams first,
        else the tenant teams already listed."""
        if not self._session.supports_sharepoint_rest:
            raise ConnectorValidationError(
                "Include Attachments needs certificate authentication: the "
                "readers of a channel file are read from SharePoint, which "
                "refuses app-only tokens from a client secret."
            )
        try:
            teams = (
                listing.collect_all_teams(
                    graph_client=self._session.graph(),
                    requested=self._requested_teams,
                )
                if self._requested_teams
                else tenant_teams
            )
            for team in teams:
                channels = listing.collect_all_channels_from_team(team=team)
                if not channels:
                    continue
                library = self.resolve_library(
                    listing.channel_ref(team.id, channels[0])
                )
                self._probe_sharepoint_rest(library.site_url)
                return
            # Every team has a General channel, so this is a listing oddity, not
            # a verified grant. Reported without marking the connector invalid.
            raise UnexpectedValidationError(
                "Could not find a channel to check the files grant on. Configure "
                "the teams to index, or retry once the tenant lists a channel."
            )
        except requests.HTTPError as e:
            if status(e) in (401, 403):
                raise InsufficientPermissionsError(
                    "Include Attachments needs read access to the channel files on "
                    f"Graph, through {GRANT_BY_CALL['files folder']} "
                    f"({status(e)} on a channel's files)."
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
        token = acquire_token_for_rest(
            self._msal_app(),
            _tenant_domain(site_url),
            self._session.sharepoint_domain_suffix,
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

    def resolve_library(self, channel: ChannelRef) -> ChannelLibrary:
        """Where the channel's files live, resolved through Graph."""
        graph_client = self._session.graph()
        folder = fetch_channel_files_folder(graph_client, channel.team_id, channel.id)
        drive_name, site_url = fetch_drive_library(graph_client, folder.drive_id)
        return ChannelLibrary(
            site_url=site_url,
            drive_id=folder.drive_id,
            drive_name=drive_name,
            folder_id=folder.id,
        )

    def rest_context(self, site_url: str) -> ClientContext:
        """SharePoint REST for a channel's site, the way the SharePoint connector
        opens it: one context per site, rebuilt once its token could be stale."""
        cached = self._rest_contexts.get(site_url)
        if cached and time.monotonic() - cached[1] <= _REST_CTX_MAX_AGE_S:
            return cached[0]
        msal_app = self._msal_app()
        tenant_domain = _tenant_domain(site_url)
        suffix = self._session.sharepoint_domain_suffix
        context = ClientContext(site_url).with_access_token(
            lambda: acquire_token_for_rest(msal_app, tenant_domain, suffix)
        )
        self._rest_contexts[site_url] = (context, time.monotonic())
        return context

    def _file_access(
        self, library: ChannelLibrary, item: DriveItemData, for_indexing: bool
    ) -> ExternalAccess:
        """The file's own readers from SharePoint, expanded through site and
        Entra groups. Empty without the enterprise permission code, as for
        SharePoint documents, so the pair's access type decides on those builds."""
        access = get_sharepoint_external_access(
            ctx=self.rest_context(library.site_url),
            graph_client=self._session.graph(),
            permission_cache=self._permission_cache,
            drive_item=item.to_sdk_driveitem(self._session.graph()),
            drive_name=library.drive_name,
        )
        return ExternalAccess(
            external_user_emails=access.external_user_emails,
            external_user_group_ids=source_group_ids(
                access.external_user_group_ids, for_indexing
            ),
            is_public=access.is_public,
        )

    def _channel_files(
        self, library: ChannelLibrary, start: SecondsSinceUnixEpoch | None
    ) -> Iterator[DriveItemData]:
        """Every indexable file under the channel's folder, changed since
        ``start``. Both walks apply the same eligibility rule, so pruning removes
        a file that grew past the threshold instead of keeping its old text."""
        window_start = datetime.fromtimestamp(start, tz=timezone.utc) if start else None
        items = iter_drive_items_paged(
            self._session.graph_api_client(),
            library.drive_id,
            folder_id=library.folder_id,
            start=window_start,
        )
        return (item for item in items if _indexable_file(item))

    def index(
        self, channel: ChannelRef, start: SecondsSinceUnixEpoch
    ) -> Iterator[Document | ConnectorFailure]:
        """The files of a channel whose library opened, none otherwise."""
        library = self._libraries.get(channel.id)
        if library is None:
            return
        for item in self._channel_files(library, start):
            yield self._file_document(channel, library, item)

    def _file_document(
        self, channel: ChannelRef, library: ChannelLibrary, item: DriveItemData
    ) -> Document | ConnectorFailure:
        """One document per channel file, carrying the file's own SharePoint
        readers so permission sync and pruning treat it like a message."""
        try:
            content = extract_drive_item_content(
                item,
                size_threshold=TEAMS_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD,
                graph_api_base=self._session.graph_root,
                access_token=self._session.access_token(),
                raw_file_callback=self._raw_file_callback(),
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
            external_access=self._file_access(library, item, for_indexing=True),
            file_id=content.staged_file_id if content is not None else None,
        )

    def slim(self, channel: ChannelRef, walk: SlimWalk) -> Iterator[SlimDocument]:
        """Channel files with the ids the indexing walk writes, and with the
        readers SharePoint grants them when the caller needs those. A refused
        folder or site raises: a channel missing from this listing would have
        its documents pruned."""
        with channel_context(channel, "files"):
            library = self.resolve_library(channel)
            for item in self._channel_files(library, start=None):
                yield SlimDocument(
                    id=file_document_id(item.id),
                    external_access=(
                        self._file_access(library, item, for_indexing=False)
                        if walk.with_readers
                        else None
                    ),
                    doc_created_at=item.created_datetime,
                )
