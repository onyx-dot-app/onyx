"""Behavior of the mock Graph and SharePoint server itself: sign-in, delta,
paging, resource units, throttling, download URLs and the corpus changes."""

import time
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from onyx.connectors.load_all import load_all_from_connector
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftAuthError,
    MicrosoftGraphError,
)
from onyx.connectors.microsoft_utils.models import (
    SharepointSecurable,
    SharepointSecurableKind,
)
from tests.external_dependency_unit.connectors.sharepoint.conftest import (
    GRAPH_BASE,
    MockSharepoint,
)
from tests.integration.mock_services.mock_sharepoint_server.mock_sharepoint.quota import (
    RuTracker,
)
from tests.integration.mock_services.mock_sharepoint_server.mock_sharepoint.settings import (
    QuotaSettings,
)

_GRAPH = "https://graph.microsoft.com"
_SITE_SECURABLE = SharepointSecurable(kind=SharepointSecurableKind.SITE)


def _delta_pages(
    mock: MockSharepoint, first: str, headers: dict[str, str] | None = None
) -> tuple[list[dict[str, Any]], str]:
    """Every item of a delta enumeration, and its delta link."""
    items: list[dict[str, Any]] = []
    link = first
    while True:
        response = mock.graph_get(link, headers=headers)
        assert response.status_code == 200, response.text
        page = response.json()
        items.extend(page["value"])
        if "@odata.nextLink" not in page:
            return items, page["@odata.deltaLink"]
        assert "@odata.deltaLink" not in page
        link = page["@odata.nextLink"]


def _drive_item_ids(mock: MockSharepoint, drive_id: str) -> set[str]:
    summary = mock.summary()
    ids = [
        *summary["supported_file_ids"],
        *summary["unsupported_file_ids"],
        *summary["folder_ids"],
    ]
    return {i for i in ids if mock.describe_file(i)["file"]["drive_id"] == drive_id}


def _app(mock: MockSharepoint, client_id: str | None = None) -> str:
    credentials = mock.credentials()
    return (
        f"{credentials['sp_directory_id']}/{client_id or credentials['sp_client_id']}"
    )


def test_unknown_or_invalid_settings_are_rejected(
    mock_sharepoint: MockSharepoint,
) -> None:
    misspelled = mock_sharepoint.client.patch(
        "/_mock/config", json={"quota": {"ru_per_minutes": 10}}
    )
    corpus_in_config = mock_sharepoint.client.patch(
        "/_mock/config", json={"corpus": {"num_sites": 1}}
    )
    negative_weight = mock_sharepoint.client.post(
        "/_mock/corpus", json={"extension_weights": {"txt": 2, "pdf": -1}}
    )

    assert misspelled.status_code == 400
    assert corpus_in_config.status_code == 400
    assert negative_weight.status_code == 400


@pytest.mark.parametrize("certificate", [False, True])
def test_sign_in_gives_a_token_that_names_the_app(
    mock_sharepoint: MockSharepoint, certificate: bool
) -> None:
    connector = mock_sharepoint.build_connector(certificate=certificate)

    info = connector.ops.check_token()

    assert info.app_id == mock_sharepoint.credentials()["sp_client_id"]
    assert info.app_name == "Onyx mock indexer"
    assert (info.certificate_not_after is not None) == certificate
    assert mock_sharepoint.op_count("login.token") == 1


def test_a_wrong_client_secret_is_refused(mock_sharepoint: MockSharepoint) -> None:
    connector = mock_sharepoint.build_connector()
    connector.load_credentials(
        {**mock_sharepoint.credentials(), "sp_client_secret": "wrong"}
    )

    with pytest.raises(MicrosoftAuthError) as refused:
        connector.ops.check_token()

    assert refused.value.code == "invalid_client"


def test_sharepoint_rest_refuses_a_client_secret_token(
    mock_sharepoint: MockSharepoint,
) -> None:
    site_url = mock_sharepoint.site_urls()[0]
    with_secret = mock_sharepoint.build_connector(sites=[site_url])
    with_certificate = mock_sharepoint.build_connector(
        certificate=True, sites=[site_url]
    )

    with pytest.raises(MicrosoftGraphError) as refused:
        with_secret.ops.list_role_assignments(
            site_url=site_url, securable=_SITE_SECURABLE
        )
    assignments = with_certificate.ops.list_role_assignments(
        site_url=site_url, securable=_SITE_SECURABLE
    )

    assert refused.value.status == 401
    assert assignments


def test_graph_refuses_a_call_with_no_token(mock_sharepoint: MockSharepoint) -> None:
    no_token = mock_sharepoint.client.get("/graph/v1.0/sites/getAllSites")
    sharepoint_token = mock_sharepoint.client.get(
        "/graph/v1.0/sites/getAllSites",
        headers={
            "Authorization": "Bearer "
            + mock_sharepoint.access_token("https://onyxmock.sharepoint.com")
        },
    )

    assert no_token.status_code == 401
    assert no_token.json()["error"]["code"] == "InvalidAuthenticationToken"
    assert sharepoint_token.status_code == 401


def test_delta_pages_end_with_a_delta_link_for_later_changes(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    mock = own_mock_sharepoint
    drive = mock.sites()[0]["drives"][0]
    select = (
        "id,name,file,folder,deleted,parentReference,sharepointIds,content.downloadUrl"
    )

    first = mock.graph_get(
        f"/drives/{drive['id']}/root/delta", params={"$top": "4", "$select": select}
    )
    page = first.json()
    items, delta_link = _delta_pages(mock, page["@odata.nextLink"])
    items = page["value"] + items

    # Each page holds $top items, and each link names the real Graph host.
    assert len(page["value"]) == 4
    assert page["@odata.nextLink"].startswith(
        f"{GRAPH_BASE}/drives/{drive['id']}/root/delta?"
    )
    assert urlsplit(delta_link).path == f"/v1.0/drives/{drive['id']}/root/delta"
    ids = [item["id"] for item in items]
    assert len(ids) == len(set(ids))
    assert set(ids) == _drive_item_ids(mock, drive["id"]) | {drive["root_id"]}
    # $select is honored.
    files = [item for item in items if "file" in item]
    assert all("webUrl" not in item and "size" not in item for item in items)
    assert all("@microsoft.graph.downloadUrl" in item for item in files)
    sharepoint_ids = files[0]["sharepointIds"]
    assert sharepoint_ids["listId"] == drive["list_id"]
    assert set(sharepoint_ids) >= {
        "listItemId",
        "listItemUniqueId",
        "siteId",
        "siteUrl",
        "webId",
    }
    assert files[0]["parentReference"]["path"].startswith(
        f"/drives/{drive['id']}/root:"
    )

    # With no change, the delta link gives no items.
    unchanged, delta_link = _delta_pages(mock, delta_link)
    assert unchanged == []

    # A later change and a later deletion come from the saved delta link.
    touched, deleted = files[0]["id"], files[1]["id"]
    mock.touch([touched])
    mock.delete_file(deleted)
    changed, next_delta_link = _delta_pages(mock, delta_link)
    assert {item["id"] for item in changed} == {touched, deleted}
    tombstone = next(item for item in changed if item["id"] == deleted)
    assert tombstone["deleted"] == {"state": "deleted"}
    assert "file" not in tombstone
    assert _delta_pages(mock, next_delta_link)[0] == []


def test_delta_latest_and_timestamp_tokens(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    mock = own_mock_sharepoint
    drive = mock.sites()[0]["drives"][0]
    path = f"/drives/{drive['id']}/root/delta"
    file_ids = sorted(_drive_item_ids(mock, drive["id"]) & mock.supported_file_ids())

    # `latest` gives no items, only a link for the changes after now.
    latest = mock.graph_get(path, params={"token": "latest"}).json()
    assert latest["value"] == []
    assert "@odata.nextLink" not in latest

    before_touch = time.strftime(
        "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 1)
    )
    mock.touch(file_ids[:2])

    since_latest, _ = _delta_pages(mock, latest["@odata.deltaLink"])
    since_time, _ = _delta_pages(
        mock, f"{path}?token={before_touch}".replace("+", "%2B")
    )
    assert {item["id"] for item in since_latest} == set(file_ids[:2])
    assert {item["id"] for item in since_time} == set(file_ids[:2])


def test_an_expired_delta_token_answers_410_with_a_resync_location(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    mock = own_mock_sharepoint
    drive = mock.sites()[0]["drives"][0]
    path = f"/drives/{drive['id']}/root/delta"
    _, delta_link = _delta_pages(mock, f"{path}?$top=5")

    mock.client.post("/_mock/corpus/expire-delta-tokens").raise_for_status()
    gone = mock.graph_get(delta_link)

    assert gone.status_code == 410
    assert gone.json()["error"]["code"] == "resyncRequired"
    location = gone.headers["location"]
    assert location == f"{GRAPH_BASE}{path}?$top=5"
    # The location starts a full enumeration.
    resynced, _ = _delta_pages(mock, location)
    assert {item["id"] for item in resynced} == (
        _drive_item_ids(mock, drive["id"]) | {drive["root_id"]}
    )
    assert mock.graph_get(path, params={"token": "not-a-token"}).status_code == 410

    # The fault expires each token that starts an incremental read.
    mock.patch_config({"faults": {"expire_delta_tokens": True}})
    assert (
        mock.graph_get(path, params={"token": "2025-01-01T00:00:00+00:00"}).status_code
        == 410
    )
    assert mock.graph_get(path, params={"token": "latest"}).status_code == 200

    # The connector then reads the drive again from its start.
    connector = mock.build_connector(include_site_pages=False)
    mock.reset_stats()
    output = load_all_from_connector(connector, time.time() - 60, time.time())
    assert output.documents == []
    stats = mock.stats()
    assert stats["statuses"]["410"] == len(mock.drive_ids())
    assert stats["ops"]["graph.drive.delta"]["count"] == 2 * len(mock.drive_ids())


def test_hierarchical_sharing_marks_only_the_permission_roots(
    mock_sharepoint: MockSharepoint,
) -> None:
    mock = mock_sharepoint
    drive = next(
        drive
        for site in mock.sites()
        for drive in site["drives"]
        if _drive_item_ids(mock, drive["id"])
        & set(mock.summary()["sharing_link_item_ids"])
    )
    in_drive = _drive_item_ids(mock, drive["id"])
    unique = in_drive & set(mock.summary()["unique_permission_item_ids"])
    with_links = in_drive & set(mock.summary()["sharing_link_item_ids"])
    path = f"/drives/{drive['id']}/root/delta"
    prefer = {"Prefer": "hierarchicalsharing, deltashowremovedasdeleted"}

    response = mock.graph_get(path, headers=prefer)
    hierarchical, _ = _delta_pages(mock, path, headers=prefer)
    plain, _ = _delta_pages(mock, path)

    assert response.headers["preference-applied"] == (
        "deltashowremovedasdeleted, hierarchicalsharing"
    )
    assert unique > with_links
    assert {item["id"] for item in hierarchical if "shared" in item} == (
        unique | {drive["root_id"]}
    )
    assert {item["id"] for item in plain if "shared" in item} == with_links
    assert "preference-applied" not in mock.graph_get(path).headers


def test_children_listing_pages_with_next_links(
    mock_sharepoint: MockSharepoint,
) -> None:
    mock = mock_sharepoint
    drive = mock.sites()[0]["drives"][0]
    link: str | None = f"/drives/{drive['id']}/root/children?$top=2&$select=id,name"
    names: list[str] = []
    pages = 0
    while link:
        page = mock.graph_get(link).json()
        assert len(page["value"]) <= 2
        names.extend(item["name"] for item in page["value"])
        link = page.get("@odata.nextLink")
        assert link is None or link.startswith(f"{GRAPH_BASE}/drives/{drive['id']}/")
        pages += 1

    by_path = mock.graph_get(f"/drives/{drive['id']}/root:/Folder%201:/children")
    folder = mock.graph_get(f"/drives/{drive['id']}/root:/Folder%201").json()

    assert pages > 1
    assert names == sorted(names, key=str.lower)
    assert "Folder 1" in names and "Folder 2" in names
    assert by_path.status_code == 200
    assert folder["folder"]["childCount"] == len(by_path.json()["value"])
    assert folder["webUrl"] == f"{drive['web_url']}/Folder%201"


def test_each_call_uses_the_resource_units_of_its_kind(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    mock = own_mock_sharepoint
    site_url = mock.site_urls()[0]
    drive = mock.sites()[0]["drives"][0]
    file_id = min(_drive_item_ids(mock, drive["id"]) & mock.supported_file_ids())
    item = f"/drives/{drive['id']}/items/{file_id}"
    connector = mock.build_connector(certificate=True, sites=[site_url])
    mock.reset_stats()

    mock.graph_get(f"/drives/{drive['id']}/root/delta")
    mock.graph_get(f"/drives/{drive['id']}/root/delta", params={"token": "latest"})
    mock.graph_get(f"/drives/{drive['id']}/root/children")
    mock.graph_get(item)
    mock.graph_get(f"{item}/permissions")
    mock.graph_get(f"{item}/content")
    mock.graph_get("/sites/getAllSites")
    connector.ops.list_role_assignments(site_url=site_url, securable=_SITE_SECURABLE)

    stats = mock.stats()
    ru = {name: op["ru"] for name, op in stats["ops"].items() if op["ru"]}
    assert ru == {
        "graph.drive.delta": 2 + 1,
        "graph.drive.children": 2,
        "graph.item.get": 1,
        "graph.item.permissions": 5,
        "graph.item.content": 1,
        "graph.sites.list": 1,
        "rest.role_assignments": 2,
    }
    assert stats["ru_by_app"] == {_app(mock): 15}

    # Each app has its own count.
    other = mock.access_token(_GRAPH, client_id="another-client")
    mock.client.get(
        f"/graph/v1.0{item}", headers={"Authorization": f"Bearer {other}"}
    ).raise_for_status()
    assert mock.stats()["ru_by_app"] == {
        _app(mock): 15,
        _app(mock, "another-client"): 1,
    }


@pytest.mark.parametrize(
    ("status", "code"), [(429, "TooManyRequests"), (503, "serviceNotAvailable")]
)
def test_an_app_over_its_budget_is_paused(
    own_mock_sharepoint: MockSharepoint, status: int, code: str
) -> None:
    mock = own_mock_sharepoint
    drive = mock.sites()[0]["drives"][0]
    item = f"/drives/{drive['id']}/root"
    mock.patch_config(
        {
            "quota": {
                "ru_per_minute": 3,
                "retry_after_seconds": 30,
                "throttle_status": status,
            },
            "auth": {"rest_requires_certificate": False},
        }
    )
    mock.reset_stats()

    allowed = [mock.graph_get(item).status_code for _ in range(3)]
    over_budget = mock.graph_get(item)
    in_pause = mock.graph_get("/sites/getAllSites")
    rest_in_pause = mock.client.get(
        "/sharepoint/onyxmock.sharepoint.com/sites/site1/_api/web",
        headers={
            "Authorization": "Bearer "
            + mock.access_token("https://onyxmock.sharepoint.com")
        },
    )
    other = mock.access_token(_GRAPH, client_id="another-client")
    other_app = mock.client.get(
        f"/graph/v1.0{item}", headers={"Authorization": f"Bearer {other}"}
    )

    assert allowed == [200, 200, 200]
    assert over_budget.status_code == status
    assert over_budget.headers["retry-after"] == "30"
    assert over_budget.json()["error"]["code"] == code
    # Each call of the app in the pause is refused, with the time that is left.
    assert in_pause.status_code == status
    assert 1 <= int(in_pause.headers["retry-after"]) <= 30
    assert rest_in_pause.status_code == status
    assert other_app.status_code == 200
    stats = mock.stats()
    assert stats["calls_during_pause"] == {_app(mock): 2}
    assert stats["calls_during_pause_total"] == 2
    assert stats["throttled"] == 3
    assert stats["throttled_by_app"] == {_app(mock): 3}
    # A throttled call also uses its RU: 3 + 1 for Graph, 2 for REST.
    assert stats["ru_by_app"][_app(mock)] == 3 + 1 + 1 + 2


def test_a_pause_ends_after_retry_after() -> None:
    """The tracker takes the time of each call, so the test needs no wait."""
    tracker = RuTracker(
        QuotaSettings(
            ru_per_minute=60,
            window_seconds=1,
            retry_after_seconds=2,
            count_throttled_calls=False,
        )
    )

    first = tracker.consume("app", 1, now=100.0)
    over_budget = tracker.consume("app", 1, now=100.1)
    in_pause = tracker.consume("app", 1, now=100.6)
    other_app = tracker.consume("other", 1, now=100.6)
    after_pause = tracker.consume("app", 1, now=102.2)

    assert first is None
    assert over_budget is not None
    assert (over_budget.scope, over_budget.retry_after) == ("minute", 2)
    assert in_pause is not None
    assert (in_pause.scope, in_pause.retry_after) == ("pause", 2)
    assert other_app is None
    assert after_pause is None


def test_an_expired_download_url_makes_the_connector_use_content(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    mock = own_mock_sharepoint
    drive = mock.sites()[0]["drives"][0]
    file_id = min(_drive_item_ids(mock, drive["id"]) & mock.supported_file_ids())
    item = f"/drives/{drive['id']}/items/{file_id}"

    valid_url = mock.graph_get(item).json()["@microsoft.graph.downloadUrl"]
    mock.patch_config({"faults": {"download_url_ttl_seconds": 0}})
    expired_url = mock.graph_get(item).json()["@microsoft.graph.downloadUrl"]
    mock.reset_stats()

    # The URL needs no Authorization header, and it is on the tenant's host.
    assert urlsplit(valid_url).hostname == "onyxmock.sharepoint.com"
    with httpx.Client() as plain:
        valid = plain.get(_through_mock(mock, valid_url))
        expired = plain.get(_through_mock(mock, expired_url))
    assert valid.status_code == 200 and valid.content
    assert expired.status_code == 401
    mock.patch_config({"faults": {"download_url_expired_status": 403}})
    with httpx.Client() as plain:
        assert plain.get(_through_mock(mock, expired_url)).status_code == 403

    mock.reset_stats()
    connector = mock.build_connector(include_site_pages=False)
    output = load_all_from_connector(connector, 0, time.time())

    files = mock.supported_file_ids()
    assert {document.id for document in output.documents} == files
    stats = mock.stats()
    # Each file: one refused download URL, then /content and its redirect.
    assert stats["ops"]["graph.item.content"]["count"] == len(files)
    assert stats["ops"]["download_url.get"]["errors"] == len(files)
    assert stats["ops"]["download_url.get"]["count"] == 2 * len(files)
    assert stats["item_downloads"] == dict.fromkeys(sorted(files), 1)


def _through_mock(mock: MockSharepoint, url: str) -> str:
    """The mock's own URL for a SharePoint URL, as the redirect builds it."""
    parts = urlsplit(url)
    return f"{mock.url}/sharepoint/{parts.hostname}{parts.path}?{parts.query}"


def test_content_sends_the_bytes_when_the_redirect_is_off(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    mock = own_mock_sharepoint
    created = mock.add_file(
        drive_id=mock.drive_ids()[0], name="Plain.txt", text="plain text"
    )
    item = f"/drives/{created['file']['drive_id']}/items/{created['file']['id']}"

    redirect = mock.graph_get(f"{item}/content")
    mock.patch_config({"faults": {"content_redirect": False}})
    direct = mock.graph_get(f"{item}/content")

    assert redirect.status_code == 302
    assert urlsplit(redirect.headers["location"]).hostname == "onyxmock.sharepoint.com"
    assert direct.status_code == 200
    assert direct.text == "plain text"
    assert mock.stats()["item_downloads"] == {created["file"]["id"]: 1}


def test_a_write_during_a_children_walk_shows_in_a_later_delta(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    mock = own_mock_sharepoint
    drive = mock.sites()[0]["drives"][0]
    saved_cursor = mock.graph_get(
        f"/drives/{drive['id']}/root/delta", params={"token": "latest"}
    ).json()["@odata.deltaLink"]
    hook = mock.write_during_walk(
        drive_id=drive["id"],
        op="children",
        after_calls=1,
        action="create",
        file={"drive_id": drive["id"], "name": "Written Later.txt", "text": "late"},
    )

    # The walk lists the root before the write, and the folders after it.
    root = mock.graph_get(f"/drives/{drive['id']}/root/children").json()["value"]
    walked = [item["name"] for item in root]
    for folder in [item for item in root if "folder" in item]:
        children = mock.graph_get(
            f"/drives/{drive['id']}/items/{folder['id']}/children"
        )
        walked.extend(item["name"] for item in children.json()["value"])
    changed, _ = _delta_pages(mock, saved_cursor)

    fired = mock.walk_hooks()[0]
    assert hook["fired"] is False
    assert fired["fired"] is True and fired["error"] is None
    assert "Written Later.txt" not in walked
    assert [item["name"] for item in changed] == ["Written Later.txt"]
    assert changed[0]["id"] == fired["result_file_id"]


def test_a_corrupt_canvas_fails_the_expanded_page_listing(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    mock = own_mock_sharepoint
    mock.set_corpus({"pages_per_site": 3, "corrupt_canvas_pages_per_site": 1})
    site = mock.sites()[0]
    pages = f"/sites/{site['id']}/pages/microsoft.graph.sitePage"

    expanded = mock.graph_get(pages, params={"$expand": "canvasLayout"})
    listed = mock.graph_get(pages)

    assert expanded.status_code == 400
    assert expanded.json()["error"]["code"] == "invalidRequest"
    assert [page["id"] for page in listed.json()["value"]] == site["page_ids"]
    assert all("canvasLayout" not in page for page in listed.json()["value"])

    # The connector then expands each page by itself, and indexes each one.
    mock.reset_stats()
    connector = mock.build_connector(include_site_documents=False)
    output = load_all_from_connector(connector, 0, time.time())

    assert {document.id for document in output.documents} == mock.page_ids()
    stats = mock.stats()
    sites = len(mock.site_urls())
    assert stats["ops"]["graph.site.pages.list"]["count"] == 2 * sites
    assert stats["ops"]["graph.site.pages.list"]["canvas_expanded"] == sites
    assert stats["ops"]["graph.site.page.get"]["canvas_expanded"] == 3 * sites
    assert stats["ops"]["graph.site.page.get"]["errors"] == sites


def test_a_sharing_link_is_in_the_graph_permissions(
    mock_sharepoint: MockSharepoint,
    ee_permission_sync: None,  # noqa: ARG001
) -> None:
    mock = mock_sharepoint
    scopes: dict[str, str] = {}
    public_by_grant: set[str] = set()
    for item_id in mock.summary()["sharing_link_item_ids"]:
        described = mock.describe_file(item_id)
        scopes[item_id] = described["file"]["sharing_links"][0]["scope"]
        if described["effective_access"]["is_public"]:
            public_by_grant.add(item_id)
        response = mock.graph_get(
            f"/drives/{described['file']['drive_id']}/items/{item_id}/permissions"
        )
        links = [p["link"] for p in response.json()["value"] if "link" in p]
        assert [link["scope"] for link in links] == [scopes[item_id]]
    assert {"anonymous", "organization"} & set(scopes.values())

    mock.reset_stats()
    connector = mock.build_connector(
        certificate=True, treat_sharing_link_as_public=True
    )
    output = load_all_from_connector(
        connector, 0, time.time(), include_permissions=True
    )

    access = {document.id: document.external_access for document in output.documents}
    for item_id, scope in scopes.items():
        item_access = access[item_id]
        assert item_access is not None
        assert item_access.is_public == (
            scope in ("anonymous", "organization") or item_id in public_by_grant
        )
    assert mock.op_count("graph.item.permissions") == len(mock.supported_file_ids())


def test_permission_changes_show_in_the_access_and_in_delta(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    mock = own_mock_sharepoint
    drive = mock.sites()[0]["drives"][0]
    in_drive = _drive_item_ids(mock, drive["id"])
    inheriting = min(
        (in_drive & mock.supported_file_ids())
        - set(mock.summary()["unique_permission_item_ids"])
    )
    user = mock.summary()["user_emails"][0]
    path = f"/drives/{drive['id']}/root/delta"
    prefer = {"Prefer": "hierarchicalsharing, deltashowsharingchanges"}
    _, delta_link = _delta_pages(mock, path, headers=prefer)

    mock.set_permissions(
        item_id=inheriting,
        copy_parent=False,
        grants=[{"principal": {"kind": "user", "key": user}, "role": "read"}],
    )
    changed, delta_link = _delta_pages(mock, delta_link, headers=prefer)
    access = mock.describe_file(inheriting)

    assert access["has_unique_permissions"] is True
    assert access["effective_access"] == {
        "user_emails": [user],
        "group_ids": [],
        "is_public": False,
    }
    assert [item["id"] for item in changed] == [inheriting]
    assert changed[0]["shared"] == {"scope": "users"}
    assert changed[0]["@microsoft.graph.sharedChanged"] == "True"

    before_restore = time.strftime(
        "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 1)
    )
    mock.set_permissions(item_id=inheriting, inherit=True)
    restored, _ = _delta_pages(mock, delta_link, headers=prefer)
    assert mock.describe_file(inheriting)["has_unique_permissions"] is False
    assert [item["id"] for item in restored] == [inheriting]
    # Graph gives an empty facet to an item whose sharing changed to inherited.
    assert restored[0]["shared"] == {}

    # A time cursor shows the same sharing change.
    since_time, _ = _delta_pages(
        mock, f"{path}?token={before_restore}".replace("+", "%2B"), headers=prefer
    )
    by_time = [item for item in since_time if item["id"] == inheriting]
    assert by_time[0]["shared"] == {}
    assert by_time[0]["@microsoft.graph.sharedChanged"] == "True"


def test_stats_count_the_calls_and_reset(mock_sharepoint: MockSharepoint) -> None:
    mock = mock_sharepoint
    token = mock.access_token(_GRAPH)
    mock.client.get(
        "/graph/v1.0/sites/root",
        headers={"Authorization": f"Bearer {token}", "User-Agent": "onyx-test/1.0"},
    ).raise_for_status()
    unknown = mock.graph_get("/sites/root/unknownSegment")

    stats = mock.stats()
    assert unknown.status_code == 400
    assert stats["ops"]["graph.site.get"]["count"] == 1
    assert stats["user_agents"]["onyx-test/1.0"] == 1
    assert stats["unmatched_requests"] == ["GET graph/v1.0/sites/root/unknownSegment"]

    mock.reset_stats()
    cleared = mock.stats()
    assert cleared["requests"] == 0
    assert cleared["ops"] == {}
    assert cleared["ru_by_app"] == {}
    assert cleared["unmatched_requests"] == []


def test_site_reads_page_and_name_the_real_hosts(
    mock_sharepoint: MockSharepoint,
) -> None:
    mock = mock_sharepoint
    summary = mock.summary()
    site = mock.sites()[0]

    web_urls: list[str] = []
    link: str | None = "/sites/getAllSites?$top=2"
    while link:
        page = mock.graph_get(link).json()
        web_urls.extend(entry["webUrl"] for entry in page["value"])
        link = page.get("@odata.nextLink")
        assert link is None or link.startswith(f"{GRAPH_BASE}/sites/getAllSites?")
    root = mock.graph_get("/sites/root").json()
    by_url = mock.graph_get("/sites/onyxmock.sharepoint.com:/sites/site1").json()
    drives = mock.graph_get(
        f"/sites/{site['id']}/drives",
        params={"$select": "id,name,webUrl,driveType", "$expand": "list($select=id)"},
    ).json()["value"]

    # The listing has the personal sites, which the connector leaves out.
    assert summary["personal_site_urls"]
    assert web_urls == summary["site_urls"] + summary["personal_site_urls"]
    connector = mock.build_connector()
    assert [s.url for s in connector.fetch_sites()] == summary["site_urls"]
    assert root["siteCollection"]["hostname"] == "onyxmock.sharepoint.com"
    assert by_url["id"] == site["id"]
    assert [drive["name"] for drive in drives] == ["Documents", "Library 2"]
    assert [
        (drive["id"], drive["webUrl"], drive["list"]["id"]) for drive in drives
    ] == [(d["id"], d["web_url"], d["list_id"]) for d in site["drives"]]
    assert drives[0]["webUrl"].endswith("/sites/site1/Shared%20Documents")
    selected = {"id", "name", "webUrl", "driveType", "list"}
    assert all(set(drive) == selected for drive in drives)


def test_directory_reads_give_the_group_members(
    mock_sharepoint: MockSharepoint,
) -> None:
    mock = mock_sharepoint
    directory = mock.client.get("/_mock/corpus/sites").json()
    users = {user["object_id"]: user for user in directory["users"]}
    groups = {group["id"]: group for group in directory["entra_groups"]}
    parent = next(group for group in groups.values() if group["member_group_ids"])
    nested = [groups[group_id] for group_id in parent["member_group_ids"]]
    connector = mock.build_connector()

    found = connector.ops.find_entra_group_id(display_name=parent["display_name"])
    members = connector.ops.list_entra_group_members(group_id=parent["id"])
    nested_security = connector.ops.list_nested_entra_groups(group_id=parent["id"])
    listed = connector.ops.list_entra_groups(page_size=2)
    transitive = mock.graph_get(f"/groups/{parent['id']}/transitiveMembers").json()
    user = users[parent["member_user_ids"][0]]
    by_name = mock.graph_get(f"/users/{user['user_principal_name']}").json()

    assert found == parent["id"]
    assert {member.id for member in members} == (
        set(parent["member_user_ids"]) | set(parent["member_group_ids"])
    )
    # A distribution list is a member, but it is not a security group.
    assert {group["security_enabled"] for group in nested} == {True, False}
    assert [group.id for group in nested_security] == [
        group["id"] for group in nested if group["security_enabled"]
    ]
    assert len(listed.items) == 2
    assert listed.next_link is not None
    assert listed.next_link.startswith(f"{GRAPH_BASE}/groups?")
    assert {entry["id"] for entry in transitive["value"]} >= {
        user_id for group in nested for user_id in group["member_user_ids"]
    }
    assert by_name["id"] == user["object_id"]
    assert by_name["mail"] == user["email"]
    assert mock.graph_get("/groups/no-such-group/members").status_code == 404
