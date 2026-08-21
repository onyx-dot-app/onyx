from unittest.mock import MagicMock

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.jsm.connector import JsmConnector
from onyx.connectors.jsm.connector import JsmConnectorCheckpoint
from onyx.connectors.models import Document
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector,
)


def _response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def test_load_from_checkpoint_indexes_jsm_requests_and_advances_final_checkpoint() -> (
    None
):
    request_url = (
        "https://example.atlassian.net/servicedesk/customer/portal/17/ITSM-1"
    )
    connector = JsmConnector(
        jira_base_url="https://example.atlassian.net",
        project_key="ITSM",
        batch_size=2,
        comment_batch_size=1,
    )
    connector.load_credentials(
        {
            "jira_user_email": "agent@example.com",
            "jira_api_token": "token",
        }
    )

    connector._session.get = MagicMock()
    get_mock = connector._session.get
    get_mock.side_effect = [
        _response({"id": "17", "projectKey": "ITSM"}),
        _response(
            {
                "values": [
                    {
                        "issueKey": "ITSM-1",
                        "serviceDeskId": "17",
                        "requestTypeId": "88",
                        "createdDate": {"iso8601": "2026-05-01T12:00:00+0000"},
                        "reporter": {
                            "displayName": "Avery Agent",
                            "emailAddress": "avery@example.com",
                        },
                        "requestFieldValues": [
                            {"label": "Summary", "value": "Laptop is broken"},
                            {
                                "label": "Description",
                                "value": {
                                    "type": "doc",
                                    "content": [
                                        {
                                            "type": "paragraph",
                                            "content": [
                                                {
                                                    "type": "text",
                                                    "text": "Screen flickers.",
                                                }
                                            ],
                                        }
                                    ],
                                },
                            },
                        ],
                        "currentStatus": {
                            "status": "Waiting for support",
                            "statusDate": {"iso8601": "2026-05-02T12:00:00+0000"},
                        },
                        "participants": {
                            "values": [
                                {
                                    "displayName": "Pat Participant",
                                    "emailAddress": "pat@example.com",
                                }
                            ]
                        },
                        "_links": {
                            "web": request_url,
                        },
                    }
                ],
                "isLastPage": True,
            }
        ),
        _response(
            {
                "values": [
                    {
                        "author": {
                            "displayName": "Avery Agent",
                            "emailAddress": "avery@example.com",
                        },
                        "createdDate": {"iso8601": "2026-05-02T13:00:00+0000"},
                        "body": "Please try an external monitor.",
                    }
                ],
                "isLastPage": False,
            }
        ),
        _response(
            {
                "values": [
                    {
                        "author": {"displayName": "Pat Participant"},
                        "body": {
                            "type": "doc",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "External monitor works.",
                                        }
                                    ],
                                }
                            ],
                        },
                    }
                ],
                "isLastPage": True,
            }
        ),
    ]

    outputs = load_everything_from_checkpoint_connector(connector, 0, 0)

    assert len(outputs) == 1
    assert outputs[0].next_checkpoint == JsmConnectorCheckpoint(
        offset=1,
        has_more=False,
    )
    assert len(outputs[0].items) == 1

    document = outputs[0].items[0]
    assert isinstance(document, Document)
    assert document.id == request_url
    assert document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert document.semantic_identifier == "ITSM-1: Laptop is broken"
    assert document.doc_updated_at is not None
    assert document.primary_owners is not None
    assert document.primary_owners[0].email == "avery@example.com"
    assert document.metadata == {
        "issue_key": "ITSM-1",
        "service_desk_id": "17",
        "request_type_id": "88",
        "status": "Waiting for support",
        "reporter": "Avery Agent",
        "reporter_email": "avery@example.com",
        "participants": ["Pat Participant"],
        "participant_emails": ["pat@example.com"],
    }
    text = document.sections[0].text
    assert "Summary: Laptop is broken" in text
    assert "Description: Screen flickers." in text
    assert "Comment by Avery Agent at 2026-05-02T13:00:00+0000" in text
    assert "External monitor works." in text

    service_desk_call = get_mock.call_args_list[0]
    assert service_desk_call.args[0].endswith(
        "/rest/servicedeskapi/servicedesk/projectKey:ITSM"
    )

    request_call = get_mock.call_args_list[1]
    assert request_call.args[0].endswith("/rest/servicedeskapi/request")
    assert request_call.kwargs["params"] == {
        "limit": 2,
        "requestOwnership": "ALL_REQUESTS",
        "serviceDeskId": "17",
        "start": 0,
    }

    first_comment_call = get_mock.call_args_list[2]
    second_comment_call = get_mock.call_args_list[3]
    assert first_comment_call.kwargs["params"] == {"limit": 1, "start": 0}
    assert second_comment_call.kwargs["params"] == {"limit": 1, "start": 1}


def test_jsm_connector_does_not_advertise_permission_sync() -> None:
    assert not issubclass(JsmConnector, SlimConnectorWithPermSync)
