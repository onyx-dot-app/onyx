"""The SharePoint gateway addresses the right Graph and SharePoint endpoints,
hands back plain data, and raises refusals as MicrosoftGraphError."""

import json
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests
from office365.graph_client import GraphClient
from office365.onedrive.drives.drive import Drive
from office365.runtime.client_request_exception import ClientRequestException

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.microsoft_utils.graph_auth import (
    MicrosoftAuthContext,
    MicrosoftAuthMethod,
)
from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
from onyx.connectors.microsoft_utils.models import (
    SharepointSecurable,
    SharepointSecurableKind,
)
from onyx.connectors.sharepoint import source_operations as gateway_module
from onyx.connectors.sharepoint.models import SharepointDrive
from onyx.connectors.sharepoint.source_operations import (
    DRIVE_EXPAND_FIELDS,
    DRIVE_LIST_PROPERTY,
    DRIVE_SELECT_FIELDS,
    REST_CTX_MAX_AGE_S,
    SharepointSourceOperations,
)
from tests.unit.onyx.connectors.sharepoint.sharepoint_gateway_fakes import (
    GRAPH_API_BASE,
    fake_gateway,
)

SITE_URL = "https://tenant.sharepoint.com/sites/eng"
OTHER_SITE_URL = "https://tenant.sharepoint.com/sites/ops"
SITE_ID = "tenant.sharepoint.com,abc,def"
PAGES = f"{GRAPH_API_BASE}/sites/{SITE_ID}/pages"
AUTH_BUILDER = "onyx.connectors.microsoft_utils.graph_gateway.build_graph_auth_context"


def _json_error(status: int, code: str) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps({"error": {"code": code, "message": "m"}}).encode()
    return requests.HTTPError(response=response)


def _sdk_error(status: int, code: str) -> ClientRequestException:
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps({"error": {"code": code, "message": "m"}}).encode()
    return ClientRequestException(f"{status} Client Error", response=response)


def _odata_mapped_drive(
    include_list: bool, *, drive_id: str = "drive-id", include_web_url: bool = True
) -> Drive:
    """A Drive the SDK mapped from a Graph answer, list relationship expanded."""
    graph_client = GraphClient(lambda: {"access_token": "unused"})
    drives = (
        graph_client.sites["site-id"]
        .drives.select(DRIVE_SELECT_FIELDS)
        .expand(DRIVE_EXPAND_FIELDS)
        .get()
    )
    properties: dict[str, Any] = {
        "id": drive_id,
        "name": "Documents",
        "driveType": "documentLibrary",
    }
    if include_web_url:
        properties["webUrl"] = f"{SITE_URL}/Documents"
    if include_list:
        properties[DRIVE_LIST_PROPERTY] = {"id": "list-id"}
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps({"value": [properties]}).encode()
    graph_client.pending_request().process_response(response, graph_client._queries[0])
    return drives[0]


class _Query:
    def __init__(self, result: Any, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    def execute_query(self) -> Any:
        if self._error is not None:
            raise self._error
        return self._result


class _DrivesCollection:
    """The SDK's drive listing: ``get`` is the first page, ``get_all`` walks
    every page."""

    def __init__(self, pages: list[list[Drive]], error: Exception | None) -> None:
        self._pages = pages
        self._error = error
        self.selected: list[str] | None = None
        self.expanded: list[str] | None = None

    def select(self, fields: list[str]) -> "_DrivesCollection":
        self.selected = fields
        return self

    def expand(self, fields: list[str]) -> "_DrivesCollection":
        self.expanded = fields
        return self

    def get(self) -> _Query:
        return _Query(list(self._pages[0]) if self._pages else [], self._error)

    def get_all(self, page_loaded: Callable[[Any], None]) -> _Query:
        page_loaded(self)
        return _Query([drive for page in self._pages for drive in page], self._error)


class _SitePage:
    """One page of the SDK's site listing, truthy like the SDK collection."""

    def __init__(self, urls: list[str], next_page: "_SitePage | None") -> None:
        self.current_page = [MagicMock(web_url=url) for url in urls]
        self._next_page = next_page

    @property
    def has_next(self) -> bool:
        return self._next_page is not None

    def _get_next(self) -> _Query:
        return _Query(self._next_page)


class _Sites:
    def __init__(
        self,
        *,
        drive_pages: list[list[Drive]] | None = None,
        site_error: Exception | None = None,
        site_id: str | None = SITE_ID,
        pages: _SitePage | None = None,
        root_hostname: str | None = None,
    ) -> None:
        self.drives = _DrivesCollection(drive_pages or [], site_error)
        self._site_error = site_error
        self._site_id = site_id
        self._pages = pages
        self.root = MagicMock()
        self.root.get.return_value = _Query(
            MagicMock(site_collection=MagicMock(hostname=root_hostname))
        )

    def get_by_url(self, url: str) -> Any:
        site = MagicMock(id=self._site_id, web_url=url, drives=self.drives)
        site.execute_query.side_effect = self._site_error
        return site

    def get_all_sites(self) -> _Query:
        return _Query(self._pages)


def _sdk_client(**kwargs: Any) -> Any:
    return MagicMock(sites=_Sites(**kwargs))


def _auth_context(method: MicrosoftAuthMethod) -> MicrosoftAuthContext:
    return MicrosoftAuthContext(app=MagicMock(), method=method)


def test_list_drives_maps_the_expanded_list() -> None:
    sdk = _sdk_client(drive_pages=[[_odata_mapped_drive(include_list=True)]])

    drives = fake_gateway(sdk_client=sdk).list_drives(site_url=SITE_URL)

    assert drives == [
        SharepointDrive(
            id="drive-id",
            name="Documents",
            web_url=f"{SITE_URL}/Documents",
            drive_type="documentLibrary",
            list_id="list-id",
        )
    ]
    assert sdk.sites.drives.selected == DRIVE_SELECT_FIELDS
    assert sdk.sites.drives.expanded == DRIVE_EXPAND_FIELDS


def test_list_drives_reads_every_page() -> None:
    sdk = _sdk_client(
        drive_pages=[
            [_odata_mapped_drive(include_list=True, drive_id="first-page")],
            [_odata_mapped_drive(include_list=True, drive_id="second-page")],
        ]
    )

    drives = fake_gateway(sdk_client=sdk).list_drives(site_url=SITE_URL)

    assert [drive.id for drive in drives] == ["first-page", "second-page"]


def test_list_drives_keeps_a_library_without_a_web_url() -> None:
    sdk = _sdk_client(
        drive_pages=[[_odata_mapped_drive(include_list=True, include_web_url=False)]]
    )

    drives = fake_gateway(sdk_client=sdk).list_drives(site_url=SITE_URL)

    assert drives[0].id == "drive-id"
    assert drives[0].web_url is None


def test_list_drives_without_expanded_list_has_no_list_id() -> None:
    sdk = _sdk_client(drive_pages=[[_odata_mapped_drive(include_list=False)]])

    drives = fake_gateway(sdk_client=sdk).list_drives(site_url=SITE_URL)

    assert drives[0].list_id is None


def test_list_drives_rejects_an_unmapped_list() -> None:
    drive = _odata_mapped_drive(include_list=False)
    drive.properties[DRIVE_LIST_PROPERTY] = {"id": "list-id"}
    sdk = _sdk_client(drive_pages=[[drive]])

    with pytest.raises(ValueError, match="unexpected type"):
        fake_gateway(sdk_client=sdk).list_drives(site_url=SITE_URL)


def test_list_drives_raises_refusals_as_microsoft_errors() -> None:
    sdk = _sdk_client(site_error=_sdk_error(403, "accessDenied"))

    with pytest.raises(MicrosoftGraphError) as raised:
        fake_gateway(sdk_client=sdk).list_drives(site_url=SITE_URL)

    assert raised.value.status == 403
    assert raised.value.code == "accessDenied"


def test_list_site_urls_reads_every_page() -> None:
    pages = _SitePage([SITE_URL], _SitePage([OTHER_SITE_URL, ""], None))
    sdk = _sdk_client(pages=pages)

    assert fake_gateway(sdk_client=sdk).list_site_urls() == [SITE_URL, OTHER_SITE_URL]


def test_list_site_urls_stops_at_the_page_cap() -> None:
    pages = _SitePage([SITE_URL], _SitePage([OTHER_SITE_URL], None))
    sdk = _sdk_client(pages=pages)

    assert fake_gateway(sdk_client=sdk).list_site_urls(max_pages=1) == [SITE_URL]


def test_check_token_reports_the_lifetime() -> None:
    def get_json(url: str, params: dict[str, str] | None) -> dict[str, Any]:  # noqa: ARG001
        raise AssertionError("no Graph call")

    assert fake_gateway(get_json=get_json).check_token().expires_in == 3600


def test_get_site_id_needs_an_id() -> None:
    sdk = _sdk_client(site_id=None)

    with pytest.raises(RuntimeError, match="without an id"):
        fake_gateway(sdk_client=sdk).get_site_id(site_url=SITE_URL)


def test_get_site_raises_refusals_as_microsoft_errors() -> None:
    sdk = _sdk_client(site_error=_sdk_error(404, "itemNotFound"))

    with pytest.raises(MicrosoftGraphError) as raised:
        fake_gateway(sdk_client=sdk).get_site_id(site_url=SITE_URL)

    assert raised.value.status == 404


def test_site_pages_expand_the_canvas_on_the_first_page_only() -> None:
    requested: list[tuple[str, dict[str, str] | None]] = []

    def get_json(url: str, params: dict[str, str] | None) -> dict[str, Any]:
        requested.append((url, params))
        if url.endswith("microsoft.graph.sitePage"):
            return {"value": [{"id": "p1"}], "@odata.nextLink": "https://next"}
        return {"value": [{"id": "p2"}]}

    gateway = fake_gateway(get_json=get_json)

    first = gateway.list_site_pages(site_id=SITE_ID, next_link=None, expand_canvas=True)
    second = gateway.list_site_pages(
        site_id=SITE_ID, next_link=first.next_link, expand_canvas=True
    )
    unexpanded = gateway.list_site_pages(
        site_id=SITE_ID, next_link=None, expand_canvas=False
    )

    assert [page["id"] for page in first.pages + second.pages] == ["p1", "p2"]
    assert [page["id"] for page in unexpanded.pages] == ["p1"]
    assert requested == [
        (f"{PAGES}/microsoft.graph.sitePage", {"$expand": "canvasLayout"}),
        ("https://next", None),
        (f"{PAGES}/microsoft.graph.sitePage", None),
    ]


def test_single_site_page_is_addressed_by_id() -> None:
    requested: list[tuple[str, dict[str, str] | None]] = []

    def get_json(url: str, params: dict[str, str] | None) -> dict[str, Any]:
        requested.append((url, params))
        return {"id": "p1"}

    gateway = fake_gateway(get_json=get_json)

    gateway.get_site_page(site_id=SITE_ID, page_id="p1", expand_canvas=True)
    gateway.get_site_page(site_id=SITE_ID, page_id="p1", expand_canvas=False)

    assert requested == [
        (f"{PAGES}/p1/microsoft.graph.sitePage", {"$expand": "canvasLayout"}),
        (f"{PAGES}/p1/microsoft.graph.sitePage", None),
    ]


def test_graph_errors_carry_the_body_code() -> None:
    def get_json(url: str, params: dict[str, str] | None) -> dict[str, Any]:  # noqa: ARG001
        raise _json_error(400, "invalidRequest")

    with pytest.raises(MicrosoftGraphError) as raised:
        fake_gateway(get_json=get_json).list_site_pages(
            site_id=SITE_ID, expand_canvas=True
        )

    assert (raised.value.status, raised.value.code) == (400, "invalidRequest")


def test_drive_item_missing_from_a_drive_is_none() -> None:
    def get_json(url: str, params: dict[str, str] | None) -> dict[str, Any]:  # noqa: ARG001
        if "/drives/d1/" in url:
            raise _json_error(404, "itemNotFound")
        return {"id": "item-1", "name": "a.pdf", "webUrl": f"{SITE_URL}/a.pdf"}

    gateway = fake_gateway(get_json=get_json)

    assert gateway.get_drive_item(drive_id="d1", item_id="item-1") is None
    found = gateway.get_drive_item(drive_id="d2", item_id="item-1")
    assert found is not None
    assert found.id == "item-1"


def test_folder_items_raise_refusals_while_iterating() -> None:
    def get_json(url: str, params: dict[str, str] | None) -> dict[str, Any]:  # noqa: ARG001
        raise _json_error(403, "accessDenied")

    items = fake_gateway(get_json=get_json).iter_folder_items(
        drive_id="d1", folder_id=None, start=None, end=None
    )

    with pytest.raises(MicrosoftGraphError):
        list(items)


def test_entra_group_probe_reads_one_named_group() -> None:
    requested: list[tuple[str, dict[str, str] | None]] = []

    def get_json(url: str, params: dict[str, str] | None) -> dict[str, Any]:
        requested.append((url, params))
        return {"value": [{"id": "g1", "displayName": "Engineering"}]}

    page = fake_gateway(get_json=get_json).list_entra_groups(page_size=1)

    assert [group.id for group in page.items] == ["g1"]
    assert requested == [
        (f"{GRAPH_API_BASE}/groups", {"$select": "id,displayName", "$top": "1"})
    ]


def test_tenant_domain_comes_from_the_configured_sites() -> None:
    sdk = _sdk_client()
    gateway = fake_gateway(sites=[SITE_URL], sdk_client=sdk)

    assert gateway.resolve_tenant_domain() == "tenant"
    sdk.sites.root.get.assert_not_called()


def test_tenant_domain_falls_back_to_the_root_site() -> None:
    gateway = fake_gateway(
        sites=[], sdk_client=_sdk_client(root_hostname="contoso.sharepoint.com")
    )

    assert gateway.resolve_tenant_domain() == "contoso"


def test_root_site_without_a_hostname_fails_validation() -> None:
    gateway = fake_gateway(sites=[], sdk_client=_sdk_client(root_hostname=None))

    with pytest.raises(ConnectorValidationError, match="root site"):
        gateway.resolve_tenant_domain()


@patch(AUTH_BUILDER, return_value=_auth_context(MicrosoftAuthMethod.CERTIFICATE))
def test_auth_method_comes_from_the_credential(_build: MagicMock) -> None:
    assert fake_gateway().get_auth_method() is MicrosoftAuthMethod.CERTIFICATE


class _ContextRecorder:
    """Stands in for the REST reads and answers with the context it was
    handed, so a test sees which context a read opened."""

    def __init__(self, rest_context: Callable[[str], Any], _graph: Any, _api: Any):
        self._rest_context = rest_context

    def list_role_assignments(
        self,
        *,
        site_url: str,
        securable: Any,  # noqa: ARG002
        max_rows: int | None = None,  # noqa: ARG002
    ) -> Any:
        return self._rest_context(site_url)


class TestRestContext:
    """One REST context per site, rebuilt once its token could be stale, with
    a fresh MSAL app each time so the token is fresh too."""

    def _context_for(self, gateway: SharepointSourceOperations, site_url: str) -> Any:
        return gateway.list_role_assignments(
            site_url=site_url,
            securable=SharepointSecurable(kind=SharepointSecurableKind.SITE),
        )

    def _gateway(self) -> SharepointSourceOperations:
        return fake_gateway(sites=[SITE_URL, OTHER_SITE_URL])

    @patch.object(gateway_module, "SharepointRestReads", _ContextRecorder)
    @patch(AUTH_BUILDER, return_value=_auth_context(MicrosoftAuthMethod.CERTIFICATE))
    @patch.object(gateway_module, "acquire_token_for_rest")
    @patch.object(gateway_module, "ClientContext")
    def test_the_context_is_reused_within_the_max_age(
        self, context_class: MagicMock, _acquire: MagicMock, _build: MagicMock
    ) -> None:
        context_class.side_effect = lambda _url: MagicMock()
        gateway = self._gateway()

        first = self._context_for(gateway, SITE_URL)

        assert self._context_for(gateway, SITE_URL) is first
        assert context_class.call_count == 1

    @patch.object(gateway_module, "SharepointRestReads", _ContextRecorder)
    @patch(AUTH_BUILDER, return_value=_auth_context(MicrosoftAuthMethod.CERTIFICATE))
    @patch.object(gateway_module, "acquire_token_for_rest")
    @patch.object(gateway_module, "ClientContext")
    def test_a_site_change_opens_another_context(
        self, context_class: MagicMock, _acquire: MagicMock, _build: MagicMock
    ) -> None:
        context_class.side_effect = lambda _url: MagicMock()
        gateway = self._gateway()

        assert self._context_for(gateway, SITE_URL) is not self._context_for(
            gateway, OTHER_SITE_URL
        )
        assert [call.args[0] for call in context_class.call_args_list] == [
            SITE_URL,
            OTHER_SITE_URL,
        ]

    @patch.object(gateway_module, "SharepointRestReads", _ContextRecorder)
    @patch(AUTH_BUILDER, return_value=_auth_context(MicrosoftAuthMethod.CERTIFICATE))
    @patch.object(gateway_module, "acquire_token_for_rest")
    @patch.object(gateway_module, "ClientContext")
    @patch.object(gateway_module, "time")
    def test_an_aged_context_is_rebuilt_with_a_fresh_msal_app(
        self,
        clock: MagicMock,
        context_class: MagicMock,
        _acquire: MagicMock,
        build: MagicMock,
    ) -> None:
        context_class.side_effect = lambda _url: MagicMock()
        gateway = self._gateway()

        clock.monotonic.return_value = 0.0
        first = self._context_for(gateway, SITE_URL)
        clock.monotonic.return_value = 100.0
        assert self._context_for(gateway, SITE_URL) is first
        clock.monotonic.return_value = REST_CTX_MAX_AGE_S + 1

        assert self._context_for(gateway, SITE_URL) is not first
        assert context_class.call_count == 2
        assert build.call_count == 2

    @patch.object(gateway_module, "SharepointRestReads", _ContextRecorder)
    @patch(AUTH_BUILDER, return_value=_auth_context(MicrosoftAuthMethod.CERTIFICATE))
    @patch.object(gateway_module, "acquire_token_for_rest")
    @patch.object(gateway_module, "ClientContext")
    def test_a_foreign_tenant_never_gets_a_context(
        self, context_class: MagicMock, _acquire: MagicMock, _build: MagicMock
    ) -> None:
        gateway = self._gateway()

        with pytest.raises(ConnectorValidationError, match="tenant's SharePoint host"):
            self._context_for(gateway, "https://victim.sharepoint.com/sites/Payroll")

        context_class.assert_not_called()


@patch.object(gateway_module, "download_via_graph_api", return_value=b"abc")
@patch.object(gateway_module, "download_with_cap")
def test_item_bytes_fall_back_to_graph_when_the_link_is_refused(
    download: MagicMock, graph_download: MagicMock
) -> None:
    download.side_effect = _json_error(403, "accessDenied")
    item = _drive_item_with_link()

    def get_json(url: str, params: dict[str, str] | None) -> dict[str, Any]:  # noqa: ARG001
        raise AssertionError("no Graph call")

    with patch.object(gateway_module.logger, "warning") as warning:
        size = fake_gateway(get_json=get_json).read_item_bytes(
            drive_id="d1", item=item, max_bytes=100
        )

    assert size == 3
    assert "tempauth" not in str(warning.call_args)
    assert graph_download.call_args.args[1:3] == ("d1", "item-1")


def _drive_item_with_link() -> DriveItemData:
    return DriveItemData.from_graph_json(
        {
            "id": "item-1",
            "name": "a.pdf",
            "webUrl": f"{SITE_URL}/a.pdf",
            "@microsoft.graph.downloadUrl": "https://download.example/a?tempauth=secret",
            "parentReference": {"driveId": "d1"},
        }
    )
