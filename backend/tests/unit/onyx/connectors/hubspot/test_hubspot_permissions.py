"""The HubSpot permission reader asks who may view each record, at most twenty
records per call, and turns the viewer ids into the emails of known users. The
connector's walk hands those out under the ids indexing gives the records."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.access.models import ExternalAccess
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.hubspot.config import HubSpotObjectType
from onyx.connectors.hubspot.connector import HUBSPOT_SEARCH_LIMIT, HubSpotConnector
from onyx.connectors.hubspot.permissions import (
    HUBSPOT_API_BASE,
    PERMITTED_USERS_BATCH_SIZE,
    PERMITTED_USERS_PATH,
    USERS_PATH,
    HubSpotApiError,
    HubSpotPermissionReader,
)
from onyx.connectors.hubspot.rate_limit import HubSpotRateLimiter
from onyx.connectors.models import HierarchyNode, SlimDocument

PERMISSIONS = "onyx.connectors.hubspot.permissions"
CONNECTOR = "onyx.connectors.hubspot.connector"
PORTAL = "46399533"
DEAL_HCRN = f"hcrn:{PORTAL}:crm-object:0-3"


def _response(status: int, body: object) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body
    response.headers = {}
    response.text = ""
    return response


class _FakeHubSpot:
    """Answers GETs by path in order and keeps the query each one carried."""

    def __init__(self, answers: dict[str, list[MagicMock]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(
        self,
        url: str,
        headers: dict[str, str],  # noqa: ARG002
        params: dict[str, object],
        timeout: int,  # noqa: ARG002
    ) -> MagicMock:
        path = url.removeprefix(HUBSPOT_API_BASE)
        self.calls.append((path, params))
        return self.answers[path].pop(0)


def _reader() -> HubSpotPermissionReader:
    return HubSpotPermissionReader("token", PORTAL, HubSpotRateLimiter())


def _view(*user_ids: int) -> dict[str, object]:
    return {"crm-object:VIEW": {"permittedUsers": list(user_ids)}}


def _emails(*emails: str) -> ExternalAccess:
    return ExternalAccess(
        external_user_emails=set(emails),
        external_user_group_ids=set(),
        is_public=False,
    )


def test_viewers_are_asked_for_together_and_an_unanswered_record_gets_none() -> None:
    fake = _FakeHubSpot(
        {
            PERMITTED_USERS_PATH: [
                _response(
                    200,
                    {
                        "resources": {
                            f"{DEAL_HCRN}:1": _view(10, 11),
                            f"{DEAL_HCRN}:2": {
                                "crm-object:EDIT": {"permittedUsers": [10]}
                            },
                        }
                    },
                )
            ]
        }
    )

    with patch(f"{PERMISSIONS}.requests.get", fake.get):
        viewers = _reader().viewers(HubSpotObjectType.DEALS, ["1", "2", "3"])

    assert viewers == {"1": {10, 11}, "2": set(), "3": set()}
    [(_, params)] = fake.calls
    assert params["resource"] == [f"{DEAL_HCRN}:1", f"{DEAL_HCRN}:2", f"{DEAL_HCRN}:3"]


def test_more_records_than_hubspot_accepts_is_refused_before_the_call() -> None:
    too_many = [str(i) for i in range(PERMITTED_USERS_BATCH_SIZE + 1)]
    with pytest.raises(ValueError):
        _reader().viewers(HubSpotObjectType.DEALS, too_many)


def test_access_uses_listed_emails_and_looks_up_the_rest_once() -> None:
    fake = _FakeHubSpot(
        {
            USERS_PATH: [
                _response(
                    200,
                    {
                        "results": [
                            {"id": "10", "email": "Ada@Example.com"},
                            {"id": "11", "email": "bob@example.com"},
                        ]
                    },
                )
            ],
            f"{USERS_PATH}/12": [
                _response(200, {"id": "12", "email": "cy@example.com"})
            ],
            f"{USERS_PATH}/13": [_response(404, {})],
            f"{USERS_PATH}/14": [
                _response(
                    200,
                    {"id": "14", "email": "app-1@appserviceaccount.na2.hubspot.com"},
                )
            ],
        }
    )

    with patch(f"{PERMISSIONS}.requests.get", fake.get):
        reader = _reader()
        first = reader.access_for([10, 12, 13, 14])
        second = reader.access_for([11, 13])

    assert first == _emails("ada@example.com", "cy@example.com")
    assert second == _emails("bob@example.com")
    assert [path for path, _ in fake.calls] == [
        USERS_PATH,
        f"{USERS_PATH}/12",
        f"{USERS_PATH}/13",
        f"{USERS_PATH}/14",
    ]


def test_a_refusal_carries_the_endpoint_and_status() -> None:
    fake = _FakeHubSpot({USERS_PATH: [_response(403, {})]})

    with (
        patch(f"{PERMISSIONS}.requests.get", fake.get),
        pytest.raises(HubSpotApiError) as refusal,
    ):
        _reader().probe_users()

    assert (refusal.value.path, refusal.value.status) == (USERS_PATH, 403)


def _connector() -> HubSpotConnector:
    connector = HubSpotConnector(object_types=["deals"])
    connector._access_token = "token"
    connector._portal_id = PORTAL
    return connector


def _slim(doc: SlimDocument | HierarchyNode) -> SlimDocument:
    assert isinstance(doc, SlimDocument)
    return doc


def _page(record_ids: list[str]) -> MagicMock:
    page = MagicMock()
    page.results = [MagicMock(id=record_id) for record_id in record_ids]
    page.paging = None
    return page


def test_the_walk_yields_document_ids_with_their_viewers_emails() -> None:
    reader = MagicMock()
    reader.viewers.side_effect = lambda _object_type, ids: {i: {int(i)} for i in ids}
    reader.access_for.side_effect = lambda ids: _emails(
        *(f"{i}@example.com" for i in ids)
    )
    sdk = MagicMock()
    sdk.crm.deals.basic_api.get_page.return_value = _page(["1", "2", "3"])

    with (
        patch(f"{CONNECTOR}.HubSpot", return_value=sdk),
        patch(f"{CONNECTOR}.HubSpotPermissionReader", return_value=reader),
        patch(f"{CONNECTOR}._SLIM_BATCH_SIZE", 2),
    ):
        batches = list(_connector().retrieve_all_slim_docs_perm_sync())

    assert [[_slim(doc).id for doc in batch] for batch in batches] == [
        ["hubspot_deal_1", "hubspot_deal_2"],
        ["hubspot_deal_3"],
    ]
    assert _slim(batches[1][0]).external_access == _emails("3@example.com")
    reader.viewers.assert_called_once_with(HubSpotObjectType.DEALS, ["1", "2", "3"])


def test_a_listing_from_a_start_searches_open_ended_with_the_modified_date() -> None:
    sdk = MagicMock()
    sdk.crm.deals.search_api.do_search.return_value = _page(["1"])

    with patch(f"{CONNECTOR}.HubSpot", return_value=sdk):
        [batch] = list(_connector().retrieve_all_slim_docs(start=1_700_000_000))

    assert [_slim(doc).id for doc in batch] == ["hubspot_deal_1"]
    request = sdk.crm.deals.search_api.do_search.call_args.kwargs[
        "public_object_search_request"
    ]
    assert request.properties == ["hs_object_id", "hs_lastmodifieddate"]
    [filter_group] = request.filter_groups
    assert [(f.operator, f.value) for f in filter_group.filters] == [
        ("GTE", "1700000000000")
    ]


def test_a_listing_the_search_cannot_complete_raises_instead_of_shrinking() -> None:
    stuck = "2024-01-01T00:00:00+00:00"
    page = MagicMock()
    page.results = [
        MagicMock(id=str(i), properties={"hs_lastmodifieddate": stuck})
        for i in range(HUBSPOT_SEARCH_LIMIT)
    ]
    page.paging = None
    sdk = MagicMock()
    sdk.crm.deals.search_api.do_search.return_value = page

    with (
        patch(f"{CONNECTOR}.HubSpot", return_value=sdk),
        pytest.raises(RuntimeError, match="did not advance"),
    ):
        list(_connector().retrieve_all_slim_docs(start=1_704_067_200))


def test_the_walk_refreshes_the_heartbeat_per_viewer_call_and_honors_stop() -> None:
    reader = MagicMock()
    reader.viewers.side_effect = lambda _object_type, ids: {i: set() for i in ids}
    reader.access_for.return_value = ExternalAccess.empty()
    sdk = MagicMock()
    sdk.crm.deals.basic_api.get_page.return_value = _page(
        [str(i) for i in range(PERMITTED_USERS_BATCH_SIZE + 1)]
    )
    callback = MagicMock()
    callback.should_stop.side_effect = [False, True]

    with (
        patch(f"{CONNECTOR}.HubSpot", return_value=sdk),
        patch(f"{CONNECTOR}.HubSpotPermissionReader", return_value=reader),
        pytest.raises(RuntimeError, match="Stop signal"),
    ):
        list(_connector().retrieve_all_slim_docs_perm_sync(callback=callback))

    callback.progress.assert_called_once()
    reader.viewers.assert_called_once()


def test_the_prune_listing_carries_ids_only_and_never_asks_for_viewers() -> None:
    sdk = MagicMock()
    sdk.crm.deals.basic_api.get_page.return_value = _page(["1", "2"])

    with (
        patch(f"{CONNECTOR}.HubSpot", return_value=sdk),
        patch(f"{CONNECTOR}.HubSpotPermissionReader") as reader_factory,
    ):
        [batch] = list(_connector().retrieve_all_slim_docs())

    assert [(_slim(doc).id, _slim(doc).external_access) for doc in batch] == [
        ("hubspot_deal_1", None),
        ("hubspot_deal_2", None),
    ]
    reader_factory.assert_not_called()


def test_the_probe_turns_a_refusal_into_insufficient_permissions() -> None:
    reader = MagicMock()
    reader.probe_users.side_effect = HubSpotApiError(USERS_PATH, _response(403, {}))

    with (
        patch(f"{CONNECTOR}.HubSpot"),
        patch(f"{CONNECTOR}.HubSpotPermissionReader", return_value=reader),
        pytest.raises(InsufficientPermissionsError, match=USERS_PATH),
    ):
        _connector().probe_permission_sync_scopes()
