import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.imap.connector import ImapConnector
from tests.daily.connectors.imap.models import EmailDoc
from tests.daily.connectors.utils import (
    load_all_docs_from_checkpoint_connector_with_perm_sync,
)
from tests.daily.connectors.utils import to_documents


@pytest.fixture
def imap_connector() -> ImapConnector:
    host = os.environ.get("IMAP_HOST")
    mailboxes_str = os.environ.get("IMAP_MAILBOXES")
    username = os.environ.get("IMAP_USERNAME")
    password = os.environ.get("IMAP_PASSWORD")

    assert host
    mailboxes = (
        [mailbox.strip() for mailbox in mailboxes_str.split(",") if mailbox]
        if mailboxes_str
        else []
    )

    imap_connector = ImapConnector(
        host=host,
        mailboxes=mailboxes,
    )
    imap_connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            tenant_id=None,
            connector_name=DocumentSource.IMAP,
            credential_json={
                "imap_username": username,
                "imap_password": password,
            },
        )
    )

    return imap_connector


@pytest.mark.parametrize(
    "expected_email_docs",
    [
        [
            EmailDoc(
                subject="Testing",
                recipients=set(["admin@onyx-test.com", "raunak@onyx.app"]),
                body="Hello, testing.",
            ),
            EmailDoc(
                subject="Hello world",
                recipients=set(["admin@onyx-test.com", "r@rabh.io", "raunak@onyx.app"]),
                body='Hello world, this is an email that contains multiple "To" recipients.',
            ),
        ]
    ],
)
def test_imap_connector(
    imap_connector: ImapConnector,
    expected_email_docs: list[EmailDoc],
) -> None:
    actual_email_docs = [
        EmailDoc.from_doc(document=document)
        for document in to_documents(
            iterator=iter(
                load_all_docs_from_checkpoint_connector_with_perm_sync(
                    connector=imap_connector,
                    start=0,
                    end=time.time(),
                )
            )
        )
    ]

    assert actual_email_docs == expected_email_docs
