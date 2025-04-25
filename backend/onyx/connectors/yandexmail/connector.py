import email
import imaplib
from datetime import datetime
from email.header import decode_header
from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import LoadConnector, PollConnector, GenerateDocumentsOutput, SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError, Document, BasicExpertInfo, TextSection


def clean_text(text: str) -> str:
    """Очистка текста для безопасного использования."""
    return "".join(c if c.isalnum() else "_" for c in text)


class YandexMailConnector(LoadConnector, PollConnector):
    def __init__(self, batch_size: int = 10):
        self.imap_server = "imap.yandex.com"
        self.batch_size = batch_size
        self.connection: imaplib.IMAP4_SSL | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        if "password" not in credentials or "email" not in credentials:
            raise ValueError("Password or email not provided in credentials")

        self.connection = imaplib.IMAP4_SSL(self.imap_server)
        try:
            self.connection.login(credentials['email'], credentials["password"])
            print("success connect")
        except imaplib.IMAP4.error:
            raise ConnectorMissingCredentialError("Invalid credentials for Yandex Mail")

    def _process_emails(self, start: datetime | None = None, end: datetime | None = None) -> GenerateDocumentsOutput:
        if not self.connection:
            raise ConnectorMissingCredentialError("Yandex Mail")

        self.connection.select("inbox")

        search_criteria = []
        if start:
            search_criteria.append(f"SINCE {start.strftime('%d-%b-%Y')}")
        if end:
            search_criteria.append(f"BEFORE {end.strftime('%d-%b-%Y')}")

        if not search_criteria:
            search_query = "ALL"
        else:
            search_query = " ".join(search_criteria)

        status, messages = self.connection.search(None, search_query)
        if status != "OK":
            raise RuntimeError("Failed to retrieve emails")

        email_ids = messages[0].split()
        doc_batch: list[Document] = []

        for email_id in email_ids:
            status, msg_data = self.connection.fetch(email_id, "(RFC822)")
            if status != "OK":
                continue

            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])

                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding or "utf-8")

                    from_ = msg.get("From")
                    people = {BasicExpertInfo(display_name=from_)}

                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode()
                                break
                    else:
                        if msg.get_content_type() == "text/plain":
                            body = msg.get_payload(decode=True).decode()

                    doc_batch.append(
                        Document(
                            id=email_id.decode("utf-8"),
                            sections=[TextSection(link="", text=body)],
                            source=DocumentSource.YANDEX,
                            semantic_identifier=subject,
                            title=subject,
                            primary_owners=list(people),
                            metadata={"from": from_},
                        )
                    )

                    if len(doc_batch) >= self.batch_size:
                        yield doc_batch
                        doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._process_emails()

    def poll_source(self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch) -> GenerateDocumentsOutput:
        start_datetime = datetime.utcfromtimestamp(start)
        end_datetime = datetime.utcfromtimestamp(end)
        return self._process_emails(start_datetime, end_datetime)


if __name__ == "__main__":
    import os

    connector = YandexMailConnector(
    )
    connector.load_credentials({"password": os.environ["YANDEX_PASSWORD"], "email": os.environ["YANDEX_EMAIL"]})

    for batch in connector.load_from_state():
        for document in batch:
            print(document)
