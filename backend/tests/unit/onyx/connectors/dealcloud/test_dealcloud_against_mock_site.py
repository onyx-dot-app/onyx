from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import CapabilityCheckContext
from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.dealcloud import source_operations
from onyx.connectors.dealcloud.capability_checks import (
    build_dealcloud_indexing_checks,
)
from onyx.connectors.dealcloud.connector import DealCloudConnector
from onyx.connectors.dealcloud.models import DealCloudCheckpoint
from onyx.connectors.dealcloud.source_operations import (
    DEALCLOUD_API_KEY,
    DEALCLOUD_CLIENT_ID,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
)
from onyx.connectors.models import Document, HierarchyNode, SlimDocument
from tests.unit.onyx.connectors.dealcloud.dealcloud_mock_site import (
    API_KEY,
    CLIENT_ID,
    SITE_URL,
    MockEntryType,
    MockField,
    MockSite,
    serve,
)

COMPANY_ID = 2014
DEAL_ID = 2020
ATTACHMENT_ID = 2010
_SEEDED_AT = datetime.now(timezone.utc) - timedelta(days=30)


def _fields(first_id: int) -> list[MockField]:
    return [
        MockField(
            id=first_id, api_name="Name", name="Name", field_type=1, system_field_type=9
        ),
        MockField(
            id=first_id + 1,
            api_name="Sector",
            name="Sector",
            field_type=2,
            is_multi_select=True,
        ),
        MockField(id=first_id + 2, api_name="Notes", name="Notes", field_type=1),
        MockField(id=first_id + 3, api_name="Logo", name="Logo", field_type=16),
        MockField(
            id=first_id + 4,
            api_name="ModifiedDate",
            name="Modified Date",
            field_type=4,
            system_field_type=3,
        ),
        MockField(
            id=first_id + 5,
            api_name="CreatedBy",
            name="Created By",
            field_type=7,
            system_field_type=2,
        ),
    ]


def seed_entry(site: MockSite, entry_type_id: int, entry_id: int, at: datetime) -> None:
    site.put_entry(
        entry_type_id,
        entry_id,
        at,
        Name=f"Entry {entry_id}",
        Sector=[{"id": 1, "name": "Software", "seqNumber": 1}],
        Notes=f"Notes for {entry_id}",
        Logo={"id": 9, "name": "logo.png"},
        ModifiedDate=at.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        CreatedBy={
            "id": 10,
            "name": "Ada",
            "url": "mailto:ada@example.com",
            "entryListId": -1,
        },
    )


def seeded_site(companies: int = 7, deals: int = 3) -> MockSite:
    site = MockSite()
    site.add_entry_type(
        MockEntryType(
            id=ATTACHMENT_ID,
            api_name="Attachment",
            plural_name="Attachments",
            entry_list_type=7,
            fields=_fields(100),
        )
    )
    site.add_entry_type(
        MockEntryType(
            id=COMPANY_ID,
            api_name="Company",
            plural_name="Companies",
            fields=_fields(200),
        )
    )
    site.add_entry_type(
        MockEntryType(
            id=DEAL_ID, api_name="Deal", plural_name="Deals", fields=_fields(300)
        )
    )
    for entry_id in range(1, companies + 1):
        seed_entry(site, COMPANY_ID, entry_id, _SEEDED_AT)
    for entry_id in range(1_000_001, 1_000_001 + deals):
        seed_entry(site, DEAL_ID, entry_id, _SEEDED_AT)
    seed_entry(site, ATTACHMENT_ID, 9_000_001, _SEEDED_AT)
    return site


def site_connector(
    entry_types: list[str] | None = None, api_key: str = API_KEY
) -> DealCloudConnector:
    connector = DealCloudConnector(base_url=SITE_URL, entry_types=entry_types)
    connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            None,
            DocumentSource.DEALCLOUD.value,
            {DEALCLOUD_CLIENT_ID: CLIENT_ID, DEALCLOUD_API_KEY: api_key},
        )
    )
    return connector


def index(
    connector: DealCloudConnector, start: float = 0
) -> tuple[list[Document], list[HierarchyNode]]:
    """Runs the connector to the end, through a JSON round trip of the
    checkpoint between calls, as the indexing run does."""
    documents: list[Document] = []
    nodes: list[HierarchyNode] = []
    checkpoint = connector.build_dummy_checkpoint()
    while checkpoint.has_more:
        wrapper = CheckpointOutputWrapper[DealCloudCheckpoint]()
        for document, node, failure, next_checkpoint in wrapper(
            connector.load_from_checkpoint(start, 4_000_000_000, checkpoint)
        ):
            assert failure is None
            if isinstance(document, Document):
                documents.append(document)
            if node is not None:
                nodes.append(node)
            if next_checkpoint is not None:
                checkpoint = connector.validate_checkpoint_json(
                    next_checkpoint.model_dump_json()
                )
    return documents, nodes


@pytest.fixture
def site() -> Iterator[MockSite]:
    mock_site = seeded_site()
    with (
        serve(mock_site),
        patch.object(source_operations, "_MIN_REQUEST_INTERVAL_SECONDS", 0.0),
    ):
        yield mock_site


def test_a_full_index_reads_every_entry_once(site: MockSite) -> None:
    connector = site_connector()

    with (
        patch("onyx.connectors.dealcloud.connector._ENTRIES_PER_STEP", 4),
        patch("onyx.connectors.dealcloud.connector.ROW_BATCH_SIZE", 2),
    ):
        documents, nodes = index(connector)

    assert sorted(document.id for document in documents) == sorted(
        [f"{SITE_URL}/entries/{COMPANY_ID}/{n}" for n in range(1, 8)]
        + [f"{SITE_URL}/entries/{DEAL_ID}/{n}" for n in range(1_000_001, 1_000_004)]
    )
    assert [node.display_name for node in nodes] == ["Companies", "Deals"]
    first = next(d for d in documents if d.id.endswith(f"/{COMPANY_ID}/1"))
    assert first.semantic_identifier == "Entry 1"
    section = first.sections[0]
    assert section.link == f"{SITE_URL}/portal/pages/1/reports/1/entries/1"
    assert section.text == "Sector: Software\nNotes: Notes for 1\nCreated By: Ada"
    assert first.doc_updated_at == _SEEDED_AT.replace(
        microsecond=_SEEDED_AT.microsecond // 1000 * 1000
    )
    assert first.primary_owners is not None
    assert first.primary_owners[0].email == "ada@example.com"
    # One token for the whole run.
    assert site.count("POST", "/api/rest/v1/oauth/token") == 1


def test_a_poll_reads_changed_entries_and_leaves_out_deleted_ones(
    site: MockSite,
) -> None:
    connector = site_connector(entry_types=["company"])
    index(connector)
    last_run = datetime.now(timezone.utc) - timedelta(hours=1)
    now = datetime.now(timezone.utc)
    seed_entry(site, COMPANY_ID, 3, now)
    seed_entry(site, COMPANY_ID, 50, now)
    site.delete_entry(COMPANY_ID, 5, now)
    site.requests.clear()

    documents, _ = index(connector, start=last_run.timestamp())

    assert sorted(document.id for document in documents) == [
        f"{SITE_URL}/entries/{COMPANY_ID}/3",
        f"{SITE_URL}/entries/{COMPANY_ID}/50",
    ]
    assert site.count("GET", f"/api/rest/v4/data/entrydata/{COMPANY_ID}/entries") == 1
    assert (
        site.requests.count(
            ("GET", f"/api/rest/v4/data/entrydata/{COMPANY_ID}/entries/allHistory")
        )
        == 1
    )


def test_the_slim_walk_lists_exactly_the_live_entries(site: MockSite) -> None:
    site.delete_entry(COMPANY_ID, 5, datetime.now(timezone.utc))

    listed = [
        item.id
        for batch in site_connector().retrieve_all_slim_docs()
        for item in batch
        if isinstance(item, SlimDocument)
    ]

    assert sorted(listed) == sorted(
        [f"{SITE_URL}/entries/{COMPANY_ID}/{n}" for n in (1, 2, 3, 4, 6, 7)]
        + [f"{SITE_URL}/entries/{DEAL_ID}/{n}" for n in range(1_000_001, 1_000_004)]
    )


def test_a_token_dropped_mid_run_is_bought_again(site: MockSite) -> None:
    connector = site_connector(entry_types=["Company"])
    connector.ops.list_entry_types()
    site.revoke_tokens()

    documents, _ = index(connector)

    assert len(documents) == 7
    assert site.count("POST", "/api/rest/v1/oauth/token") == 2


def test_a_run_with_a_wrong_api_key_fails_as_an_invalid_credential(
    site: MockSite,  # noqa: ARG001
) -> None:
    with pytest.raises(CredentialInvalidError):
        index(site_connector(api_key="wrong"))


def test_a_named_object_removed_from_the_site_leaves_the_scope(
    site: MockSite,
) -> None:
    connector = site_connector(entry_types=["Company", "Deal"])
    del site.entry_types[DEAL_ID]

    documents, _ = index(connector)

    assert len(documents) == 7
    assert all(f"/{COMPANY_ID}/" in document.id for document in documents)


def test_losing_every_named_object_fails_the_run(site: MockSite) -> None:
    connector = site_connector(entry_types=["Company", "Deal"])
    site.entry_types.clear()

    with pytest.raises(ConnectorValidationError, match="Company, Deal"):
        index(connector)
    with pytest.raises(ConnectorValidationError, match="Company, Deal"):
        list(connector.retrieve_all_slim_docs())


def test_a_site_that_returns_fewer_rows_than_asked_still_indexes_every_entry(
    site: MockSite,
) -> None:
    site.max_rows_per_query = 3

    documents, _ = index(site_connector(entry_types=["Company"]))

    assert sorted(document.id for document in documents) == [
        f"{SITE_URL}/entries/{COMPANY_ID}/{n}" for n in range(1, 8)
    ]
    # The batch of 7, then 3 and 4, then the 4 again as 2 and 2.
    assert site.count("POST", "/api/rest/v4/data/entrydata/rows/query") == 5


def test_a_run_past_the_rate_limit_still_indexes_every_entry(
    site: MockSite,
) -> None:
    site.enforce_rate_limit = True

    # One row query per entry, sent with no pacing, so more than 5 data calls
    # reach the site in one second.
    with (
        patch("onyx.connectors.dealcloud.connector.ROW_BATCH_SIZE", 1),
        patch("onyx.connectors.dealcloud.connector._ENTRIES_PER_STEP", 7),
    ):
        documents, _ = index(site_connector(entry_types=["Company"]))

    assert len(documents) == 7
    assert site.rate_limited >= 1


def test_a_request_with_the_wrong_method_is_refused(site: MockSite) -> None:
    assert site.handle("POST", "/api/rest/v4/schema/entrytypes", {}, None)[0] == 405
    assert (
        site.handle(
            "GET", f"/api/rest/v4/data/entrydata/rows/query/{COMPANY_ID}", {}, None
        )[0]
        == 405
    )


def test_the_indexing_checks_pass_against_the_site(site: MockSite) -> None:  # noqa: ARG001
    connector = site_connector(entry_types=["Company"])
    context = CapabilityCheckContext(
        source=DocumentSource.DEALCLOUD,
        credential_json={},
        connector_specific_config={"base_url": SITE_URL, "entry_types": ["Company"]},
        source_operations=connector.ops,
    )

    for check in build_dealcloud_indexing_checks():
        assert check.run(context) is None, check.check_id
