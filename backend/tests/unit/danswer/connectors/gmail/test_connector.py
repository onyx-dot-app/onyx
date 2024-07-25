import datetime

import pytest
from pytest_mock import MockFixture

from danswer.configs.constants import DocumentSource
from danswer.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from danswer.connectors.gmail.connector import GmailConnector
from danswer.connectors.models import Document


def test_email_to_document() -> None:
    connector = GmailConnector()
    email_id = "18cabedb1ea46b03"
    email_subject = "Danswer Test Subject"
    email_sender = "Google <no-reply@accounts.google.com>"
    email_recipient = "test.mail@gmail.com"
    email_date = "Wed, 27 Dec 2023 15:38:49 GMT"
    email_labels = ["UNREAD", "IMPORTANT", "CATEGORY_UPDATES", "STARRED", "INBOX"]
    full_email = {
        "id": email_id,
        "threadId": email_id,
        "labelIds": email_labels,
        "snippet": "A new sign-in. We noticed a new sign-in to your Google Account. If this was you, you don&#39;t need to do",
        "payload": {
            "partId": "",
            "mimeType": "multipart/alternative",
            "filename": "",
            "headers": [
                {"name": "Delivered-To", "value": email_recipient},
                {"name": "Date", "value": email_date},
                {
                    "name": "Message-ID",
                    "value": "<OhMtIhHwNS1NoOQRSQEWqw@notifications.google.com>",
                },
                {"name": "Subject", "value": email_subject},
                {"name": "From", "value": email_sender},
                {"name": "To", "value": email_recipient},
            ],
            "body": {"size": 0},
            "parts": [
                {
                    "partId": "0",
                    "mimeType": "text/plain",
                    "filename": "",
                    "headers": [
                        {
                            "name": "Content-Type",
                            "value": 'text/plain; charset="UTF-8"; format=flowed; delsp=yes',
                        },
                        {"name": "Content-Transfer-Encoding", "value": "base64"},
                    ],
                    "body": {
                        "size": 9,
                        "data": "dGVzdCBkYXRh",
                    },
                },
                {
                    "partId": "1",
                    "mimeType": "text/html",
                    "filename": "",
                    "headers": [
                        {"name": "Content-Type", "value": 'text/html; charset="UTF-8"'},
                        {
                            "name": "Content-Transfer-Encoding",
                            "value": "quoted-printable",
                        },
                    ],
                    "body": {
                        "size": 9,
                        "data": "dGVzdCBkYXRh",
                    },
                },
            ],
        },
        "sizeEstimate": 12048,
        "historyId": "697762",
        "internalDate": "1703691529000",
    }
    doc = connector._email_to_document(full_email)
    assert type(doc) == Document
    assert doc.source == DocumentSource.GMAIL
    assert doc.title == "Danswer Test Subject"
    assert doc.doc_updated_at == datetime.datetime(
        2023, 12, 27, 15, 38, 49, tzinfo=datetime.timezone.utc
    )
    assert doc.metadata == {
        "labels": email_labels,
        "from": email_sender,
        "to": email_recipient,
        "date": email_date,
        "subject": email_subject,
    }


def test_fetch_mails_from_gmail_empty(mocker: MockFixture) -> None:
    mock_discovery = mocker.patch("danswer.connectors.gmail.connector.discovery")
    mock_discovery.build.return_value.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": []
    }
    connector = GmailConnector()
    connector.creds = mocker.Mock()
    with pytest.raises(StopIteration):
        next(connector.load_from_state())


def test_fetch_mails_from_gmail(mocker: MockFixture) -> None:
    mock_discovery = mocker.patch("danswer.connectors.gmail.connector.discovery")
    email_id = "18cabedb1ea46b03"
    email_subject = "Danswer Test Subject"
    email_sender = "Google <no-reply@accounts.google.com>"
    email_recipient = "test.mail@gmail.com"
    mock_discovery.build.return_value.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": email_id, "threadId": email_id}],
        "nextPageToken": "14473313008248105741",
        "resultSizeEstimate": 201,
    }
    mock_discovery.build.return_value.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "id": email_id,
        "threadId": email_id,
        "labelIds": ["UNREAD", "IMPORTANT", "CATEGORY_UPDATES", "STARRED", "INBOX"],
        "snippet": "A new sign-in. We noticed a new sign-in to your Google Account. If this was you, you don&#39;t need to do",
        "payload": {
            "partId": "",
            "mimeType": "multipart/alternative",
            "filename": "",
            "headers": [
                {"name": "Delivered-To", "value": email_recipient},
                {"name": "Date", "value": "Wed, 27 Dec 2023 15:38:49 GMT"},
                {
                    "name": "Message-ID",
                    "value": "<OhMtIhHwNS1NoOQRSQEWqw@notifications.google.com>",
                },
                {"name": "Subject", "value": email_subject},
                {"name": "From", "value": email_sender},
                {"name": "To", "value": email_recipient},
            ],
            "body": {"size": 0},
            "parts": [
                {
                    "partId": "0",
                    "mimeType": "text/plain",
                    "filename": "",
                    "headers": [
                        {
                            "name": "Content-Type",
                            "value": 'text/plain; charset="UTF-8"; format=flowed; delsp=yes',
                        },
                        {"name": "Content-Transfer-Encoding", "value": "base64"},
                    ],
                    "body": {
                        "size": 9,
                        "data": "dGVzdCBkYXRh",
                    },
                },
                {
                    "partId": "1",
                    "mimeType": "text/html",
                    "filename": "",
                    "headers": [
                        {"name": "Content-Type", "value": 'text/html; charset="UTF-8"'},
                        {
                            "name": "Content-Transfer-Encoding",
                            "value": "quoted-printable",
                        },
                    ],
                    "body": {
                        "size": 9,
                        "data": "dGVzdCBkYXRh",
                    },
                },
            ],
        },
        "sizeEstimate": 12048,
        "historyId": "697762",
        "internalDate": "1703691529000",
    }

    connector = GmailConnector()
    connector.creds = mocker.Mock()
    docs = next(connector.load_from_state())
    assert len(docs) == 1
    doc: Document = docs[0]
    assert type(doc) == Document
    assert doc.id == email_id
    assert doc.title == email_subject
    assert email_recipient in doc.sections[0].text
    assert email_sender in doc.sections[0].text


def test_build_time_range_query() -> None:
    time_range_start = 1703066296.159339
    time_range_end = 1704984791.657404
    query = GmailConnector._build_time_range_query(time_range_start, time_range_end)
    assert query == "after:1703066296 before:1704984791"
    query = GmailConnector._build_time_range_query(time_range_start, None)
    assert query == "after:1703066296"
    query = GmailConnector._build_time_range_query(None, time_range_end)
    assert query == "before:1704984791"
    query = GmailConnector._build_time_range_query(0.0, time_range_end)
    assert query == "before:1704984791"
    query = GmailConnector._build_time_range_query(None, None)
    assert query is None


def test_time_str_to_utc() -> None:
    str_to_dt = {
        "Tue, 5 Oct 2021 09:38:25 GMT": datetime.datetime(
            2021, 10, 5, 9, 38, 25, tzinfo=datetime.timezone.utc
        ),
        "Sat, 24 Jul 2021 09:21:20 +0000 (UTC)": datetime.datetime(
            2021, 7, 24, 9, 21, 20, tzinfo=datetime.timezone.utc
        ),
        "Thu, 29 Jul 2021 04:20:37 -0400 (EDT)": datetime.datetime(
            2021, 7, 29, 8, 20, 37, tzinfo=datetime.timezone.utc
        ),
        "30 Jun 2023 18:45:01 +0300": datetime.datetime(
            2023, 6, 30, 15, 45, 1, tzinfo=datetime.timezone.utc
        ),
        "22 Mar 2020 20:12:18 +0000 (GMT)": datetime.datetime(
            2020, 3, 22, 20, 12, 18, tzinfo=datetime.timezone.utc
        ),
    }
    for strptime, expected_datetime in str_to_dt.items():
        assert time_str_to_utc(strptime) == expected_datetime
