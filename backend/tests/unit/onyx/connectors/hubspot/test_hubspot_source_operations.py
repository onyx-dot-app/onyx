"""The HubSpot gateway turns SDK and REST answers into plain models, builds the
requests HubSpot expects, and reports refusals as HubSpotApiError."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hubspot.crm.associations.v4.models import (
    CollectionResponseMultiAssociatedObjectWithLabelForwardPaging,
    MultiAssociatedObjectWithLabel,
)
from hubspot.crm.deals.exceptions import ApiException as DealsApiException
from hubspot.crm.tickets.models import (
    AssociatedId,
    CollectionResponseAssociatedId,
    CollectionResponseSimplePublicObjectWithAssociationsForwardPaging,
    ForwardPaging,
    NextPage,
    Paging,
    SimplePublicObjectWithAssociations,
)

from onyx.connectors.hubspot.config import HubSpotObjectType
from onyx.connectors.hubspot.models import (
    HubSpotAssociationIds,
    HubSpotPage,
)
from onyx.connectors.hubspot.source_operations import (
    HUBSPOT_PAGE_SIZE,
    PERMITTED_USERS_BATCH_SIZE,
    PERMITTED_USERS_PATH,
    HubSpotApiError,
    HubSpotSourceOperations,
    iter_pages,
)

REQUESTS_GET = "onyx.connectors.hubspot.source_operations.requests.get"
PORTAL = "46399533"
DEAL_HCRN = f"hcrn:{PORTAL}:crm-object:0-3"
START = datetime(2024, 1, 1, tzinfo=timezone.utc)
END = datetime(2024, 2, 1, tzinfo=timezone.utc)
CREATED = datetime(2024, 6, 6, 19, 17, tzinfo=timezone.utc)


def _gateway() -> tuple[HubSpotSourceOperations, MagicMock]:
    provider = MagicMock()
    provider.get_credentials.return_value = {"hubspot_access_token": "token"}
    gateway = HubSpotSourceOperations(credentials_provider=provider)
    client = MagicMock()
    gateway._client = client
    return gateway, client


def _sdk_record(record_id: str, **fields: Any) -> dict[str, Any]:
    return {"id": record_id, "created_at": CREATED, "updated_at": CREATED, **fields}


def _sdk_page(raw: dict[str, Any]) -> MagicMock:
    page = MagicMock()
    page.to_dict.return_value = raw
    return page


def _response(status: int, body: object) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body
    response.headers = {}
    response.text = ""
    return response


def _ms(moment: datetime) -> str:
    return str(int(moment.timestamp() * 1000))


def test_a_listing_keeps_inline_associations_and_whether_hubspot_paged_them() -> None:
    gateway, client = _gateway()
    client.crm.deals.basic_api.get_page.return_value = _sdk_page(
        {
            "results": [
                _sdk_record(
                    "7",
                    properties={"name": "Acme", "domain": None},
                    associations={
                        "contacts": {
                            "results": [{"id": "1"}, {"id": "2"}, {"id": "1"}]
                        },
                        "deals": {
                            "results": [{"id": "9"}],
                            "paging": {"next": {"after": "x"}},
                        },
                    },
                ),
                _sdk_record("8", properties=None),
            ]
        }
    )

    page = gateway.list_records(variant=HubSpotObjectType.DEALS, properties=["p"])

    record, bare = page.items
    assert record.properties == {"name": "Acme", "domain": None}
    assert record.associations == {
        "contacts": HubSpotAssociationIds(ids=["1", "2"], has_more=False),
        "deals": HubSpotAssociationIds(ids=["9"], has_more=True),
    }
    assert record.created_at == CREATED
    assert bare.properties == {} and bare.associations is None
    assert page.next_after is None


def test_real_sdk_objects_parse_the_same_way() -> None:
    gateway, client = _gateway()
    naive = datetime(2024, 6, 6, 19, 17)
    client.crm.tickets.basic_api.get_page.return_value = (
        CollectionResponseSimplePublicObjectWithAssociationsForwardPaging(
            results=[
                SimplePublicObjectWithAssociations(
                    id="1",
                    properties={"subject": "s"},
                    created_at=naive,
                    updated_at=naive,
                    archived=False,
                    associations={
                        "contacts": CollectionResponseAssociatedId(
                            results=[AssociatedId(id="9", type="ticket_to_contact")],
                            paging=Paging(next=NextPage(after="more")),
                        )
                    },
                )
            ],
            paging=ForwardPaging(next=NextPage(after="c2")),
        )
    )
    client.crm.associations.v4.basic_api.get_page.return_value = (
        CollectionResponseMultiAssociatedObjectWithLabelForwardPaging(
            results=[
                MultiAssociatedObjectWithLabel(to_object_id=5, association_types=[])
            ]
        )
    )

    page = gateway.list_records(
        variant=HubSpotObjectType.TICKETS, properties=["subject"]
    )
    associations = gateway.list_associations(
        object_type=HubSpotObjectType.TICKETS, object_id="1", to_object_type="contacts"
    )

    [record] = page.items
    assert record.created_at == naive.replace(tzinfo=timezone.utc)
    assert record.associations == {
        "contacts": HubSpotAssociationIds(ids=["9"], has_more=True)
    }
    assert page.next_after == "c2"
    assert associations == HubSpotPage(items=["5"], next_after=None)


def test_a_listing_passes_the_cursor_and_associations_through() -> None:
    gateway, client = _gateway()
    get_page = client.crm.deals.basic_api.get_page
    get_page.return_value = _sdk_page(
        {"results": [_sdk_record("1")], "paging": {"next": {"after": "c1"}}}
    )

    page = gateway.list_records(variant=HubSpotObjectType.DEALS, properties=["p"])
    gateway.list_records(
        variant=HubSpotObjectType.DEALS,
        properties=["p"],
        associations=[HubSpotObjectType.CONTACTS],
        after="c1",
    )

    assert [r.id for r in page.items] == ["1"]
    assert page.next_after == "c1"
    first, second = get_page.call_args_list
    assert first.kwargs["limit"] == HUBSPOT_PAGE_SIZE
    assert first.kwargs["associations"] is None and first.kwargs["after"] is None
    assert second.kwargs["associations"] == ["contacts"]
    assert second.kwargs["after"] == "c1"


@pytest.mark.parametrize(
    "object_type, modified, modified_before, expected",
    [
        (
            HubSpotObjectType.DEALS,
            "hs_lastmodifieddate",
            END,
            [("GTE", _ms(START)), ("LTE", _ms(END))],
        ),
        (HubSpotObjectType.CONTACTS, "lastmodifieddate", None, [("GTE", _ms(START))]),
    ],
)
def test_a_search_filters_and_sorts_on_the_modified_date(
    object_type: HubSpotObjectType,
    modified: str,
    modified_before: datetime | None,
    expected: list[tuple[str, str]],
) -> None:
    gateway, client = _gateway()
    crm = {
        HubSpotObjectType.DEALS: client.crm.deals,
        HubSpotObjectType.CONTACTS: client.crm.contacts,
    }[object_type]
    do_search = crm.search_api.do_search
    do_search.return_value = _sdk_page({"results": []})

    gateway.search_records(
        variant=object_type,
        properties=["p"],
        modified_after=START,
        modified_before=modified_before,
        after="c1",
    )

    request = do_search.call_args.kwargs["public_object_search_request"]
    [group] = request.filter_groups
    assert [(f.operator, f.value) for f in group.filters] == expected
    assert {f.property_name for f in group.filters} == {modified}
    assert request.sorts == [modified]
    assert request.after == "c1"


def test_a_read_of_more_than_a_page_is_refused_before_the_call() -> None:
    gateway, client = _gateway()

    with pytest.raises(ValueError):
        gateway.read_records(
            variant="deals",
            ids=[str(i) for i in range(HUBSPOT_PAGE_SIZE + 1)],
            properties=["p"],
        )

    client.crm.deals.batch_api.read.assert_not_called()


def test_notes_are_read_through_the_notes_client() -> None:
    gateway, client = _gateway()
    note = MagicMock()
    note.to_dict.return_value = _sdk_record("5", properties={"hs_note_body": "hi"})
    client.crm.objects.notes.batch_api.read.return_value = MagicMock(results=[note])

    [record] = gateway.read_records(variant="notes", ids=["5"], properties=["p"])

    assert record.properties == {"hs_note_body": "hi"}
    request = client.crm.objects.notes.batch_api.read.call_args.kwargs[
        "batch_read_input_simple_public_object_id"
    ]
    assert [i.id for i in request.inputs] == ["5"]


def test_an_sdk_refusal_carries_the_status_and_operation() -> None:
    gateway, client = _gateway()
    client.crm.deals.basic_api.get_page.side_effect = DealsApiException(
        status=403, reason="Forbidden"
    )

    with pytest.raises(HubSpotApiError) as refusal:
        gateway.list_records(variant=HubSpotObjectType.DEALS, properties=["p"])

    assert (refusal.value.status, refusal.value.operation) == (403, "deals listing")


def test_the_credential_is_read_once() -> None:
    provider = MagicMock()
    provider.get_credentials.return_value = {"hubspot_access_token": "token"}
    gateway = HubSpotSourceOperations(credentials_provider=provider)

    with patch(REQUESTS_GET, return_value=_response(404, {})):
        gateway.get_user(user_id=13)
        gateway.get_user(user_id=14)

    provider.get_credentials.assert_called_once()


def test_an_unknown_user_is_none() -> None:
    gateway, _ = _gateway()

    with patch(REQUESTS_GET, return_value=_response(404, {})):
        assert gateway.get_user(user_id=13) is None


def test_viewers_are_asked_for_by_hcrn_and_an_unanswered_record_has_none() -> None:
    gateway, _ = _gateway()
    answer = _response(
        200,
        {
            "resources": {
                f"{DEAL_HCRN}:1": {"crm-object:VIEW": {"permittedUsers": [10, 11]}},
                f"{DEAL_HCRN}:2": {"crm-object:EDIT": {"permittedUsers": [10]}},
            }
        },
    )

    with patch(REQUESTS_GET, return_value=answer) as get:
        viewers = gateway.get_record_viewers(
            portal_id=PORTAL,
            object_type=HubSpotObjectType.DEALS,
            record_ids=["1", "2", "3"],
        )

    assert viewers == {"1": {10, 11}, "2": set(), "3": set()}
    assert get.call_args.args[0].endswith(PERMITTED_USERS_PATH)
    assert get.call_args.kwargs["params"]["resource"] == [
        f"{DEAL_HCRN}:1",
        f"{DEAL_HCRN}:2",
        f"{DEAL_HCRN}:3",
    ]


def test_more_records_than_hubspot_answers_for_is_refused_before_the_call() -> None:
    gateway, _ = _gateway()

    with patch(REQUESTS_GET) as get, pytest.raises(ValueError):
        gateway.get_record_viewers(
            portal_id=PORTAL,
            object_type=HubSpotObjectType.DEALS,
            record_ids=[str(i) for i in range(PERMITTED_USERS_BATCH_SIZE + 1)],
        )

    get.assert_not_called()


def test_a_cursor_walk_stops_at_the_end_and_refuses_to_spin() -> None:
    pages = {
        None: HubSpotPage(items=[1, 2], next_after="a"),
        "a": HubSpotPage(items=[3], next_after=None),
    }
    assert list(iter_pages(lambda after: pages[after], max_pages=5)) == [1, 2, 3]

    stuck = HubSpotPage(items=[1], next_after="a")
    with pytest.raises(RuntimeError, match="stopped moving"):
        list(iter_pages(lambda _after: stuck, max_pages=5))

    endless = HubSpotPage(items=[1], next_after="b")
    with pytest.raises(RuntimeError, match="ran past"):
        list(
            iter_pages(
                lambda after: (
                    endless
                    if after is None
                    else HubSpotPage(items=[1], next_after=f"{after}b")
                ),
                max_pages=3,
            )
        )
