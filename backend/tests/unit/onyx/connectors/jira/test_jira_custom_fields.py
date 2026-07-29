"""Tests for reading Jira custom fields into the indexed document."""

import time
from typing import Any, cast
from unittest.mock import MagicMock, patch

from jira import JIRA
from jira.resilientsession import ResilientSession
from jira.resources import Issue

from onyx.connectors.jira.connector import JiraConnector, process_jira_issue
from onyx.connectors.jira.custom_fields import (
    JiraFieldMetadata,
    get_custom_field_metadata,
    render_issue_custom_fields,
    render_jira_field_value,
)
from onyx.connectors.models import Document
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector

JIRA_BASE_URL = "https://jira.example.com"

_OPTION = {
    "self": f"{JIRA_BASE_URL}/rest/api/3/customFieldOption/14764",
    "value": "Heavy",
    "id": "14764",
}


def _make_issue(fields: dict[str, Any], key: str = "DI-1") -> Issue:
    """Build an Issue the same way the connector does, from a raw API payload."""
    raw = {
        "id": "1",
        "key": key,
        "fields": {
            "summary": "Podgrywka 20.06.2026",
            "description": "Na środowiska: prod",
            "created": "2026-06-12T14:14:43.272+0200",
            "updated": "2026-07-10T10:32:53.883+0200",
            "labels": [],
            "comment": {"comments": []},
            **fields,
        },
    }
    # The payload is complete, so the session is never used for lazy loading.
    return Issue({"server": JIRA_BASE_URL}, ResilientSession(), raw=raw)


def _metadata(
    field_id: str, name: str, custom_type: str | None = None
) -> dict[str, JiraFieldMetadata]:
    return {
        field_id: JiraFieldMetadata(id=field_id, name=name, custom_type=custom_type)
    }


# --------------------------------------------------------------------------
# Value rendering
# --------------------------------------------------------------------------


def test_render_scalar_values() -> None:
    assert render_jira_field_value(None) == ""
    assert render_jira_field_value("  do 2h  ") == "do 2h"
    assert render_jira_field_value(5) == "5"
    assert render_jira_field_value(2.5) == "2.5"
    # bool subclasses int, so it must be checked first.
    assert render_jira_field_value(True) == "yes"
    assert render_jira_field_value(False) == "no"


def test_render_select_option_and_user_and_sprint() -> None:
    assert render_jira_field_value(_OPTION) == "Heavy"
    assert (
        render_jira_field_value(
            {"accountId": "123", "displayName": "Adam Serafin", "active": True}
        )
        == "Adam Serafin"
    )
    assert (
        render_jira_field_value(
            [{"id": 14890, "name": "DevOps June '26", "state": "closed"}]
        )
        == "DevOps June '26"
    )


def test_render_cascading_select() -> None:
    value = {"value": "Backend", "child": {"value": "Payments"}}
    assert render_jira_field_value(value) == "Backend - Payments"


def test_render_multi_select_joins_with_commas() -> None:
    value = [{"value": "Ring 9"}, {"value": "Ring 10"}]
    assert render_jira_field_value(value) == "Ring 9, Ring 10"


def test_render_list_of_multiline_values_joins_with_newlines() -> None:
    value = ["first\nsecond", "third"]
    assert render_jira_field_value(value) == "first\nsecond\nthird"


def test_render_adf_rich_text_field() -> None:
    value = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": "CRM"}],
            },
            {"type": "paragraph", "content": [{"type": "text", "text": "deploy it"}]},
        ],
    }
    assert render_jira_field_value(value) == "# CRM\ndeploy it"


def test_render_adf_fragment_without_doc_wrapper() -> None:
    value = {
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "inner"}]}
        ]
    }
    assert render_jira_field_value(value) == "inner"


def test_reference_only_objects_are_omitted() -> None:
    """Opaque plugin/reference objects must not be dumped into the index."""
    assert render_jira_field_value({"self": f"{JIRA_BASE_URL}/x", "id": "10001"}) == ""
    assert render_jira_field_value({}) == ""
    assert render_jira_field_value([]) == ""
    assert render_jira_field_value([None, "", {}]) == ""


# --------------------------------------------------------------------------
# Field metadata
# --------------------------------------------------------------------------


def test_noise_field_types_are_flagged() -> None:
    noise_types = [
        "com.pyxis.greenhopper.jira:gh-lexo-rank",
        "com.atlassian.jira.ext.charting:timeinstatus",
        "com.atlassian.jira.plugins.jira-development-integration-plugin:devsummary",
        "com.atlassian.servicedesk:sd-sla-field",
        "com.atlassian.jpo:jpo-custom-field-baseline-start",
    ]
    for custom_type in noise_types:
        metadata = JiraFieldMetadata(
            id="customfield_1", name="x", custom_type=custom_type
        )
        assert metadata.is_noise, custom_type

    for custom_type in [None, "com.pyxis.greenhopper.jira:gh-sprint"]:
        metadata = JiraFieldMetadata(
            id="customfield_1", name="x", custom_type=custom_type
        )
        assert not metadata.is_noise, custom_type


def test_get_custom_field_metadata_keeps_only_custom_fields() -> None:
    client = MagicMock(spec=JIRA)
    client.fields.return_value = [
        {"id": "summary", "name": "Summary", "custom": False},
        {
            "id": "customfield_13290",
            "name": "Co podgrywamy?",
            "custom": True,
            "schema": {"type": "doc", "custom": "...:textarea", "customId": 13290},
        },
        # Some deployments return a custom field with no schema at all.
        {"id": "customfield_99", "name": "Legacy", "custom": True},
    ]

    metadata = get_custom_field_metadata(client)

    assert set(metadata) == {"customfield_13290", "customfield_99"}
    assert metadata["customfield_13290"].name == "Co podgrywamy?"
    assert metadata["customfield_13290"].custom_type == "...:textarea"
    assert metadata["customfield_99"].custom_type is None


# --------------------------------------------------------------------------
# Per-issue rendering
# --------------------------------------------------------------------------


def test_fields_are_rendered_in_name_order() -> None:
    """Stable ordering keeps re-indexing an unchanged issue a no-op."""
    issue = _make_issue(
        {
            "customfield_2": {"value": "do 2h"},
            "customfield_1": {"value": "Heavy"},
        }
    )
    metadata = {
        **_metadata("customfield_1", "Typ podgrywki"),
        **_metadata("customfield_2", "Planowany downtime"),
    }

    rendered = render_issue_custom_fields(issue, metadata, max_bytes=10_000)

    assert rendered == "Planowany downtime: do 2h\nTyp podgrywki: Heavy"


def test_multiline_values_get_their_own_line() -> None:
    issue = _make_issue({"customfield_1": "line one\nline two"})
    rendered = render_issue_custom_fields(
        issue, _metadata("customfield_1", "Notes"), max_bytes=10_000
    )
    assert rendered == "Notes:\nline one\nline two"


def test_noise_and_unknown_and_empty_fields_are_skipped() -> None:
    issue = _make_issue(
        {
            "customfield_rank": "1|i0aps7:",
            "customfield_unknown": "no metadata for this one",
            "customfield_empty": None,
            "customfield_keep": {"value": "Ring 9"},
        }
    )
    metadata = {
        **_metadata(
            "customfield_rank", "Rank", "com.pyxis.greenhopper.jira:gh-lexo-rank"
        ),
        **_metadata("customfield_empty", "Empty"),
        **_metadata("customfield_keep", "Rings"),
    }

    assert (
        render_issue_custom_fields(issue, metadata, max_bytes=10_000) == "Rings: Ring 9"
    )


def test_rendering_is_capped_at_the_byte_budget() -> None:
    issue = _make_issue({"customfield_1": "x" * 500})
    metadata = _metadata("customfield_1", "Long")

    rendered = render_issue_custom_fields(issue, metadata, max_bytes=20)

    assert len(rendered.encode("utf-8")) == 20
    assert rendered.startswith("Long: xxx")


def test_no_budget_renders_nothing() -> None:
    issue = _make_issue({"customfield_1": "value"})
    metadata = _metadata("customfield_1", "Field")

    assert render_issue_custom_fields(issue, metadata, max_bytes=0) == ""


def test_byte_budget_never_splits_a_multibyte_character() -> None:
    issue = _make_issue({"customfield_1": "ą" * 50})
    metadata = _metadata("customfield_1", "Pole")

    # "Pole: " is 6 bytes, so an odd budget lands mid-character.
    rendered = render_issue_custom_fields(issue, metadata, max_bytes=13)

    assert rendered == "Pole: ąąą"
    assert len(rendered.encode("utf-8")) == 12


def test_single_oversized_field_is_truncated() -> None:
    issue = _make_issue({"customfield_1": "y" * 25_000})
    metadata = _metadata("customfield_1", "Huge")

    rendered = render_issue_custom_fields(issue, metadata, max_bytes=100_000)

    assert rendered.endswith(" [truncated]")
    assert len(rendered) < 25_000


# --------------------------------------------------------------------------
# Document assembly
# --------------------------------------------------------------------------


def test_content_is_unchanged_when_custom_fields_are_not_requested() -> None:
    """Default behaviour must stay byte-identical for existing connectors."""
    issue = _make_issue(
        {
            "description": "The description",
            "comment": {"comments": [{"body": "first"}, {"body": "second"}]},
            "customfield_1": {"value": "Heavy"},
        }
    )

    document = process_jira_issue(jira_base_url=JIRA_BASE_URL, issue=issue)

    assert document is not None
    assert document.sections[0].text == (
        "The description\nComment: first\nComment: second"
    )


def test_custom_fields_are_inserted_between_description_and_comments() -> None:
    issue = _make_issue(
        {
            "description": "The description",
            "comment": {"comments": [{"body": "first"}]},
            "customfield_1": {"value": "Heavy"},
        }
    )

    document = process_jira_issue(
        jira_base_url=JIRA_BASE_URL,
        issue=issue,
        custom_field_metadata=_metadata("customfield_1", "Typ podgrywki"),
    )

    assert document is not None
    assert document.sections[0].text == (
        "The description\nTyp podgrywki: Heavy\nComment: first"
    )


def test_trailing_newline_is_kept_when_there_are_no_comments() -> None:
    issue = _make_issue({"description": "Only a description"})

    document = process_jira_issue(jira_base_url=JIRA_BASE_URL, issue=issue)

    assert document is not None
    assert document.sections[0].text == "Only a description\n"


def test_rich_text_custom_field_table_reaches_the_document() -> None:
    """The deployment tables that live in custom fields are the point of this."""
    table = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableHeader",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {"type": "text", "text": "Service"}
                                        ],
                                    }
                                ],
                            },
                            {
                                "type": "tableHeader",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "Branch"}],
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableCell",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {"type": "text", "text": "auth-mtr"}
                                        ],
                                    }
                                ],
                            },
                            {
                                "type": "tableCell",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {"type": "text", "text": "release_1_6_2"}
                                        ],
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ],
    }
    issue = _make_issue({"description": "Deploy", "customfield_13290": table})

    document = process_jira_issue(
        jira_base_url=JIRA_BASE_URL,
        issue=issue,
        custom_field_metadata=_metadata("customfield_13290", "Co podgrywamy?"),
    )

    assert document is not None
    assert document.sections[0].text == (
        "Deploy\n"
        "Co podgrywamy?:\n"
        "| Service | Branch |\n"
        "| --- | --- |\n"
        "| auth-mtr | release_1_6_2 |\n"
    )


def test_adf_description_keeps_its_structure() -> None:
    """Cloud descriptions arrive as ADF, not as a string."""
    issue = _make_issue(
        {
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Na środowiska:"}],
                    },
                    {
                        "type": "bulletList",
                        "content": [
                            {
                                "type": "listItem",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "maven"}],
                                    }
                                ],
                            },
                            {
                                "type": "listItem",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "gbe"}],
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        }
    )

    document = process_jira_issue(jira_base_url=JIRA_BASE_URL, issue=issue)

    assert document is not None
    assert document.sections[0].text == "Na środowiska:\n- maven\n- gbe\n"


def test_custom_fields_never_push_a_ticket_over_the_size_limit() -> None:
    """A ticket that is indexed today must not start being skipped."""
    issue = _make_issue(
        {"description": "d" * 90, "customfield_1": "big value " * 1_000}
    )

    with patch("onyx.connectors.jira.connector.JIRA_CONNECTOR_MAX_TICKET_SIZE", 100):
        document = process_jira_issue(
            jira_base_url=JIRA_BASE_URL,
            issue=issue,
            custom_field_metadata=_metadata("customfield_1", "Field"),
        )

    assert document is not None
    section_text = document.sections[0].text
    assert section_text is not None
    assert len(section_text.encode("utf-8")) <= 100
    # The description still made it in; only the custom field was cut short.
    assert section_text.startswith("d" * 90)


def _connector_with_one_custom_field(*, include_custom_fields: bool) -> JiraConnector:
    connector = JiraConnector(
        jira_base_url=JIRA_BASE_URL,
        project_key="DI",
        include_custom_fields=include_custom_fields,
    )
    client = MagicMock(spec=JIRA)
    # A MagicMock _options makes the connector take the server (v2) search path.
    client._options = MagicMock()
    client.fields.return_value = [
        {
            "id": "customfield_1",
            "name": "Typ podgrywki",
            "custom": True,
            "schema": {"type": "option", "custom": "...:select"},
        }
    ]
    connector._jira_client = client
    return connector


def test_field_definitions_are_not_fetched_when_disabled() -> None:
    connector = _connector_with_one_custom_field(include_custom_fields=False)

    assert connector._get_custom_field_metadata_for_indexing() is None
    cast(MagicMock, connector.jira_client.fields).assert_not_called()


def test_field_definitions_are_fetched_once_and_reused() -> None:
    connector = _connector_with_one_custom_field(include_custom_fields=True)

    first = connector._get_custom_field_metadata_for_indexing()
    second = connector._get_custom_field_metadata_for_indexing()

    assert first is not None
    assert set(first) == {"customfield_1"}
    assert second is first
    cast(MagicMock, connector.jira_client.fields).assert_called_once()


def test_custom_fields_reach_documents_through_an_indexing_run() -> None:
    connector = _connector_with_one_custom_field(include_custom_fields=True)
    issue = _make_issue(
        {
            "customfield_1": {"value": "Heavy"},
            "project": {"key": "DI", "name": "Devops & Infrastructure"},
        }
    )
    cast(MagicMock, connector.jira_client.search_issues).return_value = [issue]

    outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    documents = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]
    assert len(documents) == 1
    assert documents[0].sections[0].text == (
        "Na środowiska: prod\nTyp podgrywki: Heavy\n"
    )


def test_oversized_ticket_is_still_skipped() -> None:
    issue = _make_issue({"description": "d" * 200})

    with patch("onyx.connectors.jira.connector.JIRA_CONNECTOR_MAX_TICKET_SIZE", 100):
        document = process_jira_issue(
            jira_base_url=JIRA_BASE_URL,
            issue=issue,
            custom_field_metadata=_metadata("customfield_1", "Field"),
        )

    assert document is None
