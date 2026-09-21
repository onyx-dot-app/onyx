"""Channel files as documents of their own: what is indexed, who may read it,
and what the connector refuses to do without a certificate."""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from office365.runtime.client_request_exception import ClientRequestException
from office365.teams.team import Team

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import TEAMS_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.microsoft_utils.drive_items import (
    DriveItemContent,
    DriveItemContentError,
    DriveItemData,
)
from onyx.connectors.microsoft_utils.graph_auth import MicrosoftAuthMethod
from onyx.connectors.models import ConnectorFailure, Document, SlimDocument, TextSection
from onyx.connectors.teams import files as files_module
from onyx.connectors.teams import listing as listing_module
from onyx.connectors.teams import session as session_module
from onyx.connectors.teams.connector import TeamsConnector
from onyx.connectors.teams.files import FileSource, file_document_id
from onyx.connectors.teams.utils import GraphRetriesExhausted, message_delta_url
from tests.unit.onyx.connectors.teams.helpers import (
    CHANNEL_ID,
    DELTA_URL,
    MEMBERS_URL,
    SERVICE_ROOT,
    TEAM_ID,
    channel_checkpoint,
    connector,
    graph_client,
    member,
    message,
    replies_url,
    step,
    walk_channel,
)

FOLDER_URL = f"teams/{TEAM_ID}/channels/{CHANNEL_ID}/filesFolder"
DRIVE = "drive-1"
FOLDER_ID = "folder-1"
SITE_URL = "https://tenant.sharepoint.example/sites/T"
DRIVE_URL = f"drives/{DRIVE}?$select=name,sharePointIds"
# The shape a live tenant answers with: the files folder names its drive and
# leaves its site id empty, and the drive names the site.
LIBRARY_ROUTES: dict[str, dict[str, Any]] = {
    FOLDER_URL: {
        "id": FOLDER_ID,
        "parentReference": {"driveId": DRIVE, "siteId": None},
    },
    DRIVE_URL: {"name": "Documents", "sharePointIds": {"siteUrl": SITE_URL}},
}
MEMBERS = {MEMBERS_URL: {"value": [member("Ada", "ada@example.com", "u1")]}}
CHANNEL_READERS = ExternalAccess(
    external_user_emails={"ada@example.com"},
    external_user_group_ids=set(),
    is_public=False,
)
# What the SharePoint permission code answers for a file, and what the file's
# document carries: the same groups under this connector's source prefix.
SITE_GROUP = f"{SITE_URL.lower()}::members"
SHAREPOINT_READERS = ExternalAccess(
    external_user_emails={"ada@example.com"},
    external_user_group_ids={SITE_GROUP},
    is_public=False,
)
FILE_READERS = ExternalAccess(
    external_user_emails={"ada@example.com"},
    external_user_group_ids={f"teams_{SITE_GROUP}"},
    is_public=False,
)


def _item(item_id: str, name: str) -> DriveItemData:
    return DriveItemData(
        id=item_id,
        name=name,
        web_url=f"{SITE_URL}/Shared%20Documents/General/{name}",
        size=10,
        mime_type="application/pdf",
        created_datetime=datetime(2026, 9, 1, tzinfo=timezone.utc),
        last_modified_datetime=datetime(2026, 9, 2, 10, tzinfo=timezone.utc),
        last_modified_by_display_name="Ada",
        last_modified_by_email="ada@example.com",
        drive_id=DRIVE,
    )


@pytest.fixture
def library(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The channel folder holds the files in ``files``. Listing, extraction and
    the SharePoint readers are stubbed and their calls recorded."""
    seen: dict[str, Any] = {"files": [], "listed": [], "extracted": [], "access": []}

    def iter_items(_client: Any, drive_id: str, **kwargs: Any) -> Any:
        seen["listed"].append((drive_id, kwargs.get("folder_id"), kwargs.get("start")))
        yield from seen["files"]

    def extract(item: DriveItemData, **kwargs: Any) -> DriveItemContent | None:
        seen["extracted"].append((item.id, kwargs["access_token"]))
        if item.name.endswith(".skip"):
            return None
        if item.name.endswith(".bad"):
            raise DriveItemContentError("parser refused it")
        return DriveItemContent(
            sections=[TextSection(link=item.web_url, text=f"Text of {item.name}")],
            staged_file_id=None,
        )

    def access(**kwargs: Any) -> ExternalAccess:
        seen["access"].append((kwargs["drive_item"].id, kwargs["drive_name"]))
        return SHAREPOINT_READERS

    monkeypatch.setattr(files_module, "iter_drive_items_paged", iter_items)
    monkeypatch.setattr(files_module, "extract_drive_item_content", extract)
    monkeypatch.setattr(files_module, "get_sharepoint_external_access", access)
    # A ClientContext double that builds a distinct context per call.
    monkeypatch.setattr(
        files_module, "ClientContext", MagicMock(side_effect=lambda _: MagicMock())
    )
    monkeypatch.setattr(files_module, "acquire_token_for_rest", MagicMock())
    monkeypatch.setattr(DriveItemData, "to_sdk_driveitem", lambda self, _client: self)
    return seen


def _rest_refusing(status: int) -> Callable[..., ExternalAccess]:
    """SharePoint REST answering the readers lookup with ``status``, the way
    the office365 SDK raises it."""

    def refuse(**_: Any) -> ExternalAccess:
        response = MagicMock(status_code=status, text="refused")
        response.headers = {"Content-Type": "text/plain"}
        raise ClientRequestException(response=response)

    return refuse


def _rest_context_calls() -> list[Any]:
    context_class = files_module.ClientContext
    assert isinstance(context_class, MagicMock)
    return [call.args for call in context_class.call_args_list]


def _channel_routes(*roots: dict[str, Any]) -> dict[str, dict[str, Any]]:
    routes: dict[str, dict[str, Any]] = {
        **MEMBERS,
        **LIBRARY_ROUTES,
        DELTA_URL: {"value": list(roots)},
    }
    for root in roots:
        routes[replies_url(root["id"])] = {"value": []}
    return routes


def _requested(client: MagicMock) -> list[str]:
    return [call.args[0] for call in client.execute_request_direct.call_args_list]


def _document_ids(items: list[Document | ConnectorFailure]) -> list[str]:
    return [item.id for item in items if isinstance(item, Document)]


def _files(teams_connector: TeamsConnector) -> FileSource:
    assert teams_connector._files is not None
    return teams_connector._files


def _sdk_team_and_channel() -> tuple[MagicMock, MagicMock]:
    team = MagicMock(spec=Team)
    team.id = TEAM_ID
    sdk_channel = MagicMock()
    sdk_channel.id = CHANNEL_ID
    sdk_channel.properties = {"displayName": "General"}
    return team, sdk_channel


def test_attachments_are_off_by_default(library: dict[str, Any]) -> None:
    library["files"] = [_item("item-1", "Plan.pdf")]
    client = graph_client(_channel_routes(message("m1", "Plan")))

    items = walk_channel(connector(client))

    assert _document_ids(items) == ["m1"]
    assert FOLDER_URL not in _requested(client)
    assert library["listed"] == []


def test_channel_files_become_documents_with_sharepoints_readers(
    library: dict[str, Any],
) -> None:
    library["files"] = [_item("item-1", "Plan.pdf"), _item("item-2", "Notes.docx")]
    client = graph_client(_channel_routes(message("m1", "Plan")))

    items = walk_channel(connector(client, include_attachments=True))

    assert _document_ids(items) == [
        "m1",
        file_document_id("item-1"),
        file_document_id("item-2"),
    ]
    plan = [item for item in items if isinstance(item, Document)][1]
    assert plan.semantic_identifier == "Plan.pdf"
    assert plan.external_access == FILE_READERS
    assert plan.doc_updated_at == datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
    assert plan.metadata == {"channel": "General"}
    assert [owner.email for owner in plan.primary_owners or []] == ["ada@example.com"]
    assert [section.text for section in plan.sections] == ["Text of Plan.pdf"]
    assert library["listed"] == [(DRIVE, FOLDER_ID, None)]
    assert library["access"] == [("item-1", "Documents"), ("item-2", "Documents")]
    assert [token for _, token in library["extracted"]] == ["token", "token"]
    assert _requested(client).count(FOLDER_URL) == 1


def test_files_follow_the_last_page_and_respect_the_poll_window(
    library: dict[str, Any],
) -> None:
    start = 1_700_000_000
    library["files"] = [_item("item-1", "Plan.pdf")]
    page_two = f"teams/{TEAM_ID}/channels/{CHANNEL_ID}/messages/delta?$skiptoken=p2"
    routes = _channel_routes(message("m1", "one"), message("m2", "two"))
    routes[message_delta_url(TEAM_ID, CHANNEL_ID, start)] = {
        "value": [message("m1", "one")],
        "@odata.nextLink": f"{SERVICE_ROOT}/{page_two}",
    }
    routes[page_two] = {"value": [message("m2", "two")]}
    teams_connector = connector(graph_client(routes), include_attachments=True)

    items, checkpoint = step(teams_connector, channel_checkpoint(), start=start)
    assert _document_ids(items) == ["m1"]
    assert library["listed"] == []

    items, checkpoint = step(teams_connector, checkpoint, start=start)
    assert _document_ids(items) == ["m2", file_document_id("item-1")]
    assert library["listed"] == [
        (DRIVE, FOLDER_ID, datetime.fromtimestamp(start, tz=timezone.utc))
    ]
    assert checkpoint.has_more is False


def test_an_unreadable_file_keeps_its_name_and_a_failed_one_is_a_document_failure(
    library: dict[str, Any],
) -> None:
    library["files"] = [_item("item-1", "empty.skip"), _item("item-2", "corrupt.bad")]
    client = graph_client(_channel_routes(message("m1", "Plan")))

    items = walk_channel(connector(client, include_attachments=True))

    documents = [item for item in items if isinstance(item, Document)]
    assert [document.id for document in documents] == ["m1", file_document_id("item-1")]
    assert [section.text for section in documents[1].sections] == ["empty.skip"]
    assert documents[1].external_access == FILE_READERS
    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == file_document_id("item-2")


def test_files_extraction_would_skip_are_listed_by_neither_walk(
    library: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    oversized = _item("item-1", "huge.pdf")
    oversized.size = TEAMS_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD + 1
    untyped = _item("item-2", "blob")
    untyped.mime_type = None
    library["files"] = [oversized, untyped, _item("item-3", "Plan.pdf")]
    team, sdk_channel = _sdk_team_and_channel()
    monkeypatch.setattr(listing_module, "collect_all_teams", lambda **_: [team])
    monkeypatch.setattr(
        listing_module, "collect_all_channels_from_team", lambda **_: [sdk_channel]
    )
    routes = _channel_routes(message("m1", "Plan"))

    indexed = walk_channel(connector(graph_client(routes), include_attachments=True))
    slim = [
        doc.id
        for batch in connector(
            graph_client(routes), include_attachments=True
        ).retrieve_all_slim_docs_perm_sync()
        for doc in batch
        if isinstance(doc, SlimDocument)
    ]

    assert _document_ids(indexed) == ["m1", file_document_id("item-3")]
    assert slim == ["m1", file_document_id("item-3")]
    assert [item_id for item_id, _ in library["extracted"]] == ["item-3"]


def test_a_refused_library_is_one_channel_failure(library: dict[str, Any]) -> None:
    routes = _channel_routes(message("m1", "Plan"))
    routes.pop(FOLDER_URL)
    client = graph_client(routes, refused={FOLDER_URL: 403})

    items = walk_channel(connector(client, include_attachments=True))

    assert _document_ids(items) == []
    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_entity is not None
    assert failures[0].failed_entity.entity_id == CHANNEL_ID
    assert library["listed"] == []


def test_a_library_outage_fails_the_attempt(
    library: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("onyx.connectors.teams.utils.time.sleep", lambda _: None)
    routes = _channel_routes(message("m1", "Plan"))
    routes.pop(DRIVE_URL)
    client = graph_client(routes, refused={DRIVE_URL: 503})

    with pytest.raises(GraphRetriesExhausted):
        walk_channel(connector(client, include_attachments=True))
    assert library["listed"] == []


def test_the_slim_walk_lists_files_with_their_own_readers(
    library: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    library["files"] = [_item("item-1", "Plan.pdf")]
    team, sdk_channel = _sdk_team_and_channel()
    monkeypatch.setattr(listing_module, "collect_all_teams", lambda **_: [team])
    monkeypatch.setattr(
        listing_module, "collect_all_channels_from_team", lambda **_: [sdk_channel]
    )
    routes = {**MEMBERS, **LIBRARY_ROUTES, DELTA_URL: {"value": [message("m1", "P")]}}
    teams_connector = connector(graph_client(routes), include_attachments=True)

    slim = [
        (doc.id, doc.external_access)
        for batch in teams_connector.retrieve_all_slim_docs_perm_sync()
        for doc in batch
        if isinstance(doc, SlimDocument)
    ]

    assert slim == [
        ("m1", CHANNEL_READERS),
        (file_document_id("item-1"), FILE_READERS),
    ]
    assert library["listed"] == [(DRIVE, FOLDER_ID, None)]


def test_the_pruning_walk_lists_the_same_ids_without_reading_readers(
    library: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    library["files"] = [_item("item-1", "Plan.pdf")]
    team, sdk_channel = _sdk_team_and_channel()
    monkeypatch.setattr(listing_module, "collect_all_teams", lambda **_: [team])
    monkeypatch.setattr(
        listing_module, "collect_all_channels_from_team", lambda **_: [sdk_channel]
    )
    routes = {**MEMBERS, **LIBRARY_ROUTES, DELTA_URL: {"value": [message("m1", "P")]}}
    client = graph_client(routes)

    slim = [
        (doc.id, doc.external_access)
        for batch in connector(
            client, include_attachments=True
        ).retrieve_all_slim_docs()
        for doc in batch
        if isinstance(doc, SlimDocument)
    ]

    assert slim == [("m1", None), (file_document_id("item-1"), None)]
    # Neither the members call nor the SharePoint readers lookup is worth making
    # for a walk that only decides what no longer exists.
    assert MEMBERS_URL not in _requested(client)
    assert library["access"] == []


@pytest.mark.usefixtures("library")
def test_the_rest_context_is_reused_per_site_until_its_token_ages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = MagicMock(monotonic=MagicMock(side_effect=[0.0, 10.0, 2000.0, 2001.0]))
    monkeypatch.setattr(files_module, "time", clock)
    teams_connector = connector(graph_client({}), include_attachments=True)

    first = teams_connector.rest_context(SITE_URL)

    assert teams_connector.rest_context(SITE_URL) is first
    assert teams_connector.rest_context(SITE_URL) is not first
    assert _rest_context_calls() == [(SITE_URL,), (SITE_URL,)]


def test_channel_site_urls_are_distinct_and_a_refused_channel_fails_the_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team, general = _sdk_team_and_channel()
    private = MagicMock()
    private.id = "19:private@thread.tacv2"
    private.properties = {"displayName": "Private"}
    refused = MagicMock()
    refused.id = "19:refused@thread.tacv2"
    refused.properties = {"displayName": "Refused"}
    channels = [general, private]
    monkeypatch.setattr(listing_module, "collect_all_teams", lambda **_: [team])
    monkeypatch.setattr(
        listing_module, "collect_all_channels_from_team", lambda **_: channels
    )
    private_folder = f"teams/{TEAM_ID}/channels/{private.id}/filesFolder"
    refused_folder = f"teams/{TEAM_ID}/channels/{refused.id}/filesFolder"
    routes = {
        **LIBRARY_ROUTES,
        private_folder: {
            "id": "folder-2",
            "parentReference": {"driveId": DRIVE, "siteId": None},
        },
    }
    client = graph_client(routes, refused={refused_folder: 403})

    assert list(connector(client, include_attachments=True).channel_site_urls()) == [
        SITE_URL
    ]

    channels.append(refused)
    with pytest.raises(ConnectorValidationError, match='"Refused"'):
        list(connector(client, include_attachments=True).channel_site_urls())


@pytest.mark.parametrize("status", [403, 404])
def test_a_site_that_refuses_the_readers_is_one_channel_failure(
    library: dict[str, Any], monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    library["files"] = [_item("item-1", "Plan.pdf")]
    monkeypatch.setattr(
        files_module, "get_sharepoint_external_access", _rest_refusing(status)
    )
    client = graph_client(_channel_routes(message("m1", "Plan")))

    items = walk_channel(connector(client, include_attachments=True))

    assert _document_ids(items) == ["m1"]
    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert [f.failed_entity.entity_id for f in failures if f.failed_entity] == [
        CHANNEL_ID
    ]


def test_a_site_outage_during_the_readers_fails_the_attempt(
    library: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    library["files"] = [_item("item-1", "Plan.pdf")]
    monkeypatch.setattr(
        files_module, "get_sharepoint_external_access", _rest_refusing(503)
    )
    client = graph_client(_channel_routes(message("m1", "Plan")))

    with pytest.raises(ClientRequestException):
        walk_channel(connector(client, include_attachments=True))


def test_attachments_need_a_certificate_credential() -> None:
    teams_connector = connector(graph_client({}), include_attachments=True)
    teams_connector._auth_method = MicrosoftAuthMethod.CLIENT_SECRET

    with pytest.raises(ConnectorValidationError, match="certificate"):
        teams_connector.validate_connector_settings()


def test_the_certificate_credential_is_parsed_and_passed_to_msal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: dict[str, Any] = {}

    def build(**kwargs: Any) -> MagicMock:
        built.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(session_module, "build_msal_app", build)
    teams_connector = TeamsConnector(include_attachments=True)

    teams_connector.load_credentials(
        {
            "authentication_method": "certificate",
            "teams_client_id": "app",
            "teams_directory_id": "tenant",
            "teams_private_key": "cGZ4",
            "teams_certificate_password": "pw",
        }
    )

    assert built["auth_method"] is MicrosoftAuthMethod.CERTIFICATE
    assert built["private_key_b64"] == "cGZ4"
    assert built["certificate_password"] == "pw"
    assert built["client_secret"] is None
    assert teams_connector._auth_method is MicrosoftAuthMethod.CERTIFICATE


def test_a_client_secret_credential_without_its_secret_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_module, "build_msal_app", MagicMock())

    with pytest.raises(KeyError, match="teams_client_secret"):
        TeamsConnector().load_credentials(
            {
                "authentication_method": "client_secret",
                "teams_client_id": "app",
                "teams_directory_id": "tenant",
            }
        )


def _validation_connector(
    monkeypatch: pytest.MonkeyPatch,
    routes: dict[str, dict[str, Any]],
    refused: dict[str, int] | None = None,
) -> tuple[TeamsConnector, list[Team]]:
    """A connector with no teams configured, so validation probes the first
    channel of the tenant teams handed to it."""
    team, sdk_channel = _sdk_team_and_channel()
    monkeypatch.setattr(
        listing_module, "collect_all_channels_from_team", lambda **_: [sdk_channel]
    )
    teams_connector = connector(
        graph_client(routes, refused=refused), include_attachments=True
    )
    return teams_connector, [team]


def _rest_answering(monkeypatch: pytest.MonkeyPatch, status: int) -> list[str]:
    """SharePoint REST answering every probe with ``status``. Returns the urls."""
    probes: list[str] = []

    def rest_get(url: str, **_: Any) -> MagicMock:
        probes.append(url)
        response = MagicMock(status_code=status)
        if status >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(
                str(status), response=response
            )
        return response

    monkeypatch.setattr(files_module.requests, "get", rest_get)
    return probes


@pytest.mark.usefixtures("library")
def test_validation_probes_the_channel_site_over_sharepoint_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes = _rest_answering(monkeypatch, 200)
    teams_connector, teams = _validation_connector(monkeypatch, LIBRARY_ROUTES)

    _files(teams_connector).validate(teams)

    assert probes == [f"{SITE_URL}/_api/web/roleassignments?$top=1"]


@pytest.mark.usefixtures("library")
@pytest.mark.parametrize("status", [401, 403])
def test_a_site_that_refuses_its_role_assignments_names_full_control(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    _rest_answering(monkeypatch, status)
    teams_connector, teams = _validation_connector(monkeypatch, LIBRARY_ROUTES)

    # A read grant on SharePoint reaches this refusal, so the message names the
    # grant that reads role assignments and not the one the app already holds.
    with pytest.raises(
        InsufficientPermissionsError, match="Sites.FullControl.All"
    ) as refusal:
        _files(teams_connector).validate(teams)
    assert "Sites.Read.All" not in str(refusal.value)


def test_the_site_comes_from_the_drive_not_the_files_folder(
    library: dict[str, Any],
) -> None:
    library["files"] = [_item("item-1", "Plan.pdf")]
    client = graph_client(_channel_routes(message("m1", "Plan")))

    items = walk_channel(connector(client, include_attachments=True))

    # The files folder of LIBRARY_ROUTES carries no site id, as a live tenant's
    # does, and the file still indexes with SharePoint REST on the drive's site.
    assert file_document_id("item-1") in _document_ids(items)
    assert _rest_context_calls() == [(SITE_URL,)]


def test_a_library_that_names_no_site_keeps_the_pair_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes = {**LIBRARY_ROUTES, DRIVE_URL: {"name": "Documents"}}
    teams_connector, teams = _validation_connector(monkeypatch, routes)

    with pytest.raises(UnexpectedValidationError, match="without its name or its site"):
        _files(teams_connector).validate(teams)


def test_a_files_folder_that_names_no_library_keeps_the_pair_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes = {**LIBRARY_ROUTES, FOLDER_URL: {"id": FOLDER_ID, "parentReference": {}}}
    teams_connector, teams = _validation_connector(monkeypatch, routes)

    with pytest.raises(UnexpectedValidationError, match="names no document library"):
        _files(teams_connector).validate(teams)


def test_a_library_that_names_no_site_is_one_channel_failure(
    library: dict[str, Any],
) -> None:
    library["files"] = [_item("item-1", "Plan.pdf")]
    routes = {
        **_channel_routes(message("m1", "Plan")),
        DRIVE_URL: {"name": "Documents"},
    }

    items = walk_channel(connector(graph_client(routes), include_attachments=True))

    # The thread still indexes, and the channel's files are recorded as the one
    # thing this attempt could not read.
    assert _document_ids(items) == ["m1"]
    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_entity is not None
    assert failures[0].failed_entity.entity_id == CHANNEL_ID
    assert "without its name or its site" in failures[0].failure_message


def test_a_refused_files_folder_names_the_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teams_connector, teams = _validation_connector(
        monkeypatch, {}, refused={FOLDER_URL: 403}
    )

    with pytest.raises(InsufficientPermissionsError, match="Sites.Read.All"):
        _files(teams_connector).validate(teams)


def test_a_listing_outage_during_validation_keeps_the_pair_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def listing_fails(**_: Any) -> list[MagicMock]:
        gateway_error = MagicMock(status_code=503, text="gateway")
        gateway_error.headers = {"Content-Type": "text/plain"}
        raise ClientRequestException(response=gateway_error)

    teams_connector, teams = _validation_connector(monkeypatch, {})
    monkeypatch.setattr(listing_module, "collect_all_channels_from_team", listing_fails)

    with pytest.raises(UnexpectedValidationError):
        _files(teams_connector).validate(teams)


def test_validation_reports_when_no_channel_can_be_probed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teams_connector, teams = _validation_connector(monkeypatch, {})
    monkeypatch.setattr(
        listing_module, "collect_all_channels_from_team", lambda **_: []
    )

    with pytest.raises(UnexpectedValidationError, match="Could not find"):
        _files(teams_connector).validate(teams)
