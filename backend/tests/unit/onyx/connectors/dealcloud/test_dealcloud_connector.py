from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.dealcloud import connector as dealcloud_connector
from onyx.connectors.dealcloud.config import DealCloudConnectorConfig
from onyx.connectors.dealcloud.connector import DealCloudConnector
from onyx.connectors.dealcloud.models import (
    DealCloudCheckpoint,
    DealCloudEntryType,
    DealCloudField,
    DealCloudRow,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import Document, HierarchyNode, SlimDocument

_BASE_URL = "https://example.dealcloud.com"
_COMPANY = DealCloudEntryType(
    id=2014, api_name="Company", plural_name="Companies", entry_list_type=1
)
_DEAL = DealCloudEntryType(
    id=2020, api_name="Deal", plural_name="Deals", entry_list_type=1
)
_ATTACHMENT = DealCloudEntryType(
    id=2010, api_name="Attachment", plural_name="Attachments", entry_list_type=7
)
_FIELDS: list[DealCloudField] = [
    DealCloudField(
        api_name="CompanyName",
        name="Company Name",
        field_type=1,
        system_field_type=9,
    ),
    DealCloudField(api_name="Sector", name="Sector", field_type=2),
    DealCloudField(api_name="Notes", name="Notes", field_type=1),
    DealCloudField(api_name="Logo", name="Logo", field_type=16),
    DealCloudField(api_name="Watchlist", name="Watchlist", field_type=6),
    DealCloudField(
        api_name="ModifiedDate",
        name="Modified Date",
        field_type=4,
        system_field_type=3,
    ),
    DealCloudField(
        api_name="CreatedBy",
        name="Created By",
        field_type=7,
        system_field_type=2,
    ),
]


def _row(entry_id: int, **values: Any) -> DealCloudRow:
    return DealCloudRow(entry_id=entry_id, values=values)


def _connector(
    site_entry_types: list[DealCloudEntryType], **kwargs: Any
) -> tuple[DealCloudConnector, MagicMock]:
    connector = DealCloudConnector(base_url=f"{_BASE_URL}/", **kwargs)
    ops = MagicMock()
    ops.list_entry_types.return_value = site_entry_types
    ops.list_fields.return_value = _FIELDS
    ops.get_rows.side_effect = lambda entry_type_id, entry_ids: [  # noqa: ARG005
        _row(entry_id) for entry_id in entry_ids
    ]
    connector._ops = ops
    return connector, ops


def _run(
    connector: DealCloudConnector,
    checkpoint: DealCloudCheckpoint,
    start: float = 0,
) -> tuple[list[Document | HierarchyNode], DealCloudCheckpoint]:
    items: list[Document | HierarchyNode] = []
    wrapper = CheckpointOutputWrapper[DealCloudCheckpoint]()
    for document, node, failure, next_checkpoint in wrapper(
        connector.load_from_checkpoint(start, 2_000_000_000, checkpoint)
    ):
        assert failure is None
        if document is not None:
            items.append(document)
        if node is not None:
            items.append(node)
        if next_checkpoint is not None:
            checkpoint = next_checkpoint
    return items, checkpoint


def test_an_entry_becomes_a_document_with_its_fields_as_text() -> None:
    connector, ops = _connector([_COMPANY])
    ops.list_entry_ids.return_value = [7]
    ops.get_rows.side_effect = None
    ops.get_rows.return_value = [
        _row(
            7,
            CompanyName={
                "id": 7,
                "name": "Acme",
                "url": f"{_BASE_URL}/portal/pages/5/reports/3/entries/7",
            },
            Sector=[{"id": 1, "name": "Software"}, {"id": 2, "name": "Health"}],
            Notes="Met the founder",
            Logo={"id": 9, "name": "logo.png"},
            Watchlist=True,
            ModifiedDate="2026-04-26T13:27:34.263Z",
            CreatedBy={"id": 3, "name": "Ada", "url": "mailto:ada@example.com"},
        )
    ]

    items, _ = _run(connector, connector.build_dummy_checkpoint())

    node, document = items
    assert isinstance(node, HierarchyNode)
    assert node.display_name == "Companies"
    assert isinstance(document, Document)
    assert document.id == f"{_BASE_URL}/entries/2014/7"
    assert document.semantic_identifier == "Acme"
    section = document.sections[0]
    assert section.link == f"{_BASE_URL}/portal/pages/5/reports/3/entries/7"
    # The image field has no text, and the name is the title.
    assert section.text == (
        "Sector: Software, Health\n"
        "Notes: Met the founder\n"
        "Watchlist: Yes\n"
        "Created By: Ada"
    )
    assert document.doc_updated_at == datetime(
        2026, 4, 26, 13, 27, 34, 263_000, tzinfo=timezone.utc
    )
    assert document.primary_owners is not None
    assert document.primary_owners[0].email == "ada@example.com"
    assert document.metadata == {"object": "Companies"}
    assert document.parent_hierarchy_raw_node_id == node.raw_node_id


def test_an_entry_without_a_name_or_text_still_has_a_title_and_a_link() -> None:
    connector, ops = _connector([_COMPANY])
    ops.list_entry_ids.return_value = [7]

    items, _ = _run(connector, connector.build_dummy_checkpoint())

    document = items[1]
    assert isinstance(document, Document)
    assert document.semantic_identifier == "Company 7"
    assert document.sections[0].text == "Company 7"
    assert document.sections[0].link == _BASE_URL


def test_the_default_scope_leaves_out_attachments() -> None:
    connector, ops = _connector([_ATTACHMENT, _COMPANY])
    ops.list_entry_ids.return_value = []

    _, checkpoint = _run(connector, connector.build_dummy_checkpoint())

    ops.list_entry_ids.assert_called_once_with(entry_type_id=2014)
    assert checkpoint.has_more is False


def test_the_checkpoint_resumes_inside_an_object_then_moves_to_the_next() -> None:
    connector, ops = _connector([_COMPANY, _DEAL])
    ops.list_entry_ids.side_effect = lambda entry_type_id: (
        [1, 2, 3, 4, 5] if entry_type_id == 2014 else [10]
    )
    walked: list[list[str]] = []
    checkpoint = connector.build_dummy_checkpoint()

    with (
        patch.object(dealcloud_connector, "_ENTRIES_PER_STEP", 4),
        patch.object(dealcloud_connector, "ROW_BATCH_SIZE", 2),
    ):
        while checkpoint.has_more:
            items, checkpoint = _run(connector, checkpoint)
            walked.append([i.id for i in items if isinstance(i, Document)])
            checkpoint = connector.validate_checkpoint_json(
                checkpoint.model_dump_json()
            )

    assert walked == [
        [f"{_BASE_URL}/entries/2014/{n}" for n in (1, 2, 3, 4)],
        [f"{_BASE_URL}/entries/2014/5"],
        [f"{_BASE_URL}/entries/2020/10"],
    ]
    assert [call.kwargs["entry_ids"] for call in ops.get_rows.call_args_list] == [
        [1, 2],
        [3, 4],
        [5],
        [10],
    ]


def test_a_poll_reads_only_the_changed_entries() -> None:
    connector, ops = _connector([_COMPANY])
    ops.list_changed_entry_ids.return_value = [2, 9]
    start = datetime.now(timezone.utc).timestamp() - 3600

    items, _ = _run(connector, connector.build_dummy_checkpoint(), start=start)

    ops.list_entry_ids.assert_not_called()
    assert ops.list_changed_entry_ids.call_args.kwargs["modified_since"] == (
        datetime.fromtimestamp(start, tz=timezone.utc)
    )
    assert [i.id for i in items if isinstance(i, Document)] == [
        f"{_BASE_URL}/entries/2014/2",
        f"{_BASE_URL}/entries/2014/9",
    ]


def test_a_start_older_than_the_change_history_reads_every_entry() -> None:
    connector, ops = _connector([_COMPANY])
    ops.list_entry_ids.return_value = [1]
    start = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()

    _run(connector, connector.build_dummy_checkpoint(), start=start)

    ops.list_changed_entry_ids.assert_not_called()
    ops.list_entry_ids.assert_called_once_with(entry_type_id=2014)


def test_object_names_are_stored_in_one_spelling() -> None:
    """A change of case alone must not read as a change of scope."""
    config = DealCloudConnectorConfig(
        base_url=_BASE_URL, entry_types=[" Deal", "company", "Company", " "]
    )

    assert config.entry_types == ["company", "deal"]


def test_a_queued_object_removed_before_its_turn_is_skipped() -> None:
    connector, ops = _connector([_DEAL])
    ops.list_entry_ids.return_value = [2, 10]
    # The position belongs to the removed object, so the next one starts over.
    checkpoint = DealCloudCheckpoint(
        has_more=True, entry_type_ids=[2014, 2020], last_entry_id=3
    )

    items, checkpoint = _run(connector, checkpoint)

    assert [i.id for i in items if isinstance(i, Document)] == [
        f"{_BASE_URL}/entries/2020/2",
        f"{_BASE_URL}/entries/2020/10",
    ]
    assert checkpoint.has_more is False


def test_the_slim_walk_lists_each_objects_folder_even_when_it_is_empty() -> None:
    """A prune removes a folder the listing leaves out."""
    connector, ops = _connector([_COMPANY, _DEAL])
    ops.list_entry_ids.side_effect = lambda entry_type_id: (
        [1] if entry_type_id == 2014 else []
    )

    items = [item for batch in connector.retrieve_all_slim_docs() for item in batch]

    assert [
        item.raw_node_id if isinstance(item, HierarchyNode) else item.id
        for item in items
    ] == [
        f"{_BASE_URL}/entrytypes/2014",
        f"{_BASE_URL}/entries/2014/1",
        f"{_BASE_URL}/entrytypes/2020",
    ]


def test_slim_walk_lists_every_entry_and_raises_when_stopped() -> None:
    connector, ops = _connector([_COMPANY])
    ops.list_entry_ids.return_value = [1, 2]

    batches = list(connector.retrieve_all_slim_docs())

    assert [
        doc.id for batch in batches for doc in batch if isinstance(doc, SlimDocument)
    ] == [
        f"{_BASE_URL}/entries/2014/1",
        f"{_BASE_URL}/entries/2014/2",
    ]

    callback = MagicMock()
    callback.should_stop.return_value = True
    with pytest.raises(RuntimeError, match="stop signal"):
        list(connector.retrieve_all_slim_docs(callback=callback))


def test_a_step_that_reads_no_rows_fails_instead_of_indexing_nothing() -> None:
    connector, ops = _connector([_COMPANY])
    ops.list_entry_ids.return_value = [1, 2]
    ops.get_rows.side_effect = None
    ops.get_rows.return_value = []

    with pytest.raises(RuntimeError, match="no rows for 2 listed Company"):
        _run(connector, connector.build_dummy_checkpoint())


def test_a_named_object_that_is_gone_leaves_the_scope() -> None:
    connector, ops = _connector([_COMPANY], entry_types=["Company", "Deal"])
    ops.list_entry_ids.return_value = [1]

    items, checkpoint = _run(connector, connector.build_dummy_checkpoint())

    assert [i.id for i in items if isinstance(i, Document)] == [
        f"{_BASE_URL}/entries/2014/1"
    ]
    assert checkpoint.has_more is False
    assert [
        item.id
        for batch in connector.retrieve_all_slim_docs()
        for item in batch
        if isinstance(item, SlimDocument)
    ] == [f"{_BASE_URL}/entries/2014/1"]


def test_no_named_object_left_fails_both_walks() -> None:
    """The API user probably lost access. Without the error, pruning would
    delete every document."""
    connector, _ = _connector([_COMPANY], entry_types=["Deal", "Fund"])

    with pytest.raises(ConnectorValidationError, match="Deal, Fund"):
        list(connector.retrieve_all_slim_docs())
    with pytest.raises(ConnectorValidationError, match="Deal, Fund"):
        _run(connector, connector.build_dummy_checkpoint())


def test_a_full_walk_applies_the_time_window_to_each_entry() -> None:
    connector, ops = _connector([_COMPANY])
    ops.list_entry_ids.return_value = [1, 2, 3]
    ops.get_rows.side_effect = None
    ops.get_rows.return_value = [
        _row(1, ModifiedDate="2001-01-01T00:00:00Z"),
        _row(2, ModifiedDate="2026-03-01T00:00:00Z"),
        _row(3),
    ]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()

    items, _ = _run(connector, connector.build_dummy_checkpoint(), start=start)

    # The entry without a modified date cannot be placed, so it is kept.
    assert [i.id for i in items if isinstance(i, Document)] == [
        f"{_BASE_URL}/entries/2014/2",
        f"{_BASE_URL}/entries/2014/3",
    ]


def test_a_run_lists_an_objects_entries_and_fields_once() -> None:
    connector, ops = _connector([_COMPANY])
    ops.list_entry_ids.return_value = list(range(1, 10))
    checkpoint = connector.build_dummy_checkpoint()

    with (
        patch.object(dealcloud_connector, "_ENTRIES_PER_STEP", 4),
        patch.object(dealcloud_connector, "ROW_BATCH_SIZE", 2),
    ):
        while checkpoint.has_more:
            _, checkpoint = _run(connector, checkpoint)

    ops.list_entry_ids.assert_called_once_with(entry_type_id=2014)
    ops.list_fields.assert_called_once_with(entry_type_id=2014)
    assert ops.get_rows.call_count == 5


def test_an_entry_modified_after_the_window_is_left_for_a_later_run() -> None:
    connector, ops = _connector([_COMPANY])
    ops.list_changed_entry_ids.return_value = [1, 2]
    now = datetime.now(timezone.utc)
    ops.get_rows.side_effect = None
    ops.get_rows.return_value = [
        _row(1, ModifiedDate=(now - timedelta(minutes=30)).isoformat()),
        _row(2, ModifiedDate=now.isoformat()),
    ]
    wrapper = CheckpointOutputWrapper[DealCloudCheckpoint]()

    documents = [
        document
        for document, _, _, _ in wrapper(
            connector.load_from_checkpoint(
                (now - timedelta(hours=1)).timestamp(),
                (now - timedelta(minutes=1)).timestamp(),
                connector.build_dummy_checkpoint(),
            )
        )
        if isinstance(document, Document)
    ]

    assert [document.id for document in documents] == [f"{_BASE_URL}/entries/2014/1"]


def test_the_scope_is_listed_once_per_run() -> None:
    connector, ops = _connector([_COMPANY, _DEAL])
    ops.list_entry_ids.return_value = [1]
    checkpoint = connector.build_dummy_checkpoint()

    while checkpoint.has_more:
        _, checkpoint = _run(connector, checkpoint)

    ops.list_entry_types.assert_called_once_with()


def test_validation_before_a_run_accepts_what_the_run_accepts() -> None:
    connector, _ = _connector([_COMPANY], entry_types=["company", "Deal"])

    connector.validate_connector_settings()

    gone, _ = _connector([_COMPANY], entry_types=["Fund", "Deal"])
    with pytest.raises(ConnectorValidationError, match="Deal, Fund"):
        gone.validate_connector_settings()
